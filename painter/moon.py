"""Make reveal maps that turn one painted full moon into every phase.

    python -m painter.moon painting/layers/moon.png

writes moon_waxing_growth.png and moon_waning_growth.png next to it. Used as
the `reveal` of a moon layer with `amount: moon_illum`, they show exactly the
lit part of the disc: the terminator is the ellipse x = 1 - 2k across each row
of the disc, which lights a fraction k of its area. Waxing lights the right
side (as seen from the northern hemisphere), waning the left.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image


def growth_maps(alpha: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ys, xs = np.nonzero(alpha)
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    r = max(xs.max() - xs.min(), ys.max() - ys.min()) / 2 + 0.5
    yy, xx = np.mgrid[0:alpha.shape[0], 0:alpha.shape[1]].astype(np.float64)
    half = np.sqrt(np.clip(r * r - (yy + 0.5 - cy) ** 2, 1e-6, None))
    xn = np.clip((xx + 0.5 - cx) / half, -1, 1)          # -1 left edge .. 1 right edge, per row
    waxing = np.round((1 - xn) / 2 * 255).astype(np.uint8)
    waning = np.round((1 + xn) / 2 * 255).astype(np.uint8)
    return waxing, waning


def main(argv: list[str]) -> None:
    if len(argv) != 1:
        sys.exit(__doc__)
    src = Path(argv[0])
    alpha = np.array(Image.open(src).convert("RGBA"))[..., 3]
    if not alpha.any():
        sys.exit(f"{src} has no painted pixels")
    for name, g in zip(("moon_waxing_growth.png", "moon_waning_growth.png"), growth_maps(alpha)):
        Image.fromarray(g, "L").save(src.parent / name)
        print(f"wrote {src.parent / name}")


if __name__ == "__main__":
    main(sys.argv[1:])
