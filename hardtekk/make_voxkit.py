# -*- coding: utf-8 -*-
"""make_voxkit.py - erzeugt eine grosse Original-Vocal-Bibliothek fuer FL Studio.

Alles rein synthetisch: deutsche Neural-TTS-Stimmen (edge-tts), Formantsynthese
und ein eigener Phase-Vocoder fuer Transposition/Chops. Keine Fremdaufnahmen,
keine Downloads, keine Nutzungsrechte Dritter.

Ordner unter hardtekk/voxkit/:
    dry/          trockene Assets (TTS-Rohsignal, gefiltert, normalisiert)
    wet/          dieselben Assets mit Hall
    _tts_cache/   MP3-Zwischenspeicher (damit Reruns kein Netz brauchen)
    MANIFEST.json / MANIFEST.csv / QA.csv

Aufruf:
    python make_voxkit.py            # komplettes Kit
    python make_voxkit.py --smoke    # nur DSP-Kette an 1 Beispiel pruefen
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import math
import os
import sys
import time

import numpy as np
import scipy.signal as sps
from scipy.signal import fftconvolve

import edge_tts
import miniaudio
import soundfile as sf

# --------------------------------------------------------------------------- #
# Konstanten
# --------------------------------------------------------------------------- #
SR = 44100
BPM = 160.0                      # Projekt-Tempo, ueber --bpm setzbar
BEAT = 60.0 / BPM                # 0.375 s bei 160
GRID_16 = BEAT / 4.0
GRID_8 = BEAT / 2.0
GRID_4 = BEAT


def set_bpm(bpm: float) -> None:
    """Rastergroessen an das Projekt-Tempo anpassen.

    Wichtig fuer die Nutzbarkeit: Chop-Laengen sind auf 16tel/8tel gerastert.
    Ein Chop, der fuer 160 BPM gebaut wurde, passt in ein 130-BPM-Projekt
    um 23 % nicht. Darum wird das Kit immer fuer das Tempo erzeugt, in dem
    es tatsaechlich gelandet ist.
    """
    global BPM, BEAT, GRID_16, GRID_8, GRID_4
    BPM = float(bpm)
    BEAT = 60.0 / BPM
    GRID_16 = BEAT / 4.0
    GRID_8 = BEAT / 2.0
    GRID_4 = BEAT

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, "voxkit")
DRY = os.path.join(KIT, "dry")
WET = os.path.join(KIT, "wet")
CACHE = os.path.join(KIT, "_tts_cache")

rng = np.random.default_rng(20261004)
MANIFEST: list[dict] = []

MALE = "de-DE-ConradNeural"
MALE2 = "de-DE-KillianNeural"
FEMALE = "de-DE-KatjaNeural"
FEMALE2 = "de-DE-AmalaNeural"

VOICE_TAG = {
    MALE: "conrad", MALE2: "killian", FEMALE: "katja", FEMALE2: "amala",
}

# --------------------------------------------------------------------------- #
# Eigene deutsche Texte (Hard-Tekk-Vibe, selbst geschrieben)
# --------------------------------------------------------------------------- #
PHRASES = [
    ("nacht", "Die Nacht gehoert uns, die Strasse gehoert uns."),
    ("kein_zurueck", "Kein Zurueck. Wir pushen weiter, immer weiter."),
    ("beton", "Beton auf den Beat, und der Beat geht nie aus."),
    ("feuer", "Wir sind das Feuer, das die kalte Stadt verbrennt."),
    ("null_hundert", "Von null auf hundert, bevor der erste Takt vorbei ist."),
    ("beats_worte", "Harte Beats, weiche Worte, aber ich bleibe hart."),
    ("such", "Such das Feuer, such die Nacht, such den Sound."),
    ("herzschlag", "Mein Herz schlaegt im Takt, immer lauter, immer gut."),
    ("stadt_wach", "Die Stadt schlaeft, wir nicht, wir sind die Wache."),
    ("noch_einmal", "Noch einmal, noch einmal, gib mir noch einmal."),
]

ADLIBS = [
    ("hey", "Hey!"), ("oh", "Oh!"), ("yeah", "Yeah!"), ("uff", "Uff!"),
    ("ha", "Ha!"), ("ja", "Ja!"), ("wow", "Wow!"), ("gonna", "Goen dir!"),
    ("come_on", "Come on!"), ("lets_go", "Letz go!"),
    ("hoho", "Hoeho!"), ("na_klar", "Na klar!"),
    ("yeah_yeah", "Yeah, yeah!"), ("oh_oh", "Oh, oh, oh!"),
    ("achtung", "Achtung!"), ("skrrt", "Skrrt!"),
    ("einmal", "Einmal! Einmal! Einmal!"), ("hooh", "Hoooh!"),
]

def slug(text: str) -> str:
    s = text.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), ("-", "_")):
        s = s.replace(a, b)
    return "".join(c if c.isalnum() or c == "_" else "_" for c in s).strip("_")


# --------------------------------------------------------------------------- #
# WAV-I/O
# --------------------------------------------------------------------------- #
def write_wav(path: str, y: np.ndarray, peak: float = 0.89) -> float:
    y = np.nan_to_num(np.asarray(y, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0)
    m = float(np.max(np.abs(y))) if y.size else 0.0
    if m > 1e-9:
        y = y * (peak / m)
    sf.write(path, np.clip(y, -1.0, 1.0), SR, subtype="PCM_16")
    dur = y.size / SR
    print(f"  OK {os.path.relpath(path, KIT):52s} {dur:6.3f}s  peak {m:.3f}")
    return dur


def record(category: str, name: str, path: str, dur: float, **meta) -> None:
    MANIFEST.append({
        "category": category, "name": name,
        "path": os.path.relpath(path, KIT).replace("\\", "/"),
        "duration_s": round(dur, 3),
        "beat160": round(dur / BEAT, 3),
        **meta,
    })


# --------------------------------------------------------------------------- #
# DSP-Bausteine
# --------------------------------------------------------------------------- #
def hp(y: np.ndarray, fc: float = 70.0, order: int = 2) -> np.ndarray:
    sos = sps.butter(order, fc / (SR / 2), btype="highpass", output="sos")
    return sps.sosfiltfilt(sos, y)


def lp(y: np.ndarray, fc: float = 17000.0, order: int = 2) -> np.ndarray:
    sos = sps.butter(order, min(fc, SR * 0.49) / (SR / 2), btype="lowpass", output="sos")
    return sps.sosfiltfilt(sos, y)


def compress(y: np.ndarray, thresh_db: float = -18.0, ratio: float = 3.0,
             atk_ms: float = 4.0, rel_ms: float = 90.0) -> np.ndarray:
    """Schneller Einpol-Kompressor (lfilter statt Python-Loop)."""
    env = np.abs(y)
    a_att = math.exp(-1.0 / max(1e-6, SR * atk_ms / 1000.0))
    a_rel = math.exp(-1.0 / max(1e-6, SR * rel_ms / 1000.0))
    # zweistufig: schnelle Attacke, langsame Release
    e1 = sps.lfilter([1 - a_att], [1, -a_att], env)
    e2 = sps.lfilter([1 - a_rel], [1, -a_rel], e1)
    thr = 10.0 ** (thresh_db / 20.0)
    over = np.maximum(e2 / thr, 1e-9)
    gain = np.where(e2 > thr, over ** (1.0 / ratio - 1.0), 1.0)
    return y * gain


def saturate(y: np.ndarray, drive: float = 1.8) -> np.ndarray:
    d = max(1.0001, drive)
    return np.tanh(y * d) / math.tanh(d)


def fit_len(y: np.ndarray, n: int) -> np.ndarray:
    if y.size == n:
        return y
    if y.size > n:
        return y[:n].copy()
    return np.pad(y, (0, n - y.size))


def fades(y: np.ndarray, ms_in: float = 2.0, ms_out: float = 10.0) -> np.ndarray:
    y = y.copy()
    n_in = min(int(SR * ms_in / 1000.0), y.size // 2)
    n_out = min(int(SR * ms_out / 1000.0), y.size // 2)
    if n_in > 0:
        y[:n_in] *= np.linspace(0.0, 1.0, n_in)
    if n_out > 0:
        y[-n_out:] *= np.linspace(1.0, 0.0, n_out)
    return y


def _pick_peaks(m: np.ndarray, thresh_rel: float = 0.12) -> np.ndarray:
    if m.size < 3:
        return np.array([int(np.argmax(m))]) if m.size else np.array([], dtype=int)
    idx = np.where((m[1:-1] > m[:-2]) & (m[1:-1] >= m[2:]) &
                   (m[1:-1] > thresh_rel * m.max()))[0] + 1
    if idx.size == 0:
        idx = np.array([int(np.argmax(m))])
    return idx


def pv_stretch(y: np.ndarray, rate: float, n_fft: int = 2048, hop_a: int = 256) -> np.ndarray:
    """Phase-Vocoder-Time-Stretch ohne Tonhoehen-Fehler.

    ``rate`` ist der Laengenfaktor (rate > 1 = laenger); dafuer wird der
    Synthese-Hop auf ``hop_a * rate`` gesetzt - ein Phasen-Recycling bei
    fixem Hop waere ja nur Resampling.

    Wichtig: Der Phasenversatz wird immer zwischen zwei *Analyse*-Frames
    bestimmt (erwarteter Schritt ``omega_bin * hop_a``, Normierung
    ``delta / hop_a``). Waere stattdessen der Synthese-Hop im Spiel, rastet
    die Tonhoehe auf FFT-Bins - im Test lag ein 140-Hz-Signal exakt
    zwischen zwei Bins und sprang auf 150.7 Hz (+128 Cent).
    Identity Phase Locking haelt den Klang transponierbarer Saeulen.
    """
    if abs(rate - 1.0) < 1e-9 or y.size < n_fft:
        return y.copy()
    hop_s = max(1, int(round(hop_a * rate)))
    if hop_s >= n_fft:                      # COLA-Sicherheit: Fenster vergroessern
        n_fft = 1 << int(math.ceil(math.log2(hop_s * 2)))
        if n_fft > y.size // 2:
            return resample_based_stretch(y, rate)
    win = sps.get_window("hann", n_fft, fftbins=True)
    f, t, Z = sps.stft(y, fs=SR, window=win, nperseg=n_fft,
                       noverlap=n_fft - hop_a, boundary="zeros", padded=True)
    mag = np.abs(Z)
    ph = np.angle(Z)
    nb, nf = mag.shape
    omega_bin = 2.0 * np.pi * np.arange(nb)[:, None] / n_fft
    adv_obs = omega_bin * hop_a             # erwarteter Analyse-Schritt
    adv_syn = omega_bin * hop_s             # Synthese-Schritt
    phi_prev = ph[:, 0:1]
    acc = ph[:, 0:1].copy()                 # Ausgabephase
    out = np.zeros_like(Z)
    out[:, 0] = Z[:, 0]
    for k in range(1, nf):
        delta = np.mod(ph[:, k:k + 1] - phi_prev - adv_obs + np.pi, 2 * np.pi) - np.pi
        omega_est = omega_bin + delta / hop_a        # rad pro Sample
        acc = acc + omega_est * hop_s                # Ausgabephase fortschreiben
        syn = acc[:, 0].copy()
        pk = _pick_peaks(mag[:, k])
        for j, p in enumerate(pk):
            lo = 0 if j == 0 else (int(pk[j - 1]) + int(p)) // 2 + 1
            hi = nb - 1 if j == len(pk) - 1 else (int(p) + int(pk[j + 1])) // 2
            syn[lo:hi + 1] = acc[int(p), 0] + (ph[lo:hi + 1, k] - ph[int(p), k])
        out[:, k] = mag[:, k] * np.exp(1j * syn)
        phi_prev = ph[:, k:k + 1]
    _, x = sps.istft(out, fs=SR, window=win, nperseg=n_fft,
                     noverlap=n_fft - hop_s, boundary=True)
    return x


def resample_based_stretch(y: np.ndarray, rate: float) -> np.ndarray:
    """Notsicherung fuer extreme Dehnungsfaktoren (Tonhoehe wandert mit)."""
    up = 1000
    down = max(1, int(round(1000 / max(rate, 1e-6))))
    return sps.resample_poly(y, up, down)


def pitch_shift(y: np.ndarray, semitones: float) -> np.ndarray:
    """Tonhoehe aendern, Laenge bleibt (Formanten wandern mit - wie bei Hardware)."""
    if abs(semitones) < 1e-9:
        return y.copy()
    rate = 2.0 ** (semitones / 12.0)
    stretched = pv_stretch(y, rate)
    up = 1000
    down = max(1, int(round(1000 * rate)))
    shifted = sps.resample_poly(stretched, up, down)
    return fit_len(shifted, y.size)


# --- Hall ------------------------------------------------------------------ #
_IR_CACHE: dict[tuple, np.ndarray] = {}


def make_ir(dur: float = 1.5, decay: float = 3.4, seed: int = 7) -> np.ndarray:
    key = (dur, decay, seed)
    if key in _IR_CACHE:
        return _IR_CACHE[key]
    r = np.random.default_rng(seed)
    n = max(64, int(SR * dur))
    t = np.arange(n) / SR
    ir = r.normal(size=n) * np.exp(-t * decay)
    for d_ms, g in ((11, 0.55), (19, 0.42), (29, 0.34), (43, 0.26), (67, 0.2)):
        d = int(SR * d_ms / 1000.0)
        if d < n:
            ir[d] += g
    ir = lp(ir, 6200.0)
    ir = hp(ir, 190.0)
    ir /= max(1e-9, float(np.sqrt(np.sum(ir ** 2))))
    _IR_CACHE[key] = ir
    return ir


def reverb(y: np.ndarray, mix: float = 0.28, dur: float = 1.5,
           decay: float = 3.4, seed: int = 7) -> np.ndarray:
    ir = make_ir(dur, decay, seed)
    wet = fftconvolve(y, ir, mode="full")[:y.size]
    return y * (1.0 - mix) + wet * mix


# --- Formanten-Pads -------------------------------------------------------- #
VOWELS = {
    # (F1, F2, F3) , (B1, B2, B3) in Hz
    "a": ((730, 1090, 2440), (80, 90, 120)),
    "e": ((530, 1840, 2480), (70, 100, 120)),
    "i": ((270, 2290, 3010), (60, 100, 140)),
    "o": ((570, 840, 2410), (70, 90, 120)),
    "u": ((300, 870, 2240), (50, 80, 120)),
}


def vowel_env(freq: np.ndarray | float, vowel: str) -> np.ndarray:
    f = np.atleast_1d(np.asarray(freq, dtype=np.float64))
    fts, bws = VOWELS[vowel]
    env = np.zeros_like(f)
    for fc, bw in zip(fts, bws):
        env += 1.0 / (1.0 + ((f - fc) / bw) ** 2)
    return env


def make_loopable(y: np.ndarray, xfade: float = 1.4) -> np.ndarray:
    """Tail an den Anfang zurueckfalten -> nahtlos wiederholbar, Laenge bleibt."""
    n_x = min(int(SR * xfade), y.size // 3)
    if n_x < 64:
        return y
    head = y[:n_x].copy()
    tail = y[-n_x:].copy()
    ramp = np.linspace(0.0, 1.0, n_x)
    blend = tail * ramp + head * (1.0 - ramp)
    return np.concatenate([blend, y[n_x:]])


def vowel_pad(dur: float, f0: float, vowel: str, vib_hz: float = 4.6,
              vib_cents: float = 16.0, breath: float = 0.05,
              harmonics: int = 48, atk: float = 0.7, rel: float = 1.3) -> np.ndarray:
    n = int(SR * dur)
    t = np.arange(n) / SR
    vib = 1.0 + (vib_cents / 1200.0) * np.sin(2 * np.pi * vib_hz * t + 0.7)
    y = np.zeros(n)
    for k in range(1, harmonics + 1):
        if k * f0 > SR * 0.45:
            break
        amp = float(vowel_env(k * f0, vowel)[0]) / (k ** 0.55)
        if amp < 1e-3:
            continue
        y += amp * np.sin(2 * np.pi * (f0 * k) * vib * t + rng.uniform(0, 2 * np.pi))
    m = float(np.max(np.abs(y)))
    if m > 1e-9:
        y /= m
    nz = lp(rng.normal(size=n), 2800.0)
    nz /= max(1e-9, float(np.max(np.abs(nz))))
    y = y + breath * nz
    # Chor (drei leicht verstimmte Kopien)
    ch = np.zeros(n)
    for d_ms, det in ((11, -0.16), (19, 0.13), (28, 0.05)):
        d = int(SR * d_ms / 1000.0)
        shifted = np.roll(pitch_shift(y, det * 2.0), d)
        ch += shifted[:n]
    y = y * 0.5 + ch / 6.0
    env = np.ones(n)
    env *= np.clip(t / max(1e-6, atk), 0.0, 1.0)
    env *= np.clip((dur - t) / max(1e-6, rel), 0.0, 1.0)
    y = fades(y * env, 40.0, 260.0)
    return make_loopable(y, min(1.4, dur / 4.0))


# --- Chop-Extraktion ------------------------------------------------------ #
def rms_env(y: np.ndarray, hop: int = 128, win: int = 256) -> np.ndarray:
    n = max(1, y.size // hop)
    out = np.zeros(n)
    for i in range(n):
        seg = y[i * hop:i * hop + win]
        out[i] = float(np.sqrt(np.mean(seg ** 2))) if seg.size else 0.0
    return out


def chop_segments(y: np.ndarray, min_len: float | None = None,
                  max_len: float | None = None) -> list[tuple[int, int, int]]:
    """Schneidet an natuerlichen Pausen und quantisiert auf 16tel/8tel/4tel.

    Rueckgabe: Liste aus (start, ende, n16) - ``n16`` ist die Laenge in
    Sechzehnteln, damit Dateiname und tatsaechliche Laenge uebereinstimmen.
    Ein blosses "nahe an der Rasterlinie snappen" liess die meisten Chops
    auf Natuerlaengen liegen (nur 22 von 75 exakt im Raster) - fuer eine
    Beat-Kit unbrauchbar, weil sie dann im Arrangement zerschieben.
    """
    if min_len is None:
        min_len = GRID_16 * 0.55
    if max_len is None:
        max_len = GRID_4 * 1.2
    hop = 128
    env = rms_env(y, hop)
    if env.max() < 1e-6:
        return []
    thresh = env.max() * 0.085
    voiced = env > thresh
    # Frame -> Sample
    segs: list[tuple[int, int]] = []
    start = None
    for i, v in enumerate(voiced):
        if v and start is None:
            start = i
        elif not v and start is not None:
            segs.append((start * hop, i * hop))
            start = None
    if start is not None:
        segs.append((start * hop, y.size))

    out: list[tuple[int, int, int]] = []
    for s, e in segs:
        seg = y[s:e]
        if seg.size < SR * min_len:
            continue
        pk = float(np.max(np.abs(seg)))
        if pk < env.max() * 0.06:
            continue
        # Praeziser anschneiden (Schwellwert 0.6% vom Segmentpeak)
        t = pk * 0.006
        nz = np.where(np.abs(seg) > t)[0]
        if nz.size == 0:
            continue
        s2 = s + int(nz[0])
        e2 = s + int(nz[-1]) + 1
        if s2 >= e2 or s2 < 0 or e2 > y.size:
            continue
        # --- harte Raster-Quantisierung: nur 16tel / 8tel / 4tel ---
        L = (e2 - s2) / SR
        n16 = 1 if L < GRID_16 * 1.5 else (2 if L < GRID_8 * 1.5 else 4)
        # naechster gesprochener Anfang nach dem Segment
        nxt = y.size
        later = np.where(voiced[min(len(voiced) - 1, int(e2 // hop) + 1):])[0]
        if later.size:
            nxt = int((min(len(voiced) - 1, int(e2 // hop) + 1) + later[0]) * hop)
        step = int(round(GRID_16 * SR))
        while n16 > 1 and s2 + n16 * step > nxt:
            n16 //= 2                      # naechstkleinere Rastergroesse passt
        target = min(s2 + n16 * step, y.size)
        if target <= s2:
            continue
        e2 = int(target)
        dur = (e2 - s2) / SR
        if dur < min_len or dur > max_len:
            continue
        out.append((s2, e2, n16))
    return out


def beat_tag(n16: int) -> str:
    return {1: "16th", 2: "8th", 4: "4th"}.get(int(n16), f"{n16}16")


def st_tag(st: float) -> str:
    s = int(round(st))
    return f"p{s}" if s > 0 else (f"m{-s}" if s < 0 else "0")


# --------------------------------------------------------------------------- #
# TTS
# --------------------------------------------------------------------------- #
async def tts_mp3(text: str, voice: str, rate: str = "+0%", pitch: str = "+0Hz") -> str:
    os.makedirs(CACHE, exist_ok=True)
    key = hashlib.md5(f"{text}|{voice}|{rate}|{pitch}".encode("utf-8")).hexdigest()[:12]
    mp3 = os.path.join(CACHE, key + ".mp3")
    if os.path.exists(mp3) and os.path.getsize(mp3) > 800:
        return mp3
    last = None
    for attempt in range(4):
        try:
            await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(mp3)
            if os.path.getsize(mp3) > 800:
                return mp3
        except Exception as exc:            # Netz flaps: mehrfach versuchen
            last = exc
            await asyncio.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"TTS fehlgeschlagen ({voice}): {text[:50]} -> {last}")


def decode_mp3(path: str) -> np.ndarray:
    dec = miniaudio.decode_file(path, output_format=miniaudio.SampleFormat.SIGNED16,
                                nchannels=1, sample_rate=SR)
    raw = bytes(dec.samples)
    return np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0


def vocal_chain(y: np.ndarray, drive: float = 1.25, air: bool = True) -> np.ndarray:
    """Einheitliche Vocal-Bearbeitung: HPF, Kompression, Sättigung, Air."""
    y = hp(y, 75.0)
    y = compress(y, thresh_db=-20.0, ratio=3.0)
    y = saturate(y, drive)
    if air:
        # "Air"-Band 8-14 kHz anheben (simpler Shelving-Filter)
        b = np.array([1.0, -1.92, 0.912])
        a = np.array([1.0, -1.70, 0.82])
        y = sps.lfilter(b, a, y) * 1.06
    y = lp(y, 18500.0)
    return y


# --------------------------------------------------------------------------- #
# Bausteine des Kits
# --------------------------------------------------------------------------- #
async def build_phrase(raw_items: list[tuple], only_dry_offsets: set[float] | None = None) -> list[dict]:
    """Phrasen: trocken + transponiert, mit Hallvariante."""
    made: list[dict] = []
    tasks = []
    for (name, text), voice in raw_items:
        tasks.append((name, text, voice))
    mp3s = {}
    for name, text, voice in tasks:
        mp3s[(name, voice)] = await tts_mp3(text, voice, rate="+6%", pitch="-2Hz")

    for name, text, voice in tasks:
        tag = VOICE_TAG[voice]
        base = vocal_chain(decode_mp3(mp3s[(name, voice)]))
        base = fades(base, 6.0, 30.0)
        offs = [0.0]
        if only_dry_offsets:
            offs = sorted(only_dry_offsets)
        for off in offs:
            y = base if abs(off) < 1e-9 else pitch_shift(base, off)
            y = fades(y, 3.0, 18.0)
            fn = f"phrase_{name}_{tag}_{st_tag(off)}st.wav"
            p = os.path.join(DRY, fn)
            dur = write_wav(p, y)
            record("phrase", os.path.basename(p), p, dur,
                   text=text, voice=tag, semitones=int(off), wet=False)
            made.append({"base": base, "path": p, "name": name, "voice": tag,
                         "off": off, "dur": dur})
            if abs(off) < 1e-9:
                wp = os.path.join(WET, fn.replace(".wav", "_wet.wav"))
                wy = fades(reverb(y, mix=0.30), 3.0, 20.0)
                wdur = write_wav(wp, wy)
                record("phrase", os.path.basename(wp), wp, wdur,
                       text=text, voice=tag, semitones=0, wet=True)
    return made


def build_chops(phrase_made: list[dict], max_files: int = 70) -> None:
    offsets = [-5, -3, 0, 3, 5, 7, -12, 10]
    n = 0
    for i, item in enumerate(phrase_made):
        base = item["base"]
        segs = chop_segments(base)
        if not segs:
            continue
        for j, (s, e, n16) in enumerate(segs):
            if n >= max_files:
                return
            seg = base[s:e]
            seg = fades(seg, 1.5, 9.0)
            st = offsets[(i + j) % len(offsets)]   # Tonhoehenleiter pro Chop
            y = seg if abs(st) < 1e-9 else pitch_shift(seg, st)
            y = compress(y, thresh_db=-16.0, ratio=4.0)
            y = saturate(y, 1.4)
            tag = beat_tag(n16)
            fn = f"chop_{item['name']}_{item['voice']}_{j:02d}_{tag}_{st_tag(st)}st.wav"
            p = os.path.join(DRY, fn)
            dur = write_wav(p, y, peak=0.92)
            record("chop", os.path.basename(p), p, dur,
                   source=item["name"], voice=item["voice"], semitones=st,
                   grid=tag, sixteenths=n16, wet=False)
            n += 1
            if n % 12 == 0:
                wp = os.path.join(WET, fn.replace(".wav", "_wet.wav"))
                wy = fades(reverb(y, mix=0.34, dur=1.1, decay=4.2, seed=11 + n), 1.5, 12.0)
                wdur = write_wav(wp, wy, peak=0.86)
                record("chop", os.path.basename(wp), wp, wdur,
                       source=item["name"], voice=item["voice"], semitones=st,
                       grid=tag, sixteenths=n16, wet=True)


def build_stacks(phrase_made: list[dict]) -> None:
    """Hook-Stacks: Trocken + Oktave tiefe + Hall, als ein File sofort lauffaehig."""
    for i, item in enumerate(phrase_made):
        if abs(item["off"]) > 1e-9:
            continue
        base = item["base"]
        sub = pitch_shift(base, -12.0)
        mix = np.clip(base * 0.85 + sub * 0.55, -1.0, 1.0)
        mix = compress(mix, thresh_db=-16.0, ratio=3.5)
        mix = saturate(mix, 1.35)
        mix = reverb(mix, mix=0.22, dur=1.2, decay=3.8, seed=23 + i)
        fn = f"stack_{item['name']}_{item['voice']}.wav"
        p = os.path.join(WET, fn)
        dur = write_wav(p, fades(mix, 4.0, 30.0), peak=0.88)
        record("stack", os.path.basename(p), p, dur,
               text="", voice=item["voice"], semitones=0, wet=True, note="dry+sub(-12)+hall")
        # Sub-Layer einzeln zum Selber-Layouten
        sp_ = os.path.join(DRY, f"layer_{item['name']}_{item['voice']}_sub_oct.wav")
        sdur = write_wav(sp_, fades(sub, 4.0, 25.0), peak=0.85)
        record("layer", os.path.basename(sp_), sp_, sdur,
               source=item["name"], voice=item["voice"], semitones=-12, wet=False)


def build_pads() -> None:
    chords = [("Am", 110.0), ("F", 87.31), ("C", 130.81), ("G", 98.0),
              ("Em", 82.41), ("Dm", 73.42)]
    vowels = ["a", "o", "u"]
    dur = BEAT * 8.0                       # 2 Takte
    for ci, (cname, f0) in enumerate(chords):
        for vi, vowel in enumerate(vowels):
            y = vowel_pad(dur, f0, vowel)
            fn = f"pad_{cname}_{vowel}_{int(round(f0))}hz.wav"
            p = os.path.join(DRY, fn)
            d = write_wav(p, lp(y, 15000.0), peak=0.72)
            record("pad", os.path.basename(p), p, d,
                   chord=cname, vowel=vowel, f0_hz=round(f0), wet=False)
            wp = os.path.join(WET, fn.replace(".wav", "_wet.wav"))
            wy = reverb(lp(y, 14000.0), mix=0.42, dur=2.6, decay=2.6, seed=31 + ci * 3 + vi)
            wd = write_wav(wp, wy, peak=0.80)
            record("pad", os.path.basename(wp), wp, wd,
                   chord=cname, vowel=vowel, f0_hz=round(f0), wet=True)


# --------------------------------------------------------------------------- #
# QA + Manifest
# --------------------------------------------------------------------------- #
def qa_report() -> list[dict]:
    rows = []
    for m in MANIFEST:
        p = os.path.join(KIT, m["path"].replace("/", os.sep))
        y, sr = sf.read(p, dtype="float64", always_2d=False)
        peak = float(np.max(np.abs(y))) if y.size else 0.0
        rms = float(np.sqrt(np.mean(y ** 2))) if y.size else 0.0
        clipped = int(np.sum(np.abs(y) >= 0.999))
        dc = float(np.mean(y)) if y.size else 0.0
        nan = bool(np.any(~np.isfinite(y)))
        rows.append({
            "file": m["name"], "dur_s": round(y.size / sr, 3),
            "peak": round(peak, 4), "rms": round(rms, 4),
            "clipped": clipped, "dc": round(dc, 5), "nan": nan,
        })
    return rows


def write_manifest() -> None:
    with open(os.path.join(KIT, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump({"bpm": BPM, "sample_rate": SR, "generator": "make_voxkit.py",
                   "source": "synthetisch (edge-tts neural + numpy DSP)",
                   "files": MANIFEST}, f, ensure_ascii=False, indent=1)
    cols = ["category", "name", "path", "duration_s", "beat160", "sixteenths",
            "voice", "semitones", "grid", "wet", "chord", "vowel", "f0_hz",
            "text", "note"]
    with open(os.path.join(KIT, "MANIFEST.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for m in MANIFEST:
            w.writerow(m)


README = """VOCAL-KIT (Hardtekk) - synthetisch, keine Fremdaufnahmen
======================================================
Erzeugt von make_voxkit.py: deutsche Neural-TTS-Stimmen (edge-tts),
Formantsynthese und eigener Phase-Vocoder. Frei verwendbar.

Raster: {BPM} BPM (1 Takt = {BEAT}s, 16tel = {GRID_16*1000:.1f}ms).
Passt das Projekt-Tempo nicht, einfach neu erzeugen:
    python make_voxkit.py --bpm <tempo>

dry/   trockene Assets          wet/   dieselben Assets mit Hall
stack_ fertiger Hook (dry+sub+hall)
layer_ einzelne Oktave-Lage zum Selber-Layouten
chop_  One-Shots, 16tel/8tel/4tel bei 160 BPM

Dateinamen-Bedeutung:
  phrase_<text>_<stimme>_<p3|m5|0>st.wav   Tonhoehe +/- n Halbtoene zur Originalstimme
  chop_<quelle>_<stimme>_<nr>_<16th|8th|4th>_<p3|m5|0>st.wav
  pad_<akkord>_<vokal>_<hz>hz.wav           Formanten-Doppler (a/e/i/o/u)
  stack_<text>_<stimme>.wav                Hook: trocken + Sub-Oktave + Hall

Empfohlener Workflow in FL Studio:
  1. Browser (Alt+F8) -> Ordner hardtekk/voxkit/dry bzw. wet oeffnen
  2. Datei in die Playlist ziehen (Dialog bestaetigen) oder in den
     Channel Rack ziehen -> FL Sampler-Kanal entsteht
  3. Mit "Paint" Clips malen; chops sind auf 16tel gerastert ({BPM} BPM)
  4. Pitch der Sampler um +/- Halbtoene justieren, das st[_pX/mX]st im
     Dateinamen zeigt die bereits eingebaute Transposition
  5. Reverb im Mixer, nicht doppelt (wet/ ist schon hallversehen)

MANIFEST.json / MANIFEST.csv: jede Datei mit Kategorie, Dauer, Taktlaenge
(bei {BPM} BPM), Stimme, Halbtoentransposition, Text, Akkord.
"""


# --------------------------------------------------------------------------- #
def est_f0(y: np.ndarray, fmin: float = 50.0, fmax: float = 1200.0) -> float:
    """Grundfrequenz aus dem Spektralpeak.

    Wichtig fuer die Selbstkontrolle: die parabolische Interpolation laeuft auf
    der *Log*-Magnitude. Auf linearer Magnitude liegt sie bei tiefen Frequenzen
    systematisch zu tief (reiner 70-Hz-Sinus: 69.61 statt 70.00 = -9 Cent),
    was sonst faelschlich als Transpositionsfehler gewertet wird.
    """
    n = 1 << int(math.ceil(math.log2(max(8192, y.size))))
    w = np.hanning(y.size)
    mag = np.abs(np.fft.rfft(y * w, n))
    freqs = np.fft.rfftfreq(n, 1.0 / SR)
    band = (freqs >= fmin) & (freqs <= fmax)
    if not band.any():
        return 0.0
    idx = np.where(band)[0]
    i = int(idx[int(np.argmax(mag[idx]))])
    if 0 < i < mag.size - 1:
        logm = np.log(np.maximum(mag, 1e-20))
        a, b, c = logm[i - 1], logm[i], logm[i + 1]
        denom = a - 2 * b + c
        d = 0.5 * (a - c) / denom if abs(denom) > 1e-20 else 0.0
        return float(freqs[i] + d * (freqs[1] - freqs[0]))
    return float(freqs[i])


def smoke() -> None:
    """DSP-Kette an einem Beispiel pruefen (mit messbarer Tonhoehen-Kontrolle)."""
    print("== Smoke ==")
    f_test = 140.0
    y = vocal_chain(np.sin(2 * np.pi * f_test * np.arange(SR) / SR))
    f_meas = est_f0(y)
    print(f"  vocal_chain      {y.size/SR:.2f}s peak={np.max(np.abs(y)):.3f} "
          f"f0={f_meas:.1f}Hz (soll {f_test:.1f})")
    for st in (-12, -5, 3, 7):
        p = pitch_shift(y, st)
        soll = f_test * 2 ** (st / 12.0)
        got = est_f0(p)
        cents = 1200 * math.log2(got / soll) if soll > 0 else 999.0
        len_ok = "OK" if abs(p.size - y.size) <= 2 else f"LAENGE {p.size-y.size:+d}"
        ok = "OK " if abs(cents) < 15 else "FEHLER"
        print(f"  pitch_shift {st:+3d}st  {p.size/SR:.3f}s (soll {y.size/SR:.3f} {len_ok}) "
              f"peak={np.max(np.abs(p)):.3f} f0={got:.1f}Hz "
              f"Abw={cents:+.1f} Cent {ok}")
    r = reverb(y, mix=0.3)
    print(f"  reverb           {r.size/SR:.2f}s peak={np.max(np.abs(r)):.3f}")
    for v in ("a", "o", "u"):
        pad = vowel_pad(BEAT * 4, 110.0, v)
        print(f"  vowel_pad {v}      {pad.size/SR:.3f}s (soll {BEAT*4:.3f}) "
              f"peak={np.max(np.abs(pad)):.3f} loop_start={pad[0]:+.3f} loop_end={pad[-1]:+.3f}")
    trem = np.sin(2 * np.pi * 3 * np.arange(y.size) / SR) * 0.6 + y * 0.4
    segs = chop_segments(saturate(trem))
    print(f"  chop_segments    {len(segs)} Segmente (16tel={GRID_16:.4f}s)")
    for s, e, n16 in segs[:6]:
        dur = (e - s) / SR
        print(f"    {dur:.4f}s = {n16} x 16tel  ({beat_tag(n16)})  Abweichung "
              f"{(dur/(n16*GRID_16)-1)*100:+.2f}%")
    print("SMOKE OK")


async def main_async(args) -> None:
    for d in (DRY, WET, CACHE):
        os.makedirs(d, exist_ok=True)
    t0 = time.time()

    print("[1/5] Phrasen ...")
    # Basis-Phrasen: 4 Texte x 2 Stimmen, transponierte Auswahl
    phrase_items = []
    for name, text in PHRASES[:6]:
        for voice in (MALE, FEMALE):
            phrase_items.append(((name, text), voice))
    made = await build_phrase(phrase_items)

    print("[2/5] Transponierte Phrasen ...")
    extra_items = [((f"{name}_tr", text), FEMALE2 if i % 2 else MALE2)
                   for i, (name, text) in enumerate(PHRASES[6:10])]
    made += await build_phrase(extra_items, only_dry_offsets={-5.0, 3.0, 5.0, 7.0})

    print("[3/5] Chops ...")
    build_chops(made, max_files=args.max_chops)

    print("[4/5] Hook-Stacks + Sub-Layer ...")
    build_stacks(made)

    print("[5/5] Formanten-Pads ...")
    build_pads()

    write_manifest()
    with open(os.path.join(KIT, "README.txt"), "w", encoding="utf-8") as f:
        f.write(README.replace("{BPM}", f"{BPM:g}"))
    rows = qa_report()
    with open(os.path.join(KIT, "QA.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    bad = [r for r in rows if r["nan"] or r["peak"] < 0.05 or r["dur_s"] < 0.02]
    print(f"\nFERTIG: {len(MANIFEST)} Dateien in {time.time()-t0:.1f}s")
    print(f"Verdaechtige Dateien: {len(bad)}")
    for r in bad[:10]:
        print("  ", r)
    from collections import Counter
    print("Kategorien:", dict(Counter(m["category"] for m in MANIFEST)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--max-chops", type=int, default=70)
    ap.add_argument("--bpm", type=float, default=130.0,
                    help="Projekt-Tempo, auf das Chops/Pads gerastert werden")
    args = ap.parse_args()
    set_bpm(args.bpm)
    if args.bpm != 130.0:
        print(f"Temo gesetzt: {args.bpm} BPM  ->  16tel={GRID_16*1000:.2f}ms")
    if args.smoke:
        smoke()
    else:
        asyncio.run(main_async(args))


if __name__ == "__main__":
    main()