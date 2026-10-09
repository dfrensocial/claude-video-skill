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

## Known unknowns (verify on first live run, record outcome in CLAUDE.md)
inclusive vs exclusive `endFrame`; whether AppendToTimeline `recordFrame` honours gaps on your version; Text+ preset import path; Fusion setting application via script; audio gain via script (we pre-gain with ffmpeg instead).
