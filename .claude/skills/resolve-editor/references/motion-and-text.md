# Motion graphics and text

## Principles (the "premium" bar)
- Every animation eased (ease-out in, ease-in out). No linear moves, no default pop/fade only.
- Entrance 6-10 frames @30 fps, exit 5-8 frames, hold ≥ reading time (words/3 s + 0.4 s).
- One motion language per video: pick a preset family and reuse it. Max 2 fonts, brand colours only.
- Text stays inside safe zones (platforms.md). Min size ~64 px for 1080 wide hook text; check contrast with a stroke/shadow/box.
- Emphasis words get colour/scale; never animate every word.

## Where the style comes from
1. Approved presets in `references/sorted/` and `presets/*.json` (written by reference ingest).
2. Brand kit (`brand-kits/<client>.json`).
3. If none exist, use the defaults below and mark the video "default style - no references supplied".

Defaults: Hook = bold sans, 2 lines max, scale-pop 85→104→100 % over 8 frames + 4-frame fade; keyword highlight in accent colour; exit = quick slide-down + fade 6 frames. Captions = 3 words/line max, active word accent colour, lower-third at ~62-68 % height.

## Preset JSON (what ingest writes, what you read)
```json
{"id":"bold-pop","kind":"parametric|fusion_setting|rendered_clip|lut",
 "entrance":{"type":"scale-pop","frames":8,"ease":"outBack","from":0.85},
 "exit":{"type":"slide-fade","frames":6,"ease":"inCubic","dy":40},
 "timing":{"hold_min_s":0.9},"style":{"font":"heading","stroke_px":6,"shadow":true,"highlight":"accent"},
 "source":"references/sorted/.../sheet.jpg","copy_rule":"timing-only|style-only|recreate"}
```
`copy_rule` records what the user allowed (timing only / style / recreate). Respect it.

## Studio style vocabulary (from the 12 references)
Full catalogue with technique IDs T1-T18 and which asset folder serves each: `reference-analysis.md`. Parametric presets for them live in `presets/*.json` (all `confidence: low`, `copy_rule: style-only`). Pick one **motion language per video**: either (A) the yellow info-card + word-pop caption look used on the studio's own Tanglish reels, or (B) kinetic-type/collage explainer look. Do not mix families in one video.

Recipes the scripts cannot do alone (state this honestly in the report):
- **Text behind subject (T3)**: duplicate the A-roll clip above the text track and give it a matte (Resolve Magic Mask or depth map). Magic Mask is a UI action, not scriptable here: prepare the layers, then ask the user to run Magic Mask on the duplicate, or fall back to text beside the subject.
- **Screen recordings (T9)**: crop/zoom to the row that matters (never show the whole dashboard), add a glow bar, float in a rounded card; keep UI text >= ~28 px on a 1080-wide frame.
- **Transitions**: flash/light-leak = Film Burn/Glow clip with Screen blend (6-14 frames, centred on the cut); whip = Directional Blur + opposing Transform keyframes (6-10 frames); glitch = Fusion glitch for hook reveals only. Each transition gets an SFX; max one transition type repeated per video plus one accent.
- **Count-up numbers (T7)**: ease-out over ~0.6 s, then hold >= 0.8 s; units as in the brief (Rs, k, "/-"); confirm Indian vs western digit grouping with the user.
- **Tanglish captions**: English key word large, romanised-Tamil connector small under it (`sub` field of `captions.py` events); never auto-translate.

## Building in Resolve
- Text+ title with brand font; keyframes via Fusion setting (preferred: import a `.setting`), else set Transform keyframes on the title clip.
- Tamil text: set a Tamil-capable font; render one frame and look before applying to all.
- Captions: build from `timeline_words` (word timestamps shifted onto the timeline), or import an SRT generated from it.
- Save any new good look back as a preset so the library grows.
