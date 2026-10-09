# Review checklist (act as a critic who didn't make the edit)

Run after the preview render; view `qc.py frames --every 1 --sheet` sheets, not just numbers.

**Cut**: no stutters/repeats left; every join reads as a sentence; no clipped word starts/ends; nothing from the script missing (or flagged); hook in first 3 s; length within ±2 s of brief.
**B-roll**: matches the spoken line; starts/ends on cue; no watermark/wrong subject; colour matches; no black/frozen frames (`qc.py`).
**Rhythm** (from the references): hook graphic/motion on screen within the first 6 frames; a visual change at least every ~1.6 s on average, no static stretch > 6 s (`qc.py check` flags it); never > ~8 s of unbroken face without an overlay, card or punch-in; scene types alternate (face / card / b-roll).
**Text**: copy exact vs brief (spelling, price, numbers); brand font/colour; inside the measured safe box x 0-920, y 150-1520 on 1080x1920 (platforms.md); captions 1-2 words with at most one emphasis word, never two emphasised events in a row; readable for its duration; entrances/exits eased; Tamil glyphs render.
**Audio**: voice clear; SFX not louder than voice; music ducked; no silence ≥0.6 s mid; -14 LUFS ±1.5; no clipping.
**Output**: right resolution/ratio/fps/codec; filename convention; file opens; duration matches timeline.
**Compliance**: no unsupported claims; `do_not` list respected; no competitor names; no third-party logos.

Output of review = a short list: PASS / FIXED / FLAGGED. If any FAIL remains after 3 loops, deliver anyway with the failure at the top of the report.
