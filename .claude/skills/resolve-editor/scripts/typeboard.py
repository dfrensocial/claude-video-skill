#!/usr/bin/env python3
"""Type + colour look-board: try fonts and colour pairs on a REAL frame before committing to a style.

  typeboard.py --frame VIDEO[@seconds] --text "Business Start" [--emph 1] --fonts "bebas,barlow condensed,druk,bangers"
               [--pairs "#FFFFFF/#E8AA05;#FFFFFF/#C8171E"] [--palette-from VIDEO] [--tamil "..."] [--sheet out.jpg]
  typeboard.py --list-fonts [--q montserrat]

* Fonts are matched by keyword against the installed font files (Windows Fonts + the user's font folder); heavy weights
  are preferred. Each tile shows the caption inside the platform's safe box (organic y 150-1520 / paid y 270-1250 on 1080x1920).
* --emph N: index of the word drawn in the accent colour (second colour of the pair); the rest uses the first colour.
* --pairs: `text/accent` hex pairs separated by `;`. With --palette-from, pairs are proposed from that video's palette.
* Output: a numbered contact sheet and JSON {tile: font file, colours}, so the choice can be written to the brand kit
  (fonts.heading, fonts.files, captions.highlight_color) and `kb.py feedback`.
Rendering is PIL text with stroke + soft shadow: close to Text+ but not identical; confirm in Resolve.
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import contact_sheet, extract_frame, probe_summary  # noqa: E402

FONT_DIRS = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
             Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"]
HEAVY = ("black", "extrabold", "heavy", "bold", "xbold", "ultra")


def all_fonts():
    out = []
    for d in FONT_DIRS:
        if d.is_dir():
            out += [p for p in d.iterdir() if p.suffix.lower() in (".ttf", ".otf")]
    return out


def find_font(keyword, fonts):
    k = keyword.lower().replace(" ", "")
    hits = [p for p in fonts if k in p.stem.lower().replace(" ", "").replace("-", "").replace("_", "")]
    if not hits:
        return None
    hits.sort(key=lambda p: (not any(h in p.stem.lower() for h in HEAVY), "italic" in p.stem.lower(), len(p.stem)))
    return hits[0]


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def draw_caption(img, text, font_path, col, acc, emph, y_frac):
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    W, H = img.size
    size = int(W * 0.13)
    font = ImageFont.truetype(str(font_path), size)
    words = text.split()
    # fit: shrink until the line fits 88 % of the width
    while size > 14:
        line_w = sum(font.getlength(w + " ") for w in words)
        if line_w < W * 0.88:
            break
        size -= 2
        font = ImageFont.truetype(str(font_path), size)
    x = (W - sum(font.getlength(w + " ") for w in words)) / 2
    y = H * y_frac
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    cx = x
    for i, w in enumerate(words):
        sd.text((cx + 3, y + 5), w, font=font, fill=(0, 0, 0, 190))
        cx += font.getlength(w + " ")
    shadow = shadow.filter(ImageFilter.GaussianBlur(4))
    img = Image.alpha_composite(img.convert("RGBA"), shadow)
    d = ImageDraw.Draw(img)
    cx = x
    for i, w in enumerate(words):
        fill = acc if i == emph else col
        d.text((cx, y), w, font=font, fill=fill + (255,), stroke_width=max(2, size // 22), stroke_fill=(0, 0, 0, 255))
        cx += font.getlength(w + " ")
    return img.convert("RGB")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--frame")
    ap.add_argument("--text", default="Business Start")
    ap.add_argument("--emph", type=int, default=1)
    ap.add_argument("--fonts", default="bebas,barlow condensed,bangers")
    ap.add_argument("--pairs", default="#FFFFFF/#E8AA05")
    ap.add_argument("--palette-from")
    ap.add_argument("--tamil")
    ap.add_argument("--sheet", default="jobs/typeboard.jpg")
    ap.add_argument("--paid", action="store_true", help="draw inside the stricter paid-Meta safe box")
    ap.add_argument("--list-fonts", action="store_true")
    ap.add_argument("--q", default="")
    a = ap.parse_args()
    fonts = all_fonts()
    if a.list_fonts:
        for p in sorted(fonts, key=lambda p: p.stem.lower()):
            if a.q.lower() in p.stem.lower():
                print(p.name)
        return
    if not a.frame:
        raise SystemExit("--frame VIDEO[@seconds] required")
    vid, _, ts = a.frame.partition("@")
    info = probe_summary(vid)
    t = float(ts) if ts else info["duration"] * 0.4
    tmp = Path(tempfile.mkdtemp())
    base = tmp / "base.jpg"
    extract_frame(vid, t, base, width=540)
    from PIL import Image
    pairs = [tuple(x.split("/")) for x in a.pairs.split(";") if x]
    if a.palette_from:
        from ingest_references import palette
        pal = [c["hex"] for c in palette(a.palette_from, 5, True, 60)]
        pairs += [("#FFFFFF", c) for c in pal[:3]] + [("#111111", c) for c in pal[3:5]]
    y_frac = (0.30 if a.paid else 0.20) if True else 0.2  # inside the safe box on a 9:16 frame
    tiles, meta = [], []
    for kw in [k.strip() for k in a.fonts.split(",") if k.strip()]:
        fp = find_font(kw, fonts)
        if not fp:
            meta.append({"font": kw, "error": "not installed"})
            continue
        for col, acc in pairs:
            img = draw_caption(Image.open(base).convert("RGB"), a.tamil if a.tamil and "noto" in kw else a.text, fp,
                               hex_rgb(col), hex_rgb(acc), a.emph, y_frac)
            f = tmp / f"t{len(tiles):02d}.jpg"
            img.save(f, quality=90)
            tiles.append(str(f))
            meta.append({"tile": len(tiles), "keyword": kw, "font_file": str(fp), "text_colour": col, "accent": acc})
    if not tiles:
        raise SystemExit("no fonts matched; try --list-fonts --q <name>")
    Path(a.sheet).parent.mkdir(parents=True, exist_ok=True)
    contact_sheet(tiles, a.sheet, cols=min(len(tiles), 4), thumb_w=360)
    print(json.dumps({"sheet": a.sheet, "tiles": meta, "time_s": round(t, 2)}, indent=1))


if __name__ == "__main__":
    main()
