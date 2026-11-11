"""Python access to wp_compose.c, the compositor the reTerminal firmware
runs (firmware/painting_frame/wp_compose.c), so previews made here are
pixel-identical to what the panel shows.

The C file is compiled on first use with the system C compiler (`cc`) and
cached here; it's rebuilt automatically whenever the source changes.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
FIRMWARE = HERE.parents[1] / "firmware" / "painting_frame"
SOURCES = [FIRMWARE / "wp_compose.c", FIRMWARE / "wp_compose.h"]

BLEND = {"normal": 0, "multiply": 1}


class Layer(ctypes.Structure):
    _fields_ = [
        ("rgba", ctypes.c_void_p),
        ("growth", ctypes.c_void_p),
        ("enc", ctypes.c_void_p),
        ("enc_mode", ctypes.c_uint8),
        ("enc_growth", ctypes.c_uint8),
        ("solid", ctypes.c_uint8 * 3),
        ("x", ctypes.c_int32), ("y", ctypes.c_int32), ("w", ctypes.c_int32), ("h", ctypes.c_int32),
        ("rows_y0", ctypes.c_int32), ("rows_n", ctypes.c_int32),
        ("amount", ctypes.c_uint16), ("feather", ctypes.c_uint16),
        ("opacity", ctypes.c_uint8), ("blend", ctypes.c_uint8),
    ]


class Tone(ctypes.Structure):
    _fields_ = [
        ("ink_rgb", (ctypes.c_uint8 * 3) * 6),
        ("saturation_q8", ctypes.c_int16),
        ("contrast_q8", ctypes.c_int16),
        ("brightness_q8", ctypes.c_int16),
        ("fit_to_panel", ctypes.c_uint8),
    ]


class Ditherer(ctypes.Structure):
    _fields_ = [("width", ctypes.c_int32),
                ("err_cur", ctypes.c_void_p),
                ("err_next", ctypes.c_void_p)]


def _compiler_attempts():
    """(environment, extra flags) to try in turn. On macOS, toolchains are often
    half-updated (an Xcode that won't launch, or a default SDK newer than the
    linker), so there we try the standalone Command Line Tools and Xcode with
    each installed SDK (the ones matching the running macOS first) before the
    plain default, which can pop up an "install developer tools" dialog."""
    if sys.platform != "darwin":
        yield dict(os.environ), []
        return
    import platform
    major = platform.mac_ver()[0].split(".")[0]
    for dev in (Path("/Library/Developer/CommandLineTools"),
                Path("/Applications/Xcode.app/Contents/Developer")):
        sdk_dir = (dev / "SDKs") if dev.name == "CommandLineTools" else \
            dev / "Platforms/MacOSX.platform/Developer/SDKs"
        if not sdk_dir.exists():
            continue
        env = dict(os.environ, DEVELOPER_DIR=str(dev))
        sdks = sorted(sdk_dir.glob("MacOSX*.sdk"), reverse=True)
        sdks.sort(key=lambda p: not p.name.startswith(f"MacOSX{major}"))
        for sdk in sdks:
            yield env, ["-isysroot", str(sdk)]
    yield dict(os.environ), []


def _build() -> ctypes.CDLL:
    digest = hashlib.sha1(b"".join(p.read_bytes() for p in SOURCES)).hexdigest()[:12]
    ext = ".dylib" if sys.platform == "darwin" else ".so"
    lib = HERE / "build" / f"wp_compose_{digest}{ext}"
    if not lib.exists():
        lib.parent.mkdir(exist_ok=True)
        for old in lib.parent.glob("wp_compose_*"):
            old.unlink()
        # -ffp-contract=off is belt and braces: the code is integer-only
        cmd = ["cc", "-O2", "-shared", "-fPIC", "-ffp-contract=off", "-o", str(lib), str(SOURCES[0])]
        for env, extra in _compiler_attempts():
            try:
                subprocess.run(cmd + extra, check=True, env=env, capture_output=True)
                break
            except (OSError, subprocess.CalledProcessError):
                continue
        else:
            raise RuntimeError(
                "Couldn't compile firmware/painting_frame/wp_compose.c. A C compiler is needed once: "
                "on a Mac run `xcode-select --install`; on Linux install gcc.")
    dll = ctypes.CDLL(str(lib))
    dll.wp_compose_rows.argtypes = [ctypes.POINTER(Layer), ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_void_p]
    dll.wp_finish_rows.argtypes = [ctypes.POINTER(Ditherer), ctypes.POINTER(Tone), ctypes.c_void_p,
                                   ctypes.c_int, ctypes.c_void_p]
    dll.wp_ditherer_init.argtypes = [ctypes.POINTER(Ditherer), ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
    return dll


_dll = None


def dll() -> ctypes.CDLL:
    global _dll
    if _dll is None:
        _dll = _build()
    return _dll


def q16(x: float) -> int:
    return max(0, min(65535, round(float(x) * 65535)))


def q8(x: float) -> int:
    return max(0, min(255, round(float(x) * 255)))


def compose(width: int, height: int, background, layers: list[dict]) -> np.ndarray:
    """Stack layers onto a background. Returns the HxWx3 uint8 canvas.

    Each layer dict has x, y, amount, feather, opacity, blend, and either
      rgba (HxWx4 uint8) + growth (HxW uint8 or None), or
      enc (bytes: encoded rows, see wpl.py) + enc_mode, enc_growth, solid, w, h."""
    canvas = np.empty((height, width, 3), np.uint8)
    canvas[:] = np.array(background, np.uint8)
    keep = []  # keep buffers alive during the call
    arr = (Layer * max(1, len(layers)))()
    for i, l in enumerate(layers):
        L = Layer()
        if l.get("enc") is not None:
            buf = ctypes.create_string_buffer(bytes(l["enc"]), len(l["enc"]))
            keep.append(buf)
            L.enc = ctypes.addressof(buf)
            L.enc_mode, L.enc_growth = l["enc_mode"], 1 if l["enc_growth"] else 0
            L.solid[0], L.solid[1], L.solid[2] = l.get("solid", (0, 0, 0))
            w, h = l["w"], l["h"]
        else:
            rgba = np.ascontiguousarray(l["rgba"], dtype=np.uint8)
            growth = None if l.get("growth") is None else np.ascontiguousarray(l["growth"], dtype=np.uint8)
            keep += [rgba, growth]
            L.rgba = rgba.ctypes.data
            L.growth = 0 if growth is None else growth.ctypes.data
            h, w = rgba.shape[:2]
        L.x, L.y, L.w, L.h = l.get("x", 0), l.get("y", 0), w, h
        L.rows_y0, L.rows_n = L.y, h
        L.amount = q16(l.get("amount", 1.0))
        L.feather = max(1, q16(l.get("feather", 0.06)))
        L.opacity = q8(l.get("opacity", 1.0))
        L.blend = BLEND[l.get("blend", "normal")]
        arr[i] = L
    dll().wp_compose_rows(arr, len(layers), 0, height, width, canvas.ctypes.data)
    return canvas


def make_tone(ink_rgb, saturation=1.0, contrast=1.0, brightness=1.0, fit_to_panel=True) -> Tone:
    t = Tone()
    for i, (r, g, b) in enumerate(ink_rgb):
        t.ink_rgb[i][0], t.ink_rgb[i][1], t.ink_rgb[i][2] = r, g, b
    t.saturation_q8 = round(saturation * 256)
    t.contrast_q8 = round(contrast * 256)
    t.brightness_q8 = round(brightness * 256)
    t.fit_to_panel = 1 if fit_to_panel else 0
    return t


def tone_and_dither(rgb: np.ndarray, tone: Tone) -> np.ndarray:
    """HxWx3 uint8 -> HxW ink indices (0..5). Does not modify `rgb`."""
    h, w = rgb.shape[:2]
    work = np.ascontiguousarray(rgb, dtype=np.uint8).copy()
    out = np.empty((h, w), np.uint8)
    a = np.zeros(3 * (w + 2), np.int16)
    b = np.zeros(3 * (w + 2), np.int16)
    d = Ditherer()
    dll().wp_ditherer_init(ctypes.byref(d), w, a.ctypes.data, b.ctypes.data)
    dll().wp_finish_rows(ctypes.byref(d), ctypes.byref(tone), work.ctypes.data, h, out.ctypes.data)
    return out
