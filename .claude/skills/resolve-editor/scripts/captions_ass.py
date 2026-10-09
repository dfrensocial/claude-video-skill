#!/usr/bin/env python3
"""Turn captions.json (from captions.py) into animated, styled captions: ASS file, burn-in, or an alpha overlay.

  captions_ass.py captions.json --out captions.ass [--font "Bebas Neue" | --font-file X.ttf] [--text-colour #FFFFFF]
                  [--accent #E8AA05] [--size 110] [--y-pct 34] [--paid] [--anim pop|slide|fade|none] [--w 1080 --h 1920]
  captions_ass.py captions.json --burn VIDEO --out out.mp4 ...     burn captions into a video (preview / no-Resolve path)
  captions_ass.py captions.json --overlay out.mov --duration SECONDS ...   transparent ProRes 4444 overlay for a Resolve track

Animation (what the `word-pop-caption` preset describes): each caption pops in over ~6 frames (scale 82 -> 100 %, blur 6 -> 0,
fade-in), emphasised words are larger and use the accent colour, a short fade-out, heavy outline + soft shadow for legibility,
text kept inside the platform safe box (organic y 150-1520 / paid y 270-1250 on 1080x1920). Fonts are given as a family name
(or a font file, whose family name is read from it); fonts folders are passed to libass so user-installed fonts work.
Tamil text is shaped by libass/HarfBuzz; use a Tamil-capable font for Tamil events (--tamil-font).
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import load_json  # noqa: E402

FONT_DIRS = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
             Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"]


def ass_colour(hexstr, alpha=0):
    h = hexstr.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}&".upper().replace("&H", "&H")


def family_of(font_file):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(str(font_file), 40).getname()[0]
    except Exception:  # noqa: BLE001
        return Path(font_file).stem


def has_tamil(s):
    return any("\u0b80" <= c <= "\u0bff" for c in s)


def ts(t):
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def build_ass(events, w=1080, h=1920, font="Arial", tamil_font="Nirmala UI", text="#FFFFFF", accent="#E8AA05",
              size=110, y_pct=34, paid=False, anim="pop", outline=None, emph_scale=1.22):
    lo, hi = (270, 1250) if paid else (150, 1520)
    y = int(max(lo + size, min(h * y_pct / 100.0, hi - size)))
    ol = outline if outline is not None else max(4, size // 14)
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},{ass_colour(text)},{ass_colour(text)},&H00000000&,&H99000000&,-1,0,0,0,100,100,0,0,1,{ol},3,5,60,60,0,1
Style: Tam,{tamil_font},{size},{ass_colour(text)},{ass_colour(text)},&H00000000&,&H99000000&,-1,0,0,0,100,100,0,0,1,{ol},3,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for e in events:
        words = e["words"]
        style = "Tam" if any(has_tamil(wd) for wd in words) else "Cap"
        parts = []
        for i, wd in enumerate(words):
            wd = wd.replace("\\", "").replace("{", "(").replace("}", ")")
            if i in e.get("emph", []):
                parts.append(f"{{\\c{ass_colour(accent)}\\fscx{int(emph_scale * 100)}\\fscy{int(emph_scale * 100)}}}{wd}"
                             f"{{\\c{ass_colour(text)}\\fscx100\\fscy100}}")
            else:
                parts.append(wd)
        body = " ".join(parts)
        dur_ms = int((e["end"] - e["start"]) * 1000)
        pop_ms = min(180, max(60, dur_ms // 3))
        if anim == "pop":
            fx = (f"{{\\an5\\pos({w // 2},{y})\\fscx82\\fscy82\\blur6\\t(0,{pop_ms},\\fscx100\\fscy100\\blur0)"
                  f"\\fad(40,50)}}")
        elif anim == "slide":
            fx = f"{{\\an5\\move({w // 2},{y + 60},{w // 2},{y},0,{pop_ms})\\fad(40,50)}}"
        elif anim == "fade":
            fx = f"{{\\an5\\pos({w // 2},{y})\\fad(80,60)}}"
        else:
            fx = f"{{\\an5\\pos({w // 2},{y})}}"
        sub = ""
        if e.get("sub"):
            sub = f"\\N{{\\fs{int(size * 0.35)}\\c{ass_colour(accent)}}}{e['sub']}"
        lines.append(f"Dialogue: 0,{ts(e['start'])},{ts(e['end'])},{style},,0,0,0,,{fx}{body}{sub}")
    return head + "\n".join(lines) + "\n"


def fontsdir_arg():
    dirs = [str(d) for d in FONT_DIRS if d.is_dir()]
    # libass takes one fontsdir: prefer the user's font folder (custom fonts); system fonts are found by fontconfig
    user = [d for d in dirs if "Microsoft\\Windows\\Fonts" in d or "Microsoft/Windows/Fonts" in d]
    return (user or dirs)[0] if dirs else None


def esc_filter_path(p):
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def sub_filter(ass_path):
    fd = fontsdir_arg()
    f = f"subtitles='{esc_filter_path(ass_path)}'"
    if fd:
        f += f":fontsdir='{esc_filter_path(fd)}'"
    return f


def burn(video, ass_path, out):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vf", sub_filter(ass_path), "-c:v", "libx264", "-crf", "18",
                    "-preset", "fast", "-c:a", "copy", str(out)], check=True)


def overlay(ass_path, out, duration, w=1080, h=1920, fps=30):
    """Transparent ProRes 4444. libass does not write alpha, so render the captions on black (B) and on white (W):
    for a pixel of alpha a and colour c, B = a*c and W = a*c + (1-a)*255, hence a = 1 - (W-B)/255 and c = B/a."""
    sf = sub_filter(ass_path)
    graph = (f"[0:v]format=gbrp,{sf},format=gbrp,split[b1][b2];[1:v]format=gbrp,{sf},format=gbrp[w];"
             f"[w][b1]blend=all_mode=subtract,format=gbrp,extractplanes=g,negate,"
             f"geq=lum='if(gte(X,W-12),0,lum(X,Y))',split[a1][a2];"  # libass leaves an artefact column at the right edge
             f"[b2]format=gbrp[bp];[bp][a1]unpremultiply[c];[c]format=gbrp[cc];[cc][a2]alphamerge,format=yuva444p10le[v]")
    subprocess.run(["ffmpeg", "-y", "-v", "error",
                    "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={fps}:d={duration}",
                    "-f", "lavfi", "-i", f"color=c=white:s={w}x{h}:r={fps}:d={duration}",
                    "-filter_complex", graph, "-map", "[v]", "-c:v", "prores_ks", "-profile:v", "4444",
                    "-pix_fmt", "yuva444p10le", str(out)], check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("captions")
    ap.add_argument("--out", help="output .ass (or the burned video with --burn); not needed with --overlay")
    ap.add_argument("--burn")
    ap.add_argument("--overlay")
    ap.add_argument("--duration", type=float)
    ap.add_argument("--font", default=None)
    ap.add_argument("--font-file")
    ap.add_argument("--tamil-font", default="Nirmala UI")
    ap.add_argument("--text-colour", default="#FFFFFF")
    ap.add_argument("--accent", default="#E8AA05")
    ap.add_argument("--size", type=int, default=110)
    ap.add_argument("--y-pct", type=float, default=34)
    ap.add_argument("--paid", action="store_true")
    ap.add_argument("--anim", default="pop", choices=["pop", "slide", "fade", "none"])
    ap.add_argument("--w", type=int, default=1080)
    ap.add_argument("--h", type=int, default=1920)
    a = ap.parse_args()
    d = load_json(a.captions, {}) or {}
    font = family_of(a.font_file) if a.font_file else (a.font or "Arial")
    ass = build_ass(d.get("events", []), a.w, a.h, font, a.tamil_font, a.text_colour, a.accent, a.size, a.y_pct, a.paid, a.anim)
    if a.burn:
        p = Path(a.out).with_suffix(".ass")
        p.write_text(ass, encoding="utf-8")
        burn(a.burn, p, a.out)
        print(a.out)
    elif a.overlay:
        p = Path(a.overlay).with_suffix(".ass")
        p.write_text(ass, encoding="utf-8")
        dur = a.duration or (d.get("stats", {}).get("duration") or max(e["end"] for e in d["events"]) + 0.5)
        overlay(p, a.overlay, dur, a.w, a.h)
        print(a.overlay)
    else:
        if not a.out:
            raise SystemExit("--out required")
        Path(a.out).write_text(ass, encoding="utf-8")
        print(a.out)


if __name__ == "__main__":
    main()
