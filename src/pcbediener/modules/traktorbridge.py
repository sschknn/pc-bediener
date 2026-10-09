"""TRAKTOR-Bruecke: MIDI als Kommando-Kanal fuer die DJ-Steuerung.

Warum MIDI und nicht Maus
-------------------------
TRAKTOR Pro 4 hat - anders als FL Studio - **keine Skript-API**. Es gibt
``plugins.setParamValue`` nicht, keinen Interpreter, nichts. Der einzige
programmierbare Kanal ist das **Controller-Manager-Mapping**: Traektor lauscht
auf einem MIDI-Port und fuehrt bei einer Note genau eine Funktion aus.

    pcbediener --midiOut--> loopMIDI Port --> Traktor (Generic MIDI)
    Deck A: Ch01.Note.C4  ->  Play/Pause

Damit ist jede Aktion *adressierbar* statt geraten: ein Note-Wert loest exakt
eine Funktion aus. Die Bruecke ist damit auch die Verifikation - es gibt einen
Zustandsrueckkanal, den man abfragen kann.

Voraussetzungen
---------------
Ein Device vom Typ "Generic MIDI" muss in Traktor existieren (In-Port
"All Ports"). Die Zuordnungen selbst werden **programmatisch** in die
Settings-.tsi geschrieben - nicht mehr per GUI-Learn, das ist bei diesem
Setup blind und unzuverlaessig:

    python tools/traktor_mapping.py           # Probelauf
    python tools/traktor_mapping.py --apply   # schreiben (Traktor vorher beenden)

Das Werkzeug klont die Vorlage aus :data:`COMMANDS` in den
``DeviceIO.Config.Controller``-Blob (siehe Modul-Doc von
``tools/traktor_mapping.py``). ``traktorbridge.note_name`` vergibt dabei
dieselben Namen (``Ch01.Note.C4``), die Traktor intern benutzt.

Der GUI-Weg bleibt als Rueckfall erhalten:
  Preferences > Controller Manager
    Device "Generic MIDI", In-Port "All Ports"
    Add In... > Funktion > Assignment = Deck, dann "Learn" + Note senden.

Kommandosendung
---------------
Gesendet wird Note-On auf Kanal 1 (Status ``0x90``), Velocity 127, gefolgt von
einem Note-Off. Der Konkretwert steht in :data:`COMMANDS`.

Der Mapping-Status ist getrennt gefuehrt: :func:`verified` weiss, welche
Zuordnungen in Traektor wirklich bestaetigt wurden. Das trennt "der Code kann
das" von "Traektor kennt das".
"""

from __future__ import annotations

import base64
import ctypes
import os
import re
import struct
from pathlib import Path
from typing import Any, Iterator

from . import flbridge

# --- Kanalkonvention --------------------------------------------------------

#: MIDI-Kanal, **0-basiert**. 0 == MIDI-Kanal 1 == Statusbyte ``0x90``.
#: Wichtig: dieses Modul rechnet durchgaengig 0-basiert (wie WinMM und
#: ``flbridge``). Traktor zeigt im Controller Manager die *1-basierte*
#: Schreibweise ("Ch01"), das ist derselbe Kanal.
CHANNEL = 0

#: Velocity fuer einen Tastendruck. 127 = maximal, fuer "gedrueckt".
VELOCITY = 127

#: Standard-Ausgangsport. Ueberschreiben mit ``PCB_TRAKTOR_MIDI_PORT`` oder
#: dem ``port``-Argument. WinMM liefert auf diesem System keine Geraetenamen,
#: der Index ist deshalb empirisch gesetzt (siehe ``flbridge.probe_ports``).
DEFAULT_PORT = int(os.environ.get("PCB_TRAKTOR_MIDI_PORT", "1"))

#: Ein Web aus Tastendruecken, das Traektor als "Hold" wertet, wird mit
#: :data:`VELOCITY` gesendet und direkt mit Note-Off beantwortet.
_PULSE_S = 0.05

#: Noten, deren Traktor-Kommando den Interaktionsmodus **Hold** verlangt
#: (nur so zugelassen): die Hot Cues (Command 2328 "Select/Set+Store Hotcue").
#: Gemessen: mit 50 ms passiert nichts, mit 350 ms wird der Marker gesetzt.
HOLD_NOTES: frozenset[int] = frozenset({36, 37, 38, 39, 40, 41, 42, 43})
_HOLD_S = 0.35


# --- Kommandoregister -------------------------------------------------------

#: note -> (name, Klartext, Deck)
#:
#: ``name`` ist der stabile Aufruf-Schluessel fuer :func:`trigger` und
#: :func:`verified` - er wird bewusst *nicht* aus dem Klartext abgeleitet,
#: weil Slugging unzuverlaessig ist ("Play/Pause Deck A" -> "playpause_deck_a").
#:
#: WICHTIG: Traktor kennt nur die Zuordnungen, die in der Assignment Table
#: stehen. Diese Tabelle ist der *Wunsch*; :data:`CONFIRMED` haelt fest, was
#: bereits verifiziert ist.
COMMANDS: dict[int, tuple[str, str, str]] = {
    # --- Transport ---
    60: ("play_a", "Play/Pause Deck A", "A"),
    62: ("play_b", "Play/Pause Deck B", "B"),
    64: ("play_c", "Play/Pause Deck C", "C"),
    65: ("play_d", "Play/Pause Deck D", "D"),
    66: ("cue_a", "Cue Deck A", "A"),
    67: ("cue_b", "Cue Deck B", "B"),
    # --- Sync ---
    68: ("sync_a", "Sync Deck A", "A"),
    69: ("sync_b", "Sync Deck B", "B"),
    70: ("sync_c", "Sync Deck C", "C"),
    71: ("sync_d", "Sync Deck D", "D"),
    # --- Hot Cues ---
    36: ("hotcue_a1", "Hot Cue 1 Deck A", "A"),
    37: ("hotcue_a2", "Hot Cue 2 Deck A", "A"),
    38: ("hotcue_a3", "Hot Cue 3 Deck A", "A"),
    39: ("hotcue_a4", "Hot Cue 4 Deck A", "A"),
    40: ("hotcue_b1", "Hot Cue 1 Deck B", "B"),
    41: ("hotcue_b2", "Hot Cue 2 Deck B", "B"),
    42: ("hotcue_b3", "Hot Cue 3 Deck B", "B"),
    43: ("hotcue_b4", "Hot Cue 4 Deck B", "B"),
    # --- Laden ---
    72: ("load_a", "Load Next in Deck A", "A"),
    73: ("load_b", "Load Next in Deck B", "B"),
}

#: Nur diese Zuordnung ist bisher in Traektor angelegt und ueber MIDI-Learn
#: bestaetigt worden. Alles andere ist vorbereitet, aber *nicht* belegt - die
#: Bruecke meldet das ehrlich statt Erfolg zu behaupten.
CONFIRMED: frozenset[int] = frozenset({60})


# --- CC-Register (Mixer: Fader & Crossfader) --------------------------------
#
# Fader und Regler laufen in Traktor **nicht** ueber Noten, sondern ueber
# Control-Change mit Interaction "Direct": der CC-Wert (0..127) bildet direkt
# den Parameter (0..1) ab. Deshalb ein eigenes Register; die Bindungsnamen
# heissen "Ch01.CC.<nnn>". Die CMAD-Vorlagen kommen 1:1 aus einem Werksmapping
# (siehe ``tools/traktor_mapping.py``), weil Noten-CMADs (Toggle) die
# Direct-Level-Regel nicht treffen.
CC_COMMANDS: dict[int, tuple[str, str]] = {
    20: ("vol_a", "Mixer Volume Deck A"),
    21: ("vol_b", "Mixer Volume Deck B"),
    22: ("xfader", "X-Fader Position"),
}


def cc_number(name: str) -> int:
    """Slug eines Mixer-Kommandos -> CC-Nummer (``"vol_a"`` -> ``20``)."""
    for cc, (key, _desc) in CC_COMMANDS.items():
        if key == name:
            return cc
    raise KeyError(
        f"unbekanntes CC-Kommando {name!r}; bekannt: "
        + ", ".join(sorted(k for k, _d in CC_COMMANDS.values()))
    )


# --- Mapping-Erkennung aus der Traktor-Konfiguration ------------------------
#
# Seit die Zuordnungen programmatisch in den ``DeviceIO.Config.Controller``-
# Blob geschrieben werden (siehe ``tools/traktor_mapping.py``), muss die
# Bruecke ihren Status nicht mehr raten: sie liest aus der Settings-.tsi,
# welche Noten tatsaechlich gemappt sind. Das ist die belastbare Quelle -
# ``CONFIRMED`` bleibt nur der Rueckfall, wenn die Datei fehlt.

#: Traktor legt die Settings je Version in einem eigenen Ordner ab.
_TSI_GLOB = "Native Instruments/Traktor */Traktor Settings.tsi"

#: Traktor schreibt Oktaven ab C-1 == MIDI 0.
_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_NAME_TO_SEMI = {n: i for i, n in enumerate(_NAMES)}


def settings_path() -> Path | None:
    """Findet die aktive ``Traktor Settings.tsi`` (neueste Version)."""
    matches = sorted((Path.home() / "Documents").glob(_TSI_GLOB))
    return matches[-1] if matches else None


def note_name(note: int) -> str:
    """MIDI-Note -> Traktor-Name (``60`` -> ``"C4"``)."""
    return f"{_NAMES[note % 12]}{note // 12 - 1}"


def note_from_name(name: str) -> int | None:
    """Traktor-Bindungsname (``"Ch01.Note.C#2"``) -> MIDI-Note."""
    m = re.search(r"\.Note\.([A-G])(#?)(-?\d+)$", name)
    if not m:
        return None
    semi = _NAME_TO_SEMI.get(m.group(1) + m.group(2))
    if semi is None:
        return None
    return (int(m.group(3)) + 1) * 12 + semi


def _iter_frames(b: bytes, off: int, end: int) -> Iterator[tuple[int, bytes, int]]:
    while off + 8 <= end:
        fid = b[off:off + 4]
        if not (fid.isascii() and fid.isalnum()):
            return
        size = struct.unpack(">I", b[off + 4:off + 8])[0]
        nxt = off + 8 + size
        if nxt > end:
            return
        yield off, fid, size
        off = nxt


def _walk_bindings(b: bytes, off: int, end: int) -> Iterator[tuple[int, str]]:
    """Durchquert den Blob und liefert ``(bindingId, Name)`` aller DCBM-Leaves."""
    for f_off, fid, size in _iter_frames(b, off, end):
        body = f_off + 8
        bend = body + size
        if fid == b"DIOM":
            yield from _walk_bindings(b, body, bend)
        elif fid == b"DEVS":
            yield from _walk_bindings(b, body + 4, bend)
        elif fid == b"DEVI":
            nlen = struct.unpack(">I", b[body:body + 4])[0]
            yield from _walk_bindings(b, body + 4 + nlen * 2, bend)
        elif fid in (b"DDAT", b"DDCB"):
            yield from _walk_bindings(b, body, bend)
        elif fid == b"DCBM":
            count = struct.unpack(">I", b[body:body + 4])[0]
            p = body + 4
            for _ in range(count):
                sz = struct.unpack(">I", b[p + 4:p + 8])[0]
                lb = p + 8
                bid = struct.unpack(">I", b[lb:lb + 4])[0]
                nl = struct.unpack(">I", b[lb + 4:lb + 8])[0]
                # Traktor speichert die Bindungsnamen als UTF-16**BE** (verifiziert
                # an Werksmappings und an der funktionierenden play_a-Regel). Mit
                # LE gelesen kaeme hier nur Zeichensalat heraus.
                name = b[lb + 8:lb + 8 + nl * 2].decode("utf-16-be", "replace")
                yield bid, name
                p += 8 + sz


def _load_blob(path: Path | None) -> bytes | None:
    p = Path(path) if path else settings_path()
    if p is None or not p.exists():
        return None
    text = p.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'Name="DeviceIO\.Config\.Controller"[^>]*Value="([^"]+)"', text)
    if not m:
        return None
    try:
        return base64.b64decode(m.group(1))
    except Exception:
        return None


def mapped_notes(path: Path | None = None) -> dict[int, str]:
    """Aus der Traktor-Settings gelesene Zuordnungen: ``{note: Name}``.

    Leeres dict, wenn die Datei fehlt oder unlesbar ist.
    """
    blob = _load_blob(path)
    if blob is None:
        return {}
    out: dict[int, str] = {}
    for _bid, name in _walk_bindings(blob, 0, len(blob)):
        note = note_from_name(name)
        if note is not None:
            out[note] = name
    return out


_CC_RE = re.compile(r"\.CC\.(\d+)\s*$")


def cc_from_name(name: str) -> int | None:
    """Traktor-Bindungsname (``"Ch01.CC.020"``) -> CC-Nummer."""
    m = _CC_RE.search(name)
    return int(m.group(1)) if m else None


def mapped_ccs(path: Path | None = None) -> dict[int, str]:
    """Gemappte Mixer-CCs aus der Settings: ``{cc: Bindungsname}``."""
    blob = _load_blob(path)
    if blob is None:
        return {}
    out: dict[int, str] = {}
    for _bid, name in _walk_bindings(blob, 0, len(blob)):
        cc = cc_from_name(name)
        if cc is not None:
            out[cc] = name
    return out


_STATUS_CACHE: tuple[float, frozenset[int]] | None = None


def confirmed_notes(path: Path | None = None, refresh: bool = False) -> frozenset[int]:
    """Noten, die in Traktor wirklich gemappt sind.

    Primaer aus der Settings-.tsi gelesen (nach mtime gecacht); faellt auf
    :data:`CONFIRMED` zurueck, wenn die Datei nicht lesbar ist.
    """
    global _STATUS_CACHE
    p = Path(path) if path else settings_path()
    try:
        mtime = p.stat().st_mtime if p and p.exists() else -1.0
    except OSError:
        mtime = -1.0
    if not refresh and _STATUS_CACHE and _STATUS_CACHE[0] == mtime:
        return _STATUS_CACHE[1]
    mapped = mapped_notes(p)
    result = frozenset(mapped) if mapped else CONFIRMED
    _STATUS_CACHE = (mtime, result)
    return result


# --- Low-Level --------------------------------------------------------------

def _short(handle: Any, msg: int) -> int:
    return flbridge._win().midiOutShortMsg(handle, ctypes.c_ulong(msg))


def note_on(note: int, channel: int = CHANNEL, velocity: int = VELOCITY,
            port: int | None = None, hold: float | None = None) -> dict[str, Any]:
    """Sendet ein Note-On/Note-Off-Paar (Tastendruck mit Loslassen).

    Das Off ist wichtig: bei Interaction Mode *Hold* feuert Traektor sonst
    dauerhaft, und die Bruecke wuerde den naechsten Befehl verschlucken.

    ``hold`` ist die Haltedauer in Sekunden. Ohne Angabe wird fuer
    :data:`HOLD_NOTES` (Hot Cues) automatisch :data:`_HOLD_S` verwendet -
    ein zu kurzer Puls wird von Traktors "Hold"-Interaktion ignoriert.
    """
    if not 0 <= note <= 127:
        raise ValueError(f"note muss 0..127 sein, war {note}")
    if not 0 <= channel <= 15:
        raise ValueError(f"channel muss 0..15 sein, war {channel}")

    index = DEFAULT_PORT if port is None else port
    handle = flbridge._open_out(index)
    status = 0x90 | (channel & 0x0F)
    try:
        rc_on = _short(handle, status | (note << 8) | (velocity << 16))
        if rc_on != 0:
            raise RuntimeError(f"Note-On abgelehnt (rc={rc_on})")
        import time
        if hold is None:
            hold = _HOLD_S if note in HOLD_NOTES else _PULSE_S
        time.sleep(hold)
        rc_off = _short(handle, status | (note << 8))
        if rc_off != 0:
            raise RuntimeError(f"Note-Off abgelehnt (rc={rc_off})")
    finally:
        flbridge._win().midiOutClose(handle)

    entry = COMMANDS.get(note)
    return {"note": note, "channel": channel + 1, "port": index,
            "command": entry[1] if entry else None,
            "command_name": entry[0] if entry else None,
            "verified_in_traktor": note in confirmed_notes()}


def control_change(cc: int, value: int, channel: int = CHANNEL,
                   port: int | None = None) -> dict[str, Any]:
    """Sendet einen Control-Change (Status ``0xB0``).

    ``value`` 0..127. Fuer Direct-Fader ist 0 der Minimal- und 127 der
    Maximalwert; :func:`to_midi_value` rechnet 0.0..1.0 um.
    """
    if not 0 <= cc <= 127:
        raise ValueError(f"cc muss 0..127 sein, war {cc}")
    if not 0 <= value <= 127:
        raise ValueError(f"value muss 0..127 sein, war {value}")
    if not 0 <= channel <= 15:
        raise ValueError(f"channel muss 0..15 sein, war {channel}")

    index = DEFAULT_PORT if port is None else port
    handle = flbridge._open_out(index)
    status = 0xB0 | (channel & 0x0F)
    try:
        rc = _short(handle, status | ((cc & 0x7F) << 8) | ((value & 0x7F) << 16))
        if rc != 0:
            raise RuntimeError(f"Control-Change abgelehnt (rc={rc})")
    finally:
        flbridge._win().midiOutClose(handle)

    entry = CC_COMMANDS.get(cc)
    return {"cc": cc, "value": value, "channel": channel + 1, "port": index,
            "command": entry[1] if entry else None,
            "command_name": entry[0] if entry else None}


def to_midi_value(value: float) -> int:
    """0.0..1.0 -> 0..127 (auf den naechsten Schritt gerundet)."""
    return max(0, min(127, round(value * 127)))


def set_volume(deck: str = "A", value: float = 1.0,
               port: int | None = None) -> dict[str, Any]:
    """Kanal-Fader eines Decks setzen (``value`` 0.0..1.0)."""
    deck = deck.upper()
    if deck not in ("A", "B"):
        raise ValueError("nur Deck A/B haben einen Vol-Mapping")
    return control_change(cc_number("vol_" + deck.lower()),
                          to_midi_value(value), port=port)


def set_xfader(value: float = 0.5, port: int | None = None) -> dict[str, Any]:
    """Crossfader setzen (``value`` 0.0 = links, 1.0 = rechts)."""
    return control_change(cc_number("xfader"), to_midi_value(value), port=port)


# --- High-Level -------------------------------------------------------------

def trigger(name: str, port: int | None = None) -> dict[str, Any]:
    """Loest ein Kommando per Namen aus, z. B. ``trigger("play_a")``."""
    for note, (key, _desc, _deck) in COMMANDS.items():
        if key == name:
            return note_on(note, port=port)
    raise KeyError(
        f"unbekanntes Kommando {name!r}; bekannt: "
        + ", ".join(sorted({k for k, _d, _dk in COMMANDS.values()}))
    )


def play(deck: str = "A", port: int | None = None) -> dict[str, Any]:
    """Play/Pause eines Decks. Wirft, wenn die Zuordnung fehlt."""
    deck = deck.upper()
    note = _lookup("Play/Pause Deck " + deck)
    return note_on(note, port=port)


def hot_cue(deck: str, index: int, port: int | None = None) -> dict[str, Any]:
    """Hot Cue 1..8 eines Decks ausloesen."""
    deck = deck.upper()
    if not 1 <= index <= 8:
        raise ValueError("Hot Cue index muss 1..8 sein")
    note = _lookup(f"Hot Cue {index} Deck {deck}")
    return note_on(note, port=port)


def _lookup(desc: str) -> int:
    for note, (_key, d, _deck) in COMMANDS.items():
        if d == desc:
            return note
    raise KeyError(f"kein Kommando fuer {desc!r}")


# --- Zustand / Diagnose ----------------------------------------------------

def verified(name: str) -> bool:
    """Ist dieses Kommando in Traektor tatsaechlich gemappt?

    ``name`` darf der Slug (``play_a``) oder der Klartext
    (``"Play/Pause Deck A"``) sein.
    """
    key = name.strip().lower()
    for note, (name_key, desc, _deck) in COMMANDS.items():
        if key in (name_key, desc.lower()):
            return note in confirmed_notes()
    raise KeyError(f"unbekanntes Kommando {name!r}")


def status() -> dict[str, Any]:
    """Uebersicht: Ports, gemappte und offene Zuordnungen."""
    ports = flbridge.midi_ports()
    settings = settings_path()
    mapped = mapped_notes(settings)
    confirmed = confirmed_notes(settings)
    ccs = mapped_ccs(settings)
    return {
        "channel": CHANNEL + 1,
        "default_port": DEFAULT_PORT,
        "ports": ports,
        "settings": str(settings) if settings else None,
        "mapped": sorted(mapped),
        "confirmed": sorted(confirmed),
        "pending": sorted(set(COMMANDS) - confirmed),
        "mapped_ccs": sorted(ccs),
        "cc_names": {str(cc): name for cc, name in ccs.items()},
        "note": ("'mapped' kommt direkt aus der Traktor-Settings-.tsi. "
                 "Nur 'pending' ist noch nicht belegt."),
    }


def learn(name: str, port: int | None = None) -> dict[str, Any]:
    """Sendet ein Kommando - zum Benutzen, waehrend Traektor im Learn-Modus ist."""
    return trigger(name, port=port)