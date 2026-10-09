#!/usr/bin/env python3
"""ffmpeg renderer for an edit spec: the no-Resolve path (previews, QC renders, and a first deliverable).

  compose.py from-cutplan cut_plan.json --out spec.json [--captions captions.ass] [--grade grade.json|--lut X.cube]
                          [--w 1080 --h 1920 --fps 30] [--music FILE --music-db -20] [--zoom-alt 1.08]
  compose.py render spec.json [--preview]          preview = half size, fast, lower quality
  compose.py example                               print a full example spec

Spec (JSON): {
 "output": {"file","w","h","fps","lufs","crf"},
 "clips":  [{"src","in","out","zoom"(1.0)}, ...]                    A-roll cuts, in order (hard cuts, 8 ms audio fades)
 "grade":  {"cdl": {"Slope":"r g b","Offset":"r g b","Power":"r g b","Saturation":"s"} (grade.py shape), "lut": "x.cube"}
 "overlays": [{"file","start","dur"?, "blend": "normal|screen|multiply|chroma-key", "x","y" (px or "center"), "width_frac",
               "opacity", "key": {"color":"0x00ff00","similarity":0.28,"blend":0.1}, "loop": bool}]
 "captions": "captions.ass"                                          burned in last (captions_ass.py makes it)
 "music": {"file","gain_db":-20,"duck":true,"fade_out":1.0}
 "sfx":   [{"file","at":seconds,"gain_db":-12}]
}
Audio is mixed in its own pass, loudness-normalised in two passes to output.lufs (default -14 LUFS, true peak -1.5 dBTP),
then muxed. Overlay blend modes: `screen` for black-background clips (glow, film burn), `multiply` for white, `chroma-key` for
green screens, `normal` for real alpha (ProRes 4444 / PNG). Everything is deterministic and re-runnable; nothing reads Resolve.
Limits: hard cuts only (no crossfades/transitions beyond overlay clips), static punch-in zoom per clip, one music track.
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import load_json, probe_summary, save_json  # noqa: E402


def esc(p):
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def sh(cmd, capture=False):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"ffmpeg failed ({r.returncode}):\n{' '.join(map(str, cmd))[:600]}\n{r.stderr[-1500:]}")
    return r


def parse3(s, default):
    try:
        v = [float(x) for x in str(s).split()]
        return v if len(v) == 3 else v[:1] * 3
    except Exception:  # noqa: BLE001
        return default


def grade_chain(g):
    """CDL -> lutrgb expressions (+ eq saturation), then an optional 3D LUT."""
    if not g:
        return []
    out = []
    cdl = g.get("cdl")
    if cdl:
        s, o, p = parse3(cdl.get("Slope"), [1, 1, 1]), parse3(cdl.get("Offset"), [0, 0, 0]), parse3(cdl.get("Power"), [1, 1, 1])
        ex = []
        for ch, i in (("r", 0), ("g", 1), ("b", 2)):
            ex.append(f"{ch}='255*pow(clip(val/255*{s[i]:.5f}+({o[i]:.5f}),0,1),{p[i]:.5f})'")
        out.append("format=rgb24,lutrgb=" + ":".join(ex))
        sat = float(cdl.get("Saturation", 1.0))
        if abs(sat - 1.0) > 0.005:
            out.append(f"eq=saturation={sat:.3f}")
    if g.get("lut"):
        out.append(f"lut3d=file='{esc(g['lut'])}'")
    return out


def vf_clip(i, c, W, H, fps):
    z = float(c.get("zoom", 1.0))
    sc = f"scale={W}:{H}:force_original_aspect_ratio=increase"
    if z > 1.001:
        sc = f"scale=iw*{z}:ih*{z}:force_original_aspect_ratio=increase,scale='max({W},iw)':'max({H},ih)'"
    return f"[{i}:v]{sc},crop={W}:{H},setsar=1,fps={fps},format=yuv420p[v{i}]"


def total_duration(spec):
    return sum(float(c["out"]) - float(c["in"]) for c in spec["clips"])


def build_video(spec, preview, tmpdir):
    o = spec["output"]
    W, H, fps = int(o.get("w", 1080)), int(o.get("h", 1920)), int(round(o.get("fps", 30)))
    if preview:
        W, H = (W // 2) // 2 * 2, (H // 2) // 2 * 2
    cmd = ["ffmpeg", "-y", "-v", "error"]
    chains = []
    n = len(spec["clips"])
    for i, c in enumerate(spec["clips"]):
        cmd += ["-ss", f"{float(c['in']):.3f}", "-t", f"{float(c['out']) - float(c['in']):.3f}", "-i", c["src"]]
        chains.append(vf_clip(i, c, W, H, fps))
    chains.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vc]")
    last = "vc"
    g = grade_chain(spec.get("grade"))
    if g:
        chains.append(f"[{last}]" + ",".join(g) + ",format=yuv420p[vg]")
        last = "vg"
    idx = n
    total = total_duration(spec)
    for k, ov in enumerate(spec.get("overlays", [])):
        start = float(ov.get("start", 0))
        dur = float(ov.get("dur") or 0)
        blend = ov.get("blend", "normal")
        if ov.get("loop"):
            cmd += ["-stream_loop", "-1"]
        cmd += ["-i", ov["file"]]
        s = f"[{idx}:v]"
        if dur:
            s += f"trim=0:{dur},"
        wf = float(ov.get("width_frac", 1.0 if blend in ("screen", "multiply") else 0.5))
        if blend in ("screen", "multiply"):
            # Build a timeline-long track that is neutral for the blend (black for screen, white for multiply), put the clip on
            # it at its start time, then blend the whole track with the picture. (tpad padding colours are unreliable in RGB.)
            lab = f"o{k}"
            neutral = "black" if blend == "screen" else "white"
            cmd += ["-f", "lavfi", "-i", f"color=c={neutral}:s={W}x{H}:r={fps}:d={total:.3f}"]
            bk = idx + 1
            chains.append(f"{s}setpts=PTS-STARTPTS+{start}/TB,scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                          f"format=rgb24[{lab}c]")
            try:
                clip_len = dur or probe_summary(ov["file"])["duration"] or 3600
            except Exception:  # noqa: BLE001
                clip_len = dur or 3600
            # overlay extends the clip's first frame backwards in time, so only enable it inside its own window
            chains.append(f"[{bk}:v]format=rgb24[{lab}n];[{lab}n][{lab}c]overlay=0:0:eof_action=pass:format=auto:"
                          f"enable='between(t,{start},{start + float(clip_len)})',format=rgb24[{lab}]")
            op = float(ov.get("opacity", 1.0))
            chains.append(f"[{last}]format=gbrp[{lab}b];[{lab}]format=gbrp[{lab}g];"
                          f"[{lab}b][{lab}g]blend=all_mode={blend}:all_opacity={op}:shortest=1,format=yuv420p[ov{k}]")
            idx += 1
        else:
            key = ""
            if blend == "chroma-key":
                kk = ov.get("key", {})
                key = f"chromakey={kk.get('color', '0x00ff00')}:{kk.get('similarity', 0.28)}:{kk.get('blend', 0.1)},"
            op = float(ov.get("opacity", 1.0))
            opf = f",colorchannelmixer=aa={op}" if op < 0.999 else ""
            x, y = ov.get("x", "center"), ov.get("y", "center")
            xe = "(W-w)/2" if x == "center" else str(x)
            ye = "(H-h)/2" if y == "center" else str(y)
            chains.append(f"{s}setpts=PTS-STARTPTS+{start}/TB,scale=iw*0+{int(W * wf)}:-2,format=rgba,{key}format=rgba{opf}[o{k}]")
            end = start + (dur or 3600)
            chains.append(f"[{last}][o{k}]overlay=x={xe}:y={ye}:enable='between(t,{start},{end})':eof_action=pass:format=auto,"
                          f"format=yuv420p[ov{k}]")
        last = f"ov{k}"
        idx += 1
    if spec.get("captions"):
        fd = None
        try:
            from captions_ass import fontsdir_arg
            fd = fontsdir_arg()
        except Exception:  # noqa: BLE001
            pass
        f = f"subtitles='{esc(spec['captions'])}'" + (f":fontsdir='{esc(fd)}'" if fd else "")
        chains.append(f"[{last}]{f}[vout]")
        last = "vout"
    outp = Path(tmpdir) / "video.mp4"
    cmd += ["-filter_complex", ";".join(chains), "-map", f"[{last}]", "-an", "-r", str(fps), "-c:v", "libx264",
            "-crf", str(28 if preview else o.get("crf", 18)), "-preset", "veryfast" if preview else "medium",
            "-pix_fmt", "yuv420p", str(outp)]
    return cmd, outp, total


def build_audio(spec, tmpdir, total):
    cmd = ["ffmpeg", "-y", "-v", "error"]
    chains, n = [], len(spec["clips"])
    for i, c in enumerate(spec["clips"]):
        d = float(c["out"]) - float(c["in"])
        try:
            has_a = probe_summary(c["src"])["has_audio"]
        except Exception:  # noqa: BLE001
            has_a = True
        if has_a:
            cmd += ["-ss", f"{float(c['in']):.3f}", "-t", f"{d:.3f}", "-i", c["src"]]
            chains.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,afade=t=in:d=0.008,"
                          f"afade=t=out:st={max(d - 0.008, 0):.3f}:d=0.008[a{i}]")
        else:
            cmd += ["-f", "lavfi", "-t", f"{d:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            chains.append(f"[{i}:a]anull[a{i}]")
    chains.append("".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[voice]")
    idx = n
    mix = ["[voice]"]
    music = spec.get("music")
    if music and music.get("file"):
        cmd += ["-stream_loop", "-1", "-i", music["file"]]
        fo = float(music.get("fade_out", 1.0))
        chains.append(f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{total:.3f},asetpts=PTS-STARTPTS,"
                      f"volume={float(music.get('gain_db', -20))}dB,afade=t=out:st={max(total - fo, 0):.3f}:d={fo}[mus]")
        if music.get("duck", True):
            chains.append("[voice]asplit=2[voice1][vsc]")
            chains.append("[mus][vsc]sidechaincompress=threshold=0.04:ratio=9:attack=15:release=350:makeup=1[musd]")
            mix = ["[voice1]", "[musd]"]
        else:
            mix.append("[mus]")
        idx += 1
    for j, s in enumerate(spec.get("sfx", [])):
        cmd += ["-i", s["file"]]
        ms = int(float(s["at"]) * 1000)
        chains.append(f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,volume={float(s.get('gain_db', -12))}dB,"
                      f"adelay={ms}|{ms}[sx{j}]")
        mix.append(f"[sx{j}]")
        idx += 1
    chains.append("".join(mix) + f"amix=inputs={len(mix)}:normalize=0:dropout_transition=0,atrim=0:{total:.3f}[mixed]")
    raw = Path(tmpdir) / "mix_raw.wav"
    cmd += ["-filter_complex", ";".join(chains), "-map", "[mixed]", "-c:a", "pcm_s16le", str(raw)]
    return cmd, raw


def loudnorm_two_pass(raw, out, lufs, tp=-1.5, lra=11):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(raw), "-af",
                        f"loudnorm=I={lufs}:TP={tp}:LRA={lra}:print_format=json", "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    if not m:
        sh(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-af", f"loudnorm=I={lufs}:TP={tp}:LRA={lra}", str(out)])
        return {"two_pass": False}
    d = json.loads(m.group(0))
    af = (f"loudnorm=I={lufs}:TP={tp}:LRA={lra}:measured_I={d['input_i']}:measured_TP={d['input_tp']}:"
          f"measured_LRA={d['input_lra']}:measured_thresh={d['input_thresh']}:offset={d['target_offset']}:linear=true")
    sh(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-af", af, "-ar", "48000", str(out)])
    return {"two_pass": True, "input_lufs": d["input_i"], "input_tp": d["input_tp"]}


def render(spec, preview=False):
    o = spec["output"]
    out = Path(o["file"])
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp()
    vcmd, vfile, total = build_video(spec, preview, tmp)
    sh(vcmd)
    acmd, raw = build_audio(spec, tmp, total)
    sh(acmd)
    wav = Path(tmp) / "mix.wav"
    info = loudnorm_two_pass(raw, wav, o.get("lufs", -14), o.get("true_peak", -1.5))
    sh(["ffmpeg", "-y", "-v", "error", "-i", str(vfile), "-i", str(wav), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", str(out)])
    return {"file": str(out), "duration": round(total, 2), "preview": preview, "audio": info}


def from_cutplan(a):
    cp = load_json(a.cutplan, None)
    if not cp:
        raise SystemExit("cannot read cut plan")
    clips = []
    for i, k in enumerate(cp["keep"]):
        z = a.zoom_alt if (a.zoom_alt and i % 2 == 1) else 1.0  # alternate punch-in hides jump cuts (editorial-craft.md)
        clips.append({"src": k["file"], "in": k["start"], "out": k["end"], "zoom": z})
    grade = {}
    if a.grade:
        gd = load_json(a.grade, {}) or {}
        grade["cdl"] = gd.get("suggest", {}).get("cdl") or gd.get("cdl") or gd
    if a.lut:
        grade["lut"] = a.lut
    spec = {"output": {"file": a.out_video, "w": a.w, "h": a.h, "fps": a.fps, "lufs": -14, "crf": 18}, "clips": clips,
            "grade": grade, "overlays": [], "sfx": []}
    if a.captions:
        spec["captions"] = a.captions
    if a.music:
        spec["music"] = {"file": a.music, "gain_db": a.music_db, "duck": True, "fade_out": 1.0}
    save_json(a.out, spec)
    print(json.dumps({"spec": a.out, "clips": len(clips), "duration": round(total_duration(spec), 2)}))


EXAMPLE = {"output": {"file": "exports/demo.mp4", "w": 1080, "h": 1920, "fps": 30, "lufs": -14},
           "clips": [{"src": "footage/a.mp4", "in": 1.2, "out": 6.4, "zoom": 1.0}, {"src": "footage/a.mp4", "in": 7.0, "out": 12.0, "zoom": 1.08}],
           "grade": {"cdl": {"Slope": "1.02 1.0 0.98", "Offset": "-0.02 -0.02 -0.02", "Power": "1.0 1.0 1.0", "Saturation": "1.05"}},
           "overlays": [{"file": "assets/asserss/Glow FX-.../Blast.mov", "start": 5.9, "blend": "screen", "opacity": 0.9},
                        {"file": "assets/asserss/IG Animations/heart.mov", "start": 8.0, "blend": "screen", "width_frac": 0.4, "x": "center", "y": 400}],
           "captions": "jobs/demo/captions.ass",
           "music": {"file": "library/music/bed.mp3", "gain_db": -20, "duck": True},
           "sfx": [{"file": "library/sfx_generated/whoosh_1.wav", "at": 5.85, "gain_db": -14}]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("from-cutplan")
    p.add_argument("cutplan"); p.add_argument("--out", required=True); p.add_argument("--out-video", default="exports/draft.mp4")
    p.add_argument("--captions"); p.add_argument("--grade"); p.add_argument("--lut")
    p.add_argument("--w", type=int, default=1080); p.add_argument("--h", type=int, default=1920); p.add_argument("--fps", type=float, default=30)
    p.add_argument("--music"); p.add_argument("--music-db", type=float, default=-20); p.add_argument("--zoom-alt", type=float, default=0)
    p = sub.add_parser("render"); p.add_argument("spec"); p.add_argument("--preview", action="store_true")
    sub.add_parser("example")
    a = ap.parse_args()
    if a.cmd == "from-cutplan":
        from_cutplan(a)
    elif a.cmd == "example":
        print(json.dumps(EXAMPLE, indent=1))
    else:
        spec = load_json(a.spec, None)
        if not spec:
            raise SystemExit("cannot read spec")
        print(json.dumps(render(spec, a.preview), indent=1))


if __name__ == "__main__":
    main()
