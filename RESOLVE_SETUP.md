# DaVinci Resolve: what I need, how I connect, how we work

Status on this PC (checked 2026-10-09): Resolve **21.0.3.7** is installed and was running; the scripting files exist (`C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting`, README dated 15 Jul 2026); the LUT folder exists. `preflight.py` still **fails to connect** ("initialization of fusionscript failed"), which means one of the two things in section 1 is not true yet. I cannot see your screen, so I cannot tell which.

## 1. What I need from you (3 checks, 2 minutes)
1. **Edition = Studio.** Resolve menu > Help > About. Scripting is **Studio only**; the free edition cannot be controlled from outside. If it says only "DaVinci Resolve" (no "Studio"), tell me: I will then prepare everything as files (EDL/XML + ffmpeg previews) and you finish inside Resolve.
2. **Preferences > System > General > "External scripting using" = Local**, click Save, **restart Resolve**.
3. Keep Resolve **open with a project loaded** (I will use a scratch project named `Dfren Scratch` for tests, never your client projects).
Then say "resolve ready" and I run `preflight.py` again.

Optional, makes the work better:
- Install the brand/reference **fonts** system-wide (Text+ can only use installed fonts). You already have a large personal font library in `%LOCALAPPDATA%\Microsoft\Windows\Fonts`; tell me which fonts the references use and I will match and test them.
- Copy the 21 `.cube` LUTs from `assets\asserss\LUTs-...\LUTs` into `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\LUT` (I will ask before copying), then I call `Project.RefreshLUTList()`.
- Magic Mask (text behind the subject) and Resolve's AI tools want a capable GPU; your RTX 5070 (12 GB) should do. Extras (e.g. extra transcription languages) install through Resolve's Extras Download Manager.
- Do **not** run any `.exe` from `assets\...\pre set davincie effect`; `.drfx` macros (MagicZoom, Letterbox, Ultimate Seamless) install by double-clicking in Resolve, only if you want them.

## 2. How I connect (two routes; I use A first)
**Route A, Python scripting (recommended, already written):** `resolve_build.py` imports Resolve's own `DaVinciResolveScript` module (`RESOLVE_SCRIPT_API` / `RESOLVE_SCRIPT_LIB` / `fusionscript.dll`, per the README) and talks to the running Resolve on this PC. No internet, no extra installs.
**Route B, Resolve MCP (optional):** `npx davinci-resolve-mcp setup` registers a community MCP server so I can call Resolve actions as tools. Needs your OK (it installs a package). Your version (21.0.3.7) predates the native MCP of 21.1 (File > Setup AI Assistants); I will not run both.
If neither connects, I fall back to files: `cut.edl` + an ffmpeg preview, so no work is lost.

## 3. How we work together (division of labour)
| Step | I do it with | Resolve call (README) | You |
|---|---|---|---|
| Ingest | `resolve_build.py build` | `MediaPool.ImportMedia`, bins per job | drop footage in `footage/` |
| Cut | `cut_plan.py` -> timeline | `AppendToTimeline` with integer frames | review `cut_plan.md` flags |
| Titles/captions | `captions.py` -> Text+ | `InsertFusionTitleIntoTimeline`, Fusion `StyledText` | pick fonts/colours from sheets |
| Colour | `grade.py` -> CDL / LUT | `SetCDL` (strings, node 1-based), `SetLUT` after `RefreshLUTList` | judge the before/after sheet |
| B-roll/overlays/transitions | `index_library.py`, `style.py plan` | clips on V2-V4, `SetProperty("CompositeMode"/"Opacity"/"ZoomX"...)` | approve candidates |
| Mask / subject | Magic Mask | `CreateMagicMask("F"/"B"/"BI")` (untested selection) | may need to click once |
| Render | `resolve_build.py render` | `SetRenderSettings`, `AddRenderJob`, `StartRendering` | watch the export |
The timeline always stays editable in Resolve; every version is a duplicate timeline (`Cut v1`, `Cut v2`), originals are never touched.

## 4. First-run test plan (we do this last, as you said)
1. `preflight.py` all green.
2. Create `Dfren Scratch`, import one short clip from `footage/`, build a 10-second timeline, run `resolve_build.py verify`: it tells us whether `endFrame` is inclusive (sources disagree; we measure it) and records the answer in `CLAUDE.md`.
3. Add one Text+ caption, one `SetCDL`, one LUT, one overlay with Screen blend, render 5 s, run `qc.py check`.
4. Try `CreateMagicMask("F")` on the scratch clip; record what happens.
5. Only then a real job.
Things I cannot verify without you: how the result looks (I judge from frame sheets, not motion), audio quality (I cannot hear), and anything that needs a click inside Resolve's UI.
