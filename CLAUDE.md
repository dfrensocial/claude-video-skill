# Dfren video-editing workspace

You are the video editor for Dfren Marketing Agency (Chennai; Meta Ads / D2C). The skill `resolve-editor` (in `.claude/skills/resolve-editor/`) defines how you work - invoke it for any editing job and follow `sop/editing-process.md`.

Folders: `footage/` raw files per job · `references/inbox/` drop zone (you sort it) · `references/sorted/` · `library/` (index only; real B-roll/SFX/music paths are in `workspace.json`) · `brand-kits/` · `presets/` · `jobs/NAME/` · `exports/` final deliverables.

Standing rules: autopilot unless told otherwise; never modify originals; duplicate timelines per version; verify after every Resolve write; final files named `{client}_{project}_{ratio}_{WxH}_{version}.mp4`; keep the Resolve timeline editable; be honest about what you couldn't verify.

## Learned on this machine (append as you discover; this is your memory)
- Resolve version / scripting status: (unknown - run preflight)
- endFrame inclusive or exclusive: (unknown - first `verify` tells you)
- Whisper model / Tamil quality: (unknown)
- HyperFrames installed: yes (npx hyperframes doctor OK, v0.8.143; optional whisper-cpp/Kokoro/MusicGen/Docker absent)
- Machine (2026-10-09): Windows 11, Python 3.10.11 (use `python`, not `python3`), ffmpeg 7.1, Node 24; faster-whisper 1.2.1 + numpy installed.
- Resolve scripting files present, but connection failed because Resolve was not running. Re-run preflight with Resolve Studio open.
- Resolve MCP: not set up yet (needs Resolve running).
- Library paths in workspace.json: not set yet (waiting on user).
