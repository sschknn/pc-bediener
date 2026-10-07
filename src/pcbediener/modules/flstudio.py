"""Anwendungs-Wissen: FL Studio per GUI-Automation steuern.

Sammelt die Befunde aus Web-Recherche (offizielle MIDI-Scripting-API,
Community-Guide flmidi-101, FLAPPY) und aus einer realen
Automations-Sitzung (Toolbar kartiert, Tempo gesetzt, Stems importiert).

Zwei Steuerwege – bewusst trennen:

1. **MIDI-Scripting-API** (``device_*.py`` im Hardware-Ordner): für
   Controller-Events (Transport, Mixer, Playlist-Mute). Eingeschränkter
   Python-3.9-Interpreter, kein Systemzugriff, kein Threading, kein
   Datei-Drag&Drop. Für Arrangement-Aufbau *nicht* geeignet.
2. **GUI-Automation** (dieses Tool): für alles, was die API nicht kann –
   Menüs, Dateidialoge, Drag&Drop aus dem Explorer, Tempo-Panel.

Reine Konstanten + Rezepte, keine Windows-Abhängigkeit beim Import.
"""

from __future__ import annotations

# --- Fensterklassen (Win32, beobachtet) --------------------------------------
#: Hauptfenster.
MAIN_CLASS = "TFruityLoopsMainForm"
#: Modal: Pattern-Umbenennung. Deaktiviert das Hauptfenster, bis es per
#: WM_CLOSE/Escape geschlossen wird – dann reagiert kein Menü mehr.
RENAME_CLASS = "TNameEditForm"
#: Modal: Bestätigungsdialoge („Confirm", „Save changes …?").
CONFIRM_CLASS = "TMsgForm"
#: FLs eigener „Save as"-Dialog (Ctrl+S bei unbenanntem Projekt). Kein
#: Systemdialog – Pfad-Paste über die Zwischenablage greift hier nicht, man
#: muss das vorbelegte Name-Feld ersetzen und die Radiobuttons bedienen.
SAVE_AS_CLASS = "TNewProjForm"
#: System-Dateidialog („Open").
FILE_DIALOG_CLASS = "#32770"
#: Aufklapp-Menüs (FILE/VIEW/Import …).
POPUP_MENU_CLASS = "TQuickPopupMenuWindow"
#: Hinweis-Leiste unten.
HINT_BAR_CLASS = "TFLHintBarForm"

WINDOW_CLASSES = {
    "main": MAIN_CLASS,
    "rename": RENAME_CLASS,
    "confirm": CONFIRM_CLASS,
    "save_as": SAVE_AS_CLASS,
    "file_dialog": FILE_DIALOG_CLASS,
    "popup_menu": POPUP_MENU_CLASS,
    "hint_bar": HINT_BAR_CLASS,
}

# --- Fenster-IDs (ui-Modul der MIDI-Scripting-API, Image-Line-Doku) ----------
WID_MIXER = 0
WID_CHANNEL_RACK = 1
WID_PLAYLIST = 2
WID_PIANO_ROLL = 3
WID_BROWSER = 4

# --- Tastenkürzel (VIEW-Menü, verifiziert) ------------------------------------
SHORTCUT_PLAYLIST = ["f5"]
SHORTCUT_CHANNEL_RACK = ["f6"]
SHORTCUT_PIANO_ROLL = ["f7"]
SHORTCUT_MIXER = ["f9"]
#: Der Browser hat **kein** Umschalt-Kürzel – er ist ein dauerhaft
#: eingdocktes Panel links und immer sichtbar. ``alt+f8`` wurde als
#: Browser-Kürzel angenommen und tat nichts; ``f8`` öffnet stattdessen
#: das Fenster ``PlugList``. Für den Browser einfach die Liste links
#: anklicken und Dateien in die Playlist ziehen.
SHORTCUT_BROWSER: tuple[str, ...] = ()
#: ``f8`` öffnet die Plugin-Liste.
SHORTCUT_PLUGLIST = ["f8"]

# --- MIDI-Scripting (Web-Recherche: flmidi-101 / Image-Line) ------------------
#: Skripte liegen unter ``<User data>\FL Studio\Settings\Hardware\<Name>\``.
#: Die Hauptdatei heißt ``device_*.py``, erste Zeile ``# name=...``.
HARDWARE_SUBDIR = ("FL Studio", "Settings", "Hardware")
DEVICE_PREFIX = "device_"
#: Module des eingebauten Interpreters (Auswahl, Doku: midi_scripting.htm).
API_MODULES = (
    "arrangement", "channels", "device", "general", "launchMapPages",
    "mixer", "patterns", "playlist", "plugins", "transport", "ui",
)

# --- Toolbar (1920x1200, per Hover-Hinweis kartiert) ----------------------------
#: (x, y, erkannter Hint-Text) – y=26 ist die Toolbar-Zeile, der Hint
#: erscheint links bei (~45, ~75).
TOOLBAR_HINTS: tuple[tuple[int, int, str], ...] = (
    (316, 26, "Pattern or song mode"),
    (340, 26, "Play"),
    (400, 26, "Stop"),
    (430, 26, "Record"),
    (462, 26, "Tempo"),
    (500, 26, "Time panel"),
    (540, 26, "Song position"),
    (660, 26, "Typing keyboard to piano"),
    (700, 26, "Recording precount"),
)
#: Tempo-Anzeige (nur lesbar per OCR, nicht per Klick tippbar).
TEMPO_READ_BOX = (415, 0, 525, 50)
TEMPO_TARGET_EXAMPLE = 160.0

# --- Rezepte (Sitzungserkenntnisse) --------------------------------------------
RECIPES = {
    # Das Tempo-Panel nimmt keine Tastatureingaben (kein Edit-Modus);
    # Draggen ändert den Wert grob. Robust: MIDI mit Tempo-Event importieren.
    "set_tempo": (
        "FILE > Import > MIDI (tempoXXX.mid mit FF 51 03 <us/beat>), "
        "Confirm mit 'No' beantworten, Pfad in den Open-Dialog (Zwischenablage + Enter), "
        "Import-Dialog mit 'Start new project' akzeptieren – "
        "danach Toolbar-OCR prüfen."
    ),
    # FL-Browser kennt nur seine Datenbank; fremde Ordner per Explorer-Drag&Drop.
    "import_audio": (
        "Explorer im Stems-Ordner öffnen, unten rechts parken, "
        "WAV per mouse_drag in die Playlist-Spurfläche (rechts der Spurköpfe) ziehen."
    ),
    # PrintWindow malt alle Child-Fenster unabhängig vom Z-Order;
    # für Menüs/Dialoge gilt nur der echte Screen-Grab.
    "screenshot_truth": (
        "Überlappungen (Menü, Confirm, maximierte Fenster) nur per Screen-Grab "
        "beurteilen, nie per PrintWindow."
    ),
    # Nach TNameEditForm ist das Hauptfenster deaktiviert: window_modal_state
    # prüfen, Dialog per WM_CLOSE schließen, danach reagiert das Menü wieder.
    "modal_dialog": (
        "Reagiert kein Menü mehr: modal_state() – enabled=False + "
        "likely_modal_blocker (TNameEditForm/TMsgForm) schließen."
    ),
}
