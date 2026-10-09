"""Steuerung von FL Studio ueber dessen eigenen Script-Output-Interpreter.

Warum dieses Modul
------------------
Die MIDI-Bruecke (``pcbediener.fl_command``) ist derzeit tot: loopMIDI
routet zwischen seinen Ports nichts, und FL hoert noch auf die
veralteten WinMM-IDs 236/237/238. Der Interpreter dagegen ist Teil von
FL selbst und spricht dieselbe Python-API an - nur ohne den Umweg ueber
MIDI.

Zwei Stolperfallen, die je eine halbe Stunde gekostet haben:

1. **Nichts kopieren.** ``keyboard_type(use_clipboard=True)`` schreibt
   in FLs Interpreter *nicht* - ohne Fehlermeldung, das Feld bleibt
   einfach leer. Der Text muss Zeichen fuer Zeichen getippt werden.
2. **Nichts zwischenspeichern.** FL verschiebt das Script-Fenster und
   die Panels nach Bedienung selbst (das Docking rechnet neu). Jede
   gespeicherte Koordinate wird dadurch falsch. Deshalb wird hier
   jedes Mal die aktuelle Fenstergometrie ueber Win32 geholt.

Rueckkanal ist das Ausgabefeld. ``WM_GETTEXT`` liefert darauf nichts
(TQuickMemo ist ein selbstgezeichnetes VCL-Control), also wird der
Text per Screenshot gelesen.
"""

from __future__ import annotations

import time

import pyautogui
import win32con
import win32gui
import win32process

pyautogui.FAILSAFE = False

FL_MAIN = "TFruityLoopsMainForm"
SCRIPT = "TPythonForm"
POPUP = "TQuickPopupMenuWindow"

#: Rechteck des Ausgabefeldes, fuer Screenshots des Rueckkanals
_MEMO_RECT: tuple[int, int, int, int] | None = None


def hwnd(cls: str, title: str | None = None) -> int:
    """Findet ein FL-Fenster anhand seiner Klasse."""
    return win32gui.FindWindow(cls, title) or 0


def children(parent: int, cls: str) -> list[int]:
    """Alle Kind-Fenster einer Klasse (Reihenfolge der Enumumeration)."""
    out: list[int] = []

    def cb(c, _):
        if win32gui.GetClassName(c) == cls:
            out.append(c)
        return True

    win32gui.EnumChildWindows(parent, cb, None)
    return out


def fl_pid() -> int:
    main = hwnd(FL_MAIN)
    return win32process.GetWindowThreadProcessId(main)[1] if main else 0


def visible_fl_windows() -> list[tuple[str, str, tuple]]:
    """Alle sichtbaren FL-Fenster: (Klasse, Titel, Rect)."""
    pid = fl_pid()
    rows: list[tuple[str, str, tuple]] = []

    def cb(c, _):
        try:
            if (win32process.GetWindowThreadProcessId(c)[1] == pid
                    and win32gui.IsWindowVisible(c)):
                rows.append((win32gui.GetClassName(c),
                             win32gui.GetWindowText(c)[:45],
                             win32gui.GetWindowRect(c)))
        except Exception:
            pass
        return True

    win32gui.EnumWindows(cb, None)
    return sorted(rows, key=lambda r: r[2][1])


def memo_rect() -> tuple[int, int, int, int]:
    """Rect des Ausgabefeldes - bei jedem Aufruf neu ermittelt."""
    script = hwnd(SCRIPT)
    memos = children(script, "TQuickMemo")
    return win32gui.GetWindowRect(memos[-1]) if memos else (645, 300, 1275, 800)


def focus(cls: str, title: str | None = None, pause: float = 0.8) -> int:
    """Bringt ein FL-Fenster in den Vordergrund und gibt sein Handle zurueck."""
    h = hwnd(cls, title)
    if not h:
        return 0
    try:
        win32gui.SetForegroundWindow(h)
    except Exception:
        pass
    time.sleep(pause)
    return h


def view_menu_item(index_1based: int, item_offset: tuple[int, int] = (169, 18),
                   sub_offset: tuple[int, int] = (0, 0)) -> bool:
    """Oeffnet VIEW und waehlt den n-ten Eintrag per Tastatur.

    Pixel-Klicks auf VCL-Popups sind unzuverlaessig: das Popup schliesst
    sich, sobald FL den Fokus neu setzt. Die Pfeiltasten navigieren
    dagegen im bereits offenen, fokussierten Popup - unabhaengig von
    jeder Pixelposition.

    Reihenfolge in FL 26.1: Playlist, Piano roll, Channel rack, Mixer,
    Browser, Project picker, Plugin picker, Tempo tapper,
    Touch controller, Script output, Toolbars, ...
    """
    focus(FL_MAIN)
    pyautogui.press("esc")
    time.sleep(0.5)
    pyautogui.moveTo(*item_offset)
    time.sleep(0.3)
    pyautogui.click()
    time.sleep(1.8)
    if not children_of_class(POPUP):
        return False
    for _ in range(index_1based):
        pyautogui.press("down")
        time.sleep(0.12)
    time.sleep(0.5)
    pyautogui.press("enter")
    time.sleep(3.5)
    return True


def children_of_class(cls: str) -> list[int]:
    out: list[int] = []

    def cb(c, _):
        if win32gui.GetClassName(c) == cls and win32gui.IsWindowVisible(c):
            out.append(c)
        return True

    win32gui.EnumWindows(cb, None)
    return out


def interpreter_tab() -> bool:
    """Sorgt dafuer, dass der Script-Output auf 'Interpreter' steht.

    Tab-Positionen werden nicht geraten, sondern aus den Text-Pixeln der
    Tab-Leiste ermittelt (der erste Tab ist 'Interpreter', danach
    folgt je MIDI-Geraet ein weiterer).
    """
    script = focus(SCRIPT)
    if not script:
        return False
    sel = children(script, "TQuickSheetSelector")
    if not sel:
        return False
    x0, y0, x1, y1 = win32gui.GetWindowRect(sel[0])
    for cx, cy in ((706, (y0 + y1) // 2), (706, y0 + 16)):
        pyautogui.moveTo(cx, cy)
        time.sleep(0.35)
        pyautogui.click()
        time.sleep(1.2)
        if "Interpreter" in _sheet_titles():
            return True
    return "Interpreter" in _sheet_titles()


def _sheet_titles() -> list[str]:
    script = hwnd(SCRIPT)
    if not script:
        return []
    return [win32gui.GetWindowText(c) for c in children(script, "TVectorSheet")]


def befehl(text: str, warte: float = 3.0, tippen: float = 0.010) -> bool:
    """Tippt einen Einzeiler in FLs Interpreter und fuehrt ihn aus.

    Zeichen fuer Zeichen - Zwischenablage kommt dort nicht an.

    Wichtig: Das Script-Fenster wird **immer erst sichtbar gemacht**.
    War es versteckt, zeigte ``GetWindowRect`` weiter die alte Position -
    der Klick landete dann in Edison oder in der Playlist und hat dabei
    Clips geloescht. Genau das ist zweimal passiert.
    """
    if not hwnd(SCRIPT):
        if not view_menu_item(10):
            return False
    win32gui.ShowWindow(hwnd(SCRIPT), win32con.SW_SHOW)
    time.sleep(1.2)

    script = focus(SCRIPT)
    if not script:
        return False
    if not win32gui.IsWindowVisible(script):
        return False
    if "Interpreter" not in _sheet_titles():
        interpreter_tab()
    edits = children(script, "TPyFormEdit")
    if not edits:
        return False
    ed = edits[0]
    x0, y0, x1, y1 = win32gui.GetWindowRect(ed)
    pyautogui.moveTo((x0 + x1) // 2, (y0 + y1) // 2)
    time.sleep(0.25)
    pyautogui.click()
    time.sleep(0.4)
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.15)
    pyautogui.press("delete")
    time.sleep(0.25)
    pyautogui.write(text, interval=tippen)
    time.sleep(0.7)
    pyautogui.press("enter")
    time.sleep(warte)
    return True