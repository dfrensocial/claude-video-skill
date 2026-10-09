# Dfren-Editor - setup in 5 minutes

1. Put this whole folder on your Desktop (`~/Desktop/Dfren-Editor`). Note: `.claude` is a **hidden folder** (Mac: Cmd+Shift+. in Finder to see it) - keep it inside.
2. Install DaVinci Resolve **Studio**. In Resolve: Preferences > System > General > *External scripting using* = **Local**. Keep Resolve open with a project.
3. Make sure Python 3.10+, ffmpeg, and Node 22+ are installed.
4. Open Claude Code in this folder (`cd ~/Desktop/Dfren-Editor && claude`), paste KICKOFF_PROMPT.md's main block, fill in your library paths.
5. Dump reference files (motion samples, fonts, LUTs, screenshots, finished videos) in `references/inbox/`; raw footage in `footage/`. Optional naming: `<type>__<copy>__<name>.ext` (copy = timing-only | style-only | recreate).
6. Add a brand kit per client: copy `brand-kits/_template.json`.

What to expect: first jobs need a few fix-rounds (the Resolve code was only logic-tested). Tamil ASR quality is uncertain. Claude cannot hear audio - cuts come from the transcript and measurements, with uncertain spots flagged.
