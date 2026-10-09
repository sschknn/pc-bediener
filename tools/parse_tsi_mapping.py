"""Reverse-Engineering des Traktor-Controller-Mappings in der .tsi.

Der Wert von ``DeviceIO.Config.Controller`` ist Base64 eines binaeren
Block-Containers (Traktor-intern "NIXML"/DIOM). Dieses Skript walkt die
Blockstruktur und extrahiert die enthaltenen UTF-16LE-Strings, damit klar
wird, wie eine einzelne Zuordnung abgelegt ist.

Aufruf:
    python tools/parse_tsi_mapping.py [pfad-zur-tsi]

Ohne Argument wird die live Settings-Datei gelesen (nur lesend!).
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


def extract_blob(tsi: Path) -> bytes:
    text = tsi.read_text(encoding="utf-8", errors="replace")
    m = re.search(
        r'Name="DeviceIO\.Config\.Controller"[^>]*Value="([^"]+)"', text
    )
    if not m:
        raise SystemExit("DeviceIO.Config.Controller nicht gefunden")
    return base64.b64decode(m.group(1))


def utf16_strings(data: bytes, min_len: int = 3) -> list[tuple[int, str]]:
    """Alle UTF-16LE-Strings mit Offset."""
    out: list[tuple[int, str]] = []
    i = 0
    n = len(data)
    buf = bytearray()
    start = 0
    while i + 1 < n:
        lo, hi = data[i], data[i + 1]
        if hi == 0 and 0x20 <= lo < 0x7F:
            if not buf:
                start = i
            buf.append(lo)
            i += 2
        else:
            if len(buf) >= min_len:
                out.append((start, buf.decode("ascii", "replace")))
            buf = bytearray()
            i += 1
    if len(buf) >= min_len:
        out.append((start, buf.decode("ascii", "replace")))
    return out


def walk_blocks(data: bytes, start: int = 0, depth: int = 0, limit: int = 400):
    """Sehr toleranter Block-Walker: 4-Byte-Tag + 4-Byte-BE-Size."""
    pos = start
    shown = 0
    while pos + 8 <= len(data) and shown < limit:
        tag = data[pos:pos + 4]
        if not tag.isascii() or not bytes(tag).isalnum():
            break
        size = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        if size > len(data) - pos - 8:
            break
        print("  " * depth + f"{tag.decode()} size={size} @ {pos}")
        shown += 1
        pos += 8 + size
    return pos


def main() -> None:
    tsi = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    raw = extract_blob(tsi)
    print(f"Datei     : {tsi}")
    print(f"Blob-Groesse: {len(raw)} bytes")
    print(f"Erste 16 bytes: {raw[:16].hex()}")
    print()

    print("=== Blockstruktur (Top-Level) ===")
    walk_blocks(raw)
    print()

    print("=== UTF-16LE-Strings (Offset: Text) ===")
    strs = utf16_strings(raw)
    print(f"{len(strs)} Strings gefunden")
    for off, s in strs[:200]:
        print(f"  {off:8d}  {s}")
    if len(strs) > 200:
        print(f"  ... {len(strs) - 200} weitere")


if __name__ == "__main__":
    main()
