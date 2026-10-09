# Dfren video-editing workspace

You are the video editor for Dfren Marketing Agency (Chennai; Meta Ads / D2C). The skill `resolve-editor` (in `.claude/skills/resolve-editor/`) defines how you work - invoke it for any editing job and follow `sop/editing-process.md`.

Folders: `footage/` raw files per job · `references/inbox/` drop zone (you sort it) · `references/sorted/` · `library/` (index only; real B-roll/SFX/music paths are in `workspace.json`) · `brand-kits/` · `presets/` · `jobs/NAME/` · `exports/` final deliverables.

Standing rules: autopilot unless told otherwise; never modify originals; duplicate timelines per version; verify after every Resolve write; final files named `{client}_{project}_{ratio}_{WxH}_{version}.mp4`; keep the Resolve timeline editable; be honest about what you couldn't verify.

## Learned on this machine (append as you discover; this is your memory)
- Resolve version / scripting status: (unknown - run preflight)
- endFrame inclusive or exclusive: (unknown - first `verify` tells you)
- Whisper / Tamil quality (measured 2026-10): English fine with `small`. CUDA libs ARE now installed (nvidia-cublas-cu12, nvidia-cudnn-cu12; user approved) and the RTX 5070 works with faster-whisper. **Tanglish: use `--lang tanglish` = large-v3 + `ta` + NO verbatim prompt: 11 s for a 23 s clean clip, 6 % low-confidence, Tamil script with English words in Latin.** The English "uh, you know" verbatim prompt makes Whisper echo the prompt on Tamil audio; `small`+auto loops; `medium` on CPU 150-215 s; `medium`+`en` translates. Under music / a second voice (Video-54546) large-v3 is still garbage in parts: `quality.unreliable_ranges` lists the bad time spans, trust only the rest, otherwise ask for the script/SRT. Romanised (Latin) Tanglish is not produced by Whisper; planned: Aksharamukha "Roman (Colloquial)" step (untested).
- Resolve: 21.0.3.7 installed and running, but `preflight` cannot connect yet: needs Studio edition + Preferences > System > General > External scripting = Local (see RESOLVE_SETUP.md). User wants the Resolve setup done LAST.
- User confirmed (2026-10-09): the yellow-tee reels (54546, 5612, 67670, 86635) are their OWN videos and their colour needs fixing; wants to experiment with fonts and colours based on the references; wants editing style as a per-job input (`styles/`), a self-learning memory graph (`knowledge/`, `kb.py`), CUDA installed, and large files pushed via Git LFS.
- GitHub repo dfrensocial/claude-video-skill is PUBLIC: do not push third-party transcripts/frames/packs (git-ignored). User OK'd pushing (2026-10-09).
- HyperFrames installed: yes (npx hyperframes doctor OK, v0.8.143; optional whisper-cpp/Kokoro/MusicGen/Docker absent)
- Machine (2026-10-09): Windows 11, Python 3.10.11 (use `python`, not `python3`), ffmpeg 7.1, Node 24; faster-whisper 1.2.1 + numpy installed.
- Resolve scripting files present, but connection failed because Resolve was not running. Re-run preflight with Resolve Studio open.
- Resolve MCP: not set up yet (needs Resolve running).
- Library paths in workspace.json: `assets_paths` set to `E:/video editor claude/assets/asserss` (1,066 indexed; overlays, green screens, letters, LUTs). `broll_paths`, `sfx_paths`, `music_paths` still EMPTY: the assets pack has no SFX, music or real B-roll.
- Workspace moved to `E:\video editor claude` (was on C: Desktop). `assets/` and `Instagram reference/` are git-ignored (16 GB, third-party packs).
- References ingested (12 unique; Video-73741 is a duplicate of Video-24447): see `references/REPORT.md`, `.claude/skills/resolve-editor/references/reference-analysis.md`, `presets/*.json`, `style-fingerprints/`.
- Measured safe zone for 1080x1920: x 0-920, y 150-1520 (from the studio's Safe Zone.png).
- `assets/asserss/pre set davincie effect/` holds .exe installers and .drfx/.zip packs: never run or install without asking.
