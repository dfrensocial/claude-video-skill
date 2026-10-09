#!/usr/bin/env python3
"""Per-video colour palettes (no fixed brand colour): propose accent/text/plate options that suit THIS footage and the style.

  palette.py --video FILE [--style STYLE_ID] [--count 3] [--out jobs/NAME/palette.json] [--board]

How it chooses: samples the footage palette (dominant colours), then scores a curated accent set (the accents seen in the
studio references plus a few extras) by (1) hue distance from the footage's dominant hues (so captions do not melt into the
background), (2) WCAG contrast of the accent against the footage's mean brightness, (3) closeness to the style's own palette
(styles/*.json colour.palette) as a mild bonus. It returns distinct options (hues >= 40 deg apart) with roles:
  text (usually white, or near-black on bright footage), accent (emphasis word, glow, bars), accent2 (analogous support),
  plate (colour for info-card backgrounds), outline. --board renders a typeboard sheet of the options on a frame.
Heuristics, not taste: look at the board and pick; tell me the choice and it is remembered (kb.py feedback --scope style/client).
"""
import argparse
import colorsys
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import find_workspace, load_json, probe_summary, save_json  # noqa: E402

ACCENTS = {  # name: hex (the first group appears in the studio's references)
    "yellow": "#E8AA05", "red": "#C8171E", "lime": "#B8FF3B", "cyan": "#1ED3E8", "magenta": "#E01E8C",
    "orange": "#FF6A1F", "electric-blue": "#2F6BFF", "mint": "#3CE6A8", "hot-pink": "#FF3D81", "cream": "#F2E9D0",
    "violet": "#8A5CFF", "gold": "#FFC933",
}


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def hexs(c):
    return "#%02X%02X%02X" % tuple(int(round(max(0, min(1, x)) * 255)) for x in c)


def lum(c):
    def f(v):
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (f(x) for x in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def hue(c):
    return colorsys.rgb_to_hsv(*c)[0] * 360.0


def hdist(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def footage_colours(video):
    from ingest_references import palette
    info = probe_summary(video)
    pal = palette(video, 5, True, min(info["duration"], 40))
    return [(rgb(p["hex"]), p["pct"]) for p in pal]


def build(video, style_id=None, count=3):
    pal = footage_colours(video)
    if not pal:
        raise SystemExit("could not sample the footage palette (needs numpy + ffmpeg)")
    mean = tuple(sum(c[i] * w for c, w in pal) / sum(w for _, w in pal) for i in range(3))
    chroma = [(c, w) for c, w in pal if colorsys.rgb_to_hsv(*c)[1] > 0.25 and colorsys.rgb_to_hsv(*c)[2] > 0.2]
    dom_hues = [hue(c) for c, _ in chroma] or [hue(mean)]
    style_pal = []
    if style_id:
        s = load_json(find_workspace() / "styles" / f"{style_id}.json", {}) or {}
        style_pal = [rgb(h) for h in s.get("colour", {}).get("palette", []) if h.startswith("#") and len(h) == 7]
    scored = []
    for name, hx in ACCENTS.items():
        c = rgb(hx)
        hd = min(hdist(hue(c), h) for h in dom_hues)
        cr = contrast(c, mean)
        st = 0.0
        if style_pal:
            st = max(0.0, 1.0 - min(sum((a - b) ** 2 for a, b in zip(c, p)) ** 0.5 for p in style_pal) / 0.8)
        # reward being far from footage hues (cap at 120 deg), readable against the mean brightness, and matching the style
        score = min(hd, 120) / 120 * 2.0 + min(cr, 7) / 7 * 1.5 + st * 1.0
        scored.append((score, name, hx, hd, cr))
    scored.sort(reverse=True)
    chosen = []
    for sc, name, hx, hd, cr in scored:
        if all(hdist(hue(rgb(hx)), hue(rgb(o["accent"]))) >= 40 for o in chosen):
            h, s_, v = colorsys.rgb_to_hsv(*rgb(hx))
            ana = colorsys.hsv_to_rgb((h + 30 / 360) % 1, s_, v)
            dark = mean and lum(mean) < 0.35
            text = (1, 1, 1) if dark or contrast((1, 1, 1), mean) >= contrast((0.07, 0.07, 0.07), mean) else (0.07, 0.07, 0.07)
            plate = colorsys.hsv_to_rgb(h, 0.9, 0.95) if name not in ("cream",) else rgb("#F2E9D0")
            chosen.append({"name": name, "accent": hx, "accent2": hexs(ana), "text": hexs(text), "plate": hexs(plate),
                           "outline": "#000000" if lum(text) > 0.5 else "#FFFFFF", "score": round(sc, 2),
                           "hue_gap_to_footage_deg": round(hd), "accent_vs_footage_contrast": round(cr, 1),
                           "text_vs_footage_contrast": round(contrast(text, mean), 1)})
        if len(chosen) >= count:
            break
    return {"video": str(video), "style": style_id, "footage_palette": [hexs(c) for c, _ in pal], "footage_mean": hexs(mean),
            "options": chosen, "note": "Heuristic ranking: look at the board and choose; the choice can be remembered with kb.py."}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", required=True)
    ap.add_argument("--style")
    ap.add_argument("--count", type=int, default=3)
    ap.add_argument("--out")
    ap.add_argument("--board", action="store_true")
    ap.add_argument("--fonts", default="bebas,montserrat,barlow condensed")
    ap.add_argument("--text", default="Business Start")
    a = ap.parse_args()
    res = build(a.video, a.style, a.count)
    if a.out:
        save_json(a.out, res)
    print(json.dumps(res, indent=1))
    if a.board:
        import subprocess
        pairs = ";".join(f"{o['text']}/{o['accent']}" for o in res["options"])
        sheet = str(Path(a.out).with_suffix(".jpg")) if a.out else "jobs/palette-board.jpg"
        subprocess.run([sys.executable, str(Path(__file__).parent / "typeboard.py"), "--frame", a.video, "--text", a.text,
                        "--fonts", a.fonts, "--pairs", pairs, "--sheet", sheet], check=False, capture_output=True)
        print("board:", sheet)


if __name__ == "__main__":
    main()
