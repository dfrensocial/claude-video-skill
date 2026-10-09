#!/usr/bin/env python3
"""Shared helpers for the resolve-editor scripts.

Run `python common.py where` to print the detected workspace and merged config.
No third-party dependencies required (Pillow / numpy are used only when present).
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".mxf", ".mts", ".m2ts", ".3gp"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".heic"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".aif", ".aiff", ".opus"}


# ---------------------------------------------------------------- json / config
def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:  # -sig: tolerate the BOM Windows PowerShell adds on `>`
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def find_workspace(start=None):
    """Workspace = folder containing workspace.json. Search env, cwd upwards, then skill location."""
    env = os.environ.get("RESOLVE_EDITOR_WORKSPACE")
    if env and (Path(env) / "workspace.json").exists():
        return Path(env).resolve()
    p = Path(start or Path.cwd()).resolve()
    for d in [p, *p.parents]:
        if (d / "workspace.json").exists():
            return d
    # installed as <workspace>/.claude/skills/resolve-editor
    parents = SKILL_DIR.parents
    if len(parents) > 2 and (parents[2] / "workspace.json").exists():
        return parents[2].resolve()
    return None


def load_config():
    cfg = load_json(SKILL_DIR / "config" / "defaults.json", {})
    ws = find_workspace()
    if ws:
        cfg = deep_merge(cfg, load_json(ws / "workspace.json", {}))
        cfg["_workspace"] = str(ws)
    return cfg


def enable_cuda_dlls():
    """Windows: make pip-installed CUDA runtime DLLs (nvidia-cublas-cu12, nvidia-cudnn-cu12) loadable by
    ctranslate2/faster-whisper. No-op elsewhere or if the packages are absent."""
    import os
    import site
    if os.name != "nt":
        return
    for base in list(site.getsitepackages()) + [site.getusersitepackages()]:
        nv = Path(base) / "nvidia"
        if nv.is_dir():
            for b in nv.glob("*/bin"):
                try:
                    os.add_dll_directory(str(b))
                except (OSError, AttributeError):
                    pass
                os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")


def cuda_available():
    enable_cuda_dlls()
    try:
        import ctranslate2  # type: ignore
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- processes
def have(binary):
    return shutil.which(binary) is not None


def run(cmd, check=True, timeout=None):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"command failed ({r.returncode}): {' '.join(map(str, cmd))}\n{r.stderr[-1500:]}")
    return r


def ffprobe(path):
    r = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    return json.loads(r.stdout)


def probe_summary(path):
    """Compact facts about a media file."""
    d = ffprobe(path)
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    dur = float(d.get("format", {}).get("duration") or (v or a or {}).get("duration") or 0)
    out = {"path": str(path), "duration": round(dur, 3), "has_video": bool(v), "has_audio": bool(a)}
    if v:
        num, _, den = (v.get("avg_frame_rate") or v.get("r_frame_rate") or "0/1").partition("/")
        fps = (float(num) / float(den or 1)) if float(den or 1) else 0.0
        w, h = int(v.get("width", 0)), int(v.get("height", 0))
        rot = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(sd["rotation"])
        rot = rot or int((v.get("tags") or {}).get("rotate", 0) or 0)
        if abs(rot) in (90, 270):
            w, h = h, w
        out.update(width=w, height=h, fps=round(fps, 3), vcodec=v.get("codec_name"), pix_fmt=v.get("pix_fmt"),
                   orientation="vertical" if h > w * 1.05 else "horizontal" if w > h * 1.05 else "square",
                   timecode=(v.get("tags") or {}).get("timecode") or (d.get("format", {}).get("tags") or {}).get("timecode"))
    if a:
        out.update(acodec=a.get("codec_name"), sample_rate=int(a.get("sample_rate", 0) or 0),
                   channels=a.get("channels"))
    return out


def seconds_to_tc(sec, fps, start_hours=0):
    fps_i = int(round(fps))
    total = int(round(sec * fps))
    f = total % fps_i
    s_total = total // fps_i
    return f"{(s_total // 3600) + start_hours:02d}:{(s_total // 60) % 60:02d}:{s_total % 60:02d}:{f:02d}"


# ---------------------------------------------------------------- text
def norm_token(tok):
    """Lowercase + strip punctuation/symbols but keep combining marks (matters for Tamil)."""
    t = unicodedata.normalize("NFC", tok.lower())
    return "".join(c for c in t if unicodedata.category(c)[0] not in "PSZC")


# ---------------------------------------------------------------- resolve connection
def resolve_env():
    sysname = platform.system()
    if sysname == "Darwin":
        api = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
        lib = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
    elif sysname == "Windows":
        pd = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        api = os.path.join(pd, "Blackmagic Design", "DaVinci Resolve", "Support", "Developer", "Scripting")
        lib = r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
    else:
        api = "/opt/resolve/Developer/Scripting"
        lib = "/opt/resolve/libs/Fusion/fusionscript.so"
    api = os.environ.get("RESOLVE_SCRIPT_API", api)
    lib = os.environ.get("RESOLVE_SCRIPT_LIB", lib)
    return api, lib


def find_resolve_python():
    """Another installed Python that can load Resolve's fusionscript (Windows `py` launcher), as an argv prefix, or None.

    Measured on this PC (Resolve Studio 21.0.3.7): the Microsoft-Store Python 3.10 fails with 'SystemError: initialization of
    fusionscript failed without raising an exception' while Python 3.13 connects. Resolve's module is picky about the
    interpreter, so Resolve-facing scripts fall back to one that works."""
    api, lib = resolve_env()
    code = ("import os,sys;os.environ['RESOLVE_SCRIPT_API']=r'%s';os.environ['RESOLVE_SCRIPT_LIB']=r'%s';"
            "sys.path.append(os.path.join(r'%s','Modules'));import DaVinciResolveScript;print('OK')" % (api, lib, api))
    cands = [[sys.executable]] + [["py", f"-3.{v}"] for v in (13, 12, 11, 10)] if os.name == "nt" else [[sys.executable]]
    for c in cands:
        if c == [sys.executable] and getattr(sys, "_hf_resolve_failed", False):
            continue
        try:
            r = subprocess.run(c + ["-c", code], capture_output=True, text=True, timeout=60)
            if "OK" in r.stdout:
                return c
        except Exception:  # noqa: BLE001
            continue
    return None


def connect_resolve():
    """Return the Resolve scripting object, or raise RuntimeError with a fix hint.

    If the current interpreter cannot load fusionscript (SystemError) and another installed Python can, the CURRENT SCRIPT is
    re-run with that Python (once, guarded by HF_RESOLVE_REEXEC) and this process exits with its exit code."""
    api, lib = resolve_env()
    os.environ["RESOLVE_SCRIPT_API"] = api
    os.environ["RESOLVE_SCRIPT_LIB"] = lib
    mod = os.path.join(api, "Modules")
    if mod not in sys.path:
        sys.path.append(mod)
    try:
        import DaVinciResolveScript as dvr  # type: ignore
    except SystemError as e:
        sys._hf_resolve_failed = True
        if not os.environ.get("HF_RESOLVE_REEXEC"):
            alt = find_resolve_python()
            if alt and alt != [sys.executable]:
                env = dict(os.environ, HF_RESOLVE_REEXEC="1")
                sys.exit(subprocess.run(alt + [os.path.abspath(sys.argv[0])] + sys.argv[1:], env=env).returncode)
        raise RuntimeError(f"fusionscript would not initialise under this Python ({sys.version.split()[0]}): {e}. "
                           "Install another Python (3.11-3.13, python.org) and retry; the `py` launcher is tried automatically.")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Cannot import DaVinciResolveScript from {mod}: {e}. "
                           "Is DaVinci Resolve Studio installed? Check RESOLVE_SCRIPT_API.")
    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        raise RuntimeError("Resolve did not answer. Open Resolve **Studio**, then Preferences > System > General > "
                           "External scripting using = Local. (The free edition blocks external scripting.)")
    return resolve


# ---------------------------------------------------------------- contact sheets
def contact_sheet(images, out_path, cols=4, thumb_w=270, label=True):
    """Tile images (paths) into one JPEG. Numbers each tile (row-major, starting at 1) when Pillow exists."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        Image = None
    if Image is None:
        tmp = out_path.parent / "_tile_tmp"
        tmp.mkdir(exist_ok=True)
        for i, p in enumerate(images, 1):
            shutil.copy(p, tmp / f"{i:04d}.jpg")
        rows = (len(images) + cols - 1) // cols
        run(["ffmpeg", "-y", "-v", "error", "-framerate", "1", "-i", str(tmp / "%04d.jpg"),
             "-vf", f"scale={thumb_w}:-2,tile={cols}x{rows}", "-frames:v", "1", str(out_path)])
        shutil.rmtree(tmp, ignore_errors=True)
        return str(out_path)
    thumbs = []
    for p in images:
        im = Image.open(p).convert("RGB")
        h = int(im.height * thumb_w / im.width)
        thumbs.append(im.resize((thumb_w, h)))
    th = max(t.height for t in thumbs)
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * thumb_w, rows * th), (20, 20, 20))
    for i, t in enumerate(thumbs):
        x, y = (i % cols) * thumb_w, (i // cols) * th
        sheet.paste(t, (x, y))
        if label:
            d = ImageDraw.Draw(sheet)
            d.rectangle([x, y, x + 34, y + 18], fill=(0, 0, 0))
            d.text((x + 4, y + 3), str(i + 1), fill=(255, 255, 0))
    sheet.save(out_path, quality=85)
    return str(out_path)


def extract_frame(video, t, out_jpg, width=480):
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(t, 0):.3f}", "-i", str(video),
         "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", str(out_jpg)])
    return str(out_jpg)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "where":
        ws = find_workspace()
        print(json.dumps({"workspace": str(ws) if ws else None, "skill_dir": str(SKILL_DIR)}, indent=2))
    else:
        print("usage: common.py where")
