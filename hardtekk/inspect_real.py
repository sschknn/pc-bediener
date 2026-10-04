# -*- coding: utf-8 -*-
"""Analysiert eine echte FL-2026-FLP: Playlist/Track-Event-Struktur."""
import struct
import sys

import pyflp
import pyflp._events as _ev

_Orig = _ev.EventEnum
def _res(i):
    if isinstance(i, _Orig):
        return i
    for sc in _Orig.__subclasses__():
        try:
            if i in sc:
                return sc(i)
        except TypeError:
            pass
    try:
        return _Orig._missing_(i)  # Pseudo-Member fuer unbekannte IDs (wie Original)
    except Exception:
        return i
_res.__subclasses__ = _Orig.__subclasses__
_ev.EventEnum = _res
pyflp.EventEnum = _res

from pyflp.arrangement import ArrangementID, ArrangementsID, TrackID, PlaylistEvent

path = sys.argv[1]
p = pyflp.parse(path)
print("Version:", p.version, "| PPQ:", p.ppq, "| Tempo:", p.tempo)

# Rohe Events in Reihenfolge, Arrangement-Bereich
in_arr = False
for e in p.events:
    if e.id == ArrangementID.New:
        in_arr = True
    if in_arr:
        size = ""
        if isinstance(e, PlaylistEvent):
            size = " DATABYTES=%d" % len(bytes(e))
        if e.id == TrackID.Data:
            size = " DATABYTES=%d" % len(bytes(e))
        print(int(e.id), type(e.id).__name__ + "." + e.id.name, type(e).__name__, size)
    if in_arr and e.id == ArrangementsID.Current:
        break

# Playlist-Item-Groesse bestimmen
for e in p.events:
    if isinstance(e, PlaylistEvent):
        raw = bytes(e)
        # bytes(e) = id + varint-len + data; Data extrahieren
        print("PlaylistEvent total serialisiert:", len(raw))
        # data length via varint nach id-byte
        data_len = 0
        shift = 0
        i = 1
        while True:
            b = raw[i]; i += 1
            data_len |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        print("Playlist-Daten:", data_len, "Bytes ->", data_len / 60, "x60 |", data_len / 64, "x64 |", data_len / 68, "x68 |", data_len / 72, "x72")
        break

# Arrangements/Tracks/Items via Modelle
for a in p.arrangements:
    print("Arrangement:", a.name)
    for t in a.tracks:
        items = list(t)
        print("  Track:", t.name, "Items:", len(items))
        for it in items[:5]:
            print("     pos", it.position, "len", it.length, dict(it.item) if hasattr(it, 'item') else '')
