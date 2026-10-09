# Reference ingest: turning dropped files into usable style

All reference material goes into `references/inbox/`. Run `python3 scripts/ingest_references.py` (copies to `references/sorted/<kind>/`, never deletes; `--move` only if asked).

## What it produces
`references/catalog.json`, `references/REPORT.md`, and per video a numbered `sheet.jpg` + `frames.json` (tile → time). Measured: scene cuts, motion-energy bursts (≈ when elements enter/exit), palette, loudness.

## What you do next
1. Read REPORT.md. Resolve "needs a human decision" items by asking ONE grouped question (e.g., "is this clip for timing only, or copy the look?").
2. For each motion reference: LOOK at the sheet, read the measured bursts, write a preset JSON into `presets/` (schema in motion-and-text.md). Be honest: you infer, you don't see motion; label `confidence`.
3. `.setting` / Fusion files → register as `fusion_setting` presets. LUTs → `lut`. Fonts → install per OS guidance and add to the brand kit. Images/screenshots → palette + layout notes. Notes `.txt` → read verbatim and obey.
4. Finished videos (kind `video-finished`) → treat as style/pacing references: extract cut rhythm (avg shot length), caption style, music energy; write a "style fingerprint" in `presets/fingerprints/<name>.md`.
5. Naming convention to skip guessing: `<type>__<copy>__<name>.<ext>` e.g. `caption__timing-only__bold-pop.mp4`.
6. Finish with a catalog summary to the user: counts per kind, presets created, open questions.

Never reproduce a third party's protected branding/footage; "timing only" and "style inspiration" are fine, exact recreation only for the user's own assets.
