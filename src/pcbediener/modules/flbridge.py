"""FL-Studio-Bruecke: MIDI als strukturierter Kommando-Kanal.

Konzept
-------
Der MCP bedient eine Anwendung ueber Pixel: Koordinaten raten, hoffen, dass
der Klick ankommt, danach aus einem Screenshot schliessen, ob es geklappt
hat. Genau daran scheitert FL Studio - VCL-Popup-Klammern schlucken Klicks,
und FL malt Panel nicht zuverlaessig neu, sodass die Pixel nicht einmal den
Zustand abbilden.

Browser-Bedienung funktioniert, weil sie *nicht* so arbeitet: Sie adressiert
Struktur statt Pixel (``role=button``, name=Import``), haelt stabile
Handles und kann den Zustand abfragen. FL Studio bietet dieselbe Schnitt-
stelle - nur nicht als GUI, sondern als **Skript-Engine**. Diese Bruecke
stellt sie ueber einen virtuellen MIDI-Port bereit:

    PC-Bediener --midiOut--> loopMIDI Port --> device_pcbediener.py --> FL-API
    PC-Bediener <--midiIn--- loopMIDI Port <-- device.midiOutMsg()  <------

Der Bypass ist nicht nur Komfort: Ohne ihn ist nicht *verifizierbar*, ob ein
Regler really auf einem Wert steht. Ueber MIDI wird jede Aktion mit einer
Antwort quittiert, also eine geschlossene Schleife statt Hoffnung.

Protokoll
---------
Senden: jedes Byte als Note-On auf Kanal 1 (``0x90 | ch``, Note = Byte,
Velocity = 127 als Datenmarker). Terminator: Note 127 mit Velocity 0.

Empfangen: Control-Change auf Kanal 16 (``0xBF``), zwei Bytes je Nachricht,
Terminator ``0x7F 0x7F``.
"""

from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
import time
from ctypes import wintypes
from typing import Any

# --- WinMM-Konstanten -------------------------------------------------------

MMSYSERR_NOERROR = 0
MDR_OUT_MIDIPORT = 1          # Callback-Slot fuer Ports (Senden)

MIM_DATA = 0x3C3
MIM_ERROR = 0x3C5
MIM_LONGDATA = 0x3C4

CALLBACK_NULL = 0x00000000
#: WICHTIG: ``midiInOpen`` braucht CALLBACK_FUNCTION, nicht CALLBACK_NULL.
#: Mit CALLBACK_NULL registriert WinMM keinen Callback - die Nachrichten
#: bleiben im Treiberpuffer und kommen nie an. Genau das ist passiert: die
#: Bruecke hat geantwortet, aber nichts kam an.
CALLBACK_FUNCTION = 0x30000000
CALLBACK_EVENT = 0x30000001
CALLBACK_THREAD = 0x30000002

_MIDIERR_UNSPECIFIED = -1
_MIDIERR_BADDEVICE = -2
_MIDIERR_NODRIVER = -10

#: Bytes, die als Terminator dienen.
_ESC = 0x7F

_winmm: Any | None = None
_winmm_err: str | None = None


def _win():
    """WinMM laden. Fehlt es (kein Windows), wird das einmal klar vermerkt."""
    global _winmm, _winmm_err
    if _winmm is not None or _winmm_err is not None:
        return _winmm
    if sys.platform != "win32":
        _winmm_err = "WinMM nur unter Windows"
        return None
    try:
        dll = ctypes.WinDLL("winmm")
    except OSError as exc:
        _winmm_err = f"winmm.dll nicht ladbar: {exc}"
        return None
    # argtypes: ohne sie interpretiert ctypes 64-Bit-Handles falsch und
    # callback-Handles werden zu 32-Bit-Werten - der Aufruf "scheitert
    # lautlos mitten im Port-Handle.
    dll.midiOutGetNumDevs.restype = ctypes.c_uint
    dll.midiOutOpen.argtypes = [
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint,
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
    dll.midiOutOpen.restype = ctypes.c_long
    dll.midiOutClose.argtypes = [ctypes.c_void_p]
    dll.midiOutClose.restype = ctypes.c_long
    dll.midiOutShortMsg.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    dll.midiOutShortMsg.restype = ctypes.c_long
    dll.midiInGetNumDevs.restype = ctypes.c_uint
    dll.midiInOpen.argtypes = [
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint,
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
    dll.midiInOpen.restype = ctypes.c_long
    dll.midiInStart.argtypes = [ctypes.c_void_p]
    dll.midiInStart.restype = ctypes.c_long
    dll.midiInStop.argtypes = [ctypes.c_void_p]
    dll.midiInStop.restype = ctypes.c_long
    dll.midiInClose.argtypes = [ctypes.c_void_p]
    dll.midiInClose.restype = ctypes.c_long
    dll.midiInReset.argtypes = [ctypes.c_void_p]
    dll.midiInReset.restype = ctypes.c_long
    _winmm = dll
    return _winmm


# --- Port-Namen -------------------------------------------------------------

def _port_names() -> dict[int, str]:
    """Port-Index -> Name, so weit ermittelbar.

    ``midiOutGetDevInfo`` fehlt in manchen Windows-Builds als Export. Dann
    wird ueber die Registry nachgeholfen - dort stehen die Geraetenamen der
    WinMM-MIDI-Treiber. Ohne Namen bleibt nur die Index-Notiz; das ist kein
    Fehler, nur weniger bequem.
    """
    dll = _win()
    if dll is None:
        return {}
    names: dict[int, str] = {}

    caps_out = getattr(dll, "midiOutGetDevInfo", None)
    if caps_out is not None:
        class _OutCaps(ctypes.Structure):
            _fields_ = [
                ("wMid", wintypes.WORD), ("wPid", wintypes.WORD),
                ("vdriver", ctypes.c_char * 32), ("vName", ctypes.c_char * 32),
                ("dwSupport", wintypes.DWORD), ("dwChannels", ctypes.c_ulong),
                ("dwNotes", ctypes.c_ulong), ("dwPatches", ctypes.c_ulong),
                ("dwSupport2", ctypes.c_ulong),
            ]

        for i in range(int(dll.midiOutGetNumDevs())):
            caps = _OutCaps()
            try:
                if caps_out(ctypes.c_ulong(i), ctypes.byref(caps)) == 0:
                    names[i] = caps.vName.decode("ascii", "replace")
            except Exception:
                pass

    if not names:
        try:
            import winreg

            key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MIDI Devices"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                i = 0
                while True:
                    try:
                        value, _data, _type = winreg.EnumValue(key, i)
                    except OSError:
                        break
                    i += 1
                    clean = value.replace("#", "").strip()
                    if clean and clean not in names:
                        names[len(names)] = clean
        except Exception:
            pass

    if not names:
        dll_count = int(dll.midiOutGetNumDevs())
        names = {i: f"Port {i}" for i in range(dll_count)}
    return names


def midi_ports() -> dict[str, Any]:
    """Alle verfuegbaren MIDI-Ports mit Index und Name."""
    dll = _win()
    if dll is None:
        return {"available": False, "error": _winmm_err}
    names = _port_names()
    out_count = int(dll.midiOutGetNumDevs())
    in_count = int(dll.midiInGetNumDevs())
    return {
        "available": True,
        "output_ports": [
            {"index": i, "name": names.get(i, f"Port {i}")}
            for i in range(out_count)
        ],
        "input_ports": [
            {"index": i, "name": names.get(i, f"Port {i}")}
            for i in range(in_count)
        ],
        "hint": ("Namen ohne OpenCV/Registry unvollstaendig - Index reicht "
                 "fuer fl_command(port=...)"),
    }


#: Empirisch ermittelter Port (2026-10-08).
#:
#: WinMM liefert auf diesem System keine Geraetenamen, also wurde der Port
#: durch *Wirkung* bestimmt: an jeden Ausgang wurde ein anderes Tempo
#: geschickt (141..146), danach zeigte FLs Tempo-Anzeige 146.000 - Port 5 ist
#: der, auf dem die Bruecke lauscht. FL weist die Bruecke drei Ports zu; nur
#: einer ist aktiv, die anderen sind in den MIDI-Einstellungen deaktiviert.
#:
#: Ueberschreiben mit der Umgebungsvariablen ``PCB_FL_MIDI_PORT`` oder dem
#: ``port``-Parameter.
DEFAULT_PORT = int(os.environ.get("PCB_FL_MIDI_PORT", "5"))


def find_port(substring: str = "loopMIDI") -> int | None:
    """Findet den ersten Port, dessen Name ``substring`` enthaelt.

    Auf Windows 10/11 liefert WinMM haeufig **keine** Geraetenamen mehr
    (``midiOutGetDevInfo`` ist nicht exportiert, der Registry-Schluessel
    ``...\\CurrentVersion\\MIDI Devices`` fehlt, weil die Enumeration ueber
    WASAPI laeuft). Dann gibt diese Funktion ``None`` zurueck - richtig,
    statt einen erfundenen Namen zu liefern. Der Aufrufer nutzt dann
    :func:`probe_ports`.
    """
    dll = _win()
    if dll is None:
        return None
    names = _port_names()
    real = [n for n in names.values() if not n.startswith("Port ")]
    if not real:
        return None
    for i, name in names.items():
        if substring.lower() in name.lower():
            return i
    return None


def probe_ports(command: str = "PING", channel: int = 0) -> dict[str, Any]:
    """Sendet einen Befehl an **alle** Ausgaenge und meldet, wer antwortet.

    Das ersetzt die fehlende Namensauflosung: FL quittiert jeden Befehl, also
    zeigt sich der richtige PortIndex daran, welcher antwortet. Ohne
    antwortenden Port (Bruecke in FL noch nicht zugewiesen) ist das Ergebnis
    trotzdem informativ - es nennt die Zahl der existierenden Ports.
    """
    dll = _win()
    if dll is None:
        return {"error": _winmm_err}
    count = int(dll.midiOutGetNumDevs())
    tried: list[dict[str, Any]] = []
    for index in range(count):
        try:
            res = send(command, port=index, channel=channel)
            tried.append({"port": index, "ok": True, "bytes": res["bytes"]})
        except Exception as exc:
            tried.append({"port": index, "ok": False, "error": str(exc)})
    return {
        "ports_tried": count,
        "results": tried,
        "note": ("Nutze anschliessend fl_listen(start_receiver=True) und "
                 "fl_receive - FL antwortet ueber MIDI-In."),
    }


# --- Senden -----------------------------------------------------------------

def _open_out(port: int) -> ctypes.c_void_p:
    dll = _win()
    if dll is None:
        raise RuntimeError(_winmm_err or "WinMM nicht verfuegbar")
    handle = ctypes.c_void_p()
    rc = dll.midiOutOpen(ctypes.byref(handle), ctypes.c_uint(int(port)),
                         CALLBACK_NULL, 0, CALLBACK_NULL)
    if rc != MMSYSERR_NOERROR:
        hint = {
            _MIDIERR_UNSPECIFIED: "unbekannter Fehler - Port existiert?",
            _MIDIERR_BADDEVICE: "Port-Index ungueltig",
            _MIDIERR_NODRIVER: "kein MIDI-Treiber - laeuft loopMIDI? "
                               "(ohne laufenden Virtual-Port rc=10)",
        }.get(int(rc), "")
        raise RuntimeError(
            f"midiOutOpen(Port {port}) rc={rc}"
            + (f" - {hint}" if hint else "")
        )
    return handle


def send(text: str, port: int | None = None, channel: int = 0,
         timeout: float = 2.0) -> dict[str, Any]:
    """Schickt ein Befehlspaket an die FL-Bruecke.

    Args:
        text: Befehl, z.B. ``"TEMPO 140"`` oder ``"EVAL mixer.getTrackVolume(0)"``.
        port: MIDI-Ausgangsport; ``None`` = erster loopMIDI-Port.
        channel: MIDI-Kanal 0-15 (FL lauscht auf Kanal 1, also 0).
    """
    if not isinstance(text, str):
        raise TypeError("text muss ein String sein")
    if not 0 <= channel <= 15:
        raise ValueError("channel muss zwischen 0 und 15 liegen")

    roh = [ord(c) & 0x7F for c in text[:4000]]
    if len(text) > 4000:
        raise ValueError("Befehl laenger als 4000 Zeichen")
    if _ESC in roh:
        raise ValueError(
            "Befehl enthaelt das Terminator-Zeichen (0x7F) - das wuerde das "
            "Paket vorzeitig beenden. Zeichen ausserhalb 0..127 ebenfalls "
            "problematisch; ASCII-Text verwenden."
        )

    index = DEFAULT_PORT if port is None else port
    if index is None:
        raise RuntimeError(
            "Kein loopMIDI-Port gefunden. Laeuft loopMIDI? "
            "Verfuegbare Ports: " + ", ".join(
                f"{p['index']}:{p['name']}"
                for p in midi_ports().get("output_ports", []))
        )

    handle = _open_out(index)
    gesendet = 0
    try:
        status = 0x90 | (int(channel) & 0x0F)
        for byte in roh:
            msg = (status | (byte << 8) | (127 << 16))
            if dll_short(handle, msg) != 0:
                raise RuntimeError(f"midiOutShortMsg fuer Byte {byte} abgelehnt")
            gesendet += 1
        terminator = status | (_ESC << 8) | (0 << 16)
        if dll_short(handle, terminator) != 0:
            raise RuntimeError("Terminator abgelehnt")
    finally:
        _win().midiOutClose(handle)

    return {
        "sent": True, "bytes": gesendet, "port": index, "channel": channel,
        "command": text, "at": round(time.time(), 3),
    }


def dll_short(handle: ctypes.c_void_p, msg: int) -> int:
    """midiOutShortMsg mit Rueckgabe des Fehlercodes."""
    dll = _win()
    return int(dll.midiOutShortMsg(handle, ctypes.c_ulong(msg & 0xFFFFFFFF)))


# --- Empfangen --------------------------------------------------------------

class _Receiver:
    """Hält einen MIDI-Input-Port offen und sammelt Antwortbytes.

    Der Callback kommt aus einer fremden WinMM-Thread; er darf nichts
    Python-Schweres tun, also legt er nur Bytes in eine Queue. ``close()``
    ist noetig, sonst blockiert ``midiInClose`` auf den Thread.
    """

    def __init__(self, port: int) -> None:
        dll = _win()
        if dll is None:
            raise RuntimeError(_winmm_err or "WinMM nicht verfuegbar")
        self.dll = dll
        self.port = int(port)
        self.queue: queue.Queue[int] = queue.Queue()
        self._bytes = bytearray()
        self._handle = ctypes.c_void_p()
        self._proto = ctypes.WINFUNCTYPE(
            None, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
            ctypes.c_ulong, ctypes.c_ulong)
        self._callback = self._proto(self._on_message)

        rc = dll.midiInOpen(ctypes.byref(self._handle), ctypes.c_uint(self.port),
                            ctypes.cast(self._callback, ctypes.c_void_p),
                            0, CALLBACK_FUNCTION)
        if rc != MMSYSERR_NOERROR:
            raise RuntimeError(f"midiInOpen(Port {self.port}) rc={rc}")
        rc = dll.midiInStart(self._handle)
        if rc != MMSYSERR_NOERROR:
            dll.midiInClose(self._handle)
            raise RuntimeError(f"midiInStart rc={rc}")

    def _on_message(self, _hm, msg, _inst, param1, _param2) -> None:
        if msg != MIM_DATA:
            return
        packed = int(param1) & 0xFFFFFFFF
        size = packed & 0xFFFF
        raw = (packed >> 16) & 0xFF
        if size < 3:
            return
        for b in (raw & 0x7F, (raw >> 7) & 0x7F):
            self.queue.put(b)

    def poll(self) -> str:
        """Holt alles Bis zum Terminator und dekodiert es als Text."""
        while True:
            try:
                byte = self.queue.get(timeout=0.05)
            except queue.Empty:
                break
            if byte == _ESC:
                # Zweites 0x7F bestaetigt das Ende der Antwort
                try:
                    confirm = self.queue.get(timeout=0.5)
                except queue.Empty:
                    confirm = _ESC
                if confirm == _ESC:
                    text = self._bytes.decode("ascii", "replace")
                    self._bytes = bytearray()
                    return text
                self._bytes.append(byte)
                continue
            self._bytes.append(byte)
        return self._bytes.decode("ascii", "replace")

    def close(self) -> None:
        try:
            self.dll.midiInStop(self._handle)
            self.dll.midiInReset(self._handle)
            self.dll.midiInClose(self._handle)
        except Exception:
            pass


_receiver: _Receiver | None = None
_receiver_thread: threading.Thread | None = None


def start_receiving(port: int | None = None) -> dict[str, Any]:
    """Oeffnet den Antwortkanal dauerhaft."""
    global _receiver, _receiver_thread
    if _receiver is not None:
        return {"ok": True, "already_open": True, "port": _receiver.port}
    index = find_port("loopMIDI") if port is None else port
    if index is None:
        raise RuntimeError("Kein loopMIDI-Eingangsport gefunden")
    _receiver = _Receiver(index)

    def _pump() -> None:
        while _receiver is not None:
            _receiver.poll()
            time.sleep(0.1)

    _receiver_thread = threading.Thread(target=_pump, daemon=True)
    _receiver_thread.start()
    return {"ok": True, "port": index}


def stop_receiving() -> dict[str, Any]:
    global _receiver, _receiver_thread
    if _receiver is None:
        return {"ok": True, "already_closed": True}
    _receiver.close()
    _receiver = None
    _receiver_thread = None
    return {"ok": True}


def receive(timeout: float = 3.0) -> dict[str, Any]:
    """Wartet bis zu ``timeout`` Sekunden auf eine Antwort."""
    if _receiver is None:
        raise RuntimeError(
            "Antwortkanal ist nicht offen - erst fl_listen(start_receiver=True)"
        )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = _receiver.poll()
        if text.strip():
            return {"response": text, "port": _receiver.port}
        time.sleep(0.1)
    return {"response": None, "timeout_s": timeout}