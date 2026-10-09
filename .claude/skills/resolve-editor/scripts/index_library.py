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
from common import (AUDIO_EXT, VIDEO_EXT, contact_sheet, extract_frame, find_workspace, have,  # noqa: E402
                    load_config, load_json, probe_summary, save_json)

KIND_EXT = {"broll": VIDEO_EXT | {".gif"}, "sfx": AUDIO_EXT, "music": AUDIO_EXT}
KEY = {"broll": "broll_paths", "sfx": "sfx_paths", "music": "music_paths"}
SPLIT = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z])(?=[A-Z])")


def tokens_of(rel_parts):
    folder, name = set(), set()
    for i, part in enumerate(rel_parts):
        stem = Path(part).stem if i == len(rel_parts) - 1 else part
        for t in SPLIT.split(stem):
            t = t.lower()
            if len(t) >= 2 and not t.isdigit():
                (name if i == len(rel_parts) - 1 else folder).add(t)
    return sorted(folder), sorted(name)


def index_path(kind):
    ws = find_workspace()
    if not ws:
        raise SystemExit("workspace.json not found - run setup_workspace.py")
    return ws / "library" / "index" / f"{kind}.json"


def probe_one(args):
    path, root, kind = args
    try:
        s = probe_summary(path)
    except Exception:  # noqa: BLE001
        return None
    rel = path.relative_to(root)
    folder, name = tokens_of((root.name,) + rel.parts)
    e = {"path": str(path), "root": str(root), "size": path.stat().st_size, "mtime": int(path.stat().st_mtime),
         "duration": s["duration"], "folder_tokens": folder, "name_tokens": name}
    if kind == "broll":
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


def search(kind, q, orient=None, min_dur=None, max_dur=None, top=12, sheet=None):
    entries = load_json(index_path(kind), []) or []
    if not entries:
        raise SystemExit(f"{kind} index is empty - run: index_library.py scan")
    terms = [t.lower() for t in SPLIT.split(q) if len(t) >= 2]
    scored = []
    for e in entries:
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
    if sheet and kind == "broll" and res and have("ffmpeg"):
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
    p.add_argument("--kinds", nargs="+", default=["broll", "sfx", "music"])
    p = sub.add_parser("search")
    p.add_argument("--kind", required=True, choices=list(KEY))
    p.add_argument("--q", default="")
    p.add_argument("--orient", choices=["vertical", "horizontal", "square"])
    p.add_argument("--min-dur", type=float)
    p.add_argument("--max-dur", type=float)
    p.add_argument("--top", type=int, default=12)
    p.add_argument("--sheet")
    sub.add_parser("stats")
    a = ap.parse_args()
    cfg = load_config()
    if a.cmd == "scan":
        scan(a.kinds, cfg)
    elif a.cmd == "search":
        print(json.dumps(search(a.kind, a.q, a.orient, a.min_dur, a.max_dur, a.top, a.sheet), indent=1))
    else:
        for k in KEY:
            e = load_json(index_path(k), []) or []
            print(f"{k}: {len(e)} files, {sum(x['duration'] for x in e) / 60:.0f} min")


if __name__ == "__main__":
    main()
