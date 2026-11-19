#!/usr/bin/env python3
"""Synthesise original drift-phonk style loops (808 bass, cowbell, clap, hats, dark pad). 100% ours: no copyright, no Content ID.
  make_phonk.py  -> music/phonk_*.mp3 + music/library.json"""
import json, os, subprocess, sys
import numpy as np
SR = 44100
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); OUT = os.path.join(ROOT, "music")
rng = np.random.default_rng(7)

def env(n, a, d): t = np.arange(n) / SR; return np.minimum(t / max(a, 1e-4), 1) * np.exp(-t / d)
def kick(): n = int(.45 * SR); t = np.arange(n) / SR; f = 38 + 95 * np.exp(-t * 22); return np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, .001, .14) * 1.2
def clap():
    n = int(.22 * SR); x = rng.standard_normal(n); x = np.convolve(x, np.ones(6) / 6, mode="same") * -1 + x * .4
    return x * (env(n, .001, .05) + .6 * np.roll(env(n, .001, .03), int(.012 * SR))) * .45
def hat(open_=False): n = int((.2 if open_ else .05) * SR); x = rng.standard_normal(n); x = x - np.convolve(x, np.ones(4) / 4, mode="same"); return x * env(n, .0005, .09 if open_ else .015) * .25
def cowbell(f, d=.16):
    n = int(.35 * SR); t = np.arange(n) / SR
    s = np.sign(np.sin(2 * np.pi * f * t)) + np.sign(np.sin(2 * np.pi * f * 1.504 * t))
    s = np.convolve(s, np.ones(3) / 3, mode="same"); return s * env(n, .001, d) * .22
def bass(f, dur, drive=2.2):
    n = int(dur * SR); t = np.arange(n) / SR; ff = f * (1 + .35 * np.exp(-t * 18)); x = np.sin(2 * np.pi * np.cumsum(ff) / SR)
    x = np.tanh(x * drive) * np.minimum(1, (dur - t) / .03) * np.minimum(t / .004, 1); return x * .75
def pad(freqs, dur):
    n = int(dur * SR); t = np.arange(n) / SR; x = np.zeros(n)
    for f in freqs:
        for det in (-.004, .004): x += (2 * ((t * f * (1 + det)) % 1) - 1) * .1
    lp = np.convolve(x, np.ones(40) / 40, mode="same"); return lp * (.6 + .4 * np.sin(2 * np.pi * .25 * t)) * .5

def build(name, bpm, root_hz, scale, bars=None, energy="high", seed=0):
    bars = bars or int(-(-46 // (240 / bpm)))
    global rng; rng = np.random.default_rng(seed or bpm)
    step = 60 / bpm / 4; n = int(bars * 16 * step * SR); mix = np.zeros(n)
    def put(x, pos, g=1.0):
        i = int(pos * SR); j = min(i + len(x), n)
        if i < n: mix[i:j] += x[:j - i] * g
    notes = [root_hz * 2 ** (s / 12) for s in scale]
    kp = [0, 6, 10] if energy == "mid" else [0, 3, 6, 10, 13]
    cow = [0, 3, 6, 8, 11, 14] if energy == "high" else [0, 6, 10]
    for b in range(bars):
        o = b * 16 * step
        chord = [root_hz * 4, root_hz * 4 * 2 ** (3 / 12), root_hz * 4 * 2 ** (7 / 12)]
        mix[int(o * SR):int(o * SR) + int(16 * step * SR)] += pad(chord, 16 * step)[:min(int(16 * step * SR), n - int(o * SR))] * (.5 if energy == "mid" else .7)
        for i, s in enumerate(range(16)):
            t0 = o + s * step
            if s in kp:
                put(kick(), t0, 1.0); put(bass(notes[(b + i) % len(notes)] / (2 if notes[(b + i) % len(notes)] > 70 else 1), step * 2.6), t0, .9)
            if s in (4, 12): put(clap(), t0, 1.0)
            if s % 2 == 0 or (energy == "high" and b % 4 == 3 and s >= 12): put(hat(s == 14), t0, .8)
            if s in cow: put(cowbell([560, 840, 700, 630][(s + b) % 4] * (1.06 if b % 4 == 3 else 1)), t0, 1.0)
    mix = np.tanh(mix * (1.6 if energy == "high" else 1.2)); mix = mix / np.abs(mix).max() * .85
    st = np.stack([mix, np.roll(mix, int(.004 * SR))], 1)                      # tiny stereo widening
    pcm = (st * 32767).astype("<i2").tobytes(); raw = os.path.join(OUT, name + ".raw")
    open(raw, "wb").write(pcm)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(SR), "-ac", "2", "-i", raw, "-af", "afade=t=in:d=0.05,afade=t=out:st=%.2f:d=0.4" % (n / SR - .4), "-b:a", "192k", os.path.join(OUT, name + ".mp3")]); os.remove(raw)
    return {"file": name + ".mp3", "bpm": bpm, "energy": energy, "seconds": round(n / SR, 1), "style": "drift phonk (synthesised)", "license": "original, generated locally - no claims"}

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True); lib = []
    minor = [0, 0, 3, 0, 7, 5, 3, 0]        # root-heavy minor line
    lib.append(build("phonk_drift_night", 140, 43.65, minor, energy="high", seed=1))      # F1 808
    lib.append(build("phonk_street_heat", 150, 49.0, [0, 3, 0, 5, 7, 3, 0, 10], energy="high", seed=2))
    lib.append(build("phonk_dark_cruise", 130, 41.2, [0, 0, 5, 3, 0, 7, 3, 0], energy="mid", seed=3))
    lib.append(build("phonk_slow_menace", 120, 36.7, [0, 3, 0, 0, 7, 3, 5, 0], energy="mid", seed=4))
    json.dump(lib, open(os.path.join(OUT, "library.json"), "w"), indent=1); print(json.dumps(lib, indent=1))
