"""MCP-Server: stellt die vier Kern-Module als Tools für die KI bereit.

Start (stdio-Transport, so nutzt OpenCode lokale MCP-Server)::

    python -m pcbediener serve

Die Tools sind nach den Modulen A-D aus der Aufgabenstellung benannt:
``exec_*`` (A), Maus/Tastatur/Fenster/Prozess (B), ``screenshot``/``system_status``
(C), ``file_*`` (D) sowie die Steuerwerkzeuge ``safety_*``.
"""

from __future__ import annotations

import functools
import importlib
import time
from typing import Any, Callable

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import __version__, runtime
from .modules import appmemory as mod_appmem
from .modules import exec as mod_exec
from .modules import files as mod_files
from .modules import flstudio as mod_flstudio
from .modules import gui as mod_gui
from .modules import proc as mod_proc
from .modules import vision as mod_vision
from .modules import background as mod_bg
from .safety import ConfirmationRequired, ForbiddenCommand, PathNotAllowed, SafetyError, require_confirm

INSTRUCTIONS = """\
Du steuerst den lokalen Windows-PC über diese Werkzeuge.

Arbeitsweise:
1. Zerlege die Aufgabe in klare Teilschritte und plane sie, bevor du handelst.
2. Nutze Tastatur-Shortcuts, wenn ein Dialog erreichbar ist – sie sind
   zuverlässiger als Klicks. Für Klicks: erst screenshot(), dann Koordinaten
   bestimmen; oder screen_find_image() mit einem Bild des Elements.
3. Warte nach Starts/Klicks mit screen_wait_for_image() oder sleep(), statt
   zu raten, ob eine Oberfläche schon geladen ist.
4. Liest du stderr/stdout aus einem exec_*-Aufruf, analysiere die Fehlermeldung,
   korrigiere den Code und führe ihn erneut aus.
5. Reagiert ein Fenster nicht mehr (kein Menü öffnet sich): window_modal_state()
   prüfen – ein modaler Dialog (z.B. Umbenennen/Bestätigen) deaktiviert das
   Hauptfenster, bis er geschlossen wird.
6. Für überlappende Fenster (Menüs, Dialoge) gilt nur screenshot(), nie ein
   PrintWindow-Composite – letzteres ignoriert die Z-Reihenfolge.
7. Pfade und Sonderzeichen immer per clipboard_set() + Strg+V eingeben
   (keyboard_type mit use_clipboard=True nutzt das automatisch).
 8. Für Bild-/Screenshot-Analyse: Subagent mit opencode/space-bunny-free
    (primär). Hängt oder scheitert es, Fallback: opencode/fledge-alpha-free.
    Das Programm-Gedächtnis (appmem_*) und flstudio_info() liefern Kontext.
9. Programm-Gedächtnis (appmem_*): Vor jeder App-Bedienung die Regel lesen
   (app_rule_get), danach Ergebnis verifizieren und Regeldatei AKTUALISIEREN
   (app_rule_set bei Erfolg, app_rule_break bei Fehlschlag). Nur verifizierte
   Wege benutzen – nie wiederholen, was unter avoid/broken steht.

LLM-Fallback-System:
- vision_model() zeigt die aktuelle Fallback-Kette (model_chain) + Status aller
  Modelle. Ein Modell mit Fehlern (Rate Limit, Quota, Credits) wird automatisch
  nach hinten verschoben und im Cooldown (60 s) gesetzt.
- Bei einem Rate-Limit-/Quota-/Credits-Fehler beim Subagenten sofort mit
  vision_model() prüfen, welches Modell als nächstes kommt. Dann den
  Subagenten mit model_chain_set(<nächstes_modell>) neu starten.
- model_chain_set(<Modell>) setzt ein Modell an die erste Stelle und löscht
  seinen Fehlerzähler – nützlich, wenn ein früherer Modell-Fehler behoben ist.
- model_chain_reset() leert alle Fehlerzähler und Cooldowns – für Neustarts.

Sicherheit:
- Destruktive Aktionen (exec_*, file_delete, file_write, file_move, process_kill,
  process_start, mouse_click) verlangen confirm=True, solange safety_mode
  "confirm" ist. Die Sperrliste in safety.py gilt immer, auch bei "auto".
- Dateizugriffe sind auf die Pfade in safety_status() begrenzt.
- Erkläre in einem kurzen Satz, was eine riskante Aktion bewirken würde, bevor
  du confirm=True setzt.
"""

#: Wiederverwendbare Annotations für die Tool-Metadaten.
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False)
NO_SIDE_EFFECTS = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False)

#: Einheitlicher Text für alle ``confirm``-Parameter.
CONFIRM_DOC = (
    "Bei safety_mode='confirm' zwingend True, damit die Aktion ausgeführt wird. "
    "Vorher in einem kurzen Satz erklären, was passiert."
)


#: Fehler, die der MCP-Server als Tool-Fehler melden soll statt als
#: "Error executing tool X" ohne jede Spur. pywinauto und comtypes erben
#: vielfach direkt von ``Exception`` – ohne diese Liste fielen Fehler aus
#: Modul E (Hintergrund-Automation) durch und die KI konnte sie nicht
#: korrigieren. Die Namen unterscheiden sich je nach pywinauto-Version,
#: deshalb wird vorsichtig nachgeschlagen statt fest verdrahtet.
_AUTOMATION_ERRORS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("comtypes", ("COMError", "com_error")),
    ("pywinauto", ("AppNotConnected", "ElementAmbiguousError",
                   "ElementNotFoundError", "WindowAmbiguousError",
                   "WindowNotFoundError")),
    ("pywinauto.application", ("AppNotConnected", "ProcessNotFoundError")),
    ("pywinauto.uia_defines", ("NoPatternInterfaceError",)),
)


def _expected_errors() -> tuple[type[BaseException], ...]:
    """Die Fehlertypen, die :func:`guard` in lesbare Tool-Fehler übersetzt."""
    found: list[type[BaseException]] = []
    for module_name, names in _AUTOMATION_ERRORS:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        for name in names:
            candidate = getattr(module, name, None)
            if isinstance(candidate, type) and issubclass(candidate, BaseException):
                found.append(candidate)
    return (
        SafetyError,
        OSError,  # FileNotFoundError, PermissionError, IsADirectoryError, ...
        ValueError,
        RuntimeError,
        NotImplementedError,
        *found,
    )


def guard(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Macht erwartete Fehler zu lesbaren Tool-Fehlern statt zu Abstürzen.

    Ohne diesen Wrapper würde der MCP-Server bei jedem kleinen Fehler nur
    "Error executing tool X" melden und den Traceback verstecken – die KI könnte
    den Fehler dann nicht selbst korrigieren.
    """
    expected = _expected_errors()

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except expected as exc:
            message = str(exc) or type(exc).__name__
            raise ToolError(f"{type(exc).__name__}: {message}") from None

    return wrapper


server = MCPServer(
    name="pc-bediener",
    title="PC-Bediener (lokale KI-Steuerung)",
    version=__version__,
    instructions=INSTRUCTIONS,
)


# ===========================================================================
# Sicherheitssteuerung
# ===========================================================================


@server.tool(
    annotations=READ_ONLY,
    description="Zeigt den aktuellen Sicherheitsmodus, erlaubte Pfade und Konfigurationspfad.",
)
@guard
def safety_status() -> dict[str, Any]:
    return runtime.describe()


@server.tool(
    annotations=WRITE,
    description=(
        "Schaltet den Sicherheitsmodus um: 'confirm' = destruktive Aktionen brauchen "
        "confirm=True (Standard), 'auto' = die KI handelt vollautonom. Die gesperrten "
        "Befehlsmuster gelten in beiden Modi."
    ),
)
@guard
def safety_mode(mode: str) -> dict[str, Any]:
    if mode not in ("confirm", "auto"):
        raise ValueError("mode muss 'confirm' oder 'auto' sein")
    runtime.set_safety_mode(mode)
    return {"safety_mode": mode, **runtime.describe()}


@server.tool(
    annotations=READ_ONLY,
    description="Zeigt das aktive Vision-Modell-Routing (Primär/Fallback) + Status aller Modelle in der Fallback-Kette.",
)
@guard
def vision_model() -> dict[str, Any]:
    cfg = runtime.get_config()
    return {
        "primary": cfg.vision_primary,
        "fallback": cfg.vision_fallback,
        "model_chain": cfg.model_chain,
        "model_state": {k: dict(v) for k, v in runtime._model_state.items()},
        "next_available": runtime.next_available_model(),
    }


@server.tool(
    annotations=WRITE,
    description="Ändert das Vision-Modell-Routing (primär/Fallback).",
)
@guard
def vision_set(primary: str | None = None, fallback: str | None = None) -> dict[str, Any]:
    cfg = runtime.get_config()
    if primary:
        cfg.vision_primary = primary
    if fallback:
        cfg.vision_fallback = fallback
    return {"primary": cfg.vision_primary, "fallback": cfg.vision_fallback}


@server.tool(
    annotations=WRITE,
    description=(
        "Setzt ein Modell an die erste Stelle der Fallback-Kette und löscht "
        "seinen Fehlerzähler. Nützlich nach einem kurzfristigen Provider-Problem, "
        "das behoben ist."
    ),
)
@guard
def model_chain_set(model_id: str) -> dict[str, Any]:
    cfg = runtime.get_config()
    if model_id in cfg.model_chain:
        cfg.model_chain = [model_id] + [m for m in cfg.model_chain if m != model_id]
    else:
        cfg.model_chain = [model_id] + cfg.model_chain
    runtime.reset_model_state(model_id)
    return {"model_chain": cfg.model_chain, "next_available": runtime.next_available_model()}


@server.tool(
    annotations=WRITE,
    description="Leert alle Modell-Fehlerzähler und Cooldowns zurück (für Neustarts).",
)
@guard
def model_chain_reset() -> dict[str, Any]:
    runtime.reset_model_state()
    cfg = runtime.get_config()
    return {"model_chain": cfg.model_chain, "next_available": runtime.next_available_model()}


# ===========================================================================
# Modul A – Code-Ausführung
# ===========================================================================


@server.tool(
    annotations=DESTRUCTIVE,
    description=(
        "Modul A: Führt Python-Code im lokalen Interpreter aus und liefert "
        "stdout, stderr, Exit-Code und Dauer. Bei Fehlern: stderr analysieren, "
        "Code korrigieren, erneut ausführen."
    ),
)
@guard
def exec_python(code: str, confirm: bool = False, timeout: int | None = None) -> dict[str, Any]:
    return mod_exec.run_python(code, runtime.get_config(), timeout, confirm).to_dict()


@server.tool(
    annotations=DESTRUCTIVE,
    description="Modul A: Führt ein PowerShell-Skript aus und liefert stdout/stderr/Exit-Code.",
)
@guard
def exec_powershell(
    script: str, confirm: bool = False, timeout: int | None = None
) -> dict[str, Any]:
    return mod_exec.run_powershell(script, runtime.get_config(), timeout, confirm).to_dict()


@server.tool(
    annotations=DESTRUCTIVE,
    description=(
        "Modul A: Führt einen Shell-Befehl aus. 'shell' erzwingt den Interpreter "
        "(powershell, pwsh, cmd, bash, sh); Standard ist unter Windows PowerShell."
    ),
)
@guard
def exec_command(
    command: str,
    shell: str | None = None,
    confirm: bool = False,
    timeout: int | None = None,
) -> dict[str, Any]:
    return mod_exec.run_command(command, runtime.get_config(), timeout, confirm, shell).to_dict()


# ===========================================================================
# Modul B – Maus
# ===========================================================================


@server.tool(
    annotations=NO_SIDE_EFFECTS,
    description=(
        "Modul B: Bewegt die Maus auf (x, y). 'duration' animiert die Bewegung "
        "(nützlich bei Drag & Drop). Koordinaten kommen aus screenshot()."
    ),
)
@guard
def mouse_move(x: int, y: int, duration: float = 0.0) -> dict[str, Any]:
    return mod_gui.move_mouse(x, y, runtime.get_config(), duration)


@server.tool(
    annotations=WRITE,
    description=(
        "Modul B: Klickt robust – auch bei Programmen, die einfache synthetische "
        "Klicks ignorieren (z.B. FL Studio). Mit 'window' wird das Zielfenster vorher "
        "FRISCH aufgelöst und in den Vordergrund+ Fokus gezwungen; danach wird die "
        "echte Cursor-Position verifiziert und ein blockierter Klick als Fehler "
        "gemeldet statt still zu scheitern. Gib bei Dialogs immer 'window' an. "
        "mode='sendinput' nutzt SendInput auf Hardware-Ebene (PyDirectInput-Art) "
        "als Fallback; hold_ms hält die Taste gedrückt (für Slider/Regler)."
    ),
)
@guard
def mouse_click(
    x: int | None = None,
    y: int | None = None,
    button: str = "left",
    clicks: int = 1,
    confirm: bool = False,
    window: str | None = None,
    exact: bool = False,
    mode: str = "pyautogui",
    hold_ms: int = 0,
) -> dict[str, Any]:
    return mod_gui.click(
        x, y, runtime.get_config(), button, clicks,
        confirm=confirm, window=window, exact=exact,
        mode=mode, hold_ms=hold_ms,
    )


@server.tool(
    annotations=WRITE,
    description=(
        "Modul B: Zwingt ein Fenster in den Vordergrund und gibt ihm den Tastatur-Fokus "
        "(AttachThreadInput + SetForegroundWindow). Nötig bei Programmen, die Klicks "
        "ohne Fokus ignorieren. Liefert zurück, ob es geklappt hat."
    ),
)
@guard
def window_activate(title: str, exact: bool = False) -> dict[str, Any]:
    return mod_gui.activate(mod_gui.find_window(title, exact))


@server.tool(
    annotations=READ_ONLY,
    description=(
        "Modul B: Prüft, ob ein Fenster noch existiert und ob es auf synthetische "
        "Nachrichten antwortet. Erkennt haengende Programme (Message-Pumpe blockiert) "
        "und veraltete Fenster-Handles – die haeufigste Fehlerursache bei GUI-Automation."
    ),
)
@guard
def window_health(title: str, exact: bool = False) -> dict[str, Any]:
    import time as _time

    win32gui, win32con = mod_gui._win32(), mod_gui._win32con()
    hwnd = mod_gui.find_window(title, exact)
    start = _time.monotonic()
    answers = bool(
        win32gui.SendMessageTimeout(
            hwnd, win32con.WM_NULL, 0, 0, win32con.SMTO_ABORTIFHUNG, 2000
        )
    )
    return {
        "hwnd": hwnd,
        "title": win32gui.GetWindowText(hwnd),
        "exists": bool(win32gui.IsWindow(hwnd)),
        "enabled": bool(win32gui.IsWindowEnabled(hwnd)),
        "visible": bool(win32gui.IsWindowVisible(hwnd)),
        "foreground": win32gui.GetForegroundWindow() == hwnd,
        "responds_to_messages": answers,
        "reply_ms": round((_time.monotonic() - start) * 1000, 1),
    }


@server.tool(
    annotations=READ_ONLY,
    description=(
        "Modul B: Diagnose für 'Fenster reagiert nicht'. Meldet, ob das Fenster "
        "durch einen modalen Dialog blockiert ist (enabled=False + Blockierer "
        "desselben Threads, z.B. FL Studios TNameEditForm/TMsgForm), inkl. "
        "GUI-Thread-Status (aktives/fokussiertes Handle). Weiter mit: Blockierer "
        "per window_action(..., 'close') oder WM_CLOSE schließen."
    ),
)
@guard
def window_modal_state(title: str, exact: bool = False) -> dict[str, Any]:
    return mod_gui.modal_state(title, exact)


@server.tool(
    annotations=READ_ONLY,
    description=(
        "Anwendungs-Wissen FL Studio: Fensterklassen, Fenster-IDs (widMixer=0, "
        "widChannelRack=1, widPlaylist=2, ...), Shortcuts (F5 Playlist, F9 Mixer, "
        "Alt+F8 Browser), MIDI-Scripting-Ablage (device_*.py) und Rezepte "
        "(Tempo setzen, Audio importieren, Modal-Dialoge)."
    ),
)
@guard
def flstudio_info() -> dict[str, Any]:
    return {
        "window_classes": mod_flstudio.WINDOW_CLASSES,
        "wid": {
            "mixer": mod_flstudio.WID_MIXER,
            "channel_rack": mod_flstudio.WID_CHANNEL_RACK,
            "playlist": mod_flstudio.WID_PLAYLIST,
            "piano_roll": mod_flstudio.WID_PIANO_ROLL,
            "browser": mod_flstudio.WID_BROWSER,
        },
        "shortcuts": {
            "playlist": mod_flstudio.SHORTCUT_PLAYLIST,
            "channel_rack": mod_flstudio.SHORTCUT_CHANNEL_RACK,
            "piano_roll": mod_flstudio.SHORTCUT_PIANO_ROLL,
            "mixer": mod_flstudio.SHORTCUT_MIXER,
            "browser": mod_flstudio.SHORTCUT_BROWSER,
        },
        "midi_scripting": {
            "hardware_subdir": list(mod_flstudio.HARDWARE_SUBDIR),
            "device_prefix": mod_flstudio.DEVICE_PREFIX,
            "api_modules": list(mod_flstudio.API_MODULES),
        },
        "toolbar_hints": [
            {"x": x, "y": y, "hint": hint}
            for x, y, hint in mod_flstudio.TOOLBAR_HINTS
        ],
        "recipes": dict(mod_flstudio.RECIPES),
    }


@server.tool(
    annotations=WRITE,
    description=(
        "Modul B: Zieht von (x1, y1) nach (x2, y2) – für Drag & Drop. "
        "steps>1 fährt in Zwischenpunkten (für Slider, die Sprünge ignorieren)."
    ),
)
@guard
def mouse_drag(
    x1: int, y1: int, x2: int, y2: int, button: str = "left", duration: float = 0.5,
    steps: int = 1,
) -> dict[str, Any]:
    return mod_gui.drag(x1, y1, x2, y2, runtime.get_config(), duration, button, steps)


@server.tool(
    annotations=WRITE,
    description=(
        "Modul B: Scrollt. Positive clicks scrollen nach oben (bzw. rechts bei "
        "horizontal=True). Optional erst an (x, y) bewegen."
    ),
)
@guard
def mouse_scroll(
    clicks: int, x: int | None = None, y: int | None = None, horizontal: bool = False
) -> dict[str, Any]:
    return mod_gui.scroll(clicks, x, y, horizontal, runtime.get_config())


@server.tool(
    annotations=READ_ONLY,
    description=(
        "Modul B: Bildschirmauflösung, Mausposition und Bildschirm-Hauptauflösung "
        "für Multi-Monitor-Setups."
    ),
)
@guard
def screen_info() -> dict[str, Any]:
    return {**mod_gui.screen_size(), "mouse": mod_gui.mouse_position()}


# ===========================================================================
# Modul B – Tastatur
# ===========================================================================


@server.tool(
    annotations=WRITE,
    description=(
        "Modul B: Tippt Text. Bei Sonderzeichen use_clipboard=True verwenden – "
        "das ist zuverlässiger als Tastendrücke für Unicode."
    ),
)
@guard
def keyboard_type(text: str, use_clipboard: bool = False, interval: float = 0.0) -> dict[str, Any]:
    return mod_gui.type_text(text, runtime.get_config(), interval, use_clipboard)


@server.tool(
    annotations=WRITE,
    description=(
        "Modul B: Drückt eine Taste, z.B. 'enter', 'esc', 'f5', 'tab', 'space', "
        "'printscreen'. Mehrfachdrücke über 'presses'."
    ),
)
@guard
def keyboard_press(key: str, presses: int = 1) -> dict[str, Any]:
    return mod_gui.press_key(key, presses, runtime.get_config())


@server.tool(
    annotations=WRITE,
    description=(
        "Modul B: Führt einen Hotkey aus, z.B. ['ctrl','c'], ['alt','tab'], "
        "['win','shift','s']. Tasten werden in dieser Reihenfolge gedrückt."
    ),
)
@guard
def keyboard_hotkey(keys: list[str]) -> dict[str, Any]:
    return mod_gui.hotkey(*keys, cfg=runtime.get_config())


@server.tool(
    annotations=WRITE,
    description=(
        "Modul B: Legt Text in die Zwischenablage (nativ, ohne Zusatzpaket). "
        "Danach mit keyboard_hotkey(['ctrl','v']) einfügen – zuverlässiger "
        "als Tippen bei Pfaden und Sonderzeichen."
    ),
)
@guard
def clipboard_set(text: str) -> dict[str, Any]:
    return mod_gui.set_clipboard(text)


@server.tool(
    annotations=READ_ONLY,
    description="Modul B: Liest den Textinhalt der Zwischenablage.",
)
@guard
def clipboard_get() -> dict[str, Any]:
    return mod_gui.get_clipboard()


@server.tool(
    annotations=READ_ONLY,
    description="Modul B: Wartet Sekunden – um UI-Animationen und Programmstarts abzuwarten.",
)
@guard
def sleep(seconds: float) -> dict[str, Any]:
    if seconds < 0 or seconds > 60:
        raise ValueError("seconds muss zwischen 0 und 60 liegen")
    time.sleep(seconds)
    return {"slept_s": seconds}


# ===========================================================================
# Modul B – Fenster
# ===========================================================================


@server.tool(
    annotations=READ_ONLY,
    description=(
        "Modul B: Listet offene Fenster mit Titel, Position, Größe und minimized/"
        "maximized. filter_text ist ein Teilstring-Filter (leer = alle)."
    ),
)
@guard
def window_list(filter_text: str = "") -> dict[str, Any]:
    return mod_gui.list_windows(filter_text)


@server.tool(
    annotations=WRITE,
    description=(
        "Modul B: Aktiviert ein Fenster anhand seines Titels und holt es aus "
        "minimiertem Zustand zurück. Der wichtigste Test für zuverlässige GUI-Steuerung."
    ),
)
@guard
def window_focus(title: str, exact: bool = False) -> dict[str, Any]:
    return mod_gui.focus_window(title, exact)


@server.tool(
    annotations=DESTRUCTIVE,
    description=(
        "Modul B: Fensteraktion – 'minimize', 'maximize', 'restore', 'hide' oder "
        "'close'. 'close' beendet die Anwendung und braucht confirm=True."
    ),
)
@guard
def window_action(
    title: str, action: str, exact: bool = False, confirm: bool = False
) -> dict[str, Any]:
    cfg = runtime.get_config()
    if action == "close":
        require_confirm(confirm, cfg, "Fenster schließen (Anwendung beenden)", title)
    return mod_gui.window_action(title, action, exact)


# ===========================================================================
# Modul E – Hintergrund-Steuerung (Fokus-frei, Maus bleibt frei)
# ===========================================================================


@server.tool(
    annotations=READ_ONLY,
    description=(
        "Modul E: Listet UIA-Controls eines Fensters (Name, Typ, AutomationId). "
        "Immer dazu nutzen, um Buttons/Edits für window_invoke/window_set_text gefunden zu werden."
    ),
)
@guard
def window_list_controls(title: str, name_filter: str = "", exact: bool = False) -> dict[str, Any]:
    return mod_bg.list_controls(title, name_filter, exact)


@server.tool(
    annotations=NO_SIDE_EFFECTS,
    description=(
        "Modul E: Setzt den Text eines Fensters (erstes Edit-Control oder über control_name) "
        "ohne Fokuswechsel und ohne den Mauscursor zu bewegen – der Benutzer kann nebenbei weiterarbeiten. "
        "Das Dokument wird NICHT automatisch gespeichert: danach window_menu(file) oder "
        "window_key_shortcut(ctrl+s) auf dasselbe Fenster anwenden."
    ),
)
@guard
def window_set_text(title: str, text: str, control_name: str | None = None, exact: bool = False) -> dict[str, Any]:
    return mod_bg.set_text(title, text, control_name, exact)


@server.tool(
    annotations=WRITE,
    description=(
        "Modul E: Klickt anonym ein Control(Name/AutomationId) eines Fensters über UIA "
        "InvokePattern – ohne Fokuswechsel und ohne den Mauscursor zu bewegen."
    ),
)
@guard
def window_invoke(title: str, control_name: str, exact: bool = False) -> dict[str, Any]:
    return mod_bg.invoke_control(title, control_name, exact)


@server.tool(
    annotations=WRITE,
    description=(
        "Modul E: Wählt einen Menüpunkt eines Fensters im Hintergrund, z. B. "
        "'File -> Save' oder 'Edit -> Copy'."
    ),
)
@guard
def window_menu(title: str, path: str, exact: bool = False) -> dict[str, Any]:
    return mod_bg.menu(title, path, exact)


@server.tool(
    annotations=WRITE,
    description=(
        "Modul E: Sendet eine Tastenkombination per PostMessage an ein Fenster "
        "(z. B. 'ctrl+s'). Funktioniert zuverlässig bei klassischen Win32-Controls; "
        "bei WinUI-Apps eher window_menu nutzen. Kein Fokuswechsel nötig."
    ),
)
@guard
def window_key_shortcut(title: str, keys: str, exact: bool = False) -> dict[str, Any]:
    return mod_bg.key_shortcut(title, keys)


@server.tool(
    annotations=READ_ONLY,
    description=(
        "Programm-Gedächtnis: Listet alle Regeln + Avoid-Liste einer App "
        "(Status, broken-Flag, Kurznotiz). Startpunkt jeder App-Automation."
    ),
)
@guard
def app_rules_list(app: str) -> dict[str, Any]:
    mod_appmem.ensure_seeded(app)
    return mod_appmem.list_rules(app)


@server.tool(
    annotations=READ_ONLY,
    description=(
        "Programm-Gedächtnis: Holt EINEN verifizierten Bedienweg (Schritte + "
        "Notiz + Status). Fehlende/defekte Regel = KeyError, dann erst einen "
        "Weg verifizieren und per app_rule_set speichern."
    ),
)
@guard
def app_rule_get(app: str, name: str) -> dict[str, Any]:
    mod_appmem.ensure_seeded(app)
    return mod_appmem.get_rule(app, name)


@server.tool(
    annotations=WRITE,
    description=(
        "Programm-Gedächtnis: Speichert einen VERIFIZIERTEN Weg (Erfolg per "
        "Screenshot/OCR/Pixel belegt). Löst broken-Flag, zählt verified_ok hoch."
    ),
)
@guard
def app_rule_set(app: str, name: str, steps: list[str], note: str = "") -> dict[str, Any]:
    return mod_appmem.set_rule(app, name, steps, note)


@server.tool(
    annotations=WRITE,
    description=(
        "Programm-Gedächtnis: Markiert einen Weg AUTOMATISCH bei Fehlschlag als "
        "defekt (mit Grund + optionalem Ersatz). Defekte Regeln werden nicht "
        "mehr benutzt, bis app_rule_set sie erneut verifiziert."
    ),
)
@guard
def app_rule_break(app: str, name: str, reason: str, replacement: str = "") -> dict[str, Any]:
    return mod_appmem.mark_broken(app, name, reason, replacement)


# ===========================================================================
# Modul B – Prozesse
# ===========================================================================


@server.tool(
    annotations=READ_ONLY,
    description=(
        "Modul B: Listet laufende Prozesse mit CPU/RAM. "
        "sort_by: cpu|memory|name|pid."
    ),
)
@guard
def process_list(
    filter_text: str = "", limit: int = 30, sort_by: str = "cpu"
) -> dict[str, Any]:
    return mod_proc.list_processes(runtime.get_config(), filter_text, limit, sort_by)


@server.tool(
    annotations=READ_ONLY,
    description="Modul B: Details zu einem Prozess (CPU, RAM, Pfad, Kommandozeile, Startzeit).",
)
@guard
def process_info(pid: int) -> dict[str, Any]:
    return mod_proc.process_info(pid)


@server.tool(
    annotations=DESTRUCTIVE,
    description=(
        "Modul B: Startet ein Programm, z.B. 'notepad' oder ein Pfad zur .exe. "
        "background=True startet es entkoppelt und wartet nicht."
    ),
)
@guard
def process_start(
    program: str,
    arguments: list[str] | None = None,
    background: bool = True,
    confirm: bool = False,
) -> dict[str, Any]:
    return mod_proc.start_process(program, runtime.get_config(), background, arguments, confirm)


@server.tool(
    annotations=DESTRUCTIVE,
    description=(
        "Modul B: Beendet einen Prozess. Systemprozesse und der eigene Prozess sind "
        "geschützt. force=True erzwingt das Beenden (SIGKILL-Äquivalent)."
    ),
)
@guard
def process_kill(pid: int, force: bool = False, confirm: bool = False) -> dict[str, Any]:
    return mod_proc.kill_process(pid, runtime.get_config(), force, confirm)


# ===========================================================================
# Modul C – Vision & Systemstatus
# ===========================================================================


@server.tool(
    annotations=NO_SIDE_EFFECTS,
    description=(
        "Modul C: Nimmt einen Screenshot auf und liefert ihn als Bild zurück – "
        "damit Oberflächen visuell analysiert und Klickpositionen bestimmt werden können. "
        "region=(links, oben, breite, hoehe) für einen Ausschnitt; max_width skaliert "
        "runter, um Tokens zu sparen."
    ),
)
@guard
def screenshot(
    region: tuple[int, int, int, int] | None = None,
    path: str | None = None,
    save: bool = True,
    max_width: int = 0,
) -> list[Image | dict[str, Any]]:
    cfg = runtime.get_config()
    meta = mod_vision.screenshot(cfg, path, region, save, max_width)
    if not meta.get("path"):
        return [meta]
    return [Image(path=meta["path"]), meta]


@server.tool(
    annotations=NO_SIDE_EFFECTS,
    description=(
        "Modul C: Sucht ein Bild auf dem Bildschirm und liefert dessen Position. "
        "Damit klickt die KI auf ein Element, ohne die Koordinate zu schätzen."
    ),
)
@guard
def screen_find_image(
    image_path: str, region: tuple[int, int, int, int] | None = None
) -> dict[str, Any]:
    return mod_vision.find_on_screen(runtime.get_config(), image_path, region)


@server.tool(
    annotations=NO_SIDE_EFFECTS,
    description=(
        "Modul C: Wartet bis zu timeout_s Sekunden darauf, dass ein Bild auf dem "
        "Bildschirm erscheint. Nützlich nach Programmstarts oder Klicks."
    ),
)
@guard
def screen_wait_for_image(
    image_path: str, timeout_s: float = 10.0, poll_interval: float = 0.5
) -> dict[str, Any]:
    return mod_vision.wait_for_image(runtime.get_config(), image_path, timeout_s, poll_interval)


@server.tool(
    annotations=READ_ONLY,
    description=(
        "Modul C: Systemstatus – CPU (inkl. pro Kern), RAM, Festplatte, Akku, "
        "Uptime, Sicherheitsmodus."
    ),
)
@guard
def system_status(include_disk: bool = True, disk_path: str | None = None) -> dict[str, Any]:
    return mod_vision.system_status(runtime.get_config(), include_disk, disk_path)


# ===========================================================================
# Modul D – Dateisystem
# ===========================================================================


@server.tool(
    annotations=READ_ONLY,
    description=(
        "Modul D: Liest eine Textdatei und liefert Inhalt plus Metadaten. "
        "Für Binärdateien read_binary nutzen (liefert Base64)."
    ),
)
@guard
def file_read(path: str, max_chars: int = 200_000) -> dict[str, Any]:
    return mod_files.read_text(path, runtime.get_config(), max_chars)


@server.tool(
    annotations=READ_ONLY,
    description="Modul D: Liest eine Binärdatei und liefert sie Base64-kodiert.",
)
@guard
def file_read_binary(path: str, max_bytes: int = 5_000_000) -> dict[str, Any]:
    return mod_files.read_binary(path, runtime.get_config(), max_bytes)


@server.tool(
    annotations=DESTRUCTIVE,
    description=(
        "Modul D: Schreibt eine Textdatei (überschreibt sie). Braucht confirm=True, "
        "solange safety_mode='confirm' gilt. append=True hängt an, ohne Bestätigung."
    ),
)
@guard
def file_write(
    path: str, content: str, append: bool = False, confirm: bool = False
) -> dict[str, Any]:
    return mod_files.write_text(path, content, runtime.get_config(), append, True, confirm)


@server.tool(
    annotations=READ_ONLY,
    description="Modul D: Listet den Inhalt eines Ordners. pattern filtert (z.B. '*.py').",
)
@guard
def file_list(path: str, pattern: str = "*", recursive: bool = False) -> dict[str, Any]:
    return mod_files.list_dir(path, runtime.get_config(), pattern, recursive)


@server.tool(
    annotations=READ_ONLY,
    description=(
        "Modul D: Kompakte Baumansicht eines Ordners (max. 3 Ebenen) – liest sich "
        "für die KI schneller als eine flache Liste."
    ),
)
@guard
def file_tree(path: str, max_depth: int = 3) -> dict[str, Any]:
    return mod_files.tree(path, runtime.get_config(), max_depth=max_depth)


@server.tool(
    annotations=READ_ONLY,
    description="Modul D: Sucht rekursiv nach Dateien/Ordnern mit Depth-Begrenzung.",
)
@guard
def file_search(
    path: str,
    pattern: str = "*",
    filter_glob: str | None = None,
    max_results: int = 200,
    max_depth: int = 8,
) -> dict[str, Any]:
    return mod_files.search(
        path, runtime.get_config(), pattern, filter_glob, max_results, max_depth
    )


@server.tool(
    annotations=NO_SIDE_EFFECTS,
    description="Modul D: Legt einen Ordner an (inklusive Elternordner).",
)
@guard
def folder_create(path: str) -> dict[str, Any]:
    return mod_files.make_dir(path, runtime.get_config())


@server.tool(
    annotations=DESTRUCTIVE,
    description=(
        "Modul D: Verschiebt oder benennt eine Datei/einen Ordner um. "
        "Braucht confirm=True bei safety_mode='confirm'."
    ),
)
@guard
def file_move(src: str, dst: str, confirm: bool = False, overwrite: bool = False) -> dict[str, Any]:
    return mod_files.move(src, dst, runtime.get_config(), confirm, overwrite)


@server.tool(
    annotations=WRITE,
    description="Modul D: Kopiert eine Datei oder einen Ordner (rekursiv).",
)
@guard
def file_copy(src: str, dst: str, overwrite: bool = False) -> dict[str, Any]:
    return mod_files.copy(src, dst, runtime.get_config(), overwrite)


@server.tool(
    annotations=DESTRUCTIVE,
    description=(
        "Modul D: Löscht eine Datei oder einen Ordner. Braucht confirm=True. "
        "Nicht-leere Ordner nur mit recursive=True."
    ),
)
@guard
def file_delete(path: str, recursive: bool = False, confirm: bool = False) -> dict[str, Any]:
    return mod_files.delete(path, runtime.get_config(), recursive, confirm)


def main() -> None:
    """Startet den Server auf stdio."""
    server.run("stdio")


if __name__ == "__main__":
    main()