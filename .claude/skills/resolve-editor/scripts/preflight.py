#!/usr/bin/env python3
"""Environment check. Run at the start of every session.

  preflight.py [--json] [--no-resolve]

Prints PASS / WARN / FAIL per check with a concrete fix. Exit code 1 if any FAIL.
Fallback behaviour when something is missing is described in SKILL.md ("When tools are missing").
"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import SKILL_DIR, connect_resolve, find_workspace, have, load_config, resolve_env  # noqa: E402

RESULTS = []


def add(name, status, detail, fix=""):
    RESULTS.append({"check": name, "status": status, "detail": detail, "fix": fix})


def cmd_out(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        return (r.stdout + r.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return f"ERR {e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-resolve", action="store_true", help="skip the live Resolve connection test")
    a = ap.parse_args()

    # python
    v = sys.version_info
    add("python", "PASS" if v >= (3, 9) else "FAIL", f"{v.major}.{v.minor}.{v.micro}", "Install Python 3.10+")

    # ffmpeg / ffprobe
    for b in ("ffmpeg", "ffprobe"):
        if have(b):
            ver = cmd_out([b, "-version"]).splitlines()[0]
            add(b, "PASS", ver)
        else:
            add(b, "FAIL", "not on PATH",
                "Mac: brew install ffmpeg | Windows: winget install Gyan.FFmpeg | then reopen the terminal")

    # node (HyperFrames / brag need 22+)
    if have("node"):
        out = cmd_out(["node", "--version"])
        m = re.match(r"v(\d+)", out)
        ok = bool(m and int(m.group(1)) >= 22)
        add("node", "PASS" if ok else "WARN", out, "" if ok else "HyperFrames and /brag need Node 22+ (nodejs.org)")
    else:
        add("node", "WARN", "not found", "Install Node 22+ to use generated motion clips (HyperFrames)")

    # numpy / PIL (optional)
    for mod, why in (("numpy", "reference motion analysis + colour matching"), ("PIL", "numbered contact sheets")):
        try:
            __import__(mod)
            add(mod, "PASS", "installed")
        except ImportError:
            add(mod, "WARN", "missing", f"pip install {'pillow' if mod == 'PIL' else mod}  ({why})")

    # ASR
    asr = None
    for mod in ("faster_whisper", "whisper"):
        try:
            __import__(mod)
            asr = mod
            break
        except ImportError:
            pass
    add("transcription", "PASS" if asr else "FAIL", asr or "no ASR engine",
        "" if asr else "pip install faster-whisper   (or import a transcript with analyze.py srt2json)")

    # workspace
    ws = find_workspace()
    cfg = load_config()
    if ws:
        add("workspace", "PASS", str(ws))
        for key in ("broll_paths", "sfx_paths", "music_paths"):
            paths = (cfg.get("library") or {}).get(key) or []
            if not paths:
                add(f"library.{key}", "WARN", "not set", f"Add your folder path(s) to workspace.json > library > {key}")
            else:
                for p in paths:
                    add(f"library.{key}", "PASS" if Path(p).expanduser().exists() else "FAIL", p,
                        "Path not found - fix it in workspace.json")
    else:
        add("workspace", "FAIL", "workspace.json not found",
            f"python {SKILL_DIR}/scripts/setup_workspace.py --root <your workspace folder>")

    # Resolve install + scripting
    api, lib = resolve_env()
    api_ok, lib_ok = Path(api).exists(), Path(lib).exists()
    add("resolve scripting files", "PASS" if api_ok and lib_ok else "FAIL",
        f"api={'ok' if api_ok else 'missing'} lib={'ok' if lib_ok else 'missing'} ({platform.system()})",
        "" if api_ok and lib_ok else "Install DaVinci Resolve Studio, or set RESOLVE_SCRIPT_API / RESOLVE_SCRIPT_LIB")
    if not a.no_resolve and api_ok and lib_ok:
        os.environ["HF_RESOLVE_REEXEC"] = "1"  # preflight reports; it must not re-run itself under another Python
        info, via, err = None, "", None
        try:
            r = connect_resolve()
            pj = r.GetProjectManager().GetCurrentProject()
            info = {"product": r.GetProductName(), "version": r.GetVersionString(), "project": pj.GetName() if pj else None}
        except RuntimeError as e0:
            err = e0
            if "would not initialise" in str(e0):
                from common import find_resolve_python
                alt = find_resolve_python()
                if alt:
                    try:
                        p = subprocess.run(alt + [str(Path(__file__).parent / "resolve_build.py"), "probe"], capture_output=True,
                                           text=True, timeout=90)
                        info = json.loads(p.stdout)
                        via = (f" via `{' '.join(alt)}` (this Python {sys.version.split()[0]} cannot load fusionscript; "
                               "Resolve scripts re-run themselves with it automatically)")
                    except Exception as e1:  # noqa: BLE001
                        err = e1
        except Exception as e:  # noqa: BLE001
            err = e
        if info:
            studio = "studio" in (info.get("product") or "").lower()
            add("resolve connection", "PASS" if studio else "FAIL", f"{info.get('product')} {info.get('version')}{via}",
                "" if studio else "Free edition cannot be scripted externally (Resolve 21.1+). Use Studio.")
            add("resolve project", "PASS" if info.get("project") else "WARN", str(info.get("project") or "no project open"),
                "" if info.get("project") else "Open or create a project (never rely on the untitled default project)")
        else:
            add("resolve connection", "FAIL", str(err).splitlines()[0][:200],
                "Open Resolve Studio; Preferences > System > General > External scripting using = Local")

    # MCP registration (best effort)
    if have("claude"):
        out = cmd_out(["claude", "mcp", "list"])
        has = "resolve" in out.lower()
        add("resolve MCP registered", "PASS" if has else "WARN", "found" if has else "not found",
            "" if has else "npx davinci-resolve-mcp setup  (Studio running, External scripting = Local) "
                           "or in Resolve 21.1+: File > Setup AI Assistants. resolve_build.py works without MCP.")
    else:
        add("claude CLI", "WARN", "not on PATH (cannot check MCP registration)")

    # hyperframes (shallow; deep check = npx hyperframes doctor)
    add("hyperframes", "WARN", "not checked here",
        "Run `npx hyperframes doctor`; plugin: /plugin marketplace add heygen-com/hyperframes")

    if a.json:
        print(json.dumps(RESULTS, indent=2))
    else:
        icon = {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]"}
        for r in RESULTS:
            line = f"{icon[r['status']]} {r['check']}: {r['detail']}"
            if r["status"] != "PASS" and r["fix"]:
                line += f"\n         fix: {r['fix']}"
            print(line)
        fails = sum(r["status"] == "FAIL" for r in RESULTS)
        warns = sum(r["status"] == "WARN" for r in RESULTS)
        print(f"\n{fails} fail, {warns} warn")
    sys.exit(1 if any(r["status"] == "FAIL" for r in RESULTS) else 0)


if __name__ == "__main__":
    main()
