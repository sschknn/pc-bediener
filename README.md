# PC-Bediener

Lokale PC-Steuerung für eine KI über **MCP** (Model Context Protocol). Die KI
steuert den Rechner über 35 Werkzeuge in vier Modulen — Code-Ausführung,
GUI/Prozesse, Vision und Dateisystem — und bekommt jeden Fehler als lesbare
Meldung zurück, den sie selbst korrigieren kann.

| Modul | Inhalt | Werkzeuge |
|---|---|---|
| **A** – Code-Ausführung | Python, PowerShell, Shell → stdout/stderr/Exit-Code | `exec_python`, `exec_powershell`, `exec_command` |
| **B** – GUI & Prozesse | Maus (inkl. Drehregler), Tastatur, Fenster, Prozesse | 19 Tools (`mouse_*`, `keyboard_*`, `window_*`, `process_*`) |
| **C** – Vision & Status | Screenshots, Bildsuche, CPU/RAM/Disk | `screenshot`, `screen_find_image`, `system_status`, … |
| **D** – Dateisystem | Lesen, Schreiben, Suchen, Verschieben, Löschen | 10 Tools (`file_*`) |

> `pyautogui`, `psutil`, `pywin32`, `PIL` — die vier Bibliotheken aus der
> Aufgabenstellung sind die Basis der Module B und C.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Prüfen, ob alles bereit ist:

```powershell
.\.venv\Scripts\python.exe -m pcbediener doctor
```

```
[OK  ] Python >= 3.11     3.11.9
[OK  ] pyautogui          Maus, Tastatur, Screenshot
[OK  ] psutil             Prozesse, Systemstatus
[OK  ] PIL                Bildverarbeitung
[OK  ] win32gui           Fenstersteuerung
[OK  ] mcp                MCP-Server
[OK  ] Screenshot         1920x1200 @ 1920px
[OK  ] Fensterzugriff     12 sichtbare Fenster
```

## Als MCP-Server in OpenCode eintragen

Der Server spricht **stdio** — läuft also als Kindprozess von OpenCode, kein
Port, kein Netzwerk.

```powershell
opencode mcp add pcbediener -- "C:\Users\frank\Documents\Projekte\pc bediener\.venv\Scripts\python.exe" -m pcbediener serve
opencode mcp list
```

Oder von Hand in `opencode.jsonc` (liegt dem Projekt bereits bei):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "pcbediener": {
        "type": "local",
        "command": [
          "C:\\Users\\frank\\Documents\\Projekte\\pc bediener\\.venv\\Scripts\\python.exe",
          "-m",
          "pcbediener",
          "serve"
        ],
        "cwd": "C:\\Users\\frank\\Documents\\Projekte\\pc bediener"
      }
    }
  }
}
```

Wichtig für V2:

- Server liegen unter **`mcp.servers`**, nicht direkt unter `mcp`. Ein
  `enabled`-Feld gibt es nicht — zum Deaktivieren dient `disabled: true`.
- `cwd` bestimmt das Arbeitsverzeichnis des Serverprozesses. Der
  `screenshot_dir` wird relativ dazu aufgelöst, Screenshots landen also im
  Projektordner.
- OpenCode benennt die Tools `<server>_<tool>`; im Code Mode sind sie als
  `tools.pcbediener.exec_python(...)` gruppiert. Der Server-Name ist darum
  bewusst ohne Bindestrich gewählt.

Der vollständige KI-System-Prompt liegt in **[AGENTS.md](AGENTS.md)** und kann
als Instructions übernommen werden.

## Sicherheitsmodi

Der Modus ist umschaltbar — wie gewünscht entweder mit Bestätigung oder
vollautonom.

| Modus | Verhalten |
|---|---|
| `confirm` (Standard) | Destruktive Aktionen laufen nur mit `confirm=True`. Der Aufruf scheitert sonst mit `ConfirmationRequired`. |
| `auto` | Die KI handelt vollautonom, ohne Rückfrage. |

**In beiden Modi gilt die Sperrliste in `src/pcbediener/safety.py` immer.**
Sie blockiert u. a. `format`, `diskpart`, `rd C:\`, `del /s /q C:\*`,
`rm -rf /`, `Remove-Item C:\... -Recurse`, `shutil.rmtree('C:/')`,
`cipher /w`, `vssadmin delete shadows`, Bootmanipulation via `bcdedit`,
`Set-ExecutionPolicy Unrestricted`, `Invoke-Expression`/`iex`,
Registry-Autostart und `shutdown`.

Weitere Schranken, die nicht abschaltbar sind:

- **Pfadgrenzen** — Dateioperationen nur innerhalb von `allowed_paths`
  (Vorgabe: der Benutzerordner). Ausbruch über `..` oder Symlinks wird durch
  `Path.resolve()` verhindert.
- **Prozessschutz** — `explorer.exe`, `svchost.exe`, `csrss`, `lsass`,
  `winlogon` und der eigene Prozess lassen sich nicht beenden.
- **Ordner-Schutz beim Löschen** — nicht-leere Ordner werden nur mit
  `recursive=True` gelöscht.

Umschalten:

```powershell
# dauerhaft
.\.venv\Scripts\python.exe -m pcbediener config set --safety-mode auto
.\.venv\Scripts\python.exe -m pcbediener config set --safety-mode confirm

# oder zur Laufzeit aus der Unterhaltung heraus
#   safety_mode("auto")   /   safety_mode("confirm")
```

## Konfiguration

Standard: `%APPDATA%\pcbediener\config.json`

```json
{
  "safety_mode": "confirm",
  "allowed_paths": ["C:\\Users\\frank\\Documents"],
  "exec_timeout": 60,
  "exec_max_output_chars": 20000,
  "screenshot_dir": "C:\\Users\\frank\\Documents\\Projekte\\pc bediener\\screenshots",
  "forbidden_patterns": ["mein_geheimer_befehl"]
}
```

Alles lässt sich auch per CLI setzen oder per Umgebungsvariable überschreiben
(`PCB_SAFETY_MODE`, `PCB_EXEC_TIMEOUT`, `PCB_CONFIG`, …):

```powershell
.\.venv\Scripts\python.exe -m pcbediener config set --add-allowed-path "C:\Users\frank\Downloads"
.\.venv\Scripts\python.exe -m pcbediener config show
```

## CLI

| Befehl | Zweck |
|---|---|
| `python -m pcbediener serve` | MCP-Server auf stdio starten |
| `python -m pcbediener doctor` | Umgebung auf Laufbereitschaft prüfen |
| `python -m pcbediener tools` | alle Tools mit Beschreibung auflisten |
| `python -m pcbediener status` | Systemstatus als JSON |
| `python -m pcbediener shot -p x.png` | Screenshot aufnehmen |
| `python -m pcbediener config show\|path\|init\|set` | Konfiguration verwalten |

## Aufbau

```
src/pcbediener/
├── mcp_server.py    # 35 Tools, Fehlerbehandlung, Sicherheits-Metadaten
├── cli.py           # Kommandozeile
├── config.py        # Defaults + JSON-Datei + PCB_-Umgebungsvariablen
├── safety.py        # Sperrliste + Bestätigungs-Gate  ← zentrale Schranke
├── paths.py         # Pfad-Allowlist (resolve gegen Symlinks/..)
├── runtime.py       # aktive Config, umschaltbar zur Laufzeit
└── modules/
    ├── exec.py      # Modul A
    ├── gui.py       # Modul B: Maus, Tastatur, Fenster
    ├── proc.py      # Modul B: Prozesse
    ├── vision.py    # Modul C: Screenshots, Status, Bildsuche
    └── files.py     # Modul D: Dateisystem
```

Die Sicherheitslogik liegt bewusst **nur** in `safety.py` und `paths.py`.
Jedes Modul fragt dort nach, bevor es etwas Destruktives tut — die Module
selbst enthalten keine eigenen Prüfungen.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

```
213 passed, 1 skipped
```

Abgedeckt sind Konfiguration, Sperrliste, Pfadgrenzen, alle vier Module,
die MCP-Schemas und – wichtig – ein echter **stdio-Handshake**: Der Test
startet `python -m pcbediener serve` als Subprozess und ruft Tools über das
MCP-Protokoll auf. GUI- und Vision-Tests verwenden eine Attrappe statt
`pyautogui`, damit sie nie den echten Desktop beeinflussen.

Zwei Regressionstests sind besonders lehrreich:

- `test_all_pywin32_attributes_exist` prüft **jedes** verwendete
  `win32gui`/`win32con`/`win32process`-Attribut statisch. pywin32 verteilt seine
  Funktionen auf mehrere Module (`GetWindowThreadProcessId` liegt in
  `win32process`, `GetCurrentThreadId` in `win32api`, `IsZoomed` gibt es nur
  über `ctypes`) – solche Fehler fallen sonst erst zur Laufzeit auf.
- `test_list_windows_finds_what_win32_sees` vergleicht `window_list()` direkt
  mit einer rohen `EnumWindows`-Zählung, damit ein verschluckter Fehler nicht
  als „es gibt keine Fenster" durchgeht.

### Maussteuerung live prüfen

Unit-Tests mit einer Attrappe beweisen nur, dass die Aufrufe *gemacht*
werden – nicht, dass Windows sie auch *zustellt*. Genau daran scheitert
GUI-Automation. Deshalb gibt es zusätzlich einen Prüfstand gegen echtes
Fenster:

```powershell
.\.venv\Scripts\python.exe tools\verify_mouse.py
```

Er startet ein Tk-Fenster, das jeden Maus-Input protokolliert (Positionen,
Tastendrücke, Modifier-Zustand, Mausrad), positioniert es bewusst auf dem
**linken** Monitor (`x < 0`) und fährt es mit `sendinput_move/click/drag/scroll`
an. Geprüft werden u. a.:

- pixelgenaues Landen auf negativen Koordinaten,
- 24 Einzelimpulse für einen 24-Schritt-Drag statt eines Sprungs,
- exakter Gesamtweg (kein ±1-px-Rundungsfehler),
- `Ctrl` bleibt während des Drags gedrückt und ist danach wieder frei,
- Mausrad-Vorzeichen, `Alt`+Klick, `Ctrl`+`Shift` gleichzeitig, `hold_ms`.

Dieser Prüfstand hat zwei echte Fehler gefunden, die kein Attrappen-Test
gesehen hätte: die 1-px-Abweichung absoluter SendInput-Koordinaten (Windows
rundet pro Monitor) und die stillschweigend ignorierte `hold_ms` im
SendInput-Klick-Modus.

## Hinweise

- Der Server arbeitet in der Benutzersitzung, in der er gestartet wurde.
  Fenster anderer Sitzungen sind nicht sichtbar.
- Der Maus-Fail-Safe von `pyautogui` bleibt aktiv (Maus in die obere linke
  Ecke = Abbruch).
- Koordinaten sind **Desktop**-Koordinaten. Bei mehreren Monitoren können sie
  negativ sein; `screen_info()` liefert den Ursprung und die Gesamtgrösse des
  virtuellen Desktops.
- `mcp` 2.x wird vorausgesetzt (`mcp.server.mcpserver.MCPServer`). In 1.x hieß
  die Klasse `FastMCP`.