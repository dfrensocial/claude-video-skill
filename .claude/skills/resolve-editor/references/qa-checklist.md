# Review checklist (act as a critic who didn't make the edit)

Run after the preview render; view `qc.py frames --every 1 --sheet` sheets, not just numbers.

**Cut**: no stutters/repeats left; every join reads as a sentence; no clipped word starts/ends; nothing from the script missing (or flagged); hook in first 3 s; length within ±2 s of brief.
**B-roll**: matches the spoken line; starts/ends on cue; no watermark/wrong subject; colour matches; no black/frozen frames (`qc.py`).
**Text**: copy exact vs brief (spelling, price, numbers); brand font/colour; in safe zone; readable for its duration; entrances/exits eased; Tamil glyphs render.
**Audio**: voice clear; SFX not louder than voice; music ducked; no silence ≥0.6 s mid; -14 LUFS ±1.5; no clipping.
**Output**: right resolution/ratio/fps/codec; filename convention; file opens; duration matches timeline.
**Compliance**: no unsupported claims; `do_not` list respected; no competitor names; no third-party logos.

Output of review = a short list: PASS / FIXED / FLAGGED. If any FAIL remains after 3 loops, deliver anyway with the failure at the top of the report.
