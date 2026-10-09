#!/usr/bin/env python3
"""Create / repair the workspace folder layout and workspace.json.

  setup_workspace.py --root ~/Desktop/DfrenEditor [--broll PATH ...] [--sfx PATH ...] [--music PATH ...]

Safe to re-run: never overwrites existing files or deletes anything.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import load_json, save_json  # noqa: E402

DIRS = [
    "footage", "references/inbox", "references/sorted", "presets", "brand-kits",
    "style-fingerprints", "jobs", "exports", "library/index",
]

TEMPLATE = {
    "mode": "autopilot",
    "library": {"broll_paths": [], "sfx_paths": [], "music_paths": []},
    "defaults": {"ratio": "9:16", "language": "auto", "platform": "meta-reels"},
    "resolve": {"project_prefix": "Dfren", "scratch_project": "Dfren Scratch"},
    "notes": "Edit freely. mode: 'autopilot' (self-review, no approval stops) or 'checkpoint' (ask before building)."
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--broll", nargs="*", default=[])
    ap.add_argument("--sfx", nargs="*", default=[])
    ap.add_argument("--music", nargs="*", default=[])
    a = ap.parse_args()
    root = Path(a.root).expanduser().resolve()
    for d in DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    cfg_path = root / "workspace.json"
    cfg = load_json(cfg_path) or TEMPLATE
    lib = cfg.setdefault("library", {})
    for key, vals in (("broll_paths", a.broll), ("sfx_paths", a.sfx), ("music_paths", a.music)):
        cur = lib.setdefault(key, [])
        for v in vals:
            v = str(Path(v).expanduser())
            if v not in cur:
                cur.append(v)
    save_json(cfg_path, cfg)
    tmpl = root / "brand-kits" / "_template.json"
    src = Path(__file__).resolve().parents[1] / "config" / "brand-kit.template.json"
    if src.exists() and not tmpl.exists():
        tmpl.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"workspace ready: {root}")
    print(f"edit {cfg_path} to set library paths and mode")


if __name__ == "__main__":
    main()
