"""Scannt alle CMAI-Mappings einer Traktor-.tsi und zeigt die CMAD-Rohwerte.

Kein Bindungs-Namens-Lookup noetig: nur Control-Id, Typ und die 4-Byte-Worte
des CMAD-Frames (int + float) - so laesst sich das Interaction-Encoding
(Toggle/Hold/Direct/Trigger) und das Set-to-Value direkt ablesen.
"""
from __future__ import annotations

import base64
import re
import struct
import sys
from pathlib import Path


def u32(b, o):
    return struct.unpack(">I", b[o:o + 4])[0]


def i32(b, o):
    return struct.unpack(">i", b[o:o + 4])[0]


def f32(b, o):
    return struct.unpack(">f", b[o:o + 4])[0]


def extract(text: str) -> bytes | None:
    m = re.search(r'Name="DeviceIO\.Config\.Controller"[^>]*Value="([^"]+)"', text)
    if m:
        return base64.b64decode(m.group(1))
    best = None
    for m in re.finditer(r'Value="([A-Za-z0-9+/=]{200,})"', text):
        if best is None or len(m.group(1)) > len(best):
            best = m.group(1)
    return base64.b64decode(best) if best else None


def iter_frames(b, off, end):
    while off + 8 <= end:
        fid = b[off:off + 4]
        if not (fid.isascii() and fid.isalnum()):
            return
        size = u32(b, off + 4)
        nxt = off + 8 + size
        if nxt > end:
            return
        yield off, fid.decode(), size
        off = nxt


def find_cmai(b, off, end, out):
    for f_off, fid, size in iter_frames(b, off, end):
        body = f_off + 8
        bend = f_off + 8 + size
        if fid == "DIOM":
            find_cmai(b, body, bend, out)
        elif fid == "DEVS":
            find_cmai(b, body + 4, bend, out)
        elif fid == "DEVI":
            nl = u32(b, body)
            find_cmai(b, body + 4 + nl * 2, bend, out)
        elif fid in ("DDAT", "DDCB"):
            find_cmai(b, body, bend, out)
        elif fid == "CMAS":
            cnt = u32(b, body)
            p = body + 4
            for _ in range(cnt):
                sz = u32(b, p + 4)
                out.append(p)          # p zeigt auf CMAI-Frame-Start
                p += 8 + sz


def dump(b, off):
    size = u32(b, off + 4)
    body = off + 8
    binding = u32(b, body)
    typ = u32(b, body + 4)
    ctrl = u32(b, body + 8)
    s_off = body + 12
    s_id = b[s_off:s_off + 4].decode("ascii", "replace")
    s_size = u32(b, s_off + 4)
    sb = s_off + 8
    n = s_size // 4
    words = [b[sb + 4 * k:sb + 4 * k + 4] for k in range(n)]
    ints = [struct.unpack(">i", w)[0] for w in words]
    floats = [struct.unpack(">f", w)[0] for w in words]
    return binding, typ, ctrl, s_id, s_size, ints, floats


def main():
    tsi = Path(sys.argv[1])
    text = tsi.read_text(encoding="utf-8", errors="replace")
    raw = extract(text)
    if raw is None:
        raise SystemExit("kein Blob")
    out = []
    find_cmai(raw, 0, len(raw), out)
    print(f"{tsi.name}: {len(out)} Mappings, blob {len(raw)}")
    want = None
    if len(sys.argv) > 2:
        want = {int(x) for x in sys.argv[2].split(",")}
    for off in out:
        binding, typ, ctrl, s_id, s_size, ints, floats = dump(raw, off)
        if want and ctrl not in want:
            continue
        print(f"ctrl={ctrl:6d} type={typ} {s_id} size={s_size} "
              f"ints={ints}")


if __name__ == "__main__":
    main()
