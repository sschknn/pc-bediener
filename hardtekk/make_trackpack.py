# -*- coding: utf-8 -*-
"""make_trackpack.py - kurze, eindeutige Namen fuer den FL-Studio-Aufbau.

Problem: Der FL-Browser ist schmal (~190 px), Dateinamen wie
"chop_nacht_conrad_00_16th_m5st.wav" werden mitten im Namen abgeschnitten -
die Halbton-Transposition ist dann nicht mehr erkennbar. Dieses Skript legt
die fuer den Trackaufbau benoetigten Dateien deshalb unter
voxkit/track/ mit kurzen Namen ab (c1..c6, d1, d2, h1..h4, p1, p2) und
schreibt ORDER.md als Zuordnungstabelle.

Quelle bleibt immer voxkit/dry bzw. voxkit/wet (MANIFEST.json als Index).
"""
from __future__ import annotations

import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.join(HERE, "voxkit")
TRACK = os.path.join(KIT, "track")

# (Kurzname, Kategorie, Voice, semitones, grid, Suffix wet?, Beschreibung)
PLAN = [
    ("c1", "chop", "conrad", -5, "16th", False, "Chop-Leiter 1/6 (Tonhoehe -5 Halbtoene)"),
    ("c2", "chop", "conrad", -3, "16th", False, "Chop-Leiter 2/6 (-3)"),
    ("c3", "chop", "conrad",  0, "16th", False, "Chop-Leiter 3/6 (Originaltonhoehe)"),
    ("c4", "chop", "conrad",  3, "16th", False, "Chop-Leiter 4/6 (+3)"),
    ("c5", "chop", "conrad",  5, "16th", False, "Chop-Leiter 5/6 (+5)"),
    ("c6", "chop", "conrad",  7, "16th", False, "Chop-Leiter 6/6 (+7)"),
    ("d1", "pad", None, None, None, False, "Pad a-Moll, Vokal a, trocken, 2 Takte"),
    ("d2", "pad", None, None, None, False, "Pad F, Vokal o, trocken, 2 Takte"),
    ("h1", "stack", "conrad", 0, None, True, "Hook 'Beton auf den Beat' maennlich, mit Sub-Oktave+Hall"),
    ("h2", "stack", "katja",  0, None, True, "Hook 'Wir sind das Feuer' weiblich"),
    ("h3", "stack", "conrad", 0, None, True, "Hook 'Kein Zurueck' maennlich"),
    ("h4", "stack", "katja",  0, None, True, "Hook 'Die Nacht gehoert uns' weiblich"),
    ("p1", "phrase", "conrad", 0, None, False, "Phrase 'Die Nacht gehoert uns' trocken"),
    ("p2", "phrase", "katja",  0, None, False, "Phrase 'Beton auf den Beat' trocken"),
]


def load_manifest() -> list[dict]:
    with open(os.path.join(KIT, "MANIFEST.json"), encoding="utf-8") as f:
        return json.load(f)["files"]


def pick(files: list[dict], category: str, voice: str | None,
         semitones: int | None, grid: str | None) -> dict | None:
    """Erste passende Datei; bei semitones None wird nichts gefiltert."""
    cands = [f for f in files
             if f["category"] == category
             and (voice is None or f.get("voice") == voice)
             and (semitones is None or f.get("semitones") == semitones)
             and (grid is None or f.get("grid") == grid)]
    if not cands:
        return None
    cands.sort(key=lambda f: f["name"])
    return cands[0]


def main() -> None:
    os.makedirs(TRACK, exist_ok=True)
    for old in os.listdir(TRACK):
        os.remove(os.path.join(TRACK, old))

    files = load_manifest()
    by_name = {f["name"]: f for f in files}
    lines = [
        "# Arrangement-Paket (voxkit/track)",
        "",
        "Kurze Dateinamen, weil der FL-Browser schmal ist und lange Namen",
        "mitten im Namen abgeschnitten werden. Quelle: voxkit/dry bzw. wet.",
        "",
        "| kurz | Datei | Takte (130 BPM) | Inhalt |",
        "|------|-------|-----------------|--------|",
    ]
    missing = []
    for short, category, voice, st, grid, want_wet, desc in PLAN:
        hit = None
        if category == "chop":
            hit = pick(files, "chop", voice, st, grid)
        elif category == "pad":
            hit = next((f for f in files if f["category"] == "pad"
                        and f.get("chord") == "Am" and f.get("vowel") == "a"
                        and not f.get("wet")), None) if short == "d1" else \
                  next((f for f in files if f["category"] == "pad"
                        and f.get("chord") == "F" and f.get("vowel") == "o"
                        and not f.get("wet")), None)
        elif category == "stack":
            seq = {"h1": "beton", "h2": "feuer", "h3": "kein_zurueck", "h4": "nacht"}
            base = seq[short]
            hit = next((f for f in files if f["category"] == "stack"
                        and f["name"].startswith(f"stack_{base}_{voice}")), None)
        elif category == "phrase":
            base = "nacht" if short == "p1" else "beton"
            hit = next((f for f in files if f["category"] == "phrase"
                        and f["name"].startswith(f"phrase_{base}_{voice}_0st")), None)
        if hit is None:
            missing.append(short)
            continue
        src = os.path.join(KIT, hit["path"].replace("/", os.sep))
        dst = os.path.join(TRACK, short + ".wav")
        shutil.copy2(src, dst)
        kb = os.path.getsize(dst) / 1024
        print(f"  {short}.wav  <- {hit['name']:44s} {hit['beat160']:5.2f} Beats  {kb:7.1f} KB  {desc}")
        lines.append(f"| {short} | {hit['name']} | {hit['beat160']:.2f} | {desc} |")

    with open(os.path.join(TRACK, "ORDER.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n{len(PLAN)-len(missing)} Dateien in {TRACK}")
    if missing:
        print("FEHLT:", missing)


if __name__ == "__main__":
    main()