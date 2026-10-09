#!/usr/bin/env python3
"""Place SFX on a compose.py spec from the events in it (overlays, cuts, emphasised captions).

  sfxplan.py spec.json [--captions captions.json] [--sfx-dir library/sfx] [--max-per-s 0.67] [--gain-db -15] [--lead 0.05]
             [--style-density 0.5] [--out spec.json]

Rules (references/broll-and-sfx.md): SFX supports a visual event, never decorates silence; average density <= --max-per-s
(default 1 per 1.5 s); a minimum gap of 0.45 s between sounds; samples rotate so the same file never plays twice in a row;
each sound starts `lead` s (about 2 frames) BEFORE the event; levels sit at gain_db relative to the loudness-normalised mix
(compose.py normalises the voice+music+sfx mix afterwards, so keep SFX 12-18 dB under the speech).
Event -> sound: overlay start (screen/glow/burn) -> whoosh; overlay start (alpha/key) -> pop; cut with punch-in change -> swish;
emphasised caption word -> pop (at most every 1.5 s); number-like caption -> ding; paper-style overlay -> a paper sound if one exists.
Writes the `sfx` list into the spec (replaces a previous auto-generated list; keeps entries marked "manual": true).
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import find_workspace, load_json, save_json  # noqa: E402

CLASS_WORDS = {"whoosh": ["whoosh"], "swish": ["swish"], "pop": ["pop"], "ding": ["ding"], "hit": ["hit"], "stamp": ["stamp"],
               "paper": ["paper", "newspaper", "page"], "riser": ["riser"]}


def library(sfx_dir):
    files = sorted(Path(sfx_dir).rglob("*.wav")) + sorted(Path(sfx_dir).rglob("*.mp3"))
    by = {k: [] for k in CLASS_WORDS}
    for f in files:
        n = f.stem.lower()
        for cls, words in CLASS_WORDS.items():
            if any(w in n for w in words):
                by[cls].append(str(f))
    return by


def events(spec, captions):
    ev = []
    t = 0.0
    prev_zoom = None
    for i, c in enumerate(spec["clips"]):
        z = float(c.get("zoom", 1.0))
        if i > 0 and prev_zoom is not None and abs(z - prev_zoom) > 0.01:
            ev.append((t, "swish", 2))
        prev_zoom = z
        t += float(c["out"]) - float(c["in"])
    for o in spec.get("overlays", []):
        name = Path(o["file"]).as_posix().lower()
        if "paper" in name:
            ev.append((float(o.get("start", 0)), "paper", 3))
        elif o.get("blend") in ("screen", "multiply"):
            ev.append((float(o.get("start", 0)), "whoosh", 3))
        else:
            ev.append((float(o.get("start", 0)), "pop", 2))
    last_emph = -9.0
    for e in (captions or {}).get("events", []):
        if not e.get("emph"):
            continue
        w = e["words"][e["emph"][0]]
        if re.search(r"\d", w):
            ev.append((e["start"], "ding", 2))
            last_emph = e["start"]
        elif e["start"] - last_emph >= 1.5:
            ev.append((e["start"], "pop", 1))
            last_emph = e["start"]
    return sorted(ev)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec")
    ap.add_argument("--captions")
    ap.add_argument("--sfx-dir")
    ap.add_argument("--max-per-s", type=float, default=0.67)
    ap.add_argument("--style-density", type=float, help="style's sfx.density_per_s: caps --max-per-s if lower")
    ap.add_argument("--gain-db", type=float, default=-15)
    ap.add_argument("--lead", type=float, default=0.05)
    ap.add_argument("--out")
    a = ap.parse_args()
    spec = load_json(a.spec, None)
    caps = load_json(a.captions, None) if a.captions else None
    sfx_dir = a.sfx_dir or str(find_workspace() / "library" / "sfx")
    lib = library(sfx_dir)
    total = sum(float(c["out"]) - float(c["in"]) for c in spec["clips"])
    dens = min(a.max_per_s, a.style_density) if a.style_density else a.max_per_s
    budget = max(1, int(total * dens))
    ev = events(spec, caps)
    # keep the highest-priority events if over budget, then enforce min gap
    keep = sorted(ev, key=lambda e: (-e[2], e[0]))[:budget]
    keep.sort()
    out, last_t, used = [m for m in spec.get("sfx", []) if m.get("manual")], -9.0, {}
    last_file = None
    for t, cls, pr in keep:
        pool = lib.get(cls) or lib.get("pop") or []
        if not pool or t - last_t < 0.45:
            continue
        k = used.get(cls, 0)
        f = pool[k % len(pool)]
        if f == last_file and len(pool) > 1:
            k += 1
            f = pool[k % len(pool)]
        used[cls] = k + 1
        out.append({"file": f, "at": round(max(t - a.lead, 0), 3), "gain_db": a.gain_db + (2 if cls in ("hit", "whoosh") else 0), "why": cls})
        last_t, last_file = t, f
    spec["sfx"] = sorted(out, key=lambda m: m["at"])
    save_json(a.out or a.spec, spec)
    print(json.dumps({"sfx": len(spec["sfx"]), "per_s": round(len(spec["sfx"]) / max(total, 1), 2), "budget": budget,
                      "events_considered": len(ev), "classes": sorted({m.get('why') for m in spec['sfx']})}))


if __name__ == "__main__":
    main()
