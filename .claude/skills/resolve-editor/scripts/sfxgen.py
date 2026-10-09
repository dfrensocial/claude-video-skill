#!/usr/bin/env python3
"""Synthesise a small, original, royalty-free SFX library (numpy, no downloads): whoosh, swish, pop, click, hit, riser, ding,
glitch, stamp, tick. Several variants of each. Output: <workspace>/library/sfx/generated/<name>_NN.wav (48 kHz stereo 16-bit).

  sfxgen.py [--out DIR] [--variants 3] [--seed 7]

These are simple synthetic sounds meant for UI/transition accents, not studio-grade foley. I cannot hear them: they are checked
by measurement only (duration, peak, RMS, spectral centroid; see the printed table). Judge by ear and tell me which to replace;
the user's own packs (e.g. library/sfx/paper/) work alongside them via index_library.py (--kind sfx).
Peaks are normalised to -3 dBFS so the mixer's per-event gain_db (compose.py `sfx`) sets the level (-18..-12 dB vs voice).
"""
import argparse
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from common import find_workspace  # noqa: E402

SR = 48000


def t_axis(d):
    return np.arange(int(SR * d)) / SR


def env_ar(n, attack, release, curve=2.0):
    e = np.ones(n)
    a, r = int(SR * attack), int(SR * release)
    if a > 0:
        e[:a] = np.linspace(0, 1, a) ** curve
    if r > 0:
        e[-r:] = np.linspace(1, 0, r) ** curve
    return e


def lowpass_sweep(x, f0, f1):
    """One-pole low-pass whose cutoff glides f0 -> f1 (Hz) across the signal."""
    n = len(x)
    f = np.geomspace(max(f0, 20), max(f1, 20), n)
    a = 1 - np.exp(-2 * np.pi * f / SR)
    y = np.zeros(n)
    s = 0.0
    for i in range(n):
        s += a[i] * (x[i] - s)
        y[i] = s
    return y


def highpass(x, fc):
    a = np.exp(-2 * np.pi * fc / SR)
    y = np.zeros(len(x))
    px = py = 0.0
    for i in range(len(x)):
        py = a * (py + x[i] - px)
        px = x[i]
        y[i] = py
    return y


def norm(x, peak_db=-3.0):
    m = float(np.max(np.abs(x))) or 1.0
    return x * (10 ** (peak_db / 20) / m)


def stereo(x, pan0=0.0, pan1=0.0):
    n = len(x)
    p = np.linspace(pan0, pan1, n)  # -1 left .. +1 right
    l = x * np.sqrt((1 - p) / 2)
    r = x * np.sqrt((1 + p) / 2)
    return np.stack([l, r], 1)


def whoosh(rng, d=0.7):
    n = int(SR * d)
    x = rng.standard_normal(n)
    y = lowpass_sweep(x, 300, 5000) * env_ar(n, d * 0.55, d * 0.4)
    y = highpass(y, 120)
    return stereo(norm(y), rng.choice([-0.8, 0.8]), -rng.choice([-0.8, 0.8]) * 0.2)


def swish(rng, d=0.28):
    n = int(SR * d)
    x = rng.standard_normal(n)
    y = lowpass_sweep(x, 1500, 9000) * env_ar(n, d * 0.45, d * 0.5)
    return stereo(norm(highpass(y, 400)), -0.7, 0.7)


def pop(rng, d=0.16):
    t = t_axis(d)
    f = rng.uniform(520, 760)
    y = np.sin(2 * np.pi * (f * 0.45 + f * 0.55 * np.exp(-t * 35)) * t) * np.exp(-t * 28)
    y[: int(SR * 0.002)] += rng.standard_normal(int(SR * 0.002)) * 0.4
    return stereo(norm(y))


def click(rng, d=0.05):
    t = t_axis(d)
    y = np.sin(2 * np.pi * rng.uniform(1700, 2300) * t) * np.exp(-t * 90)
    y[: int(SR * 0.0015)] += rng.standard_normal(int(SR * 0.0015)) * 0.6
    return stereo(norm(y))


def tick(rng, d=0.03):
    t = t_axis(d)
    return stereo(norm(np.sin(2 * np.pi * rng.uniform(3000, 4200) * t) * np.exp(-t * 160)))


def hit(rng, d=0.9):
    t = t_axis(d)
    body = np.sin(2 * np.pi * (48 + 90 * np.exp(-t * 18)) * t) * np.exp(-t * 5.5)
    nz = rng.standard_normal(len(t))
    nz = lowpass_sweep(nz, 6000, 300) * np.exp(-t * 14) * 0.5
    return stereo(norm(body + nz))


def riser(rng, d=1.6):
    n = int(SR * d)
    t = t_axis(d)
    tone = np.sin(2 * np.pi * np.cumsum(np.geomspace(180, 1800, n)) / SR)
    nz = lowpass_sweep(rng.standard_normal(n), 400, 7000)
    y = (0.6 * tone + 0.8 * nz) * (np.linspace(0, 1, n) ** 2.2)
    y *= env_ar(n, 0, 0.03, 1)
    return stereo(norm(y))


def ding(rng, d=1.3):
    t = t_axis(d)
    f = rng.choice([1318.5, 1568.0, 1760.0])
    y = sum(a * np.sin(2 * np.pi * f * k * t) * np.exp(-t * dec) for k, a, dec in ((1, 1.0, 3.2), (2.01, 0.4, 5.0), (3.02, 0.15, 8.0)))
    return stereo(norm(y))


def glitch(rng, d=0.4):
    n = int(SR * d)
    x = np.zeros(n)
    pos = 0
    while pos < n:
        ln = int(SR * rng.uniform(0.012, 0.05))
        seg = np.sign(rng.standard_normal(ln)) * rng.uniform(0.3, 1.0) if rng.random() < 0.5 else \
            np.sin(2 * np.pi * rng.uniform(300, 3000) * np.arange(ln) / SR)
        x[pos:pos + ln] = seg[: n - pos]
        pos += ln + int(SR * rng.uniform(0.0, 0.03))
    return stereo(norm(x * env_ar(n, 0.005, 0.1)), rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5))


def stamp(rng, d=0.35):
    t = t_axis(d)
    thud = np.sin(2 * np.pi * (70 + 60 * np.exp(-t * 40)) * t) * np.exp(-t * 14)
    snap = highpass(rng.standard_normal(len(t)), 1200) * np.exp(-t * 60) * 0.7
    return stereo(norm(thud + snap))


KINDS = {"whoosh": whoosh, "swish": swish, "pop": pop, "click": click, "tick": tick, "hit": hit, "riser": riser,
         "ding": ding, "glitch": glitch, "stamp": stamp}


def write_wav(path, x):
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def spectrum_stats(x):
    """Power-weighted spectral centroid (Hz) and the share of energy below 200 Hz."""
    m = x.mean(1)
    sp = np.abs(np.fft.rfft(m)) ** 2
    fr = np.fft.rfftfreq(len(m), 1 / SR)
    tot = sp.sum() or 1.0
    return float((sp * fr).sum() / tot), float(sp[fr < 200].sum() / tot)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out")
    ap.add_argument("--variants", type=int, default=3)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    ws = find_workspace()
    out = Path(a.out) if a.out else (ws / "library" / "sfx" / "generated")
    out.mkdir(parents=True, exist_ok=True)
    print("name | dur s | peak dBFS | rms dBFS | centroid Hz | energy <200 Hz")
    for name, fn in KINDS.items():
        for v in range(1, a.variants + 1):
            rng = np.random.default_rng(a.seed * 1000 + v * 17 + len(name))
            x = norm(fn(rng))  # peak -3 dBFS after the pan law
            p = out / f"{name}_{v:02d}.wav"
            write_wav(p, x)
            rms = 20 * np.log10(np.sqrt((x ** 2).mean()) + 1e-9)
            c, low = spectrum_stats(x)
            print(f"{p.name} | {len(x) / SR:.2f} | {20 * np.log10(np.abs(x).max()):.1f} | {rms:.1f} | {c:.0f} | {low * 100:.0f}%")
    print(f"wrote to {out}")


if __name__ == "__main__":
    main()
