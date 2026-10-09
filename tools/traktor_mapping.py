"""Schreibt alle Traktor-Bruecken-Kommandos direkt in Traktor Settings.tsi.

Hintergrund
-----------
Traktor Pro 4 hat keine Skript-API; der einzige Kanal ist das Controller-
Manager-Mapping im ``DeviceIO.Config.Controller``-Blob. Statt per GUI (blind)
lernt dieses Werkzeug die Zuordnungen *programmatisch* an.

Format (reverse-engineered + aus Werksmappings verifiziert):
  Frame    : char[4] Id + uint32 BE size(content without 8-byte header)
  String   : uint32 BE len + wchar_t[len], UTF-16**BE** (no NUL).
             Gilt fuer DEVI-Namen, DDCI/DDCO-"DCDT"-Eintraege UND die
             DCBM-Bindungsnamen. Nur die CMAD-Comment-Zeichenkette ist LE.
  DIOM > DIOI + DEVS > DEVI(name) > DDAT > ... > DDCB > (CMAS + DCBM)
  CMAS     : int count + count * CMAI
  CMAI     : int bindingId + int type + int controlId + CMAD
  CMAD     : 120-byte body, 30 int32 words (Traktor 4)
               word2 = InteractionMode  0=Trigger 1=Toggle 2=Hold 3=Direct 8=Output
               word3 = Deck (0=A,1=B,2=C,3=D)
               word11 = SetValueTo
  DCBM     : int count + count * (int id + string name)
             Der id ist ein freier, geraetelokaler Schluessel; er muss nur
             mit dem bindingId der zugehoerigen CMAI uebereinstimmen. Die
             eigentliche Steuerung steckt im NAMEN (z. B. "Ch01.Note.C4").

Als Vorlage dient das bereits funktionierende ``play_a``-Mapping; nur
InteractionMode, Deck und SetValueTo werden ueberschrieben. **Ausnahme
Hotcue:** hier wird eine Werks-Hotcue-Regel als Vorlage benutzt, weil eine
"hold+value"-Zuordnung zusaetzlich den Wertebereich (min/max) und Flags
traegt. Ein aus ``play_a`` geklonter CMAD (Bereich 0..1 statt -1..7) wurde von
Traktor zwar geladen, aber nicht ausgewertet - der Hotcue blieb wirkungslos.
"""
from __future__ import annotations

import base64
import re
import struct
import sys
from pathlib import Path

TSI = Path(
    r"C:\Users\frank\Documents\Native Instruments\Traktor 4.0.2\Traktor Settings.tsi"
)

# note -> (controlId, interactionWord, deckIndex, setValue)
#   Play/Pause 100, Cue 206, Sync On 125 : switch  -> Toggle (1)
#   Load Next 2176                       : one-shot -> Trigger (0)
#   Select/Set+Store Hotcue 2328         : hold+value -> Hold (2), setValue = cue-1
PLAY, CUE, SYNC, LOAD, HOTCUE = 100, 206, 125, 2176, 2328
TRIGGER, TOGGLE, HOLD = 0, 1, 2


def mapping_plan() -> list[tuple[int, str, int, int, int, int]]:
    """(note, name, controlId, interaction, deck, setValue)"""
    plan = []
    decks = {"A": 0, "B": 1, "C": 2, "D": 3}
    for note, (name, _desc, deck) in _bridge_commands().items():
        d = decks[deck]
        if name.startswith("play_"):
            plan.append((note, name, PLAY, TOGGLE, d, 0))
        elif name.startswith("cue_"):
            plan.append((note, name, CUE, TOGGLE, d, 0))
        elif name.startswith("sync_"):
            plan.append((note, name, SYNC, TOGGLE, d, 0))
        elif name.startswith("load_"):
            plan.append((note, name, LOAD, TRIGGER, d, 0))
        elif name.startswith("hotcue_"):
            idx = int(name[-1])          # 1..4
            plan.append((note, name, HOTCUE, HOLD, d, idx - 1))
    return plan


def _bridge_commands():
    """Importiert COMMANDS aus traktorbridge (ohne pcbediener-Paket)."""
    src = Path(__file__).resolve().parents[1] / "src" / "pcbediener" / "modules" / "traktorbridge.py"
    ns: dict = {}
    text = src.read_text(encoding="utf-8")
    block = text.split("COMMANDS: dict", 1)[1].split("}", 1)[0]
    # Zeilen wie: 60: ("play_a", "Play/Pause Deck A", "A"),
    cmds = {}
    for m in re.finditer(r'(\d+):\s*\("([^"]+)",\s*"([^"]+)",\s*"([^"]+)"\)', block):
        cmds[int(m.group(1))] = (m.group(2), m.group(3), m.group(4))
    if not cmds:
        raise SystemExit("COMMANDS nicht geparst")
    return cmds


NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_name(note: int) -> str:
    return f"{NAMES[note % 12]}{note // 12 - 1}"


def u32(b, o):
    return struct.unpack(">I", b[o:o + 4])[0]


def frame(fid: bytes, content: bytes) -> bytes:
    return fid + struct.pack(">I", len(content)) + content


def read_blob(tsi: Path) -> tuple[bytes, str, re.Match]:
    text = tsi.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'(<Entry[^>]*Name="DeviceIO\.Config\.Controller"[^>]*Value=")([^"]+)(")', text)
    if not m:
        raise SystemExit("DeviceIO.Config.Controller nicht gefunden")
    return base64.b64decode(m.group(2)), text, m


def locate(raw: bytes):
    """Findet DDCB (Mappings-Container) und den darauf folgenden DVST-Frame."""
    # DDAT ist Kind von DEVI; wir suchen einfach den ersten DVST nach DDCB.
    ddcb = raw.find(b"DDCB")
    if ddcb < 0:
        raise SystemExit("DDCB nicht gefunden")
    dvst = raw.find(b"DVST", ddcb)
    if dvst < 0:
        raise SystemExit("DVST nicht gefunden")
    return ddcb, dvst


def existing_cmad(raw: bytes) -> bytes:
    """Body (120 Byte) des ersten CMAD-Frames als Vorlage."""
    i = raw.find(b"CMAI")
    if i < 0:
        raise SystemExit("CMAI nicht gefunden")
    s = i + 8 + 12
    if raw[s:s + 4] != b"CMAD":
        raise SystemExit("CMAD nicht an erwarteter Stelle")
    size = u32(raw, s + 4)
    return raw[s + 8:s + 8 + size]


#: Werksdateien mit Hotcue-Regeln sind teils noch im 116-Byte-Format; in
#: Traktor 4 (120 Byte) unterscheidet sich eine Hotcue-Regel von unserer
#: play_a-Vorlage nur in vier Woertern. Werte aus einer echten Traktor-4-
#: Werksregel (Pioneer DDJ-ERGO, controlId 2328) verifiziert:
#:   Wort  9 = 1        (Flag "hat Wert")
#:   Wort 20 = -1       (Wertebereich min)
#:   Wort 22 = 7        (Wertebereich max)  -> Bereich -1..7 = HotCue 1..8
#:   Wort 26 = 1        (Flag)
HOTCUE_FIELDS = {9: 1, 20: -1, 22: 7, 26: 1}


def build_cmad(template: bytes, interaction: int, deck: int, setvalue: int,
               extra: dict[int, int] | None = None) -> bytes:
    b = bytearray(template)
    struct.pack_into(">i", b, 8, interaction)
    struct.pack_into(">i", b, 12, deck)
    struct.pack_into(">i", b, 44, setvalue)
    if extra:
        for word, value in extra.items():
            struct.pack_into(">i", b, word * 4, value)
    return bytes(b)


def build(raw: bytes) -> bytes:
    template = existing_cmad(raw)
    if len(template) != 120:
        raise SystemExit(f"unerwartete CMAD-Groesse {len(template)}")
    plan = mapping_plan()
    cmas_content = struct.pack(">I", len(plan))
    dcbm_content = struct.pack(">I", len(plan))
    for i, (note, name, ctrl, inter, deck, setval) in enumerate(plan, start=1):
        extra = HOTCUE_FIELDS if ctrl == HOTCUE else None
        cmad = build_cmad(template, inter, deck, setval, extra)
        cmai = struct.pack(">II", i, 0) + struct.pack(">I", ctrl) + frame(b"CMAD", cmad)
        cmas_content += frame(b"CMAI", cmai)
        nm = f"Ch01.Note.{note_name(note)}"
        # WICHTIG: Traktor liest die Bindungsnamen als UTF-16BE (verifiziert an
        # der funktionierenden play_a-Regel und an Werksmappings). Mit LE
        # verwirft Traktor die komplette DCBM-Tabelle lautlos.
        leaf = struct.pack(">I", i) + struct.pack(">I", len(nm)) + nm.encode("utf-16-be")
        dcbm_content += frame(b"DCBM", leaf)

    ddcb = frame(b"DDCB", frame(b"CMAS", cmas_content) + frame(b"DCBM", dcbm_content))

    ddcb_off, dvst_off = locate(raw)
    new = bytearray(raw[:ddcb_off] + ddcb + raw[dvst_off:])
    total = len(new)
    # Vorfahren-Sizes patchen (DIOM 0, DEVS 20, DEVI 32, DDAT 68).
    for off in (0, 20, 32, 68):
        struct.pack_into(">I", new, off + 4, total - off - 8)
    return bytes(new)


def main() -> None:
    apply_ = "--apply" in sys.argv
    raw, text, m = read_blob(TSI)
    new = build(raw)
    print(f"alt: {len(raw)} bytes  ->  neu: {len(new)} bytes")
    plan = mapping_plan()
    print(f"{len(plan)} Mappings:")
    for note, name, ctrl, inter, deck, setval in plan:
        print(f"  note {note:3d} {note_name(note):4s} {name:12s} "
              f"ctrl={ctrl:5d} inter={inter} deck={deck} set={setval}")
    # Bindungsnamen gegen den Blob pruefen (muessen als UTF-16BE vorliegen).
    for note, *_ in plan:
        pat = f"Ch01.Note.{note_name(note)}".encode("utf-16-be")
        assert pat in raw, f"Notenname fehlt im Blob: {note_name(note)}"
    print("alle Notennamen im Definitionsblob vorhanden.")
    if not apply_:
        print("\n(Probelauf; mit --apply schreiben)")
        return
    b64 = base64.b64encode(new).decode("ascii")
    out = text[:m.start(2)] + b64 + text[m.end(2):]
    TSI.write_text(out, encoding="utf-8")
    print(f"geschrieben: {TSI}")


if __name__ == "__main__":
    main()
