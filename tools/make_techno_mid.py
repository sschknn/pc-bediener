"""Erzeugt eine Techno-Schleife als SMF-Datei fuer den FL-Studio-Import.

Warum MIDI statt Pixel-Klicks
----------------------------
Der FL-Studio-MIDI-Import baut Patterns UND Playlist-Clips selbst auf. Das
spart Hunderte von Klicks im Step-Sequencer und im Playlist - und genau
diese Klicks sind laut Programm-Gedächtnis die gefährliche Stelle
(``PLAYLIST_DANGER_ZONE``: zweimal irreparabel zerstörte Clips). Der
Programm-Stand (``HARTTEKK_flp_stuerzt_fl_ab``) belegt ausserdem, dass der
Weg über .flp-Dateien FL zum Absturz brachte. MIDI ist ein dritter Weg:
Standardformat, vom Import-Dialog erzeugt, ohne Handarbeit am Rechner.

Der Song: 140 BPM (techno-Standard), F-Moll, 4 Takte, 5 Spuren.
BPM steckt als FF 51 im MIDI - FL übernimmt das beim Import, also muss das
Tempo-Feld nicht angefasst werden (das hat laut Gedächtnis keinen Edit-Modus).

Aufruf:  .venv\\Scripts\\python.exe tools\\make_techno_mid.py [zielpfad]
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

# --- Formale Parameter -------------------------------------------------------

BPM = 140.0
BARS = 32
TPQ = 480                      # Ticks pro Viertelnote
STEP = TPQ // 4                # eine Sechzehntnote = 120 Ticks
BAR = TPQ * 4                  # ein Takt = 1920 Ticks

MICROSECONDS = int(round(60_000_000 / BPM))   # 428571 fuer 140 BPM

# F-Moll. MIDI-Nummern: C4 = 60.
F2, AB2, C3, EB3 = 41, 44, 48, 51
F3, AB3, C4, D4, EB4, F4, G4, AB4, C5 = 53, 56, 60, 62, 63, 65, 67, 68, 72

# --- Arrangement -------------------------------------------------------------
#
# Statt 32 mal identischem Material bekommt jeder Takt eine Maske. Das ist der
# Unterschied zwischen einem Loop und einem Song: der Drop baut sich auf, ein
# Breakaway bei Takt 17 macht Spannung, Takt 24 ist die Breakdown vor dem
# letzten Durchlauf. Beim Import legt FL daraus **ein** Pattern ueber 32 Takte
# an - und dieses wird dann mit genau fuenf kurzen Drags in die Playlist
# gemalt (einer pro Spur). Mehr braucht es nicht.
#
# K = Kick, H = Hats, C = Clap, B = Bass, S = Stab
ARRANGEMENT: tuple[str, ...] = (
    "K",                                     # 1  Intro: nur der Puls
    "K",                                     # 2
    "KH",                                    # 3  Hi-Hats kommen
    "KH",                                    # 4
    "KHCB",                                  # 5  Groove: Bass + Clap
    "KHCB",                                  # 6
    "KHCB",                                  # 7
    "KHCB",                                  # 8
    "KHCBS",                                 # 9  Drop: Stab dazu
    "KHCBS",                                 # 10
    "KHCBS",                                 # 11
    "KHCBS",                                 # 12
    "KHCBS",                                 # 13
    "KHCBS",                                 # 14
    "KHCBS",                                 # 15
    "KH",                                    # 16 Build: alles raus
    "KH",                                    # 17 Breakaway
    "KHCBS",                                 # 18 Drop zurueck
    "KHCBS",                                 # 19
    "KHCBS",                                 # 20
    "KHCBS",                                 # 21
    "KHCBS",                                 # 22
    "KHCBS",                                 # 23
    "KHCB",                                  # 24 Breakdown vor dem Finale
    "KHCBS",                                 # 25 Letzter Durchlauf
    "KHCBS",                                 # 26
    "KHCBS",                                 # 27
    "KHCBS",                                 # 28
    "KHCBS",                                 # 29
    "KHCBS",                                 # 30
    "KHCBS",                                 # 31
    "KHCBS",                                 # 32
)


# --- Minimaler SMF-Writer ----------------------------------------------------

def _varlen(value: int) -> bytes:
    """MIDI-Variable-Length-Quantity."""
    if value < 0:
        raise ValueError("VarLen kann nicht negativ sein")
    out = bytearray([value & 0x7F])
    value >>= 7
    while value:
        out.insert(0, (value & 0x7F) | 0x80)
        value >>= 7
    return bytes(out)


class Track:
    """Eine MIDI-Spur: sammelt (absolute Ticks, Event-Bytes)."""

    def __init__(self, name: str, channel: int) -> None:
        self.name = name
        self.channel = channel
        self._events: list[tuple[int, int, bytes]] = []

    def add(self, tick: int, priority: int, data: bytes) -> None:
        self._events.append((tick, priority, data))

    def note(self, tick: int, key: int, velocity: int, length: int) -> None:
        """Note an/ab mit fester Length in Ticks (kein laufendes Sustain)."""
        if velocity <= 0:
            return
        self.add(tick, 2, bytes([0x90 | self.channel, key, velocity]))
        self.add(tick + max(1, length), 1,
                 bytes([0x80 | self.channel, key, 0x40]))

    def program(self, number: int) -> None:
        self.add(0, 0, bytes([0xC0 | self.channel, number]))

    def to_bytes(self) -> bytes:
        chunks: list[bytes] = []
        name = self.name.encode("ascii", "replace")
        chunks.append(_varlen(0) + b"\xFF\x03" + _varlen(len(name)) + name)
        # WICHTIG: MIDI schreibt *Delta*-Zeiten, nicht absolute Ticks. Mit
        # absoluten Werten laeuft die Spur quasi sofort ins Overflow und FL
        # importiert entweder nichts oder eine zerhackte Zeitachse. Nach der
        # Sortierung wird deshalb durch Subtraktion der Abstand gebildet.
        #
        # Reihenfolge bei gleicher Zeit: Note-off (priority 1) vor Note-on
        # (priority 2), damit ein Repeated Note nicht abgeschnitten wird.
        previous = 0
        for tick, _prio, data in sorted(self._events):
            delta = tick - previous
            if delta < 0:
                raise AssertionError(
                    f"{self.name}: Delta negativ ({delta}) - Sortierung kaputt")
            chunks.append(_varlen(delta) + data)
            previous = tick
        chunks.append(_varlen(0) + b"\xFF\x2F\x00")
        body = b"".join(chunks)
        return b"MTrk" + struct.pack(">I", len(body)) + body


def tempo_track() -> bytes:
    """Spur 0: Tempo- und Taktart-Angaben (ohne Noten)."""
    chunks: list[bytes] = []
    name = b"TECHNO 140"
    chunks.append(_varlen(0) + b"\xFF\x03" + _varlen(len(name)) + name)
    # FF 51 03 <Mikrosekunden pro Viertelnote>
    chunks.append(_varlen(0) + b"\xFF\x51\x03"
                  + struct.pack(">I", MICROSECONDS)[1:])
    # FF 58 04 04 02 18 08 -> 4/4, 24 MIDI-Clocks je Viertel, 8 32tel
    chunks.append(_varlen(0) + b"\xFF\x58\x04\x04\x02\x18\x08")
    chunks.append(_varlen(0) + b"\xFF\x2F\x00")
    body = b"".join(chunks)
    return b"MTrk" + struct.pack(">I", len(body)) + body


def build() -> bytes:
    tracks = [Track("KICK", 0), Track("CLAP", 1), Track("HATS", 2),
              Track("BASS", 3), Track("STAB", 4)]
    kick, clap, hats, bass, stab = tracks

    kick.program(0)          # GM 1  Acoustic Grand
    clap.program(9)          # GM 10  Celesta (Proxy fuer Handclap)
    hats.program(9)
    bass.program(33)         # GM 34  Electric Bass (fingers)
    stab.program(81)         # GM 82  Lead 1 (square) -> techno Stab

    # Bass-Riff, Sechzehntenschritte innerhalb eines Takts.
    riff = [
        (0, F2), (3, F2), (4, AB2), (6, F2),
        (8, C3), (11, EB3), (12, C3), (14, F2),
    ]

    for bar in range(BARS):
        base = bar * BAR
        mask = set(ARRANGEMENT[bar])
        # Variante alle 4 Takte -> das 4-Takt-Motiv bleibt musikalisch,
        # waehrend die 32 Takte nicht wie eine Kopie wirken.
        phrase = bar % 4

        if "K" in mask:
            # Four-on-the-floor auf jedem Viertel
            for beat in range(4):
                kick.note(base + beat * TPQ, 36, 120, 90)

        if "C" in mask:
            # Clap auf 2 und 4 (Offbeat)
            for beat in (1, 3):
                clap.note(base + beat * TPQ, 39, 105, 110)

        if "H" in mask:
            # geschlossen auf jedem ungeraden 16tel, offen auf dem
            # vorletzten 16tel jedes Takts
            for step in range(16):
                if step % 2 == 1:
                    hats.note(base + step * STEP, 42, 62, 55)
            hats.note(base + 14 * STEP, 46, 88, 260)

        if "B" in mask:
            # treibendes 16tel-Riff; im 2. und 4. Takt der Phrase eine
            # Oktave hoeher = Spannung
            for step, key in riff:
                octave = 12 if phrase in (1, 3) else 0
                length = STEP * (2 if step % 4 else 3)
                bass.note(base + step * STEP, key + octave, 112, length)

        if "S" in mask:
            # minor-Akkord-Arpeggio auf den ungeraden 16teln; in der zweiten
            # Haelfte der Phrase lauter -> der Stab "faehrt" an
            arp = [F3, AB3, C4, EB4, F4, EB4, C4, AB3]
            for i, key in enumerate(arp):
                velocity = 78 if phrase in (1, 3) else 58
                stab.note(base + i * 2 * STEP, key, velocity, STEP)

    header = (b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks) + 1, TPQ))
    return header + tempo_track() + b"".join(t.to_bytes() for t in tracks)


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else (
        Path(__file__).resolve().parents[1] / "hardtekk" / "techno_140.mid")
    target.parent.mkdir(parents=True, exist_ok=True)
    data = build()
    target.write_bytes(data)

    # Gegenprobe: die Datei muss als SMF lesbar sein und die Spuren
    # muessen die erwarteten Namen tragen - daran haengt spaeter, wie FL die
    # Patterns benennt.
    assert data[:4] == b"MThd", "kein SMF-Header"
    assert struct.unpack(">H", data[8:10])[0] == 1, "Format muss 1 sein"
    count = struct.unpack(">H", data[10:12])[0]
    assert len(ARRANGEMENT) == BARS, \
        f"Arrangement hat {len(ARRANGEMENT)} Eintraege, BARS ist {BARS}"
    print(f"{target}  ({len(data)} Bytes, {count} Spuren)")
    print(f"BPM {BPM:g}, {BARS} Takte, {BARS * 4 * 60 / BPM:.1f} s, "
          f"{MICROSECONDS} us/Viertel, F-Moll")
    print("Aufbau: " + " ".join(
        f"{i + 1}:{m}" for i, m in enumerate(ARRANGEMENT)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))