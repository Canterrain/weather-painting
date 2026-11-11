"""Layer compositing.

A scene is a folder with a scene.yaml and your painted layers (PNG with
transparency). Layers are stacked bottom to top. Each layer can say:

  when:     should it be drawn at all?                 (expression, default true)
  amount:   how much of it (0..1) — drives `reveal` or `stages`
  reveal:   grayscale "growth map": black areas appear first, white last
  stages:   a list of images swapped in as `amount` rises
  opacity:  0..1 fade (expression)
  blend:    normal | multiply   (multiply = a transparent watercolor glaze)
  steps:    quantize amount/opacity to this many steps so the picture only
            changes (and the panel only refreshes) in visible increments
  offset:   [x, y] if the PNG is smaller than the canvas
  optional: true to skip a missing file silently
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

from . import native
from .expr import evaluate


@lru_cache(maxsize=128)
def _load_rgba(path: str, mtime: float) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGBA"), dtype=np.uint8)


@lru_cache(maxsize=64)
def _load_gray(path: str, mtime: float) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"), dtype=np.uint8)


def load_rgba(path: Path) -> np.ndarray:
    return _load_rgba(str(path), os.path.getmtime(path))


def load_gray(path: Path) -> np.ndarray:
    return _load_gray(str(path), os.path.getmtime(path))


def _quantize(x: float, steps: int) -> float:
    x = max(0.0, min(1.0, float(x)))
    return round(x * steps) / steps if steps else x


@dataclass
class Rendered:
    image: Image.Image
    drawn: list[str]


class Scene:
    def __init__(self, folder: str | Path):
        self.folder = Path(folder)
        with open(self.folder / "scene.yaml") as f:
            self.spec = yaml.safe_load(f)
        self.width, self.height = self.spec.get("canvas", [1600, 1200])
        self.background = tuple(self.spec.get("background", [255, 255, 255]))
        self.default_steps = int(self.spec.get("steps", 10))

    def _warn(self, msg):
        print(f"[scene] {msg}", file=sys.stderr)

    def active_layers(self, state: dict) -> list[dict]:
        """Decide which layers are drawn, and how much of each, for this weather."""
        out = []
        for layer in self.spec.get("layers", []):
            lid = layer.get("id", layer.get("file", "?"))
            if not evaluate(layer.get("when", True), state):
                continue
            steps = int(layer.get("steps", self.default_steps))
            amount = _quantize(evaluate(layer.get("amount", 1), state), steps)
            opacity = _quantize(evaluate(layer.get("opacity", 1), state), steps)
            if amount <= 0 or opacity <= 0:
                continue

            rgba = self._layer_pixels(layer, amount)
            if rgba is None:
                continue
            growth = None
            if "reveal" in layer:
                p = self._path(layer["reveal"])
                if p is not None:
                    growth = load_gray(p)
                    if growth.shape != rgba.shape[:2]:
                        self._warn(f"reveal map {layer['reveal']} is not the same size as its layer; ignored")
                        growth = None

            x, y = layer.get("offset", [0, 0])
            h, w = rgba.shape[:2]
            if x + w > self.width or y + h > self.height:
                self._warn(f"layer {lid!r} ({w}x{h} at {x},{y}) doesn't fit the {self.width}x{self.height} canvas; skipped")
                continue
            out.append({"id": lid, "rgba": rgba, "growth": growth, "x": x, "y": y,
                        "amount": amount if growth is not None else 1.0,
                        "feather": float(layer.get("feather", 0.06)), "opacity": opacity,
                        "blend": layer.get("blend", "normal"), "label_amount": amount})
        return out

    def render(self, state: dict) -> Rendered:
        layers = self.active_layers(state)
        canvas = native.compose(self.width, self.height, self.background, layers)
        drawn = [f"{l['id']} (amount {l['label_amount']:.2f})" if l["label_amount"] < 1 else l["id"]
                 for l in layers]
        return Rendered(Image.fromarray(canvas, "RGB"), drawn)

    def _path(self, rel: str, optional: bool = False) -> Path | None:
        p = self.folder / rel
        if not p.exists():
            if not optional:
                self._warn(f"missing file {rel} (skipping)")
            return None
        return p

    def _layer_pixels(self, layer: dict, amount: float):
        if "stages" in layer:
            chosen = None
            for stage in layer["stages"]:
                if amount >= float(stage.get("at", 0)):
                    chosen = stage
            if chosen is None:
                return None
            p = self._path(chosen["file"], layer.get("optional", False))
        else:
            p = self._path(layer["file"], layer.get("optional", False))
        return None if p is None else load_rgba(p)
