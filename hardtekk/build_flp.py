# -*- coding: utf-8 -*-
"""Baut HARTTEKK.flp - ein komplettes FL-Studio-Projekt (Hard Tekk, 155 BPM, deutsche Vocals).

Strategie: rohe FLP-Events in korrekter Reihenfolge in einen pyflp-EventTree
haengen und mit pyflp.save() serialisieren. Anschliessend Roundtrip-Validierung.
"""
import os
import struct

import pyflp
import pyflp._events as _ev


# --- Workaround: pyflp 2.2.1 + Python 3.11 -> EventEnum(id) wirft TypeError,
# --- weil die Enum-Basisklasse keine Member hat. Aufloesung per Subklassen-Suche.
_OrigEventEnum = _ev.EventEnum


def _resolve_event_enum(id_):
    if isinstance(id_, _OrigEventEnum):
        return id_
    for sc in _OrigEventEnum.__subclasses__():
        try:
            if id_ in sc:
                return sc(id_)
        except TypeError:
            continue
    return id_  # Fallback: rohes int (int-Vergleiche funktionieren weiterhin)


_resolve_event_enum.__subclasses__ = _OrigEventEnum.__subclasses__  # fuer pyflp.parse()


_ev.EventEnum = _resolve_event_enum
pyflp.EventEnum = _resolve_event_enum

from pyflp._events import (
    AsciiEvent,
    BoolEvent,
    EventTree,
    I32Event,
    U8Event,
    U16Event,
    U32Event,
    UnicodeEvent,
)
from pyflp.arrangement import (
    ArrangementID,
    ArrangementsID,
    PlaylistEvent,
    TrackEvent,
    TrackID,
)
from pyflp.channel import ChannelID, DisplayGroupID
from pyflp.pattern import NotesEvent, PatternID, PatternsID
from pyflp.project import FileFormat, Project, ProjectID

PPQ = 96
STEP = PPQ // 4          # 24 Ticks = 1 Sechzehntel
BAR = PPQ * 4            # 384 Ticks = 1 Takt
BPM = 155

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(HERE, "samples")
PACKS = r"C:\Program Files\Image-Line\FL Studio 2026\Data\Patches\Packs"
OUT_DIR = r"C:\Users\frank\Documents\Image-Line\FL Studio\Projects"
OUT = os.path.join(OUT_DIR, "HARTTEKK.flp")

# ---------------------------------------------------------------- Events

def u8(i, v):    return U8Event(i, struct.pack("<B", v))
def boolean(i, v): return BoolEvent(i, b"\x01" if v else b"\x00")
def u16(i, v):   return U16Event(i, struct.pack("<H", v))
def u32(i, v):   return U32Event(i, struct.pack("<I", v))
def i32(i, v):   return I32Event(i, struct.pack("<i", v))
def astr(i, s):  return AsciiEvent(i, s.encode("ascii") + b"\x00")
def ustr(i, s):  return UnicodeEvent(i, s.encode("utf-16-le") + b"\x00\x00")


def note(pos, ch, key=60, length=96, vel=100, pan=64, fine=120):
    """24-Byte-Noten-Struct. Defaults = FL-Standard (fine_pitch 120 = Mittellage)."""
    return struct.pack(
        "<IHHIHHBBBBBBBB",
        pos, 0, ch, length, key, 0, fine, 0, 0, 0, pan, vel, 255, 255,
    )


# Echte Byte-Templates aus einer FL-2026-Datei (FL 2026: Item=88 Bytes, Track=70 Bytes)
with open(os.path.join(HERE, "item88.bin"), "rb") as fh:
    ITEM88_TEMPLATE = fh.read()
with open(os.path.join(HERE, "track70.bin"), "rb") as fh:
    TRACK70_TEMPLATE = fh.read()
assert len(ITEM88_TEMPLATE) == 88 and len(TRACK70_TEMPLATE) == 70


def pl_item(pos, pat_iid, length, track):
    """88-Byte-Playlist-Item (FL-2026-Format, Template aus echter Datei)."""
    assert length <= 0xFFFFFFFF
    b = bytearray(ITEM88_TEMPLATE)
    struct.pack_into("<I", b, 0, pos)                # position
    struct.pack_into("<H", b, 6, 20480 + pat_iid)    # item_index
    struct.pack_into("<I", b, 8, length)             # length
    struct.pack_into("<H", b, 12, 500 - track)       # track_rvidx
    return bytes(b)


def track_data(iid):
    """70-Byte-Track-Struct (FL-2026-Format, Template aus echter Datei)."""
    b = bytearray(TRACK70_TEMPLATE)
    struct.pack_into("<I", b, 0, iid)
    return bytes(b)

# ---------------------------------------------------------------- Inhalt

CHANNELS = [  # (Name, Sample) - Reihenfolge = Rack-Index
    ("HT Kick",    PACKS + r"\Drums\Kicks\909 Kick.wav"),
    ("HT Snare",   PACKS + r"\Drums\Snares\909 Snare.wav"),
    ("HT CH",      PACKS + r"\Drums\Hats\909 CH 1.wav"),
    ("HT OH",      PACKS + r"\Drums\Hats\909 OH.wav"),
    ("HT Bass",    SAMPLES + r"\bass.wav"),
    ("HT Lead",    SAMPLES + r"\lead.wav"),
    ("VOX Achtung", SAMPLES + r"\vox_achtung.wav"),
    ("VOX Hart",    SAMPLES + r"\vox_hart.wav"),
    ("VOX Zaehlen", SAMPLES + r"\vox_zaehlen.wav"),
    ("VOX Nacht",   SAMPLES + r"\vox_nacht.wav"),
]
KICK, SNR, CH, OH, BASS, LEAD, VAC, VHT, VZL, VNT = range(10)


def drum(pat_ch, steps, vel=110, length=90, key=60):
    return b"".join(note(s * STEP, pat_ch, key=key, length=length, vel=vel) for s in steps)


PATTERNS = []  # (iid, name, ticks, notes_bytes)

PATTERNS.append((1, "Kick 4x4", BAR, drum(KICK, [0, 4, 8, 12], vel=118)))
PATTERNS.append((2, "Snare 2+4", BAR, drum(SNR, [4, 12], vel=112)))
PATTERNS.append((3, "CH 8ths", BAR, b"".join(
    note(s * STEP, CH, length=20, vel=(100 if s % 4 == 0 else 72)) for s in range(0, 16, 2))))
PATTERNS.append((4, "OH Offbeat", BAR, drum(OH, [2, 6, 10, 14], vel=95, length=60)))
PATTERNS.append((5, "Bass Offbeat", BAR, drum(BASS, [2, 6, 10, 14], vel=112, length=84)))
# Lead-Riff: 2 Takte, 16tel Staccato, A-Moll, aggressiv aufsteigend
riff = []
melody = [69] * 8 + [67] * 4 + [65] * 4 + [69] * 8 + [72] * 2 + [74] * 2 + [76] * 4
for st, key in enumerate(melody):
    riff.append(note(st * STEP, LEAD, key=key, length=18, vel=112))
PATTERNS.append((6, "Lead Riff", 2 * BAR, b"".join(riff)))
PATTERNS.append((7, "VOX Hart", BAR, note(0, VHT, length=BAR, vel=115)))
PATTERNS.append((8, "VOX Zaehlen", BAR, note(0, VZL, length=BAR, vel=115)))
PATTERNS.append((9, "VOX Achtung", BAR, note(0, VAC, length=BAR, vel=115)))
PATTERNS.append((10, "VOX Nacht", 2 * BAR, note(0, VNT, length=2 * BAR, vel=115)))
PATTERNS.append((11, "Snare Roll", BAR, b"".join(
    note(s * STEP, SNR, length=18, vel=60 + int(60 * s / 15)) for s in range(16))))

TRACKS = ["Drums", "Bass+Lead", "Vocals"]

# Playlist: (pattern_iid, start_bar, track)
ITEMS = []
for b in range(0, 4):                       # Intro
    ITEMS += [(1, b, 1), (3, b, 1)]
ITEMS.append((9, 0, 3))
for b in range(4, 8):                       # Groove
    ITEMS += [(1, b, 1), (2, b, 1), (3, b, 1), (4, b, 1), (5, b, 2)]
for b in range(8, 12):                      # Hook
    ITEMS += [(1, b, 1), (2, b, 1), (3, b, 1), (4, b, 1), (5, b, 2), (7, b, 3)]
for b in (12, 13):                          # Build
    ITEMS += [(1, b, 1), (3, b, 1), (11, b, 1)]
ITEMS.append((8, 13, 3))
for b in range(14, 22):                     # Drop 1
    ITEMS += [(1, b, 1), (2, b, 1), (3, b, 1), (4, b, 1), (5, b, 2)]
for b in (14, 16, 18, 20):
    ITEMS.append((6, b, 2))
ITEMS += [(10, 14, 3), (7, 16, 3), (10, 18, 3), (7, 20, 3)]
for b in range(22, 26):                     # Break
    ITEMS.append((3, b, 1))
ITEMS += [(10, 22, 3), (7, 24, 3), (5, 24, 2), (5, 25, 2)]
for b in range(26, 34):                     # Drop 2
    ITEMS += [(1, b, 1), (2, b, 1), (3, b, 1), (4, b, 1), (5, b, 2)]
for b in (26, 28, 30, 32):
    ITEMS.append((6, b, 2))
ITEMS += [(10, 26, 3), (7, 28, 3), (10, 30, 3), (7, 32, 3)]
ITEMS += [(1, 34, 1), (2, 34, 1), (1, 35, 1)]  # Outro

PL_LENGTHS = {6: 2 * BAR, 10: 2 * BAR}  # Pattern, die laenger als 1 Takt sind

# ---------------------------------------------------------------- Aufbau

ev = []
ev.append(astr(ProjectID.FLVersion, "26.1.0.5530"))  # MUSS erstes Event sein (exakt installierte Version)

for iid, (name, path) in enumerate(CHANNELS):
    ev.append(u16(ChannelID.New, iid))
    ev.append(boolean(ChannelID.IsEnabled, True))
    ev.append(u8(ChannelID.Type, 0))  # Sampler
    ev.append(i32(ChannelID.GroupNum, 0))
    ev.append(ustr(getattr(ChannelID, "_Name"), name))
    ev.append(ustr(ChannelID.SamplePath, path))
ev.append(ustr(DisplayGroupID.Name, "Unnamed"))

ev.append(u16(PatternsID.CurrentlySelected, 1))
for iid, name, ticks, notes in PATTERNS:
    ev.append(u16(PatternID.New, iid))
    ev.append(NotesEvent(PatternID.Notes, notes))
    ev.append(u16(PatternID.New, iid))  # FL schreibt New zweimal; pyflp dedupliziert
    ev.append(ustr(PatternID.Name, name))
    ev.append(u32(PatternID.Length, ticks))

ev.append(u16(ArrangementID.New, 0))
ev.append(ustr(ArrangementID.Name, "HARTTEKK"))
pl = b"".join(
    pl_item(bar * BAR, iid, PL_LENGTHS.get(iid, BAR), track) for iid, bar, track in ITEMS
)
from pyflp._events import UnknownDataEvent
ev.append(UnknownDataEvent(ArrangementID.Playlist, pl))  # rohe 88-Byte-Items (pyflp kennt FL-2026-Format nicht)
for i, tname in enumerate(TRACKS, start=1):
    ev.append(TrackEvent(TrackID.Data, track_data(i)))  # Data VOR Name: so gruppiert FL die Tracks
    ev.append(ustr(TrackID.Name, tname))
ev.append(u16(ArrangementsID.Current, 0))  # terminiert den Arrangement-Block (wie echte FLPs)

ev.append(u32(ProjectID.Tempo, BPM * 1000))
ev.append(ustr(ProjectID.Title, "HARTTEKK - 155 BPM"))
ev.append(ustr(ProjectID.Genre, "Hard Tekk"))
ev.append(ustr(ProjectID.Artists, "pc-bediener AI"))

from pyflp._events import IndexedEvent

tree = EventTree(init=[IndexedEvent(r, e) for r, e in enumerate(ev)])

proj = Project(tree, channel_count=len(CHANNELS), ppq=PPQ, format=FileFormat.Project)
os.makedirs(OUT_DIR, exist_ok=True)
pyflp.save(proj, OUT)
print("GESPEICHERT:", OUT, os.path.getsize(OUT), "Bytes")

# ---------------------------------------------------------------- Validierung

ArrangementID.Playlist.type = UnknownDataEvent  # sonst parst pyflp 88-Byte-Items falsch
p = pyflp.parse(OUT)
print("Version:", p.version, "| Tempo:", p.tempo, "| PPQ:", p.ppq, "| Titel:", p.title)
chs = list(p.channels)
print("Channels:", len(chs))
for c in chs:
    sp = getattr(c, "sample_path", None)
    print("  ", c.iid, c.name, "->", sp)
pats = list(p.patterns)
print("Patterns:", len(pats))
for pt in pats:
    print("  ", pt.iid, pt.name, len(list(pt.notes)), "Noten, Laenge", pt.length)
# Arrangement-Validierung roh (pyflp versteht FL-2026-Item-Format nicht)
import pyflp._events as _ev2
pl_evt = None
track_count = 0
for e in p.events:
    if e.id == ArrangementID.Playlist:
        pl_evt = e
    if e.id == TrackID.Data:
        track_count += 1
assert pl_evt is not None
raw = bytes(pl_evt)
# varint-Laenge ueberspringen
i = 1
shift = 0
dlen = 0
while True:
    bb = raw[i]; i += 1
    dlen |= (bb & 0x7F) << shift
    if not (bb & 0x80):
        break
    shift += 7
print("Playlist-Blob:", dlen, "Bytes =", dlen // 88, "Items a 88 Bytes | Tracks:", track_count)
assert dlen == len(ITEMS) * 88, "Item-Groessen stimmen nicht!"
print("VALIDIERUNG OK")
