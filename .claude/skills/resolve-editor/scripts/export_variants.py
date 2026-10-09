#!/usr/bin/env python3
"""Make delivery variants (aspect ratios) from a finished master with ffmpeg, loudness-normalised.

  export_variants.py MASTER.mp4 --out DIR --client Dfren --project Chai [--ratios 9:16 4:5 1:1 16:9]
                    [--fill blur|crop|pad] [--version v1] [--lufs -14] [--tp -1.5] [--fps 30]

Naming: {client}_{project}_{ratio}_{WxH}_{version}.mp4   (ratio written 9x16)
H.264 High, yuv420p, AAC 48k, +faststart. Two-pass loudnorm (measure, then apply linear).
fill: blur = scaled-to-fit over blurred copy of itself (default), crop = centre crop, pad = black bars.
NOTE: crop/blur can cut off burned-in text. For text-heavy edits re-layout in Resolve instead and check QC frames.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import load_config, probe_summary, run  # noqa: E402

SIZES = {"9:16": (1080, 1920), "4:5": (1080, 1350), "1:1": (1080, 1080), "16:9": (1920, 1080)}


def vf(w, h, fill):
    if fill == "crop":
        return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,format=yuv420p"
    if fill == "pad":
        return f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,format=yuv420p"
    return (f"[0:v]split=2[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=30:5[bg];"
            f"[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[v]")


def measure(src, lufs, tp):
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(src), "-vn", "-af",
             f"loudnorm=I={lufs}:TP={tp}:LRA=11:print_format=json", "-f", "null", "-"], check=False)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    return json.loads(m.group(0)) if m else None


def make(src, dst, w, h, fill, lufs, tp, fps, has_audio):
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src)]
    f = vf(w, h, fill)
    if fill == "blur":
        cmd += ["-filter_complex", f.replace("[v]", f",fps={fps}[v]"), "-map", "[v]"]
    else:
        cmd += ["-vf", f + f",fps={fps}", "-map", "0:v:0"]
    if has_audio:
        m = measure(src, lufs, tp)
        if m:
            af = (f"loudnorm=I={lufs}:TP={tp}:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
                  f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
        else:
            af = f"loudnorm=I={lufs}:TP={tp}:LRA=11"
        cmd += ["-map", "0:a:0", "-af", af + ",aresample=48000", "-c:a", "aac", "-b:a", "192k", "-ar", "48000"]
    cmd += ["-c:v", "libx264", "-profile:v", "high", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(dst)]
    run(cmd)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("master")
    ap.add_argument("--out", required=True)
    ap.add_argument("--client", default="client")
    ap.add_argument("--project", default="project")
    ap.add_argument("--ratios", nargs="+", default=["9:16"])
    ap.add_argument("--fill", choices=["blur", "crop", "pad"], default="blur")
    ap.add_argument("--version", default="v1")
    ap.add_argument("--lufs", type=float)
    ap.add_argument("--tp", type=float)
    ap.add_argument("--fps", type=float)
    a = ap.parse_args()
    cfg = load_config()
    lufs = a.lufs if a.lufs is not None else cfg["output"]["lufs"]
    tp = a.tp if a.tp is not None else cfg["output"]["true_peak"]
    fps = a.fps or cfg["output"].get("fps", 30)
    info = probe_summary(a.master)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    made = []
    for r in a.ratios:
        if r not in SIZES:
            raise SystemExit(f"unknown ratio {r}; use {list(SIZES)}")
        w, h = SIZES[r]
        name = f"{a.client}_{a.project}_{r.replace(':', 'x')}_{w}x{h}_{a.version}.mp4".replace(" ", "-")
        dst = out / name
        make(a.master, dst, w, h, a.fill, lufs, tp, fps, info["has_audio"])
        made.append(str(dst))
        print("wrote", dst)
    print(json.dumps({"files": made}))


if __name__ == "__main__":
    main()
