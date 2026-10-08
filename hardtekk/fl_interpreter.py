"""Steuert FL Studio ueber den eingebauten Interpreter.

Warum ueber den Interpreter und nicht ueber Klicks:
Die GUI-Automation scheiterte wiederholt, weil sich Browser-Zeilen und
Panel-Positionen verschieben, sobald sich das Layout aendert. Der
Interpreter dagegen gibt FLs echten Projektzustand zurueck -
kanaele, Patterns, Tempo - und setzt Werte direkt.

Einschraenkung (empirisch geprueft):
  * Der Interpreter kann ALLES lesen und fast alles schreiben.
  * Tempo laesst sich ueber general.setValue setzen.
  * Playlist-Clips kann er NICHT anlegen - dafuer bleibt die GUI
    noetig, aber mit vorher vermessener Geometrie statt geratenen
    Koordinaten.

Arbeitsweise je Befehl: Fenster positionieren -> Feld fokussieren ->
Befehl einfuegen -> Ausgabe ablesen.
"""
from __future__ import annotations

#: Wo das "Script output"-Fenster beim Zugriff stehen soll.
#:
#: Position und Groesse werden per Win32 gesetzt, nicht per Maus-Drag:
#: der Drag hat das FL-Hauptfenster mitgerissen und minimiert.
FENSTER_X = 400
FENSTER_Y = 60
FENSTER_W = 630
FENSTER_H = 1000

#: Versatz vom Fensterrand zum Eingabefeld.
#:
#: VORHER KAM DAS IMMER ZUERST: der Reiter "Interpreter" muss aktiv sein.
#: Standardmaessig steht das Fenster auf dem Reiter "loopMIDI Port 2"
#: (dem Skript-Reiter). Solange der falsche Reiter vorn ist, nimmt das
#: Eingabefeld nichts an - es bleibt einfach leer, ohne jede Fehlermeldung.
#:
#: Danach muss der Klick in den TEXTBEREICH des Feldes gehen, nicht auf
#: den blauen Rahmen: Rahmenklick setzt den Cursor, die Eingabe geht dann
#: aber verloren.
REITER_X = 110
REITER_Y = 50
FELD_DX = 100
FELD_DY = 118


class Interpreter:
    """Kanal zu FL Studios Script-Interpreter."""

    def __init__(self, tools):
        self.t = tools

    async def fenster_platzieren(self) -> dict:
        """Setzt das Script-Fenster an eine feste Position und Groesse.

        Per Win32 gesetzt statt per Maus-Drag: beim Drag hat der
        Versuch das FL-Hauptfenster mitgerissen und minimiert, weil das
        Script-Fenster ein Kindfenster von FL ist.

        Ohne ausreichende Hoehe ragt die Ausgabe aus dem Fenster heraus
        und wird beim Screenshot abgeschnitten - man sieht dann zwar
        einen ``RuntimeError``, aber nicht das Ergebnis.
        """
        hwnd = await self._finde_fenster()
        r = await self.t.exec_python({
            "confirm": True,
            "code": (
                "import win32gui, win32con\n"
                "h = win32gui.FindWindow('TPythonForm', 'Script output')\n"
                "if not h: raise RuntimeError('FLs Script-Fenster ist nicht offen')\n"
                "win32gui.SetWindowPos(h, win32con.HWND_TOP, %d, %d, %d, %d,\n"
                "                      win32con.SWP_SHOWWINDOW)\n"
                "print(win32gui.GetWindowRect(h))\n"
                % (FENSTER_X, FENSTER_Y, FENSTER_W, FENSTER_H)
            ),
        })
        await self.t.sleep({"seconds": 1.2})
        return hwnd

    async def _finde_fenster(self) -> dict:
        w = await self.t.window_list({"filter_text": "Script output"})
        if not w.get("windows"):
            raise RuntimeError(
                "FLs 'Script output'-Fenster ist nicht offen. "
                "Oeffnen ueber: VIEW > Script output"
            )
        return w["windows"][0]

    async def reiter_aktivieren(self) -> None:
        """Klickt den 'Interpreter'-Reiter an.

        Noetig, weil FL das Fenster standardmaessig mit dem Skript-Reiter
        (``loopMIDI Port 2``) oeffnet. Ist der falsche Reiter vorn, geht
        jede Eingabe ins Leere - ohne Fehlermeldung, das Feld bleibt
        einfach leer. Genau das kostete mehrere erfolglose Versuche.
        """
        await self.t.mouse_click({
            "x": FENSTER_X + REITER_X, "y": FENSTER_Y + REITER_Y,
            "confirm": True, "hold_ms": 200,
        })
        await self.t.sleep({"seconds": 1.2})

    async def fuehre(self, befehl: str) -> str:
        """Schickt einen Befehl an FL und liefert die Ausgabe zurueck."""
        await self.fenster_platzieren()
        await self.reiter_aktivieren()
        await self.t.mouse_click({
            "x": FENSTER_X + FELD_DX, "y": FENSTER_Y + FELD_DY,
            "confirm": True, "hold_ms": 300,
        })
        await self.t.sleep({"seconds": 1.0})
        await self.t.clipboard_set({"text": befehl})
        await self.t.keyboard_hotkey({"keys": ["ctrl", "v"]})
        await self.t.sleep({"seconds": 1.0})
        await self.t.keyboard_press({"key": "enter"})
        await self.t.sleep({"seconds": 2.5})

    async def pattern_laenge(self, index: int, takte: int | None = None) -> str:
        """Liest oder setzt die Laenge eines Patterns in Takten.

        Wichtig fuer Playlist-Clips: ein Clip erbt die Laenge seines
        Patterns. Ein 70-Takt-Vocal braucht ein 70-Takt-Pattern, sonst
        muss der Clip per Rand gezogen werden - und der Clip-Rand liegt
        dann ausserhalb des erreichbaren Bildschirms.
        """
        if takte is None:
            await self.fuehre(
                "import patterns; print('LEN:', patterns.getPatternLength(%d))" % index)
        else:
            await self.fuehre(
                "import patterns; patterns.setPatternLength(%d, %d); "
                "print('LEN:', patterns.getPatternLength(%d))" % (index, takte, index))

    async def tempo_setzen(self, bpm: float) -> str:
        """Setzt das Projekt-Tempo.

        FL 26.1 rechnet in **Millisekunden pro Beat x 1000**:
        157000 ergibt 157.000 BPM in der Toolbar. Ein Float loest
        ``RuntimeError: Range error`` aus, deshalb wird ganzzahlig
        gesetzt.
        """
        wert = int(round(float(bpm) * 1000))
        await self.fuehre(
            "import mixer; mixer.setCurrentTempo(%d); "
            "print('TEMPO:', mixer.getCurrentTempo())" % wert
        )

    async def tempo_lesen(self) -> str:
        await self.fuehre(
            "import mixer; print('TEMPO:', mixer.getCurrentTempo())")

    async def kanaele(self) -> str:
        await self.fuehre(
            "import channels; print('KANAELE:', channels.channelCount(1), ["
            "channels.getChannelName(i) for i in range(channels.channelCount(1))])")

    async def patterns(self) -> str:
        await self.fuehre(
            "import patterns; print('PATTERNS:', patterns.patternCount())")

    async def abspielen(self) -> str:
        await self.fuehre("import transport; transport.play(); print('PLAY')")

    async def stoppen(self) -> str:
        await self.fuehre("import transport; transport.stop(); print('STOP')")

    async def kanal_mute(self, index: int, an: bool) -> str:
        await self.fuehre(
            "import channels; channels.muteChannel(%d, %d); print('MUTE %d = %d')"
            % (index, 1 if an else 0, index, 1 if an else 0))

    async def kanal_lautstaerke(self, index: int, wert: float) -> str:
        await self.fuehre(
            "import channels; channels.setChannelVolume(%d, %r); "
            "print('VOL %d =', channels.getChannelVolume(%d))"
            % (index, float(wert), index, index))

    async def kanal_benennen(self, index: int, name: str) -> str:
        await self.fuehre(
            "import channels; channels.setChannelName(%d, %r); "
            "print('NAME %d =', channels.getChannelName(%d))"
            % (index, name, index, index))

    async def mixer_tracks(self) -> str:
        await self.fuehre("import mixer; print('MIXER:', mixer.trackCount())")

    async def projekt_info(self) -> str:
        await self.fuehre(
            "import general, channels, patterns, mixer; "
            "print('INFO:', general.getVersion(), '| Tempo', "
            "mixer.getCurrentTempo(), '| Kanaele', channels.channelCount(1), "
            "| Patterns', patterns.patternCount(), "
            "| Mixer', mixer.trackCount())")

    async def ausgabe(self) -> str:
        """Liest den Ausgabebereich als Screenshot zurueck.

        Der Interpreter gibt Text nicht als Rueckgabewert zurueck, er
        schreibt ihn in sein Fenster. Das ist der einzige Weg.
        """
        p = await self.t.screenshot({
            "region": [FENSTER_X + 12, FENSTER_Y + 130, FENSTER_W - 24, 700],
            "max_width": 1212,
        })
        return p["path"]