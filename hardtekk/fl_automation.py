"""Baut einen Hardtekk-Track in FL Studio: Beat aus Soundpacks + echter Vocal.

Der Ablauf ist in allen 5 Tracks gleich, deshalb als Skript, damit die
Klick-Koordinaten nur an einer Stelle gepflegt werden muessen.

Reihenfolge ist wichtig und aus der Praxis erarbeitet:
  1. Neues Projekt            - sonst Patterns vom letzten Track
  2. Tempo per MIDI-Import    - legt ein leeres Pattern an; deshalb ZUERST,
                                bevor der Beat kommt
  3. 808-Kanaele sind schon da (FL-Standardprojekt)
  4. Step-Sequencer einschalten (Filter "All" + Grid-Umschalter)
  5. Steps klicken            - Geometrie per Pixelanalyse vermessen
  6. Beat-Pattern ins Playlist ziehen und auf Taktzahl strecken
  7. Vocal aus dem Browser danebenlegen
  8. Speichern

Bekannte Stolpersteine (siehe AGENTS.md / App-Gedaechtnis):
  * "Unsorted"-Filter blendet die Step-Schnitflaechen aus
  * Grid-Umschalter oben rechts im Rack muss AN sein, sonst kein Step-Sequencer
  * Das Tempo-Panel nimmt keine Eingaben -> Tempo nur per MIDI-Import
  * Der MIDI-Import ersetzt den Clip an der Wiedergabeposition -> Playhead
    ans Projektende stellen, bevor ein Clip existiert
  * Clip-Laenge per Rand ziehen ist zuverlaessiger als "Chop > Repeating"
"""
import sys
import time

sys.path.insert(0, r"C:\Users\frank\Documents\Projekte\pc bediener\.venv\Lib\site-packages")

# --- Geometrie (1:1-Screenshot, per Pixelanalyse vermessen) -------------------
# Step n bei x = 606 + (n-1)*16, Kanaele 30 px Abstand ab y = 144
STEP_X0 = 606
STEP_PITCH = 16
KANAL_Y = {
    "808 Kick": 144,
    "808 Clap": 174,
    "808 HiHat": 204,
    "808 Snare": 234,
    "808 Astronomic": 264,
}

BEAT = {
    "808 Kick": [1, 5, 9, 13],
    "808 Clap": [5, 13],
    "808 HiHat": [2, 4, 6, 8, 10, 12, 14, 16],
    "808 Snare": [15],
    "808 Astronomic": [7, 15],
}


class Steuerung:
    """Kapselt die MCP-Tools, damit der Ablauf lesbar bleibt."""

    def __init__(self, tools):
        self.t = tools

    async def klick(self, x, y, hold=0, doppelt=False):
        klicks = 2 if doppelt else 1
        await self.t.mouse_click({"x": x, "y": y, "hold_ms": hold,
                                  "clicks": klicks, "confirm": True})
        await self.t.warte(0.4 if hold else 0.22)

    async def warte(self, s):
        await self.t.sleep({"seconds": s})

    async def taste(self, key, pausen=0.4):
        await self.t.keyboard_press({"key": key})
        await self.warte(pausen)

    async def hotkey(self, tasten, pausen=0.6):
        await self.t.keyboard_hotkey({"keys": tasten})
        await self.warte(pausen)

    async def pfad_eintragen(self, pfad):
        await self.t.clipboard_set({"text": pfad})
        await self.warte(0.3)
        await self.hotkey(["ctrl", "v"], 0.5)
        await self.taste("enter", 3.5)

    async def step_klicken(self, kanal, steps):
        y = KANAL_Y[kanal]
        for s in steps:
            await self.t.mouse_click({
                "x": STEP_X0 + (s - 1) * STEP_PITCH, "y": y, "confirm": True})
            await self.warte(0.2)

    async def fenster_titel(self):
        w = await self.t.window_list({"filter_text": "FL"})
        return w["windows"][0]["title"] if w.get("windows") else None

    async def tempo_setzen(self, bpm):
        """MIDI-Import bei leerem Projekt - setzt das Tempo zuverlaessig."""
        await self.pfad_eintragen(
            rf"C:\Users\frank\Documents\Projekte\pc bediener\hardtekk\tempo{bpm}.mid")

    async def rack_vorbereiten(self):
        """Filter auf 'All' und Step-Sequencer einschalten."""
        await self.taste("f6", 2.0)                    # Channel Rack
        await self.klick(529, 97, hold=120)             # Filter-Dropdown
        await self.warte(1.5)
        await self.klick(500, 118, hold=120)            # "All"
        await self.warte(1.5)
        await self.klick(1718, 97, hold=180)            # Grid-Umschalter
        await self.warte(2.0)

    async def beat_programmieren(self):
        for kanal, steps in BEAT.items():
            await self.step_klicken(kanal, steps)

    async def beat_ins_playlist(self, takte, spur_y=435, start_x=660):
        """Pattern auf die Spur ziehen und auf die volle Laenge strecken."""
        await self.t.mouse_drag({
            "x1": 450, "y1": 163, "x2": start_x, "y2": spur_y,
            "steps": 16, "duration": 1.6, "confirm": True})
        await self.warte(2.5)
        # Rand bis zum Ende des Vocals ziehen
        ziel_x = start_x + takte * 20
        await self.t.mouse_drag({
            "x1": start_x + 20, "y1": spur_y, "x2": ziel_x, "y2": spur_y,
            "steps": 20, "duration": 1.8, "confirm": True})
        await self.warte(2.0)