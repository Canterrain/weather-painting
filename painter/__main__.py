"""Command line.

  python -m painter render                       live weather -> out/
  python -m painter render --scenario scenarios/blizzard.yaml
  python -m painter render --set snow_depth_cm=8 --set phase=night
  python -m painter studio                       try the scene under any weather in the browser
  python -m painter gallery                      every scenario -> out/gallery.png
  python -m painter gallery --combos             every season x weather combination
  python -m painter palette                      color guide for painting
  python -m painter check my_layer.png           how a painting/layer will look on the panel
  python -m painter state                        print the live weather state
  python -m painter publish                      layers + compiled rules for frames to download (docs/)
  python -m painter firmware-data                built-in rules + demo cases for the firmware
  python -m painter.submission layers.zip        check a gallery submission, ready its release

Any command takes --scene FOLDER to use a scene other than the one in config.yaml.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

from . import epaper, palette_chart
from .pipeline import (ROOT, load_config, live_state, make_frame, parse_overrides,
                       panel_indices, save_frame, scenario_state)
from .weather import DEFAULT_STATE, derive


def cmd_render(args, cfg):
    if args.scenario:
        state = scenario_state(args.scenario, parse_overrides(args.set))
    elif args.set:
        s = dict(DEFAULT_STATE)
        s.update(parse_overrides(args.set))
        state = derive(s)
    else:
        state = live_state(cfg)
    frame = make_frame(cfg, state)
    out = Path(args.out)
    save_frame(frame, out)
    print("layers:", ", ".join(frame.layers) or "(none)")
    print(f"wrote {out}/frame.bin ({len(frame.data):,} bytes), preview.png, composite.png, state.json")


def cmd_gallery(args, cfg):
    if args.combos:
        from .combos import combos
        cases = [(name, state) for name, _, state in combos()]
    else:
        files = sorted(Path(args.scenarios).glob("*.yaml"))
        if not files:
            raise SystemExit(f"no scenarios in {args.scenarios}")
        cases = [(f.stem, scenario_state(f)) for f in files]
    thumbs = []
    for name, state in cases:
        frame = make_frame(cfg, state)
        print(f"{name:22s} {', '.join(frame.layers)}")
        t = frame.preview.copy()
        t.thumbnail((400, 400))
        thumbs.append((name, t))
    tw, th = max(t.width for _, t in thumbs), max(t.height for _, t in thumbs)
    cols = min(4, len(thumbs))
    rows = math.ceil(len(thumbs) / cols)
    sheet = Image.new("RGB", (cols * (tw + 20) + 20, rows * (th + 50) + 20), "white")
    d = ImageDraw.Draw(sheet)
    for i, (name, t) in enumerate(thumbs):
        x, y = 20 + (i % cols) * (tw + 20), 20 + (i // cols) * (th + 50)
        sheet.paste(t, (x, y))
        d.text((x, y + th + 8), name, fill="black", font=palette_chart._font(20))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sheet.save(out / "gallery.png")
    print(f"wrote {out}/gallery.png")


def cmd_palette(args, cfg):
    painted, sim, data = palette_chart.build(cfg.get("display", {}))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    side = Image.new("RGB", (painted.width * 2 + 30, painted.height), "white")
    side.paste(painted, (0, 0))
    side.paste(sim, (painted.width + 30, 0))
    side.save(out / "palette_guide.png")
    sim.save(out / "palette_panel_sim.png")
    (out / "palette_chart.bin").write_bytes(data)
    print(f"wrote {out}/palette_guide.png (left: painted, right: panel simulation), "
          f"palette_panel_sim.png, palette_chart.bin (send to the device to calibrate)")


def cmd_check(args, cfg):
    disp = cfg.get("display", {})
    img = Image.open(args.image)
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img.convert("RGBA"))
    img = img.convert("RGB")
    idx = panel_indices(img, disp)
    sim = epaper.simulate(idx, disp.get("palette", "perceived"))
    side = Image.new("RGB", (img.width * 2 + 20, img.height), "white")
    side.paste(img, (0, 0))
    side.paste(sim, (img.width + 20, 0))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / (Path(args.image).stem + "_check.png")
    side.save(dest)
    print(f"wrote {dest} (left: your image, right: panel simulation)")


def cmd_publish(args, cfg):
    from .publish import publish
    publish(cfg, Path(args.out), sorted(Path(args.scenarios).glob("*.yaml")))


def cmd_firmware_data(args, cfg):
    from .firmware_data import write
    write(cfg)


def cmd_state(args, cfg):
    print(json.dumps(live_state(cfg), indent=2))


def main():
    p = argparse.ArgumentParser(prog="painter")
    p.add_argument("--config", default=str(ROOT / "config.yaml"))
    p.add_argument("--scene", help="scene folder (overrides config.yaml)")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("render")
    r.add_argument("--scenario")
    r.add_argument("--set", action="append", metavar="KEY=VALUE")
    r.add_argument("--out", default=str(ROOT / "out"))
    g = sub.add_parser("gallery")
    g.add_argument("--scenarios", default=str(ROOT / "scenarios"))
    g.add_argument("--out", default=str(ROOT / "out"))
    g.add_argument("--combos", action="store_true", help="every season x weather combination instead of scenarios/")
    st = sub.add_parser("studio")
    st.add_argument("--port", type=int, default=8765)
    st.add_argument("--no-browser", action="store_true")
    pc = sub.add_parser("palette")
    pc.add_argument("--out", default=str(ROOT / "out"))
    c = sub.add_parser("check")
    c.add_argument("image")
    c.add_argument("--out", default=str(ROOT / "out"))
    sub.add_parser("state")
    sub.add_parser("firmware-data")
    pb = sub.add_parser("publish")
    pb.add_argument("--out", default=str(ROOT / "docs"))
    pb.add_argument("--scenarios", default=str(ROOT / "scenarios"))

    args = p.parse_args()
    cfg = load_config(args.config)
    if args.scene:
        cfg["scene"] = str(Path(args.scene).resolve())
    if args.cmd == "studio":
        from .studio import studio
        studio(cfg, args.port, not args.no_browser)
    else:
        {"render": cmd_render, "gallery": cmd_gallery, "palette": cmd_palette,
         "check": cmd_check, "state": cmd_state,
         "publish": cmd_publish, "firmware-data": cmd_firmware_data}[args.cmd](args, cfg)


if __name__ == "__main__":
    main()
