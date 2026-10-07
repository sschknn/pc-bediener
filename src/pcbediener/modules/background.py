"""Modul E – Hintergrund-Automation: Fenster bedienen ohne Fokuswechsel.

Alle Aktionen in diesem Modul bewegen NICHT die echte Maus, verändern den
Vordergrund NICHT und klauen dem Benutzer deswegen nicht die Kontrolle:
Text setzen über UIA ``ValuePattern``/``EM_SETTEXT``, Buttons anklicken über
UIA ``InvokePattern``, Menüs per ``menu_select``.

Damit kann der Benutzer nebenbei weiter Maus/Tastatur am aktiven Fenster
benutzen, während die KI im Hintergrund ein anderes Fenster steuert.
Fallback: PostMessage-Tastenkombinationen (z. B. Strg+S) funktionieren bei
Klassik-Apps; neue WinUI-Apps brauchen ``menu_select`` oder
``window_invoke`` auf den passenden Tree-Item.
"""

from __future__ import annotations

import ctypes
import threading
import time
from typing import Any

from ..config import Config  # noqa: F401 – Rückgabewerte tragen cfg-Typ

Bennennung = dict[str, Any]

#: Marker pro Thread: COM ist dort schon als STA initialisiert.
#:
#: ``pythoncom.CoInitialize()`` ist ein Zähler, kein Flag – jeder Aufruf
#: erhöht ihn um eins, und nur ``CoUninitialize()`` baut ihn ab. Ein Aufruf
#: pro Tool-Call ließ den Zähler im stundenlang laufenden MCP-Server
#: unbegrenzt wachsen; danach war die UIA-Schnittstelle des Prozesses
#: verklemmt und Modul E antwortete nur noch mit "Error executing tool ...".
#: Einmal pro Thread initialisieren und bewusst *nicht* abbauen: der Thread
#: soll für die Lebensdauer STA bleiben, genau das will pywinauto.
_com_state = threading.local()


def _ensure_com_sta() -> None:
    """Initialisiert COM einmal pro Thread als STA (pywinauto-Bedarf)."""
    if getattr(_com_state, "ready", False):
        return
    try:
        import pythoncom

        pythoncom.CoInitialize()
        _com_state.ready = True
    except Exception:
        # Kein pythoncom oder schon im falschen Apartment: pywinauto
        # versucht es selbst und meldet einen brauchbaren Fehler.
        pass


def _desktop():
    _ensure_com_sta()
    try:
        from pywinauto import Desktop
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pywinauto ist nicht installiert") from exc
    return Desktop(backend="uia")


def _invoke(*args, **kwargs):  # pragma: no cover - dünne Helfer
    raise NotImplementedError


def _desktop_windows(title: str, exact: bool):
    d = _desktop()
    needle = title.lower()
    cands = []
    for w in d.windows():
        try:
            t = (w.window_text() or "").strip()
        except Exception:
            continue
        if t and ((t.lower() == needle) if exact else (needle in t.lower())):
            cands.append(w)
    return cands


def _hwnds_by_title(title: str, exact: bool) -> list[tuple[int, str]]:
    import win32gui

    hits: list[tuple[int, str]] = []

    def cb(h: int, acc) -> bool:
        if win32gui.IsWindowVisible(h):
            t = win32gui.GetWindowText(h)
            if t and ((t.lower() == title.lower()) if exact else (title.lower() in t.lower())):
                acc.append((h, t))
        return True

    win32gui.EnumWindows(cb, None)
    return hits


def find_window(title: str, exact: bool = False):
    """Findet ein Top-Level-Fenster nach Titel(teil).

    UIA-Desktop zuerst; fällt im MCP-Server-Aparart oft als leere Liste aus –
    dann per win32gui-Handle bestimmen und per pywinauto konsekvent verbinden.
    """
    try:
        cands = _desktop_windows(title, exact)
        if cands:
            return cands[0]
    except Exception:
        pass
    hits = _hwnds_by_title(title, exact)
    if not hits:
        raise RuntimeError(f"Kein Fenster mit Titel {title!r} gefunden.")
    hwnd, t = hits[0]
    try:
        from pywinauto import Application

        app = Application(backend="uia").connect(handle=hwnd)
        for w in app.windows():
            try:
                if w.window_text().strip() == t.strip():
                    return w
            except Exception:
                continue
        return app.top_window()
    except Exception:
        try:
            cands = _desktop_windows(title, exact)
            if cands:
                return cands[0]
        except Exception:
            pass
        raise RuntimeError(f"Fenster gefunden, konnte aber nicht per pywinauto verknüpft werden: {t!r}")


def list_controls(title: str, name_filter: str = "", exact: bool = False, max_items: int = 60) -> dict[str, Any]:
    """Listet UIA-Controls eines Fensters (Name, ControlType, AutomationId)."""
    w = find_window(title, exact)
    out = []
    needle = name_filter.lower()
    for c in w.descendants():
        try:
            info = c.element_info
            name = info.name or ""
            if needle and needle not in name.lower():
                continue
            rect = info.rectangle
            out.append({
                "name": name,
                "control_type": info.control_type,
                "automation_id": info.automation_id,
                "class_name": info.class_name,
                "rect": [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top] if rect else None,
                "enabled": info.enabled,
            })
        except Exception:
            continue
        if len(out) >= max_items:
            break
    return {"count": len(out), "controls": out, "truncated": len(out) >= max_items}


def set_text(title: str, text: str, control_name: str | None = None, exact: bool = False) -> dict[str, Any]:
    """Setzt Text in ein Edit-Control, ohne Fokus/Maus zu ändern."""
    w = find_window(title, exact)
    edits = []
    if control_name:
        for c in w.descendants():
            try:
                if c.window_text() == control_name or (c.element_info.automation_id or "") == control_name:
                    edits.append(c)
                    break
            except Exception:
                continue
    else:
        for c in w.descendants(control_type="Edit"):
            edits.append(c)
    if not edits:
        raise RuntimeError(f"Kein Edit-Control in Fenster {title!r} gefunden")
    edit = edits[0]
    try:
        edit.set_edit_text(text)  # EM_SETTEXT, braucht keinen Fokus
    except Exception:
        # Fallback: UIA ValuePattern
        vp = edit.get_value_pattern() if hasattr(edit, "get_value_pattern") else None
        if vp is not None:
            vp.value(text)
        else:
            try:
                edit.iface_value.SetValue(text)  # type: ignore[attr-defined]
            except Exception as exc:
                raise RuntimeError(f"Text setzen fehlgeschlagen: {exc}")
    verify = ""
    try:
        verify = edit.window_text()
    except Exception:
        pass
    return {"ok": True, "text_length": len(text), "verified_preview": verify[:80]}


def invoke_control(title: str, control_name: str, exact: bool = False) -> dict[str, Any]:
    """Klickt ein UIA-Controls über InvokePattern – ohne Fokus/Maus."""
    w = find_window(title, exact)
    needle = control_name.lower()
    for c in w.descendants():
        try:
            nm = c.element_info.name or ""
            aid = c.element_info.automation_id or ""
            if (needle != "") and (needle == nm.lower() or needle == aid.lower() or needle in nm.lower()):
                try:
                    c.invoke()  # Button.invoke / _InvokePattern
                    return {"ok": True, "invoked": nm or aid}
                except Exception:
                    try:
                        if c.element_info.control_type == "CheckBox":
                            tbp = c.toggle_toggle()  # type: ignore[attr-defined]
                            return {"ok": True, "toggled": nm or aid}
                    except Exception:
                        pass
                    # Letzter Ausweg: Klick auf Container-Rect (virtuelle Maus)
                    try:
                        rect = c.element_info.rectangle
                        ctypes.windll.user32.SetCursorPos(int(rect.left + rect.width() / 2), int(rect.top + rect.height() / 2))
                        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                        return {"ok": True, "invoked_via_real_cursor": nm or aid}
                    except Exception:
                        pass
        except Exception:
            continue
    raise RuntimeError(f"Control {control_name!r} nicht gefunden")


def menu(title: str, path: str, exact: bool = False, pause: float = 0.5) -> dict[str, Any]:
    """Wählt einen Menüpunkt, optional "File -> Save" Stil."""
    import time as _time
    w = find_window(title, exact)
    w.menu_select(path)
    _time.sleep(pause)
    return {"ok": True, "menu_path": path}


def key_shortcut(title: str, keys: str) -> dict[str, Any]:
    """Sendet einen Hotkey an ein Fenster über PostMessage (je App best-effort).

    Im Gegensatz zu pyautogui bewegt sich die Hauptmaus NICHT. Gibt aber
    bewusst raw-Events an das jeweilige Fensterhandles Chon. Besser
    ``menu()``/``invoke_control()`` verwenden, wenn ein sichtbares Control
    existiert.
    """
    import win32gui
    import win32con

    hwnd = None
    needle = title.lower()

    def cb(h: int, acc) -> bool:
        nonlocal hwnd
        if win32gui.IsWindowVisible(h):
            t = win32gui.GetWindowText(h)
            if t and needle in t.lower():
                hwnd = h
                return False
        return True

    win32gui.EnumWindows(cb, None)
    if hwnd is None:
        raise RuntimeError(f"Fenster {title!r} nicht gefunden")

    parts = [p.strip().lower() for p in keys.split("+")]
    vk_map = {
        "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B,
        "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B,
        "space": 0x20, "tab": 0x09, "backspace": 0x08, "delete": 0x2E, "del": 0x2E,
        "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
        "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
        "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
        "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    }

    def vk(k: str) -> int:
        if k in vk_map:
            return vk_map[k]
        if len(k) == 1:
            code = ord(k.upper())
            return code
        raise ValueError(f"Unbekannte Taste {k!r}")

    modifiers = [p for p in parts if p in ("ctrl", "control", "shift", "alt", "win")]
    mains = [p for p in parts if p not in ("ctrl", "control", "shift", "alt", "win")]
    if len(mains) != 1:
        raise ValueError("Genau eine Haupttaste angeben, z. B. 'ctrl+s'")
    mod_vks = [vk(p) for p in modifiers]
    main_vk = vk(mains[0])

    flags_down = 0x0001 | (0 << 16)  # lParam-Grundzustand
    for m in mod_vks:
        win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, m, flags_down)
    win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, main_vk, 0x0001)
    win32gui.PostMessage(hwnd, win32con.WM_KEYUP, main_vk, 0xC001)
    for m in reversed(mod_vks):
        win32gui.PostMessage(hwnd, win32con.WM_KEYUP, m, 0xC001)
    time.sleep(0.3)
    return {"ok": True, "shortcut": keys, "hwnd": hwnd}
