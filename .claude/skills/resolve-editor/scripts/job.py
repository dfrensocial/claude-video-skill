#!/usr/bin/env python3
"""Per-job working folder + changelog.

  job.py init --name NAME [--client C] [--ratio 9:16] [--duration 30] [--lang en] [--platform meta-reels]
              [--mode autopilot|checkpoint] [--footage PATH ...] [--script FILE] [--preset ID]
  job.py log NAME "message"          # append a timestamped line to jobs/NAME/changelog.md
  job.py show NAME

Folder:  jobs/NAME/{analysis,plan,preview,qc,broll,clips,output}  job.json  changelog.md
"""
import argparse
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import find_workspace, load_config, load_json, save_json  # noqa: E402


def job_dir(name):
    ws = find_workspace()
    if not ws:
        raise SystemExit("workspace.json not found - run setup_workspace.py first")
    return ws / "jobs" / name


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("--name", required=True)
    p.add_argument("--client", default="")
    p.add_argument("--ratio", default=None)
    p.add_argument("--duration", type=float, default=None)
    p.add_argument("--lang", default=None)
    p.add_argument("--platform", default=None)
    p.add_argument("--mode", default=None)
    p.add_argument("--footage", nargs="*", default=[])
    p.add_argument("--script", default="")
    p.add_argument("--preset", default="")
    p = sub.add_parser("log")
    p.add_argument("name")
    p.add_argument("message")
    p = sub.add_parser("show")
    p.add_argument("name")
    a = ap.parse_args()

    if a.cmd == "init":
        cfg = load_config()
        d = job_dir(a.name)
        for sd in ("analysis", "plan", "preview", "qc", "broll", "clips", "output"):
            (d / sd).mkdir(parents=True, exist_ok=True)
        job = {
            "name": a.name, "client": a.client, "created": now(),
            "ratio": a.ratio or cfg["defaults"]["ratio"], "target_duration": a.duration,
            "language": a.lang or cfg["defaults"]["language"], "platform": a.platform or cfg["defaults"]["platform"],
            "mode": a.mode or cfg["mode"], "footage": [str(Path(f).expanduser()) for f in a.footage],
            "script": a.script, "preset": a.preset, "assumptions": [], "stage": "init",
        }
        save_json(d / "job.json", job)
        (d / "changelog.md").write_text(f"# Changelog - {a.name}\n\n- {now()} job created\n", encoding="utf-8")
        print(f"job ready: {d}")
    elif a.cmd == "log":
        d = job_dir(a.name)
        with open(d / "changelog.md", "a", encoding="utf-8") as f:
            f.write(f"- {now()} {a.message}\n")
    elif a.cmd == "show":
        d = job_dir(a.name)
        print(load_json(d / "job.json"))
        print((d / "changelog.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
