#!/usr/bin/env python3
"""Event-synced sound design bed (no melody): sub drone, risers, booms, fire whooshes, crackle, ticks, glitch zaps, heartbeat.

  sounddesign.py events.json --out bed.wav [--total 17.9]
  events.json: {"total": 17.9, "drone": {"gain_db": -26, "start": 0, "rise_to": 12.0},
                "events": [{"t": 1.2, "kind": "riser", "dur": 1.2, "gain_db": -14}, {"t": 1.3, "kind": "boom", "gain_db": -8}, ...]}
kinds: boom, riser, whoosh, fire (swell + crackle), crackle (dur), tick, zap (glitch), heartbeat (dur), swell (reverse-cymbal style), impact (short punch)
Everything is synthesised with numpy (deterministic, seeded), stereo 48 kHz. I cannot hear it: levels and spectra are reported so
they can be checked by measurement, and the result must be judged by ear. The bed is mixed UNDER the voice (compose.py sidechain).
"""
import argparse
import json
import sys
import wave
from pathlib import Path

import numpy as np

SR = 48000


def tx(d):
    return np.arange(int(SR * d)) / SR


def lp(x, fc):
    a = 1 - np.exp(-2 * np.pi * fc / SR)
    y = np.zeros_like(x)
    s = 0.0
    for i in range(len(x)):
        s += a * (x[i] - s)
        y[i] = s
    return y


def lp_sweep(x, f0, f1):
    n = len(x)
    f = np.geomspace(max(f0, 20), max(f1, 20), n)
    a = 1 - np.exp(-2 * np.pi * f / SR)
    y = np.zeros(n)
    s = 0.0
    for i in range(n):
        s += a[i] * (x[i] - s)
        y[i] = s
    return y


def hp(x, fc):
    return x - lp(x, fc)


def reverb(x, rt=1.4, mix=0.35, seed=1):
    rng = np.random.default_rng(seed)
    n = int(SR * rt)
    ir = rng.standard_normal(n) * np.exp(-np.linspace(0, 6.5, n))
    ir = lp(ir, 5200)
    ir /= np.abs(ir).sum() ** 0.5 + 1e-9
    nfft = 1 << int(np.ceil(np.log2(len(x) + n)))
    y = np.fft.irfft(np.fft.rfft(x, nfft) * np.fft.rfft(ir, nfft), nfft)[: len(x) + n]
    out = np.zeros(len(y))
    out[: len(x)] += x * (1 - mix)
    out += y * mix * (np.abs(x).max() / (np.abs(y).max() + 1e-9))
    return out


def st(x, pan=0.0):
    l = x * np.sqrt((1 - pan) / 2)
    r = x * np.sqrt((1 + pan) / 2)
    return np.stack([l, r], 1)


def boom(rng, d=2.2):
    t = tx(d)
    body = np.sin(2 * np.pi * np.cumsum(38 + 110 * np.exp(-t * 9)) / SR) * np.exp(-t * 2.3)
    sub = np.sin(2 * np.pi * 31 * t) * np.exp(-t * 1.6) * 0.8
    nz = lp_sweep(rng.standard_normal(len(t)), 5000, 160) * np.exp(-t * 6) * 0.7
    crack = hp(rng.standard_normal(len(t)), 1800) * np.exp(-t * 70) * 0.5
    x = body + sub + nz + crack
    x = reverb(x, 1.6, 0.30, seed=int(rng.integers(1, 99)))
    return st(x)


def impact(rng, d=0.5):
    t = tx(d)
    x = np.sin(2 * np.pi * np.cumsum(60 + 160 * np.exp(-t * 28)) / SR) * np.exp(-t * 11)
    x += hp(rng.standard_normal(len(t)), 1500) * np.exp(-t * 55) * 0.55
    return st(x)


def riser(rng, d=1.4):
    n = int(SR * d)
    t = tx(d)
    nz = lp_sweep(rng.standard_normal(n), 250, 9000)
    tone = np.sin(2 * np.pi * np.cumsum(np.geomspace(90, 1400, n)) / SR)
    env = np.linspace(0, 1, n) ** 2.4
    x = (0.85 * nz + 0.45 * tone) * env
    x = x * (1 - 0.0 * t)
    return st(x, 0.0)


def swell(rng, d=1.2):
    n = int(SR * d)
    nz = hp(lp_sweep(rng.standard_normal(n), 800, 11000), 400)
    env = np.concatenate([np.linspace(0, 1, int(n * 0.88)) ** 3, np.linspace(1, 0, n - int(n * 0.88)) ** 1.5])
    return st(nz * env)


def whoosh(rng, d=0.7, pan0=-0.7, pan1=0.7):
    n = int(SR * d)
    x = lp_sweep(rng.standard_normal(n), 300, 6500)
    env = np.concatenate([np.linspace(0, 1, int(n * 0.5)) ** 1.6, np.linspace(1, 0, n - int(n * 0.5)) ** 1.8])
    x = hp(x * env, 150)
    p = np.linspace(pan0, pan1, n)
    return np.stack([x * np.sqrt((1 - p) / 2), x * np.sqrt((1 + p) / 2)], 1)


def crackle_signal(rng, d, density=70.0, level=1.0):
    n = int(SR * d)
    x = np.zeros(n)
    k = int(density * d)
    pos = rng.integers(0, max(n - 400, 1), k)
    for p in pos:
        ln = int(rng.integers(40, 380))
        amp = rng.uniform(0.2, 1.0) * level
        seg = rng.standard_normal(ln) * np.exp(-np.linspace(0, 7, ln)) * amp
        x[p:p + ln] += seg[: n - p]
    x = hp(x, 1200)
    return x


def fire(rng, d=1.8):
    n = int(SR * d)
    nz = lp_sweep(rng.standard_normal(n), 400, 4200)
    env = np.concatenate([np.linspace(0, 1, int(n * 0.35)) ** 1.4, np.linspace(1, 0.35, n - int(n * 0.35)) ** 1.2])
    cr = crackle_signal(rng, d, 120, 1.0) * env * 1.6
    x = 0.8 * hp(nz, 90) * env + cr
    return st(x)


def crackle(rng, d=2.0):
    x = crackle_signal(rng, d, 90, 1.0)
    env = np.concatenate([np.linspace(0, 1, int(SR * 0.15)), np.ones(int(SR * d) - int(SR * 0.3)), np.linspace(1, 0, int(SR * 0.15))])
    return st(x * env[: len(x)] if len(env) >= len(x) else x)


def tick(rng, d=0.05):
    t = tx(d)
    return st(np.sin(2 * np.pi * rng.uniform(2800, 3800) * t) * np.exp(-t * 150))


def zap(rng, d=0.22):
    n = int(SR * d)
    x = np.zeros(n)
    pos = 0
    while pos < n:
        ln = int(SR * rng.uniform(0.008, 0.03))
        seg = np.sign(rng.standard_normal(ln)) * rng.uniform(0.3, 1.0) if rng.random() < 0.5 else \
            np.sin(2 * np.pi * rng.uniform(300, 4000) * np.arange(ln) / SR)
        x[pos:pos + ln] = seg[: n - pos]
        pos += ln + int(SR * rng.uniform(0.0, 0.02))
    return st(x * np.exp(-np.linspace(0, 3, n)), rng.uniform(-0.6, 0.6))


def heartbeat(rng, d=1.6):
    n = int(SR * d)
    out = np.zeros(n)
    t = tx(0.18)
    thump = np.sin(2 * np.pi * (52 + 40 * np.exp(-t * 30)) * t) * np.exp(-t * 20)
    for beat in np.arange(0, d - 0.3, 0.8):
        for off, g in ((0.0, 1.0), (0.22, 0.7)):
            i = int((beat + off) * SR)
            out[i:i + len(thump)] += thump[: n - i] * g
    return st(out)


KINDS = {"boom": boom, "impact": impact, "riser": riser, "swell": swell, "whoosh": whoosh, "fire": fire, "crackle": crackle,
         "tick": tick, "zap": zap, "heartbeat": heartbeat}


def drone(total, gain_db, rise_to=None, seed=3):
    rng = np.random.default_rng(seed)
    n = int(SR * total)
    t = np.arange(n) / SR
    f0 = 55.0 * (1 + (0.5 * (t / (rise_to or total)).clip(0, 1) ** 2 if rise_to else 0))
    base = np.sin(2 * np.pi * np.cumsum(f0) / SR) * 0.6 + np.sin(2 * np.pi * np.cumsum(f0 * 2.003) / SR) * 0.25
    saw = ((np.cumsum(f0 * 1.5) / SR) % 1.0) * 2 - 1
    saw = lp(saw, 420) * 0.35 * (0.6 + 0.4 * np.sin(2 * np.pi * 0.17 * t))
    air = lp_sweep(rng.standard_normal(n), 300, 1500) * 0.06
    x = (base + saw + air) * (0.35 + 0.65 * (t / total) ** 0.8) * np.clip(t / 0.8, 0, 1)
    x *= 10 ** (gain_db / 20) / (np.abs(x).max() + 1e-9)
    return st(x)


def render(spec, out_wav, total=None):
    total = float(total or spec.get("total", 18.0))
    tail = 2.5
    n = int(SR * (total + tail))
    mix = np.zeros((n, 2))
    d = spec.get("drone")
    if d:
        dr = drone(total, d.get("gain_db", -26), d.get("rise_to"))
        mix[: len(dr)] += dr
    report = []
    for k, e in enumerate(spec.get("events", [])):
        rng = np.random.default_rng(1000 + k * 31)
        fn = KINDS[e["kind"]]
        kw = {"d": e["dur"]} if e.get("dur") else {}
        sig = fn(rng, **kw)
        g = 10 ** (e.get("gain_db", -12) / 20)
        peak = np.abs(sig).max() or 1.0
        sig = sig / peak * g
        i0 = int(float(e["t"]) * SR)
        end = min(n, i0 + len(sig))
        mix[i0:end] += sig[: end - i0]
        report.append((e["t"], e["kind"], round(20 * np.log10(g + 1e-9), 1)))
    pk = np.abs(mix).max()
    if pk > 0.95:
        mix *= 0.95 / pk
    pcm = (np.clip(mix, -1, 1) * 32767).astype("<i2")
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    rms = 20 * np.log10(np.sqrt((mix ** 2).mean()) + 1e-9)
    return {"file": str(out_wav), "duration": round(len(mix) / SR, 2), "peak_dbfs": round(20 * np.log10(np.abs(mix).max() + 1e-9), 1),
            "rms_dbfs": round(rms, 1), "events": len(report)}


def render_stems(spec, out_dir, gain_offset_db=0.0):
    """One WAV per event (+ the drone) instead of a single bed, so every sound is its own editable clip in Resolve.
    Returns [{"t", "kind", "file", "dur"}]. gain_offset_db is applied to everything (used to hit the loudness target)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    total = float(spec.get("total", 18.0))
    items = []

    def save(sig, name, t, kind):
        pk = np.abs(sig).max()
        if pk > 0.98:
            sig = sig * 0.98 / pk
        pcm = (np.clip(sig, -1, 1) * 32767).astype("<i2")
        p = out_dir / name
        with wave.open(str(p), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm.tobytes())
        items.append({"t": round(float(t), 3), "kind": kind, "file": str(p), "dur": round(len(sig) / SR, 3)})

    gain = 10 ** (gain_offset_db / 20)
    d = spec.get("drone")
    if d:
        dr = drone(total, d.get("gain_db", -26), d.get("rise_to")) * gain
        save(dr, "00_drone.wav", 0.0, "drone")
    for k, e in enumerate(spec.get("events", [])):
        rng = np.random.default_rng(1000 + k * 31)
        kw = {"d": e["dur"]} if e.get("dur") else {}
        sig = KINDS[e["kind"]](rng, **kw)
        sig = sig / (np.abs(sig).max() or 1.0) * (10 ** (e.get("gain_db", -12) / 20)) * gain
        save(sig, f"{k + 1:02d}_{float(e['t']):06.2f}_{e['kind']}.wav", e["t"], e["kind"])
    return items


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("events")
    ap.add_argument("--out", required=True)
    ap.add_argument("--total", type=float)
    a = ap.parse_args()
    spec = json.load(open(a.events, encoding="utf-8"))
    print(json.dumps(render(spec, a.out, a.total), indent=1))


if __name__ == "__main__":
    main()
