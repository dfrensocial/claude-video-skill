#!/usr/bin/env python3
"""STEP 1 of the SOP: take the user's four inputs, organise them in a job folder on the Desktop, analyse everything.

  intake.py --raw FILE [FILE ...] --reference FILE --type "hype transition reel" --idea "text of the idea" [--name slug]
            [--client X] [--lang auto|en|ta|tanglish] [--hub "C:/Users/<you>/Desktop/Dfren Video Editor"] [--placement organic|paid]

The four inputs (all required): raw video(s), the type of edit, exactly ONE reference video, a text description of the idea.
Creates <hub>/jobs/<date>_<slug>/ :
  inputs/raw/        copies of the raw files (read-only; originals are never touched)
  inputs/reference/  the ONE reference video (read-only copy)
  inputs/brief.md    type + idea, verbatim
  inputs/manifest.json   original paths, sha1, size, probe
  analysis/          transcripts, frame/contact sheets, speech window, colour, reference fingerprint, memory.md, style_brief.md (to fill)
  work/              creative_plan.json and generated assets go here (disposable)
  output/            the Resolve render, the .drp project export, the report (the deliverables)
Nothing is edited here. After this script the agent LOOKS at the sheets, fills analysis/style_brief.md, writes work/creative_plan.json.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import contact_sheet, extract_frame, find_workspace, probe_summary, save_json  # noqa: E402

VIDEO = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".webm", ".mxf", ".mts"}


def default_hub():
    for c in (Path.home() / "OneDrive" / "Desktop", Path.home() / "Desktop"):
        if c.is_dir():
            return c / "Dfren Video Editor"
    return Path.home() / "Dfren Video Editor"


def slug(s, n=40):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:n] or "job"


def sha1(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def copy_ro(src, dst_dir):
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / Path(src).name
    if not dst.exists():
        shutil.copy2(src, dst)
        os.chmod(dst, stat.S_IREAD)
    return dst


def rms_series(path, win=0.25):
    import numpy as np
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"], capture_output=True)
    x = np.frombuffer(r.stdout, dtype="<i2").astype(float) / 32768
    n = int(16000 * win)
    return [20 * np.log10(np.sqrt((x[i:i + n] ** 2).mean()) + 1e-9) for i in range(0, max(len(x) - n, 0), n)], win


def speech_window(path):
    """When speech really starts/ends (RMS 10 dB above the noise floor for >= 0.5 s). Whisper's own first-word times are
    unreliable after a silent lead-in (measured on the demo clip: it said 0.0 s, speech began at 4.8 s)."""
    import numpy as np
    s, win = rms_series(path)
    if len(s) < 4:
        return None
    floor = float(np.percentile(s, 20))
    thr = floor + 10
    hot = [v > thr for v in s]
    need = int(0.5 / win)
    start = end = None
    for i in range(len(hot) - need):
        if all(hot[i:i + need]):
            start = i * win
            break
    for i in range(len(hot) - 1, need, -1):
        if all(hot[i - need:i]):
            end = i * win
            break
    return {"start": round(start, 2) if start is not None else None, "end": round(end, 2) if end is not None else None,
            "noise_floor_db": round(floor, 1), "threshold_db": round(thr, 1)}


def sheet(path, out_jpg, max_tiles=44, width=216):
    info = probe_summary(path)
    dur = info["duration"]
    step = max(0.5, dur / max_tiles)
    times = [round(t, 2) for t in [i * step for i in range(int(dur / step) + 1)] if t < dur - 0.05]
    tmp = Path(out_jpg).parent / f"_tiles_{Path(out_jpg).stem}"
    tmp.mkdir(parents=True, exist_ok=True)
    files = []
    for i, t in enumerate(times):
        f = tmp / f"{i:03d}.jpg"
        extract_frame(path, t, f, width=width * 2)
        files.append(str(f))
    cols = 11 if info.get("orientation") == "vertical" else 6
    contact_sheet(files, out_jpg, cols=cols, thumb_w=width)
    shutil.rmtree(tmp, ignore_errors=True)
    save_json(Path(out_jpg).with_suffix(".json"), {"tile_n_time_s": {str(i + 1): t for i, t in enumerate(times)}, "seconds_per_tile": round(step, 2)})
    return times


def transcribe_region(path, lang, window, out_json, work):
    """Transcribe the speech region only (avoids Whisper's silent-lead-in timing errors), shift times back."""
    from analyze import transcribe
    try:
        from common import cuda_available
        gpu = cuda_available()
    except Exception:  # noqa: BLE001
        gpu = False
    model = "large-v3" if gpu else "small"
    src = str(path)
    off = 0.0
    if window and window.get("start") and window["start"] > 1.0:
        off = max(window["start"] - 0.4, 0)
        wav = Path(work) / (Path(path).stem + "_speech.wav")
        end = (window.get("end") or probe_summary(path)["duration"]) + 0.4
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{off:.2f}", "-t", f"{end - off:.2f}", "-i", str(path), "-vn", "-ac", "1",
                        "-ar", "16000", str(wav)], check=True)
        src = str(wav)
    t = transcribe(src, lang="auto" if lang in (None, "auto") else lang, model=model, device="cuda" if gpu else "cpu",
                   verbatim=(lang in ("en",)))
    for w in t.get("words", []):
        w["start"] = round(w["start"] + off, 3)
        w["end"] = round(w["end"] + off, 3)
    for s in t.get("segments", []):
        s["start"] = round(s["start"] + off, 3)
        s["end"] = round(s["end"] + off, 3)
    t["file"] = str(path)
    t["speech_offset"] = off
    save_json(out_json, t)
    return t


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", nargs="+", required=True)
    ap.add_argument("--reference", nargs="+", required=True)
    ap.add_argument("--type", dest="etype", required=True)
    ap.add_argument("--idea", required=True)
    ap.add_argument("--name")
    ap.add_argument("--client", default="")
    ap.add_argument("--lang", default="auto")
    ap.add_argument("--placement", default="organic", choices=["organic", "paid"])
    ap.add_argument("--hub")
    ap.add_argument("--no-transcribe", action="store_true")
    a = ap.parse_args()

    problems = []
    raws = [Path(p) for p in a.raw]
    for p in raws:
        if not p.is_file() or p.suffix.lower() not in VIDEO:
            problems.append(f"raw file missing or not a video: {p}")
    if len(a.reference) != 1:
        problems.append(f"exactly ONE reference video is required (got {len(a.reference)})")
    ref = Path(a.reference[0])
    if not ref.is_file() or ref.suffix.lower() not in VIDEO:
        problems.append(f"reference is missing or not a video: {ref}")
    if len(a.etype.strip()) < 3:
        problems.append("the type of edit is empty")
    if len(a.idea.strip()) < 10:
        problems.append("the text description of the idea is too short: ask the user for 1-3 sentences")
    if problems:
        print(json.dumps({"ok": False, "missing_or_invalid": problems}, indent=1))
        sys.exit(2)

    hub = Path(a.hub) if a.hub else default_hub()
    job = hub / "jobs" / f"{dt.date.today().isoformat()}_{slug(a.name or a.etype + ' ' + a.idea)}"
    n = 2
    base = job
    while job.exists():
        job = Path(f"{base}-{n}")
        n += 1
    for d in ("inputs/raw", "inputs/reference", "analysis", "work/assets", "output"):
        (job / d).mkdir(parents=True, exist_ok=True)
    manifest = {"created": dt.datetime.now().isoformat(timespec="seconds"), "client": a.client, "lang": a.lang, "placement": a.placement,
                "type": a.etype, "raw": [], "reference": None}
    raw_copies = []
    for p in raws:
        c = copy_ro(p, job / "inputs" / "raw")
        raw_copies.append(c)
        manifest["raw"].append({"original": str(p.resolve()), "copy": str(c), "sha1": sha1(p), "size": p.stat().st_size, "probe": probe_summary(c)})
    rc = copy_ro(ref, job / "inputs" / "reference")
    manifest["reference"] = {"original": str(ref.resolve()), "copy": str(rc), "sha1": sha1(ref), "size": ref.stat().st_size, "probe": probe_summary(rc)}
    (job / "inputs" / "brief.md").write_text(
        f"# Brief (verbatim from the user)\n\n**Type of edit:** {a.etype}\n\n**Idea / transition description:**\n\n{a.idea}\n\n"
        f"**Client:** {a.client or '-'}   **Language:** {a.lang}   **Placement:** {a.placement}\n", encoding="utf-8")
    save_json(job / "inputs" / "manifest.json", manifest)

    A = job / "analysis"
    summary = {"job": str(job), "raw": [], "reference": {}}
    # ---- raw footage
    from analyze import loudness
    from grade import analyze as grade_analyze
    for i, c in enumerate(raw_copies, 1):
        info = probe_summary(c)
        item = {"file": str(c), "duration": info["duration"], "res": f"{info.get('width')}x{info.get('height')}", "fps": info.get("fps")}
        if info["has_audio"]:
            item["loudness"] = loudness(c)
            item["speech_window"] = speech_window(c)
        sheet(c, A / f"raw_{i:02d}_sheet.jpg")
        try:
            g = grade_analyze(str(c), 10)
            save_json(A / f"raw_{i:02d}_colour.json", g)
            item["colour_flags"] = g["flags"]
        except Exception as e:  # noqa: BLE001
            item["colour_error"] = str(e)[:100]
        if info["has_audio"] and not a.no_transcribe:
            try:
                t = transcribe_region(c, a.lang, item.get("speech_window"), A / f"raw_{i:02d}_transcript.json", A)
                item["language"] = t.get("language")
                item["words"] = len(t.get("words", []))
                item["transcript_quality"] = t.get("quality")
                item["text"] = " ".join(s["text"] for s in t.get("segments", []))[:600]
            except Exception as e:  # noqa: BLE001
                item["transcript_error"] = str(e)[:160]
        summary["raw"].append(item)
    # ---- the ONE reference
    from ingest_references import analyse_video
    rinfo = probe_summary(rc)
    ra = analyse_video(str(rc), rinfo, A / "reference", 120)
    ra["probe"] = {k: rinfo.get(k) for k in ("duration", "width", "height", "fps", "orientation", "has_audio")}
    b = ra.get("motion_bursts", [])
    marks = [0.0] + [x["start"] for x in b] + [min(rinfo["duration"], 120)]
    ra["longest_static_s"] = round(max(marks[k + 1] - marks[k] for k in range(len(marks) - 1)), 2)
    ra["bursts_per_s"] = round(len(b) / max(rinfo["duration"], 1), 2)
    sheet(rc, A / "reference_dense.jpg", max_tiles=60, width=180)
    if rinfo["has_audio"] and not a.no_transcribe:
        try:
            ra["speech_window"] = speech_window(rc)
            t = transcribe_region(rc, "auto", ra["speech_window"], A / "reference_transcript.json", A)
            ra["transcript_text"] = " ".join(s["text"] for s in t.get("segments", []))[:800]
            ra["wpm"] = round(len(t.get("words", [])) / max(rinfo["duration"], 1) * 60)
        except Exception as e:  # noqa: BLE001
            ra["transcript_error"] = str(e)[:160]
    try:
        from style import load_styles, measure_reference, nearest_by_reference
        m = measure_reference(str(rc))
        ra["nearest_styles"] = nearest_by_reference(load_styles(), m)[:3]
    except Exception as e:  # noqa: BLE001
        ra["style_error"] = str(e)[:120]
    save_json(A / "reference_fingerprint.json", ra)
    summary["reference"] = {k: ra.get(k) for k in ("probe", "avg_shot_len", "bursts_per_s", "longest_static_s", "palette", "loudness", "wpm", "nearest_styles")}
    # ---- memory
    ws = find_workspace()
    words = " ".join(re.findall(r"[A-Za-z]{4,}", a.idea))[:300]
    mem = subprocess.run([sys.executable, str(Path(__file__).parent / "kb.py"), "context", "--client", a.client or "", "--words", words, "--budget", "3000"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ws) if ws else None)
    (A / "memory.md").write_text(mem.stdout or "(knowledge graph empty)", encoding="utf-8")
    # ---- style brief skeleton the agent MUST complete after looking at the sheets
    rf = summary["reference"]
    (A / "style_brief.md").write_text(f"""# Style brief (FILL THIS IN after LOOKING at analysis/reference_sheet + reference_dense + raw sheets)

## Measured (do not edit)
- Reference: {rf.get('probe')}  avg shot {rf.get('avg_shot_len')} s, {rf.get('bursts_per_s')} changes/s, longest static {rf.get('longest_static_s')} s, wpm {rf.get('wpm')}
- Reference palette: {[c.get('hex') for c in (rf.get('palette') or [])][:5]}   loudness {rf.get('loudness')}
- Nearest known styles: {rf.get('nearest_styles')}
- Type of edit asked: {a.etype}
- Idea (verbatim): {a.idea}

## What the reference does (fill by LOOKING; one line each; name the technique IDs from references/reference-analysis.md)
- Opening / hook (first 3 s):
- Pacing (shot length, cut rhythm, where it speeds up):
- Typography (size, weight, position, per-word animation, emphasis colour, how text enters/exits):
- Transitions (type, length, what covers the cut):
- Effects (zoom/shake/flash/glitch/speed ramps):
- Graphics / cards / HUD / overlays:
- Colour and grade:
- Sound (music energy, SFX on which events, voice treatment):
- Ending / CTA:

## Mapping to OUR footage and idea (fill)
| Reference element | Our equivalent | Source in raw footage (time) | Tool (Resolve-native / generated clip) |
|---|---|---|---|

## Decisions where the reference and the idea disagree (the idea wins; say why):
""", encoding="utf-8")
    save_json(A / "INTAKE_SUMMARY.json", summary)
    print(json.dumps({"ok": True, "job": str(job), "next": "LOOK at analysis/*_sheet.jpg and reference_dense.jpg, fill analysis/style_brief.md, write work/creative_plan.json, then make_assets.py and resolve_job.py",
                      "summary": summary}, indent=1, default=str)[:6000])


if __name__ == "__main__":
    main()
