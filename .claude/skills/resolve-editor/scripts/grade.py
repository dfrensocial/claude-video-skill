#!/usr/bin/env python3
"""Colour: measure footage, suggest a primary correction (CDL), and PREVIEW it (and LUTs) before touching Resolve.

  grade.py analyze FILE [--samples 12] [--out analysis.json]
  grade.py preview FILE [--time T] [--auto | --cdl "slope r g b; offset r g b; power r g b; sat s"]
                        [--lut PATH.cube] [--all-luts DIR] [--sheet out.jpg]
  grade.py match --target A_ROLL --source B_ROLL            (delegates to color_match.py)

What `analyze` reports (from evenly spaced frames): luma mean, black/white points (p2/p98), contrast, mean RGB cast,
skin-tone hue vs the vectorscope skin line (~123 deg), saturation, and a verdict:
  ok | underexposed | overexposed | flat-contrast | cast | skin-off-line | coloured-bg.
`coloured-bg` = strongly coloured BACKGROUND (mean per-pixel saturation outside skin > 0.38). It cannot tell coloured
light from a coloured wall. The studio's own references keep gel light as the look, so for coloured-bg footage the
suggestion only protects skin and exposure and never neutralises the cast (references/editing-knowledge.md, colour).
The suggested CDL is returned in Resolve's SetCDL shape ({"NodeIndex","Slope","Offset","Power","Saturation"} as strings,
NodeIndex 1-based) so the agent can apply it with TimelineItem.SetCDL. Previews apply the same maths in numpy
(out = (in*slope + offset)^power, then saturation), an approximation of Resolve's CDL, good for choosing, not for final judging.
Heuristics, not magic: always LOOK at the preview sheet; skin detection is a YCbCr mask and can be fooled by wood/walls.
"""
import argparse
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import contact_sheet, extract_frame, probe_summary, save_json  # noqa: E402

SKIN_LINE_DEG = 123.0


def np_():
    import numpy as np
    return np


def load_rgb(path):
    from PIL import Image
    return np_().asarray(Image.open(path).convert("RGB"), dtype=np_().float32) / 255.0


def save_rgb(arr, path):
    from PIL import Image
    np = np_()
    Image.fromarray((np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8)).save(path, quality=92)


def ycbcr(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cb = 0.5 + (-0.168736 * r - 0.331264 * g + 0.5 * b)
    cr = 0.5 + (0.5 * r - 0.418688 * g - 0.081312 * b)
    return y, cb, cr


def skin_mask(rgb):
    y, cb, cr = ycbcr(rgb)
    cb8, cr8 = cb * 255, cr * 255
    return (cb8 > 77) & (cb8 < 127) & (cr8 > 133) & (cr8 < 173) & (y > 0.15) & (y < 0.95)


def hue_deg(rgb_mean):
    y, cb, cr = ycbcr(np_().asarray(rgb_mean, dtype=np_().float32).reshape(1, 1, 3))
    return math.degrees(math.atan2(float(cr[0, 0]) - 0.5, float(cb[0, 0]) - 0.5)) % 360.0


def sat_of(rgb):
    mx, mn = rgb.max(-1), rgb.min(-1)
    return (mx - mn) / (mx + 1e-6)


def grab_frames(path, n, out_dir):
    info = probe_summary(path)
    dur = max(info["duration"], 0.1)
    files = []
    for i in range(n):
        t = dur * (i + 0.5) / n
        f = Path(out_dir) / f"g{i:02d}.jpg"
        extract_frame(path, t, f, width=480)
        files.append(f)
    return files, info


def apply_cdl(rgb, slope, offset, power, sat):
    np = np_()
    out = np.clip(rgb * np.asarray(slope) + np.asarray(offset), 0, 1) ** np.asarray(power)
    y = (0.299 * out[..., 0] + 0.587 * out[..., 1] + 0.114 * out[..., 2])[..., None]
    return np.clip(y + (out - y) * sat, 0, 1)


def analyze(path, samples=12):
    np = np_()
    tmp = tempfile.mkdtemp()
    files, info = grab_frames(path, samples, tmp)
    ys, means, skins, bgsat, bgrgb = [], [], [], [], []
    p2s, p98s = [], []
    for f in files:
        rgb = load_rgb(f)
        y = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
        ys.append(float(y.mean()))
        p2s.append(float(np.percentile(y, 2)))
        p98s.append(float(np.percentile(y, 98)))
        means.append(rgb.reshape(-1, 3).mean(0))
        m = skin_mask(rgb)
        if m.mean() > 0.01:
            skins.append(rgb[m].mean(0))
        nm = (~m) & (rgb.max(-1) > 0.12)  # non-skin, not near-black (black has meaningless saturation)
        if nm.sum() > 50:
            s = sat_of(rgb[nm])
            bgsat.append(float(s.mean()))
            bgrgb.append(rgb[nm].mean(0))
    mean_rgb = np.mean(means, 0)
    luma = float(np.mean(ys))
    p2, p98 = float(np.mean(p2s)), float(np.mean(p98s))
    gray = float(mean_rgb.mean())
    cast = (mean_rgb / (gray + 1e-6)).tolist()
    cast_mag = float(np.abs(np.array(cast) - 1).max())
    skin = np.mean(skins, 0) if skins else None
    skin_hue = hue_deg(skin) if skin is not None else None
    bg_s = float(np.mean(bgsat)) if bgsat else 0.0
    bg_rgb = np.mean(bgrgb, 0) if bgrgb else mean_rgb
    bg_chroma = float((bg_rgb.max() - bg_rgb.min()) / (bg_rgb.max() + 1e-6))
    flags = []
    # Colourful background: coloured light (gel) OR a coloured wall; pixels are per-pixel saturation outside skin,
    # because averaging opposite colours (purple + red + blue) cancels out and hides a strong gel look.
    gel = bg_s > 0.38
    if gel:
        flags.append("coloured-bg")
    if luma < 0.30:
        flags.append("underexposed")
    elif luma > 0.62:
        flags.append("overexposed")
    if p98 - p2 < 0.55:
        flags.append("flat-contrast")
    if not gel and cast_mag > 0.12:
        flags.append("cast")
    if skin_hue is not None and abs(skin_hue - SKIN_LINE_DEG) > 8:
        flags.append("skin-off-line")
    res = {"file": str(path), "samples": len(files), "luma_mean": round(luma, 3), "black_point": round(p2, 3),
           "white_point": round(p98, 3), "mean_rgb": [round(float(x), 3) for x in mean_rgb], "cast_ratio_rgb": [round(c, 3) for c in cast],
           "cast_magnitude": round(cast_mag, 3), "bg_chroma": round(bg_chroma, 3), "skin_found": bool(skins),
           "skin_hue_deg": None if skin_hue is None else round(skin_hue, 1), "skin_line_deg": SKIN_LINE_DEG,
           "saturation_bg": round(bg_s, 3), "flags": flags or ["ok"]}
    res["suggest"] = suggest(res, mean_rgb, skin)
    return res


def suggest(res, mean_rgb, skin):
    """Conservative primary correction as CDL. Never neutralise a gel look; protect skin + exposure."""
    np = np_()
    gel = "coloured-bg" in res["flags"]
    slope = np.ones(3)
    offset = np.zeros(3)
    power = np.ones(3)
    sat = 1.0
    notes = []
    # exposure: move mean luma toward ~0.46 with a power curve (gamma), capped
    luma = res["luma_mean"]
    if abs(luma - 0.46) > 0.05:
        g = math.log(0.46) / math.log(max(min(luma, 0.95), 0.05))
        g = max(0.75, min(1.35, g))
        power[:] = g
        notes.append(f"midtones {'lifted' if luma < 0.46 else 'lowered'} (gamma {g:.2f})")
    # black point: pull a lifted black down, but never crush
    if res["black_point"] > 0.07:
        off = -min(res["black_point"] - 0.03, 0.08)
        offset[:] = off
        notes.append(f"black point {res['black_point']:.2f} -> ~0.03")
    # contrast via slope when flat
    if res["white_point"] < 0.85 and res["white_point"] - res["black_point"] > 0.1:
        s = min(0.92 / max(res["white_point"], 0.1), 1.25)
        slope *= s
        notes.append(f"white point {res['white_point']:.2f} -> ~0.92 (x{s:.2f})")
    if gel:
        notes.append("COLOURED BACKGROUND (gel light or painted wall): cast left alone on purpose; only exposure and skin are corrected. "
                     "If it is an unwanted cast, tell me and I will neutralise it")
    elif res["cast_magnitude"] > 0.06:
        c = np.array(res["cast_ratio_rgb"])
        corr = 1.0 / np.clip(c, 0.85, 1.18)  # limited gray-world: at most ~15 %
        corr = corr / corr.mean()
        slope *= corr
        notes.append(f"cast neutralised (gains R{corr[0]:.2f} G{corr[1]:.2f} B{corr[2]:.2f})")
    # skin: grid-search small R/B gains that move skin hue toward the skin line without wrecking luma
    if skin is not None and abs(res["skin_hue_deg"] - SKIN_LINE_DEG) > 4:
        best, bestd = (1.0, 1.0), abs(res["skin_hue_deg"] - SKIN_LINE_DEG)
        base = np.clip(skin * slope + offset, 0, 1) ** power
        for rg in np.linspace(0.9, 1.1, 21):
            for bg in np.linspace(0.9, 1.1, 21):
                cand = np.clip(base * np.array([rg, 1.0, bg]), 0, 1)
                d = abs(hue_deg(cand) - SKIN_LINE_DEG)
                if d < bestd - 0.2:
                    best, bestd = (rg, bg), d
        if best != (1.0, 1.0):
            slope *= np.array([best[0], 1.0, best[1]])
            notes.append(f"skin hue {res['skin_hue_deg']:.0f} -> ~{SKIN_LINE_DEG + bestd:.0f} deg (R x{best[0]:.2f}, B x{best[1]:.2f})")
    if res["saturation_bg"] < 0.18 and not gel:
        sat = 1.12
        notes.append("slight saturation lift 1.12")
    cdl = {"NodeIndex": "1", "Slope": " ".join(f"{x:.4f}" for x in slope), "Offset": " ".join(f"{x:.4f}" for x in offset),
           "Power": " ".join(f"{x:.4f}" for x in power), "Saturation": f"{sat:.3f}"}
    return {"cdl": cdl, "notes": notes or ["nothing to fix"], "confidence": "medium" if skin is not None else "low (no skin found)"}


def parse_cdl(s):
    d = {"slope": [1, 1, 1], "offset": [0, 0, 0], "power": [1, 1, 1], "sat": 1.0}
    for part in s.split(";"):
        k, _, v = part.strip().partition(" ")
        nums = [float(x) for x in v.split()]
        if k in ("slope", "offset", "power"):
            d[k] = nums if len(nums) == 3 else nums * 3
        elif k == "sat":
            d["sat"] = nums[0]
    return d


def lut_apply(src_jpg, lut, out_jpg):
    # ffmpeg lut3d handles .cube; escape the Windows path for the filter graph
    p = str(lut).replace("\\", "/").replace(":", "\\:")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src_jpg), "-vf", f"lut3d=file='{p}'", str(out_jpg)], check=True)


def preview(path, t=None, auto=False, cdl=None, lut=None, all_luts=None, sheet=None):
    np = np_()
    info = probe_summary(path)
    t = info["duration"] * 0.4 if t is None else t
    tmp = Path(tempfile.mkdtemp())
    base = tmp / "before.jpg"
    extract_frame(path, t, base, width=540)
    tiles, labels = [base], ["before"]
    rgb = load_rgb(base)
    if auto or cdl:
        d = parse_cdl(cdl) if cdl else None
        if auto:
            c = analyze(path, 8)["suggest"]["cdl"]
            d = {"slope": [float(x) for x in c["Slope"].split()], "offset": [float(x) for x in c["Offset"].split()],
                 "power": [float(x) for x in c["Power"].split()], "sat": float(c["Saturation"])}
        out = tmp / "cdl.jpg"
        save_rgb(apply_cdl(rgb, d["slope"], d["offset"], d["power"], d["sat"]), out)
        tiles.append(out)
        labels.append("auto CDL" if auto else "CDL")
    luts = []
    if lut:
        luts.append(Path(lut))
    if all_luts:
        luts += sorted(Path(all_luts).glob("*.cube"))
    for i, l in enumerate(luts):
        o = tmp / f"lut{i:02d}.jpg"
        try:
            src = tiles[1] if len(tiles) > 1 and (auto or cdl) else base  # LUT on top of the correction when one exists
            lut_apply(src, l, o)
            tiles.append(o)
            labels.append(l.stem)
        except Exception as e:  # noqa: BLE001
            print(f"[skip] {l.name}: {e}", file=sys.stderr)
    sheet = sheet or str(Path("jobs") / "grade_preview.jpg")
    Path(sheet).parent.mkdir(parents=True, exist_ok=True)
    contact_sheet([str(x) for x in tiles], sheet, cols=min(len(tiles), 4), thumb_w=360)
    return {"sheet": sheet, "tiles": [{"n": i + 1, "what": lab} for i, lab in enumerate(labels)], "time_s": round(t, 2)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("analyze"); p.add_argument("file"); p.add_argument("--samples", type=int, default=12); p.add_argument("--out")
    p = sub.add_parser("preview"); p.add_argument("file"); p.add_argument("--time", type=float)
    p.add_argument("--auto", action="store_true"); p.add_argument("--cdl"); p.add_argument("--lut"); p.add_argument("--all-luts")
    p.add_argument("--sheet")
    p = sub.add_parser("match"); p.add_argument("rest", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    if a.cmd == "analyze":
        r = analyze(a.file, a.samples)
        if a.out:
            save_json(a.out, r)
        print(json.dumps(r, indent=1))
    elif a.cmd == "preview":
        print(json.dumps(preview(a.file, a.time, a.auto, a.cdl, a.lut, a.all_luts, a.sheet), indent=1))
    else:
        sys.exit(subprocess.call([sys.executable, str(Path(__file__).parent / "color_match.py")] + a.rest))


if __name__ == "__main__":
    main()
