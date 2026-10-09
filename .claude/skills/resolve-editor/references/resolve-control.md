# Controlling DaVinci Resolve Studio

Two routes. Prefer the MCP for exploratory/creative operations; use `scripts/resolve_build.py` for deterministic builds. Both need **Resolve Studio** with Preferences > System > General > *External scripting using* = **Local**, and Resolve running with a project open.

## Route A - resolve_build.py (no MCP)
`probe` (connection + version), `build`, `verify`, `place`, `markers`, `render`. Run in a **scratch project first**. Always `verify` after `build`; if every clip is long/short by one frame flip `--end-offset` (-1 ↔ 0). Add `--mock` to dry-run logic without Resolve.

## Route B - Resolve MCP
- `samuelgursky/davinci-resolve-mcp`: `npx davinci-resolve-mcp setup` (registers with Claude Code; ~35 compound tools). Verify with `/mcp` in Claude Code.
- Resolve 21.1+ has a native MCP (File > Setup AI Assistants). Use whichever works; don't run both.
- Tools worth knowing (names as documented; confirm with the live tool list, it changes): `timeline` (get_transcript, propose_cuts, apply_cuts, ripple_insert, copy_range), `edit_engine` (plan_/execute_ for selects, tighten, silence ripple), `timeline_versioning` (archive/rollback - use before risky edits), `media_pool`, `knowledge` (read before creative work), `folder.transcribe_audio`.
- If a tool errors, read the error, try the granular equivalent, then fall back to Route A. Don't loop more than 3 times.

## Rules
1. One project per client job: `Dfren - <job>`; bins `RAW/<job>`, `BROLL`, `SFX`, `CLIPS`.
2. Duplicate the timeline for each version (`Cut v1`, `Cut v2`). Never edit in place after the client has seen a version.
3. Track layout (video): V1 A-roll, V2 B-roll, V3 clips/cards, V4 text/graphics. Audio: A1 voice, A2 SFX, A3 music.
4. Read back after writes (clip count, durations, positions). Take a frame with `qc.py frames` from a preview render, not from memory.
5. Text: Text+ via Fusion, titles carry brand font/colour; entrance/exit animation from approved presets (see motion-and-text.md). Set Tamil font explicitly and test-render one frame.
6. Colour: apply the CDL suggested by `color_match.py` through the clip's colour page (CDL) or a node; view before/after.
7. Render: `resolve_build.py render` (H.264 MP4). Preview renders at half resolution are fine for QC frames.
8. If Resolve is not running or scripting is blocked: say exactly which step failed and fall back to the EDL (`cut.edl`) + ffmpeg preview so work is not lost.

## Connection facts (verified against the local README, Resolve 21.0.3.7 on this PC; see also editing-knowledge.md section 4)
- Windows env (README): `RESOLVE_SCRIPT_API=%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting`, `RESOLVE_SCRIPT_LIB=C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll`, `PYTHONPATH` += `%RESOLVE_SCRIPT_API%\Modules\`. Resolve must be running and **Preferences > System > General > External scripting using = Local**.
- Studio vs Free: external scripting needs **Studio**. Resolve 21.1 (Sept 2026) also made scripting Studio-only and added a native MCP (File > Setup AI Assistants); this PC has 21.0.3.7, so use `resolve_build.py` (Route A) or the community MCP. Run only one MCP.
- API details used by this skill: node indexes are 1-based; `SetCDL` takes STRING values (`{"NodeIndex":"1","Slope":"r g b","Offset":"r g b","Power":"r g b","Saturation":"s"}`); `SetLUT(node, path)` only works on LUTs Resolve already discovered, so copy the .cube into Resolve's LUT folder and call `Project.RefreshLUTList()` first; use INTEGER frames in `AppendToTimeline` (fractional values silently return nothing: check the returned list length).

## VERIFIED LIVE on Resolve Studio 21.0.3.7 (2026-10-09, scratch project "Dfren Scratch")
Works:
- **Python**: Resolve's `fusionscript` refuses to initialise under the Microsoft-Store **Python 3.10** (`SystemError: initialization of fusionscript failed without raising an exception`) but loads under **Python 3.13** (via `py -3.13`). `common.connect_resolve()` re-runs the calling script under a working interpreter automatically; `preflight.py` reports it. The Resolve log line `Started script server` proves Resolve itself was fine.
- `clipInfo endFrame` is **exclusive** (default `--end-offset 0`; `verify` caught the off-by-one with the old default).
- `AppendToTimeline` with integer frames, `recordFrame` positions (timeline starts at frame 108000 = 01:00:00:00 @30), `mediaType` 1/2, `trackIndex`; `tl.AddTrack("video")`/`("audio","stereo")` is needed first (a missing track returns `[None]`, which `place` now treats as failure).
- `TimelineItem.SetCDL` (strings, node 1) -> True; `Project.RefreshLUTList()` + `NodeGraph.SetLUT(1, "Dfren\\file.cube")` -> True and `GetLUT(1)` reads it back (LUTs live in `...\Support\LUT\Dfren`, copied by `resolve_build.py grade/from-spec`; a CDL and a LUT can share node 1).
- `SetProperty("CompositeMode", resolve.COMPOSITE_SCREEN)` (5.0), `Opacity` (0-100), `ZoomX/ZoomY`, `Tilt` read back correctly; the zoom needed to cover a landscape overlay on a 9:16 timeline is computed from `Resolution`.
- `InsertFusionTitleIntoTimeline("Text+")` returns an item; `GetFusionCompByIndex(1).GetToolList(False,"TextPlus")` finds the tool; `SetInput("StyledText", ...)` and `SetInput("Font","Bebas Neue")` read back correctly.
- Resolve's own render (`SetCurrentRenderFormatAndCodec("mp4","H264")`, `SetRenderSettings`, `AddRenderJob`, `StartRendering`, status polling): 23 s 1080x1920 timeline in 10 s, matched the ffmpeg render frame for frame (captions, cards, grade); QC -14.1 LUFS.
Does NOT work / is limited:
- `InsertFusionTitleIntoTimeline` goes to V1 at the playhead (it split the clip), and with V1 locked it returns None: a Text+ cannot be targeted to V2 or trimmed to 0.3 s from the script. So per-word captions are placed as ONE transparent ProRes caption overlay (`captions_ass.py --overlay`), not as editable Text+ per caption; single Text+ titles are still possible on an otherwise empty timeline.
- `TimelineItem.SetProperty("Volume", ...)` fails: audio gain is pre-applied with ffmpeg (SFX gain, ducked music stem).
- `CreateMagicMask("F")` returned False without a selection; text-behind-subject stays a manual Magic Mask step.
- Resolve's keyers are not scriptable here: green screens are pre-keyed to ProRes 4444 alpha with ffmpeg before placing.
Still unknown: Fusion preset (`.setting`) import by script; SRT import into a subtitle track by script; behaviour on a project that already has client timelines.
