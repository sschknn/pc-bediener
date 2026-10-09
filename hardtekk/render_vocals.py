"""Vocal-Stem fuer den Hardtekk-Track: gepresster, pitch-verschobener Hook.

Ansatz
------
Hardtekk lebt von einem "gestrippten" Schreie-Call - wie eine kaputte
Geraete-Stimme, distoort und leicht pitch-verschoben. Dazu passt keine
saubere Silben-Chop-Automation (die Onsets der One-Shots sind zu dicht
und schwer zuverlaessig zu isolieren), sondern:

* ein **Vocal-Hook** aus einem langen PHRASE/STORY-Sample, das auf die
  Taktlaenge gestreckt wird,
* **Pitch-Shift nach unten** (dunkler, bedrohlicher),
* **Drive** fuer den zerhackten Hardtekk-Charakter,
* im **Intro/Outro als dumpfer Filter-Pad**, im **Main als kurzer,
  lauter Call** auf der "und"-Position (typisch: Naehe zum Kick).

Das Ergebnis ist ein eigener Stem, der in der FL-Playlist als
"VOCALS"-Spur dazukommt und den Track rund macht.
"""
from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
from scipy import signal

PACK = Path(r"C:\Users\frank\Music\TKNVLT_Hardtekk")
P1 = PACK / "TKNVLT - Free Hardtechno Sample Pack Vol. 1"
VOC = P1 / "Vocals"
OUT = PACK / "render"
OUT.mkdir(parents=True, exist_ok=True)

SR = 44100
BPM = 150.0
BAR = 4 * 60.0 / BPM          # 1,6 s
BARS = 32
TOTAL = BAR * BARS
SIXTEENTH = 60.0 / BPM / 4.0

# reuse I/O aus dem Renderer
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location(
    "rht", Path(__file__).with_name("render_hardtekk.py"))
rht = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(rht)
read_wav = rht.read_wav
resample = rht.resample
to_mono = rht.to_mono
lowpass = rht.lowpass
highpass = rht.highpass
saturate = rht.saturate
fade = rht.fade


def time_stretch(x: float, factor: float) -> np.ndarray:
    """Aendert die Laenge, ohne die Tonhoehe (Phase-Vocoder-naeher)."""
    if abs(factor - 1.0) < 1e-3:
        return x
    # OLA mit grossem Hop und Ueberlappung: guenstiger als ein voller
    # Vocoder und fuer einen groove-lastigen Vocal völlig ausreichend.
    frame = 1024
    hop_out = max(1, int(frame / factor))
    hop_in = frame
    win = np.hanning(frame * 2)[:frame]
    n_out = int(len(x) / factor)
    out = np.zeros(n_out + frame, dtype=np.float32)
    wsum = np.zeros(n_out + frame, dtype=np.float32)
    pos = 0
    for i in range(0, len(x) - frame, hop_in):
        seg = x[i:i + frame] * win
        o = pos
        out[o:o + frame] += seg
        wsum[o:o + frame] += win
        pos += hop_out
    nz = wsum > 1e-6
    out[nz] /= wsum[nz]
    return out[:n_out]


def pitch_shift(x: np.ndarray, semis: float) -> np.ndarray:
    """Pitch-Shift ueber Zeit-Stretch + Resampling."""
    if abs(semis) < 1e-3:
        return x
    factor = 2.0 ** (semis / 12.0)
    y = time_stretch(x, factor)
    # Resample => Tonhoehe aendert sich, Laenge nicht (Rueckrechnung)
    n_out = len(y)
    y2 = resample(y, int(round(SR * factor)), SR)
    if len(y2) < n_out:
        y2 = np.pad(y2, (0, n_out - len(y2)))
    return y2[:n_out]


def loop_to_bars(x: np.ndarray, bars: float) -> np.ndarray:
    need = int(BAR * bars * SR)
    if len(x) >= need:
        return x[:need]
    reps = int(math.ceil(need / max(1, len(x))))
    return np.tile(x, reps)[:need]


def place(buf, src, t, gain=1.0):
    i = int(round(t * SR))
    if i < 0 or gain <= 0:
        return
    n = min(len(src), len(buf) - i)
    if n > 0:
        buf[i:i + n] += src[:n] * gain


def load_voc(name: str) -> np.ndarray:
    x, rate = read_wav(VOC / name)
    return resample(to_mono(x), rate)


def build() -> Path:
    print("lade Vocals ...")
    # Lange Phrasen eignen sich besser als Stab als die Einzelwoerter.
    phrases = sorted(VOC.glob("TKNVLT_FREE_HT_VOX_PHRASE_*.wav"))
    stories = sorted(VOC.glob("TKNVLT_FREE_HT_STORY_*.wav"))
    hook_src = read_wav(phrases[1])[0] if phrases else read_wav(stories[0])[0]
    hook_src = resample(to_mono(hook_src), rht.read_wav(phrases[1] if phrases else stories[0])[1])

    # Call: 2 Takte, pitch -3 Halbtoene, stark geschaerft
    call = pitch_shift(loop_to_bars(hook_src, 2), -3.0)
    call = highpass(call, 110.0)
    call = saturate(call, 3.4, 0.75)
    call = call / (np.max(np.abs(call)) + 1e-9)

    # Pad: dieselbe Phrase tief und dumpf fuer Intro/Outro
    pad = pitch_shift(loop_to_bars(hook_src, 4), -7.0)
    pad = lowpass(pad, 900.0)
    pad = pad / (np.max(np.abs(pad)) + 1e-9)

    n = int(TOTAL * SR) + SR
    vox = np.zeros(n, dtype=np.float32)

    # --- Pad im Intro (Takte 1-4) und als Ueberleitung vor dem Drop -----
    for bar, g in [(0, 0.5), (1, 0.55), (2, 0.55), (3, 0.5),
                   (12, 0.5), (13, 0.55), (14, 0.6), (15, 0.7)]:
        place(vox, loop_to_bars(pad, 1), bar * BAR, g)

    # --- Call im Main (Takt 5-12, 17-28) auf den "&"-Positionen --------
    for bar in range(5, 13):
        for step in (2, 10):                    # leichte Offbeat-Bewegung
            place(vox, call, bar * BAR + step * SIXTEENTH, 0.55)
    for bar in range(17, 29):
        for step in (2, 10):
            place(vox, call, bar * BAR + step * SIXTEENTH, 0.72)

    # --- ein langer Call auf dem Drop (Takt 17) --------------------------
    place(vox, call, 16 * BAR, 0.95)
    # --- Outro-Ausklang ---------------------------------------------------
    for bar in range(29, 32):
        place(vox, loop_to_bars(pad, 1), bar * BAR, 0.4 * (32 - bar) / 3.0)

    vox = vox[:int(TOTAL * SR)]
    fade(vox, 0.02, 0.9)

    p = rht.write_wav(OUT / "hardtekk_vocals.wav", vox, 0.9)
    x, rate = read_wav(p)
    print(f"  {p.name} {len(x)/rate:.2f}s peak {np.max(np.abs(x)):.3f} "
          f"rms {20*math.log10(max(float(np.sqrt(np.mean(x**2))),1e-9)):.2f} dBFS")
    return p


if __name__ == "__main__":
    build()