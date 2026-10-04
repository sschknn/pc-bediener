# -*- coding: utf-8 -*-
"""Erzeugt alle Audio-Dateien fuer den Hard-Tekk-Track:
- bass.wav  : Offbeat-Sawtooth-Bass (C2), synthetisiert mit numpy
- lead.wav  : Supersaw-Lead mit Distortion (C4)
- vox_*.wav : Deutsche Sprach-Vocals via edge-tts (de-DE-ConradNeural), konvertiert zu WAV
"""
import asyncio
import os
import sys
import wave

import numpy as np
import miniaudio
import edge_tts

SR = 44100
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")
os.makedirs(OUT, exist_ok=True)


def write_wav(path, data, sr=SR):
    data = np.clip(data, -1.0, 1.0)
    pcm = (data * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    print("OK", os.path.basename(path), len(data) / sr, "s")


def saw_additive(f0, t, harmonics=24):
    """Bandbegrenzter Saegezahn ueber additive Synthese."""
    y = np.zeros_like(t)
    for k in range(1, harmonics + 1):
        if k * f0 > SR / 2:
            break
        y += np.sin(2 * np.pi * f0 * k * t) / k
    return y * (2.0 / np.pi)


def make_bass():
    dur = 0.45
    t = np.arange(int(SR * dur)) / SR
    y = saw_additive(65.4064, t)  # C2
    env = np.exp(-t * 9.0)  # knackiger Decay
    env *= 1.0 - np.exp(-t * 800.0)  # 1.25ms Anti-Klick-Attack
    y = y * env
    y = np.tanh(y * 2.2)  # Saettigung
    write_wav(os.path.join(OUT, "bass.wav"), y * 0.9)


def make_lead():
    dur = 0.9
    t = np.arange(int(SR * dur)) / SR
    f0 = 261.6256  # C4
    y = np.zeros_like(t)
    for cents in (-14, -7, 0, 7, 14):  # Supersaw-Detune
        f = f0 * (2.0 ** (cents / 1200.0))
        y += saw_additive(f, t, harmonics=30)
    y /= 5.0
    env = np.ones_like(t)
    env *= 1.0 - np.exp(-t * 500.0)          # Attack
    env *= np.minimum(1.0, np.exp(-np.maximum(0, t - 0.55) * 14.0) + 0.6)  # Release
    y = y * env
    y = np.tanh(y * 2.8)  # Distortion
    write_wav(os.path.join(OUT, "lead.wav"), y * 0.85)


VOX = [
    # (Datei, Text, Rate, Pitch)
    ("vox_achtung",  "Achtung! Achtung! Hier kommt der Bass!", "+10%", "-4Hz"),
    ("vox_hart",     "Hart! Hart! Hart! Hart!",                "+22%", "-6Hz"),
    ("vox_zaehlen",  "Eins! Zwei! Drei! Vier!",                "+15%", "-4Hz"),
    ("vox_nacht",    "Wir drehen durch die Nacht!",            "+8%",  "-4Hz"),
]
VOICE = "de-DE-ConradNeural"


async def make_vox():
    for name, text, rate, pitch in VOX:
        mp3 = os.path.join(OUT, name + ".mp3")
        wav = os.path.join(OUT, name + ".wav")
        comm = edge_tts.Communicate(text, VOICE, rate=rate, pitch=pitch)
        await comm.save(mp3)
        # MP3 -> WAV 44.1kHz mono s16
        dec = miniaudio.decode_file(
            mp3,
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=1,
            sample_rate=SR,
        )
        with wave.open(wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(bytes(dec.samples))
        os.remove(mp3)
        print("OK", name + ".wav")


make_bass()
make_lead()
asyncio.run(make_vox())
print("FERTIG")
