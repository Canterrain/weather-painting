"""Publish a scene for reTerminal frames to download.

    python -m painter publish [--scene scene] [--out site]

Writes, under <out>/<scene name>/:

    scene.txt      canvas, inks, tone, and every layer's compiled rules
    layers/*.wpl   encoded layers (see wpl.py)
    manifest.txt   version + size + checksum of every file, so frames only
                   download what changed

Before writing, every compiled rule is checked against the real expression
evaluator for every scenario in scenarios/ and every demo combination, and
the layer decisions the frame will make (decide()) are checked against the
Mac renderer's.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

import numpy as np

from . import epaper, native, rules, wpl
from .combos import combos
from .scene import Scene, load_gray, load_rgba
from .weather import DEFAULT_STATE

STATE_KEYS = set(DEFAULT_STATE)


def _safe(name: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")


def _quantize(x: float, steps: int) -> float:
    x = max(0.0, min(1.0, float(x)))
    return round(x * steps) / steps if steps else x


def to_panel(arr, rotate: int, canvas_wh, offset) -> np.ndarray:
    """Place a layer on the full canvas and turn it onto the portrait panel,
    the same way pipeline.make_frame turns the finished painting (clockwise
    degrees). The frame then composes rows in panel orientation unchanged."""
    w, h = canvas_wh
    full = np.zeros((h, w) + arr.shape[2:], arr.dtype)
    x, y = offset
    full[y:y + arr.shape[0], x:x + arr.shape[1]] = arr
    return np.ascontiguousarray(np.rot90(full, k=-(rotate // 90) % 4))


def wpl_name(png: str, reveal: str | None) -> str:
    """The .wpl file a layer PNG (plus its optional reveal map) becomes."""
    return _safe(Path(png).stem) + (("__" + _safe(Path(reveal).stem)) if reveal else "") + ".wpl"


def compile_scene(scene: Scene, disp: dict, rules_only: bool = False) -> tuple[list[str], dict, list[dict]]:
    """Returns (scene.txt lines, {wpl name: encoded layer}, compiled layer list).
    With rules_only, every layer is kept whether or not its files exist and
    nothing is encoded: the frame's built-in rules for uploaded paintings."""
    encoded: dict[str, dict] = {}
    compiled = []
    rotate = int(disp.get("rotate", 0)) % 360
    if rotate % 90:
        raise SystemExit("display.rotate must be 0, 90, 180 or 270")
    panel_w, panel_h = (scene.height, scene.width) if rotate in (90, 270) else (scene.width, scene.height)
    if (panel_w, panel_h) != (epaper.PANEL_W, epaper.PANEL_H):
        raise SystemExit(f"a {scene.width}x{scene.height} canvas rotated {rotate} doesn't fit the "
                         f"{epaper.PANEL_W}x{epaper.PANEL_H} panel; check canvas and display.rotate")

    def wpl_for(png: str, reveal: str | None, offset) -> str | None:
        name = wpl_name(png, reveal)
        if rules_only:
            return name
        p = scene.folder / png
        if not p.exists():
            return None
        if name not in encoded:
            rgba = load_rgba(p)
            growth = None
            if reveal and (scene.folder / reveal).exists():
                growth = load_gray(scene.folder / reveal)
                if growth.shape != rgba.shape[:2]:
                    growth = None
            canvas = (scene.width, scene.height)
            encoded[name] = wpl.encode(to_panel(rgba, rotate, canvas, offset),
                                       None if growth is None else to_panel(growth, rotate, canvas, offset))
        return name

    for layer in scene.spec.get("layers", []):
        lid = layer.get("id", layer.get("file", "?"))
        offset = layer.get("offset", [0, 0])
        reveal = layer.get("reveal")
        entry = {
            "id": lid,
            "blend": native.BLEND[layer.get("blend", "normal")],
            "steps": int(layer.get("steps", scene.default_steps)),
            "feather": max(1, native.q16(float(layer.get("feather", 0.06)))),
            "has_growth": bool(reveal),
            "when_src": layer.get("when", True), "amount_src": layer.get("amount", 1),
            "opacity_src": layer.get("opacity", 1),
        }
        for key in ("when", "amount", "opacity"):
            entry[key] = rules.compile_expr(entry[f"{key}_src"], STATE_KEYS)
        if "stages" in layer:
            entry["stages"] = []
            for st in layer["stages"]:
                name = wpl_for(st["file"], reveal, offset)
                if name:
                    entry["stages"].append((float(st.get("at", 0)), name))
            if not entry["stages"]:
                continue
        else:
            name = wpl_for(layer["file"], reveal, offset)
            if not name:
                if not layer.get("optional"):
                    print(f"[publish] missing {layer['file']} - layer {lid!r} left out")
                continue
            entry["file"] = name
        compiled.append(entry)

    inks = epaper.palette_rgb(disp.get("palette", "perceived"))
    lines = ["WPS1",
             f"canvas {panel_w} {panel_h}",
             "background " + " ".join(str(c) for c in scene.background),
             "inks " + " ".join(f"{r} {g} {b}" for r, g, b in inks),
             f"tone {round(disp.get('saturation', 1.0) * 256)} {round(disp.get('contrast', 1.0) * 256)} "
             f"{round(disp.get('brightness', 1.0) * 256)} {1 if disp.get('fit_to_panel', True) else 0}"]
    for e in compiled:
        lines.append(f"layer {_safe(e['id'])} {e['blend']} {e['steps']} {e['feather']} {int(e['has_growth'])}")
        if "file" in e:
            lines.append(f"file {e['file']}")
        for at, name in e.get("stages", []):
            lines.append(f"stage {at!r} {name}")
        for key in ("when", "amount", "opacity"):
            lines.append(f"{key} " + " ".join(e[key]))
        lines.append("end")
    return lines, encoded, compiled


def decide(compiled: list[dict], state: dict) -> list[tuple]:
    """The frame's layer decisions: [(id, wpl file, amount, opacity)], same maths as scene.active_layers."""
    out = []
    for e in compiled:
        if not rules._truthy(rules.eval_tokens(e["when"], state)):
            continue
        amount = _quantize(rules.eval_tokens(e["amount"], state), e["steps"])
        opacity = _quantize(rules.eval_tokens(e["opacity"], state), e["steps"])
        if amount <= 0 or opacity <= 0:
            continue
        if "stages" in e:
            chosen = [name for at, name in e["stages"] if amount >= at]
            if not chosen:
                continue
            file = chosen[-1]
        else:
            file = e["file"]
        out.append((e["id"], file, amount if e["has_growth"] else 1.0, opacity))
    return out


def verify(scene: Scene, compiled: list[dict], cases: list[tuple[str, dict]], decisions: bool = True) -> int:
    """Check every compiled rule against the expression evaluator for each case
    and, with `decisions`, the frame's layer choices against the Mac renderer's."""
    problems = 0
    for name, state in cases:
        for e in compiled:
            for key in ("when", "amount", "opacity"):
                if not rules.check(e[f"{key}_src"], e[key], state):
                    print(f"[publish] rule mismatch: layer {e['id']} {key} in {name}")
                    problems += 1
        if not decisions:
            continue
        mac = [(l["id"], l["amount"], l["opacity"]) for l in scene.active_layers(state)]
        dev = [(i, a, o) for i, _, a, o in decide(compiled, state)]
        if mac != dev:
            print(f"[publish] decision mismatch in {name}:\n  mac    {mac}\n  device {dev}")
            problems += 1
    return problems


def publish(cfg: dict, out: Path, scenario_files) -> Path:
    from .pipeline import scenario_state
    scene = Scene(cfg["_root"] / cfg.get("scene", "scene"))
    disp = cfg.get("display", {})
    lines, encoded, compiled = compile_scene(scene, disp)
    cases = [(f.name, scenario_state(f)) for f in scenario_files]
    cases += [(name, state) for name, _, state in combos()]
    problems = verify(scene, compiled, cases)
    if problems:
        raise SystemExit(f"{problems} problem(s); nothing published")

    dest = out / _safe(scene.folder.name)
    if dest.exists():
        shutil.rmtree(dest)
    (dest / "layers").mkdir(parents=True)
    (dest / "scene.txt").write_text("\n".join(lines) + "\n")
    files = [("scene.txt", dest / "scene.txt")]
    for name, enc in sorted(encoded.items()):
        wpl.write(dest / "layers" / name, enc)
        files.append((f"layers/{name}", dest / "layers" / name))

    entries = []
    for rel, path in files:
        data = path.read_bytes()
        entries.append((rel, len(data), hashlib.sha1(data).hexdigest()[:16]))
    version = hashlib.sha1("".join(f"{r}{s}{h}" for r, s, h in entries).encode()).hexdigest()[:12]
    (dest / "manifest.txt").write_text(
        f"WPM1 {version}\n" + "".join(f"file {r} {s} {h}\n" for r, s, h in entries))

    total = sum(s for _, s, _ in entries)
    print(f"published {scene.folder.name}: {len(compiled)} layers, {len(encoded)} files, "
          f"{total / 1e6:.1f} MB, version {version} -> {dest}")
    print(f"checked {len(cases)} cases ({len(list(scenario_files))} scenarios + {len(cases) - len(list(scenario_files))} "
          f"demo combinations): rules and layer decisions match the Mac renderer")
    return dest
