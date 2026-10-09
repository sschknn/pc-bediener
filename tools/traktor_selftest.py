"""Traktor-Selbsttest: sendet die Bruecken-Kommandos und dokumentiert jeden
Schritt mit einem Screenshot der Deck-Kopfzeilen.

Ablauf
------
Der Test sendet nacheinander echte MIDI-Noten ueber dieselbe Bruecke, die
auch der Agent benutzt (``traktorbridge``), macht nach jedem Schritt eine
Aufnahme des Traktor-Fensters und legt daraus zwei Dinge ab:

  tmp/selftest/NN_<name>.png     Fenster-Ausschnitt des vollen Fensters
  tmp/selftest/_montage.png      alle Deck-Kopfzeilen untereinander, mit
                                 Beschriftung - ein Bild fuer die Vision-Pruefung

So laesst sich ohne laufende GUI-Interaktion nachvollziehen, ob eine Note
wirklich etwas ausloest (Deck laedt, Playhead laeuft, SYNC leuchtet, ...).
"""
from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pcbediener.modules import traktorbridge as tb  # noqa: E402

from PIL import Image, ImageDraw, ImageGrab  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tmp" / "selftest"
TITLE = "Traktor Pro 4"

_u = ctypes.windll.user32


def window_rect() -> tuple[int, int, int, int]:
    hwnd = _u.FindWindowW(None, TITLE)
    if not hwnd:
        raise SystemExit("Traktor-Fenster nicht gefunden")
    r = wintypes.RECT()
    _u.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def grab_window() -> Image.Image:
    l, t, r, b = window_rect()
    vx = _u.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
    vy = _u.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
    full = ImageGrab.grab(all_screens=True)
    return full.crop((l - vx, t - vy, r - vx, b - vy))


#: (name, kommandos, wartezeit nach dem Senden)
STEPS: list[tuple[str, list[str], float]] = [
    ("baseline", [], 0.3),
    ("load_a_b", ["load_a", "load_b"], 2.5),
    ("play_a", ["play_a"], 2.0),
    ("play_b", ["play_b"], 2.0),
    ("sync_a", ["sync_a"], 0.8),
    ("hotcue_a1", ["hotcue_a1"], 0.8),
    ("hotcue_a2", ["hotcue_a2"], 0.8),
    ("cue_a", ["cue_a"], 0.8),
    ("pause_a", ["play_a"], 0.8),
    ("pause_b", ["play_b"], 0.8),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tops: list[Image.Image] = []
    labels: list[str] = []

    for i, (name, cmds, wait) in enumerate(STEPS):
        for c in cmds:
            res = tb.trigger(c)
            print(f"{name:10s} -> {c:10s} note={res['note']:3d} "
                  f"mapped={res['verified_in_traktor']}")
        time.sleep(wait)
        img = grab_window()
        img.save(OUT / f"{i:02d}_{name}.png")
        # Kopfzeile: globaler Header + Deck-Header (A/B)
        tops.append(img.crop((0, 0, img.width, min(300, img.height))))
        labels.append(name)

    # Montage mit Beschriftung
    bar = 26
    width = max(t.width for t in tops)
    total = sum(t.height + bar for t in tops)
    montage = Image.new("RGB", (width, total), (20, 20, 20))
    d = ImageDraw.Draw(montage)
    y = 0
    for lab, tile in zip(labels, tops):
        d.rectangle([0, y, width, y + bar - 1], fill=(0, 90, 160))
        d.text((6, y + 7), lab, fill=(255, 255, 255))
        montage.paste(tile, (0, y + bar))
        y += tile.height + bar
    montage.save(OUT / "_montage.png")
    print("Montage:", OUT / "_montage.png", montage.size)


if __name__ == "__main__":
    main()
