#!/usr/bin/env python3
"""Compile and package flash-ready reTerminal E1004 images for the USB installer
and for updates over Wi-Fi.

    python3 tools/prepare_installer.py

The version comes from FW_VERSION in firmware/painting_frame/version.h, so the
installer, the frame's "Check for an update" button, and the firmware itself
always agree. Raise it there before preparing a new release.
"""

import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import struct
import subprocess
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
FQBN = "esp32:esp32:XIAO_ESP32S3:PSRAM=opi"
SKETCH_DIR = ROOT / "firmware" / "painting_frame"
SKETCH = "painting_frame.ino"
PARTS = [
    (0x0, SKETCH + ".bootloader.bin", "bootloader.bin", 0x8000),
    (0x8000, SKETCH + ".partitions.bin", "partitions.bin", 0x1000),
    (0xE000, "boot_app0.bin", "boot_app0.bin", 0x2000),
    (0x10000, SKETCH + ".bin", "firmware.bin", 0x330000),
]


def firmware_version():
    text = (SKETCH_DIR / "version.h").read_text()
    match = re.search(r'#define\s+FW_VERSION\s+"([0-9]+(?:\.[0-9]+)*)"', text)
    if not match:
        raise ValueError("FW_VERSION in version.h should look like \"0.2.0\"")
    return match.group(1)


def validate_images(images):
    """Reject another chip/layout or any write reaching saved-setting sectors."""
    for offset, _, name, maximum in PARTS:
        data = images[name]
        if not data or len(data) > maximum:
            raise ValueError(f"Unexpected size for {name}: {len(data)} bytes")
        # esptool erases whole 4 KB sectors for each part, even without a full erase.
        end = (offset + len(data) + 0xFFF) & ~0xFFF
        if offset < 0xE000 and end > 0x9000:
            raise ValueError(f"{name} would overwrite saved settings")

    for name in ("bootloader.bin", "firmware.bin"):
        data = images[name]
        # chip ID 9 is the ESP32-S3
        if len(data) < 24 or data[0] != 0xE9 or int.from_bytes(data[12:14], "little") != 9:
            raise ValueError(f"{name} is not an ESP32-S3 image")
        # Arduino already patches these fields; Web Serial must not depend on
        # the upload CLI to patch them later.
        if data[2:4] != bytes([2, 0x3F]):
            raise ValueError(f"{name} must already have DIO / 80 MHz / 8 MB flash headers")

    table = images["partitions.bin"]
    found = {}
    md5_checked = False
    for start in range(0, len(table) - 31, 32):
        magic, kind, subtype, offset, size, raw_name, flags = struct.unpack_from("<HBBII16sI", table, start)
        if magic == 0xEBEB:
            if hashlib.md5(table[:start]).digest() != table[start + 16:start + 32]:
                raise ValueError("Partition-table checksum does not match")
            md5_checked = True
            break
        if magic != 0x50AA:
            raise ValueError("Invalid partition table")
        name = raw_name.rstrip(b"\0").decode("ascii")
        if name in found:
            raise ValueError("Duplicate partition name")
        found[name] = (kind, subtype, offset, size, flags)
    expected = {
        "nvs": (1, 2, 0x9000, 0x5000, 0),
        "otadata": (1, 0, 0xE000, 0x2000, 0),
        "app0": (0, 0x10, 0x10000, 0x330000, 0),
        "app1": (0, 0x11, 0x340000, 0x330000, 0),
        "spiffs": (1, 0x82, 0x670000, 0x180000, 0),
        "coredump": (1, 3, 0x7F0000, 0x10000, 0),
    }
    if not md5_checked or found != expected:
        raise ValueError("Partition layout differs from the supported 8 MB layout with Wi-Fi updates")


def main():
    version = firmware_version()
    cli = shutil.which("arduino-cli")
    if not cli:
        raise SystemExit("Arduino CLI is required; see guides/development.md")

    scratch = ROOT / ".arduino"
    scratch.mkdir(exist_ok=True)
    build = scratch / "installer-build"
    source_files = sorted(p for p in SKETCH_DIR.iterdir()
                          if p.suffix in (".ino", ".cpp", ".h", ".c") and p.name != "config.h")
    fingerprint = hashlib.sha256()
    # Compile a staged copy, so a local config.h with someone's Wi-Fi details
    # can never end up in a published image.
    with tempfile.TemporaryDirectory(prefix="installer-source-", dir=scratch) as temporary:
        stage = Path(temporary) / "painting_frame"
        stage.mkdir()
        for source in source_files:
            data = source.read_bytes()
            fingerprint.update(source.name.encode() + b"\0" + data + b"\0")
            (stage / source.name).write_bytes(data)
        subprocess.run([cli, "compile", "--fqbn", FQBN, "--build-path", str(build), str(stage)], check=True)

    # Validate the freshly generated upload plan, not arbitrary pre-existing binaries.
    lines = (build / "flash_args").read_text().splitlines()
    if shlex.split(lines[0]) != ["--flash-mode", "dio", "--flash-freq", "80m", "--flash-size", "8MB"]:
        raise ValueError("Unexpected flash configuration")
    plan = [(int(offset, 0), name) for offset, name in (shlex.split(line) for line in lines[1:] if line.strip())]
    if plan != [(offset, source) for offset, source, _, _ in PARTS]:
        raise ValueError("Unexpected upload offsets or files")
    images = {name: (build / source).read_bytes() for _, source, name, _ in PARTS}
    validate_images(images)
    if version.encode() not in images["firmware.bin"]:
        raise ValueError(f"firmware.bin doesn't contain version {version}")

    manifest = {
        "name": "Weather Painting",
        "version": version,
        "new_install_prompt_erase": True,
        "new_install_improv_wait_time": 0,
        "builds": [{"chipFamily": "ESP32-S3", "parts": [
            {"path": name, "offset": offset} for offset, _, name, _ in PARTS
        ]}],
    }
    info = {
        "version": version,
        "builtAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fqbn": FQBN,
        "sourceSha256": fingerprint.hexdigest(),
        "sourceFiles": [p.name for p in source_files],
        "parts": [{"path": name, "offset": offset, "bytes": len(images[name]),
                   "sha256": hashlib.sha256(images[name]).hexdigest()} for offset, _, name, _ in PARTS],
    }
    output = ROOT / "docs" / "firmware"
    output.mkdir(parents=True, exist_ok=True)
    # Publish the manifest and version.txt last; no output files are touched
    # before validation succeeds. Frames check version.txt for updates over
    # Wi-Fi and then download firmware.bin.
    for name, data in images.items():
        (output / name).write_bytes(data)
    (output / "build-info.json").write_text(json.dumps(info, indent=2) + "\n")
    checksums = "".join(f"{part['sha256']}  {part['path']}\n" for part in info["parts"])
    (output / "SHA256SUMS").write_text(checksums)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (output / "version.txt").write_text(version + "\n")
    print(f"Prepared {version}: four validated ESP32-S3 images in docs/firmware/.")
    print("No frame was flashed and nothing was published.")


if __name__ == "__main__":
    main()
