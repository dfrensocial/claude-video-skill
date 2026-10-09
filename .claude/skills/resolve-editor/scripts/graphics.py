#!/usr/bin/env python3
"""Render motion-graphic cards (HyperFrames templates in <workspace>/graphics/cards/*.html) with per-job variables.

  graphics.py list                                  templates + their variables and defaults
  graphics.py render TEMPLATE [--var k=v ...] [--vars-json '{...}'] [--palette palette.json --option 0]
                     [--out file.mov] [--format mov|webm|mp4] [--quality draft|looks|delivery] [--show-s 3.0]
  graphics.py batch jobs.json                       [{"template":..., "vars":{...}, "out":...}, ...] rendered one by one

Templates: count-up, info-card, ring-percent, compare-card (each 1080x1920, transparent background unless plate_mode=full), fire-wipe (WebGL flame transition; dur/dir/band/seed/heat), typo (one kinetic-typography + HUD layer from a JSON events list; see references/director-playbook.md).
Colours: pass --palette (palette.py output) and --option N to fill text/accent/plate; explicit --var values win.
Output: a transparent ProRes 4444 .mov (default) that compose.py places as a `normal` overlay, or webm/mp4.
Rules: every number/claim comes from the brief verbatim (never invent statistics); `grouping` = western|indian for digits;
`show_s` sets how long the card stays before its exit animation, the file is a fixed 5-6 s long, so give the overlay
`dur` = show_s + 0.4 in the compose spec.
Needs Node + the `hyperframes` CLI (npx) and Chrome (checked by `npx hyperframes doctor`). Fonts: Bebas Neue + Montserrat
(OFL) shipped in graphics/assets/fonts.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import find_workspace, load_json  # noqa: E402


def gdir():
    return find_workspace() / "graphics"


def template_vars(path):
    txt = Path(path).read_text(encoding="utf-8")
    m = re.search(r"data-composition-variables='(\[.*?\])'", txt, re.S)
    return json.loads(m.group(1)) if m else []


def cmd_list(a):
    for p in sorted((gdir() / "cards").glob("*.html")):
        print(f"\n{p.stem}")
        for v in template_vars(p):
            print(f"   {v['id']:<14} {v['type']:<7} default={v['default']!r}  # {v['label']}")


def parse_value(v):
    try:
        return json.loads(v)
    except Exception:  # noqa: BLE001
        return v


def card_colours(opt, plate_mode, declared):
    """Map a palette option to card colours WITH a contrast check (the first version painted ring, plate and text in
    near-identical colours and the ring vanished). Full/card plates: the plate takes the option's plate colour, text is
    whichever of near-black/white reads better on it, the accent is the first candidate with contrast >= 3 against the
    plate. Transparent cards (plate_mode none, e.g. count-up) sit on footage: keep the option's text/accent as given."""
    from palette import contrast, rgb
    out = {}
    plate = opt.get("plate") or opt.get("accent") or "#E8AA05"
    if str(plate_mode) in ("full", "card"):
        text = "#111111" if contrast(rgb("#111111"), rgb(plate)) >= contrast(rgb("#FFFFFF"), rgb(plate)) else "#FFFFFF"
        accent = next((c for c in (opt.get("accent2"), opt.get("accent"), "#C8171E", "#111111", "#FFFFFF", "#1DB954")
                       if c and contrast(rgb(c), rgb(plate)) >= 3.0 and c.lower() != plate.lower()), text)
        cand = {"plate": plate, "text": text, "accent": accent, "card": "#FFFFFF" if text == "#111111" else "#1B1B1B"}
    else:
        cand = {"text": opt.get("text", "#FFFFFF"), "accent": opt.get("accent", "#E8AA05")}
    for k, v in cand.items():
        if k in declared:
            out[k] = v
    return out


def render(template, variables, out, fmt="mov", quality="looks", palette=None, option=0, show_s=None):
    g = gdir()
    src = g / "cards" / f"{template}.html"
    if not src.exists():
        raise SystemExit(f"no template {template}; try: graphics.py list")
    declared = {v["id"]: v for v in template_vars(src)}
    merged = {}
    if palette:
        pal = load_json(palette, {}) or {}
        opts = pal.get("options") or []
        if opts:
            eff_mode = variables.get("plate_mode", declared.get("plate_mode", {}).get("default"))
            merged.update(card_colours(opts[min(option, len(opts) - 1)], eff_mode, declared))
    merged.update(variables)
    if show_s is not None and "show_s" in declared:
        merged["show_s"] = show_s
    unknown = [k for k in merged if k not in declared]
    if unknown:
        print(f"[warn] unknown variables ignored by the template: {unknown}", file=sys.stderr)
    out = (Path(out) if out else (find_workspace() / "jobs" / "graphics" / f"{template}.{fmt}")).resolve()  # renderer runs in graphics/
    out.parent.mkdir(parents=True, exist_ok=True)
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        raise SystemExit("npx not found (Node required)")
    vf = Path(tempfile.mkdtemp()) / "vars.json"
    vf.write_text(json.dumps(merged), encoding="ascii", errors="ignore") if all(ord(c) < 128 for c in json.dumps(merged)) \
        else vf.write_text(json.dumps(merged), encoding="utf-8")
    cmd = [npx, "--yes", "hyperframes", "render", str(g), "--composition", f"cards/{template}.html", "--format", fmt,
           "-q", quality, "-o", str(out), "--variables-file", str(vf), "--quiet"]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(g))
    if r.returncode != 0 or not out.exists():
        raise SystemExit(f"render failed ({r.returncode}):\n{(r.stdout + r.stderr)[-1500:]}")
    return {"template": template, "file": str(out), "format": fmt, "variables": merged,
            "overlay_dur_hint": round(float(merged.get('show_s', declared.get('show_s', {}).get('default', 3.0))) + 0.4, 2)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("render")
    p.add_argument("template"); p.add_argument("--var", action="append", default=[]); p.add_argument("--vars-json")
    p.add_argument("--palette"); p.add_argument("--option", type=int, default=0); p.add_argument("--out")
    p.add_argument("--format", default="mov", choices=["mov", "webm", "mp4"])
    p.add_argument("--quality", default="looks", choices=["draft", "looks", "delivery"]); p.add_argument("--show-s", type=float)
    p = sub.add_parser("batch"); p.add_argument("jobs")
    a = ap.parse_args()
    if a.cmd == "list":
        cmd_list(a)
    elif a.cmd == "render":
        vs = json.loads(a.vars_json) if a.vars_json else {}
        for kv in a.var:
            k, _, v = kv.partition("=")
            vs[k] = parse_value(v)
        print(json.dumps(render(a.template, vs, a.out, a.format, a.quality, a.palette, a.option, a.show_s), indent=1))
    else:
        for j in load_json(a.jobs, []):
            print(json.dumps(render(j["template"], j.get("vars", {}), j.get("out"), j.get("format", "mov"),
                                    j.get("quality", "looks"), j.get("palette"), j.get("option", 0), j.get("show_s")), indent=1))


if __name__ == "__main__":
    main()
