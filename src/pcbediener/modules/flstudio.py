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
    #
    # ACHTUNG – der MIDI-Import legt ein Pattern an und setzt es an die
    # Wiedergabeposition in die Playlist. Liegt dort schon ein Clip, wird er
    # ersetzt (in einer Sitzung hat das so den dritten Beat-Track vernichtet).
    # Vorher also entweder ans Projektende springen oder die Position prüfen.
    "set_tempo": (
        "FILE > Import > MIDI (tempoXXX.mid mit FF 51 03 <us/beat>), "
        "Confirm mit 'No' beantworten, Pfad in den Open-Dialog (Zwischenablage + Enter), "
        "danach Toolbar-OCR prüfen. ACHTUNG: der Import legt ein Pattern "
        "an der Wiedergabeposition an - vorhandene Clips dort gehen verloren."
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

# --- Drehregler / Knobs / Slider (amtliche Image-Line-Doku) --------------------
#
# Quelle: image-line.com/fl-studio-learning/fl-studio-online-manual/
#         html/basics_interface.htm  -> Abschnitt "Knobs & sliders"
#         sowie html/basics_shortcuts.htm
#
# Das ist das Wichtigste für GUI-Automation, weil FL **keine** API zum Setzen
# von Plugin-Parametern hat (siehe SCRIPT_API_FACTS) – die Maus ist der
# einzige Weg. Und die Maus braucht exakt diese Modifikatoren:
#
#   Wert ändern          Linksklick auf den Regler und **vertikal ziehen**
#                        (horizontal bei waagerechten Reglern)
#   Wert exakt eintippen  Rechtsklick auf den Regler -> "Type in value"
#   Feinabstimmung        **Ctrl** während des Ziehens gedrückt halten
#                        (alternativ beide Maustasten gedrückt halten)
#   Rastpunkte aus       **Shift** während des Tweaks
#   Reset auf Default    **Alt** + Linksklick (bzw. Mittelklick bei
#                        3-Tasten-Maus)
#   Automation verlinken  Rechtsklick -> Link-Optionen / "last tweaked"
#
# Warum das im MCP so wichtig ist: ohne `modifiers` in mouse_drag/click war
# keine dieser Varianten überhaupt bedienbar – ein Regler liess sich nur
# ungenau verschieben, nie auf einen bekannten Wert setzen oder zurücksetzen.
KNOB_FACTS = {
    "ziehen": "Linksklick auf den Regler + vertikaler Zug (oben = höher)",
    "exakter_wert": "Rechtsklick -> 'Type in value' (deterministisch!)",
    "fein": "Ctrl + Zug  (alternativ beide Maustasten gedrückt)",
    "kein_snap": "Shift + Zug (Rastpunkte wie Default werden ignoriert)",
    "reset": "Alt + Linksklick (oder Mittelklick) -> Defaultwert",
    "rad": "Mausrad über dem Regler aendert den Wert in fester Schrittweite",
    "werteinheit": "0-100 %, 0-1 oder kontextabhaengig (dB); Typing erlaubt die Wahl",
    "auslesen": "Hint-Bar (TFLHintBarForm) zeigt Name+Wert beim Hover; per Screenshot lesen",
    "api": "plugins.setParamValue existiert NICHT - Maus ist der einzige Weg",
}

#: Fensterraster des FL-Hauptfensters: ``(x, y, breite, hoehe)``. Alle
#: Werkzeug-Koordinaten sind relativ dazu – anders als absolute Zahlen
#: bleibt das über Monitorwechsel und Fenstergrössen hinweg gültig.
#: Nur Beispieldaten aus einer realen Sitzung (1920x1200 Fenster).
FL_WINDOW_SIZE_EXAMPLE = (1920, 1200)

#: Rechteck der Hint-Bar am unteren Fensterrand, relativ zum FL-Hauptfenster.
#: Dort schreibt FL beim Hover "Parameter  -  Wert in Einheit"; das ist der
#: einzige Ort, an dem sich ein Regler-Wert ohne Plugin-spezifisches OCR
#: auslesen lässt.
HINT_BAR_REL = (0, 1150, 900, 50)


def hint_bar_rect(window_rect: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Absolute Hint-Bar-Rechtecke für ein FL-Hauptfenster.

    Args:
        window_rect: ``(links, oben, breite, hoehe)`` des Hauptfensters,
            z.B. von :func:`pcbediener.modules.gui.list_windows`.

    Returns:
        ``(links, oben, breite, hoehe)`` in Desktop-Koordinaten – direkt als
        ``screenshot(region=...)`` verwendbar.
    """
    left, top, width, height = window_rect
    rel = HINT_BAR_REL
    bar_height = rel[3]
    return (left + rel[0], top + max(0, height - (FL_WINDOW_SIZE_EXAMPLE[1] - rel[1])),
            min(rel[2], width), min(bar_height, height))


# --- Script-output-Interpreter (FL 26.1, empirisch ermittelt) ------------------
#
# VIEW > "Script output" ist eine eingedockte Seite von FLs Hauptfenster
# (Kette: TQuickMemo < TVectorSheet < TPythonForm < TFruityLoopsMainForm).
# Damit laesst sich FLs Python-API bedienen - unabhaengig von MIDI-Geraeten,
# die FL exklusiv haelt (midiOutOpen liefert rc=10).
#
# WICHTIGSTE FALLE DER GANZEN SITZUNG:
# ``keyboard_type(use_clipboard=True)`` schreibt in das Eingabefeld
# **nicht** - ohne jede Fehlermeldung, das Feld bleibt einfach leer und der
# Befehl laeuft nie. Es muss Zeichen fuer Zeichen getippt werden
# (``use_clipboard=False``). Das war die Ursache dafuer, dass sich die
# Bruecke ueber Stunden als "tot" darstellte.

#: Reiter des Script-Fensters (TQuickSheetSelector) und seiner Kinder.
SCRIPT_WINDOW_CLASS = "TPythonForm"
SCRIPT_OUTPUT_TITLE = "Script output"
#: Seitenreiter: "Interpreter" bzw. "loopMIDI Port 2". Standardmaessig steht
#: der Skript-Reiter vorn - dann nimmt das Eingabefeld nichts an.
SCRIPT_TAB_CLASS = "TQuickSheetSelector"
SCRIPT_INPUT_CLASS = "TPyFormEdit"
SCRIPT_OUTPUT_CLASS = "TQuickMemo"

#: Layout des Script-Fensters, gemessen per Win32 (``GetWindowRect`` der
#: Kinder), Fenster bei (400, 60, 630, 1000):
#:   TNewCaption      (404,  64, 1026,  90)
#:   TQuickSheetSelector (406,  93, 1024, 125)
#:   TPyFormEdit      (414, 146, 1016, 170)   <- Eingabefeld, Mitte y=158
#:   TQuickMemo       (414, 193, 1016, 987)   <- Ausgabe
#:   TVectorPanel     (406, 996, 1024, 1054)  <- "Clear output" links
#: Der Klick muss in den TEXTBEREICH des Feldes (y 146..170). Auf den blauen
#: Rahmen geklickt geht der Cursor zwar hin, die Eingabe geht danach verloren.
SCRIPT_INPUT_BOX = (414, 146, 1016, 170)

#: Verfuegbare Module (import-Test, FL 26.1): channels, general, transport,
#: playlist, mixer, patterns, device, ui. **Nicht** vorhanden: pattern (kein
#: setStep/getStep), info, note, crowdmix, daw, debug, fl.
SCRIPT_MODULES = (
    "channels", "general", "transport", "playlist",
    "mixer", "patterns", "device", "ui",
)

#: Was die API kann - und was sie nicht kann. Erschuetterend, aber entscheidend
#: fuer die Aufgabenverteilung GUI/API:
#:
#: Kann:  mixer.setCurrentTempo(bpm*1000) / getCurrentTempo()
#:        patterns.setPatternLength(i, takte) / getPatternLength(i)
#:        patterns.setPatternName / getPatternName / patternCount
#:        channels.getChannelName / setChannelName / muteChannel
#:        playlist.getTrackName / setTrackName / trackCount / selectTrack
#:        transport.play() / stop()
#:
#: Kann NICHT:
#:   * Playlist-Clips anlegen. ``playlist`` existiert in 26.1 zwar, hat aber
#:     nur Lese-/Auswahlfunktionen. ``insertLoopMode`` und
#:     ``insertPatternClip`` existieren NICHT - ``includeLoopMode`` ist nur
#:     der Snap-Modus. Deshalb: Clip per Stift-Werkzeug + Klick zeichnen.
#:   * Steps schreiben. Kein ``pattern``-Modul, kein setStep/getNote.
#:   * Dateien lesen/schreiben. ``open()`` -> SystemError, ``os.system`` und
#:     ``subprocess`` liefern -1 (gesperrt). Auch ``__file__`` fehlt.
#:     print() ins Memo ist der einzige Ausgabekanal.
#:   * Zaehlerfunktionen sind unzuverlaessig: ``patterns.patternCount()``
#:     lieferte 0, obwohl Pattern 0 existierte und ``getPatternLength(0)``
#:     sauber 70 zurueckgab. Einzelabfragen funktionieren, also nicht auf
#:     die Zaehler verlassen.
#:
#: Im Memo liest man die Ausgabe per Screenshot. ``WM_GETTEXT`` auf dem
#: Delphi-Memo (TQuickMemo) und auf dem Eingabefeld (TPyFormEdit) liefert
#: nichts - das sind keine Standard-Controls.
SCRIPT_API_FACTS = {
    "tempo_einheit": "mixer.setCurrentTempo(157000) -> 157.000 BPM; float wirft RuntimeError",
    "kein_dateisystem": "open() -> SystemError, os.system/subprocess -> -1",
    "kein_clip_api": "playlist.insertLoopMode / insertPatternClip existieren nicht",
    "kein_step_api": "kein pattern-Modul, kein setStep",
    "zaehler_maeandern": "patterns.patternCount() liefert 0 trotz existierender Patterns",
}

#: FL malt nur die Panels neu, die sich geaendert haben. Nach Klicks auf das
#: Script-Fenster oder den Channel Rack bleibt der Bildschirm "stale" - man
#: sieht dann den alten Playlist- oder Mixer-Inhalt an der Stelle des
#: Script-Fensters, obwohl der Befehl ausgefuehrt wurde. Win32 meldet
#: weiterhin korrekt Fenster und Trefferpunkt; nur die Pixel luegen.
#: Abhilfe: vor jeder Messung FL minimieren und restaurieren
#: (``SW_MINIMIZE``/``SW_RESTORE``), fuer den Rack dessen ``SC_RESTORE``/
#: ``SC_MAXIMIZE``. Das kostet ~2 s, spart aber Stunden Fehldeutung.
RECIPES_STALE = (
    "FL zeichnet Panels nicht zuverlaessig neu. Vor jeder Pixelmessung "
    "FL minimieren+restaurieren; fuer den Channel Rack SC_RESTORE/SC_MAXIMIZE. "
    "Win32-Fensterdaten sind dabei immer korrekt, nur die Pixel nicht."
)

RECIPES.update({
    # --- Drehregler ------------------------------------------------------
    "drehregler_genau_setzen": (
        "Drei Wege, absteigend nach Verlaesslichkeit:\n"
        "1) window_set_text / mouse_knob(reset=True): Alt+Linksklick auf den "
        "Regler setzt ihn auf den Defaultwert (100% zuverlaessig).\n"
        "2) Rechtsklick auf den Regler -> 'Type in value' -> Zahl tippen. "
        "Deterministisch, weil der Dialog den Wert als Text annimmt.\n"
        "3) mouse_knob(delta_px=N) = vertikaler Zug mit N Pixeln. Ungenau: FL "
        "rundet und rastet ein. Mit fine=True (Ctrl) ~4x feiner; no_snap=True "
        "(Shift) hebt die Rastpunkte auf.\n"
        "IMMER window='FL Studio' angeben - Panel-Fenster (Mixer, geoeffnetes "
        "Plugin) verwerfen jeden Klick ohne Eingabefokus."
    ),
    "drehregler_wert_auslesen": (
        "Maus ueber den Regler halten (mouse_move), ~0.4 s warten, dann "
        "screenshot(region=flstudio.hint_bar_rect(...)). Die Hint-Bar zeigt "
        "'Parameter - Wert in Einheit'. Der Wert-Dialog 'Type in value' "
        "anzeigen und ablesen ist ebenfalls moeglich, aber blockiert das "
        "Hauptfenster bis zum Schliessen."
    ),
    "drehregler_warum_keine_api": (
        "FLs Python-API kann Mixer-Tempo, Pattern-Laenge, Kanaele, Playlist-"
        "Spurnamen - aber KEINE Plugin-Parameter. plugins.setParamValue gibt "
        "es nicht. Deshalb ist der Mausweg fuer Regler der einzige Weg, und "
        "er braucht zwingend die Modifier (ctrl/alt/shift)."
    ),
    "regler_klicks_statt_drag": (
        "mouse_knob(clicks=5) scrollt 5 Rastungen ueber dem Regler. FL gibt "
        "jeder Rastung dieselbe Schrittweite, das Ergebnis ist damit "
        "reproduzierbar - ein Drag ueber N Pixel ist es nicht. Fuer "
        "wiederholbare Vergleiche (A/B eines Filters) deshalb clicks nutzen."
    ),
    # Tempo ueber die API statt ueber MIDI-Import: kein Neben effect, der
    # Clips an der Wiedergabeposition zerstoert.
    "set_tempo_api": (
        "VIEW > Script output, Reiter 'Interpreter' anklicken, Feld bei "
        "(715,158) mit use_clipboard=False tippen: "
        "import mixer; mixer.setCurrentTempo(140000). "
        "Toolbar zeigt danach 140.000."
    ),
    # Clip-Laenge haengt an der Pattern-Laenge - das umgeht das Ziehen des
    # Clip-Randes, dessen Kante ausserhalb des Bildschirms liegt.
    "clip_laenge": (
        "patterns.setPatternLength(0, taktzahl) setzt die Pattern-Laenge. "
        "Ein neu gezeichneter Playlist-Clip erbt sie. Danach Clip mit dem "
        "Stift-Werkzeug (1076,136) und einem Klick auf die Spurspur ziehen."
    ),
    "script_output_fenster": (
        "TPythonForm ist ein KINDfenster von FL. Position per "
        "SetWindowPos setzen, nicht per Maus-Drag - der Drag riss das "
        "FL-Hauptfenster mit und minimierte es."
    ),
    "steps_programmieren": (
        "Channel Rack per SC_MAXIMIZE vergroessern, dann Step n bei "
        "x = 602 + (n-1)*16, Kanaele y = 141/171/201/231/261. "
        "FL verschluckt einzelne Klicks: Soll-Ist-Loop bauen - klicken, "
        "Rack neu zeichnen, Steps per Pixelanalyse lesen, nachbessern."
    ),
    "step_geometrie_falle": (
        "Die ersten zwei Knöpfe einer Kanalzeile (x=573, 590) sind "
        "Vorschau-Felder, KEINE Steps. Eine Schaetzung lag hier 20 px daneben "
        "undProgrammierte die falschen Steps."
    ),
    "speichern_als": (
        "Ctrl+S ueberschreibt ein benanntes Projekt still. Immer "
        "Ctrl+Shift+S; FL zeigt den normalen Windows-Dialog (#32770). "
        "Pfad per WM_SETTEXT ins Namensfeld, Save-Knopf per BM_CLICK. "
        "Die Rueckfrage 'Datei existiert' sitzt im Dialog 'Confirm Save As' "
        "und wird ebenfalls per BM_CLICK auf '&Yes' bestaetigt."
    ),
})
