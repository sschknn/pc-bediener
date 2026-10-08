"""
BLOCKLICHT - Stereo-Rendering der bestehenden Stems.

Der Mono-Mix war die offene Schwelle. Hier wird jeder Stem gezielt
stereo verbreitert:

  Drums  - Kick/Sub bleiben tief mono, nur die Obertone (Hats/Snare) spreizen
  Bass   - bleibt komplett mono (Club-/PA-Kompatibilitaet)
  Synth  - echte Seitenbreite, Sub-Oktave bleibt mono
  Vocals - trocken praktisch mono, nur minimal aufgeweitet (Rap-Standard)

Verfahren: Haas-Dekorrelation -> M/S -> Highpass auf der Seite.
Der Highpass ist entscheidend, sonst wird der Bass mitgespreizt und
die Mono-Summe faellt auseinander.

Erzeugt ausschliesslich neue Dateien. Die Mono-Originale bleiben unberuehrt.
"""

import os
import sys

import numpy as np
import soundfile as sf
from scipy import signal

sys.path.insert(0, r"C:\Users\frank\Documents\Projekte\pc bediener\hardtekk")
import build_blocklicht as B

SR = B.SR
OUTDIR = r"C:\Users\frank\Documents\Projekte\hardtekk_stereo"
os.makedirs(OUTDIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Werkzeuge
# ---------------------------------------------------------------------------
def ms(sec):
    return int(round(sec * SR))


def rms(x):
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64))) + 1e-12)


def db(x):
    return 20.0 * np.log10(x)


def side_from_haas(x, delay_ms):
    """
    Dekorreliertes Seiten-Signal aus einem Mono-Signal.

    Ein kurzer Verzoegerungssprung plus Kombdifferenz liefert ein Signal,
    das dem Original zeitlich verschoben ist -> M und S sind unkorreliert.
    """
    n = len(x)
    d = max(1, min(ms(delay_ms / 1000.0), n // 4))
    z = np.zeros(n, dtype=np.float64)
    z[d:] = x[:-d]
    return z - x


def to_stereo(mono, width=0.5, hf_hz=250.0, delay_ms=13.0):
    """
    Mono -> Stereo mit einstellbarer Breite.

    width = 0.0  -> exakt mono
    width = 0.5  -> Seite 6 dB unter Mitte (solide Breite)
    width = 1.0  -> Seite auf Mittelpegel (+6 dB, sehr breit)

    hf_hz: Allpassgrenze der Seite. Der Tieffrequenzbereich bleibt dadurch
    in beiden Kanaelen identisch -> Summation nach Mono klingt korrekt.
    """
    M = mono.astype(np.float64)
    if width <= 0.0:
        return M.copy(), M.copy()

    S = side_from_haas(M, delay_ms)
    sos = signal.butter(2, hf_hz, "high", fs=SR, output="sos")
    S = signal.sosfilt(sos, S)

    # Seitenpegel auf Mitte normieren, damit 'width' vergleichbar ist
    S = S / rms(S) * rms(M)
    S *= width

    L = M + S
    R = M - S
    return L, R


def hp(x, hz):
    sos = signal.butter(2, hz, "high", fs=SR, output="sos")
    return signal.sosfilt(sos, x).astype(np.float64)


def lp(x, hz):
    sos = signal.butter(2, hz, "low", fs=SR, output="sos")
    return signal.sosfilt(sos, x).astype(np.float64)


def analyse(L, R, label):
    """Kennzahlen, mit denen sich die Breite objektiv belegen laesst."""
    corr = float(np.corrcoef(L, R)[0, 1])
    mid = (L + R) / 2.0
    side = (L - R) / 2.0
    width_db = db(rms(side) / rms(mid))
    # Mono-Kompatibilitaet: das Tiefband muss in beiden Kanaelen
    # IDENTISCH sein, sonst bricht die Mono-Summe zusammen.
    lp_corr = float(np.corrcoef(lp(L, 120.0), lp(R, 120.0))[0, 1])
    lp_diff = db(rms(lp(L - R, 120.0)) / rms(lp(L, 120.0)))
    return {
        "label": label,
        "corr": round(corr, 4),
        "width_db": round(width_db, 2),
        "lp_corr": round(lp_corr, 4),
        "lp_diff_db": round(lp_diff, 1),
        "peak": round(float(np.max(np.abs(np.stack([L, R], 1)))), 4),
    }


def write_stereo(path, L, R, peak=0.89):
    st = np.stack([L, R], axis=1).astype(np.float32)
    m = float(np.max(np.abs(st)) + 1e-9)
    if m > peak:
        st = st * (peak / m)
    sf.write(path, st, SR, subtype="PCM_16")
    return {"path": path, "peak": round(m, 4),
            "bytes": int(os.path.getsize(path))}


# ---------------------------------------------------------------------------
# Stems bauen (Mono-Quellen aus dem bestaetigten Build uebernehmen)
# ---------------------------------------------------------------------------
print("=" * 74)
print("BLOCKLICHT - Stereo-Rendering")
print("=" * 74)

print("[1/4] Mono-Quellen aus dem bestaetigten Build ...")
drums_m, kicks, claps = B.build_drums()
bass_m = B.build_bass(kicks)
synth_m = B.build_synth()
vocals_m, report = B.build_vocals(kicks)
print(f"      Kicks: {len(kicks)}   Partie-Zeilen: {len(report)}")

# ---------------------------------------------------------------------------
# Stereowerte pro Stem
# ---------------------------------------------------------------------------
SETTINGS = {
    # name        width  hf_hz  delay
    "drums":  (0.50, 420.0, 10.0),   # Kick/Sub tief mono, Hats/Clap spreizen
    "bass":   (0.00, 250.0, 13.0),   # bewusst mono
    "synth":  (0.60, 320.0, 15.0),   # melodische Elemente weit
    "vocals": (0.22, 400.0,  9.0),   # Rap-Stimme fast mono, minimal Luft
}

print("[2/4] Stereo-Konvertierung ...")
mono_src = {"drums": drums_m, "bass": bass_m,
            "synth": synth_m, "vocals": vocals_m}
stereo = {}
for name, (w, hf, d) in SETTINGS.items():
    L, R = to_stereo(mono_src[name], w, hf, d)
    stereo[name] = (L, R)
    a = analyse(L, R, name)
    print(f"      {name:<7} width={w:.2f} hp={hf:>5.0f}Hz delay={d:>4.1f}ms "
          f"| corr={a['corr']:>6.3f}  breite={a['width_db']:>6.2f} dB  "
          f"tief<120Hz: corr={a['lp_corr']:.4f} diff={a['lp_diff_db']:+.1f} dB")

print("[3/4] Schreiben ...")
res = {}
for name, (L, R) in stereo.items():
    res[name] = write_stereo(os.path.join(OUTDIR, f"blocklicht_{name}_ST.wav"), L, R)
    print(f"      {name:<7} {os.path.basename(res[name]['path']):<28} "
          f"{res[name]['bytes']/1024/1024:>6.2f} MB")

# Vergleich: Pegel- und Mono-Summenverhalten gegenueber dem Original
print()
print("      Pegelvergleich Mono -> Stereo (RMS des Mittelkanals, dB):")
for name in SETTINGS:
    src = mono_src[name]
    L, R = stereo[name]
    mid = (L + R) / 2.0
    print(f"        {name:<7} {db(rms(mid)) - db(rms(src)):+.2f} dB")

print()
print("      Mono-Summe gegenueber Original (< 120 Hz, Pegel):")
for name in SETTINGS:
    src = mono_src[name]
    L, R = stereo[name]
    a = float(np.abs(L + R).max() + 1e-9)
    b = float(np.abs(2.0 * src).max() + 1e-9)
    print(f"        {name:<7} Peak {db(a):+.2f} dB  (Original {db(b):+.2f} dB, "
          f"Diffa {db(a) - db(b):+.2f} dB)")

# ---------------------------------------------------------------------------
# Stereo-Mix-Referenz
# ---------------------------------------------------------------------------
print("[4/4] Stereo-Mix ...")
mix = sum(stereo[n][0] * g for n, g in
          (("drums", 1.00), ("bass", 0.92), ("synth", 0.80), ("vocals", 0.95)))
mix_r = sum(stereo[n][1] * g for n, g in
            (("drums", 1.00), ("bass", 0.92), ("synth", 0.80), ("vocals", 0.95)))
mix = np.tanh(mix * 0.85) * 1.05
mix_r = np.tanh(mix_r * 0.85) * 1.05
mix, mix_r = B.soft_limit(mix, 0.92, 0.70), B.soft_limit(mix_r, 0.92, 0.70)
res["mix"] = write_stereo(os.path.join(OUTDIR, "blocklicht_mix_ST.wav"), mix, mix_r, 0.92)
a = analyse(mix, mix_r, "mix")
print(f"      Mix: corr={a['corr']:.3f}  breite={a['width_db']:.2f} dB  "
      f"tief<120Hz: corr={a['lp_corr']:.4f} diff={a['lp_diff_db']:+.1f} dB")

# ---------------------------------------------------------------------------
# Bericht
# ---------------------------------------------------------------------------
lines = [
    "BLOCKLICHT - Stereo-Vergleich",
    "=" * 74,
    f"Tempo {B.BPM:.0f} BPM | {B.TOTAL_BARS} Takte | F#-Moll",
    "",
    "Je Stem:",
    "  corr        L/R-Korrelation des Vollsignals (1.0 = vollstaendig mono)",
    "  breite dB   Side/Mid-Verhaeltnis; 0 dB = Seite so laut wie Mitte",
    "  tief corr   L/R-Korrelation des Tiefbands < 120 Hz",
    "              Muss 1.0 sein - nur dann bleibt die Mono-Summe intakt",
    "  tief diff   Pegelabweichung der Mono-Summe < 120 Hz gegenueber Original",
    "",
    f"{'Stem':<8}{'width':>8}{'hp Hz':>8}{'delay':>8}{'corr':>8}"
    f"{'breite dB':>11}{'tief corr':>11}{'tief diff':>11}",
]
for name, (w, hf, d) in SETTINGS.items():
    L, R = stereo[name]
    a = analyse(L, R, name)
    lines.append(f"{name:<8}{w:>8.2f}{hf:>8.0f}{d:>8.1f}{a['corr']:>8.3f}"
                 f"{a['width_db']:>11.2f}{a['lp_corr']:>11.4f}{a['lp_diff_db']:>11.1f}")
L, R = mix, mix_r
a = analyse(L, R, "mix")
lines.append(f"{'MIX':<8}{'-':>8}{'-':>8}{'-':>8}{a['corr']:>8.3f}"
             f"{a['width_db']:>11.2f}{a['lp_corr']:>11.4f}{a['lp_diff_db']:>11.1f}")
lines += [
    "",
    "Dateien (alle neu, Mono-Originale unberuehrt):",
]
for name in list(SETTINGS) + ["mix"]:
    lines.append("  " + os.path.basename(res[name]["path"]))
lines += [
    "",
    "Anwendung in FL Studio: die *_ST.wav ueber die _ST-Clips legen,",
    "oder die vier Stems auf neue Playlist-Spuren ziehen und die",
    "Mono-Spuren stummschalten.",
]
with open(os.path.join(OUTDIR, "STEREO_REPORT.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

print("-" * 74)
print("FERTIG ->", OUTDIR)
print("-" * 74)
