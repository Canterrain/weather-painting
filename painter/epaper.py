"""Spectra 6 panel model: palette, dithering, 4bpp packing and previews.

The reTerminal E1004 panel (T133A01) is 1200 x 1600, portrait-native, and can
physically show six inks. Every other color is an illusion made by dithering
(mixing dots of those inks).

The frame the device downloads is 1200*1600/2 = 960,000 bytes: two pixels per
byte, left pixel in the high nibble, using the raw panel codes below (the same
codes Seeed_GFX's own image examples push with `epaper.pushImage`).
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageEnhance

PANEL_W, PANEL_H = 1200, 1600
FRAME_BYTES = PANEL_W * PANEL_H // 2

# name, raw panel code, "nominal" sRGB (what Seeed's converter assumes),
# "perceived" sRGB (roughly what the inks look like on a real Spectra 6 panel
# under room light: muted, slightly warm paper, no pure black).
#
# The perceived values are approximations; tune them to your own panel with
# `python -m painter calibrate` (see README).
INKS = [
    ("white",  0x0, (255, 255, 255), (222, 222, 212)),
    ("black",  0xF, (0,   0,   0),   (28,  30,  36)),
    ("red",    0x6, (229, 57,  53),  (165, 36,  30)),
    ("yellow", 0xB, (255, 216, 0),   (222, 204, 30)),
    ("blue",   0xD, (0,   76,  255), (52,  88,  172)),  # lightened after comparing a real panel
    ("green",  0x2, (29,  185, 84),  (50,  108, 66)),
]

INK_CODES = np.array([code for _, code, _, _ in INKS], dtype=np.uint8)


def palette_rgb(kind: str = "perceived") -> list[tuple[int, int, int]]:
    col = 3 if kind == "perceived" else 2
    return [ink[col] for ink in INKS]


def _palette_image(colors) -> Image.Image:
    # Pillow wants a full 256-entry palette. Repeat our six colors so every
    # index maps back to an ink with `index % 6`.
    flat = []
    for i in range(256):
        flat.extend(colors[i % len(colors)])
    pal = Image.new("P", (1, 1))
    pal.putpalette(flat)
    return pal


def prepare(img: Image.Image, saturation=1.0, contrast=1.0, brightness=1.0,
            fit_to_panel: bool = True, palette: str = "perceived") -> Image.Image:
    """Tone tweaks applied before dithering.

    fit_to_panel squeezes the painting's 0..255 range onto the panel's real
    black..white range. Without it, anything paler than the panel's (grayish)
    white is simply rounded to white and faint washes vanish."""
    img = img.convert("RGB")
    if brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(brightness)
    if contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(contrast)
    if saturation != 1.0:
        img = ImageEnhance.Color(img).enhance(saturation)
    if fit_to_panel and palette == "perceived":
        pal = palette_rgb("perceived")
        white, black = np.array(pal[0], np.float32), np.array(pal[1], np.float32)
        a = np.asarray(img, np.float32) / 255.0
        img = Image.fromarray((black + a * (white - black) + 0.5).astype(np.uint8), "RGB")
    return img


def dither(img: Image.Image, palette: str = "perceived", method: str = "floyd") -> np.ndarray:
    """Return an HxW array of ink indices (0..5, into INKS)."""
    pal = _palette_image(palette_rgb(palette))
    mode = Image.Dither.FLOYDSTEINBERG if method == "floyd" else Image.Dither.NONE
    q = img.convert("RGB").quantize(palette=pal, dither=mode)
    return (np.asarray(q, dtype=np.uint8) % len(INKS)).astype(np.uint8)


def pack(indices: np.ndarray) -> bytes:
    """Pack ink indices (1600 rows x 1200 cols) into the 4bpp panel frame."""
    if indices.shape != (PANEL_H, PANEL_W):
        raise ValueError(f"frame must be {PANEL_W}x{PANEL_H}, got {indices.shape[1]}x{indices.shape[0]}")
    codes = INK_CODES[indices]
    packed = (codes[:, 0::2] << 4) | codes[:, 1::2]
    return packed.astype(np.uint8).tobytes()


def simulate(indices: np.ndarray, palette: str = "perceived") -> Image.Image:
    """Show what the panel will display, using the chosen palette colors."""
    lut = np.array(palette_rgb(palette), dtype=np.uint8)
    return Image.fromarray(lut[indices], "RGB")


def to_panel_orientation(img: Image.Image, rotate: int) -> Image.Image:
    """Rotate the painted canvas so it lands on the portrait-native panel.
    `rotate` is clockwise degrees: 0, 90, 180 or 270."""
    rotate = rotate % 360
    if rotate:
        img = img.rotate(-rotate, expand=True)
    if img.size != (PANEL_W, PANEL_H):
        raise ValueError(
            f"after rotating {rotate} deg the canvas is {img.size[0]}x{img.size[1]}; "
            f"the panel needs {PANEL_W}x{PANEL_H}. Paint at 1200x1600 (portrait) "
            f"or 1600x1200 (landscape, with rotate: 90 or 270)."
        )
    return img
