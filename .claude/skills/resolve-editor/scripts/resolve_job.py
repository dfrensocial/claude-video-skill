#!/usr/bin/env python3
"""STEP 5-8 of the SOP: build the job in DaVinci Resolve Studio (mandatory), render FROM Resolve, export the project, review.

  resolve_job.py build  JOB_DIR [--version v1]       project "Dfren - <job>", bins, timeline, all tracks (see TRACK MAP)
  resolve_job.py render JOB_DIR [--version v1]       Resolve's own render -> output/<client>_<job>_<ratio>_<WxH>_<version>.mp4
  resolve_job.py export JOB_DIR                      output/<job>.drp (the whole Resolve project, openable on any Resolve Studio)
  resolve_job.py review JOB_DIR                      contact sheet + QC of the Resolve render -> output/review_sheet.jpg, output/qc.json
  resolve_job.py all    JOB_DIR                      build + render + export + review

Runs under any Python (re-runs itself under `py -3.13` when this Python cannot load Resolve's module). Standard library only.

TRACK MAP (video, bottom to top) -> every element is its own clip so the user can move/trim/replace/delete it:
  V1  A-roll (cleaned-voice copy of the raw; sub-clips carry NATIVE stepped punch-in Zoom/Pan/Tilt and the CDL/LUT grade)
  V2..Vn  native title clips (real, retypable Resolve titles imported from generated FCPXML: font, size, colour, position)
  then, each category on its own tracks, in this stacking order:  cutaways -> glitch -> typography -> flashes/fire wipes/licks -> HUD
Audio: A1 voice (from the A-roll clips), A2.. each sound event as its own clip (booms, risers, whooshes ...), drone on its own track.
Markers: one per plan marker, transition and title.  Clip colours: typography Orange, fire/flash Red, glitch Pink, cutaway Blue, sound Green.
What is NOT native (and stays honest): the motion INSIDE typography/fire/glitch clips is baked (they are clips, not keyframed Text+); keyframed
animation on imported titles is dropped by Resolve's FCPXML import (only static titles survive); audio gain cannot be scripted (stems are pre-gained).
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import connect_resolve as _connect  # noqa: E402
import resolve_build as rb  # noqa: E402

def connect_resolve():
    """Connect to Resolve Studio; if it is not running, start it (it exits on its own now and then) and wait for scripting to answer."""
    try:
        return _connect()
    except Exception:  # noqa: BLE001
        exe = r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe"
        running = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Resolve.exe"], capture_output=True, text=True).stdout
        if "Resolve.exe" not in running and os.path.exists(exe):
            subprocess.Popen([exe])
        last = None
        for _ in range(24):
            time.sleep(10)
            try:
                return _connect()
            except Exception as e:  # noqa: BLE001
                last = e
        raise SystemExit(f"Resolve did not come up: {last}")


CAT_ORDER = ["cutaway", "glitch", "typography", "transition", "hud"]
COLORS = {"typography": "Orange", "hud": "Yellow", "transition": "Red", "flash": "Red", "glitch": "Pink", "cutaway": "Blue", "sound": "Green"}


def jload(p, default=None):
    try:
        return json.load(open(p, encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001
        return default


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def probe_dur(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


# ------------------------------------------------------------------ native titles via FCPXML
def titles_fcpxml(plan, out_path):
    """Static, editable titles: lanes compact to V2.. on import. position units = % of frame HEIGHT, +y up (measured)."""
    W, H = plan.get("size", [1080, 1920])
    fps = int(plan.get("fps", 30))
    total = int(round(float(plan["duration"]) * fps))
    tc = 3600

    def a(sec):
        return f"{int(round((tc + sec) * fps))}/{fps}s"

    lanes, body = [], []
    for k, t in enumerate(sorted(plan.get("native_titles", []), key=lambda x: x["t"])):
        s, e = float(t["t"]), float(t["t"]) + float(t["dur"])
        for i, end in enumerate(lanes):
            if s >= end - 1e-6:
                lanes[i] = e
                lane = i + 1
                break
        else:
            lanes.append(e)
            lane = len(lanes)
        x_px, y_px = t.get("pos_px", [W / 2, H * float(t.get("y_pct", 50)) / 100])
        ux, uy = (x_px - W / 2) / (H / 100.0), (H / 2 - y_px) / (H / 100.0)
        col = " ".join(str(v) for v in (t.get("color", [1, 1, 1]) + [1])[:4])
        dur_f = int(round(float(t["dur"]) * fps))
        body.append(f'''<title ref="r2" lane="{lane}" offset="{a(s)}" name="{esc(t.get('name', t['text'])[:40])}" duration="{dur_f}/{fps}s" start="{tc}s">
          <text><text-style ref="ts{k}">{esc(t['text'])}</text-style></text>
          <text-style-def id="ts{k}"><text-style font="{esc(t.get('font', 'Montserrat'))}" fontSize="{t.get('size', 90) * 1080.0 / H:.1f}" fontColor="{col}" bold="{1 if t.get('bold', True) else 0}" alignment="center"/></text-style-def>
          <adjust-transform position="{ux:.3f} {uy:.3f}" scale="1 1"/></title>''')
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.9"><resources>
<format id="r1" name="FFVideoFormat{H}p{fps}" frameDuration="1/{fps}s" width="{W}" height="{H}" colorSpace="1-1-1 (Rec. 709)"/>
<effect id="r2" name="Basic Title" uid=".../Titles.localized/Build In:Out.localized/Basic Title.localized/Basic Title.moti"/></resources>
<library><event name="Dfren"><project name="Titles">
<sequence format="r1" duration="{total}/{fps}s" tcStart="{tc}s" tcFormat="NDF"><spine>
<gap name="Gap" offset="{tc}s" duration="{total}/{fps}s" start="{tc}s">{''.join(body)}</gap></spine></sequence></project></event></library></fcpxml>'''
    Path(out_path).write_text(xml, encoding="utf-8")
    return out_path


# ------------------------------------------------------------------ V1 segmentation (cuts + native stepped punches/shake)
def v1_segments(plan):
    """Return [{"clip", "T0", "T1", "src_in", "zoom", "pan", "tilt", "cdl"}] covering the whole timeline in 1-frame-aligned pieces."""
    fps = int(plan.get("fps", 30))
    clips, T = [], 0.0
    for c in plan["clips"]:
        d = float(c["out"]) - float(c["in"])
        clips.append((c, T, T + d))
        T += d
    marks = {0.0, T}
    for c, a, b in clips:
        marks.update((a, b))
    base = sorted(plan.get("base_zoom", [[0, 1.0]]))
    marks.update(float(x[0]) for x in base)
    for p in plan.get("punches", []):
        s = float(p["t"])
        steps = p.get("steps", [[0.07, 1.0], [0.10, 0.5], [0.13, 0.2]])
        t = s
        marks.add(s)
        for dt, _ in steps:
            t += dt
            marks.add(t)
    for sh_ in plan.get("shakes", []):
        s, d = float(sh_["t"]), float(sh_["dur"])
        n = max(2, int(round(d * fps / 2)))
        for i in range(n + 1):
            marks.add(s + i * 2 / fps)
    for g in plan.get("grade_changes", []):
        marks.add(float(g["t"]))
    marks = sorted({round(round(m * fps) / fps, 5) for m in marks if 0 <= m <= T + 1e-6})

    def base_zoom(t):
        z = base[0][1]
        for tt, zz in base:
            if t >= tt - 1e-9:
                z = zz
        return z

    def punch_extra(t):
        ex = 0.0
        for p in plan.get("punches", []):
            amp = float(p.get("zoom", 1.15)) - 1.0
            s = float(p["t"])
            cur = s
            for dt, k in p.get("steps", [[0.07, 1.0], [0.10, 0.5], [0.13, 0.2]]):
                if cur - 1e-9 <= t < cur + dt - 1e-9:
                    ex = max(ex, amp * k)
                cur += dt
        return ex

    def shake(t):
        px, py = 0.0, 0.0
        for k, s_ in enumerate(plan.get("shakes", [])):
            s, d, amp = float(s_["t"]), float(s_["dur"]), float(s_.get("px", 12))
            if s - 1e-9 <= t < s + d:
                i = int(round((t - s) * fps / 2))
                decay = math.exp(-5 * (t - s) / d)
                px += amp * decay * math.sin(2.7 * i + 1.3 * k)
                py += amp * decay * math.sin(3.9 * i + 2.1 * k)
        return px, py

    def cdl_for(t):
        cur = plan.get("grade", {}).get("cdl")
        for g in sorted(plan.get("grade_changes", []), key=lambda x: x["t"]):
            if t >= float(g["t"]) - 1e-9:
                cur = g["cdl"]
        return cur

    segs = []
    for a, b in zip(marks, marks[1:]):
        if b - a < 0.5 / fps:
            continue
        mid = (a + b) / 2
        c = next((cc for cc in clips if cc[1] - 1e-9 <= mid < cc[2] + 1e-9), None)
        if not c:
            continue
        clip, c0, _ = c
        z = base_zoom(mid) + punch_extra(mid)
        px, py = shake(mid)
        if abs(px) + abs(py) > 0.5:
            z = max(z, 1.05)
        segs.append({"clip": clip, "T0": a, "T1": b, "src_in": float(clip["in"]) + (a - c0), "zoom": round(z, 4), "pan": round(px, 1),
                     "tilt": round(py, 1), "cdl": cdl_for(mid)})
    # merge neighbours with identical state inside the same clip
    out = []
    for s in segs:
        if out and out[-1]["clip"] is s["clip"] and (out[-1]["zoom"], out[-1]["pan"], out[-1]["tilt"], out[-1]["cdl"]) == (s["zoom"], s["pan"], s["tilt"], s["cdl"]):
            out[-1]["T1"] = s["T1"]
        else:
            out.append(dict(s))
    return out


# ------------------------------------------------------------------ build
def build(job, version):
    plan = jload(job / "work" / "creative_plan.json")
    man = jload(job / "work" / "assets" / "manifest.json")
    if not plan or not man:
        raise SystemExit("creative_plan.json or assets/manifest.json missing: run make_assets.py first")
    W, H = plan.get("size", [1080, 1920])
    fps = int(plan.get("fps", 30))
    resolve = connect_resolve()
    jobname = plan.get("job") or job.name
    proj_name = f"Dfren - {jobname}"
    proj = rb.ensure_project(resolve, proj_name)
    if proj.GetTimelineCount() == 0:
        proj.SetSetting("timelineFrameRate", str(fps))
        proj.SetSetting("timelineResolutionWidth", str(W))
        proj.SetSetting("timelineResolutionHeight", str(H))
    pool = proj.GetMediaPool()
    tl_name = f"{jobname} {version}"
    if rb.find_timeline(proj, tl_name):
        tl_name += time.strftime(" %H%M%S")
    # ---- timeline (with native titles when the plan has any)
    if plan.get("native_titles"):
        fx = titles_fcpxml(plan, job / "work" / "titles.fcpxml")
        tl = pool.ImportTimelineFromFile(str(fx), {"timelineName": tl_name, "importSourceClips": False})
        if not tl:
            raise SystemExit("FCPXML title import failed")
    else:
        tl = pool.CreateEmptyTimeline(tl_name)
        try:
            tl.SetSetting("useCustomSettings", "1")
            tl.SetSetting("timelineResolutionWidth", str(W))
            tl.SetSetting("timelineResolutionHeight", str(H))
            tl.SetSetting("timelineFrameRate", str(fps))
        except Exception as e:  # noqa: BLE001
            print("[warn] timeline format:", e)
    proj.SetCurrentTimeline(tl)
    start0 = tl.GetStartFrame()
    tl_w = float(proj.GetSetting("timelineResolutionWidth") or W)
    tl_h = float(proj.GetSetting("timelineResolutionHeight") or H)
    cache = {}
    report = {"timeline": tl_name, "project": proj_name, "tracks": {}, "problems": []}

    # ---- media import into bins
    rb.ensure_bin(pool, "RAW")
    clip_items = {}
    for sid, path in man["voice"].items():
        clip_items[sid] = rb.get_or_import(pool, cache, path)
    for sid, p in plan["sources"].items():
        if sid not in clip_items:
            clip_items[sid] = rb.get_or_import(pool, cache, p)
    for folder, key_ in (("ASSETS/Transitions", "transitions"), ("ASSETS/Typography", "typography"), ("ASSETS/Sound", "sound")):
        rb.ensure_bin(pool, folder)
        for it in man.get(key_, []):
            rb.get_or_import(pool, cache, it["file"])
    rb.ensure_bin(pool, "")  # back to root

    # ---- V1 A-roll with native stepped zoom/pan/tilt
    segs = v1_segments(plan)
    infos, meta = [], []
    for s in segs:
        clip = s["clip"]
        mi = clip_items[clip["src"]]
        sfps = rb.clip_fps(mi, fps)
        sf = int(round(s["src_in"] * sfps))
        ef = sf + int(round((s["T1"] - s["T0"]) * sfps))
        info = {"mediaPoolItem": mi, "startFrame": sf, "endFrame": ef, "trackIndex": 1, "recordFrame": start0 + int(round(s["T0"] * fps))}
        if clip.get("mute"):
            info["mediaType"] = 1
        infos.append(info)
        meta.append(s)
    placed = pool.AppendToTimeline(infos)
    if not placed or len(placed) != len(infos) or any(p is None for p in placed):
        raise SystemExit(f"V1 placement failed ({len(placed or [])}/{len(infos)})")
    lut = (plan.get("grade") or {}).get("lut")
    lut_rel = rb.lut_install(lut) if lut else None
    if lut_rel:
        proj.RefreshLUTList()
    for it, s in zip(placed, meta):
        it.SetProperty("ZoomX", s["zoom"])
        it.SetProperty("ZoomY", s["zoom"])
        if s["pan"] or s["tilt"]:
            it.SetProperty("Pan", s["pan"])
            it.SetProperty("Tilt", s["tilt"])
        if s["cdl"]:
            c = s["cdl"]
            it.SetCDL({"NodeIndex": "1", "Slope": str(c["Slope"]), "Offset": str(c["Offset"]), "Power": str(c["Power"]), "Saturation": str(c["Saturation"])})
        if lut_rel:
            it.GetNodeGraph().SetLUT(1, lut_rel)
    report["tracks"]["V1"] = {"clips": len(placed), "native": "cuts, zoom/pan/tilt steps, CDL" + (", LUT" if lut_rel else "")}

    # ---- overlays on tracks above the titles, stacked by category
    n_title_tracks = max(tl.GetTrackCount("video"), 1)
    items = []   # (category, start, dur, mediaitem, spec)
    for c in plan.get("cutaways", []):
        mi = clip_items[c["src"]]
        items.append(("cutaway", float(c["t"]), float(c["dur"]), mi, {"blend": "normal", "in": float(c["in"]), "video_only": True, "label": "cutaway"}))
    for tr in man.get("transitions", []):
        mi = rb.get_or_import(pool, cache, tr["file"])
        cat = "glitch" if tr["kind"] == "glitch" else "transition"
        spec = {"blend": "normal", "label": tr["kind"]}
        if tr.get("opacity") is not None:
            spec["opacity"] = tr["opacity"]
        items.append((cat, float(tr["start"]), float(tr["dur"]), mi, spec))
    for ty in man.get("typography", []):
        mi = rb.get_or_import(pool, cache, ty["file"])
        items.append(("hud" if ty["kind"] == "hud" else "typography", float(ty["start"]), float(ty["dur"]), mi,
                      {"blend": "normal", "label": ty.get("label", ty["kind"])}))
    dur_plan = float(plan["duration"])
    items = [(c_, s_, min(d_, dur_plan - s_), m_, sp_) for c_, s_, d_, m_, sp_ in items if s_ < dur_plan - 0.05]   # nothing may run past the edit
    track_end, cat_base, placements = {}, {}, []
    next_base = n_title_tracks + 1
    for cat in CAT_ORDER:
        cat_items = sorted([x for x in items if x[0] == cat], key=lambda x: x[1])
        if not cat_items:
            continue
        cat_base[cat] = next_base
        used = 0
        for _, st, du, mi, spec in cat_items:
            k = 0
            while track_end.get((cat, k), -1) > st + 1e-6:
                k += 1
            track_end[(cat, k)] = st + du
            used = max(used, k + 1)
            placements.append((cat, cat_base[cat] + k, st, du, mi, spec))
        next_base += used
    for cat, tr_idx, st, du, mi, spec in placements:
        while tl.GetTrackCount("video") < tr_idx:
            tl.AddTrack("video")
    infos2, meta2 = [], []
    for cat, tr_idx, st, du, mi, spec in placements:
        mfps = rb.clip_fps(mi, fps)
        sf = int(round(spec.get("in", 0.0) * mfps))
        ef = sf + int(round(du * mfps))
        try:
            total_frames = int(float(mi.GetClipProperty("Frames")))
            ef = min(ef, total_frames) if total_frames > sf else ef
        except Exception:  # noqa: BLE001
            pass
        info = {"mediaPoolItem": mi, "startFrame": sf, "endFrame": ef, "trackIndex": tr_idx, "recordFrame": start0 + int(round(st * fps)),
                "mediaType": 1}
        infos2.append(info)
        meta2.append((cat, tr_idx, spec, mi))
    placed2 = pool.AppendToTimeline(infos2) if infos2 else []
    if len(placed2 or []) != len(infos2) or any(p is None for p in placed2 or []):
        report["problems"].append(f"overlay placement incomplete {len(placed2 or [])}/{len(infos2)}")
    for it, (cat, tr_idx, spec, mi) in zip(placed2 or [], meta2):
        if it is None:
            continue
        if spec.get("blend") != "normal" or spec.get("opacity"):
            rb.apply_item_props(resolve, it, spec, mi, tl_w, tl_h)
        try:
            it.SetClipColor(COLORS.get(spec.get("label"), COLORS.get(cat, "Blue")))
        except Exception:  # noqa: BLE001
            pass
        report["tracks"].setdefault(f"V{tr_idx}", {"category": cat, "clips": 0})["clips"] += 1

    # ---- audio: every sound event is its own clip (A1 is the A-roll voice)
    sounds = man.get("sound", [])
    a_end, a_infos = {}, []
    dur_total = float(plan["duration"])
    for s in sorted(sounds, key=lambda x: x["t"]):
        if s["t"] >= dur_total - 0.05:
            continue
        s = dict(s, dur=min(float(s["dur"]), dur_total - float(s["t"])))   # never let a sound tail stretch the timeline past the edit
        mi = rb.get_or_import(pool, cache, s["file"])
        k = 2
        while a_end.get(k, -1) > s["t"] + 1e-6:
            k += 1
        a_end[k] = s["t"] + s["dur"]
        while tl.GetTrackCount("audio") < k:
            tl.AddTrack("audio", "stereo")
        sfps = rb.clip_fps(mi, fps)   # Resolve reports audio files at the project rate (30), so frames = seconds * that
        a_infos.append({"mediaPoolItem": mi, "startFrame": 0, "endFrame": max(1, int(math.floor(s["dur"] * sfps))),
                        "trackIndex": k, "recordFrame": start0 + int(round(s["t"] * fps)), "mediaType": 2})
    placed3 = pool.AppendToTimeline(a_infos) if a_infos else []
    if a_infos and (len(placed3 or []) != len(a_infos) or any(p is None for p in placed3 or [])):
        report["problems"].append(f"sound placement incomplete {len(placed3 or [])}/{len(a_infos)}")
    report["tracks"]["audio"] = {"voice": "A1 (from V1 clips)", "sound_clips": len(placed3 or []), "tracks": tl.GetTrackCount("audio")}
    # ---- markers
    mk = 0
    for m in plan.get("markers", []):
        if tl.AddMarker(int(round(float(m["t"]) * fps)), m.get("color", "Blue"), m.get("name", ""), m.get("note", ""), 1, ""):
            mk += 1
    for tr in man.get("transitions", []):
        if tl.AddMarker(int(round(float(tr["t"]) * fps)), "Red", f"{tr['kind']}", tr.get("note", ""), 1, ""):
            mk += 1
    report["markers"] = mk
    # ---- read back
    for kind in ("video", "audio"):
        for t in range(1, tl.GetTrackCount(kind) + 1):
            its = tl.GetItemListInTrack(kind, t) or []
            report["tracks"].setdefault(f"{kind[0].upper()}{t}", {})["items"] = len(its)
    report["timeline_frames"] = (tl.GetEndFrame() - tl.GetStartFrame())
    report["expected_frames"] = int(round(float(plan["duration"]) * fps))
    (job / "output").mkdir(exist_ok=True)
    (job / "output" / "timeline_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return report


def final_name(job, plan, version):
    W, H = plan.get("size", [1080, 1920])
    ratio = "9x16" if H > W else ("16x9" if W > H else "1x1")
    client = (plan.get("client") or "dfren").lower().replace(" ", "-")
    return f"{client}_{(plan.get('job') or job.name)}_{ratio}_{W}x{H}_{version}"


def render(job, version):
    plan = jload(job / "work" / "creative_plan.json")
    resolve = connect_resolve()
    proj = resolve.GetProjectManager().GetCurrentProject()
    name = f"{plan.get('job') or job.name} {version}"
    tl = None
    for i in range(1, proj.GetTimelineCount() + 1):
        t = proj.GetTimelineByIndex(i)
        if t.GetName().startswith(name):
            tl = t
    if not tl:
        raise SystemExit(f"timeline '{name}' not found in project {proj.GetName()}")
    proj.SetCurrentTimeline(tl)
    out = job / "output"
    out.mkdir(exist_ok=True)
    fname = final_name(job, plan, version)
    W, H = plan.get("size", [1080, 1920])
    if not proj.SetCurrentRenderFormatAndCodec("mp4", "H264"):
        raise SystemExit("render format rejected")
    ok = proj.SetRenderSettings({"SelectAllFrames": True, "TargetDir": str(out), "CustomName": fname, "ExportVideo": True, "ExportAudio": True,
                                 "FormatWidth": W, "FormatHeight": H, "FrameRate": float(plan.get("fps", 30))})
    if not ok:
        raise SystemExit("SetRenderSettings failed")
    jid = proj.AddRenderJob()
    proj.StartRendering(jid)
    t0 = time.time()
    while time.time() - t0 < 1800:
        st = proj.GetRenderJobStatus(jid) or {}
        if st.get("JobStatus") in ("Complete", "Failed", "Cancelled"):
            print(json.dumps({"status": st.get("JobStatus"), "file": str(out / (fname + ".mp4")), "seconds": round(time.time() - t0)}))
            return st.get("JobStatus") == "Complete"
        time.sleep(2)
    raise SystemExit("render timed out")


def export_project(job):
    resolve = connect_resolve()
    pm = resolve.GetProjectManager()
    proj = pm.GetCurrentProject()
    out = job / "output" / (job.name + ".drp")
    ok = pm.ExportProject(proj.GetName(), str(out), True)
    print(json.dumps({"exported": bool(ok), "file": str(out)}))


def review(job, version):
    plan = jload(job / "work" / "creative_plan.json")
    mp4 = job / "output" / (final_name(job, plan, version) + ".mp4")
    if not mp4.exists():
        raise SystemExit(f"no render at {mp4}")
    py = shutil.which("python") or "python"
    eng = Path(__file__).parent
    subprocess.run([py, str(eng / "qc.py"), "check", str(mp4), "--expect-res", "x".join(str(v) for v in plan.get("size", [1080, 1920])),
                    "--out", str(job / "output" / "qc.json")], check=False)
    sheet = job / "output" / "review_sheet.jpg"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp4), "-vf", "fps=1/0.6,scale=216:-1,tile=10x3", "-frames:v", "1", "-q:v", "3", str(sheet)], check=False)
    print("review sheet:", sheet)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["build", "render", "export", "review", "all"])
    ap.add_argument("job")
    ap.add_argument("--version", default="v1")
    a = ap.parse_args()
    job = Path(a.job)
    if a.cmd in ("build", "all"):
        build(job, a.version)
    if a.cmd in ("render", "all"):
        render(job, a.version)
    if a.cmd in ("export", "all"):
        export_project(job)
    if a.cmd in ("review", "all"):
        review(job, a.version)


if __name__ == "__main__":
    main()
