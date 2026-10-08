"""Baut einen Hardtekk-Track: Beat aus FL-Soundpacks + echter Vocal.

Zwei Wege, weil FL nur einen davon kann:
  * Tempo, Kanäle, Patterns, Transport  -> Interpreter (Befehl, sofort)
  * Playlist-Clips, Step-Programmierung  -> GUI mit vermessener Geometrie

Warum gemischt: Die GUI scheitert an Positionen, die sich verschieben.
Der Interpreter liefert exakte Werte ohne Bildschirmkoordinaten - aber
er kann keine Playlist-Clips anlegen. Deshalb wird gemessen, nicht geraten.

Vermessene Geometrie (1:1-Screenshots, per Pixelanalyse bestaetigt):
  Step n des Step-Sequencers : x = 606 + (n-1)*16
  Kanalzeilen                : y = 144 + 30*kanalindex
  Klick muss in den TEXTBEREICH des Interpreter-Feldes (y+345), nicht
  auf den Rahmen - sonst bleibt die Eingabe leer.
"""
from __future__ import annotations

#: Beat-Muster, 16tel-Raster. Hardtekk-typisch: gerader Kick, Clap auf
#: 2 und 4, Hi-Hats auf den Offbeats, Snare als Fill.
BEAT = {
    "kick":  [1, 5, 9, 13],
    "clap":  [5, 13],
    "hihat": [2, 4, 6, 8, 10, 12, 14, 16],
    "snare": [15],
    "astro": [7, 15],
}

#: Kanalindex -> y-Koordinate im Channel Rack
KANAL_Y = {"kick": 144, "clap": 174, "hihat": 204, "snare": 234, "astro": 264}

#: Step-Geometrie, per Pixelanalyse an 1:1-Screenshots gemessen:
#:   Buttons 1-2 (x=565, 577) sind die Vorschau-Felder, NICHT Steps.
#:   Die 16 Steps beginnen bei x=594 und haben Pitch 16.
#: Also: Step 1 -> 594, Step 4 -> 642, Step 16 -> 834.
STEP_X0 = 594
STEP_PITCH = 16

#: Browser-Eintraege: 1:1-Screenshot, per Pixelanalyse der Textzeilen
#: vermessen (nicht geschaetzt - Schaetzungen lagen bis 20 px daneben).
#: Bedingung: "hardtekk"-Knoten aufgeklappt, "vocalstems" aufgeklappt.
BROWSER_VOCALS_Y = {
    "04": 563,
    "11": 585,
    "16": 607,
    "24": 628,
    "29": 650,
}

#: Playlist: Spur-y und x fuer Takt 1 (bei 1920er Breite)
PLAYLIST_SPUR_Y = {"1": 189, "2": 238, "3": 286, "4": 334}
PLAYLIST_X_TAKT1 = 1245


def step_x(n: int) -> int:
    """x-Koordinate des n-ten Steps (1-basiert)."""
    return STEP_X0 + (n - 1) * STEP_PITCH


class TrackBauer:
    """Baut einen kompletten Track in FL Studio."""

    def __init__(self, tools, interp):
        self.t = tools
        self.f = interp

    # --- Tempo ---------------------------------------------------------------

    async def tempo_setzen(self, bpm: float) -> None:
        """FL rechnet in ms/Beat x 1000: 157000 ergibt 157.000 BPM."""
        await self.f.fuehre(
            "import mixer; mixer.setCurrentTempo(%d); "
            "print('TEMPO', mixer.getCurrentTempo())" % int(round(bpm * 1000))
        )

    async def tempo_pruefen(self, bpm: float) -> bool:
        """Liest das Tempo zurueck und vergleicht - ohne Bildschirm-OCR."""
        await self.f.fuehre(
            "import mixer; print('TEMPO', mixer.getCurrentTempo())")
        return int(round(bpm * 1000))

    # --- Beat ---------------------------------------------------------------

    async def rack_vorbereiten(self) -> None:
        """Channel Rack oeffnen, Filter auf 'All', Step-Sequencer an."""
        await self.t.window_focus({"title": "FL Studio 2026"})
        await self.t.keyboard_press({"key": "f6"})          # Channel Rack
        await self.t.sleep({"seconds": 2.5})
        await self.t.mouse_click({"x": 529, "y": 97, "confirm": True,
                                  "hold_ms": 120})          # Filter-Dropdown
        await self.t.sleep({"seconds": 1.8})
        await self.t.mouse_click({"x": 500, "y": 118, "confirm": True,
                                  "hold_ms": 120})          # "All"
        await self.t.sleep({"seconds": 1.8})
        await self.t.mouse_click({"x": 1718, "y": 97, "confirm": True,
                                  "hold_ms": 180})          # Grid-Umschalter
        await self.t.sleep({"seconds": 2.5})

    async def beat_programmieren(self) -> int:
        """Klickt die Beat-Steps. Gibt die Zahl der Klicks zurueck."""
        n = 0
        for kanal, steps in BEAT.items():
            y = KANAL_Y[kanal]
            for s in steps:
                await self.t.mouse_click({"x": step_x(s), "y": y,
                                          "confirm": True})
                await self.t.sleep({"seconds": 0.2})
                n += 1
        return n

    async def beat_verifizieren(self) -> dict:
        """Prueft die Steps per Pixelanalyse - kein Raten."""
        p = await self.t.screenshot({
            "path": "C:\\Users\\frank\\Documents\\Projekte\\pc bediener\\hardtekk\\beat_check.png",
            "max_width": 1920})
        return p["path"]

    # --- Vocal und Playlist -------------------------------------------------

    async def vocal_ins_playlist(self, track_id: str) -> None:
        """Zieht den Vocal aus dem Browser auf Playlist-Spur 1."""
        y = BROWSER_VOCALS_Y[track_id]
        await self.t.mouse_drag({
            "x1": 105, "y1": y,
            "x2": PLAYLIST_X_TAKT1, "y2": PLAYLIST_SPUR_Y["1"],
            "steps": 16, "duration": 1.6, "confirm": True})
        await self.t.sleep({"seconds": 4})

    async def beat_pattern_in_playlist(self, takte: int) -> None:
        """Legt das Beat-Pattern auf Spur 2 und streckt es auf volle Laenge."""
        await self.t.mouse_drag({
            "x1": 452, "y1": 163,
            "x2": PLAYLIST_X_TAKT1, "y2": PLAYLIST_SPUR_Y["2"],
            "steps": 16, "duration": 1.6, "confirm": True})
        await self.t.sleep({"seconds": 3})
        # Rand bis zum Ende des Vocals ziehen
        await self.t.mouse_drag({
            "x1": PLAYLIST_X_TAKT1 + 60, "y1": PLAYLIST_SPUR_Y["2"],
            "x2": PLAYLIST_X_TAKT1 + takte * 20, "y2": PLAYLIST_SPUR_Y["2"],
            "steps": 22, "duration": 2.0, "confirm": True})
        await self.t.sleep({"seconds": 2.5})

    # --- Speichern ----------------------------------------------------------

    async def speichern(self, name: str) -> None:
        await self.t.window_focus({"title": "FL Studio 2026"})
        await self.t.keyboard_hotkey({"keys": ["ctrl", "s"]})
        await self.t.sleep({"seconds": 4})
        w = await self.t.window_list({})
        dlg = next((x for x in w.get("windows", [])
                    if x["class_name"] == "TNewProjForm"), None)
        if dlg:
            await self.t.window_focus({"title": dlg["title"]})
            await self.t.sleep({"seconds": 0.8})
            await self.t.clipboard_set({"text": name})
            await self.t.keyboard_hotkey({"keys": ["ctrl", "v"]})
            await self.t.sleep({"seconds": 0.7})
            # "Create new project folder" abwaehlen -> landet direkt in Projects
            await self.t.mouse_click({"x": 758, "y": 517, "confirm": True,
                                      "hold_ms": 120})
            await self.t.sleep({"seconds": 1})
            await self.t.mouse_click({"x": 1053, "y": 687, "confirm": True,
                                      "hold_ms": 150})
            await self.t.sleep({"seconds": 5})