"""Studio: try a scene under any weather in the browser.

    python -m painter [--scene my_painting] studio [--port 8765]

Opens a page with controls for season, time of day, clouds, rain, snow and
the moon, and shows the painting as the panel will render it (the same
dithering the frame runs). "Every combination" lays out every season x
weather test case on one page. The preview updates by itself when a layer
file or scene.yaml is saved, so a painter can keep it open next to Photoshop.
"""

from __future__ import annotations

import base64
import io
import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .combos import SEASONS, combos, complete
from .expr import evaluate
from .pipeline import make_frame, scenario_state
from .scene import Scene

_render_lock = threading.Lock()


def _png(img, max_w: int | None = None) -> bytes:
    if max_w and img.width > max_w:
        img = img.copy()
        img.thumbnail((max_w, max_w))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _scene_dir(cfg) -> Path:
    return Path(cfg["_root"]) / cfg.get("scene", "scene")


def _scene_version(folder: Path) -> str:
    """Changes whenever any file in the scene folder is saved."""
    latest = 0.0
    count = 0
    for root, _, files in os.walk(folder):
        for f in files:
            count += 1
            try:
                latest = max(latest, os.path.getmtime(os.path.join(root, f)))
            except OSError:
                pass
    return f"{latest:.3f}-{count}"


def _missing(scene: Scene, state: dict) -> list[str]:
    """Layers whose rules say "draw me" now but whose file isn't painted yet."""
    out = []
    for layer in scene.spec.get("layers", []):
        try:
            if not evaluate(layer.get("when", True), state):
                continue
        except Exception:
            continue
        files = [s["file"] for s in layer.get("stages", [])] or [layer.get("file")]
        if not any(f and (scene.folder / f).exists() for f in files):
            out.append(layer.get("id", files[0]))
    return out


def _render(cfg, state: dict) -> dict:
    with _render_lock:
        frame = make_frame(cfg, state)
        scene = Scene(_scene_dir(cfg))
    return {"panel": frame.preview, "color": frame.composite, "layers": frame.layers,
            "missing": _missing(scene, state)}


def _scenarios(root: Path) -> dict[str, Path]:
    return {p.stem: p for p in sorted((root / "scenarios").glob("*.yaml"))}


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Painting Studio</title>
<style>
:root { --bg:#f6f4ef; --panel:#fff; --ink:#222; --muted:#6b6b6b; --line:#ddd8cc; --accent:#2f5d9e; --warn:#a5241e; }
* { box-sizing:border-box; }
body { margin:0; font:14px/1.4 -apple-system,system-ui,sans-serif; background:var(--bg); color:var(--ink); }
header { display:flex; gap:16px; align-items:center; padding:10px 16px; border-bottom:1px solid var(--line); background:var(--panel); flex-wrap:wrap; }
header h1 { font-size:16px; margin:0; }
header .scene { color:var(--muted); }
header nav { margin-left:auto; display:flex; gap:6px; }
button, select { font:inherit; padding:5px 10px; border:1px solid var(--line); border-radius:6px; background:#fff; cursor:pointer; }
button.on { background:var(--accent); color:#fff; border-color:var(--accent); }
main { display:grid; grid-template-columns:300px 1fr; gap:16px; padding:16px; }
@media (max-width:800px) { main { grid-template-columns:1fr; } }
.controls { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px; align-self:start; }
.controls h2 { font-size:12px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); margin:14px 0 6px; }
.controls h2:first-child { margin-top:0; }
.row { display:flex; align-items:center; gap:8px; margin:6px 0; }
.row label { flex:0 0 110px; }
.row input[type=range] { flex:1; min-width:0; }
.row output { flex:0 0 52px; text-align:right; font-variant-numeric:tabular-nums; color:var(--muted); }
.seg { display:flex; flex-wrap:wrap; gap:4px; }
.seg button { padding:3px 8px; }
.view { min-width:0; }
.view img { width:100%; height:auto; display:block; border:1px solid var(--line); border-radius:4px; background:#fff; image-rendering:auto; }
.info { margin-top:10px; display:flex; gap:16px; flex-wrap:wrap; }
.chips span { display:inline-block; padding:2px 8px; margin:2px; border-radius:10px; background:#e8eef7; font-size:12px; }
.chips.missing span { background:#f7e4e2; color:var(--warn); }
.busy { opacity:.55; transition:opacity .2s; }
#grid { display:none; padding:16px; }
#grid h3 { margin:18px 0 8px; font-size:15px; }
.cells { display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:12px; }
.cell { background:var(--panel); border:1px solid var(--line); border-radius:6px; padding:6px; cursor:pointer; }
.cell img { width:100%; aspect-ratio:4/3; display:block; background:#eee; }
.cell div { font-size:12px; margin-top:4px; }
.hint { color:var(--muted); font-size:12px; margin-top:12px; }
</style></head><body>
<header>
  <h1>Painting Studio</h1><span class="scene" id="sceneName"></span>
  <select id="preset"><option value="">Presets…</option></select>
  <nav><button id="tabOne" class="on">One weather</button><button id="tabAll">Every combination</button></nav>
</header>
<section id="one"><main>
  <div class="controls">
    <h2>When</h2>
    <div class="row"><label>Season</label><div class="seg" id="season"></div></div>
    <div class="row"><label>Time of day</label><div class="seg" id="phase"></div></div>
    <h2>Sky</h2>
    <div class="row"><label>Cloud cover</label><input type="range" id="cloud_cover" min="0" max="100" step="5"><output></output></div>
    <div class="row"><label>Fog</label><input type="checkbox" id="is_foggy"></div>
    <div class="row"><label>Thunderstorm</label><input type="checkbox" id="is_stormy"></div>
    <h2>Rain</h2>
    <div class="row"><label>Rain (mm/h)</label><input type="range" id="rain_mm_h" min="0" max="10" step="0.5"><output></output></div>
    <div class="row"><label>Puddles (mm)</label><input type="range" id="puddle_mm" min="0" max="15" step="0.5"><output></output></div>
    <div class="row"><label>Ground wet</label><input type="checkbox" id="ground_wet"></div>
    <h2>Snow and cold</h2>
    <div class="row"><label>Temperature °C</label><input type="range" id="temp_c" min="-15" max="35" step="1"><output></output></div>
    <div class="row"><label>Snowfall (cm/h)</label><input type="range" id="snowfall_cm_h" min="0" max="5" step="0.1"><output></output></div>
    <div class="row"><label>Snow on ground</label><input type="range" id="snow_depth_cm" min="0" max="30" step="0.5"><output></output></div>
    <div class="row"><label>Snow on roofs</label><input type="range" id="roof_snow_cm" min="0" max="12" step="0.5"><output></output></div>
    <h2>Moon</h2>
    <div class="row"><label>Moon is up</label><input type="checkbox" id="moon_up"></div>
    <div class="row"><label>Lit</label><input type="range" id="moon_illum" min="0" max="1" step="0.01"><output></output></div>
    <div class="row"><label>Direction</label><div class="seg" id="moon_waxing"></div></div>
    <p class="hint">The picture is the panel simulation: the same dithering to six inks the frame does. Save a layer in Photoshop and it re-renders by itself.</p>
  </div>
  <div class="view">
    <div class="seg" style="margin-bottom:8px"><button id="vPanel" class="on">As the panel shows it</button><button id="vColor">Full color</button></div>
    <img id="img" alt="painting preview">
    <div class="info">
      <div><b>Drawn, bottom to top</b><div class="chips" id="layers"></div></div>
      <div><b>Wanted here but not painted yet</b><div class="chips missing" id="missing"></div></div>
    </div>
  </div>
</main></section>
<section id="grid"></section>
<script>
const SEASON_TEMPS = __SEASON_TEMPS__, SEASONS = Object.keys(SEASON_TEMPS), PHASES = ["dawn","day","dusk","night"];
let state = __DEFAULT__, view = "panel", last = null, version = null, gridBuilt = false;
const $ = id => document.getElementById(id);

function seg(id, values, labels, key) {
  const el = $(id);
  values.forEach((v, i) => {
    const b = document.createElement("button");
    b.textContent = labels[i];
    b.onclick = () => { state[key] = v; if (key === "season") state.temp_c = SEASON_TEMPS[v]; sync(); go(); };
    b.dataset.v = JSON.stringify(v); el.appendChild(b);
  });
}
seg("season", SEASONS, SEASONS.map(s => s[0].toUpperCase() + s.slice(1)), "season");
seg("phase", PHASES, ["Dawn","Day","Dusk","Night"], "phase");
seg("moon_waxing", [true,false], ["Waxing","Waning"], "moon_waxing");

const sliders = ["cloud_cover","rain_mm_h","puddle_mm","temp_c","snowfall_cm_h","snow_depth_cm","roof_snow_cm","moon_illum"];
const checks = ["is_foggy","is_stormy","ground_wet","moon_up"];
sliders.forEach(k => $(k).oninput = e => { state[k] = +e.target.value; sync(); go(); });
checks.forEach(k => $(k).onchange = e => { state[k] = e.target.checked; go(); });

function sync() {
  sliders.forEach(k => { $(k).value = state[k]; $(k).nextElementSibling.textContent = state[k]; });
  checks.forEach(k => $(k).checked = !!state[k]);
  for (const [id, key] of [["season","season"],["phase","phase"],["moon_waxing","moon_waxing"]])
    [...$(id).children].forEach(b => b.classList.toggle("on", b.dataset.v === JSON.stringify(state[key])));
}

let timer = null, inflight = false, queued = false;
function go() { clearTimeout(timer); timer = setTimeout(render, 120); }
async function render() {
  if (inflight) { queued = true; return; }
  inflight = true; $("img").classList.add("busy");
  try {
    const r = await fetch("/render", {method:"POST", body: JSON.stringify(state)});
    last = await r.json(); show();
  } finally {
    inflight = false; $("img").classList.remove("busy");
    if (queued) { queued = false; render(); }
  }
}
function chips(el, items, empty) { el.innerHTML = items.length ? items.map(t => `<span>${t}</span>`).join("") : `<span style="background:none">${empty}</span>`; }
function show() {
  if (!last) return;
  $("img").src = view === "panel" ? last.panel : last.color;
  chips($("layers"), last.layers, "nothing");
  chips($("missing"), last.missing, "none");
}
$("vPanel").onclick = () => { view = "panel"; $("vPanel").classList.add("on"); $("vColor").classList.remove("on"); show(); };
$("vColor").onclick = () => { view = "color"; $("vColor").classList.add("on"); $("vPanel").classList.remove("on"); show(); };

async function loadPresets() {
  const p = await (await fetch("/presets")).json();
  $("sceneName").textContent = p.scene;
  const sel = $("preset");
  for (const [group, items] of [["Every combination", p.combos], ["Scenario files", p.scenarios]]) {
    const g = document.createElement("optgroup"); g.label = group;
    items.forEach(([id, title]) => { const o = document.createElement("option"); o.value = id; o.textContent = title; g.appendChild(o); });
    sel.appendChild(g);
  }
  sel.onchange = async () => {
    if (!sel.value) return;
    state = await (await fetch("/preset?id=" + encodeURIComponent(sel.value))).json();
    sel.value = ""; showOne(); sync(); go();
  };
}

function showOne() { $("one").style.display = ""; $("grid").style.display = "none"; $("tabOne").classList.add("on"); $("tabAll").classList.remove("on"); }
$("tabOne").onclick = showOne;
$("tabAll").onclick = async () => {
  $("one").style.display = "none"; $("grid").style.display = "block";
  $("tabAll").classList.add("on"); $("tabOne").classList.remove("on");
  if (!gridBuilt) buildGrid();
};
async function buildGrid() {
  gridBuilt = true;
  const p = await (await fetch("/presets")).json();
  const grid = $("grid"); grid.innerHTML = "<p class='hint'>Rendered as the panel shows them. Click one to open it with the controls.</p>";
  let section = null, current = null;
  const queue = [];
  p.combos.forEach(([id, title]) => {
    const season = id.split("_")[0];
    if (season !== current) {
      current = season;
      const h = document.createElement("h3"); h.textContent = season[0].toUpperCase() + season.slice(1); grid.appendChild(h);
      section = document.createElement("div"); section.className = "cells"; grid.appendChild(section);
    }
    const cell = document.createElement("div"); cell.className = "cell";
    cell.innerHTML = `<img alt=""><div>${title.split(": ")[1]}</div>`;
    cell.onclick = async () => { state = await (await fetch("/preset?id=" + id)).json(); showOne(); sync(); go(); };
    section.appendChild(cell); queue.push([cell.querySelector("img"), id]);
  });
  const v = version;
  const worker = async () => { while (queue.length) { const [img, id] = queue.shift(); img.src = `/thumb?id=${id}&v=${v}`; await new Promise(r => { img.onload = img.onerror = r; }); } };
  await Promise.all([worker(), worker(), worker()]);
}

async function watch() {
  try {
    const v = (await (await fetch("/version")).json()).version;
    if (version !== null && v !== version) { version = v; render(); gridBuilt = false; if ($("grid").style.display === "block") buildGrid(); }
    version = v;
  } catch (e) {}
  setTimeout(watch, 1500);
}
loadPresets(); sync(); render(); watch();
</script></body></html>
"""

# the controls start from this
START = {"season": "summer", "phase": "day", "cloud_cover": 10, "is_foggy": False, "is_stormy": False,
         "rain_mm_h": 0, "puddle_mm": 0, "ground_wet": False, "temp_c": 20, "snowfall_cm_h": 0,
         "snow_depth_cm": 0, "roof_snow_cm": 0, "moon_up": True, "moon_illum": 0.5, "moon_waxing": True}
CONTROLLED = list(START)


def _from_page(data: dict) -> dict:
    s = {k: data[k] for k in CONTROLLED if k in data}
    s["month"] = SEASONS.get(s.get("season"), (6, 0))[0]
    return complete(s)


def _to_page(state: dict) -> dict:
    return {k: state.get(k, START[k]) for k in CONTROLLED}


def make_handler(cfg):
    root = Path(cfg["_root"])
    all_combos = {name: (title, st) for name, title, st in combos(plausible_only=True)}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj):
            self._send(200, json.dumps(obj).encode(), "application/json")

        def do_GET(self):
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path == "/":
                page = (PAGE.replace("__SEASON_TEMPS__", json.dumps({k: t for k, (_, t) in SEASONS.items()}))
                        .replace("__DEFAULT__", json.dumps(START)))
                self._send(200, page.encode(), "text/html; charset=utf-8")
            elif url.path == "/version":
                self._json({"version": _scene_version(_scene_dir(cfg))})
            elif url.path == "/presets":
                self._json({"scene": _scene_dir(cfg).name,
                            "combos": [[n, t] for n, (t, _) in all_combos.items()],
                            "scenarios": [[n, n.replace("_", " ")] for n in _scenarios(root)]})
            elif url.path == "/preset":
                pid = q.get("id", "")
                if pid in all_combos:
                    self._json(_to_page(all_combos[pid][1]))
                elif pid in _scenarios(root):
                    self._json(_to_page(scenario_state(_scenarios(root)[pid])))
                else:
                    self._send(404, b"unknown preset", "text/plain")
            elif url.path == "/thumb":
                pid = q.get("id", "")
                if pid not in all_combos:
                    return self._send(404, b"unknown", "text/plain")
                out = _render(cfg, all_combos[pid][1])
                self._send(200, _png(out["panel"], 480), "image/png")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if urlparse(self.path).path != "/render":
                return self._send(404, b"not found", "text/plain")
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            out = _render(cfg, _from_page(data))
            url = lambda img: "data:image/png;base64," + base64.b64encode(_png(img)).decode()
            self._json({"panel": url(out["panel"]), "color": url(out["color"]),
                        "layers": out["layers"], "missing": out["missing"]})

        def log_message(self, fmt, *args):
            pass

    return Handler


def studio(cfg: dict, port: int = 8765, open_browser: bool = True) -> None:
    folder = _scene_dir(cfg)
    if not (folder / "scene.yaml").exists():
        raise SystemExit(f"no scene.yaml in {folder}")
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(cfg))
    url = f"http://127.0.0.1:{port}/"
    print(f"Painting Studio for {folder.name}: {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
