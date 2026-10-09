#!/usr/bin/env python3
"""One command for the deterministic part of an edit: footage + brief + style  ->  finished draft mp4 + report (no Resolve needed).

  pipeline.py --job NAME --footage FILE_OR_DIR [FILE ...] [--brief "..."] [--client X] [--lang auto|en|tanglish]
              [--style ID | a+b | auto] [--ref REFERENCE.mp4] [--length SECONDS] [--placement organic|paid]
              [--grade auto|none|keep] [--lut X.cube] [--palette-option N] [--font bebas] [--cards cards.json]
              [--overlays overlays.json] [--music FILE] [--script script.txt] [--w 1080 --h 1920 --fps 30] [--force] [--preview-only]

Steps (each skipped if its output exists, unless --force; all artefacts in jobs/NAME/):
  1 style plan        style.py plan            -> style_plan.json/.md (+ asset candidate sheets, memory rules applied)
  2 transcripts       analyze.py transcribe     -> transcripts/*.json   (Tanglish: large-v3 + ta profile; quality flag kept)
  3 romanise          romanize.py               -> *.roman.transcript.json (Tamil script -> Tanglish, only when language is ta)
  4 cut plan          cut_plan.py               -> cut/cut_plan.json (+ .md to READ before trusting it)
  5 captions          captions.py + captions_ass.py -> captions.json, captions.ass (animated, safe-zone aware)
  6 colour            grade.py analyze          -> grade.json (CDL suggestion; coloured backgrounds are never neutralised)
  7 palette           palette.py                -> palette.json (per-video accent options, option --palette-option is used)
  8 graphics cards    graphics.py render        -> cards from --cards (the agent/user decide WHAT and WHEN; numbers verbatim from the brief)
  9 compose + SFX     compose.py + sfxplan.py   -> spec.json, draft_preview.mp4, final mp4 in exports/
 10 QC + report       qc.py check               -> qc.json, report.md

cards.json: [{"template":"count-up","start":4.2,"show_s":2.6,"vars":{"value":151250,"label":"Total Amount"}}, ...]
overlays.json: [{"file":"assets/.../Blast.mov","start":4.6,"blend":"screen","opacity":0.9}, ...]   (compose.py overlay format)
Honest limits: the cut plan is a first pass (read cut_plan.md); captions from an UNRELIABLE transcript are skipped unless
a script/SRT is supplied; no music is added unless --music is given; I cannot hear the result.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from common import find_workspace, load_json, probe_summary, save_json  # noqa: E402

PY = sys.executable


def run(cmd, log, check=True):
    log.write(f"\n$ {' '.join(map(str, cmd))}\n")
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", errors="replace")
    log.write((r.stdout or "")[-3000:] + (r.stderr or "")[-1500:])
    log.flush()
    if check and r.returncode != 0:
        raise SystemExit(f"step failed ({r.returncode}): {' '.join(map(str, cmd))[:200]}\n{(r.stderr or r.stdout)[-1200:]}")
    return r


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "x").lower()).strip("-") or "x"


def pick_font(keyword):
    from typeboard import all_fonts, find_font
    fp = find_font(keyword, all_fonts())
    return fp


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", required=True)
    ap.add_argument("--footage", nargs="+", required=True)
    ap.add_argument("--brief", default="")
    ap.add_argument("--client", default="")
    ap.add_argument("--lang", default="auto")
    ap.add_argument("--style")
    ap.add_argument("--ref")
    ap.add_argument("--length", type=float)
    ap.add_argument("--placement", default="organic", choices=["organic", "paid"])
    ap.add_argument("--grade", default="auto", choices=["auto", "none", "keep"])
    ap.add_argument("--lut")
    ap.add_argument("--palette-option", type=int, default=0)
    ap.add_argument("--font")
    ap.add_argument("--cards")
    ap.add_argument("--overlays")
    ap.add_argument("--music")
    ap.add_argument("--script")
    ap.add_argument("--model", default=None)
    ap.add_argument("--w", type=int, default=1080)
    ap.add_argument("--h", type=int, default=1920)
    ap.add_argument("--fps", type=float, default=30)
    ap.add_argument("--version", default="v1")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--preview-only", action="store_true")
    a = ap.parse_args()

    ws = find_workspace()
    jd = ws / "jobs" / a.job
    jd.mkdir(parents=True, exist_ok=True)
    log = open(jd / "pipeline.log", "a", encoding="utf-8")
    t0 = time.time()
    notes, flags = [], []
    S = HERE

    def step(name):
        print(f"[{time.time() - t0:5.0f}s] {name}", flush=True)

    # files
    files = []
    for p in a.footage:
        p = Path(p)
        files += sorted(f for f in p.rglob("*") if f.suffix.lower() in {".mp4", ".mov", ".mkv", ".m4v"}) if p.is_dir() else [p]
    if not files:
        raise SystemExit("no footage found")

    # 1 style plan
    step("1 style plan")
    sp_json = jd / "style_plan.json"
    if a.force or not sp_json.exists():
        cmd = [PY, S / "style.py", "plan", "--job", a.job, "--footage", *map(str, files), "--brief", a.brief]
        if a.client:
            cmd += ["--client", a.client]
        if a.style:
            cmd += ["--style", a.style]
        if a.ref:
            cmd += ["--ref", a.ref]
        if a.length:
            cmd += ["--length", a.length]
        if a.lang != "auto":
            cmd += ["--lang", a.lang]
        run(cmd, log)
    sp = load_json(sp_json, {})
    style_id = sp.get("style")
    cap_cfg = sp.get("captions") or {}
    notes.append(f"style: {style_id} ({'; '.join(sp.get('why', []))})")

    # 2 transcripts (+3 romanise)
    step("2 transcripts")
    tdir = jd / "transcripts"
    tdir.mkdir(exist_ok=True)
    tx_paths, unreliable_all = [], False
    for f in files:
        tj = tdir / f"{f.stem}.transcript.json"
        if a.force or not tj.exists():
            cmd = [PY, S / "analyze.py", "transcribe", f, "--lang", "tanglish" if a.lang == "tanglish" else a.lang]
            if a.model:
                cmd += ["--model", a.model]
            r = run(cmd, log)
            tj.write_text(r.stdout, encoding="utf-8")
        t = load_json(tj, {})
        q = t.get("quality", {})
        if q.get("unreliable"):
            unreliable_all = True
            flags.append(f"transcript of {f.name} is UNRELIABLE (low-conf {q.get('low_conf_ratio')}); bad ranges: {q.get('unreliable_ranges')[:6]}")
        if t.get("language") == "ta":
            step("3 romanise")
            rj = tdir / f"{f.stem}.roman.transcript.json"
            if a.force or not rj.exists():
                run([PY, S / "romanize.py", tj, "--out", rj], log)
                rt = load_json(rj, {})
                rt["file"] = str(f.resolve())
                save_json(rj, rt)
            tx_paths.append(rj)
        else:
            tx_paths.append(tj)

    # 4 cut plan
    step("4 cut plan")
    cdir = jd / "cut"
    if a.force or not (cdir / "cut_plan.json").exists():
        cmd = [PY, S / "cut_plan.py", "--transcripts", *map(str, tx_paths), "--out", cdir]
        if a.script:
            cmd += ["--script", a.script]
        run(cmd, log)
    cp = load_json(cdir / "cut_plan.json", {})
    notes.append(f"cut: kept {cp.get('kept_duration')}s of {cp.get('raw_duration')}s, confidence {cp.get('confidence')}, review items {len(cp.get('review', []))}")
    if cp.get("confidence", 1) < 0.7:
        flags.append("cut plan confidence below 0.7: read cut/cut_plan.md before trusting this edit")
    if not cp.get("keep"):
        raise SystemExit("cut plan kept nothing; check transcripts")

    # cards are read early: their time windows decide where captions must step aside
    cards_list = load_json(a.cards, []) if a.cards else []
    plate_windows = []
    for c in cards_list:
        mode = (c.get("vars") or {}).get("plate_mode", "none" if c["template"] == "count-up" else "full")
        if mode in ("full", "card"):
            s = float(c["start"])
            plate_windows.append((s, s + float(c.get("dur") or (float(c.get("show_s", 3.0)) + 0.4))))

    # 5 captions
    step("5 captions")
    capj, ass = jd / "captions.json", jd / "captions.ass"
    skip_caps = unreliable_all and not a.script
    if skip_caps:
        flags.append("captions SKIPPED: transcript unreliable and no script/SRT supplied (a wrong caption is worse than none)")
    else:
        mw = str(cap_cfg.get("max_words", 2))
        if a.force or not capj.exists():
            run([PY, S / "captions.py", cdir / "cut_plan.json", "--out", capj, "--max-words", mw], log)
        # 7 palette first (captions colours need it)
        step("7 palette")
        pj = jd / "palette.json"
        if a.force or not pj.exists():
            run([PY, S / "palette.py", "--video", files[0], "--style", style_id or "", "--out", pj], log, check=False)
        pal = load_json(pj, {}) or {}
        opt = (pal.get("options") or [{}])
        opt = opt[min(a.palette_option, len(opt) - 1)] if opt else {}
        accent, text = opt.get("accent", "#E8AA05"), opt.get("text", "#FFFFFF")
        notes.append(f"palette option {a.palette_option}: accent {accent}, text {text} ({opt.get('name')})")
        from captions_ass import build_ass, family_of
        kw = a.font or ("montserrat" if (sp.get("captions") or {}).get("case") == "normal" and style_id in ("yellow-infocard-tanglish",) else "bebas")
        fp = pick_font(kw)
        family = family_of(fp) if fp else "Arial"
        size = 150 if "bebas" in kw.lower() else 108
        if a.force or not ass.exists():
            ev_all = (load_json(capj, {}) or {}).get("events", [])
            # captions step aside while a full-screen card is up (the card carries the message; both would clutter)
            ev = [e for e in ev_all if not any(e["start"] < w1 and e["end"] > w0 for w0, w1 in plate_windows)]
            if len(ev) < len(ev_all):
                notes.append(f"captions hidden during {len(plate_windows)} full-screen card(s): {len(ev_all) - len(ev)} event(s) removed")
            y_list = cap_cfg.get("y_pct") or [30, 40]
            ass.write_text(build_ass(ev, a.w, a.h, family, "Nirmala UI", text, accent, size, sum(y_list) / len(y_list),
                                     a.placement == "paid", "pop"), encoding="utf-8")
        notes.append(f"captions: font {family}, {len(ev if 'ev' in dir() else [])} events, placement {a.placement}")

    # 6 colour
    step("6 colour")
    gj = jd / "grade.json"
    grade = {}
    if a.grade != "none":
        if a.force or not gj.exists():
            run([PY, S / "grade.py", "analyze", files[0], "--out", gj], log, check=False)
        g = load_json(gj, {}) or {}
        notes.append(f"colour flags: {g.get('flags')}")
        if a.grade == "auto" and g.get("suggest"):
            grade["cdl"] = g["suggest"]["cdl"]
    if a.lut:
        grade["lut"] = str(Path(a.lut).resolve())

    # 8 cards
    step("8 graphics cards")
    overlays = []
    if a.cards:
        from graphics import render as grender
        for i, c in enumerate(cards_list):
            out = jd / "cards" / f"{i:02d}_{c['template']}.mov"
            cvars = dict(c.get("vars", {}))
            if c["template"] == "count-up":
                cvars.setdefault("y_pct", 58)  # below the caption band (captions sit at ~30-40 %)
            if a.force or not out.exists():
                r = grender(c["template"], cvars, str(out), "mov", c.get("quality", "looks"),
                            str(jd / "palette.json") if (jd / "palette.json").exists() else None, a.palette_option, c.get("show_s"))
            overlays.append({"file": str(out), "start": float(c["start"]), "dur": float(c.get("dur") or (float(c.get("show_s", 3.0)) + 0.4)),
                             "blend": "normal", "width_frac": 1.0, "x": 0, "y": 0})
    if a.overlays:
        overlays += load_json(a.overlays, []) or []

    # 9 compose
    step("9 compose + SFX + render")
    spec_p = jd / "spec.json"
    zoom = 1.08 if (sp.get("rhythm") or {}).get("avg_shot_s", [2, 3])[0] < 1.5 or True else 0
    ratio = "9x16" if a.h > a.w else ("16x9" if a.w > a.h else "1x1")
    final = ws / "exports" / f"{slug(a.client or 'dfren')}_{slug(a.job)}_{ratio}_{a.w}x{a.h}_{a.version}.mp4"
    cmd = [PY, S / "compose.py", "from-cutplan", cdir / "cut_plan.json", "--out", spec_p, "--out-video", final, "--w", a.w, "--h", a.h,
           "--fps", a.fps, "--zoom-alt", zoom]
    if ass.exists() and not skip_caps:
        cmd += ["--captions", ass]
    run(cmd, log)
    spec = load_json(spec_p, {})
    spec["grade"] = grade
    spec["overlays"] = overlays
    if a.music:
        spec["music"] = {"file": str(Path(a.music).resolve()), "gain_db": (sp.get("music") or {}).get("duck_db", -14) - 6, "duck": True, "fade_out": 1.0}
    save_json(spec_p, spec)
    dens = (sp.get("sfx") or {}).get("density_per_s")
    sfxcmd = [PY, S / "sfxplan.py", spec_p]
    if capj.exists() and not skip_caps:
        sfxcmd += ["--captions", capj]
    if dens:
        sfxcmd += ["--style-density", dens]
    run(sfxcmd, log, check=False)
    prev = jd / "draft_preview.mp4"
    spec_prev = load_json(spec_p, {})
    spec_prev["output"]["file"] = str(prev)
    save_json(jd / "spec_preview.json", spec_prev)
    run([PY, S / "compose.py", "render", jd / "spec_preview.json", "--preview"], log)
    if not a.preview_only:
        run([PY, S / "compose.py", "render", spec_p], log)
    outp = prev if a.preview_only else final

    # 10 QC + report
    step("10 QC + report")
    qj = jd / "qc.json"
    r = run([PY, S / "qc.py", "check", outp, "--expect-res", f"{a.w}x{a.h}", "--out", qj], log, check=False)
    qc = load_json(qj, {}) or {}
    bad = [c for c in qc.get("checks", []) if c["status"] != "PASS"]
    card_windows = [(float(c["start"]), float(c["start"]) + float(c.get("dur") or (float(c.get("show_s", 3.0)) + 0.4))) for c in cards_list]
    for c in bad:
        if c["check"] == "frozen frames":
            # a card holding on its finished state is an intended hold, not a stuck clip
            spans = [(float(x), float(y)) for x, y in re.findall(r"([\d.]+)-([\d.]+)s", c["detail"])]
            if spans and all(any(s >= w0 - 0.2 and e <= w1 + 0.2 for w0, w1 in card_windows) for s, e in spans):
                notes.append(f"QC frozen frames {spans} are inside card holds (expected)")
                continue
        flags.append(f"QC {c['status']}: {c['check']}: {c['detail']}")
    info = probe_summary(outp)
    rep = [f"# Report: {a.job}", f"- Output: `{outp}` ({info['duration']:.1f}s, {info.get('width')}x{info.get('height')}, {info.get('fps')} fps)",
           f"- Preview: `{prev}`", f"- Style plan: `{jd / 'style_plan.md'}`", "", "## What was done"] + [f"- {n}" for n in notes]
    rep += ["", "## Flags (read these)"] + ([f"- {f}" for f in flags] or ["- none"])
    rep += ["", "## Not verified", "- I cannot hear the audio or watch motion: judge pacing, caption timing and SFX by eye/ear.",
            "- Cut plan is a first pass: read `cut/cut_plan.md`.", f"- Elapsed {time.time() - t0:.0f}s"]
    (jd / "report.md").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print("\n".join(rep))


if __name__ == "__main__":
    main()
