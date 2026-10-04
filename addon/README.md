# PC-Bediener + FL Studio OpenCode-Addon

Autonome PC-Steuerung und FL Studio Produktion mit pcbediener MCP-Tools.

## Installation

1. Kopiere den `addon`-Ordner in dein OpenCode-Addon-Verzeichnis.
2. Starte OpenCode neu.
3. Das Addon ist automatisch verfügbar.

## Verfügbare Tools

### Sicherheit
- `safety_status()` - Sicherheitsmodus anzeigen
- `safety_mode(mode)` - Modus umschalten (confirm/auto)

### Code-Ausführung (Modul A)
- `exec_python(code, confirm, timeout)` - Python-Code ausführen
- `exec_powershell(script, confirm, timeout)` - PowerShell-Skript
- `exec_command(command, shell, confirm, timeout)` - Shell-Befehl

### GUI & Prozesse (Modul B)
- `mouse_move(x, y, duration)` - Maus bewegen
- `mouse_click(x, y, button, clicks, confirm, window, mode)` - Klicken
- `mouse_drag(x1, y1, x2, y2, button, duration, steps)` - Drag & Drop
- `mouse_scroll(clicks, x, y, horizontal)` - Scrollen
- `keyboard_type(text, use_clipboard, interval)` - Text tippen
- `keyboard_press(key, presses)` - Taste drücken
- `keyboard_hotkey(keys)` - Hotkey ausführen
- `clipboard_set(text)` / `clipboard_get()` - Zwischenablage
- `sleep(seconds)` - Warten
- `window_list(filter_text)` - Fenster auflisten
- `window_focus(title, exact)` - Fenster aktivieren
- `window_action(title, action, confirm)` - Fensteraktion
- `window_modal_state(title, exact)` - Modal-Dialog prüfen
- `window_health(title, exact)` - Fenster-Gesundheit
- `window_activate(title, exact)` - In Vordergrund

### Hintergrund-Steuerung (Modul E)
- `window_list_controls(title, name_filter, exact)` - UIA-Controls
- `window_set_text(title, text, control_name, exact)` - Text setzen
- `window_invoke(title, control_name, exact)` - Control invoke
- `window_menu(title, path, exact)` - Menüpunkt wählen
- `window_key_shortcut(title, keys, exact)` - Tastenkombination

### Prozesse (Modul B)
- `process_list(filter_text, limit, sort_by)` - Prozesse auflisten
- `process_info(pid)` - Prozess-Details
- `process_start(program, arguments, background, confirm)` - Starten
- `process_kill(pid, force, confirm)` - Beenden

### Vision & System (Modul C)
- `screenshot(region, path, save, max_width)` - Screenshot
- `screen_find_image(image_path, region)` - Bild finden
- `screen_wait_for_image(image_path, timeout_s, poll_interval)` - Auf Bild warten
- `system_status(include_disk, disk_path)` - Systemstatus

### Dateisystem (Modul D)
- `file_read(path, max_chars)` - Textdatei lesen
- `file_read_binary(path, max_bytes)` - Binärdatei lesen
- `file_write(path, content, append, confirm)` - Schreiben
- `file_list(path, pattern, recursive)` - Ordnerinhalt
- `file_tree(path, max_depth)` - Baumansicht
- `file_search(path, pattern, filter_glob, max_results, max_depth)` - Suchen
- `folder_create(path)` - Ordner anlegen
- `file_move(src, dst, confirm, overwrite)` - Verschieben
- `file_copy(src, dst, overwrite)` - Kopieren
- `file_delete(path, recursive, confirm)` - Löschen

### Programm-Gedächtnis
- `app_rules_list(app)` - Regeln anzeigen
- `app_rule_get(app, name)` - Bedienweg holen
- `app_rule_set(app, name, steps, note)` - Bedienweg speichern
- `app_rule_break(app, name, reason, replacement)` - Defekt markieren

### FL Studio (Modul F)
- `flstudio_info()` - FL Studio Wissen (Fensterklassen, IDs, Shortcuts, Rezepte)

## FL Studio Wissen

### Fensterklassen
- TFruityLoopsMainForm (Hauptfenster)
- TNameEditForm (Umbenennen-Modal)
- TMsgForm (Bestätigungsdialog)
- #32770 (System-Dateidialog)
- TQuickPopupMenuWindow (Aufklapp-Menüs)
- TFLHintBarForm (Hinweis-Leiste)

### Fenster-IDs
- widMixer = 0
- widChannelRack = 1
- widPlaylist = 2
- widPianoRoll = 3
- widBrowser = 4

### Shortcuts
- F5 = Playlist
- F6 = Channel Rack
- F7 = Piano Roll
- F9 = Mixer
- Alt+F8 = Browser

### Rezepte
- Tempo setzen: FILE > Import > MIDI (tempoXXX.mid mit FF 51 03 <us/beat>)
- Audio importieren: Explorer > WAV per Drag&Drop in Playlist-Spurfläche
- Modal-Dialoge: window_modal_state() prüfen, TNameEditForm/TMsgForm schließen

## Arbeitsweise

1. Prüfe zuerst `safety_status()`
2. Nutze Tastatur-Shortcuts vor Maus
3. Warte nach Programmstarts mit `screen_wait_for_image()` oder `sleep()`
4. Korrigiere Fehler selbst (stderr analysieren, Code anpassen, erneut ausführen)
5. Verwende `flstudio_info()` für FL-Studio-Wissen
6. Nutze `app_rule_get()` für bewährte Bedienwege

## Entwicklung

Das Addon befindet sich unter `addon/pcbediener_addon.py`.
Die OpenCode-Konfiguration ist in `addon/opencode.json`.
