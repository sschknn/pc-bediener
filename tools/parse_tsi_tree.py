"""Vollstaendiger, rekursiver Parser des Traktor-Controller-Blobs (korrigiert).

Korrektur ggue. der Doku: ``Size`` ist die **Content-Groesse ohne** den
8-Byte-Frame-Header. Naechster Frame = off + 8 + size.

Damit:
  DIOM  Size = Dateilaenge - 8
  DIOI  Size = 4   (nur der int)
"""
from __future__ import annotations

import base64
import re
import struct
import sys
from pathlib import Path

DEFAULT = Path(
    r"C:\Users\frank\Documents\Native Instruments\Traktor 4.0.2\Traktor Settings.tsi"
)

CONTAINERS = {b"DIOM", b"DDAT", b"DDDC", b"DDCB", b"DDCI", b"DDCO", b"CMAS"}


def read_blob(tsi: Path) -> bytes:
    text = tsi.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'Name="DeviceIO\.Config\.Controller"[^>]*Value="([^"]+)"', text)
    if not m:
        raise SystemExit("DeviceIO.Config.Controller nicht gefunden")
    return base64.b64decode(m.group(1))


def u32(b: bytes, off: int) -> int:
    return struct.unpack(">I", b[off:off + 4])[0]


def walk(b: bytes, off: int, end: int, depth: int = 0):
    """Liefert (offset, id, size, depth) aller Frames."""
    while off + 8 <= end:
        fid = b[off:off + 4]
        if not (fid.isascii() and fid.isalnum()):
            return off
        size = u32(b, off + 4)
        nxt = off + 8 + size
        if nxt > end:
            return off
        yield off, fid.decode(), size, depth
        body = off + 8
        if fid == b"DIOM":
            yield from walk(b, body, nxt, depth + 1)
        elif fid == b"DEVI":
            nlen = u32(b, body)
            yield from walk(b, body + 4 + nlen * 2, nxt, depth + 1)
        elif fid in CONTAINERS:
            yield from walk(b, body, nxt, depth + 1)
        elif fid == b"DEVS":
            # int count, dann count * DEVI
            yield from walk(b, body + 4, nxt, depth + 1)
        elif fid == b"DDCI" or fid == b"DDCO":
            yield from walk(b, body + 4, nxt, depth + 1)
        elif fid == b"CMAS":
            yield from walk(b, body + 4, nxt, depth + 1)
        # DCDT, DCBM usw. sind Blaetter
        off = nxt
    return off


def read_wstr(b: bytes, off: int) -> tuple[str, int]:
    n = u32(b, off)
    off += 4
    return b[off:off + n * 2].decode("utf-16-le", "replace"), off + n * 2


def dump_cmai(b: bytes, off: int) -> None:
    size = u32(b, off + 4)
    body = off + 8
    binding = u32(b, body)
    mtype = u32(b, body + 4)
    ctrl = u32(b, body + 8)
    s_off = body + 12
    s_id = b[s_off:s_off + 4].decode("ascii", "replace")
    s_size = u32(b, s_off + 4)
    print(f"  CMAI @ {off} size={size} binding={binding} type={mtype} ctrl={ctrl}")
    print(f"    settings {s_id} size={s_size} hex={b[s_off:s_off+8+s_size].hex()}")
    sb = s_off + 8
    ints = struct.unpack(">10i", b[sb:sb + 40])
    sv = struct.unpack(">f", b[sb + 40:sb + 44])[0]
    clen = u32(b, sb + 44)
    comment = ""
    if clen:
        comment, _ = read_wstr(b, sb + 44)
    rest = b[sb + 44 + clen * 2:s_off + 8 + s_size]
    print(f"    CMAD ints={ints} SetValueTo={sv} CommentLen={clen} Comment={comment!r}")
    print(f"    CMAD rest({len(rest)})={rest.hex()}")


def main() -> None:
    tsi = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    raw = read_blob(tsi)
    print(f"Blob {len(raw)} bytes\n=== Baum ===")
    cmai, dcbm = [], []
    for off, fid, size, depth in walk(raw, 0, len(raw)):
        if depth <= 4 or fid in ("CMAS", "CMAI", "DCBM"):
            print("  " * depth + f"{fid} @ {off} size={size}")
        if fid == "CMAI":
            cmai.append(off)
        if fid == "DCBM":
            dcbm.append(off)
    print(f"\n=== {len(cmai)} CMAI-Mappings ===")
    for off in cmai:
        dump_cmai(raw, off)
    print(f"\n=== DCBM @ {dcbm} ===")
    for off in dcbm:
        size = u32(raw, off + 4)
        print(f"  DCBM @ {off} size={size} hex={raw[off:off+min(size+8,120)].hex()}")


if __name__ == "__main__":
    main()
