"""Dump aller Mappings aus einer Traktor-.tsi (Settings oder Einzelmapping).

Loest die DCBM-Bindings (Id -> MIDI-Name) auf und zeigt je CMAI:
  Binding-Id, Name, Typ(In/Out), TraktorControlId, InteractionMode, Deck,
  ControllerType, SetValueTo.

Damit laesst sich aus Werksmappings (z. B. S4) das exakte Encoding von
Trigger/Hold/Toggle und Hotcue-Werten ablesen.
"""
from __future__ import annotations

import base64
import re
import struct
import sys
from pathlib import Path

# Bedeutung der Interaction-Codes (ivanz-Spec)
INTERACTION = {
    1: "Toggle", 2: "Hold", 3: "Direct", 4: "Relative",
    5: "Increment", 6: "Decrement", 7: "Reset", 8: "Output",
}
CONTROLLER = {0: "Button", 1: "Fader/Knob", 2: "Encoder", 65535: "LED"}
DECK = {-1: "DeviceTarget", 0: "A", 1: "B", 2: "C", 3: "D",
        4: "RD2S1", 5: "RD2S2", 6: "RD2S3", 7: "RD2S4"}


def u32(b: bytes, off: int) -> int:
    return struct.unpack(">I", b[off:off + 4])[0]


def i32(b: bytes, off: int) -> int:
    return struct.unpack(">i", b[off:off + 4])[0]


def f32(b: bytes, off: int) -> float:
    return struct.unpack(">f", b[off:off + 4])[0]


def wstr(b: bytes, off: int) -> tuple[str, int]:
    n = u32(b, off)
    off += 4
    return b[off:off + n * 2].decode("utf-16-le", "replace"), off + n * 2


def extract_blob(text: str) -> bytes | None:
    # Settings: bestimmter Eintrag. Einzelmapping: erster grosser Base64-Wert.
    m = re.search(r'Name="DeviceIO\.Config\.Controller"[^>]*Value="([^"]+)"', text)
    if m:
        return base64.b64decode(m.group(1))
    best = None
    for m in re.finditer(r'Value="([A-Za-z0-9+/=]{200,})"', text):
        if best is None or len(m.group(1)) > len(best):
            best = m.group(1)
    return base64.b64decode(best) if best else None


def iter_frames(b: bytes, off: int, end: int):
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


def collect(b: bytes, off: int, end: int, out: dict):
    """Sammelt DCBM-Bindings und CMAI-Mappings rekursiv."""
    for f_off, fid, size in iter_frames(b, off, end):
        body = f_off + 8
        bend = f_off + 8 + size
        if fid == "DIOM":
            collect(b, body, bend, out)
        elif fid == "DEVS":
            collect(b, body + 4, bend, out)
        elif fid == "DEVI":
            nlen = u32(b, body)
            collect(b, body + 4 + nlen * 2, bend, out)
        elif fid == "DDAT":
            collect(b, body, bend, out)
        elif fid == "DDCB":
            collect(b, body, bend, out)
        elif fid == "DCBM":
            # Container: int count, dann count * DCBM(leaf)
            cnt = u32(b, body)
            p = body + 4
            for _ in range(cnt):
                sz = u32(b, p + 4)
                lb = p + 8
                bid = u32(b, lb)
                name, _ = wstr(b, lb + 4)
                out["bindings"][bid] = name
                p += 8 + sz
        elif fid == "CMAS":
            cnt = u32(b, body)
            p = body + 4
            for _ in range(cnt):
                sz = u32(b, p + 4)
                lb = p + 8
                out["mappings"].append((lb, sz))
                p += 8 + sz
        elif fid == "DDDC":
            collect(b, body, bend, out)


def dump_mapping(b: bytes, off: int, bindings: dict) -> dict:
    binding = u32(b, off)
    mtype = u32(b, off + 4)
    ctrl = u32(b, off + 8)
    s_off = off + 12
    s_size = u32(b, s_off + 4)
    sb = s_off + 8
    ctrltype = u32(b, sb + 4)
    inter = u32(b, sb + 8)
    deck = i32(b, sb + 12)
    setval = f32(b, sb + 40)
    clen = u32(b, sb + 44)
    comment = ""
    if clen:
        comment, _ = wstr(b, sb + 44)
    return {
        "binding": binding, "name": bindings.get(binding, "?"),
        "type": "Out" if mtype else "In", "ctrl": ctrl,
        "ctrltype": CONTROLLER.get(ctrltype, ctrltype),
        "interaction": INTERACTION.get(inter, inter),
        "deck": DECK.get(deck, deck), "setval": setval,
        "comment": comment,
    }


def main() -> None:
    tsi = Path(sys.argv[1])
    text = tsi.read_text(encoding="utf-8", errors="replace")
    raw = extract_blob(text)
    if raw is None:
        raise SystemExit("kein Mapping-Blob gefunden")
    out = {"bindings": {}, "mappings": []}
    collect(raw, 0, len(raw), out)
    print(f"{tsi.name}: {len(out['bindings'])} Bindings, "
          f"{len(out['mappings'])} Mappings\n")
    want = None
    if len(sys.argv) > 2:
        want = {int(x) for x in sys.argv[2].split(",")}
    for off, sz in out["mappings"]:
        d = dump_mapping(raw, off, out["bindings"])
        if want and d["ctrl"] not in want:
            continue
        print(f"ctrl={d['ctrl']:5d} {d['name']:16s} {d['type']:3s} "
              f"{d['ctrltype']:9s} inter={d['interaction']:9s} "
              f"deck={d['deck']:6s} setval={d['setval']:.2f} {d['comment']}")


if __name__ == "__main__":
    main()
