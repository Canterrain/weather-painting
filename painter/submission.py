"""Check a painting submitted to the gallery and get it ready to release.

    python -m painter submission layers.zip --out out/submission

Reads the PNG layers in the zip, named as in guides/painting.md, checks
them, and writes to --out:

    report.md   what was found and anything wrong, posted on the submission
    release/    the files a frame downloads, side by side (a GitHub release
                can't hold folders, so the frame fetches layers/x.wpl as
                x.wpl), plus cover.jpg and preview.jpg

Exits with status 1 when the painting can't be used; report.md says why.
"""

from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path, PurePosixPath

import numpy as np
import yaml
from PIL import Image, ImageDraw

from . import palette_chart
from .combos import combos
from .moon import growth_maps
from .pipeline import ROOT, load_config, make_frame

STANDARD = ROOT / "painting" / "scene.yaml"
REQUIRED = ("sky_clear.png", "ground_summer.png")
MAX_FILES = 60
MAX_UNZIPPED = 400 * 1024 * 1024
# The cases shown on the preview sheet, from the demo's combinations
PREVIEW = ["summer_clear", "spring_light_rain", "autumn_overcast", "winter_snowing",
           "summer_thunderstorm", "autumn_fog", "winter_after_snow", "summer_night_first_quarter"]


def layer_names(spec: dict) -> set[str]:
    """Every PNG the standard layout uses."""
    names = set()
    for layer in spec.get("layers", []):
        for f in [layer.get("file"), layer.get("reveal")] + [s["file"] for s in layer.get("stages", [])]:
            if f:
                names.add(PurePosixPath(f).name)
    return names


def unpack(zip_path: Path, dest: Path, allowed: set[str], canvas: tuple[int, int]) -> tuple[list[str], list[str]]:
    """Copy the zip's usable layers into dest. Returns (layers found, problems)."""
    problems, found = [], []
    by_lower = {n.lower(): n for n in allowed}
    try:
        z = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        return [], ["The attachment isn't a zip file."]
    with z:
        entries = [i for i in z.infolist() if not i.is_dir()]
        entries = [i for i in entries if not i.filename.startswith("__MACOSX/")
                   and not PurePosixPath(i.filename).name.startswith(".")]
        if len(entries) > MAX_FILES:
            return [], [f"The zip has {len(entries)} files; a painting has at most {len(allowed)}."]
        if sum(i.file_size for i in entries) > MAX_UNZIPPED:
            return [], ["The zip is too large once unpacked."]
        for info in entries:
            base = PurePosixPath(info.filename).name   # folders inside the zip don't matter
            name = by_lower.get(base.lower())
            if not name:
                problems.append(f"`{base}` isn't a layer name from the painting guide, so it was skipped.")
                continue
            if name in found:
                problems.append(f"There's more than one `{name}`.")
                continue
            target = dest / name
            with z.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            try:
                with Image.open(target) as img:   # reads the size without decoding the picture
                    fmt, size = img.format, img.size
            except Exception:
                fmt, size = None, None
            if fmt != "PNG":
                problems.append(f"`{name}` isn't a PNG image.")
            elif size != canvas:
                problems.append(f"`{name}` is {size[0]}×{size[1]}; layers must be {canvas[0]}×{canvas[1]}.")
            else:
                found.append(name)
                continue
            target.unlink()
    return sorted(found), problems


def preview_sheet(cfg: dict) -> tuple[Image.Image, Image.Image]:
    """A cover (summer, clear) and a sheet of several kinds of weather, as the panel shows them."""
    cases = {name: (title, state) for name, title, state in combos()}
    thumbs = []
    cover = None
    for name in PREVIEW:
        title, state = cases[name]
        frame = make_frame(cfg, state)
        if cover is None:
            cover = frame.preview.copy()
            cover.thumbnail((800, 800))
        t = frame.preview.copy()
        t.thumbnail((400, 400))
        thumbs.append((title, t))
    tw, th = thumbs[0][1].size
    cols = 4
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (tw + 16) + 16, rows * (th + 44) + 16), "white")
    d = ImageDraw.Draw(sheet)
    for i, (title, t) in enumerate(thumbs):
        x, y = 16 + (i % cols) * (tw + 16), 16 + (i // cols) * (th + 44)
        sheet.paste(t, (x, y))
        d.text((x, y + th + 6), title, fill="black", font=palette_chart._font(18))
    return cover.convert("RGB"), sheet


def check(zip_path: Path, out: Path) -> bool:
    from .publish import publish

    if out.exists():
        shutil.rmtree(out)
    scene_dir = out / "painting"
    (scene_dir / "layers").mkdir(parents=True)
    spec = yaml.safe_load(STANDARD.read_text())
    shutil.copy(STANDARD, scene_dir / "scene.yaml")
    canvas = tuple(spec.get("canvas", [1600, 1200]))
    allowed = layer_names(spec)

    found, problems = unpack(zip_path, scene_dir / "layers", allowed, canvas)
    missing = [n for n in REQUIRED if n not in found]
    for n in missing:
        problems.append(f"`{n}` is needed, and it's missing.")

    # the moon's phases come from the one painted moon, as on the settings page
    moon = scene_dir / "layers" / "moon.png"
    if moon.exists():
        alpha = np.asarray(Image.open(moon).convert("RGBA"))[:, :, 3]
        if alpha.any():
            for name, g in zip(("moon_waxing_growth.png", "moon_waning_growth.png"), growth_maps(alpha)):
                if name not in found:
                    Image.fromarray(g, "L").save(moon.parent / name)
        else:
            problems.append("`moon.png` is empty: there's no moon painted on it.")

    usable = not missing
    release = out / "release"
    if usable:
        cfg = load_config()
        cfg["scene"] = str(scene_dir)
        built = publish(cfg, out / "build", sorted((ROOT / "scenarios").glob("*.yaml")))
        release.mkdir()
        for f in [built / "manifest.txt", built / "scene.txt"] + sorted((built / "layers").glob("*.wpl")):
            shutil.copy(f, release / f.name)
        cover, sheet = preview_sheet(cfg)
        cover.save(release / "cover.jpg", quality=85)
        sheet.save(release / "preview.jpg", quality=85)

    optional = sorted(allowed - set(found) - {"moon_waxing_growth.png", "moon_waning_growth.png"} - set(REQUIRED))
    lines = ["### Painting check", ""]
    lines.append("✅ This painting can be used." if usable and not problems else
                 "✅ This painting can be used, with the notes below." if usable else
                 "❌ This painting can't be used yet. Fix what's below, then edit the issue to attach a new zip.")
    lines += ["", f"**Layers found ({len(found)}):** " + (", ".join(f"`{n}`" for n in found) or "none")]
    if optional:
        lines += ["", "**Optional layers not included:** " + ", ".join(f"`{n}`" for n in optional)]
    if problems:
        lines += ["", "**Notes:**"] + [f"- {p}" for p in problems]
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return usable


def main(argv: list[str]) -> None:
    import argparse
    p = argparse.ArgumentParser(prog="painter submission")
    p.add_argument("zip")
    p.add_argument("--out", default=str(ROOT / "out" / "submission"))
    args = p.parse_args(argv)
    sys.exit(0 if check(Path(args.zip), Path(args.out)) else 1)


if __name__ == "__main__":
    main(sys.argv[1:])
