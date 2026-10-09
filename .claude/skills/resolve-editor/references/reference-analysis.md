# What the reference videos actually do (measured + viewed, 12 unique clips)

Source: `Instagram reference/` (13 files; Video-73741 is a byte-identical duplicate of Video-24447). Measured by `ingest_references.py` (cuts, motion bursts, loudness) and by viewing numbered contact sheets plus 1-fps dense sheets. I cannot hear audio or see motion between frames, so entrance/exit timing is inferred from motion bursts. Treat everything here as style inspiration, **timing-only / style-only**, never frame-for-frame copies of other creators' work.

## 0. Numbers that matter
| Fact | Measured |
|---|---|
| Loudness of every reference | -14.0 to -14.6 LUFS integrated (matches our -14 target) |
| True peak | -3.5 to -0.1 dBTP (several exceed our -1.5 limit; keep ours at <= -1.5) |
| Canvas | vertical clips 720x1280 (9:16); horizontal 960x720 / 1276x718 (these are screen-recordings of YouTube explainers, not Reels) |
| Frame rate | 24 fps in 10/12, 25 and 30 fps in the rest. Cinematic 24 is common; timeline fps should match source, not be forced to 30 |
| Average shot length | talking-head + graphics Reels: 1.8-2.8 s. Kinetic-type explainers: 0.5-1.2 s. Slow "story" cuts: 5-8 s |
| Motion-burst density | 0.7-1.7 per second: something on screen changes about every 0.6-1.4 s even in "slow" videos |
| Audio | loudness range is only 1.2-6.7 LU, i.e. heavily levelled. I cannot hear the clips, so whether they use music/SFX layers is unverified (ask the user, or check with `analyze.py loudness` per band) |

## 0b. What the speech tells us (faster-whisper `small`, see editorial-craft.md for trust levels)
- The 8 English references transcribe cleanly (0-5 % low-confidence words) and run **194-268 words/min** (fast explainers) down to ~76 wpm for slow cinematic ones. At 200+ wpm a 2-word caption pop lasts ~0.3-0.5 s, which is why `captions.py` uses a 0.28 s minimum hold.
- The 4 Tanglish reels (54546, 5612, 67670, 86635) are the ones whose transcript fails, so their word timings below come from the **visuals only**, not from speech.
- Topic of the references: most are explainers about editing/animating with Claude plus an editing MCP (the clips name Claude, Invideo's MCP page, Cursor), i.e. the studio is collecting examples of AI-driven editing. Not used as content, only as style.

## 1. The two style families
**A. Dfren / "yellow tee" creator reels (54546, 5612, 67670, 86635; vertical, Tanglish).** Probably the studio's own look, confirm with the user.
- Talking head in a coloured-gel room (magenta/blue, red, green) or against a pink wall. Brand yellow `#E8AA05`-ish + black + white. Yellow full-frame "info card" scenes alternate with the face.
- Word-by-word captions, 1-2 words on screen, big condensed or heavy sans, white with dark shadow, centred-upper (not in the bottom UI zone). Key word gets a heavy weight or a second line (e.g. "Business / Start", "Product / nambi"). Small romanised-Tamil sub-word under the English word.
- Text that lives inside the scene: rotated "BRO" lying on the desk, "CLIENT / AD ACCOUNT" stacked at top-left, metallic-gradient condensed lettering, green glowing highlight bars on screens, big number count-ups ("Total Amount 82,499/- -> 151,250/- -> 300,000/-").
- Cutaways: stock/AI B-roll in a rounded-corner "phone card" on black, screen recordings in a floating rounded card, split cards like Original vs Copy with progress bars, 91% / 99% rings, collapsing bar charts, Greek pillars, flask with new products. These are designed infographic scenes on yellow, not footage.
- AI-generated 3D (Pixar-like) character B-roll for story beats (86635), whip-pan blur transitions into it.
- 2X-speed callout scene: guest video in a rounded card over a yellow **speed-lines** backdrop with a "2X SPEED" label and a thin progress bar with a time counter (67670).

**B. "Motion-design explainer" references (24447, 42028, 44049, 84658, 86514, 93227, 94468, 95528).** Mostly horizontal screen recordings of other people's videos about motion graphics.
- Kinetic typography locked to speech: each word enters with its own motion (scale, blur-in, slide, typewriter, glitch), emphasis words are large and in the accent colour (red `#C8171E`-style), small connector words stay small/white.
- Text interacts with the subject: subject cut-out (matte) with text passing BEHIND the head/body (42028, 94468, 24447 silhouette), text reflowing around a face, giant letters filling the frame behind/in front ("LIKE", "DM", "AI").
- Collage / paper cut-out looks: torn-paper yellow label text on newspaper/map texture, halftone cut-out people, stamps, postage, cropped objects with a red offset-shadow edge (84658, 93227, 95528).
- Transitions: zoom blur, pixel/mosaic reveal, light-leak / flash bursts, whip blur, glitch/RGB split, shape wipes, speed lines, "page" or "paper rip" cuts.
- Backgrounds change colour to match the beat (red -> blue -> black) with colour-graded matching subject glow.

## 2. Technique catalogue -> what to build
| ID | Technique | Seen in | How we build it (Resolve) | Asset available |
|---|---|---|---|---|
| T1 | Word-by-word caption, 1-2 words, emphasis word bigger/accent | 5612, 86635, 54546, 94468, 42028 | Text+ per word from `timeline_words`; keyword heuristics in `captions.py` (planned) | fonts: pick brand font |
| T2 | Kinetic type with per-word entrance variety | 42028, 86514, 95528 | Fusion Text+ with keyframed Transform + blur; vary entrance per word from a small preset pool | `Animated Letters Pack`, `Paper effects/Letters` |
| T3 | Text behind subject (occlusion) | 42028, 94468, 24447 | Magic Mask (Studio) or depth map on V1 duplicate placed ABOVE the text track; or ffmpeg/rembg matte | none (needs matte) |
| T4 | Yellow info-card scene (stat, comparison, ring %, pillars) | 86635, 54546 | HyperFrames or Resolve Fusion built to brand kit; full-frame on V3 | `Back grounds`, `Motion Backgrounds` for plates |
| T5 | Rounded-corner floating card (phone card / screen-rec) with drop shadow, optional 3D tilt | 54546, 67670, 5612 | Fusion rounded-rect mask + shadow, or `MagicZoomV3`/`Ultimate Seamless` drfx; scale-pop entrance | `Hands`, `green screen phone` |
| T6 | Speed-lines backdrop + "2X SPEED" label + progress bar | 67670 | speed-lines clip on V2, source clip card on V3, label Text+, bar = Fusion rect with time-linked width | `10 Speed Lines Anime Backgrounds` (11 .mov) |
| T7 | Number count-up with units (Rs, k) | 54546, 86635 | Fusion Text+ with expression `string.format` on a keyframed number; ease-out | none |
| T8 | Scene-integrated 3D text (rotated, perspective, lying on desk) | 54546 | Fusion Text3D/Transform with corner pin, tracked if camera moves | none |
| T9 | Screen-recording scene: crop/zoom to the relevant UI + glow highlight | 54546, 5612, 93227 | punch-in keyframes, green glow bar (alpha overlay), ensure text readable at phone size | `Glow FX`, `IG Animations` |
| T10 | Paper / collage cut-out text and torn-paper label | 95528, 84658, 93227 | Text+ on yellow torn-paper PNG, jittered 8-12 fps stop-motion transform | `Paper effects` (10 GB), `PNGs` |
| T11 | Flash / light-leak / film-burn transition | 44049, 95528 | Add-blend (Screen) clip from `Film Burn Transitions`, 6-12 frames centred on the cut | yes |
| T12 | Glitch / RGB split / mosaic reveal | 86514, 44049 | Resolve Fusion glitch preset or pre-rendered overlay | partially |
| T13 | Whip-pan / motion-blur transition into B-roll | 86635 | Resolve "Directional blur" + transform keyframes on both clips | `MrAlexTech Ultimate Seamless` |
| T14 | AI-generated B-roll (3D character, stylised scenes) | 86635, 44049 | out-of-scope generator (Higgsfield/Kling etc., user-supplied); we ingest the clip like any B-roll | n/a |
| T15 | Coloured gel light + subject colour pop, matched grade across B-roll | 54546, 67670, 42028 | LUT per scene (see `LUTs`) + node-level tint; use `color_match.py` for B-roll | 21 .cube LUTs |
| T16 | SFX on graphic events (whoosh on card, pop on word, hit on number): standard practice per the studio SOP, not verifiable from the clips | n/a | `broll-and-sfx.md`; needs an SFX library (none in assets/ except a zipped Paper SFX pack) | **missing** |
| T17 | Hook in first 1.5 s: text + movement already on screen at frame 0 | 24447, 54546, 86635, 94468 | rule in `editorial-craft.md`; first graphic must start <= frame 6 | n/a |
| T18 | Ending: on-brand CTA / icon beat; last frame is held <= 1 s | 5612, 84658 | CTA card from clip-studio | n/a |

## 3. Rules distilled (add to every job's QA)
1. Something visually new at least every 1.5-2.5 s (cut, card, graphic, punch-in). If the A-roll runs 3 s with no change, flag it.
2. Captions never sit in the platform UI zones (see `platforms.md` measured safe zone). In the references they sit at ~28-45 % height or in the middle.
3. One accent colour per video plus white/black; accent used on keywords and glows only.
4. Every graphic has an entrance, a hold >= reading time, and an exit. No graphic just "appears".
5. Alternate scene types (face -> card -> face -> B-roll). Never more than ~8 s of unbroken face without an overlay.
6. B-roll cards are rounded corners with a soft shadow when floating, or full-bleed when they replace A-roll; never a hard rectangle with a thin border.
7. Colour: keep face skin consistent; gel-light rooms are graded as a look, not corrected to neutral.
8. Loudness target -14 LUFS, true peak <= -1.5 dBTP; music compressed so the voice stays on top.
9. For Tanglish: show English keywords large and the romanised Tamil connector smaller beneath/beside. Do not translate unless asked.

## 4. Honest limits
- Several references are screen-recordings of third-party videos about motion design. They tell us the *vocabulary* of effects, not a ready preset.
- Motion bursts are a proxy for animation timing; exact easing curves are guessed (marked `confidence: low` in presets).
- I cannot verify fonts from pixels; I name families by look only (heavy condensed sans, geometric sans, slab serif). Ask the user for the real font files.
