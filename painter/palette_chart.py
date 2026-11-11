"""A painter's reference chart: what the panel can do with color.

Each swatch shows the color you paint (top) and what the panel will show
(bottom, simulated). The chart is exactly panel-sized, so the same file can be
sent to the device to compare the simulation against the real thing.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import epaper

INKS = [("White", (255, 255, 255)), ("Black", (0, 0, 0)), ("Red", (229, 57, 53)),
        ("Yellow", (255, 216, 0)), ("Blue", (0, 76, 255)), ("Green", (29, 185, 84))]

GOOD_MIXES = [
    ("Orange  R+Y", (240, 130, 30)), ("Pink  R+W", (240, 160, 160)), ("Purple  R+B", (120, 50, 150)),
    ("Sky  B+W", (150, 185, 235)), ("Lime  G+Y", (170, 210, 60)), ("Brown  R+G+K", (120, 75, 40)),
    ("Pale gray  K+W", (200, 200, 200)), ("Mid gray  K+W", (128, 128, 128)), ("Night  B+K", (25, 35, 90)),
    ("Forest  G+K", (30, 80, 40)), ("Teal  B+G", (30, 120, 130)), ("Cream  Y+W", (250, 240, 180)),
]

RISKY = [
    ("Beige / taupe", (190, 175, 150)), ("Dusty rose", (190, 140, 140)), ("Sage", (150, 170, 140)),
    ("Slate", (100, 110, 125)), ("Navy vs black", (15, 20, 50)), ("Pale lilac", (220, 210, 235)),
]

GRADIENTS = [
    ("Day sky: white > blue", [(255, 255, 255), (70, 120, 230)]),
    ("Dusk: yellow > red > purple", [(255, 220, 60), (230, 70, 50), (90, 40, 120)]),
    ("Night: blue > black", [(40, 70, 170), (5, 5, 15)]),
    ("Snow shadow: white > pale blue", [(255, 255, 255), (170, 195, 240)]),
]


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _gradient(w, h, stops):
    t = np.linspace(0, 1, w)
    seg = len(stops) - 1
    out = np.zeros((h, w, 3), dtype=np.float32)
    for i in range(seg):
        a, b = np.array(stops[i], np.float32), np.array(stops[i + 1], np.float32)
        lo, hi = i / seg, (i + 1) / seg
        m = (t >= lo) & (t <= hi)
        u = ((t[m] - lo) / (hi - lo))[:, None]
        out[:, m] = a + (b - a) * u
    return out.astype(np.uint8)


def build(disp: dict) -> tuple[Image.Image, Image.Image, bytes]:
    from .pipeline import panel_indices
    palette = disp.get("palette", "perceived")
    W, H = epaper.PANEL_W, epaper.PANEL_H
    painted = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(painted)
    title, label = _font(40), _font(22)
    labels = []  # drawn after dithering so text stays crisp

    y = 30
    labels.append(((40, y), "E1004 / Spectra 6 color guide", title))
    y += 70

    def row(items, y, heading, cols=6, sw=170, sh=150):
        labels.append(((40, y), heading, label))
        y += 36
        for i, (name, rgb) in enumerate(items):
            cx = 40 + (i % cols) * (sw + 22)
            cy = y + (i // cols) * (sh + 50)
            d.rectangle([cx, cy, cx + sw, cy + sh], fill=rgb)
            labels.append(((cx, cy + sh + 6), name, label))
        return y + ((len(items) + cols - 1) // cols) * (sh + 50) + 10

    y = row(INKS, y, "The six physical inks (solid, crisp, no dither noise)")
    y = row(GOOD_MIXES, y, "Two-ink mixes that dither well")
    y = row(RISKY, y, "Risky: muted/near-neutral tones turn speckly")
    labels.append(((40, y), "Gradients", label))
    y += 36
    for name, stops in GRADIENTS:
        painted.paste(Image.fromarray(_gradient(W - 80, 70, stops)), (40, y))
        labels.append(((40, y + 74), name, label))
        y += 115

    # Labels go on after the swatches are dithered so the text stays crisp.
    swatches = painted.copy()
    for pos, text, font in labels:
        ImageDraw.Draw(painted).text(pos, text, fill=(0, 0, 0), font=font)
    idx = panel_indices(swatches, disp)
    text_mask = np.asarray(painted.convert("L")) < 60
    text_mask &= np.asarray(swatches.convert("L")) > 60
    idx[text_mask] = 1  # black ink
    return painted, epaper.simulate(idx, palette), epaper.pack(idx)
