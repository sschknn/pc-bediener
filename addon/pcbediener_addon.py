"""OpenCode-Addon: pcbediener MCP-Server mit FL-Studio-Wissen.

Dieses Addon stellt bei jeder OpenCode-Sitzion die pcbediener MCP-Tools
und das gesamte FL-Studio-Bedienungswissen bereit.

Installation:
    1. Kopiere diesen Ordner in dein OpenCode-Addon-Verzeichnis.
    2. Starte OpenCode neu.
    3. Das Addon ist automatisch verfuegbar.

Verwendung:
    - Alle pcbediener-Tools sind via MCP erreichbar.
    - FL-Studio-Wissen ist in der INSTRUCTIONS-Konstante hinterlegt.
    - Bei Fehlern: safety_status() pruefen, dann korrektur.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

# --- Projektroot fuer relative Importe -----------------------------------
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from pcbediener import runtime  # noqa: E402
from pcbediener.modules import flstudio as mod_flstudio  # noqa: E402
from pcbediener.modules import gui as mod_gui  # noqa: E402
from pcbediener.modules import exec as mod_exec  # noqa: E402
from pcbediener.modules import files as mod_files  # noqa: E402
from pcbediener.modules import proc as mod_proc  # noqa: E402
from pcbediener.modules import vision as mod_vision  # noqa: E402
from pcbediener.modules import appmemory as mod_appmem  # noqa: E402
from pcbediener.modules import background as mod_bg  # noqa: E402
from pcbediener.safety import require_confirm  # noqa: E402

# ===========================================================================
# FL-Studio-Wissen (bei jeder Sitzion verfuegbar)
# ===========================================================================

INSTRUCTIONS = """\
## PC-Bediener + FL Studio Addon (v1.0)

Du bist ein autonomer System-Steuerungs-Assistent UND Producer DJ.
Du steuerst den lokalen Windows-PC ueber die pcbediener MCP-Tools
und produzierst Tracks in FL Studio.

### FL Studio Wissen (immer verfuegbar)

Fensterklassen:
- TFruityLoopsMainForm (Hauptfenster)
- TNameEditForm (Umbenennen-Modal)
- TMsgForm (Bestaetigungsdialog)
- #32770 (System-Dateidialog)
- TQuickPopupMenuWindow (Aufklapp-Menues)
- TFLHintBarForm (Hinweis-Leiste)

Fenster-IDs:
- widMixer = 0
- widChannelRack = 1
- widPlaylist = 2
- widPianoRoll = 3
- widBrowser = 4

Shortcuts:
- F5 = Playlist
- F6 = Channel Rack
- F7 = Piano Roll
- F9 = Mixer
- Alt+F8 = Browser

Rezepte:
- Tempo setzen: FILE > Import > MIDI (tempoXXX.mid mit FF 51 03 <us/beat>)
- Audio importieren: Explorer > WAV per Drag&Drop in Playlist-Spurflaeche
- Modal-Dialoge: window_modal_state() pruefen, TNameEditForm/TMsgForm schliessen

Toolbar-Hints (1920x1200):
- (316, 26) Pattern/Song mode
- (340, 26) Play
- (400, 26) Stop
- (430, 26) Record
- (462, 26) Tempo
- (500, 26) Time panel
- (540, 26) Song position
"""

# ===========================================================================
# Tool-Registry (fuer OpenCode-MCP-Integration)
# ===========================================================================

TOOLS: dict[str, dict[str, Any]] = {}


def register_tool(
    name: str | None = None,
    *,
    description: str = "",
    annotations: dict[str, Any] | None = None,
) -> Callable:
    """Registriert ein Tool in der OpenCode-Tool-Registry.

    Kann als Decorator mit oder ohne Argumente verwendet werden:
        @register_tool
        def meine_funktion() -> dict: ...

        @register_tool("mein_tool", description="Beschreibung")
        def meine_funktion() -> dict: ...
    """
    def decorator(fn: Callable) -> Callable:
        tool_name = name or fn.__name__
        TOOLS[tool_name] = {
            "fn": fn,
            "description": description or fn.__doc__ or "",
            "annotations": annotations or {},
        }
        return fn
    if name is not None and callable(name):
        # @register_tool ohne Argumente
        fn = name
        return register_tool()(fn)
    return decorator


# --- Sicherheitssteuerung ------------------------------------------------

@register_tool(description="Zeigt den aktuellen Sicherheitsmodus, erlaubte Pfade und Konfigurationspfad.")
def safety_status() -> dict[str, Any]:
    return runtime.describe()


@register_tool(description="Schaltet den Sicherheitsmodus um: 'confirm' oder 'auto'.")
def safety_mode(mode: str) -> dict[str, Any]:
    if mode not in ("confirm", "auto"):
        raise ValueError("mode muss 'confirm' oder 'auto' sein")
    runtime.set_safety_mode(mode)
    return {"safety_mode": mode, **runtime.describe()}


# --- Modul A: Code-Ausfuehrung -------------------------------------------

@register_tool(description="Fuehrt Python-Code aus.")
def exec_python(code: str, confirm: bool = False, timeout: int | None = None) -> dict[str, Any]:
    return mod_exec.run_python(code, runtime.get_config(), timeout, confirm).to_dict()


@register_tool(description="Fuehrt ein PowerShell-Skript aus.")
def exec_powershell(script: str, confirm: bool = False, timeout: int | None = None) -> dict[str, Any]:
    return mod_exec.run_powershell(script, runtime.get_config(), timeout, confirm).to_dict()


@register_tool(description="Fuehrt einen Shell-Befehl aus.")
def exec_command(command: str, shell: str | None = None, confirm: bool = False, timeout: int | None = None) -> dict[str, Any]:
    return mod_exec.run_command(command, runtime.get_config(), timeout, confirm, shell).to_dict()


# --- Modul B: Maus & Tastatur --------------------------------------------

@register_tool(description="Bewegt die Maus auf (x, y).")
def mouse_move(x: int, y: int, duration: float = 0.0) -> dict[str, Any]:
    return mod_gui.move_mouse(x, y, runtime.get_config(), duration)


@register_tool(description="Klickt robust auch bei FL Studio.")
def mouse_click(
    x: int | None = None, y: int | None = None, button: str = "left",
    clicks: int = 1, confirm: bool = False, window: str | None = None,
    exact: bool = False, mode: str = "pyautogui", hold_ms: int = 0,
) -> dict[str, Any]:
    return mod_gui.click(x, y, runtime.get_config(), button, clicks,
                         confirm=confirm, window=window, exact=exact,
                         mode=mode, hold_ms=hold_ms)


@register_tool(description="Zieht von (x1, y1) nach (x2, y2).")
def mouse_drag(x1: int, y1: int, x2: int, y2: int, button: str = "left",
               duration: float = 0.5, steps: int = 1) -> dict[str, Any]:
    return mod_gui.drag(x1, y1, x2, y2, runtime.get_config(), duration, button, steps)


@register_tool(description="Scrollt.")
def mouse_scroll(clicks: int, x: int | None = None, y: int | None = None, horizontal: bool = False) -> dict[str, Any]:
    return mod_gui.scroll(clicks, x, y, horizontal, runtime.get_config())


@register_tool(description="Tippt Text.")
def keyboard_type(text: str, use_clipboard: bool = False, interval: float = 0.0) -> dict[str, Any]:
    return mod_gui.type_text(text, runtime.get_config(), interval, use_clipboard)


@register_tool(description="Drueckt eine Taste.")
def keyboard_press(key: str, presses: int = 1) -> dict[str, Any]:
    return mod_gui.press_key(key, presses, runtime.get_config())


@register_tool(description="Fuehrt einen Hotkey aus.")
def keyboard_hotkey(keys: list[str]) -> dict[str, Any]:
    return mod_gui.hotkey(*keys, cfg=runtime.get_config())


@register_tool(description="Legt Text in die Zwischenablage.")
def clipboard_set(text: str) -> dict[str, Any]:
    return mod_gui.set_clipboard(text)


@register_tool(description="Liest die Zwischenablage.")
def clipboard_get() -> dict[str, Any]:
    return mod_gui.get_clipboard()


@register_tool(description="Wartet Sekunden.")
def sleep(seconds: float) -> dict[str, Any]:
    if seconds < 0 or seconds > 60:
        raise ValueError("seconds muss zwischen 0 und 60 liegen")
    import time as _time
    _time.sleep(seconds)
    return {"slept_s": seconds}


# --- Modul B: Fenster -----------------------------------------------------

@register_tool(description="Listet offene Fenster.")
def window_list(filter_text: str = "") -> dict[str, Any]:
    return mod_gui.list_windows(filter_text)


@register_tool(description="Aktiviert ein Fenster.")
def window_focus(title: str, exact: bool = False) -> dict[str, Any]:
    return mod_gui.focus_window(title, exact)


@register_tool(description="Fuuehrt eine Fensteraktion aus.")
def window_action(title: str, action: str, exact: bool = False, confirm: bool = False) -> dict[str, Any]:
    cfg = runtime.get_config()
    if action == "close":
        require_confirm(confirm, cfg, "Fenster schliessen", title)
    return mod_gui.window_action(title, action, exact)


@register_tool(description="Diagnose fuer 'Fenster reagiert nicht'.")
def window_modal_state(title: str, exact: bool = False) -> dict[str, Any]:
    return mod_gui.modal_state(title, exact)


@register_tool(description="Prueft ob ein Fenster noch existiert und antwortet.")
def window_health(title: str, exact: bool = False) -> dict[str, Any]:
    import time as _time
    win32gui, win32con = mod_gui._win32(), mod_gui._win32con()
    hwnd = mod_gui.find_window(title, exact)
    start = _time.monotonic()
    answers = bool(win32gui.SendMessageTimeout(hwnd, win32con.WM_NULL, 0, 0, win32con.SMTO_ABORTIFHUNG, 2000))
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


@register_tool(description="Zwingt ein Fenster in den Vordergrund.")
def window_activate(title: str, exact: bool = False) -> dict[str, Any]:
    return mod_gui.activate(mod_gui.find_window(title, exact))


# --- Modul E: Hintergrund-Steuerung ----------------------------------------

@register_tool(description="Listet UIA-Controls eines Fensters.")
def window_list_controls(title: str, name_filter: str = "", exact: bool = False) -> dict[str, Any]:
    return mod_bg.list_controls(title, name_filter, exact)


@register_tool(description="Setzt den Text eines Fensters.")
def window_set_text(title: str, text: str, control_name: str | None = None, exact: bool = False) -> dict[str, Any]:
    return mod_bg.set_text(title, text, control_name, exact)


@register_tool(description="Klickt anonym ein Control eines Fensters.")
def window_invoke(title: str, control_name: str, exact: bool = False) -> dict[str, Any]:
    return mod_bg.invoke_control(title, control_name, exact)


@register_tool(description="Waehlt einen Menuepunkt eines Fensters.")
def window_menu(title: str, path: str, exact: bool = False) -> dict[str, Any]:
    return mod_bg.menu(title, path, exact)


@register_tool(description="Sendet eine Tastenkombination an ein Fenster.")
def window_key_shortcut(title: str, keys: str, exact: bool = False) -> dict[str, Any]:
    return mod_bg.key_shortcut(title, keys)


# --- Modul B: Prozesse ----------------------------------------------------

@register_tool(description="Listet laufende Prozesse.")
def process_list(filter_text: str = "", limit: int = 30, sort_by: str = "cpu") -> dict[str, Any]:
    return mod_proc.list_processes(runtime.get_config(), filter_text, limit, sort_by)


@register_tool(description="Details zu einem Prozess.")
def process_info(pid: int) -> dict[str, Any]:
    return mod_proc.process_info(pid)


@register_tool(description="Startet ein Programm.")
def process_start(program: str, arguments: list[str] | None = None, background: bool = True, confirm: bool = False) -> dict[str, Any]:
    return mod_proc.start_process(program, runtime.get_config(), background, arguments, confirm)


@register_tool(description="Beendet einen Prozess.")
def process_kill(pid: int, force: bool = False, confirm: bool = False) -> dict[str, Any]:
    return mod_proc.kill_process(pid, runtime.get_config(), force, confirm)


# --- Modul C: Vision & Systemstatus ---------------------------------------

@register_tool(description="Nemmt einen Screenshot auf.")
def screenshot(region: tuple[int, int, int, int] | None = None, path: str | None = None,
              save: bool = True, max_width: int = 0) -> list[Any]:
    cfg = runtime.get_config()
    meta = mod_vision.screenshot(cfg, path, region, save, max_width)
    if not meta.get("path"):
        return [meta]
    return [meta]


@register_tool(description="Sucht ein Bild auf dem Bildschirm.")
def screen_find_image(image_path: str, region: tuple[int, int, int, int] | None = None) -> dict[str, Any]:
    return mod_vision.find_on_screen(runtime.get_config(), image_path, region)


@register_tool(description="Wartet bis ein Bild erscheint.")
def screen_wait_for_image(image_path: str, timeout_s: float = 10.0, poll_interval: float = 0.5) -> dict[str, Any]:
    return mod_vision.wait_for_image(runtime.get_config(), image_path, timeout_s, poll_interval)


@register_tool(description="Systemstatus.")
def system_status(include_disk: bool = True, disk_path: str | None = None) -> dict[str, Any]:
    return mod_vision.system_status(runtime.get_config(), include_disk, disk_path)


# --- Modul D: Dateisystem -------------------------------------------------

@register_tool(description="Liest eine Textdatei.")
def file_read(path: str, max_chars: int = 200_000) -> dict[str, Any]:
    return mod_files.read_text(path, runtime.get_config(), max_chars)


@register_tool(description="Liest eine Binaerdatei.")
def file_read_binary(path: str, max_bytes: int = 5_000_000) -> dict[str, Any]:
    return mod_files.read_binary(path, runtime.get_config(), max_bytes)


@register_tool(description="Schreibt eine Textdatei.")
def file_write(path: str, content: str, append: bool = False, confirm: bool = False) -> dict[str, Any]:
    return mod_files.write_text(path, content, runtime.get_config(), append, True, confirm)


@register_tool(description="Listet den Inhalt eines Ordners.")
def file_list(path: str, pattern: str = "*", recursive: bool = False) -> dict[str, Any]:
    return mod_files.list_dir(path, runtime.get_config(), pattern, recursive)


@register_tool(description="Kompakte Baumansicht.")
def file_tree(path: str, max_depth: int = 3) -> dict[str, Any]:
    return mod_files.tree(path, runtime.get_config(), max_depth=max_depth)


@register_tool(description="Rekursiv suchen.")
def file_search(path: str, pattern: str = "*", filter_glob: str | None = None,
                max_results: int = 200, max_depth: int = 8) -> dict[str, Any]:
    return mod_files.search(path, runtime.get_config(), pattern, filter_glob, max_results, max_depth)


@register_tool(description="Legt einen Ordner an.")
def folder_create(path: str) -> dict[str, Any]:
    return mod_files.make_dir(path, runtime.get_config())


@register_tool(description="Verschiebt oder benennt um.")
def file_move(src: str, dst: str, confirm: bool = False, overwrite: bool = False) -> dict[str, Any]:
    return mod_files.move(src, dst, runtime.get_config(), confirm, overwrite)


@register_tool(description="Kopiert eine Datei.")
def file_copy(src: str, dst: str, overwrite: bool = False) -> dict[str, Any]:
    return mod_files.copy(src, dst, runtime.get_config(), overwrite)


@register_tool(description="Loescht eine Datei.")
def file_delete(path: str, recursive: bool = False, confirm: bool = False) -> dict[str, Any]:
    return mod_files.delete(path, runtime.get_config(), recursive, confirm)


# --- Programm-Gedaechtnis --------------------------------------------------

@register_tool(description="Listet alle Regeln einer App.")
def app_rules_list(app: str) -> dict[str, Any]:
    mod_appmem.ensure_seeded(app)
    return mod_appmem.list_rules(app)


@register_tool(description="Holt einen verifizierten Bedienweg.")
def app_rule_get(app: str, name: str) -> dict[str, Any]:
    mod_appmem.ensure_seeded(app)
    return mod_appmem.get_rule(app, name)


@register_tool(description="Speichert einen verifizierten Weg.")
def app_rule_set(app: str, name: str, steps: list[str], note: str = "") -> dict[str, Any]:
    return mod_appmem.set_rule(app, name, steps, note)


@register_tool(description="Markiert einen Weg als defekt.")
def app_rule_break(app: str, name: str, reason: str, replacement: str = "") -> dict[str, Any]:
    return mod_appmem.mark_broken(app, name, reason, replacement)


# --- FL Studio-Spezifische Tools ------------------------------------------

@register_tool(description="Anwendungs-Wissen FL Studio.")
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


# ===========================================================================
# OpenCode-Addon Initialisierung
# ===========================================================================

def init_addon() -> dict[str, Any]:
    """Initialisiert das Addon bei Start jeder Sitzion.

    Returns:
        Dictionary mit verfuegbaren Tools und FL-Studio-Wissen.
    """
    tools_list = list(TOOLS.keys())
    return {
        "addon": "pcbediener",
        "version": "1.0.0",
        "tools_available": tools_list,
        "tool_count": len(tools_list),
        "flstudio_knowledge": {
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
            "recipes": dict(mod_flstudio.RECIPES),
        },
        "instructions": INSTRUCTIONS,
    }


# --- Auto-Load bei Import -------------------------------------------------
if __name__ != "__main__":
    INIT_RESULT = init_addon()
