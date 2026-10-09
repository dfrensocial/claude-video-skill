#!/usr/bin/env python3
"""Sort and measure everything dropped in references/inbox.

  ingest_references.py [--inbox DIR] [--sorted DIR] [--move] [--max-seconds 120]

For each file it: classifies it, copies (or --move) it into references/sorted/<kind>/, and for videos and
images extracts measurable facts. It never deletes anything and skips files already catalogued (by hash).

Outputs:
  references/catalog.json         one entry per file (kind, probe, measurements, sorted path, user note)
  references/REPORT.md            what was found + items that need a human decision
  sorted/<kind>/<stem>/sheet.jpg  numbered contact sheet (the agent LOOKS at these) + frames.json (tile -> time)

Measured for videos (<= max-seconds): scene cuts, motion-energy bursts (when things move on / off screen),
dominant palette, loudness. These are rough but real: motion bursts approximate entrance/exit timing; the
agent combines them with what it sees on the sheet to write a preset (see references/reference-ingest.md).
Optional naming convention to skip guessing:  <type>__<copy>__<name>.<ext>  e.g. caption__timing-only__bold-pop.mp4
"""
import argparse
import hashlib
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (AUDIO_EXT, IMAGE_EXT, VIDEO_EXT, contact_sheet, extract_frame, find_workspace,  # noqa: E402
                    have, load_json, probe_summary, run, save_json)

FONT_EXT = {".ttf", ".otf", ".ttc", ".woff", ".woff2"}
LUT_EXT = {".cube", ".3dl", ".look", ".dctl"}
RESOLVE_EXT = {".drx", ".drp", ".drt", ".setting", ".drfx", ".comp", ".dpx"}
TEMPLATE_EXT = {".mogrt", ".aep", ".aet", ".ffx", ".prproj", ".psd", ".ai", ".fcpxml", ".xml", ".edl", ".otio"}
DOC_EXT = {".txt", ".md", ".pdf", ".docx", ".json", ".csv", ".rtf"}
ARCHIVE_EXT = {".zip", ".rar", ".7z", ".tar", ".gz"}

TYPE_TAGS = {"caption", "title", "lowerthird", "transition", "hook", "cta", "broll", "sfx", "overlay", "endcard",
             "color", "screenshot", "typography", "layout", "dislike", "finished", "raw", "zoom", "kinetic"}


def sha1(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def classify(p, probe):
    ext = p.suffix.lower()
    if ext in FONT_EXT:
        return "fonts"
    if ext in LUT_EXT:
        return "luts"
    if ext in RESOLVE_EXT:
        return "resolve-assets"
    if ext in TEMPLATE_EXT:
        return "templates"
    if ext in ARCHIVE_EXT:
        return "archives"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in IMAGE_EXT:
        return "images"
    if ext in DOC_EXT:
        return "notes"
    if ext in VIDEO_EXT or ext == ".gif":
        d = (probe or {}).get("duration", 0)
        return "video-motion" if d <= 15 else "video-finished"
    return "unknown"


def parse_name(stem):
    parts = stem.split("__")
    if len(parts) >= 2 and parts[0].lower().replace("-", "").replace("_", "") in TYPE_TAGS:
        return {"declared_type": parts[0].lower(), "copy": parts[1] if len(parts) > 2 else "", "label": parts[-1]}
    return {}


def palette(images_or_video, k=5, is_video=False, seconds=None):
    """Dominant colours via a tiny k-means on 48px frames. Returns [{'hex','pct'}]. Needs numpy."""
    try:
        import numpy as np
    except ImportError:
        return []
    cmd = ["ffmpeg", "-v", "error", "-i", str(images_or_video)]
    if is_video:
        cmd += ["-vf", "fps=2,scale=48:-2"]
    else:
        cmd += ["-vf", "scale=48:-2"]
    if seconds:
        cmd[3:3] = ["-t", str(seconds)]
    cmd += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    r = __import__("subprocess").run(cmd, capture_output=True)
    if not r.stdout:
        return []
    data = np.frombuffer(r.stdout, dtype=np.uint8).reshape(-1, 3).astype(np.float32)
    if len(data) > 40000:
        data = data[np.random.default_rng(0).choice(len(data), 40000, replace=False)]
    rng = np.random.default_rng(1)
    cent = data[rng.choice(len(data), min(k, len(data)), replace=False)]
    for _ in range(12):
        lab = ((data[:, None, :] - cent[None]) ** 2).sum(-1).argmin(1)
        for i in range(len(cent)):
            m = lab == i
            if m.any():
                cent[i] = data[m].mean(0)
    counts = [(lab == i).sum() for i in range(len(cent))]
    tot = sum(counts)
    order = sorted(range(len(cent)), key=lambda i: -counts[i])
    return [{"hex": "#%02x%02x%02x" % tuple(int(x) for x in cent[i]), "pct": round(100 * counts[i] / tot, 1)} for i in order]


def motion_energy(path, info, max_seconds):
    """Mean absolute frame difference over time at 15 fps, 96px wide. Returns (times, energy) or None."""
    try:
        import numpy as np
    except ImportError:
        return None
    w = 96
    h = max(2, int(round(w * info["height"] / info["width"] / 2)) * 2)
    cmd = ["ffmpeg", "-v", "error", "-t", str(max_seconds), "-i", str(path), "-an",
           "-vf", f"fps=15,scale={w}:{h},format=gray", "-f", "rawvideo", "-"]
    r = __import__("subprocess").run(cmd, capture_output=True)
    n = len(r.stdout) // (w * h)
    if n < 3:
        return None
    arr = np.frombuffer(r.stdout[:n * w * h], dtype=np.uint8).reshape(n, h, w).astype(np.float32)
    e = np.abs(np.diff(arr, axis=0)).mean(axis=(1, 2))
    return [round(i / 15.0, 3) for i in range(1, n)], e


def bursts(times, e):
    import numpy as np
    thr = max(0.8, 0.2 * float(np.percentile(e, 95)))
    out, start = [], None
    for t, v in zip(times, e):
        if v > thr and start is None:
            start = t
        elif v <= thr and start is not None:
            seg = [x for tt, x in zip(times, e) if start <= tt <= t]
            out.append({"start": round(start, 2), "end": round(t, 2), "peak": round(float(max(seg)), 1)})
            start = None
    if start is not None:
        out.append({"start": round(start, 2), "end": round(times[-1], 2), "peak": round(float(e.max()), 1)})
    return [b for b in out if b["end"] - b["start"] >= 0.07]


def analyse_video(p, info, outdir, max_seconds):
    from analyze import loudness, scenes  # local import to keep startup light
    res = {}
    dur = min(info["duration"], max_seconds)
    outdir.mkdir(parents=True, exist_ok=True)
    cuts = scenes(p, 0.3)["cuts"]
    res["scene_cuts"] = [c for c in cuts if c <= dur]
    res["avg_shot_len"] = round(dur / (len(res["scene_cuts"]) + 1), 2)
    me = motion_energy(p, info, max_seconds)
    if me:
        res["motion_bursts"] = bursts(*me)
    res["palette"] = palette(p, is_video=True, seconds=max_seconds)
    if info["has_audio"]:
        res["loudness"] = loudness(p)
    # contact sheet: even samples + the start/end of every motion burst (that is where entrances/exits live)
    times = [dur * i / 11 for i in range(12)]
    for b in res.get("motion_bursts", [])[:6]:
        times += [b["start"], (b["start"] + b["end"]) / 2, b["end"]]
    times = sorted({round(min(max(t, 0), max(dur - 0.05, 0)), 2) for t in times})[:24]
    tmp = Path(tempfile.mkdtemp())
    frames = []
    for i, t in enumerate(times, 1):
        f = tmp / f"{i:03d}.jpg"
        extract_frame(p, t, f, width=360)
        frames.append(str(f))
    contact_sheet(frames, outdir / "sheet.jpg", cols=6 if info["orientation"] != "vertical" else 8, thumb_w=216 if info["orientation"] == "vertical" else 320)
    save_json(outdir / "frames.json", {"tiles_row_major_from_1": times})
    res["sheet"] = str(outdir / "sheet.jpg")
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inbox")
    ap.add_argument("--sorted")
    ap.add_argument("--move", action="store_true", help="move instead of copy (originals leave the inbox)")
    ap.add_argument("--max-seconds", type=float, default=120)
    a = ap.parse_args()
    ws = find_workspace()
    if not ws:
        raise SystemExit("workspace.json not found - run setup_workspace.py")
    inbox = Path(a.inbox) if a.inbox else ws / "references" / "inbox"
    sorted_dir = Path(a.sorted) if a.sorted else ws / "references" / "sorted"
    cat_path = ws / "references" / "catalog.json"
    catalog = load_json(cat_path, []) or []
    seen = {c["sha1"] for c in catalog}
    if not have("ffmpeg"):
        raise SystemExit("ffmpeg required")

    files = [p for p in sorted(inbox.rglob("*")) if p.is_file() and not p.name.startswith(".")]
    new, needs_decision = [], []
    for p in files:
        if p.suffix.lower() in (".txt", ".md") and any(q != p and q.stem == p.stem for q in files):
            continue  # sidecar note for another file: read as that file's user_note, not catalogued separately
        h = sha1(p)
        if h in seen:
            continue
        seen.add(h)  # also dedupe identical files inside this same batch
        try:
            probe = probe_summary(p) if p.suffix.lower() in (VIDEO_EXT | AUDIO_EXT | IMAGE_EXT | {".gif"}) else None
        except Exception:  # noqa: BLE001
            probe = None
        kind = classify(p, probe)
        meta = parse_name(p.stem)
        note_file = next((p.with_suffix(s) for s in (".txt", ".md") if p.with_suffix(s).exists() and p.with_suffix(s) != p), None)
        entry = {"id": f"{kind}-{h[:8]}", "sha1": h, "original": str(p), "kind": kind, "name": p.name,
                 "declared": meta, "user_note": note_file.read_text(encoding="utf-8", errors="ignore")[:1000] if note_file else "",
                 "status": "unreviewed"}
        dest_dir = sorted_dir / kind
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / p.name
        if dest.exists():
            dest = dest_dir / f"{p.stem}_{h[:6]}{p.suffix}"
        (shutil.move if a.move else shutil.copy2)(str(p), str(dest))
        entry["sorted"] = str(dest)
        try:
            if kind in ("video-motion", "video-finished") and probe and probe["has_video"]:
                entry["probe"] = probe
                entry["analysis"] = analyse_video(dest, probe, dest_dir / dest.stem, a.max_seconds)
                if kind == "video-finished":
                    needs_decision.append(f"{p.name}: long video ({probe['duration']:.0f}s) - finished sample for a style "
                                          "fingerprint, a raw clip, or a motion reference? (name it final__ / raw__ to skip this)")
            elif kind == "images":
                im = probe or probe_summary(p)
                entry["probe"] = im
                entry["analysis"] = {"palette": palette(dest)}
                ar = im["height"] / im["width"] if im.get("width") else 0
                entry["analysis"]["looks_like"] = ("phone screenshot / vertical frame" if ar > 1.6 else
                                                   "desktop/horizontal frame" if ar < 0.8 else "square-ish")
            elif kind == "fonts":
                r = run(["fc-scan", "--format", "%{family} | %{style} | %{lang}\\n", str(dest)], check=False) if have("fc-scan") else None
                if r and r.stdout.strip():
                    fam, style, lang = [x.strip() for x in r.stdout.splitlines()[0].split("|", 2)]
                    entry["analysis"] = {"font": f"{fam} {style}", "supports_tamil": "ta" in lang.split("|")}
            elif kind == "audio":
                entry["probe"] = probe
                needs_decision.append(f"{p.name}: audio file - SFX, music, or voice sample? Add it to your SFX/music library path instead.")
            elif kind in ("archives", "unknown"):
                needs_decision.append(f"{p.name}: cannot auto-process ({kind}). Extract it into the inbox or tell me what it is.")
        except Exception as e:  # noqa: BLE001
            entry["analysis_error"] = str(e)[:300]
        if kind in ("video-motion", "images") and not meta and not entry["user_note"]:
            needs_decision.append(f"{p.name}: no note - what should be copied from it (entrance timing, layout, colours, caption style)?")
        catalog.append(entry)
        new.append(entry)

    save_json(cat_path, catalog)
    lines = ["# Reference ingest report", "", f"- New files processed: **{len(new)}**  (total catalogued: {len(catalog)})", ""]
    by = {}
    for e in new:
        by.setdefault(e["kind"], []).append(e)
    for k, v in by.items():
        lines.append(f"## {k} ({len(v)})")
        for e in v:
            an = e.get("analysis", {})
            extra = ""
            if "palette" in an and an["palette"]:
                extra += " palette " + ", ".join(c["hex"] for c in an["palette"][:4])
            if "avg_shot_len" in an:
                extra += f"; avg shot {an['avg_shot_len']}s; {len(an.get('motion_bursts', []))} motion bursts"
            if an.get("sheet"):
                extra += f"; sheet: {an['sheet']}"
            lines.append(f"- {e['name']} -> {e['sorted']}{extra}")
        lines.append("")
    if needs_decision:
        lines += ["## Needs a human decision", ""] + [f"- {d}" for d in needs_decision]
    (ws / "references" / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(new)} new reference file(s) sorted. Report: {ws / 'references' / 'REPORT.md'}")


if __name__ == "__main__":
    main()
