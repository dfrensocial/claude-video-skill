#!/usr/bin/env python3
"""Suggest a starting-point CDL grade that makes a B-roll clip sit closer to the A-roll's colour.

  color_match.py --target aroll.mp4 --source broll.mp4 [--target-t 3.0] [--source-t 1.0] [--out cdl.json]

Method: sample frames, compare per-channel mean/std (in display gamma space) and saturation of SOURCE vs
TARGET, then return CDL slope/offset/power-free values plus a saturation multiplier, clamped to safe ranges
(slope 0.8-1.25, offset +/-0.05, sat 0.8-1.25). This is a heuristic starting point. ALWAYS look at a frame
pair after applying it, and do not touch skin tones on the A-roll. Needs numpy.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import probe_summary  # noqa: E402


def sample(path, t0=None, n=8):
    import numpy as np
    dur = probe_summary(path)["duration"]
    if t0 is not None:
        vf = f"select='lt(t,{t0 + 1.0})*gte(t,{t0})',scale=96:-2"
        cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-vf", vf, "-vsync", "0", "-frames:v", str(n),
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    else:
        cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"fps={n / max(dur, 0.1):.4f},scale=96:-2",
               "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    r = subprocess.run(cmd, capture_output=True)
    data = np.frombuffer(r.stdout, dtype=np.uint8)
    if data.size < 3:
        raise SystemExit(f"could not read frames from {path}")
    return data.reshape(-1, 3).astype(np.float64) / 255.0


def stats(px):
    import numpy as np
    mx, mn = px.max(1), px.min(1)
    sat = float(np.mean(np.where(mx > 1e-3, (mx - mn) / np.maximum(mx, 1e-3), 0)))
    return px.mean(0), px.std(0), sat


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--target-t", type=float)
    ap.add_argument("--source-t", type=float)
    ap.add_argument("--out")
    a = ap.parse_args()
    import numpy as np
    tm, ts, tsat = stats(sample(a.target, a.target_t))
    sm, ss, ssat = stats(sample(a.source, a.source_t))
    slope = np.clip(ts / np.maximum(ss, 1e-3), 0.8, 1.25)
    offset = np.clip(tm - slope * sm, -0.05, 0.05)
    sat = float(np.clip(tsat / max(ssat, 1e-3), 0.8, 1.25))
    out = {"cdl": {"slope": [round(float(x), 3) for x in slope], "offset": [round(float(x), 3) for x in offset],
                   "power": [1.0, 1.0, 1.0], "saturation": round(sat, 3)},
           "target_mean_rgb": [round(float(x), 3) for x in tm], "source_mean_rgb": [round(float(x), 3) for x in sm],
           "note": "starting point only - verify visually; keep A-roll skin tones untouched"}
    print(json.dumps(out, indent=2))
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
