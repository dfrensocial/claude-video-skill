#!/usr/bin/env python3
"""Footage analysis: probe, silence, scenes, loudness, transcript.

Usage:
  analyze.py probe FILE
  analyze.py silence FILE [--noise -35] [--min 0.3]
  analyze.py scenes FILE [--threshold 0.3]
  analyze.py loudness FILE
  analyze.py transcribe FILE [--lang auto|en|ta|...] [--model small] [--device auto] [--no-verbatim]
  analyze.py srt2json FILE.srt --media FILE
  analyze.py all FILE --out DIR        # everything above, degrading gracefully

Transcript JSON schema (what cut_plan.py consumes):
  {"file": str, "language": str, "duration": float,
   "words": [{"w": str, "start": float, "end": float, "p": float}], "segments": [{"start","end","text"}]}
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (cuda_available, enable_cuda_dlls, have, load_config, probe_summary, run,  # noqa: E402
                    save_json)

VERBATIM_PROMPT = ("Umm, let me think, like, hmm... Okay, so, uh, I- I was, you know, going to say, "
                   "uh, the the thing is, actually, yeah.")


def silence(path, noise_db=-35.0, min_dur=0.3):
    dur = probe_summary(path)["duration"]
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af",
             f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"], check=False)
    out, cur = [], None
    for line in r.stderr.splitlines():
        m = re.search(r"silence_start:\s*(-?[\d.]+)", line)
        if m:
            cur = max(float(m.group(1)), 0.0)
        m = re.search(r"silence_end:\s*(-?[\d.]+)", line)
        if m and cur is not None:
            out.append({"start": round(cur, 3), "end": round(float(m.group(1)), 3)})
            cur = None
    if cur is not None:
        out.append({"start": round(cur, 3), "end": round(dur, 3)})
    total = sum(s["end"] - s["start"] for s in out)
    return {"file": str(path), "duration": dur, "noise_db": noise_db, "min_dur": min_dur,
            "silence": out, "silence_ratio": round(total / dur, 4) if dur else 0}


def scenes(path, threshold=0.3):
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-an", "-vf",
             f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"], check=False)
    times = [round(float(m.group(1)), 3) for m in re.finditer(r"pts_time:([\d.]+)", r.stderr)]
    return {"file": str(path), "threshold": threshold, "cuts": times}


def loudness(path):
    r = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "ebur128=peak=true",
             "-f", "null", "-"], check=False)
    err = r.stderr
    tail = err[err.rfind("Summary:"):] if "Summary:" in err else err

    def grab(pattern):
        m = re.search(pattern, tail)
        return float(m.group(1)) if m else None

    return {"file": str(path), "integrated_lufs": grab(r"I:\s+(-?[\d.]+)\s+LUFS"),
            "lra": grab(r"LRA:\s+(-?[\d.]+)\s+LU"), "true_peak_dbfs": grab(r"Peak:\s+(-?[\d.]+)\s+dBFS")}


def transcript_quality(t):
    """Cheap trust signal for an ASR result: share of low-confidence words and the longest run of one repeated
    word (Whisper loops on music / unfamiliar languages). Measured on this studio's references: English clips
    -> 0-5 % low-confidence; Tanglish clips with `small`+auto -> 25-40 % and loops (see CLAUDE.md)."""
    words = t.get("words", [])
    n = len(words)
    low = sum(1 for w in words if w.get("p", 1.0) < 0.5)
    run = best = 1
    for a, b in zip(words, words[1:]):
        run = run + 1 if a["w"].strip(" ,.?!").lower() == b["w"].strip(" ,.?!").lower() else 1
        best = max(best, run)
    ratio = round(low / n, 2) if n else 1.0
    unreliable = n == 0 or ratio > 0.25 or best >= 4
    # per-segment trust: a clip can be fine in clean speech and garbage under music / a second voice
    bad_ranges = []
    for s in t.get("segments", []):
        ws = [w for w in words if s["start"] - 0.05 <= w["start"] <= s["end"] + 0.05]
        if ws and sum(1 for w in ws if w.get("p", 1.0) < 0.5) / len(ws) > 0.4:
            bad_ranges.append([s["start"], s["end"]])
    note = ("OK for word-level cuts" if not unreliable else
            "UNRELIABLE: do not cut or caption from these words. Ask for the script/SRT, use a larger model or "
            "--lang en/ta explicitly (editorial-craft.md), and fall back to silence-based cutting.")
    return {"words": n, "low_conf_ratio": ratio, "max_repeat_run": best, "unreliable": unreliable, "note": note,
            "unreliable_ranges": bad_ranges}


TAMIL_PROFILE = {"lang": "ta", "model": "large-v3", "verbatim": False}


def transcribe(path, lang="auto", model="small", device="auto", verbatim=True):
    """Transcribe; Tamil/Tanglish gets its own profile.

    Measured here (RTX 5070, Video-5612): large-v3 + --lang ta + NO English verbatim prompt = 11 s, 6 % low-confidence;
    the English 'uh, you know' verbatim prompt makes Whisper echo the prompt on Tamil audio, small+auto loops, and
    medium on CPU needs 150-215 s. So: `--lang tanglish` = that profile; and if an `auto` run detects Tamil and
    comes back unreliable, it is re-run automatically with the profile (needs CUDA for sane speed; on CPU it warns)."""
    if lang in ("tanglish", "ta-profile"):
        lang, model, verbatim = TAMIL_PROFILE["lang"], TAMIL_PROFILE["model"], TAMIL_PROFILE["verbatim"]
    elif lang == "ta":
        verbatim = False
    t = _transcribe(path, lang, model, device, verbatim)
    t["quality"] = transcript_quality(t)
    if (t.get("language") == "ta" and t["quality"]["unreliable"] and model != TAMIL_PROFILE["model"]
            and (device == "cuda" or (device == "auto" and cuda_available()))):
        print("[INFO] Tamil detected and first pass unreliable: re-running with large-v3 + ta + no verbatim prompt",
              file=sys.stderr)
        t = _transcribe(path, TAMIL_PROFILE["lang"], TAMIL_PROFILE["model"], device, TAMIL_PROFILE["verbatim"])
        t["quality"] = transcript_quality(t)
        t["profile"] = "tamil-auto-rerun"
    if t["quality"]["unreliable"]:
        print(f"[WARN] transcript quality: {t['quality']['note']} "
              f"(low-conf {t['quality']['low_conf_ratio']}, repeat run {t['quality']['max_repeat_run']})", file=sys.stderr)
    return t


def _transcribe(path, lang="auto", model="small", device="auto", verbatim=True):
    duration = probe_summary(path)["duration"]
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        WhisperModel = None
    if WhisperModel is not None:
        dev = device
        if dev == "auto":
            dev = "cuda" if cuda_available() else "cpu"
        elif dev == "cuda":
            enable_cuda_dlls()
        m = WhisperModel(model, device=dev, compute_type="float16" if dev == "cuda" else "int8")
        segs, info = m.transcribe(str(path), language=None if lang == "auto" else lang, word_timestamps=True,
                                  vad_filter=True, beam_size=5, condition_on_previous_text=False,
                                  initial_prompt=VERBATIM_PROMPT if verbatim else None)
        words, segments = [], []
        for s in segs:
            segments.append({"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip()})
            for w in (s.words or []):
                words.append({"w": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3),
                              "p": round(float(getattr(w, "probability", 1.0)), 3)})
        return {"file": str(path), "language": info.language, "duration": duration, "engine": "faster-whisper",
                "words": words, "segments": segments}
    try:
        import whisper  # type: ignore
    except ImportError:
        raise SystemExit("No ASR engine found. Install one:  pip install faster-whisper   "
                         "(or supply your own transcript with `analyze.py srt2json`).")
    m = whisper.load_model(model)
    res = m.transcribe(str(path), language=None if lang == "auto" else lang, word_timestamps=True,
                       condition_on_previous_text=False, initial_prompt=VERBATIM_PROMPT if verbatim else None)
    words, segments = [], []
    for s in res["segments"]:
        segments.append({"start": round(s["start"], 3), "end": round(s["end"], 3), "text": s["text"].strip()})
        for w in s.get("words", []):
            words.append({"w": w["word"].strip(), "start": round(w["start"], 3), "end": round(w["end"], 3),
                          "p": round(float(w.get("probability", 1.0)), 3)})
    return {"file": str(path), "language": res.get("language"), "duration": duration, "engine": "openai-whisper",
            "words": words, "segments": segments}


def _ts(s):
    h, m, rest = s.strip().split(":")
    sec, _, ms = rest.replace(",", ".").partition(".")
    return int(h) * 3600 + int(m) * 60 + int(sec) + float("0." + (ms or "0"))


def srt2json(srt_path, media):
    """Convert an SRT (e.g. exported from Resolve) to the transcript schema. Word times are interpolated."""
    text = Path(srt_path).read_text(encoding="utf-8-sig")
    words, segments = [], []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l for l in block.splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        idx = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if idx is None:
            continue
        a, b = [x.strip() for x in lines[idx].split("-->")]
        start, end = _ts(a), _ts(b.split()[0])
        toks = " ".join(lines[idx + 1:]).split()
        if not toks:
            continue
        segments.append({"start": round(start, 3), "end": round(end, 3), "text": " ".join(toks)})
        total = sum(max(len(t), 1) for t in toks)
        t0 = start
        for t in toks:
            d = (end - start) * max(len(t), 1) / total
            words.append({"w": t, "start": round(t0, 3), "end": round(t0 + d, 3), "p": 0.8})
            t0 += d
    return {"file": str(media), "language": "unknown", "duration": probe_summary(media)["duration"],
            "engine": "srt-import (interpolated word times)", "words": words, "segments": segments}


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("probe", "silence", "scenes", "loudness", "transcribe", "all"):
        p = sub.add_parser(name)
        p.add_argument("file")
        if name == "silence":
            p.add_argument("--noise", type=float, default=cfg["silence"]["noise_db"])
            p.add_argument("--min", type=float, default=cfg["silence"]["min_dur"])
        if name == "scenes":
            p.add_argument("--threshold", type=float, default=0.3)
        if name in ("transcribe", "all"):
            p.add_argument("--lang", default=cfg["transcribe"]["language"])
            p.add_argument("--model", default=cfg["transcribe"]["model"])
            p.add_argument("--device", default=cfg["transcribe"]["device"])
            p.add_argument("--no-verbatim", action="store_true")
        if name == "all":
            p.add_argument("--out", required=True)
            p.add_argument("--skip-transcribe", action="store_true")
    p = sub.add_parser("srt2json")
    p.add_argument("file")
    p.add_argument("--media", required=True)
    p.add_argument("--out")
    a = ap.parse_args()

    if not have("ffmpeg"):
        raise SystemExit("ffmpeg not found on PATH. Install it first (see preflight.py).")

    if a.cmd == "probe":
        print(json.dumps(probe_summary(a.file), indent=2))
    elif a.cmd == "silence":
        print(json.dumps(silence(a.file, a.noise, a.min), indent=2))
    elif a.cmd == "scenes":
        print(json.dumps(scenes(a.file, a.threshold), indent=2))
    elif a.cmd == "loudness":
        print(json.dumps(loudness(a.file), indent=2))
    elif a.cmd == "transcribe":
        print(json.dumps(transcribe(a.file, a.lang, a.model, a.device, not a.no_verbatim), ensure_ascii=False, indent=2))
    elif a.cmd == "srt2json":
        res = srt2json(a.file, a.media)
        if a.out:
            save_json(a.out, res)
            print(f"wrote {a.out}")
        else:
            print(json.dumps(res, ensure_ascii=False, indent=2))
    elif a.cmd == "all":
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        stem = Path(a.file).stem
        info = probe_summary(a.file)
        save_json(out / f"{stem}.probe.json", info)
        if info["has_audio"]:
            save_json(out / f"{stem}.silence.json", silence(a.file, cfg["silence"]["noise_db"], cfg["silence"]["min_dur"]))
            save_json(out / f"{stem}.loudness.json", loudness(a.file))
        if info["has_video"]:
            save_json(out / f"{stem}.scenes.json", scenes(a.file))
        if info["has_audio"] and not a.skip_transcribe:
            try:
                save_json(out / f"{stem}.transcript.json",
                          transcribe(a.file, a.lang, a.model, a.device, not a.no_verbatim))
            except SystemExit as e:
                print(f"[transcript skipped] {e}", file=sys.stderr)
        print(f"analysis written to {out}")


if __name__ == "__main__":
    main()
