# Director playbook: how a dense, reference-quality edit is built here

Worked example: `examples/fire-reel_build_edit.py` (the "AI-edited fire reel", 18 s, from one low-res phone take). Copy it, change the footage/timings/words, run it. Everything is on the OUTPUT timeline `T`; map source time with `T = src - offset`.

## 1. Read the footage like an editor (before touching anything)
1. `analyze.py probe/loudness/silence`, a dense frame sheet (`ffmpeg -vf fps=2,tile`), and a transcript restricted to the speech (`--model large-v3 --device cuda`). **Measure when speech really starts** (per-0.5 s RMS): Whisper's first words were wrong because of a silent lead-in; here speech started at 4.8 s, so the reel opens on a cold-open hook instead of 5 s of dead air.
2. Get word timings from a transcript of the speech-only region, then write them in the director script as comments: every text hit, camera pulse, sound hit and transition is pinned to a word time.
3. Look at the source frames to find usable cutaway footage in the unused parts (video only; the voice keeps running).

## 2. The layers (bottom to top) and what builds each
| Layer | Tool | Notes |
|---|---|---|
| A-roll + cold open | `compose.py` clips | muted cold-open clip + continuous A-roll; low-res phone footage is upscaled with lanczos then `finish.sharpen` |
| Camera | `compose.camera` | slow push-in keyframes, **beat pulses on key words** (+7-20 %), impact shake; one `scale(eval=frame)+crop` expression |
| Grade | `compose.grade/finish/fx` | CDL + sharpen + vignette + grain; `fx` windows: flash, rgbsplit, blur, tint; a **grade change after the big hit** ("fire mode") and a dim/blur behind the end card |
| Cutaways | `overlays` with `in`, `fit:"cover"`, fades | from unused source ranges, covered by flame licks / glitch splits |
| Transitions | `graphics/cards/fire-wipe.html` (WebGL) | wipe = full-cover fire sweeping a direction (cover peak = start + 0.5 * dur: put the cut there); flick = same shader, `band 1.0`, 0.6 s, never fully covers |
| Typography + HUD | `graphics/cards/typo.html` (HyperFrames) | one transparent layer for the whole reel, JSON events (below) |
| Sound | `sounddesign.py` + `compose` voice chain | event-synced bed, mixed under the voice with gentle sidechain |

## 3. Typography events (typo.html `events` JSON, times on T)
`phrase` {t, dur, y(% of height), lines:[[word...]], exit, gap}; a word = {w, s: xs|sm|md|lg|xl|mega, a: pop|rise|slam|blur|flip|glitch|spin|drop, c: w|a|r|y|k, fire:true, at: T, strike: T, dim: T}.
Others: `counter` {from,to,suffix,label,px,flash}, `badge`, `emoji`, `hud` {status:[{t,text}]} (REC dot, timecode, corner brackets, typed status line), `embers`, `shock` (thin expanding ring), `shake`.
Rules learned the hard way:
- **Every line auto-fits** (`MAXW` 960 px, `zoom`), measured after fonts load and before tweens exist. The first version clipped half the words.
- **One phrase on screen at a time.** Give each phrase an explicit `dur` that ends before the next begins; overlapping phrases looked like noise.
- Big type must stay readable on bright frames: dark outline (round: a ring of text-shadows; `-webkit-text-stroke` makes square miter slabs at 600 px), gradient face for fire words.
- **No soft glows / gradients / box-shadows in an alpha overlay.** They are stored premultiplied and come out dark or hide the footage (the "dark disc"). Use thin solid shapes; get brightness from `fx.flash` in the compositor.
- Scaling a bordered element scales its border (a ring became a fat donut): animate an SVG circle's radius instead.
- Do not cover the speaker's face for more than a beat; keep `mega` <= 620 px and move it up.
- Keep HUD/decoration inside the safe zone and out of the text band.

## 4. Fire wipe shader (what makes it read as fire)
Noise stretched along the sweep axis and scrolling the same way (tongues rise); three octaves (billow, tongue, lick); heat ramp ember red -> orange -> yellow, white only in the hottest cores; ragged leading edge from the noise, cooling/smoky trailing edge; premultiplied output. Variables: `dur`, `dir` up/down/left/right, `band` (1.7 = full-screen cover for a moment, 1.0 = flame lick), `seed`, `heat`.

## 5. Sound design (measured, not heard)
Events: heartbeat, riser (into every hit), boom (hit), impact (word hits), whoosh/swell, fire (swell + crackle), crackle bed, tick, zap (glitch), drone rising to the big moment. Keep the bed ~20 dB under the voice between hits and let hits reach +3..+5 dB over the voice RMS (measured half-second by half-second with `audio_iter`-style checks: voice-only vs mix). Voice chain: highpass 85, afftdn, small EQ, compressor (makeup 2), limiter. Final: two-pass loudnorm -14 LUFS; set `true_peak` about -4 so the AAC encode lands under -1.5 dBTP.

## 6. Review loop that actually caught the problems
Contact sheet every 0.6 s of a PREVIEW render (`--preview`, half size), fix structure; then full-res key frames at each hit (480 px wide tiles are not enough to see outline slabs or clipped words); isolate a layer (render it alone over grey, print alpha stats) when something looks wrong; QC; only then export. Iteration costs: typography 100 s, compose preview 60 s, final 50 s.

## 7. Honest limits
Sound design and motion feel are judged by measurement and stills only; the creative timing (which words get which animation) is my judgement from the transcript. Footage resolution caps sharpness (478x850 source). In Resolve, typography/fire layers arrive as transparent clips, not editable text.
