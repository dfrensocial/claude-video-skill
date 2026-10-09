#!/usr/bin/env python3
"""Deterministic DaVinci Resolve Studio builder (external scripting API). Works WITHOUT any MCP server.

  *** NOT YET RUN AGAINST A LIVE RESOLVE. The logic is tested against a mock only (see --mock). ***
  *** First run in a scratch project. Use `verify` after every `build`; trust its report over this code. ***

  resolve_build.py probe
  resolve_build.py build   --plan cut_plan.json --project "Dfren - NAME" [--timeline "Cut v1"] [--bin "RAW/NAME"]
                           [--fps 30] [--width 1080] [--height 1920] [--end-offset -1]
  resolve_build.py verify  --plan cut_plan.json [--timeline "Cut v1"] [--end-offset -1]
  resolve_build.py place   --placements placements.json [--timeline "Cut v1"] [--workdir jobs/NAME/clips]
  resolve_build.py markers --file markers.json [--timeline "Cut v1"]
  resolve_build.py render  --out DIR --name NAME [--timeline "Cut v1"] [--preview] [--width W --height H]
                           [--format mp4 --codec H264] [--timeout 1800]
  Add --mock to any command to run against an in-memory fake (for logic tests only).

placements.json:  {"items":[{"kind":"broll|sfx|music|clip","path":"/abs/file","tl_start":12.4,"duration":2.2,
                             "src_start":0.0,"track":2,"gain_db":-12}]}      # track = video track (broll/clip) or audio track
markers.json:     {"markers":[{"tl_sec":3.2,"color":"Blue","name":"B-roll: tea pour","note":"","dur_sec":0}]}

Frame arithmetic: source frames = round(seconds * source_fps). Resolve's clipInfo endFrame is treated as INCLUSIVE
by default (--end-offset -1). If `verify` reports every clip long/short by one frame, flip --end-offset to 0.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import connect_resolve, probe_summary  # noqa: E402


# ----------------------------------------------------------------------------- mock (logic tests only)
class _Clip:
    def __init__(self, path):
        self.path = path
        info = probe_summary(path)
        self.fps = info.get("fps", 30.0)
        self.frames = int(info["duration"] * self.fps)

    def GetClipProperty(self, k=None):
        d = {"File Path": self.path, "FPS": str(self.fps), "Frames": str(self.frames), "Start": "0"}
        return d.get(k) if k else d

    def GetName(self):
        return Path(self.path).name


class _Item:
    def __init__(self, clip, sf, ef, rec, track, mtype):
        self.clip, self.sf, self.ef, self.rec, self.track, self.mtype = clip, sf, ef, rec, track, mtype

    def GetStart(self):
        return self.rec

    def GetDuration(self):
        return self.ef - self.sf + 1

    def GetEnd(self):
        return self.rec + self.GetDuration()

    def GetSourceStartFrame(self):
        return self.sf

    def GetSourceEndFrame(self):
        return self.ef

    def GetName(self):
        return self.clip.GetName()


class _Timeline:
    def __init__(self, name, fps):
        self.name, self.fps = name, fps
        self.tracks = {"video": {1: []}, "audio": {1: []}}
        self.markers = []

    def GetName(self):
        return self.name

    def GetStartFrame(self):
        return 86400

    def GetEndFrame(self):
        ends = [i.GetEnd() for t in self.tracks["video"].values() for i in t]
        return max(ends) if ends else 86400

    def GetTrackCount(self, kind):
        return len(self.tracks[kind])

    def AddTrack(self, kind, sub=None):
        self.tracks[kind][len(self.tracks[kind]) + 1] = []
        return True

    def GetItemListInTrack(self, kind, idx):
        return self.tracks[kind].get(idx, [])

    def SetSetting(self, k, v):
        return True

    def AddMarker(self, frame, color, name, note, dur, custom=""):
        self.markers.append((frame, color, name, note, dur))
        return True


class _Folder:
    def __init__(self, name):
        self.name, self.clips, self.subs = name, [], []

    def GetName(self):
        return self.name

    def GetClipList(self):
        return self.clips

    def GetSubFolderList(self):
        return self.subs


class _Pool:
    def __init__(self, project):
        self.project, self.root = project, _Folder("Master")
        self.cur = self.root

    def GetRootFolder(self):
        return self.root

    def GetCurrentFolder(self):
        return self.cur

    def AddSubFolder(self, parent, name):
        f = _Folder(name)
        parent.subs.append(f)
        return f

    def SetCurrentFolder(self, f):
        self.cur = f
        return True

    def ImportMedia(self, paths):
        out = [_Clip(p) for p in paths]
        self.cur.clips.extend(out)
        return out

    def CreateEmptyTimeline(self, name):
        tl = _Timeline(name, self.project.fps)
        self.project.timelines.append(tl)
        self.project.current = tl
        return tl

    def AppendToTimeline(self, infos):
        out = []
        for ci in infos:
            tl = self.project.current
            mtype = ci.get("mediaType", 0)
            kind = "audio" if mtype == 2 else "video"
            tr = ci.get("trackIndex", 1)
            tl.tracks[kind].setdefault(tr, [])
            if "recordFrame" in ci:
                rec = ci["recordFrame"]
            else:
                lst = tl.tracks[kind][tr]
                rec = lst[-1].GetEnd() if lst else tl.GetStartFrame()
            it = _Item(ci["mediaPoolItem"], ci["startFrame"], ci["endFrame"], rec, tr, mtype)
            tl.tracks[kind][tr].append(it)
            out.append(it)
        return out


class _Project:
    def __init__(self, name):
        self.name, self.timelines, self.current, self.fps, self.settings = name, [], None, 30, {}
        self.pool = _Pool(self)

    def GetName(self):
        return self.name

    def GetMediaPool(self):
        return self.pool

    def SetSetting(self, k, v):
        self.settings[k] = v
        if k == "timelineFrameRate":
            self.fps = float(v)
        return True

    def GetSetting(self, k):
        return self.settings.get(k, str(self.fps) if k == "timelineFrameRate" else "")

    def GetTimelineCount(self):
        return len(self.timelines)

    def GetTimelineByIndex(self, i):
        return self.timelines[i - 1]

    def GetCurrentTimeline(self):
        return self.current

    def SetCurrentTimeline(self, tl):
        self.current = tl
        return True


class _PM:
    def __init__(self):
        self.projects = {}
        self.cur = None

    def GetProjectListInCurrentFolder(self):
        return list(self.projects)

    def CreateProject(self, name):
        self.projects[name] = _Project(name)
        self.cur = self.projects[name]
        return self.cur

    def LoadProject(self, name):
        self.cur = self.projects[name]
        return self.cur

    def GetCurrentProject(self):
        return self.cur


class MockResolve:
    def __init__(self):
        self.pm = _PM()

    def GetProjectManager(self):
        return self.pm

    def GetProductName(self):
        return "DaVinci Resolve Studio (MOCK)"

    def GetVersionString(self):
        return "0.0.mock"


_MOCK = None


def get_resolve(mock):
    global _MOCK
    if mock:
        _MOCK = _MOCK or MockResolve()
        return _MOCK
    return connect_resolve()


# ----------------------------------------------------------------------------- helpers
def ensure_project(resolve, name):
    pm = resolve.GetProjectManager()
    if name in (pm.GetProjectListInCurrentFolder() or []):
        proj = pm.LoadProject(name)
    else:
        proj = pm.CreateProject(name)
    if not proj:
        raise SystemExit(f"could not open or create project '{name}'")
    return proj


def find_timeline(project, name):
    for i in range(1, (project.GetTimelineCount() or 0) + 1):
        tl = project.GetTimelineByIndex(i)
        if tl.GetName() == name:
            return tl
    return None


def current_or_named(project, name):
    if name:
        tl = find_timeline(project, name)
        if not tl:
            raise SystemExit(f"timeline '{name}' not found")
        project.SetCurrentTimeline(tl)
        return tl
    tl = project.GetCurrentTimeline()
    if not tl:
        raise SystemExit("no current timeline")
    return tl


def ensure_bin(pool, path):
    cur = pool.GetRootFolder()
    for part in [p for p in (path or "").split("/") if p]:
        nxt = next((f for f in cur.GetSubFolderList() if f.GetName() == part), None)
        cur = nxt or pool.AddSubFolder(cur, part)
    pool.SetCurrentFolder(cur)
    return cur


def all_clips(folder):
    out = list(folder.GetClipList() or [])
    for s in folder.GetSubFolderList() or []:
        out += all_clips(s)
    return out


def get_or_import(pool, cache, path):
    path = str(Path(path).resolve())
    if path in cache:
        return cache[path]
    for c in all_clips(pool.GetRootFolder()):
        if str(c.GetClipProperty("File Path")) == path:
            cache[path] = c
            return c
    items = pool.ImportMedia([path])
    if not items:
        raise SystemExit(f"Resolve could not import {path}")
    cache[path] = items[0]
    return items[0]


def clip_fps(item, fallback=30.0):
    try:
        return float(item.GetClipProperty("FPS"))
    except (TypeError, ValueError):
        return fallback


# ----------------------------------------------------------------------------- commands
def cmd_probe(a):
    r = get_resolve(a.mock)
    out = {"product": r.GetProductName(), "version": r.GetVersionString()}
    proj = r.GetProjectManager().GetCurrentProject()
    out["project"] = proj.GetName() if proj else None
    tl = proj.GetCurrentTimeline() if proj else None
    out["timeline"] = tl.GetName() if tl else None
    print(json.dumps(out, indent=2))


def cmd_build(a):
    plan = json.load(open(a.plan, encoding="utf-8"))
    r = get_resolve(a.mock)
    proj = ensure_project(r, a.project)
    if proj.GetTimelineCount() == 0:
        proj.SetSetting("timelineFrameRate", str(a.fps))
        proj.SetSetting("timelineResolutionWidth", str(a.width))
        proj.SetSetting("timelineResolutionHeight", str(a.height))
    pool = proj.GetMediaPool()
    if a.bin:
        ensure_bin(pool, a.bin)
    cache = {}
    for f in plan["files"]:
        get_or_import(pool, cache, f)
    name = a.timeline or "Cut v1"
    if find_timeline(proj, name):
        name = f"{name} {time.strftime('%H%M%S')}"
        print(f"timeline name existed; using '{name}'")
    tl = pool.CreateEmptyTimeline(name)
    if not tl:
        raise SystemExit("CreateEmptyTimeline failed")
    proj.SetCurrentTimeline(tl)
    try:  # custom per-timeline format (needed when the project already has timelines at another format)
        tl.SetSetting("useCustomSettings", "1")
        tl.SetSetting("timelineResolutionWidth", str(a.width))
        tl.SetSetting("timelineResolutionHeight", str(a.height))
        tl.SetSetting("timelineFrameRate", str(a.fps))
    except Exception as e:  # noqa: BLE001
        print(f"[warn] could not set custom timeline format: {e}")
    infos = []
    for k in plan["keep"]:
        it = get_or_import(pool, cache, k["file"])
        fps = clip_fps(it, a.fps)
        sf = int(round(k["start"] * fps))
        ef = max(sf, int(round(k["end"] * fps)) + a.end_offset)
        infos.append({"mediaPoolItem": it, "startFrame": sf, "endFrame": ef})
    placed = pool.AppendToTimeline(infos)
    n = len(placed) if placed else 0
    print(f"timeline '{name}': appended {n}/{len(infos)} ranges")
    if n != len(infos):
        raise SystemExit("not all ranges were appended - run verify, check the Resolve console, and retry")
    print("next: resolve_build.py verify --plan", a.plan, "--timeline", repr(name))


def cmd_verify(a):
    plan = json.load(open(a.plan, encoding="utf-8"))
    r = get_resolve(a.mock)
    proj = r.GetProjectManager().GetCurrentProject()
    tl = current_or_named(proj, a.timeline)
    tfps = float(tl.GetSetting("timelineFrameRate")) if hasattr(tl, "GetSetting") and tl.GetSetting("timelineFrameRate") else float(proj.GetSetting("timelineFrameRate") or 30)
    items = tl.GetItemListInTrack("video", 1) or []
    problems, biases = [], []
    if len(items) != len(plan["keep"]):
        problems.append(f"clip count {len(items)} != planned {len(plan['keep'])}")
    prev_end = None
    for i, (it, k) in enumerate(zip(items, plan["keep"])):
        exp = int(round((k["end"] - k["start"]) * tfps))
        got = it.GetDuration()
        biases.append(got - exp)
        if abs(got - exp) > 1:
            problems.append(f"clip {i + 1}: duration {got}f, expected ~{exp}f")
        if prev_end is not None and it.GetStart() != prev_end:
            problems.append(f"clip {i + 1}: gap/overlap of {it.GetStart() - prev_end} frames")
        prev_end = it.GetEnd()
    if biases and all(b == biases[0] for b in biases) and biases[0] != 0:
        problems.append(f"every clip is {biases[0]:+d} frame(s) vs plan: flip --end-offset (currently {a.end_offset})")
    total_exp = plan["timeline_duration"]
    total_got = sum(i.GetDuration() for i in items) / tfps if items else 0
    if abs(total_got - total_exp) > 0.5:
        problems.append(f"total {total_got:.2f}s vs planned {total_exp:.2f}s")
    print(json.dumps({"ok": not problems, "clips": len(items), "total_s": round(total_got, 2), "problems": problems}, indent=2))
    sys.exit(0 if not problems else 1)


def cmd_place(a):
    data = json.load(open(a.placements, encoding="utf-8"))
    r = get_resolve(a.mock)
    proj = r.GetProjectManager().GetCurrentProject()
    tl = current_or_named(proj, a.timeline)
    pool = proj.GetMediaPool()
    cache = {}
    tfps = float(proj.GetSetting("timelineFrameRate") or 30)
    start0 = tl.GetStartFrame()
    infos, report = [], []
    for k, it in enumerate(data["items"]):
        path = it["path"]
        if it.get("gain_db") and not a.mock:
            wd = Path(a.workdir or ".") / "gained"
            wd.mkdir(parents=True, exist_ok=True)
            out = wd / f"{Path(path).stem}_{it['gain_db']:+.0f}dB{Path(path).suffix}"
            if not out.exists():
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", path, "-af", f"volume={it['gain_db']}dB", str(out)], check=True)
            path = str(out)
        mi = get_or_import(pool, cache, path)
        fps = clip_fps(mi, tfps)
        sf = int(round(it.get("src_start", 0) * fps))
        ef = max(sf, sf + int(round(it["duration"] * fps)) + a.end_offset)
        is_audio = it["kind"] in ("sfx", "music")
        track = int(it.get("track", 1 if is_audio else 2))
        kind = "audio" if is_audio else "video"
        while tl.GetTrackCount(kind) < track:
            tl.AddTrack(kind, "stereo") if is_audio else tl.AddTrack(kind)
        info = {"mediaPoolItem": mi, "startFrame": sf, "endFrame": ef, "trackIndex": track,
                "recordFrame": start0 + int(round(it["tl_start"] * tfps)), "mediaType": 2 if is_audio else 1}
        infos.append(info)
        report.append(f"{it['kind']} {Path(path).name} @ {it['tl_start']}s on {kind[0].upper()}{track}")
    placed = pool.AppendToTimeline(infos)
    print(f"placed {len(placed or [])}/{len(infos)}")
    for line in report:
        print(" -", line)
    if len(placed or []) != len(infos):
        raise SystemExit("some items were not placed - re-run verify / inspect the timeline")


def cmd_markers(a):
    data = json.load(open(a.file, encoding="utf-8"))
    r = get_resolve(a.mock)
    proj = r.GetProjectManager().GetCurrentProject()
    tl = current_or_named(proj, a.timeline)
    tfps = float(proj.GetSetting("timelineFrameRate") or 30)
    # Resolve timeline markers use frames relative to the timeline start (frameId), not absolute TC frames
    ok = 0
    for m in data["markers"]:
        frame = int(round(m["tl_sec"] * tfps))
        if tl.AddMarker(frame, m.get("color", "Blue"), m.get("name", ""), m.get("note", ""),
                        max(1, int(round(m.get("dur_sec", 0) * tfps))), ""):
            ok += 1
    print(f"markers added {ok}/{len(data['markers'])}")


def cmd_render(a):
    r = get_resolve(a.mock)
    proj = r.GetProjectManager().GetCurrentProject()
    current_or_named(proj, a.timeline)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.mock:
        print("[mock] render skipped")
        return
    if not proj.SetCurrentRenderFormatAndCodec(a.format, a.codec):
        raise SystemExit(f"format/codec rejected: {a.format}/{a.codec}. Check project.GetRenderFormats()/GetRenderCodecs().")
    settings = {"SelectAllFrames": True, "TargetDir": str(out), "CustomName": a.name, "ExportVideo": True, "ExportAudio": True}
    if a.width and a.height:
        settings.update(FormatWidth=a.width, FormatHeight=a.height)
    if a.preview:
        settings["VideoQuality"] = 0
    if not proj.SetRenderSettings(settings):
        raise SystemExit("SetRenderSettings returned False")
    job = proj.AddRenderJob()
    if not job:
        raise SystemExit("AddRenderJob failed")
    proj.StartRendering(job)
    t0 = time.time()
    while time.time() - t0 < a.timeout:
        st = proj.GetRenderJobStatus(job) or {}
        s = st.get("JobStatus")
        if s in ("Complete", "Failed", "Cancelled"):
            print(json.dumps({"job": job, "status": s, "dir": str(out), "name": a.name}))
            sys.exit(0 if s == "Complete" else 1)
        time.sleep(2)
    raise SystemExit("render timed out (still running in Resolve's queue)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mock", action="store_true", help="use an in-memory fake Resolve (logic tests only)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe")
    p = sub.add_parser("build")
    p.add_argument("--plan", required=True)
    p.add_argument("--project", required=True)
    p.add_argument("--timeline")
    p.add_argument("--bin")
    p.add_argument("--fps", type=float, default=30)
    p.add_argument("--width", type=int, default=1080)
    p.add_argument("--height", type=int, default=1920)
    p.add_argument("--end-offset", type=int, default=-1)
    p = sub.add_parser("verify")
    p.add_argument("--plan", required=True)
    p.add_argument("--timeline")
    p.add_argument("--end-offset", type=int, default=-1)
    p = sub.add_parser("place")
    p.add_argument("--placements", required=True)
    p.add_argument("--timeline")
    p.add_argument("--workdir")
    p.add_argument("--end-offset", type=int, default=-1)
    p = sub.add_parser("markers")
    p.add_argument("--file", required=True)
    p.add_argument("--timeline")
    p = sub.add_parser("render")
    p.add_argument("--out", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--timeline")
    p.add_argument("--preview", action="store_true")
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--format", default="mp4")
    p.add_argument("--codec", default="H264")
    p.add_argument("--timeout", type=int, default=1800)
    a, rest = ap.parse_known_args()
    # allow --mock after the subcommand too
    if "--mock" in rest:
        a.mock = True
    globals()["cmd_" + a.cmd](a)


if __name__ == "__main__":
    main()
