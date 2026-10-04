"""Modul B (Teil 1) – GUI-Steuerung: Maus, Tastatur, Fenster.

``pyautogui`` und ``pywin32`` werden erst bei Bedarf importiert, damit das
Paket auch ohne grafischen Desktop (z.B. in Tests oder auf einem Server)
importierbar bleibt.
"""

from __future__ import annotations

import ctypes
import time
from dataclasses import asdict, dataclass
from typing import Any, Literal

from ..config import Config
from ..safety import ConfirmationRequired, ForbiddenCommand, require_confirm

Button = Literal["left", "right", "middle"]
#: Tastennamen, die pyautogui direkt kennt – für die Validierung in Hotkeys.
_SPECIAL_KEYS = {
    "enter", "return", "tab", "shift", "ctrl", "control", "alt", "esc", "escape",
    "space", "backspace", "delete", "del", "home", "end", "pgup", "pgdn", "up",
    "down", "left", "right", "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9",
    "f10", "f11", "f12", "insert", "printscreen", "win", "cmd", "command",
}


def _pyautogui():
    """Lazy-Import von pyautogui mit verständlicher Fehlermeldung."""
    try:
        import pyautogui
    except Exception as exc:  # pragma: no cover - plattformabhängig
        raise RuntimeError(
            "pyautogui konnte nicht geladen werden. "
            "Installiere es mit: pip install pyautogui"
        ) from exc
    # Fail-Safe aktiv lassen: Maus in die obere linke Ecke -> Abbruch.
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    return pyautogui


@dataclass
class Point:
    x: int
    y: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass
class WindowInfo:
    """Ein Fenstereintrag."""

    hwnd: int
    title: str
    class_name: str
    pid: int
    x: int
    y: int
    width: int
    height: int
    minimized: bool
    maximized: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- Maus -------------------------------------------------------------------


def screen_size() -> dict[str, int]:
    """Auflösung des primären Bildschirms."""
    size = _pyautogui().size()
    return {"width": int(size[0]), "height": int(size[1])}


def mouse_position() -> dict[str, int]:
    """Aktuelle Mausposition."""
    pos = _pyautogui().position()
    return {"x": int(pos[0]), "y": int(pos[1])}


def move_mouse(x: int, y: int, cfg: Config, duration: float = 0.0) -> dict[str, Any]:
    """Bewegt die Maus absolut auf (x, y).

    ``duration`` > 0 animiert die Bewegung, was bei Drag-Drop oft realistischer
    von UI-Automationen akzeptiert wird.
    """
    pg = _pyautogui()
    width, height = pg.size()
    if not (0 <= x < width and 0 <= y < height):
        raise ValueError(
            f"Koordinate ({x}, {y}) liegt außerhalb des Bildschirms ({width}x{height})"
        )
    pg.moveTo(x, y, duration=duration)
    return {"moved_to": {"x": int(x), "y": int(y)}}


def activate(hwnd: int) -> dict[str, Any]:
    """Zwingt ein Fenster in den Vordergrund *und* aktiviert es.

    Das ist der entscheidende Schritt, ohne den viele Programme Klicks
    ignorieren: Windows stellt ``SetForegroundWindow`` zurück, wenn der
    aufrufende Prozess nicht selbst im Vordergrund war. ``AttachThreadInput``
    hängt den eigenen Thread kurz an den Fenster-Thread und umgeht diese
    Sperre. Danach besitzt das Fenster auch den Tastatur-Fokus, den
    Delphi/VCL-Programme (u.a. FL Studio) für Hover- und Klick-Reaktion
    brauchen.
    """
    win32gui, win32con, win32process = _win32(), _win32con(), _win32process()
    import win32api

    if not win32gui.IsWindow(hwnd):
        raise ValueError(f"Fenster-Handle {hwnd} existiert nicht (mehr)")

    win32gui.ShowWindow(hwnd, win32con.SW_SHOW)

    already = win32gui.GetForegroundWindow() == hwnd
    attached = False
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass  # häufig blockiert -> AttachThreadInput-Weg unten

    if win32gui.GetForegroundWindow() != hwnd:
        current = win32api.GetCurrentThreadId()
        fg = win32gui.GetForegroundWindow()
        threads = {
            win32process.GetWindowThreadProcessId(hwnd)[0],
            win32process.GetWindowThreadProcessId(fg)[0] if fg else 0,
        }
        threads.discard(0)
        try:
            for thread in threads:
                win32process.AttachThreadInput(current, thread, True)
            attached = True
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
            try:
                win32gui.SetActiveWindow(hwnd)
            except Exception:
                pass
        finally:
            if attached:
                for thread in threads:
                    try:
                        win32process.AttachThreadInput(current, thread, False)
                    except Exception:
                        pass

    return {
        "hwnd": hwnd,
        "title": win32gui.GetWindowText(hwnd),
        "foreground": win32gui.GetForegroundWindow() == hwnd,
        "was_already_foreground": already,
        "thread_input_attached": attached,
    }


def click(
    x: int | None = None,
    y: int | None = None,
    cfg: Config | None = None,
    button: Button = "left",
    clicks: int = 1,
    interval: float = 0.1,
    confirm: bool = False,
    window: str | None = None,
    exact: bool = False,
) -> dict[str, Any]:
    """Klickt robust – auch bei Programmen, die synthetische Klicks ignorieren.

    Gegen ``pyautogui.click`` gibt es drei entscheidende Unterschiede:

    1. **Handle frisch auflösen.** Fenster-Handles veralten schnell (FL Studio
       bekam innerhalb weniger Minuten neue). Deshalb wird ``window`` immer
       unmittelbar vor dem Klick neu aufgelöst und danach geprüft, ob es noch
       gültig ist.
    2. **Vordergrund erzwingen** (:func:`activate`). Viele Programme ignorieren
       Klicks, wenn ihr Fenster nicht den Fokus hat.
    3. **Echten Cursor setzen und prüfen.** ``SetCursorPos`` + ``mouse_event``
       statt nur ``pyautogui.click``; anschließend wird die tatsächliche
       Cursor-Position verifiziert. Weicht sie ab, blockiert der Desktop die
       Eingabe (z.B. wegen abweichender Integritätsstufe) – das wird als
       Fehler gemeldet statt stillschweigend zu scheitern.

    Args:
        window: Titel des Zielfensters. Vor dem Klick wird es in den
            Vordergrund geholt. Sehr empfehlenswert für Dialoge.
        exact: Exakte Titelübereinstimmung statt Teilstring.
    """
    if button not in ("left", "right", "middle"):
        raise ValueError(f"Unbekannte Maustaste: {button}")
    if clicks < 1 or clicks > 5:
        raise ValueError("clicks muss zwischen 1 und 5 liegen")

    if cfg is not None:
        require_confirm(
            confirm, cfg, f"{clicks}x {button}-Klick",
            f"bei ({x}, {y})" + (f" im Fenster {window!r}" if window else "") if x is not None else "",
        )

    activation: dict[str, Any] | None = None
    if window:
        hwnd = find_window(window, exact)          # immer frisch auflösen
        activation = activate(hwnd)

    pg = _pyautogui()
    if x is not None and y is not None:
        # Position hart setzen und danach prüfen, statt zu hoffen.
        try:
            import win32api

            win32api.SetCursorPos((int(x), int(y)))
        except Exception:
            move_mouse(x, y, cfg) if cfg else pg.moveTo(x, y)

        actual = pg.position()
        if (int(actual[0]), int(actual[1])) != (int(x), int(y)):
            raise RuntimeError(
                f"Cursor liess sich nicht auf ({x}, {y}) setzen – "
                f"tatsaechlich ({actual[0]}, {actual[1]}). Meist blockiert eine "
                "abweichende Integritaetsstufe (UIPI) die synthetische Eingabe: "
                "laeuft der PC-Bediener mit geringeren Rechten als das Zielprogramm?"
            )

    pg.click(
        x=x, y=y, button=button, clicks=clicks, interval=interval,
        duration=0 if cfg is None else cfg.click_delay_ms / 1000,
    )

    return {
        "clicked": {"x": int(pg.position()[0]), "y": int(pg.position()[1])},
        "button": button,
        "clicks": clicks,
        "target_window": window,
        "activation": activation,
    }


def mouse_down(button: Button = "left", x: int | None = None, y: int | None = None, cfg: Config | None = None) -> dict[str, Any]:
    """Drückt eine Maustaste (für manuelles Drag & Drop)."""
    pg = _pyautogui()
    if x is not None and y is not None:
        move_mouse(x, y, cfg) if cfg else pg.moveTo(x, y)
    pg.mouseDown(button=button)
    return {"button_down": button, "position": mouse_position()}


def mouse_up(button: Button = "left") -> dict[str, Any]:
    """Lässt eine Maustaste los."""
    _pyautogui().mouseUp(button=button)
    return {"button_up": button, "position": mouse_position()}


def drag(
    x1: int, y1: int, x2: int, y2: int, cfg: Config | None = None,
    duration: float = 0.5, button: Button = "left",
) -> dict[str, Any]:
    """Zieht von (x1, y1) nach (x2, y2)."""
    pg = _pyautogui()
    pg.moveTo(x1, y1)
    pg.mouseDown(button=button)
    try:
        pg.moveTo(x2, y2, duration=duration)
    finally:
        pg.mouseUp(button=button)  # auch bei Fehlern loslassen
    return {"from": {"x": x1, "y": y1}, "to": {"x": x2, "y": y2}, "button": button}


def scroll(clicks: int, x: int | None = None, y: int | None = None, horizontal: bool = False, cfg: Config | None = None) -> dict[str, Any]:
    """Scrollt. Positive ``clicks`` scrollen nach oben/rechts."""
    pg = _pyautogui()
    if cfg is not None and x is not None and y is not None:
        move_mouse(x, y, cfg)
    if horizontal:
        pg.hscroll(clicks)
    else:
        pg.scroll(clicks)
    return {"scrolled": clicks, "horizontal": horizontal}


# --- Tastatur ---------------------------------------------------------------


def type_text(text: str, cfg: Config | None = None, interval: float = 0.0, use_clipboard: bool = False) -> dict[str, Any]:
    """Tippt Text.

    ``use_clipboard=True`` nutzt Zwischenablage + Strg+V – das ist die einzige
    zuverlässige Methode für Unicode/Sonderzeichen.
    """
    if not isinstance(text, str):
        raise TypeError("text muss ein String sein")
    pg = _pyautogui()
    delay = interval if interval else (cfg.key_delay_ms / 1000 if cfg else 0.0)

    if use_clipboard or (not text.isascii() and _has_non_ascii(text)):
        try:
            import pyperclip
        except ImportError as exc:
            raise RuntimeError("pyperclip fehlt – pip install pyperclip") from exc
        pyperclip.copy(text)
        pg.hotkey("ctrl", "v")
        return {"typed_chars": len(text), "method": "clipboard"}

    pg.write(text, interval=delay)
    return {"typed_chars": len(text), "method": "keyboard"}


def _has_non_ascii(text: str) -> bool:
    return any(ord(ch) > 127 for ch in text)


def press_key(key: str, presses: int = 1, cfg: Config | None = None) -> dict[str, Any]:
    """Drückt eine Taste, z.B. ``enter``, ``f5``, ``esc``."""
    if presses < 1:
        raise ValueError("presses muss >= 1 sein")
    pg = _pyautogui()
    delay = (cfg.key_delay_ms / 1000) if cfg else 0.0
    pg.press(key, presses=presses, interval=delay)
    return {"pressed": key, "count": presses}


def hotkey(*keys: str, cfg: Config | None = None) -> dict[str, Any]:
    """Führt einen Hotkey aus, z.B. ``hotkey("ctrl", "c")`` oder ``("alt","tab")``.

    Die Reihenfolge ist „in dieser Reihenfolge gedrückt, dann umgekehrt losgelassen“.
    """
    if len(keys) < 2:
        raise ValueError("Ein Hotkey braucht mindestens 2 Tasten")
    _pyautogui().hotkey(*keys, interval=(cfg.key_delay_ms / 1000) if cfg else 0.0)
    return {"hotkey": list(keys)}


# --- Fenster ----------------------------------------------------------------


def _win32():
    try:
        import win32gui
    except ImportError as exc:  # pragma: no cover - nur unter Windows
        raise RuntimeError(
            "Fenstersteuerung braucht pywin32 – pip install pywin32"
        ) from exc
    return win32gui


def _win32con():
    import win32con

    return win32con


def _win32process():
    try:
        import win32process
    except ImportError as exc:  # pragma: no cover - nur unter Windows
        raise RuntimeError(
            "Fenstersteuerung braucht pywin32 – pip install pywin32"
        ) from exc
    return win32process


def _is_zoomed(hwnd: int) -> bool:
    """Ist das Fenster maximiert?

    ``win32gui`` hat keine ``IsZoomed``-Funktion – dafür braucht es den
    direkten Win32-Aufruf.
    """
    try:
        return bool(ctypes.windll.user32.IsZoomed(hwnd))
    except (AttributeError, OSError):
        return False


def _window_pid(hwnd: int) -> int:
    """Prozess-ID eines Fensters.

    ``GetWindowThreadProcessId`` liegt in ``win32process``, nicht in
    ``win32gui`` – der Unterschied ist in pywin32 leicht zu übersehen.
    """
    return _win32process().GetWindowThreadProcessId(hwnd)[1]


def _window_info(hwnd: int) -> WindowInfo:
    win32gui = _win32()
    title = win32gui.GetWindowText(hwnd)
    try:
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    except Exception:
        left = top = right = bottom = 0
    return WindowInfo(
        hwnd=hwnd,
        title=title,
        class_name=win32gui.GetClassName(hwnd) or "",
        pid=_window_pid(hwnd),
        x=left,
        y=top,
        width=right - left,
        height=bottom - top,
        minimized=bool(win32gui.IsIconic(hwnd)),
        maximized=_is_zoomed(hwnd),
    )


def list_windows(filter_text: str = "", visible_only: bool = True) -> dict[str, Any]:
    """Listet Fenster mit Titel. ``filter_text`` ist ein Teilstring-Filter.

    Liefert ``{"count": n, "windows": [...]}`` statt einer nackten Liste: So
    bekommt der MCP-Client einen einzigen JSON-Block mit Anzahl, statt einen
    Textblock pro Fenster.
    """
    win32gui = _win32()
    found: list[dict[str, Any]] = []
    # Fenster, die zwischen Enumeration und Abfrage schon wieder verschwunden
    # sind, sind normal und werden übersprungen. Alles andere wird NICHT
    # geschluckt: ein still verschluckter Fehler liefert eine leere Liste und
    # lässt die KI raten, es gäbe keine Fenster.
    vanished = 0

    def callback(hwnd: int, _param: Any) -> bool:
        nonlocal vanished
        if visible_only and not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return True
        if filter_text and filter_text.lower() not in title.lower():
            return True
        try:
            found.append(_window_info(hwnd).to_dict())
        except (RuntimeError, ImportError):
            raise
        except Exception:
            vanished += 1  # nur zwischenzeitlich zerstörte Fenster
        return True

    win32gui.EnumWindows(callback, None)
    return {
        "count": len(found),
        "vanished": vanished,
        "windows": found,
    }


def find_window(title: str, exact: bool = False) -> int:
    """Findet ein Fenster per Titel und gibt sein ``hwnd`` zurück.

    Raises:
        WindowNotFound: Kein Fenster mit diesem Titel gefunden.
    """
    win32gui = _win32()
    matches: list[tuple[int, str]] = []

    def callback(hwnd: int, _param: Any) -> bool:
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title_here = win32gui.GetWindowText(hwnd)
        if not title_here:
            return True
        hit = (title_here == title) if exact else (title.lower() in title_here.lower())
        if not hit:
            return True  # weitersuchen
        matches.append((hwnd, title_here))
        # False beendet EnumWindows. EnumWindows läuft in Z-Reihenfolge,
        # der erste Treffer ist damit das oberste Fenster.
        return False

    win32gui.EnumWindows(callback, None)
    if not matches:
        raise WindowNotFound(
            f"Kein Fenster mit dem Titel {title!r} gefunden. "
            "Nutze list_windows(), um verfügbare Titel zu sehen."
        )
    return matches[0][0]


class WindowNotFound(RuntimeError):
    """Kein Fenster mit dem gewünschten Titel gefunden."""


def focus_window(title: str, exact: bool = False) -> dict[str, Any]:
    """Aktiviert ein Fenster und holt es aus minimiertem Zustand zurück."""
    win32gui, win32con = _win32(), _win32con()
    hwnd = find_window(title, exact)
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    _force_foreground(hwnd, win32gui, win32con)
    return _window_info(hwnd).to_dict()


def _force_foreground(hwnd: int, win32gui, win32con) -> None:
    """Setzt ein Fenster in den Vordergrund.

    ``SetForegroundWindow`` wird von Windows blockiert, wenn der aufrufende
    Prozess nicht im Vordergrund war. Der Workaround ist, sich kurz an den
    Thread des Zielfensters zu hängen (``AttachThreadInput``).
    """
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass  # oft blockiert -> der AttachThreadInput-Weg unten hilft

    fg = win32gui.GetForegroundWindow()
    if fg == hwnd:
        return

    win32process = _win32process()
    try:
        import win32api

        # GetCurrentThreadId liegt in win32api, nicht in win32process.
        current_thread = win32api.GetCurrentThreadId()
        target_thread = win32process.GetWindowThreadProcessId(hwnd)[0]
        fg_thread = win32process.GetWindowThreadProcessId(fg)[0] if fg else 0
        for thread in {target_thread, fg_thread}:
            if thread:
                win32process.AttachThreadInput(current_thread, thread, True)
        try:
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        finally:
            for thread in {target_thread, fg_thread}:
                if thread:
                    win32process.AttachThreadInput(current_thread, thread, False)
    except Exception:
        # Im schlimmsten Fall liegt das Fenster immerhin wieder sichtbar oben.
        try:
            win32gui.BringWindowToTop(hwnd)
        except Exception:
            pass


def window_action(title: str, action: str, exact: bool = False) -> dict[str, Any]:
    """Führt eine Fensteraktion aus: ``minimize``, ``maximize``, ``restore``,
    ``close`` oder ``hide``."""
    win32gui, win32con = _win32(), _win32con()
    hwnd = find_window(title, exact)

    actions = {
        "minimize": win32con.SW_MINIMIZE,
        "maximize": win32con.SW_MAXIMIZE,
        "restore": win32con.SW_RESTORE,
        "hide": win32con.SW_HIDE,
    }
    if action == "close":
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    elif action in actions:
        win32gui.ShowWindow(hwnd, actions[action])
        if action in ("restore", "maximize"):
            _force_foreground(hwnd, win32gui, win32con)
    else:
        raise ValueError(
            f"Unbekannte Aktion {action!r}. Möglich: minimize, maximize, restore, hide, close"
        )
    return {**_window_info(hwnd).to_dict(), "action": action}