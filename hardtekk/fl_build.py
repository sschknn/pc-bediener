"""Baut die restlichen Hardtekk-Tracks in FL Studio.

Alle Koordinaten sind per Pixelanalyse an 1:1-Screenshots gemessen, nicht
geschaetzt. Wer sie aendert, sollte sie vorher nachmessen - eine
Schaetzung lag in dieser Session bis 20 px daneben.

Warum ueberhaupt GUI und nicht nur API:

Die FL-Python-API kann Tempo (``mixer.setCurrentTempo``), Pattern-Laenge
(``patterns.setPatternLength``), Namen und Transport. Sie kann aber
KEINE Playlist-Clips anlegen. ``playlist`` existiert zwar in FL 26.1,
hat aber nur Lese-/Auswahlfunktionen - ``insertLoopMode`` und
``insertPatternClip`` gibt es nicht (nur ``includeLoopMode`` fuer den
Snap-Modus). Auch ein ``pattern``-Modul mit ``setStep`` existiert nicht.
Clip und Steps bleiben daher zwingend GUI-Arbeit.

Zwei Stolperfallen, die den halben Aufbau gekostet haben:

1. ``keyboard_type(use_clipboard=True)`` schreibt in FLs Interpreter
   **nicht** - ohne Fehlermeldung, das Feld bleibt einfach leer. Es muss
   Zeichen fuer Zeichen getippt werden (``use_clipboard=False`` /
   ``pyautogui.write``).
2. FL zeichnet das Script-Fenster nicht zuverlaessig neu. Der Befehl
   laeuft, das Bild ist aber stale. Deshalb wird vor jeder Messung eine
   Neuzeichnung erzwungen (Minimieren/Restaurieren).

Klicks auf Step-Knoepfe werden nicht immer registriert. Deshalb
programmiert ``beat`` ueber einen Soll-Ist-Loop: klicken, neu zeichnen,
messen, nachbessern - statt blind zu klicken.
"""
from __future__ import annotations

import time
from pathlib import Path

import pyautogui
import win32con
import win32gui

pyautogui.FAILSAFE = False

# --- FL-Fenster -----------------------------------------------------------

FL_KLASSE = "TFruityLoopsMainForm"
SCRIPT_KLASSE = "TPythonForm"
RACK_KLASSE = "TStepSeqForm"

#: Menueleiste und Script-Fenster (1:1 bei 1920x1080)
MENU_VIEW = (169, 18)
MENU_SCRIPT_OUTPUT = (200, 232)
SCRIPT_POS = (400, 60, 630, 1000)
#: Eingabefeld des Interpreters: y 146..170 -> Mitte 158
SCRIPT_FELD = (715, 158)
#: "Clear output"-Knopf am unteren Rand des Script-Fensters
SCRIPT_CLEAR = (465, 1024)

#: Channel Rack: Kanalzeilen und Step-Positionen (gemessen nach SC_MAXIMIZE)
KANAL_Y = {"Kick": 141, "Clap": 171, "HiHat": 201, "Snare": 231, "Astro": 261}
STEP_X0 = 602
STEP_PITCH = 16

#: Hardtekk-Beat, 16tel-Raster
BEAT = {
    "Kick":  [1, 5, 9, 13],
    "Clap":  [5, 13],
    "HiHat": [2, 4, 6, 8, 10, 12, 14, 16],
    "Snare": [15],
    "Astro": [7, 15],
}

#: Browser: Zeilen der Vocal-Dateien unter hardtekk > vocalstems
VOCAL_Y = {"04": 685, "11": 706, "16": 727, "24": 748, "29": 769}
VOCAL_X = 110

#: Playlist: Spur-Baender y 148..196 (1) und 196..244 (2)
SPUR_Y = {1: 172, 2: 220}
TAKT1_X = 1251


def step_x(n: int) -> int:
    """x-Koordinate des n-ten Steps (1-basiert)."""
    return STEP_X0 + (n - 1) * STEP_PITCH


def _finde(klasse: str, titel: str | None = None) -> int:
    hwnd = win32gui.FindWindow(klasse, titel)
    return hwnd or 0


def _dialog_finden(titel: str | None) -> int:
    """Findet einen sichtbaren Windows-Dialog (#32770) per Titel."""
    treffer = []

    def cb(h, _):
        if win32gui.GetClassName(h) == "#32770" and win32gui.IsWindowVisible(h):
            if titel is None or win32gui.GetWindowText(h) == titel:
                treffer.append(h)
        return True

    win32gui.EnumWindows(cb, None)
    return treffer[0] if treffer else 0


def _klick(x: int, y: int, pause: float = 0.4) -> None:
    """Ein Klick mit kurzer Pause - FL verliert sonst schnelle Klicks."""
    pyautogui.moveTo(x, y)
    time.sleep(0.12)
    pyautogui.click()
    time.sleep(pause)


def fl_zeichne_neu() -> None:
    """Erzwingt eine Neuzeichnung von FLs Hauptfenster.

    FL malt nur die Panels neu, die sich geaendert haben. Nach Klicks auf
    das Script-Fenster oder den Rack bleibt der Bildschirm sonst stale und
    jede Messung liest Muell.
    """
    hwnd = _finde(FL_KLASSE)
    if not hwnd:
        return
    win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
    time.sleep(0.9)
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    time.sleep(1.3)
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.4)


def rack_zeichne_neu() -> None:
    """Neuzeichnung nur des Channel Racks - schneller als das ganze Fenster."""
    hwnd = _finde(FL_KLASSE)
    if not hwnd:
        return
    rack = []

    def cb(h, _):
        if win32gui.GetClassName(h) == RACK_KLASSE:
            rack.append(h)
        return True

    win32gui.EnumChildWindows(hwnd, cb, None)
    if not rack:
        return
    for msg in (win32con.SC_RESTORE, win32con.SC_MAXIMIZE):
        win32gui.PostMessage(rack[0], win32con.WM_SYSCOMMAND, msg, 0)
        time.sleep(0.9)


# --- Interpreter -----------------------------------------------------------


def script_fenster() -> int:
    """Oeffnet FLs 'Script output' und legt es an feste Koordinaten."""
    hwnd = _finde(SCRIPT_KLASSE, "Script output")
    if not hwnd:
        pyautogui.moveTo(*MENU_VIEW)
        time.sleep(0.15)
        pyautogui.click()
        time.sleep(1.8)
        pyautogui.moveTo(*MENU_SCRIPT_OUTPUT)
        time.sleep(0.15)
        pyautogui.click()
        time.sleep(3.5)
        hwnd = _finde(SCRIPT_KLASSE, "Script output")
    if not hwnd:
        raise RuntimeError("FLs Script-Fenster laesst sich nicht oeffnen")
    win32gui.SetWindowPos(
        hwnd, win32con.HWND_TOP, *SCRIPT_POS, win32con.SWP_SHOWWINDOW)
    win32gui.BringWindowToTop(hwnd)
    time.sleep(0.8)
    return hwnd


def befehl(text: str) -> None:
    """Schickt einen Einzeiler an FLs Interpreter.

    Wichtig: ``pyautogui.write`` tippt Zeichen fuer Zeichen. Paste per
    Zwischenablage kommt in diesem Feld **nicht** an.
    """
    script_fenster()
    _klick(*SCRIPT_FELD, pause=0.9)
    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.2)
    pyautogui.press("delete")
    time.sleep(0.3)
    pyautogui.write(text, interval=0.015)
    time.sleep(0.8)
    pyautogui.press("enter")
    time.sleep(2.8)


def script_schliessen() -> None:
    hwnd = _finde(SCRIPT_KLASSE, "Script output")
    if hwnd:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        time.sleep(1.0)


def tempo_und_laenge(bpm: float, takte: int) -> None:
    """Setzt Tempo und Pattern-Laenge - beides ueber die API."""
    befehl(
        "import mixer, patterns; "
        "mixer.setCurrentTempo(%d); "
        "patterns.setPatternLength(0, %d); "
        "print('TEMPO', mixer.getCurrentTempo(), 'TAKTE', patterns.getPatternLength(0))"
        % (int(round(bpm * 1000)), takte)
    )
    script_schliessen()


# --- Playlist --------------------------------------------------------------


def clip_waehlen_und_loeschen(spur_y: int) -> None:
    _klick(1400, spur_y, pause=1.0)
    pyautogui.press("delete")
    time.sleep(1.5)


def clip_ziehen(x1: int, y1: int, x2: int, y2: int) -> None:
    """Drag innerhalb FLs - braucht Pausen, sonst startet er nicht."""
    pyautogui.moveTo(x1, y1)
    time.sleep(0.4)
    pyautogui.mouseDown()
    time.sleep(0.5)
    pyautogui.moveTo(x1 + 4, y1 + 7, duration=0.4)
    time.sleep(0.3)
    pyautogui.moveTo((x1 + x2) // 2, (y1 + y2) // 2, duration=0.8)
    time.sleep(0.3)
    pyautogui.moveTo(x2, y2, duration=1.0)
    time.sleep(0.8)
    pyautogui.mouseUp()
    time.sleep(4.0)


def clip_zeichnen(spur: int) -> None:
    """Legt den aktiven Pattern als Clip an (Stift-Werkzeug + Klick)."""
    _klick(1076, 136, pause=1.5)          # Stift
    _klick(TAKT1_X + 20, SPUR_Y[spur], pause=3.5)


def vocal_einsetzen(nr: str) -> None:
    """Zieht den passenden Vocal aus dem Browser auf Spur 1."""
    clip_waehlen_und_loeschen(SPUR_Y[1])
    clip_ziehen(VOCAL_X, VOCAL_Y[nr], TAKT1_X + 20, SPUR_Y[1])


def beat_einsetzen() -> None:
    """Ersetzt den Beat-Clip auf Spur 2 durch einen in aktueller Laenge."""
    clip_waehlen_und_loeschen(SPUR_Y[2])
    clip_zeichnen(2)


# --- Step-Sequencer --------------------------------------------------------


def _steps_lesen() -> dict:
    """Liest die aktiven Steps je Kanal aus dem Rack-Bild."""
    from PIL import ImageGrab

    img = ImageGrab.grab().crop((383, 108, 1919, 328)).convert("RGB")
    px = img.load()

    def lum(x, y):
        r, g, b = px[x, y]
        return 0.299 * r + 0.587 * g + 0.114 * b

    zustand = {}
    for name, sy in KANAL_Y.items():
        yc = sy - 108
        an = []
        for n in range(1, 17):
            xc = STEP_X0 - 383 + (n - 1) * STEP_PITCH
            m = sum(
                lum(xc + dx, yc + dy)
                for dx in (-2, -1, 0, 1, 2)
                for dy in range(-6, 7)
            ) / 65.0
            if m > 130:
                an.append(n)
        zustand[name] = an
    return zustand


def beat_programmieren(max_runden: int = 7) -> dict:
    """Programmiert den Beat selbstkorrigierend.

    FL verschluckt einzelne Klicks auf den Step-Knoepfen. Statt blind zu
    klicken wird jede Runde gemessen und nur die Abweichung nachgebessert,
    mit mehreren y-Versuchen pro Step.
    """
    for runde in range(max_runden):
        rack_zeichne_neu()
        ist = _steps_lesen()
        fehler = []
        for name, soll in BEAT.items():
            fehler += [(name, n, True) for n in sorted(set(soll) - set(ist[name]))]
            fehler += [(name, n, False) for n in sorted(set(ist[name]) - set(soll))]
        if not fehler:
            return ist
        for name, n, gewuenscht in fehler:
            x = step_x(n)
            y_basis = KANAL_Y[name]
            for dy in (0, -4, 4, -8, 8, -12, 12):
                _klick(x, y_basis + dy, pause=0.35)
                rack_zeichne_neu()
                if (n in _steps_lesen()[name]) == gewuenscht:
                    break
    return _steps_lesen()


# --- Speichern -------------------------------------------------------------


FL_PROJEKTE = r"C:\Users\frank\Documents\Image-Line\FL Studio\Projects"


def speichern(name: str, ordner: str = FL_PROJEKTE) -> str:
    """Speichert als <ordner>\\<name>.flp und gibt den vollen Pfad zurueck.

    Wichtig: **Strg+S reicht nicht.** Ist das Projekt bereits benannt,
    ueberschreibt Strg+S stillschweigend die bestehende Datei - so wurde
    in dieser Session versehentlich Track 24 mit den Daten von Track 04
    ueberschrieben. Es braucht "Save as" (Strg+Umschalt+S).

    FL zeigt dafuer den normalen Windows-Dialog (#32770), nicht seinen
    eigenen. Der wird deshalb per Win32 bedient: Pfad ins Namensfeld
    setzen, Save-Knopf klicken. Keine festen Koordinaten, die brechen
    sofort, wenn der Dialog woanders aufgeht.
    """
    fl = _finde(FL_KLASSE)
    win32gui.SetForegroundWindow(fl)
    time.sleep(0.6)
    pyautogui.hotkey("ctrl", "shift", "s")
    time.sleep(4.5)

    ziel = str(Path(ordner) / (name + ".flp"))
    dlg = _dialog_finden("Save As")
    if not dlg:
        raise RuntimeError("Save-as-Dialog kam nicht")

    edit, knopf = None, None
    def cb(h, _):
        nonlocal edit, knopf
        c = win32gui.GetClassName(h)
        t = win32gui.GetWindowText(h)
        if c == "Edit" and edit is None and win32gui.IsWindowVisible(h):
            edit = h
        if c == "Button" and t.replace("&", "") in ("Save", "Speichern"):
            knopf = h
        return True

    win32gui.EnumChildWindows(dlg, cb, None)
    if edit is None or knopf is None:
        raise RuntimeError("Namensfeld oder Save-Knopf im Dialog nicht gefunden")

    win32gui.SendMessage(edit, win32con.WM_SETTEXT, 0, ziel)
    time.sleep(0.6)
    win32gui.SendMessage(knopf, win32con.BM_CLICK, 0, 0)
    time.sleep(4.0)
    _bestaetige_ueberschreiben()
    return ziel


def _bestaetige_ueberschreiben() -> None:
    """Bestaetigt 'Datei existiert. Ersetzen?' per Win32.

    Erscheint nur, wenn der Zielname schon vergeben ist. Per Maus zu
    klicken ist fehleranfaellig, weil der Dialog frei platziert ist.
    """
    time.sleep(1.5)
    dlg = _dialog_finden("Confirm Save As")
    if not dlg:
        return

    def cb(h, _):
        if win32gui.GetClassName(h) == "Button":
            beschriftung = win32gui.GetWindowText(h).replace("&", "")
            if beschriftung in ("Yes", "Ja"):
                win32gui.SendMessage(h, win32con.BM_CLICK, 0, 0)
                return False
        return True

    win32gui.EnumChildWindows(dlg, cb, None)
    time.sleep(6.0)