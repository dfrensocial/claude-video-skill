#!/usr/bin/env python3
"""Director script: 'FIRE REEL' (AI-edited fire-transition reel) built from footage/demo1/raw.mp4.

Every time below is on the OUTPUT timeline T.  Source mapping: T = src - 3.0 for src >= 4.6 (A-roll), after a 1.6 s cold open.
Speech (src): This 4.77 | video 5.21 | being 5.79 | completely 5.95 | edited 6.41 | by 6.77 | AI 7.13 | not 7.71 | single 8.55 |
step 8.83 | human 10.27 | complete 12.07 | transition 12.41 | video 12.79 | with 13.21 | FIRE 13.47 | check 15.43 | first 15.79 |
output 16.05 | this 17.33 | reel 18.15-18.81.
Run:  python jobs/fire-reel/build_edit.py [--preview] [--skip-render-cards]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".claude" / "skills" / "resolve-editor" / "scripts"))
import compose  # noqa: E402
import graphics  # noqa: E402
import sounddesign  # noqa: E402

JOB = ROOT / "jobs" / "fire-reel"
RAW = str(ROOT / "footage" / "demo1" / "raw.mp4")
ASSETS = ROOT / "assets" / "asserss"
BURN = ASSETS / "Film Burn Transitions-20241225T142257Z-001" / "Film Burn Transitions"
OFF = 3.0           # T = src - OFF for the A-roll
A0, A1 = 4.6, 21.2  # A-roll source range
H0, H1 = 0.15, 1.75 # cold open source range (headphone macro)
T_A = H1 - H0       # A-roll starts here (1.6 s)
T_END = T_A + (A1 - A0)  # 18.2


def T(src):
    return round(src - OFF, 3)


ap = argparse.ArgumentParser()
ap.add_argument("--preview", action="store_true")
ap.add_argument("--skip-render-cards", action="store_true")
ap.add_argument("--out", default=str(ROOT / "exports" / "fire-reel_v1.mp4"))
a = ap.parse_args()
JOB.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------------ 1. fire wipes (alpha overlays, cover peak = start + 0.5*dur)
wipes = [  # (name, cut time, dur, dir, seed, heat)
    ("fire_hook", T_A, 1.25, "up", 3, 0.8),
    ("fire_main", T(13.47) - 0.02, 1.7, "up", 7, 0.95),
    ("fire_end", T_END - 1.8, 1.3, "down", 5, 0.85),
]
wipe_files = {}
for name, cut, dur, d, seed, heat in wipes:
    out = JOB / f"{name}.mov"
    wipe_files[name] = (out, cut - 0.5 * dur, dur)
    if not out.exists() or not a.skip_render_cards:
        graphics.render("fire-wipe", {"dur": dur, "dir": d, "seed": seed, "heat": heat}, str(out), "mov", "looks")
        print("rendered", name)
# short flame licks over smaller cuts (band 1.0: a quick flare that never fully covers the picture)
flicks = {}
for name, d, seed in (("flick_r", "right", 11), ("flick_l", "left", 13), ("flick_u", "up", 17)):
    out = JOB / f"{name}.mov"
    flicks[name] = out
    if not out.exists() or not a.skip_render_cards:
        graphics.render("fire-wipe", {"dur": 0.6, "dir": d, "seed": seed, "heat": 0.9, "band": 1.0}, str(out), "mov", "looks")
        print("rendered", name)

# ------------------------------------------------------------------ 2. typography layer
W = lambda w, s="md", **k: dict(w=w, s=s, **k)
events = [
    # HUD for the whole piece
    {"type": "hud", "t": 0.15, "dur": T_END - 1.9, "tc_start": 0.0, "status": [
        {"t": 0.35, "text": "ANALYZING FOOTAGE"}, {"t": 1.9, "text": "DETECTING SPEECH"}, {"t": 3.3, "text": "GENERATING CUTS"},
        {"t": 5.4, "text": "REMOVING HUMAN INPUT"}, {"t": 8.5, "text": "LOADING FIRE ENGINE"},
        {"t": 10.9, "text": "RENDERING TRANSITIONS"}, {"t": 12.9, "text": "EXPORTING FIRST OUTPUT"}]},
    # --- cold open
    {"type": "phrase", "t": 0.3, "dur": 1.35, "y": 40, "exit": "zoom", "gap": 6, "lines": [
        [W("THE FIRST", "sm", at=0.35, a="rise")],
        [W("AI-EDITED", "lg", at=0.62, a="glitch", c="y")],
        [W("FIRE REEL", "xl", at=0.9, a="slam", fire=True)]]},
    {"type": "embers", "t": 0.7, "dur": 1.3, "n": 70, "y0": 104, "seed": 2},
    # --- 1: "This video is being completely edited by AI"
    {"type": "phrase", "t": T(4.77), "dur": 1.95, "y": 25, "exit": "up", "lines": [
        [W("THIS VIDEO IS BEING", "sm", at=T(4.77), a="rise")],
        [W("COMPLETELY", "md", at=T(5.95), a="flip", c="y")]]},
    {"type": "phrase", "t": T(6.41), "dur": 1.6, "y": 34, "exit": "zoom", "gap": 0, "lines": [
        [W("EDITED BY", "lg", at=T(6.41), a="blur")],
        [W("AI", "mega", at=T(7.13), a="slam", fire=True)]]},
    {"type": "shock", "t": T(7.13) + 0.2, "x": 540, "y": 800, "size": 22},
    {"type": "shake", "t": T(7.13) + 0.2, "amp": 22, "dur": 0.35},
    # --- 2: "and not even a single step was done by a human"
    {"type": "phrase", "t": T(7.71), "dur": 3.75, "y": 30, "exit": "fall", "gap": 2, "lines": [
        [W("NOT EVEN", "md", at=T(7.71), a="blur")],
        [W("A SINGLE STEP", "lg", at=T(8.55), a="glitch", c="y")],
        [W("WAS DONE BY A", "sm", at=T(9.43), a="pop"), W("HUMAN", "xl", at=T(10.27), a="drop", c="r", strike=T(10.27) + 0.3, dim=T(10.27) + 0.45)]]},
    {"type": "counter", "t": T(7.8), "dur": 2.9, "y": 64, "from": 100, "to": 0, "suffix": "%", "label": "HUMAN INPUT", "px": 250,
     "count": 2.4, "flash": "#ff2b2b"},
    {"type": "shake", "t": T(10.27) + 0.28, "amp": 14, "dur": 0.3},
    # --- 3: "and this is going to be a complete transition video with fire"
    {"type": "phrase", "t": T(12.07) - 0.1, "dur": 1.45, "y": 27, "exit": "glitch", "gap": 0, "lines": [
        [W("COMPLETE", "lg", at=T(12.07), a="rise")],
        [W("TRANSITION", "xl", at=T(12.41), a="glitch", c="a")],
        [W("VIDEO", "md", at=T(12.79), a="pop")]]},
    {"type": "phrase", "t": T(13.21) - 0.05, "dur": 2.3, "y": 38, "exit": "zoom", "gap": 0, "lines": [
        [W("WITH", "lg", at=T(13.21), a="pop")],
        [W("FIRE", "mega", at=T(13.47), a="slam", fire=True)]]},
    {"type": "embers", "t": T(13.47) - 0.1, "dur": 2.8, "n": 130, "y0": 106, "seed": 9},
    {"type": "shock", "t": T(13.47) + 0.2, "x": 540, "y": 800, "size": 28, "dur": 0.7},
    {"type": "shake", "t": T(13.47) + 0.2, "amp": 30, "dur": 0.55},
    {"type": "emoji", "t": T(13.47) + 0.45, "dur": 1.7, "e": "🔥", "x": 740, "y": 1010, "px": 230, "rot": 10},
    # --- 4: "and you are going to check the first output of this reel"
    {"type": "phrase", "t": T(15.43) - 0.05, "dur": 2.0, "y": 27, "exit": "up", "gap": 2, "lines": [
        [W("CHECK THE", "md", at=T(15.43), a="rise")],
        [W("FIRST OUTPUT", "lg", at=T(15.79), a="flip", c="y")]]},
    {"type": "badge", "t": T(16.05), "dur": 2.1, "text": "AI EDIT #001", "x": 640, "y": 184, "bg": "#ff7a1a"},
    {"type": "phrase", "t": T(17.33) - 0.05, "dur": 1.3, "y": 56, "exit": "shrink", "lines": [
        [W("OF THIS REEL", "md", at=T(17.33), a="blur")]]},
    # --- end card
    {"type": "phrase", "t": T_END - 1.55, "dur": 1.55, "y": 38, "exit": "up", "gap": 4, "lines": [
        [W("100%", "xl", at=T_END - 1.5, a="slam", fire=True)],
        [W("AI EDITED", "lg", at=T_END - 1.2, a="rise")],
        [W("NO HUMAN INPUT", "sm", at=T_END - 0.9, a="pop", c="y")]]},
    {"type": "emoji", "t": T_END - 1.1, "dur": 1.1, "e": "🔥", "x": 880, "y": 560, "px": 150, "rot": -8},
]
(JOB / "typo_events.json").write_text(json.dumps(events, ensure_ascii=False, indent=1), encoding="utf-8")
typo_mov = JOB / "typo.mov"
if not a.skip_render_cards or not typo_mov.exists():
    graphics.render("typo", {"events": json.dumps(events, ensure_ascii=False)}, str(typo_mov), "mov", "looks")
    print("rendered typography")

# ------------------------------------------------------------------ 3. sound design (event-synced)
tF = T(13.47)
sd = {"total": T_END, "drone": {"gain_db": -27, "rise_to": tF}, "events": [
    {"t": 0.0, "kind": "heartbeat", "dur": 1.6, "gain_db": -22},
    {"t": 0.15, "kind": "riser", "dur": 1.4, "gain_db": -14},
    {"t": T_A - 0.62, "kind": "fire", "dur": 1.3, "gain_db": -13},
    {"t": T_A, "kind": "boom", "gain_db": -9},
    {"t": T(5.5) - 0.0, "kind": "tick", "gain_db": -26},
    {"t": T(5.95) - 0.0, "kind": "whoosh", "gain_db": -22},
    {"t": T(6.8), "kind": "swell", "dur": 0.55, "gain_db": -18},
    {"t": T(7.13), "kind": "impact", "gain_db": -9},
    {"t": T(7.13) + 0.02, "kind": "boom", "gain_db": -14},
    {"t": T(7.71), "kind": "tick", "gain_db": -24},
    {"t": T(8.55), "kind": "zap", "gain_db": -20},
    {"t": T(8.83), "kind": "tick", "gain_db": -24},
    {"t": T(10.27), "kind": "impact", "gain_db": -11},
    {"t": T(10.27) + 0.3, "kind": "zap", "gain_db": -16},
    {"t": T(11.2), "kind": "riser", "dur": 1.9, "gain_db": -16},
    {"t": T(12.41), "kind": "zap", "gain_db": -18},
    {"t": tF - 0.9, "kind": "fire", "dur": 1.8, "gain_db": -11},
    {"t": tF, "kind": "boom", "gain_db": -7},
    {"t": tF, "kind": "impact", "gain_db": -9},
    {"t": tF + 0.3, "kind": "crackle", "dur": 2.6, "gain_db": -24},
    {"t": T(15.43) - 0.35, "kind": "whoosh", "gain_db": -15},
    {"t": T(15.79), "kind": "tick", "gain_db": -22},
    {"t": T(18.15), "kind": "impact", "gain_db": -15},
    {"t": T_END - 1.8, "kind": "fire", "dur": 1.3, "gain_db": -15},
    {"t": T_END - 1.5, "kind": "boom", "gain_db": -11},
    {"t": T_END - 1.4, "kind": "crackle", "dur": 1.4, "gain_db": -26},
]}
(JOB / "sound_events.json").write_text(json.dumps(sd, indent=1), encoding="utf-8")
bed = JOB / "bed.wav"
print(sounddesign.render(sd, bed, T_END))

# ------------------------------------------------------------------ 4. edit spec
def ov(file, start, **kw):
    return dict(file=str(file), start=start, **kw)

pulses = [(T(7.13), .17), (T(7.71), .09), (T(8.55), .08), (T(8.83), .09), (T(10.27), .14), (T(12.41), .09), (T(13.47), .2),
          (T(15.79), .1), (T(16.05), .08), (T(18.15), .12), (T_A, .10), (T(5.95), .07)]
overlays = [
    # cutaways from unused parts of the same shoot (video only; voice keeps running)
    ov(RAW, T(6.15), **{"in": 2.95}, dur=0.72, blend="normal", fit="cover", fps_in=True, fade_in=0.04, fade_out=0.04),
    ov(RAW, T(8.4), **{"in": 2.0}, dur=0.62, blend="normal", fit="cover", fps_in=True, fade_in=0.04, fade_out=0.04),
    # flame licks over the cuts (own fire shader; the pack's film burns were yellow-green, not fire)
    ov(flicks["flick_r"], T(6.15) - 0.28, blend="normal", fit="cover", dur=0.6),
    ov(flicks["flick_l"], T(6.15) + 0.72 - 0.28, blend="normal", fit="cover", dur=0.6),
    ov(flicks["flick_u"], T(8.4) - 0.28, blend="normal", fit="cover", dur=0.6),
    ov(flicks["flick_r"], T(8.4) + 0.62 - 0.28, blend="normal", fit="cover", dur=0.6),
    ov(flicks["flick_l"], T(11.4), blend="normal", fit="cover", dur=0.6),
    ov(flicks["flick_u"], T(15.3) - 0.2, blend="normal", fit="cover", dur=0.6),
    # three fire wipes
    *[ov(f, s, blend="normal", fit="cover", dur=d) for (f, s, d) in wipe_files.values()],
    # typography + HUD on top of everything
    ov(typo_mov, 0.0, blend="normal", fit="cover", dur=T_END),
]
spec = {
    "output": {"file": a.out, "w": 1080, "h": 1920, "fps": 30, "lufs": -14, "true_peak": -4.2, "crf": 17},
    "clips": [{"src": RAW, "in": H0, "out": H1, "mute": True},
              {"src": RAW, "in": A0, "out": A1}],
    "camera": {"zoom": [[0, 1.0], [T_A, 1.16], [T_A + 0.001, 1.0], [T(13.47), 1.07], [T_END, 1.12]],
               "pulses": [{"t": t, "amp": amp, "decay": 8} for t, amp in pulses],
               "shake": [{"t": T(7.13) + 0.2, "dur": 0.4, "amp": 16}, {"t": T(10.27) + 0.28, "dur": 0.35, "amp": 12},
                         {"t": T(13.47) + 0.2, "dur": 0.55, "amp": 22}, {"t": T_END - 1.5, "dur": 0.4, "amp": 14}]},
    "grade": {"cdl": {"Slope": "1.10 1.03 0.93", "Offset": "0.022 0.012 0.0", "Power": "0.84 0.88 0.96", "Saturation": "1.25"}},
    "finish": {"sharpen": 0.8, "vignette": 5.5, "grain": 5},
    "fx": [
        {"type": "flash", "t": T_A - 0.05, "dur": 0.2, "amp": 0.7},
        {"type": "flash", "t": T(7.13) + 0.15, "dur": 0.16, "amp": 0.85}, {"type": "rgbsplit", "t": T(7.13) + 0.15, "dur": 0.24, "px": 11},
        {"type": "rgbsplit", "t": T(6.15), "dur": 0.1, "px": 9}, {"type": "rgbsplit", "t": T(6.15) + 0.72, "dur": 0.1, "px": 9},
        {"type": "rgbsplit", "t": T(8.4), "dur": 0.1, "px": 9}, {"type": "rgbsplit", "t": T(8.4) + 0.62, "dur": 0.1, "px": 9},
        {"type": "rgbsplit", "t": T(10.27) + 0.28, "dur": 0.2, "px": 8}, {"type": "blur", "t": T(10.27) + 0.28, "dur": 0.1, "px": 6},
        {"type": "tint", "t": T(13.47) - 0.1, "dur": 0.25, "g": 0.55, "b": 0.25},
        {"type": "flash", "t": T(13.47) + 0.1, "dur": 0.22, "amp": 0.9},
        {"type": "rgbsplit", "t": T(15.6), "dur": 0.2, "px": 12}, {"type": "blur", "t": T(15.6), "dur": 0.12, "px": 8},
        # 'fire mode' look after the hit: hotter, more saturated; then dim + blur behind the end card
        {"type": "grade", "t": T(13.47) + 0.15, "dur": T_END - 1.9 - T(13.47), "rs": 0.04, "rm": 0.06, "bm": -0.05, "bs": -0.03, "sat": 1.12, "contrast": 1.06},
        {"type": "grade", "t": T_END - 1.65, "dur": 3.0, "brightness": -0.22, "sat": 0.75, "blur": 5},
    ],
    "voice_chain": "highpass=f=85,afftdn=nf=-24,equalizer=f=220:t=q:w=1:g=-2,equalizer=f=3400:t=q:w=1:g=3,"
                   "acompressor=threshold=-22dB:ratio=3.5:attack=6:release=120:makeup=2,alimiter=limit=0.9",
    "overlays": overlays,
    "music": {"file": str(bed), "gain_db": 9.5, "duck": True, "fade_out": 0.6, "sc": {"threshold": 0.1, "ratio": 2.2, "release": 300}},
    "sfx": [],
}
(JOB / "spec.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
res = compose.render(spec, preview=a.preview)
print(json.dumps(res, indent=1))
