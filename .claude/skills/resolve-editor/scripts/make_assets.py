#!/usr/bin/env python3
"""STEP 4 of the SOP: turn work/creative_plan.json into generated assets (the Resolve build then imports and places them).

  make_assets.py JOB_DIR [--only typography,transitions,sound,voice] [--force]

Writes into <job>/work/assets/ and a manifest work/assets/manifest.json that resolve_job.py reads:
  voice/<src>_clean.mp4         the raw video stream copied untouched + the voice processed (denoise, EQ, compressor), gained to the target
  transitions/*.mov             fire wipes / flame licks (WebGL shader), flashes, glitch clips cut from the footage itself (alpha ProRes 4444)
  typography/*.mov              animated typography split into ONE CLIP PER EVENT (so each can be moved, trimmed, swapped, deleted in Resolve),
                                plus the HUD as one clip. Events never overlap inside a lane (auto lane assignment).
  sound/*.wav                   one WAV per sound event + a drone, loudness-calibrated so the Resolve render lands near target_lufs
Nothing here edits the user's inputs. Everything is disposable and re-generated from the plan.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import load_json, probe_summary, save_json  # noqa: E402
import compose  # noqa: E402
import graphics  # noqa: E402
import sounddesign  # noqa: E402


def slug(s, n=28):
    return re.sub(r"[^A-Za-z0-9]+", "-", str(s)).strip("-")[:n] or "x"


def key(d):
    return hashlib.sha1(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:10]


def src_time(plan, T):
    """Map an output time to (source path, source seconds) through the plan's clip list."""
    t = 0.0
    for c in plan["clips"]:
        d = float(c["out"]) - float(c["in"])
        if t - 1e-6 <= T < t + d:
            return plan["sources"][c["src"]], float(c["in"]) + (T - t)
        t += d
    return None, None


def sh(cmd):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(map(str, cmd))[:200]}\n{r.stderr[-800:]}")
    return r


def lane_assign(events, pad_after=0.4):
    """Greedy: put each event in the first lane where it does not overlap (exit animation included) another event."""
    lanes = []
    out = []
    for e in sorted(events, key=lambda e: e["t"]):
        a, b = e["t"], e["t"] + e["dur"] + pad_after
        for i, end in enumerate(lanes):
            if a >= end - 1e-6:
                lanes[i] = b
                out.append((i, e))
                break
        else:
            lanes.append(b)
            out.append((len(lanes) - 1, e))
    return out, len(lanes)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("job")
    ap.add_argument("--only", default="voice,transitions,typography,sound")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    job = Path(a.job)
    plan = load_json(job / "work" / "creative_plan.json", None)
    if not plan:
        raise SystemExit("work/creative_plan.json not found or invalid: write the plan first (SOP step 3)")
    A = job / "work" / "assets"
    for d in ("voice", "transitions", "typography", "sound", "video"):
        (A / d).mkdir(parents=True, exist_ok=True)
    only = set(a.only.split(","))
    W, H = plan.get("size", [1080, 1920])
    fps = int(plan.get("fps", 30))
    total = float(plan["duration"])
    manifest = {"job": plan.get("job"), "voice": {}, "transitions": [], "typography": [], "sound": [], "gain_offset_db": 0.0}
    mpath = A / "manifest.json"
    old = load_json(mpath, {}) or {}

    # ------------------------------------------------------------ voice (clean audio baked next to an untouched video stream)
    voice_cfg = plan.get("voice") or {}
    chain = voice_cfg.get("chain")
    offset_db = float(old.get("gain_offset_db", 0.0))
    srcs_used = sorted({c["src"] for c in plan["clips"] if not c.get("mute")})

    def build_voice(off):
        res = {}
        for sid in srcs_used:
            src = plan["sources"][sid]
            out = A / "voice" / f"{slug(Path(src).stem)}_clean_g{off:+.1f}_{key(chain)}.mp4"
            if not probe_summary(src)["has_audio"]:
                res[sid] = src
                continue
            af = ((chain + ",") if chain else "") + f"volume={off:.2f}dB"
            sh(["ffmpeg", "-y", "-v", "error", "-i", src, "-c:v", "copy", "-af", af, "-c:a", "aac", "-b:a", "256k", str(out)])
            res[sid] = str(out)
        return res

    # ------------------------------------------------------------ sound: stems + loudness calibration against the cleaned voice
    snd = plan.get("sound") or {}
    if "voice" in only or "sound" in only:
        manifest["voice"] = build_voice(0.0)
    if "sound" in only:
        snd = dict(snd, total=total)
        stems0 = sounddesign.render_stems(snd, A / "sound" / "calib", 0.0)
        # simulate the Resolve audio mix (voice from V1/A1 clips + stems at their times) and measure it
        sim_clips = [{"src": manifest["voice"].get(c["src"], plan["sources"][c["src"]]), "in": c["in"], "out": c["out"], "mute": c.get("mute", False)}
                     for c in plan["clips"]]
        spec = {"clips": sim_clips, "sfx": [{"file": s["file"], "at": s["t"], "gain_db": 0} for s in stems0], "output": {}}
        import tempfile
        tmp = tempfile.mkdtemp()
        cmd, raw = compose.build_audio(spec, tmp, total)
        compose.sh(cmd)
        m = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(raw), "-af", "ebur128=peak=true", "-f", "null", "-"],
                           capture_output=True, text=True)
        li = re.findall(r"I:\s+(-?[\d.]+) LUFS", m.stderr)
        tp = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", m.stderr)
        target = float(voice_cfg.get("target_lufs", -14))
        lufs = float(li[-1]) if li else target
        peak = float(tp[-1]) if tp else -3.0
        # Resolve's own mix of the same clips measured 2.7-2.9 dB quieter than this simulation (same stems, same voice), so the
        # calibration adds that back (override per job with voice.resolve_comp_db; re-measure with `resolve_job.py review`).
        comp = float(voice_cfg.get("resolve_comp_db", 2.8))
        offset = min(target - lufs + comp,          # the loudness target ...
                     -1.8 - peak + comp)            # ... but never past -1.8 dBFS true peak in the Resolve render (AAC headroom)
        offset = max(-14.0, min(10.0, offset))
        manifest["gain_offset_db"] = round(offset, 2)
        manifest["mix_measured"] = {"lufs_before": lufs, "peak_before": peak, "offset_db": round(offset, 2)}
        manifest["voice"] = build_voice(offset)
        manifest["sound"] = sounddesign.render_stems(snd, A / "sound" / f"g{offset:+.1f}_{key(snd)}", offset)
        print("sound: mix", lufs, "LUFS, peak", peak, "-> offset", round(offset, 2), "dB;", len(manifest["sound"]), "stems")
    else:
        manifest["sound"] = old.get("sound", [])
        manifest["voice"] = old.get("voice") or build_voice(offset_db)
        manifest["gain_offset_db"] = offset_db

    # ------------------------------------------------------------ transitions
    if "transitions" in only:
        for i, tr in enumerate(plan.get("transitions", [])):
            kind = tr["kind"]
            t = float(tr["t"])
            dur = float(tr.get("dur", 1.2 if kind == "fire_wipe" else 0.6))
            if kind in ("fire_wipe", "lick"):
                params = {"dur": dur, "dir": tr.get("dir", "up"), "seed": tr.get("seed", 3 + i), "heat": tr.get("heat", 0.85),
                          "band": tr.get("band", 1.7 if kind == "fire_wipe" else 1.0)}
                f = A / "transitions" / f"{i + 1:02d}_{kind}_{t:06.2f}_{key(params)}.mov"
                if a.force or not f.exists():
                    graphics.render("fire-wipe", params, str(f), "mov", "looks")
                length = 3.0   # the template file is 3 s long; the Resolve clip is trimmed to dur
                start = float(tr.get("start", t - (0.5 * dur if kind == "fire_wipe" else 0.28 * dur / 0.6)))
                manifest["transitions"].append({"kind": kind, "file": str(f), "start": round(start, 3), "dur": round(dur + 0.05, 3), "t": t,
                                                "note": tr.get("note", "")})
            elif kind == "flash":
                f = A / "transitions" / f"{i + 1:02d}_flash_{t:06.2f}_{key(tr)}.mov"
                if a.force or not f.exists():
                    sh(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=white:s={W}x{H}:r={fps}:d={dur}", "-vf",
                        f"format=rgba,fade=t=in:st=0:d={dur * 0.15:.3f}:alpha=1,fade=t=out:st={dur * 0.15:.3f}:d={dur * 0.85:.3f}:alpha=1",
                        "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", str(f)])
                manifest["transitions"].append({"kind": "flash", "file": str(f), "start": t, "dur": dur, "t": t, "opacity": tr.get("opacity", 0.85)})
            elif kind == "glitch":
                src, st = src_time(plan, t)
                if not src:
                    continue
                f = A / "transitions" / f"{i + 1:02d}_glitch_{t:06.2f}_{key(tr)}.mov"
                px = int(tr.get("px", 14))
                if a.force or not f.exists():
                    sh(["ffmpeg", "-y", "-v", "error", "-ss", f"{st:.3f}", "-t", f"{dur}", "-i", src, "-vf",
                        f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},fps={fps},format=rgb24,"
                        f"rgbashift=rh={px}:bh={-px}:rv={px // 3}:bv={-px // 3},noise=alls=22:allf=t,eq=contrast=1.25:saturation=1.4,format=yuv420p",
                        "-an", "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", str(f)])
                manifest["transitions"].append({"kind": "glitch", "file": str(f), "start": t, "dur": dur, "t": t})
        print("transitions:", len(manifest["transitions"]))
    else:
        manifest["transitions"] = old.get("transitions", [])

    # ------------------------------------------------------------ typography (one clip per event)
    if "typography" in only:
        ty = plan.get("typography") or {}
        events = list(ty.get("events", []))
        hud = [e for e in events if e["type"] == "hud"]
        rest = [e for e in events if e["type"] != "hud"]
        lane_of, nlanes = lane_assign([dict(e, dur=float(e.get("dur", 1.0))) for e in rest])
        groups = {}
        for ln, e in lane_of:
            groups.setdefault(ln, []).append(e)
        render_jobs = [("hud", hud)] if hud else []
        render_jobs += [(f"lane{ln}", evs) for ln, evs in sorted(groups.items())]
        for name, evs in render_jobs:
            lane_file = A / "typography" / f"_{name}_full.mov"
            h = key(evs)
            marker = A / "typography" / f"_{name}.hash"
            if a.force or not lane_file.exists() or not marker.exists() or marker.read_text() != h:
                graphics.render("typo", {"events": json.dumps(evs, ensure_ascii=False)}, str(lane_file), "mov", "looks")
                marker.write_text(h)
            if name == "hud":
                e = evs[0]
                f = A / "typography" / f"typo_hud_{e['t']:06.2f}_{key(e)}.mov"
                s0 = max(e["t"] - 0.05, 0)
                dd = e["dur"] + 0.4
                sh(["ffmpeg", "-y", "-v", "error", "-ss", f"{s0:.3f}", "-t", f"{dd:.3f}", "-i", str(lane_file), "-c:v", "prores_ks", "-profile:v", "4444",
                    "-pix_fmt", "yuva444p10le", str(f)])
                manifest["typography"].append({"kind": "hud", "file": str(f), "start": s0, "dur": dd, "label": "HUD"})
                continue
            for e in evs:
                s0 = max(e["t"] - 0.08, 0)
                dd = float(e["dur"]) + 0.5
                label = ""
                if e["type"] == "phrase":
                    label = " ".join(w["w"] for ln in e.get("lines", []) for w in ln)
                else:
                    label = e.get("text") or e.get("label") or e.get("e") or e["type"]
                f = A / "typography" / f"typo_{name}_{e['t']:06.2f}_{slug(label)}_{key(e)}.mov"
                if a.force or not f.exists() or marker.read_text() != h or True:
                    sh(["ffmpeg", "-y", "-v", "error", "-ss", f"{s0:.3f}", "-t", f"{dd:.3f}", "-i", str(lane_file), "-c:v", "prores_ks", "-profile:v", "4444",
                        "-pix_fmt", "yuva444p10le", str(f)])
                manifest["typography"].append({"kind": e["type"], "file": str(f), "start": s0, "dur": dd, "label": label, "lane": name})
        print("typography:", len(manifest["typography"]), "clips from", len(render_jobs), "renders")
    else:
        manifest["typography"] = old.get("typography", [])

    save_json(mpath, manifest)
    print("manifest:", mpath)


if __name__ == "__main__":
    main()
