# B-roll and SFX

## Finding B-roll moments (from `timeline_words` in cut_plan.json)
- Concrete nouns/actions (product, ingredient, place, "pour", "open"), numbers/claims, scene changes, and any jump cut that is visually jarring.
- On talking head: new visual every 2-4 s; B-roll length 0.8-2.5 s; never cover the hook's first 0.6 s with B-roll unless the brief says so; keep the speaker's face on screen for CTA.
- Start B-roll 2-5 frames **before** the matching word lands (it feels synced); end on a cut, not mid-motion.

## Searching the library
`python3 scripts/index_library.py search --kind broll --q "tea pour steam cup chai" --orient vertical --min-dur 2 --sheet jobs/NAME/broll/s1.jpg`
Send several synonyms. LOOK at the sheet (tile n = result n). Reject: wrong subject, watermark, wrong orientation, motion that fights the speaker's gesture, brand conflict. If nothing fits, say "no suitable B-roll for <line>" - don't force one; offer a generated card or a punch-in instead.

## Alignment & colour check
1. Place → preview render → `qc.py frames` at each B-roll start/end → LOOK.
2. `color_match.py --target <aroll> --source <broll>`; apply the CDL; re-check. Brand palette from the kit beats literal matching for accents.
3. Aspect/scale: fill the frame (scale to fit height for vertical); avoid black bars; no stretched clips.

## SFX
- Pools: whoosh/swish (transitions, text in/out), hit/impact (emphasis, stat reveal), pop/click (UI-like text), riser (before a reveal), ding/cash (offer). Search `--kind sfx --q "whoosh swoosh"` `--max-dur 1.5`.
- Rule: SFX supports an event; ≤ 1 per 1.5 s on average; vary the sample; level -18 to -12 dB relative to voice peak; start 1-3 frames before the visual event.
- Music: pick by tags in the brand kit; trim to length, fade out last 1 s, duck -12 to -18 dB under voice (pre-gain with ffmpeg via `place` gain_db, or Resolve fairlight ducking).
- Nothing over the loudest word of the hook.
