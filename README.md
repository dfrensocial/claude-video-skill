# Dfren video editor: an AI that edits your videos (a Claude Code skill)

## Use it in 2 steps (no coding)
1. Open **Claude Code** in this folder (open a terminal here and type `claude`) and drop your raw video into the `footage/` folder.
2. Tell Claude what you want, in plain words (type, or speak with `/voice`), for example: *"Edit footage/my-clip.mp4 into a hype Reel with big animated text, fire transitions and sound effects."* Claude edits it and saves the finished MP4 in `exports/`.

Optional: say the style you like ("like the yellow info-card reels", "kinetic text", "calm and clean"), the language (English / Tamil / Tanglish) and where it will run (organic Reel or paid ad). If you tell Claude to change something ("make the text bigger"), it remembers it for next time.

## What it does
- Cuts from the transcript (removes dead air, fillers, retakes), cleans and levels the voice, grades the colour.
- Adds animated captions and big kinetic typography, graphics cards (counters, rings, comparisons), real fire transitions, glitch and flash cuts, camera punch-ins and event-synced sound design.
- Exports a ready-to-upload 9:16 MP4 (-14 LUFS), and can also build an **editable DaVinci Resolve timeline**.

## One-time setup (Windows 11)
Needs: Claude Code (claude.ai account), Python 3.10+, ffmpeg, Node 22+. Recommended: an NVIDIA GPU (fast Tamil/English transcription via `faster-whisper` + CUDA libraries). For the Resolve timeline: DaVinci Resolve **Studio** with Preferences > System > General > *External scripting using* = **Local** (the scripts use `py -3.13` automatically if your default Python cannot load Resolve; see `RESOLVE_SETUP.md`).
Your own packs (overlays, LUTs, SFX, music, B-roll) go in the folders listed in `workspace.json`; third-party packs and your footage are git-ignored and never pushed.

## How it is organised
- `.claude/skills/resolve-editor/` : the skill (`SKILL.md` is the entry point, `references/` has the playbooks, `scripts/` the tools, `examples/` a full worked edit).
- `graphics/` : HyperFrames motion-graphics templates (kinetic typography, fire wipe, cards).
- `styles/`, `presets/`, `style-fingerprints/` : editing styles learned from the reference videos.
- `knowledge/` : the memory graph (your corrections and preferences, so you never repeat them).
- `footage/` (input), `exports/` (finished videos), `jobs/` (work files).

## Honest limits
Claude cannot hear audio or watch motion: it checks frames, measurements and QC, so judge the sound and feel yourself and tell it what to change. Low-resolution source footage stays soft. Tamil transcription is good on clean speech and unreliable under music (the tool flags the bad parts). Text in the Resolve timeline arrives as transparent clips, not editable Text+ layers.
