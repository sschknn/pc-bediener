# -*- coding: utf-8 -*-
"""Roher FLP-Event-Dump ohne pyflp (FL 2026 hat neue Event-IDs/Structs)."""
import struct
import sys

path = sys.argv[1]
data = open(path, "rb").read()
assert data[:4] == b"FLhd"
hdr_size, fmt, nch, ppq = struct.unpack_from("<Ih2H", data, 4)
print(f"Header: fmt={fmt} channels={nch} ppq={ppq}")
assert data[14:18] == b"FLdt"
pos = 22  # 14 Header + 4 "FLdt" + 4 chunk size

events = []
while pos < len(data):
    eid = data[pos]
    pos += 1
    if eid < 64:
        d = data[pos:pos+1]; pos += 1
    elif eid < 128:
        d = data[pos:pos+2]; pos += 2
    elif eid < 192:
        d = data[pos:pos+4]; pos += 4
    else:
        shift = 0; size = 0
        while True:
            b = data[pos]; pos += 1
            size |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        d = data[pos:pos+size]; pos += size
    events.append((eid, d))

print("Events gesamt:", len(events))

# Arrangement-Bereich: New=99, Name=241, Playlist=233, TrackName=239, TrackData=238, Current=100
ARR = {99, 241, 233, 239, 238, 100}
in_arr = False
for eid, d in events:
    if eid == 99:
        in_arr = True
    if in_arr and eid in ARR:
        print(f"  id={eid} len={len(d)}", d[:16].hex() if eid in (238,) else "")
    if in_arr and eid == 100:
        break

# Playlist-Item-Analyse
for eid, d in events:
    if eid == 233:
        n60, n64, n68, n72 = len(d)/60, len(d)/64, len(d)/68, len(d)/72
        print(f"Playlist-Blob: {len(d)} Bytes -> x60={n60:.2f} x64={n64:.2f} x68={n68:.2f} x72={n72:.2f}")
        # Erstes Item roh
        print("Item[0] 64 Bytes:", d[:64].hex())
        pos_i, pbase, iidx, ln, trk = struct.unpack_from("<IHHIH", d, 0)
        print(f"  position={pos_i} pattern_base={pbase} item_index={iidx} length={ln} track_rvidx={trk}")
        break

# FLVersion (199)
for eid, d in events[:5]:
    if eid == 199:
        print("FLVersion:", d.rstrip(b"\x00").decode("ascii", "replace"))
