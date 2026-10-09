# Generated clips (hook cards, stat cards, CTA end cards, lower-thirds)

Used when no B-roll fits or for designed moments. Output is a short MP4 (full-frame, or on black for Screen/Add blending) placed on V3.

## Tools, in order of preference
1. **Resolve Text+/Fusion** - editable, native. Use for text-only overlays.
2. **HyperFrames** (heygen-com, Apache-2.0; needs Node 22+ and FFmpeg): `npx hyperframes doctor` → `npx hyperframes init <dir>` → write HTML/CSS/GSAP composition → `npx hyperframes preview` → `npx hyperframes render`. MP4 output only is documented; **alpha is unverified** - design full-frame cards or use black background + Screen blend.
3. **/brag** works only for codebase-launch videos (via HyperFrames) - not for ad clips; don't use it unless the job is a code/product-launch video.
4. ffmpeg drawtext/xfade for trivial cards.
Avoid Remotion (commercial licence concerns for an agency).

## Procedure
1. Spec the clip from clip-templates/README.md (size = timeline res, fps = timeline fps, duration, brand colours/fonts, text copy from the brief verbatim).
2. Build in `jobs/NAME/clips/`, render at timeline res.
3. `qc.py frames` → LOOK at first/mid/last frame; check text legible, in safe zone, brand colours exact.
4. Place with `resolve_build.py place` (kind `clip`).
5. Install HyperFrames only after the user's OK (kickoff authorises it once).
