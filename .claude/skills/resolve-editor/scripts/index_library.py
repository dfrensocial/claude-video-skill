#!/usr/bin/env python3
"""Index and search the user's prebuilt B-roll / SFX / music libraries (read-only: never modifies them).

  index_library.py scan [--kinds broll sfx music]       # reads paths from workspace.json > library
  index_library.py search --kind broll --q "pour steam cup chai" [--orient vertical] [--min-dur 2]
                          [--top 12] [--sheet out.jpg]
  index_library.py search --kind sfx --q "whoosh swoosh" [--max-dur 1.5] [--top 10]
  index_library.py stats

Tags come from the folder and file names (folder tokens weigh more). Pass SEVERAL synonyms in --q;
matching is OR with ranking. With --sheet, a numbered contact sheet of poster frames is written so the
agent can LOOK at candidates before choosing (tile n = result n).
"""
import argparse
import json
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (AUDIO_EXT, IMAGE_EXT, VIDEO_EXT, contact_sheet, extract_frame, find_workspace, have,  # noqa: E402
                    load_config, load_json, probe_summary, save_json)

KIND_EXT = {"broll": VIDEO_EXT | {".gif"}, "sfx": AUDIO_EXT, "music": AUDIO_EXT,
            "assets": VIDEO_EXT | IMAGE_EXT | {".gif", ".cube"}}
KEY = {"broll": "broll_paths", "sfx": "sfx_paths", "music": "music_paths", "assets": "assets_paths"}
SPLIT = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z])(?=[A-Z])")
EXPORT_STAMP = re.compile(r"^\d{8}t\d{6}z$")  # Google-Drive zip suffix, e.g. -20241225T142251Z-001
ALPHA_FMTS = ("rgba", "bgra", "argb", "abgr", "yuva", "ya8", "ya16", "gbrap")  # pal8 (GIF) cannot tell: judged by corners
# folder/name words that mean "black or green background, composite with a blend mode / key" -> hint only
SCREEN_WORDS = {"grain", "burn", "leak", "leaks", "glow", "overlay", "overlays", "sparkle", "smoke", "fire", "dust",
                "explosion", "blast", "light", "lights", "flare", "bokeh", "particles"}
KEY_WORDS = {"green", "chroma", "greenscreen"}


def tokens_of(rel_parts):
    folder, name = set(), set()
    for i, part in enumerate(rel_parts):
        stem = Path(part).stem if i == len(rel_parts) - 1 else part
        for t in SPLIT.split(stem):
            t = t.lower()
            if len(t) >= 2 and not t.isdigit() and not EXPORT_STAMP.match(t) and t != "copy":
                (name if i == len(rel_parts) - 1 else folder).add(t)
    return sorted(folder), sorted(name)


def index_path(kind):
    ws = find_workspace()
    if not ws:
        raise SystemExit("workspace.json not found - run setup_workspace.py")
    return ws / "library" / "index" / f"{kind}.json"


def clean_category(part):
    """'Glow FX-20241225T142251Z-001' -> 'Glow FX'."""
    return re.sub(r"-\d{8}T\d{6}Z-\d+.*$", "", part).strip()


def asset_facts(path, rel, s, folder, name):
    """Extra fields for the `assets` kind: category, alpha, blend hint, asset type."""
    ext = path.suffix.lower()
    cat = clean_category(rel.parts[0]) if len(rel.parts) > 1 else "(root)"
    toks = set(folder) | set(name)
    if ext == ".cube":
        return {"category": cat, "asset_type": "lut", "alpha": False, "blend": None}
    pix = (s.get("pix_fmt") or "").lower()
    atype = "image" if ext in IMAGE_EXT else "video"
    # a pixel format with an alpha plane is only a hint (the GIF decoder reports bgra for opaque GIFs): check real pixels
    alpha = pix.startswith(ALPHA_FMTS) and real_alpha(path, s.get("duration") or 0)
    bg = None
    if alpha:
        blend = "normal"          # real transparency: place on V3/V4 as is
    elif atype == "video":
        bg = corner_background(path, s.get("duration") or 0)
        blend = {"green": "chroma-key", "black": "screen", "white": "multiply"}.get(bg)
        if blend is None:         # corners inconclusive: fall back to name hints, else it is a full-frame plate
            blend = ("chroma-key" if toks & KEY_WORDS else "screen" if toks & SCREEN_WORDS else "plate")
    else:
        blend = "normal"
    return {"category": cat, "asset_type": atype, "alpha": bool(alpha), "blend": blend, "bg": bg}


def real_alpha(path, duration):
    """True if a frame of the file really contains transparent pixels (checks two points in time)."""
    try:
        import subprocess
        from PIL import Image
        for frac in (0.15, 0.5):
            tmp = Path(tempfile.mkdtemp()) / "a.png"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{duration * frac:.3f}", "-i", str(path), "-frames:v", "1",
                            "-vf", "scale=96:-1,format=rgba", str(tmp)], check=True, capture_output=True)
            a = Image.open(tmp).convert("RGBA").getchannel("A")
            if a.getextrema()[0] < 245:
                return True
        return False
    except Exception:  # noqa: BLE001
        return True  # cannot tell: trust the pixel format


def corner_background(path, duration):
    """Classify the background from the four corners of one frame: green / black / white / None."""
    try:
        from PIL import Image
        tmp = Path(tempfile.mkdtemp()) / "c.jpg"
        extract_frame(str(path), duration * 0.35, tmp, width=96)
        im = Image.open(tmp).convert("RGB")
        w, h = im.size
        px = [im.getpixel(p) for p in ((2, 2), (w - 3, 2), (2, h - 3), (w - 3, h - 3))]
        r, g, b = (sum(c[i] for c in px) / 4 for i in range(3))
        if g > 140 and r < 110 and b < 110:
            return "green"
        if max(r, g, b) < 28:
            return "black"
        if min(r, g, b) > 232:
            return "white"
    except Exception:  # noqa: BLE001
        pass
    return None


def probe_one(args):
    path, root, kind = args
    rel = path.relative_to(root)
    folder, name = tokens_of((root.name,) + rel.parts)
    try:
        s = {"duration": 0.0, "has_audio": False} if path.suffix.lower() == ".cube" else probe_summary(path)
    except Exception:  # noqa: BLE001
        return None
    e = {"path": str(path), "root": str(root), "size": path.stat().st_size, "mtime": int(path.stat().st_mtime),
         "duration": s["duration"], "folder_tokens": folder, "name_tokens": name}
    if kind == "assets":
        e.update(width=s.get("width"), height=s.get("height"), fps=s.get("fps"), orientation=s.get("orientation"),
                 **asset_facts(path, rel, s, folder, name))
    elif kind == "broll":
        e.update(width=s.get("width"), height=s.get("height"), fps=s.get("fps"),
                 orientation=s.get("orientation"), has_audio=s["has_audio"])
    else:
        e.update(sample_rate=s.get("sample_rate"), channels=s.get("channels"))
    return e


def scan(kinds, cfg):
    lib = cfg.get("library") or {}
    for kind in kinds:
        old = {e["path"]: e for e in (load_json(index_path(kind), []) or [])}
        jobs, entries = [], []
        for root in lib.get(KEY[kind], []):
            r = Path(root).expanduser()
            if not r.exists():
                print(f"[skip] {kind}: {r} does not exist", file=sys.stderr)
                continue
            for p in r.rglob("*"):
                if p.is_file() and p.suffix.lower() in KIND_EXT[kind] and not p.name.startswith("."):
                    prev = old.get(str(p))
                    if prev and prev["size"] == p.stat().st_size and prev["mtime"] == int(p.stat().st_mtime):
                        entries.append(prev)
                    else:
                        jobs.append((p, r, kind))
        with ThreadPoolExecutor(max_workers=8) as ex:
            for e in ex.map(probe_one, jobs):
                if e:
                    entries.append(e)
        save_json(index_path(kind), entries)
        print(f"{kind}: {len(entries)} files indexed ({len(jobs)} new/changed)")


def search(kind, q, orient=None, min_dur=None, max_dur=None, top=12, sheet=None,
           category=None, alpha=None, asset_type=None):
    entries = load_json(index_path(kind), []) or []
    if not entries:
        raise SystemExit(f"{kind} index is empty - run: index_library.py scan")
    terms = [t.lower() for t in SPLIT.split(q) if len(t) >= 2]
    scored = []
    for e in entries:
        if category and category.lower() not in (e.get("category") or "").lower():
            continue
        if alpha is not None and bool(e.get("alpha")) != alpha:
            continue
        if asset_type and e.get("asset_type") != asset_type:
            continue
        if orient and e.get("orientation") and e["orientation"] != orient:
            continue
        if min_dur and e["duration"] < min_dur:
            continue
        if max_dur and e["duration"] > max_dur:
            continue
        s = 0.0
        for t in terms:
            for tok in e["folder_tokens"]:
                s += 3.0 if tok == t else 1.5 if (len(t) >= 3 and (tok.startswith(t) or t.startswith(tok)) and len(tok) >= 3) else 0
            for tok in e["name_tokens"]:
                s += 2.0 if tok == t else 1.0 if (len(t) >= 3 and (tok.startswith(t) or t.startswith(tok)) and len(tok) >= 3) else 0
        if s > 0 or not terms:
            scored.append((s, e))
    scored.sort(key=lambda x: (-x[0], -x[1]["duration"]))
    res = []
    for i, (s, e) in enumerate(scored[:top], 1):
        res.append({"n": i, "score": round(s, 1), "path": e["path"], "duration": e["duration"],
                    "orientation": e.get("orientation"), "res": f"{e.get('width')}x{e.get('height')}" if e.get("width") else None,
                    "tags": e["folder_tokens"] + e["name_tokens"]})
        if kind == "assets":
            res[-1].update(category=e.get("category"), asset_type=e.get("asset_type"),
                           alpha=e.get("alpha"), blend=e.get("blend"))
    if (sheet and kind in ("broll", "assets") and res and have("ffmpeg")
            and not any(r.get("asset_type") == "lut" for r in res)):  # LUTs have no picture: keep tile numbers honest
        tmp = Path(tempfile.mkdtemp())
        frames = []
        for r in res:
            f = tmp / f"{r['n']:03d}.jpg"
            extract_frame(r["path"], r["duration"] * 0.35, f, width=360)
            frames.append(str(f))
        contact_sheet(frames, sheet, cols=4, thumb_w=270)
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scan")
    p.add_argument("--kinds", nargs="+", default=["broll", "sfx", "music", "assets"], choices=list(KEY))
    p = sub.add_parser("search")
    p.add_argument("--kind", required=True, choices=list(KEY))
    p.add_argument("--q", default="")
    p.add_argument("--orient", choices=["vertical", "horizontal", "square"])
    p.add_argument("--min-dur", type=float)
    p.add_argument("--max-dur", type=float)
    p.add_argument("--top", type=int, default=12)
    p.add_argument("--sheet")
    p.add_argument("--category", help="assets only: folder category substring, e.g. 'glow' or 'paper'")
    p.add_argument("--alpha", action="store_true", help="assets only: only files with real transparency")
    p.add_argument("--asset-type", choices=["video", "image", "lut"], help="assets only")
    sub.add_parser("stats")
    a = ap.parse_args()
    cfg = load_config()
    if a.cmd == "scan":
        scan(a.kinds, cfg)
    elif a.cmd == "search":
        print(json.dumps(search(a.kind, a.q, a.orient, a.min_dur, a.max_dur, a.top, a.sheet,
                                a.category, True if a.alpha else None, a.asset_type), indent=1))
    else:
        for k in KEY:
            e = load_json(index_path(k), []) or []
            print(f"{k}: {len(e)} files, {sum(x['duration'] for x in e) / 60:.0f} min")
            if k == "assets" and e:
                from collections import Counter
                for cat, n in Counter(x.get("category") for x in e).most_common():
                    print(f"   {cat}: {n}")


if __name__ == "__main__":
    main()
