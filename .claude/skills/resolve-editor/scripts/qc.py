#!/usr/bin/env python3
"""Quality control on a RENDERED file (a preview render from Resolve, or the final).

  qc.py check FILE [--expect-res 1080x1920] [--expect-fps 30] [--expect-dur 32] [--lufs -14] [--out qc.json]
  qc.py frames FILE --times 1.2,3.4,7.0 [--out DIR] [--sheet sheet.jpg]      # numbered contact sheet
  qc.py frames FILE --every 2 --out DIR --sheet sheet.jpg

`check` flags: wrong resolution/fps/duration, missing audio, black frames, frozen frames (stuck B-roll or a
timeline gap), dead air in the middle of the audio, trailing/leading silence, loudness off target, peaks near
clipping. Exit code 1 when any check FAILs. WARN means "look at this", not "broken".
"""
import argparse
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from analyze import loudness, silence  # noqa: E402
from common import contact_sheet, extract_frame, load_config, probe_summary, run, save_json  # noqa: E402


def black_intervals(path, min_dur):
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-an", "-vf",
             f"blackdetect=d={min_dur}:pix_th=0.10", "-f", "null", "-"], check=False)
    return [{"start": float(a), "end": float(b)} for a, b in
            re.findall(r"black_start:([\d.]+)\s+black_end:([\d.]+)", r.stderr)]


def freeze_intervals(path, min_dur):
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-an", "-vf",
             f"freezedetect=n=-60dB:d={min_dur}", "-f", "null", "-"], check=False)
    starts = [float(x) for x in re.findall(r"freeze_start:\s*([\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"freeze_end:\s*([\d.]+)", r.stderr)]
    dur = probe_summary(path)["duration"]
    return [{"start": s, "end": (ends[i] if i < len(ends) else dur)} for i, s in enumerate(starts)]


def check(path, expect_res=None, expect_fps=None, expect_dur=None, lufs=None, cfg=None):
    cfg = cfg or load_config()
    q = cfg["qc"]
    lufs = cfg["output"]["lufs"] if lufs is None else lufs
    info = probe_summary(path)
    res = []

    def add(name, status, detail):
        res.append({"check": name, "status": status, "detail": detail})

    if not info["has_video"]:
        add("video stream", "FAIL", "no video")
    if expect_res:
        got = f"{info.get('width')}x{info.get('height')}"
        add("resolution", "PASS" if got == expect_res else "FAIL", f"{got} (expected {expect_res})")
    if expect_fps:
        add("frame rate", "PASS" if abs(info.get("fps", 0) - expect_fps) < 0.05 else "WARN",
            f"{info.get('fps')} (expected {expect_fps})")
    if expect_dur:
        d = info["duration"]
        add("duration", "PASS" if abs(d - expect_dur) <= q["dur_tolerance"] else "WARN", f"{d:.2f}s (expected ~{expect_dur}s)")
    if not info["has_audio"]:
        add("audio stream", "FAIL", "no audio track")
    else:
        lo = loudness(path)
        i, tp = lo["integrated_lufs"], lo["true_peak_dbfs"]
        if i is None:
            add("loudness", "WARN", "could not measure")
        else:
            diff = abs(i - lufs)
            add("loudness", "PASS" if diff <= q["lufs_tolerance"] else "WARN" if diff <= 3 else "FAIL",
                f"{i} LUFS (target {lufs} +/- {q['lufs_tolerance']})")
        if tp is not None:
            add("peaks", "PASS" if tp <= -1.0 else "WARN" if tp <= -0.1 else "FAIL", f"{tp} dBFS true peak")
        sil = silence(path, -40.0, q["mid_silence_max"])["silence"]
        dur = info["duration"]
        mid = [s for s in sil if s["start"] > 0.4 and s["end"] < dur - 0.4]
        lead = [s for s in sil if s["start"] <= 0.05 and s["end"] - s["start"] > 0.4]
        tail = [s for s in sil if s["end"] >= dur - 0.05 and s["end"] - s["start"] > 0.6]
        add("dead air (mid)", "PASS" if not mid else "WARN",
            "none" if not mid else "; ".join(f"{s['start']:.1f}-{s['end']:.1f}s" for s in mid))
        add("lead/tail silence", "PASS" if not (lead or tail) else "WARN",
            "ok" if not (lead or tail) else f"lead {len(lead)} tail {len(tail)}")
    if info["has_video"]:
        bl = black_intervals(path, q["black_min_dur"])
        dur = info["duration"]
        mid = [b for b in bl if b["start"] > 0.3 and b["end"] < dur - 0.3]
        edge = [b for b in bl if b not in mid]
        add("black frames (mid)", "PASS" if not mid else "FAIL",
            "none" if not mid else "; ".join(f"{b['start']:.2f}-{b['end']:.2f}s" for b in mid))
        add("black frames (start/end)", "PASS" if not edge else "WARN",
            "none" if not edge else "; ".join(f"{b['start']:.2f}-{b['end']:.2f}s" for b in edge))
        fr = freeze_intervals(path, q["freeze_min_dur"])
        add("frozen frames", "PASS" if not fr else "WARN",
            "none" if not fr else "; ".join(f"{b['start']:.1f}-{b['end']:.1f}s" for b in fr) + " (stuck B-roll / gap? intentional hold?)")
    return {"file": str(path), "info": info, "checks": res,
            "ok": not any(r["status"] == "FAIL" for r in res)}


def frames(path, times, out_dir, sheet=None, width=360):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = []
    for i, t in enumerate(times, 1):
        files.append(extract_frame(path, t, out / f"f{i:03d}_{t:07.2f}.jpg", width=width))
    if sheet:
        contact_sheet(files, sheet, cols=min(len(files), 6), thumb_w=min(width, 300))
    return files


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check")
    p.add_argument("file")
    p.add_argument("--expect-res")
    p.add_argument("--expect-fps", type=float)
    p.add_argument("--expect-dur", type=float)
    p.add_argument("--lufs", type=float)
    p.add_argument("--out")
    p = sub.add_parser("frames")
    p.add_argument("file")
    p.add_argument("--times")
    p.add_argument("--every", type=float)
    p.add_argument("--out")
    p.add_argument("--sheet")
    a = ap.parse_args()
    if a.cmd == "check":
        rep = check(a.file, a.expect_res, a.expect_fps, a.expect_dur, a.lufs)
        for r in rep["checks"]:
            print(f"[{r['status']}] {r['check']}: {r['detail']}")
        if a.out:
            save_json(a.out, rep)
        sys.exit(0 if rep["ok"] else 1)
    else:
        dur = probe_summary(a.file)["duration"]
        if a.times:
            times = [float(x) for x in a.times.split(",") if x.strip()]
        elif a.every:
            times, t = [], 0.0
            while t < dur:
                times.append(round(t, 2))
                t += a.every
        else:
            raise SystemExit("give --times or --every")
        out = a.out or tempfile.mkdtemp()
        files = frames(a.file, [min(max(t, 0), max(dur - 0.05, 0)) for t in times], out, a.sheet)
        print(f"{len(files)} frames in {out}" + (f"; sheet {a.sheet} (tile n = time #{'n'}: {times})" if a.sheet else ""))


if __name__ == "__main__":
    main()
