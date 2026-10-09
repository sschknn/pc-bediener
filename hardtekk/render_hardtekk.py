"""Rendert einen Hardtekk-Track aus den TKNVLT-Sample-Packs.

Warum offline rendern statt per Drag & Drop in FL bauen
-------------------------------------------------------
FL Studio ist eine VCL-Anwendung: sie schluckt OLE-Drags aus dem
Explorer, rueckt Panels beim Beruehren um und meldet Zustands-
aenderungen nicht zurueck. Jeder Baustein (Sample laden, Step
programmieren, Clip setzen) kostete mehrere Fehlversuche. Die
Arrangement-Logik ist dagegen genau die Sorte Problem, die ein
Skript saenger loest als eine Maus: Positionen sind Taktarithmetik,
nicht Pixel.

Deshalb: hier werden die Stems deterministisch gerendert und danach
als echte Audio-Spuren in FL importiert. Der Producer kann danach wie
gewohnt weiterarbeiten - und die Stems sind einzeln editierbar.

Aufbau (150 BPM, 32 Takte, 4/4, Takt = 1,6 s)
----------------------------------------------
Takt  1- 4  Intro      Offbeat-Rumble + Hats, Acid dunkel, kein Kick
Takt  5-12  Section A  Kick 4-on-the-floor + Rumble + Hats + Acid
Takt 13-16  Build      Percussion, Hats laufen hoch, Riser ab Takt 13,
                      Impact auf Takt 16, Kick im Takt 16 raus
Takt 17-28  Section B  volles Arrangement + Stab-Layer, Schranz-Ghost
Takt 29-32  Outro      Kick bleibt, Layers laufen aus, letzter Takt leer

Alle gesetzten Loops wurden vorher auf ihre tatsaechliche Laenge
gemessen: nur Exakt-150-BPM-Dateien werden verwendet, damit nichts
gegen das Projekt-Tempo schlaegt.
"""
from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np
from scipy import signal

# --- Konfiguration ----------------------------------------------------------

BPM = 150.0
STEPS_PER_BAR = 16
SIXTEENTH = 60.0 / BPM / 4.0          # 0,1 s
BAR = SIXTEENTH * STEPS_PER_BAR       # 1,6 s
BARS = 32
SR = 44100
TOTAL = BAR * BARS

PACK = Path(r"C:\Users\frank\Music\TKNVLT_Hardtekk")
SRC = PACK / "_track150"
P1 = PACK / "TKNVLT - Free Hardtechno Sample Pack Vol. 1"
OUT = PACK / "render"
OUT.mkdir(parents=True, exist_ok=True)

# --- Patterns ---------------------------------------------------------------

KICK_STEPS = [0, 4, 8, 12]      # vier auf die Viertel
RUMBLE_STEPS = [2, 6, 10, 14]   # Offbeat-Rumble = Signatur des Hardtekk
CLAP_STEPS = [4, 12]
PERC_STEPS = [3, 11]
GHOST_STEPS = [14]              # Schranz-Ghost auf dem letzten 16er


def curve(pairs: list[tuple[int, float]], n: int = BARS) -> list[float]:
    """Baut eine Gain-Kurve aus (Takt, Gain)-Stuetzpunkten.

    Zwischen den Stuetzpunkten wird interpoliert - dadurch bekommt der
    Build eine echte Rampe statt harter Spruenge.
    """
    g = [0.0] * n
    pts = sorted(pairs)
    for i, (bar, val) in enumerate(pts):
        if bar < n:
            g[bar] = val
    for i in range(n):
        lo = [p for p in pts if p[0] <= i]
        hi = [p for p in pts if p[0] >= i]
        if not lo:
            continue
        if not hi:
            continue
        b0, v0 = lo[-1]
        b1, v1 = hi[0]
        if b1 == b0:
            g[i] = v1
        else:
            f = (i - b0) / (b1 - b0)
            g[i] = v0 + (v1 - v0) * f
    return g


# --- Audio-I/O --------------------------------------------------------------

def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        n, ch, width, rate = (w.getnframes(), w.getnchannels(),
                              w.getsampwidth(), w.getframerate())
        raw = w.readframes(n)
    if width == 2:
        d = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 3:
        a = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = a[:, 0] | (a[:, 1] << 8) | (a[:, 2] << 16)
        v = np.where(v & 0x800000, v - 0x1000000, v)
        d = v.astype(np.float32) / 8388608.0
    elif width == 4:
        d = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    elif width == 1:
        d = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128
    else:
        raise ValueError(f"{path.name}: unbekannte Samplebreite {width}")
    return d.reshape(-1, ch), rate


def to_mono(x: np.ndarray) -> np.ndarray:
    return x.mean(axis=1) if x.ndim > 1 else x


def resample(x: np.ndarray, frm: int, to: int = SR) -> np.ndarray:
    if frm == to:
        return x
    g = math.gcd(int(frm), int(to))
    return signal.resample_poly(x, to // g, frm // g)


def load(name: str, base: Path = SRC) -> np.ndarray:
    p = base / name
    if not p.exists():
        raise FileNotFoundError(p)
    x, rate = read_wav(p)
    return resample(to_mono(x), rate)


def write_wav(path: Path, x: np.ndarray, peak: float = 0.89) -> Path:
    if x.ndim == 1:
        x = np.stack([x, x], axis=1)
    x = x.astype(np.float32)
    m = float(np.max(np.abs(x))) or 1.0
    x = np.clip(x / m * peak, -1.0, 1.0)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    return path


# --- DSP --------------------------------------------------------------------

def place(buf: np.ndarray, src: np.ndarray, t: float, gain: float = 1.0,
          pan: float = 0.0) -> None:
    """Legt `src` additiv ab Sekunde `t` ab (mono- oder stereo-Buf)."""
    i = int(round(t * SR))
    if i < 0 or gain <= 0.0:
        return
    n = min(len(src), len(buf) - i)
    if n <= 0:
        return
    s = src[:n] * gain
    if pan == 0.0 or buf.ndim == 1:
        buf[i:i + n] += s
        return
    l = math.cos((pan + 1.0) * math.pi / 4)
    r = math.sin((pan + 1.0) * math.pi / 4)
    buf[i:i + n, 0] += s * l
    buf[i:i + n, 1] += s * r


def place_loop(buf: np.ndarray, src: np.ndarray, start_bar: int,
               gains, pan: float = 0.0) -> None:
    """Setzt einen Loop taktweise - mit eigener Gain je Takt.

    Bewusst taktweise statt als Block: nur so lassen sich Aus- und
    Einblendungen pro Takt steuern, ohne dass sich Loops ueberlappen.
    """
    # Epsilon, weil ein exakt taktlanger Loop nach dem Resampling
    # 12,8000001 Takte haben kann - ceil() wuerde daraus 9 machen.
    n_bars = int(math.ceil(len(src) / (BAR * SR) - 1e-3))
    for k in range(n_bars):
        if start_bar + k >= BARS:
            break
        if isinstance(gains, (list, tuple)):
            g = gains[k] if k < len(gains) else gains[-1]
        else:
            g = gains
        if g <= 0.0:
            continue
        off = int(k * BAR * SR)
        seg = src[off:off + int(BAR * SR)]
        if len(seg) == 0:
            break
        place(buf, seg, (start_bar + k) * BAR, g, pan)


def duck(buf: np.ndarray, times: list[float], depth: float = 0.3,
         length: float = 0.16) -> None:
    """Sidechain: kurzer Pegelabfall nach jedem Kick."""
    n = int(length * SR)
    env = np.exp(-np.arange(n) / (n / 5.0)).astype(np.float32)
    for t in times:
        i = int(round(t * SR))
        if i >= len(buf):
            continue
        k = min(n, len(buf) - i)
        f = (1.0 - depth * env[:k])
        buf[i:i + k] *= f[:, None] if buf.ndim > 1 else f


def lowpass(x: np.ndarray, cutoff: float, order: int = 4) -> np.ndarray:
    wn = min(max(cutoff / (SR / 2), 1e-4), 0.99)
    b, a = signal.butter(order, wn, btype="low")
    return signal.lfilter(b, a, signal.lfilter(b, a, x))


def highpass(x: np.ndarray, cutoff: float, order: int = 2) -> np.ndarray:
    wn = min(max(cutoff / (SR / 2), 1e-4), 0.99)
    b, a = signal.butter(order, wn, btype="high")
    return signal.lfilter(b, a, x)


def saturate(x: np.ndarray, drive: float = 2.2, mix: float = 0.6) -> np.ndarray:
    y = np.tanh(x * drive) / math.tanh(drive)
    return x * (1.0 - mix) + y * mix


def fade(x: np.ndarray, fin: float, fout: float) -> np.ndarray:
    n = len(x)
    a, b = max(1, int(fin * SR)), max(1, int(fout * SR))
    x[:a] *= np.linspace(0, 1, a)
    if b < n:
        x[n - b:] *= np.linspace(1, 0, b)
    return x


def ramp(src: np.ndarray, length_s: float) -> np.ndarray:
    """Blendet ein FX-Sample auf seine volle Laenge ein (Riser)."""
    k = min(len(src), int(length_s * SR))
    if k <= 0:
        return src
    out = src.copy()
    out[:k] *= np.linspace(0.25, 1.0, k)
    return out


# --- Gain-Kurven ------------------------------------------------------------

# Indizes hier sind 0-basiert: Index 15 = Takt 16 (Pre-Drop ohne Kick),
# Index 16 = Takt 17 (Drop). Genau dieser eine Takt ohne Kick ist das,
# was den Drop spuerbar macht - steht er versehentlich zu spaet, klingt
# Takt 17 messbar leiser als Takt 18 (das war der erste Fehlversuch).
G_KICK = curve([(0, 0.0), (4, 0.9), (14, 0.95), (15, 0.0), (16, 1.0),
                (30, 0.9), (31, 0.0)])
G_RUMBLE = curve([(0, 0.6), (4, 0.65), (12, 0.72), (16, 0.8), (17, 0.85),
                  (28, 0.85), (32, 0.45)])
G_CLAP = curve([(0, 0.0), (7, 0.34), (16, 0.45), (28, 0.45), (31, 0.2),
                (32, 0.0)])
G_PERC = curve([(0, 0.0), (12, 0.55), (16, 0.6), (28, 0.6), (32, 0.0)])
G_HAT = curve([(0, 0.32), (4, 0.48), (12, 0.5), (14, 1.05), (15, 0.9),
               (16, 0.8), (28, 0.8), (31, 0.5), (32, 0.0)])
G_ACID = curve([(0, 0.0), (4, 0.45), (12, 0.5), (14, 0.8), (15, 0.95),
                (16, 0.7), (28, 0.7), (31, 0.45), (32, 0.0)])
G_STAB = curve([(0, 0.0), (16, 0.5), (20, 0.62), (28, 0.62), (30, 0.3),
                (31, 0.0)])
G_OHAT = curve([(0, 0.22), (4, 0.32), (16, 0.42), (28, 0.42), (32, 0.15)])


def build() -> dict[str, Path]:
    print(f"Samples aus {PACK}")
    s_kick = load("01_KICK_Hardcore.wav")
    s_rumble = load("02_KICK_Rumble.wav")
    s_schranz = load("03_KICK_Schranz.wav")
    s_clap = load("04_CLAP.wav")
    s_ohat = load("06_HAT_Open.wav")
    s_perc = load("07_PERC.wav")

    l_hat = load("10_LOOP_Hat_150.wav")       # 8 Takte, exakt 150
    l_acid = load("11_LOOP_Acid_150.wav")     # 4 Takte, exakt 150
    l_perc = load("12_LOOP_Perc_150.wav")     # 8 Takte, exakt 150
    l_stab = load("Synth & Melodic/Stab Loops/TKNVLT_FREE_HT_STAB_LOOP_1_150.wav",
                  P1)                        # 4 Takte, exakt 150
    fx_rise = load("FX/Risers/TKNVLT_FREE_HT_RISE_08.wav", P1)   # 3 Takte
    fx_imp = load("FX/Impacts/TKNVLT_FREE_HT_IMP_09.wav", P1)   # 4 Takte

    n = int(TOTAL * SR) + SR
    drums = np.zeros(n, dtype=np.float32)
    bass = np.zeros(n, dtype=np.float32)
    texture = np.zeros(n, dtype=np.float32)
    fx = np.zeros(n, dtype=np.float32)

    print(f"arrangiere {BARS} Takte @ {BPM:.0f} BPM "
          f"({TOTAL:.1f} s, Takt {BAR:.2f} s)")

    for bar in range(BARS):
        t0 = bar * BAR

        if G_KICK[bar] > 0.0:
            for s in KICK_STEPS:
                place(drums, s_kick, t0 + s * SIXTEENTH, G_KICK[bar])
            if bar >= 16:                     # Schranz-Ghost nur im Main
                place(drums, s_schranz, t0 + GHOST_STEPS[0] * SIXTEENTH,
                      0.45 * G_KICK[bar])
        if G_RUMBLE[bar] > 0.0:
            for s in RUMBLE_STEPS:
                place(drums, s_rumble, t0 + s * SIXTEENTH, G_RUMBLE[bar])
        if G_CLAP[bar] > 0.0:
            for s in CLAP_STEPS:
                place(drums, s_clap, t0 + s * SIXTEENTH, G_CLAP[bar])
        if G_PERC[bar] > 0.0:
            for s in PERC_STEPS:
                place(drums, s_perc, t0 + s * SIXTEENTH, G_PERC[bar])
        if G_OHAT[bar] > 0.0:
            place(texture, s_ohat, t0 + 15 * SIXTEENTH, G_OHAT[bar])

    # --- Loops, taktweise platziert ----------------------------------------
    # Hat-Loop: 8 Takte ab Takt 1
    place_loop(texture, l_hat, 0, G_HAT[:8])
    place_loop(texture, l_hat, 8, G_HAT[8:16])
    place_loop(texture, l_hat, 16, G_HAT[16:24])
    place_loop(texture, l_hat, 24, G_HAT[24:32])

    # Perc-Loop: 8 Takte ab Takt 13 und 21
    place_loop(texture, l_perc, 12, G_PERC[12:20])
    place_loop(texture, l_perc, 20, G_PERC[20:28])

    # Acid-Loop: 4 Takte, alle 4 Takte neu gesetzt
    for start in range(4, BARS, 4):
        place_loop(bass, l_acid, start, G_ACID[start:start + 4])

    # Stab-Loop: 4 Takte ab Takt 17, im Build lauter
    for start in range(16, BARS, 4):
        g = [G_STAB[start + k] for k in range(4)]
        place_loop(bass, l_stab, start, g, pan=0.12)

    # --- FX: Riser ueber die letzten 3 Takte des Builds, Impact auf den Drop
    place(fx, ramp(fx_rise, 3 * BAR), 13 * BAR, 0.5)     # Takt 14-16
    place(fx, fx_imp, 16 * BAR, 0.85)                    # Takt 17 = Drop
    place(fx, fx_imp, 28 * BAR, 0.4)                     # Takt 29 = Outro

    # --- Intro-Bass: Acid tiefgefiltert unter den Rumble legen -------------
    intro = lowpass(l_acid, 240.0)
    place_loop(bass, intro, 0, [0.5, 0.55, 0.6, 0.6])

    n_use = int(TOTAL * SR)
    drums, bass, texture, fx = (a[:n_use] for a in (drums, bass, texture, fx))

    # --- Sidechain auf allem ausser dem Kick -------------------------------
    kt = [bar * BAR + s * SIXTEENTH
          for bar in range(BARS) if G_KICK[bar] > 0.0 for s in KICK_STEPS]
    duck(texture, kt, 0.30)
    duck(bass, kt, 0.20)
    duck(fx, kt, 0.15)

    # --- Klang --------------------------------------------------------------
    drums = saturate(drums, 2.6, 0.55)
    bass = saturate(bass, 1.8, 0.45)
    texture = highpass(texture, 190.0)
    texture = saturate(texture, 1.4, 0.30)
    fx = highpass(fx, 60.0)

    fade(drums, 0.002, 0.25)
    fade(texture, 0.01, 0.7)
    fade(bass, 0.05, 0.9)
    fade(fx, 0.05, 0.4)

    print("schreibe Stems ...")
    paths = {
        "drums":  write_wav(OUT / "hardtekk_drums.wav", drums, 0.95),
        "bass":   write_wav(OUT / "hardtekk_bass.wav", bass, 0.88),
        "textur": write_wav(OUT / "hardtekk_textur.wav", texture, 0.88),
        "fx":     write_wav(OUT / "hardtekk_fx.wav", fx, 0.85),
    }
    mix = (drums * 1.00 + bass * 0.95 + texture * 0.85 + fx * 0.75)
    mix = saturate(mix, 1.35, 0.35)
    paths["mix"] = write_wav(OUT / "hardtekk_mix.wav", mix, 0.95)

    for k, p in paths.items():
        d, r = read_wav(p)
        print(f"  {k:7s} {p.name:22s} {len(d)/r:6.2f}s peak "
              f"{np.max(np.abs(d)):.3f} rms "
              f"{20*np.log10(max(float(np.sqrt(np.mean(d**2))),1e-9)):6.2f} dBFS")
    return paths


if __name__ == "__main__":
    build()