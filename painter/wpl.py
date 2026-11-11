"""Layer files the reTerminal reads from its SD card (.wpl, version 2).

Only painted pixels are stored: each row is a list of spans (runs of
non-transparent pixels), and each layer uses the cheapest pixel form that
represents it exactly:

    RGB    3 bytes/pixel  every painted pixel is fully opaque (base painting, skies)
    ALPHA  1 byte/pixel   one color at varying opacity (glazes, stars, moon glow)
    RGBA   4 bytes/pixel  everything else

File layout (little-endian):

    offset  size   field
    0       4      magic "WPL2"
    4       2      x        where the layer's box sits on the canvas
    6       2      y
    8       2      w
    10      2      h
    12      1      flags    bit 0: rows carry growth-map bytes
                            bit 1: every pixel of the box is fully opaque
    13      1      mode     0 RGBA, 1 RGB, 2 ALPHA (matches WP_ENC_* in wp_compose.h)
    14      3      solid    the color for ALPHA mode
    17      15     reserved (zero)
    32      4*h    row offsets, relative to the start of the row data
    32+4h   ...    rows: u16 nspans, nspans x (u16 x, u16 len), span pixels, [span growth bytes]

Encoding is lossless for every painted pixel, so the panel shows exactly what
the Mac preview (which composites the plain RGBA) shows.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

HEADER = struct.Struct("<4sHHHHBB3B15x")
assert HEADER.size == 32
MODE_RGBA, MODE_RGB, MODE_ALPHA = 0, 1, 2


def bbox(rgba: np.ndarray) -> tuple[int, int, int, int] | None:
    """(x, y, w, h) of the non-transparent pixels, or None if fully transparent."""
    alpha = rgba[..., 3]
    rows = np.flatnonzero(alpha.any(axis=1))
    cols = np.flatnonzero(alpha.any(axis=0))
    if rows.size == 0:
        return None
    return int(cols[0]), int(rows[0]), int(cols[-1] - cols[0] + 1), int(rows[-1] - rows[0] + 1)


def choose_mode(rgba: np.ndarray) -> tuple[int, tuple[int, int, int]]:
    painted = rgba[rgba[..., 3] > 0]
    if painted.size == 0:
        return MODE_ALPHA, (0, 0, 0)
    first = painted[0, :3]
    if (painted[:, :3] == first).all():
        return MODE_ALPHA, tuple(int(c) for c in first)
    if (painted[:, 3] == 255).all():
        return MODE_RGB, (0, 0, 0)
    return MODE_RGBA, (0, 0, 0)


def encode(rgba: np.ndarray, growth: np.ndarray | None = None, x0: int = 0, y0: int = 0) -> dict:
    """Encode a canvas-positioned layer. Returns the fields compose() and write() need."""
    box = bbox(rgba) or (0, 0, 1, 1)
    bx, by, w, h = box
    crop = np.ascontiguousarray(rgba[by:by + h, bx:bx + w], dtype=np.uint8)
    gcrop = None if growth is None else np.ascontiguousarray(growth[by:by + h, bx:bx + w], dtype=np.uint8)
    mode, solid = choose_mode(crop)

    rows, offsets, pos = [], [], 0
    for r in range(h):
        painted = crop[r, :, 3] > 0
        # span starts/ends from the edges of the painted mask
        edges = np.diff(np.concatenate(([0], painted.view(np.int8), [0])))
        starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
        parts = [struct.pack("<H", len(starts))]
        parts += [struct.pack("<HH", s, e - s) for s, e in zip(starts, ends)]
        idx = np.concatenate([np.arange(s, e) for s, e in zip(starts, ends)]) if len(starts) else np.empty(0, int)
        px = crop[r, idx]
        if mode == MODE_RGBA:
            parts.append(px.tobytes())
        elif mode == MODE_RGB:
            parts.append(px[:, :3].tobytes())
        else:
            parts.append(px[:, 3].tobytes())
        if gcrop is not None:
            parts.append(gcrop[r, idx].tobytes())
        row = b"".join(parts)
        offsets.append(pos)
        pos += len(row)
        rows.append(row)

    return {"x": x0 + bx, "y": y0 + by, "w": w, "h": h, "enc_mode": mode, "solid": solid,
            "enc_growth": gcrop is not None, "opaque": bool((crop[..., 3] == 255).all()),
            "enc": b"".join(rows), "offsets": offsets}


def write(path: Path, layer: dict) -> int:
    """Write an encoded layer (from encode()). Returns the file size."""
    header = HEADER.pack(b"WPL2", layer["x"], layer["y"], layer["w"], layer["h"],
                         (1 if layer["enc_growth"] else 0) | (2 if layer.get("opaque") else 0),
                         layer["enc_mode"], *layer["solid"])
    table = struct.pack(f"<{layer['h']}I", *layer["offsets"])
    data = header + table + layer["enc"]
    path.write_bytes(data)
    return len(data)


def read(path: Path) -> dict:
    data = Path(path).read_bytes()
    magic, x, y, w, h, flags, mode, r, g, b = HEADER.unpack_from(data)
    if magic != b"WPL2":
        raise ValueError(f"{path} is not a WPL2 layer file")
    offsets = list(struct.unpack_from(f"<{h}I", data, 32))
    return {"x": x, "y": y, "w": w, "h": h, "enc_growth": bool(flags & 1), "opaque": bool(flags & 2),
            "enc_mode": mode,
            "solid": (r, g, b), "enc": data[32 + 4 * h:], "offsets": offsets}
