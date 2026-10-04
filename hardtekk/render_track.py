# -*- coding: utf-8 -*-
"""Rendert HARTTEKK offline zu WAV - identisch zum Arrangement in build_flp.py.

FL Studio (Trial) kann keine Projekte oeffnen, daher eigenstaendiges Mischen:
- Jede Playlist-Position aus dem Arrangement wird mit dem jeweiligen Sample
  platziert (Sampler = One-Shot, volle Sample-Laenge)
- Pitch: key 60 = Originaltempo, sonst Resampling per 2^((key-60)/12)
- Velocity: lineare Lautstaerke-Skalierung
"""
import os
import struct
import wave

import numpy as np
import miniaudio

SR = 44100
BPM = 155.0
PPQ = 96
TICK_S = 60.0 / (BPM * PPQ)   # Sekunden pro Tick
BAR = PPQ * 4                 # 384 Ticks

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(HERE, "samples")
PACKS = r"C:\Program Files\Image-Line\FL Studio 2026\Data\Patches\Packs"
OUT = os.path.join(HERE, "HARTTEKK.wav")

CHANNELS = [
    PACKS + r"\Drums\Kicks\909 Kick.wav",
    PACKS + r"\Drums\Snares\909 Snare.wav",
    PACKS + r"\Drums\Hats\909 CH 1.wav",
    PACKS + r"\Drums\Hats\909 OH.wav",
    SAMPLES + r"\bass.wav",
    SAMPLES + r"\lead.wav",
    SAMPLES + r"\vox_achtung.wav",
    SAMPLES + r"\vox_hart.wav",
    SAMPLES + r"\vox_zaehlen.wav",
    SAMPLES + r"\vox_nacht.wav",
]
KICK, SNR, CH, OH, BASS, LEAD, VAC, VHT, VZL, VNT = range(10)


def load(path):
    dec = miniaudio.decode_file(
        path, output_format=miniaudio.SampleFormat.FLOAT32,
        nchannels=2, sample_rate=SR,
    )
    a = np.frombuffer(bytes(dec.samples), dtype=np.float32).reshape(-1, 2).copy()
    return a


def pitched(sample, key):
    if key == 60:
        return sample
    factor = 2.0 ** ((key - 60) / 12.0)
    n = int(len(sample) / factor)
    if n < 64:
        return sample
    x_old = np.arange(len(sample)) * factor
    x_new = np.arange(n)
    out = np.empty((n, 2), dtype=np.float32)
    out[:, 0] = np.interp(x_new, x_old, sample[:, 0])
    out[:, 1] = np.interp(x_new, x_old, sample[:, 1])
    return out


# (pos_ticks, channel, key, velocity) - wie in build_flp.py
def drum(ch, steps, vel=110, key=60):
    return [(s * 24, ch, key, vel) for s in steps]


PATTERNS = {}
PATTERNS[1] = drum(KICK, [0, 4, 8, 12], vel=118)
PATTERNS[2] = drum(SNR, [4, 12], vel=112)
PATTERNS[3] = [(s * 24, CH, 60, (100 if s % 4 == 0 else 72)) for s in range(0, 16, 2)]
PATTERNS[4] = drum(OH, [2, 6, 10, 14], vel=95)
PATTERNS[5] = drum(BASS, [2, 6, 10, 14], vel=112)
melody = [69] * 8 + [67] * 4 + [65] * 4 + [69] * 8 + [72] * 2 + [74] * 2 + [76] * 4
PATTERNS[6] = [(st * 24, LEAD, key, 112) for st, key in enumerate(melody)]
PATTERNS[7] = [(0, VHT, 60, 115)]
PATTERNS[8] = [(0, VZL, 60, 115)]
PATTERNS[9] = [(0, VAC, 60, 115)]
PATTERNS[10] = [(0, VNT, 60, 115)]
PATTERNS[11] = [(s * 24, SNR, 60, 60 + int(60 * s / 15)) for s in range(16)]

ITEMS = []
for b in range(0, 4):
    ITEMS += [(1, b), (3, b)]
ITEMS.append((9, 0))
for b in range(4, 8):
    ITEMS += [(1, b), (2, b), (3, b), (4, b), (5, b)]
for b in range(8, 12):
    ITEMS += [(1, b), (2, b), (3, b), (4, b), (5, b), (7, b)]
for b in (12, 13):
    ITEMS += [(1, b), (3, b), (11, b)]
ITEMS.append((8, 13))
for b in range(14, 22):
    ITEMS += [(1, b), (2, b), (3, b), (4, b), (5, b)]
for b in (14, 16, 18, 20):
    ITEMS.append((6, b))
ITEMS += [(10, 14), (7, 16), (10, 18), (7, 20)]
for b in range(22, 26):
    ITEMS.append((3, b))
ITEMS += [(10, 22), (7, 24), (5, 24), (5, 25)]
for b in range(26, 34):
    ITEMS += [(1, b), (2, b), (3, b), (4, b), (5, b)]
for b in (26, 28, 30, 32):
    ITEMS.append((6, b))
ITEMS += [(10, 26), (7, 28), (10, 30), (7, 32)]
ITEMS += [(1, 34), (2, 34), (1, 35)]

# ---------------------------------------------------------------- Mixdown
total_s = 36 * BAR * TICK_S + 3.0
mix = np.zeros((int(total_s * SR), 2), dtype=np.float32)

cache = {}
placed = 0
for pat_id, bar in ITEMS:
    for pos, ch, key, vel in PATTERNS[pat_id]:
        k = (ch, key)
        if k not in cache:
            cache[k] = pitched(load(CHANNELS[ch]), key)
        smp = cache[k]
        start = int((bar * BAR + pos) * TICK_S * SR)
        end = min(start + len(smp), len(mix))
        if start >= len(mix):
            continue
        gain = vel / 128.0
        mix[start:end] += smp[: end - start] * gain
        placed += 1

print("Platzierte Sample-Hits:", placed)

# Soft-Clip + Normalisierung
mix = np.tanh(mix * 1.1)
peak = np.max(np.abs(mix))
if peak > 0:
    mix *= 0.95 / peak
print("Peak vor Norm:", round(float(peak), 3))

pcm = (np.clip(mix, -1, 1) * 32767.0).astype(np.int16)
with wave.open(OUT, "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print("FERTIG:", OUT, round(len(mix) / SR, 1), "s")
