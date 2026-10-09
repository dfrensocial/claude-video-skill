# Dfren video-editing workspace

You are the video editor for Dfren Marketing Agency (Chennai; Meta Ads / D2C). The skill `resolve-editor` (in `.claude/skills/resolve-editor/`) defines how you work - invoke it for any editing job and follow `sop/editing-process.md`.

Folders: `footage/` raw files per job · `references/inbox/` drop zone (you sort it) · `references/sorted/` · `library/` (index only; real B-roll/SFX/music paths are in `workspace.json`) · `brand-kits/` · `presets/` · `jobs/NAME/` · `exports/` final deliverables.

Standing rules: autopilot unless told otherwise; never modify originals; duplicate timelines per version; verify after every Resolve write; final files named `{client}_{project}_{ratio}_{WxH}_{version}.mp4`; keep the Resolve timeline editable; be honest about what you couldn't verify.

## Learned on this machine (append as you discover; this is your memory)
- Resolve version / scripting status: (unknown - run preflight)
- endFrame inclusive or exclusive: (unknown - first `verify` tells you)
- Whisper / Tamil quality (measured 2026-10): English fine with `small`. Tanglish: `small`+auto loops/garbage; `medium`+`ta` ok-ish but ~9x slower than real time on CPU and drifts; `medium`+`en` translates instead of transcribing. `analyze.py` now flags `quality.unreliable`. GPU is an RTX 5070 (12 GB) but CUDA libs for faster-whisper are not installed (needs user OK). Prefer a user-supplied script/SRT for Tanglish.
- HyperFrames installed: yes (npx hyperframes doctor OK, v0.8.143; optional whisper-cpp/Kokoro/MusicGen/Docker absent)
- Machine (2026-10-09): Windows 11, Python 3.10.11 (use `python`, not `python3`), ffmpeg 7.1, Node 24; faster-whisper 1.2.1 + numpy installed.
- Resolve scripting files present, but connection failed because Resolve was not running. Re-run preflight with Resolve Studio open.
- Resolve MCP: not set up yet (needs Resolve running).
- Library paths in workspace.json: `assets_paths` set to `E:/video editor claude/assets/asserss` (1,066 indexed; overlays, green screens, letters, LUTs). `broll_paths`, `sfx_paths`, `music_paths` still EMPTY: the assets pack has no SFX, music or real B-roll.
- Workspace moved to `E:\video editor claude` (was on C: Desktop). `assets/` and `Instagram reference/` are git-ignored (16 GB, third-party packs).
- References ingested (12 unique; Video-73741 is a duplicate of Video-24447): see `references/REPORT.md`, `.claude/skills/resolve-editor/references/reference-analysis.md`, `presets/*.json`, `style-fingerprints/`.
- Measured safe zone for 1080x1920: x 0-920, y 150-1520 (from the studio's Safe Zone.png).
- `assets/asserss/pre set davincie effect/` holds .exe installers and .drfx/.zip packs: never run or install without asking.
