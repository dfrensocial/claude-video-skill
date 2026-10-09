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

## Building in Resolve
- Text+ title with brand font; keyframes via Fusion setting (preferred: import a `.setting`), else set Transform keyframes on the title clip.
- Tamil text: set a Tamil-capable font; render one frame and look before applying to all.
- Captions: build from `timeline_words` (word timestamps shifted onto the timeline), or import an SRT generated from it.
- Save any new good look back as a preset so the library grows.
