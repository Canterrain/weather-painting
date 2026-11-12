"""Glue: config -> weather state -> composited painting -> panel frame."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

from . import epaper, native
from .scene import Scene
from .weather import (DEFAULT_STATE, blend, build_state, derive, fetch_open_meteo, fetch_radar, fetch_reports,
                      geocode, model_soon, stations)

ROOT = Path(__file__).resolve().parent.parent


def load_config(path: str | Path = ROOT / "config.yaml") -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    cfg["_root"] = Path(path).resolve().parent
    return cfg


def resolve_location(cfg: dict) -> tuple[float, float]:
    """lat/lon from config.yaml, or look up `location.name` (e.g. 'Cincinnati,OH,US')
    with Open-Meteo's geocoder. The environment variable PAINTER_LOCATION
    overrides both, so a public repo doesn't have to contain your location."""
    loc = dict(cfg.get("location") or {})
    env_name = os.environ.get("PAINTER_LOCATION")
    if env_name:
        loc = {"name": env_name}
    if loc.get("lat") is not None and loc.get("lon") is not None:
        return float(loc["lat"]), float(loc["lon"])
    if not loc.get("name"):
        raise SystemExit("Set location.name (e.g. 'Cincinnati,OH,US') or location.lat/lon in config.yaml")
    if "_geocoded" not in cfg:
        cfg["_geocoded"] = geocode(loc["name"])
        print(f"[painter] location {loc['name']!r} -> {cfg['_geocoded']['name']} "
              f"({cfg['_geocoded']['lat']:.3f}, {cfg['_geocoded']['lon']:.3f})")
    return cfg["_geocoded"]["lat"], cfg["_geocoded"]["lon"]


def live_state(cfg: dict) -> dict:
    lat, lon = resolve_location(cfg)
    now = time.time()
    data = fetch_open_meteo(lat, lon)
    state = build_state(data, lat, lon, now)
    try:
        reports = fetch_reports(lat, lon)
    except OSError:
        reports = []   # no airport reports: keep the forecast's "right now"
    try:
        radar = fetch_radar(lat, lon, now)
    except OSError:
        radar = None
    return blend(state, stations(reports, lat, lon, now), model_soon(data, now), radar)


def scenario_state(path: str | Path, overrides: dict | None = None) -> dict:
    with open(path) as f:
        spec = yaml.safe_load(f) or {}
    s = dict(DEFAULT_STATE)
    s.update({k: v for k, v in spec.items() if k != "name"})
    s.update(overrides or {})
    return derive(s)


def parse_overrides(pairs: list[str]) -> dict:
    out = {}
    for p in pairs or []:
        k, _, v = p.partition("=")
        out[k.strip()] = yaml.safe_load(v)
    return out


def panel_indices(img: Image.Image, disp: dict) -> np.ndarray:
    """Tone-map and dither an RGB image to ink indices with the shared C code
    (the exact routine the reTerminal runs)."""
    tone = native.make_tone(epaper.palette_rgb(disp.get("palette", "perceived")),
                            disp.get("saturation", 1.0), disp.get("contrast", 1.0),
                            disp.get("brightness", 1.0), disp.get("fit_to_panel", True))
    return native.tone_and_dither(np.asarray(img.convert("RGB")), tone)


@dataclass
class Frame:
    state: dict
    layers: list[str]
    composite: Image.Image      # the painting, full color, canvas orientation
    preview: Image.Image        # simulated panel output, canvas orientation
    data: bytes                 # 960,000-byte packed frame for the device
    etag: str
    rendered_at: float


def make_frame(cfg: dict, state: dict) -> Frame:
    scene = Scene(cfg["_root"] / cfg.get("scene", "scene"))
    rendered = scene.render(state)
    disp = cfg.get("display", {})
    rotate = int(disp.get("rotate", 0))
    palette = disp.get("palette", "perceived")

    panel_img = epaper.to_panel_orientation(rendered.image, rotate)
    idx = panel_indices(panel_img, disp)
    data = epaper.pack(idx)
    preview = epaper.simulate(idx, palette)
    if rotate % 360:
        preview = preview.rotate(rotate % 360, expand=True)  # back to how you painted it

    return Frame(state, rendered.drawn, rendered.image, preview, data,
                 '"' + hashlib.sha1(data).hexdigest()[:16] + '"', time.time())


def save_frame(frame: Frame, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "frame.bin").write_bytes(frame.data)
    frame.composite.save(out / "composite.png")
    frame.preview.save(out / "preview.png")
    (out / "state.json").write_text(json.dumps({"state": frame.state, "layers": frame.layers}, indent=2))
