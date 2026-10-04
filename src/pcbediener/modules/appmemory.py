"""Programm-Gedächtnis: verifizierte Bedienwege pro Anwendung.

Jede Anwendung bekommt eine JSON-Datei mit **Regeln** – aber nur Wege, die
wirklich funktioniert haben (verifiziert per Screenshot, OCR oder Pixel).
Fehlgeschlagene Wege stehen unter ``avoid`` mit Grund und werden nie wieder
probiert, solange sie als ``broken`` markiert sind.

Automatische Aktualisierung (Pflicht im Arbeitsablauf):

1. Vor einer Bedienung: ``get_rule(app, name)`` lesen und genau so vorgehen.
2. Nach dem Schritt das Ergebnis verifizieren (Screenshot/OCR/Pixel).
3. Erfolg → ``set_rule(...)`` (Zähler hoch, ``broken`` lösen).
4. Fehlschlag → ``mark_broken(...)`` mit Grund; sobald ein Ersatzweg
   verifiziert ist, ``set_rule(...)`` für den Ersatz.

So läuft der Programm-Ablauf sicher: Was einmal nicht mehr geht, wird
automatisch aus dem aktiven Weg entfernt.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

ENV_DIR = "PCB_APPMEM_DIR"
APP_DIR_NAME = "pcbediener"


def mem_dir() -> Path:
    """Speicherort der Regeldateien (per Env überschreibbar, z.B. für Tests)."""
    env = os.environ.get(ENV_DIR)
    if env:
        base = Path(env)
    else:
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
        base = Path(appdata) / APP_DIR_NAME / "appmem"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _path(app: str) -> Path:
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in app.lower())
    if not safe:
        raise ValueError("app darf nicht leer sein")
    return mem_dir() / f"{safe}.json"


def _blank(app: str) -> dict[str, Any]:
    return {"app": app, "rules": {}, "avoid": {}, "updated": 0.0}


def load_app(app: str) -> dict[str, Any]:
    """Lädt die Regeldatei einer App (leere Hülle, wenn neu)."""
    p = _path(app)
    if not p.is_file():
        return _blank(app)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _blank(app)
    if not isinstance(data, dict):
        return _blank(app)
    data.setdefault("rules", {})
    data.setdefault("avoid", {})
    return data


def _save(app: str, data: dict[str, Any]) -> dict[str, Any]:
    data["updated"] = time.time()
    _path(app).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def get_rule(app: str, name: str) -> dict[str, Any]:
    """Holt eine Regel inkl. Status (``broken``/``verified``/``open``)."""
    data = load_app(app)
    rule = data["rules"].get(name)
    if rule is None:
        raise KeyError(f"Keine Regel {name!r} für {app!r} – erst verifizieren, dann set_rule().")
    return {"app": app, "name": name, **rule}


def list_rules(app: str) -> dict[str, Any]:
    """Alle Regeln + Avoid-Liste einer App (Kurzform)."""
    data = load_app(app)
    return {
        "app": app,
        "rules": {n: {"status": r.get("status", "?"), "broken": bool(r.get("broken")),
                      "verified_ok": r.get("verified_ok", 0), "note": r.get("note", "")[:120]}
                  for n, r in data["rules"].items()},
        "avoid": data["avoid"],
    }


def set_rule(app: str, name: str, steps: list[str], note: str = "") -> dict[str, Any]:
    """Speichert einen VERIFIZIERTEN Weg (Erfolg per Screenshot/OCR/Pixel belegt).

    Löst ein ``broken``-Flag und erhöht den ``verified_ok``-Zähler.
    """
    if not steps or not all(isinstance(s, str) and s.strip() for s in steps):
        raise ValueError("steps braucht mindestens einen nicht-leeren Schritt")
    data = load_app(app)
    prev = data["rules"].get(name, {})
    data["rules"][name] = {
        "status": "verified",
        "broken": False,
        "steps": [s.strip() for s in steps],
        "note": note,
        "verified_ok": int(prev.get("verified_ok", 0)) + 1,
        "history": [*prev.get("history", []), {"ok": True, "at": time.time(), "note": note}][-10:],
    }
    _save(app, data)
    return {"app": app, "name": name, **data["rules"][name]}


def mark_broken(app: str, name: str, reason: str, replacement: str = "") -> dict[str, Any]:
    """Markiert einen Weg als defekt (AUTOMATISCH bei Fehlschlag aufrufen).

    Die Regel bleibt lesbar (Historie), wird aber nicht mehr als Weg benutzt,
    bis ``set_rule`` sie erneut verifiziert. Optional steht der Ersatzweg
    direkt dabei.
    """
    if not reason.strip():
        raise ValueError("reason darf nicht leer sein")
    data = load_app(app)
    prev = data["rules"].get(name, {})
    entry = {
        "status": "broken",
        "broken": True,
        "steps": prev.get("steps", []),
        "note": prev.get("note", ""),
        "verified_ok": int(prev.get("verified_ok", 0)),
        "broken_reason": reason,
        "replacement": replacement,
        "history": [*prev.get("history", []), {"ok": False, "at": time.time(), "note": reason}][-10:],
    }
    data["rules"][name] = entry
    if replacement:
        data["avoid"][name] = reason
    _save(app, data)
    return {"app": app, "name": name, **entry}


def add_avoid(app: str, what: str, reason: str) -> dict[str, Any]:
    """Trägt einen nachweislich NICHT lauffähigen Weg ein (nie wieder probieren)."""
    if not what.strip() or not reason.strip():
        raise ValueError("what und reason dürfen nicht leer sein")
    data = load_app(app)
    data["avoid"][what] = reason
    _save(app, data)
    return {"app": app, "avoid": data["avoid"]}


# --- Startbestand: in dieser Sitzung VERIFIZIERTES FL-Wissen ------------------
_SEEDS: dict[str, dict[str, Any]] = {
    "flstudio": {
        "rules": {
            "tempo_via_midi_import": {
                "steps": [
                    "FILE-Menü (21,26) per SendInput-Klick öffnen",
                    "Import > MIDI wählen, Confirm ggf. mit No beantworten",
                    "Pfad per Zwischenablage in Open-Dialog einfügen + Enter",
                    "Import-Dialog akzeptieren, Toolbar per OCR prüfen",
                ],
                "note": "tempo160.mid (FF 51 03 05 DD B0) setzte Projekt auf 160 BPM, OCR-verifiziert.",
            },
            "browser_drag_audio": {
                "steps": [
                    "Browser per Alt+F8 öffnen, hardtekk-Ordner aufklappen",
                    "Dateizeile per OCR finden (x~200), Drag in Playlist-Spur",
                    "FL als Vordergrund VOR mouseUp setzen (Drop-Dialog erscheint)",
                    "'Dropped sample(s)'-Dialog beantworten (siehe Regel drop_dialog)",
                ],
                "note": "Drop aus FL-Browser löst Dialog aus = Datei akzeptiert. Explorer-Drag meiden (falsche Spalte gegriffen).",
            },
            "modal_tmsgform_close": {
                "steps": [
                    "window_modal_state prüfen (enabled=False + likely_modal_blocker)",
                    "WM_CLOSE an blockierenden Dialog posten",
                    "Hauptfenster wieder enabled verifizieren",
                ],
                "note": "TNameEditForm so geschlossen, Menüs reagierten wieder.",
            },
        },
        "avoid": {
            "tempo_panel_typing": "Tempo-Feld hat keinen Edit-Modus (Klick/Tippen wirkungslos, OCR-verifiziert).",
            "printwindow_ground_truth": "PrintWindow mischt Child-Fenster ohne Z-Order – nur Screen-Grabs zählen bei Überlappung.",
            "explorer_drag_ohne_dialog": "Drop ohne Dialog-Antwort platziert nichts (stiller Fehlschlag).",
        },
    },
}


def ensure_seeded(app: str) -> dict[str, Any]:
    """Legt den Startbestand an, falls die App noch keine Regeldatei hat."""
    if _path(app).is_file():
        return {"app": app, "seeded": False}
    seed = _SEEDS.get(app.lower(), {})
    data = _blank(app)
    for name, rule in seed.get("rules", {}).items():
        data["rules"][name] = {
            "status": "verified", "broken": False, "verified_ok": 1,
            "steps": rule["steps"], "note": rule.get("note", ""), "history": [],
        }
    data["avoid"] = dict(seed.get("avoid", {}))
    _save(app, data)
    return {"app": app, "seeded": True, "rules": sorted(data["rules"]), "avoid": sorted(data["avoid"])}
