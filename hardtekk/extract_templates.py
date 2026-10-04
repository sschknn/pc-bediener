# -*- coding: utf-8 -*-
"""Extrahiert die echten FL-2026-Templates (88-Byte-Item, 70-Byte-Track) als .bin."""
import glob
import os
import struct

candidates = glob.glob(
    r"C:\Users\frank\Documents\Image-Line\FL Studio\Projects\**\*.flp", recursive=True
)
HERE = os.path.dirname(os.path.abspath(__file__))


def events_of(path):
    data = open(path, "rb").read()
    assert data[:4] == b"FLhd" and data[14:18] == b"FLdt"
    pos = 22
    evs = []
    while pos < len(data):
        eid = data[pos]
        pos += 1
        if eid < 64:
            d = data[pos:pos + 1]; pos += 1
        elif eid < 128:
            d = data[pos:pos + 2]; pos += 2
        elif eid < 192:
            d = data[pos:pos + 4]; pos += 4
        else:
            shift = 0; size = 0
            while True:
                b = data[pos]; pos += 1
                size |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
            d = data[pos:pos + size]; pos += size
        evs.append((eid, d))
    return evs


item88 = None
track70 = None
for f in candidates:
    if "HARTTEKK" in f.upper():
        continue
    try:
        evs = events_of(f)
    except Exception:
        continue
    for eid, d in evs:
        if eid == 233 and len(d) >= 88 and item88 is None:
            item88 = d[:88]
            print("Item-Template aus:", os.path.basename(f), "(Blob", len(d), "Bytes)")
        if eid == 238 and len(d) == 70 and track70 is None:
            track70 = d
    if item88 and track70:
        break

assert item88 and len(item88) == 88
assert track70 and len(track70) == 70
open(os.path.join(HERE, "item88.bin"), "wb").write(item88)
open(os.path.join(HERE, "track70.bin"), "wb").write(track70)
print("item88.bin :", item88.hex())
print("track70.bin:", track70.hex())
print("OK")
