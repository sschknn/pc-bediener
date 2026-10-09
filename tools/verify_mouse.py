"""Lebend-Verifikation der Maussteuerung gegen ein echtes Fenster.

Hintergrund: Unit-Tests mit der pyautogui-Attrappe beweisen nur, dass die
Aufrufe *gemacht* werden. Sie beweisen nicht, dass Windows sie auch
*zustellt* – und genau daran scheitern GUI-Automationen: Der Code sendet
korrekt, das Zielprogramm sieht nichts.

Dieses Skript startet ein kleines Tk-Fenster, das jeden Maus-Input
protokolliert (Positionen, Tastendrücke, Modifier-Zustand, Mausrad), und
fährt es dann mit den echten Funktionen aus ``pcbediener.modules.gui`` an.
Ausgewertet wird die Logdatei, nicht der Bildschirm.

Start:  .venv\\Scripts\\python.exe tools\\verify_mouse.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Das Fenster steht bewusst auf dem *linken* Monitor (x < 0). Genau dort
# scheiterte die alte Implementierung: sie kannte nur den primären Monitor
# und lehnte negative Koordinaten ab.
WINDOW_X = -1500
WINDOW_Y = 200
WINDOW_W = 700
WINDOW_H = 500
LOG = Path(tempfile.gettempdir()) / "mousetarget_events.jsonl"


# --- Ziel-Anwendung -----------------------------------------------------------

def run_target() -> None:  # pragma: no cover - Kindprozess
    import tkinter as tk

    LOG.write_text("", encoding="utf-8")
    root = tk.Tk()
    root.title("MOUSETARGET")
    root.geometry(f"{WINDOW_W}x{WINDOW_H}+{WINDOW_X}+{WINDOW_Y}")
    root.attributes("-topmost", True)
    canvas = tk.Canvas(root, bg="#203040", highlightthickness=0)
    canvas.pack(fill="both", expand=True)

    def log(kind: str, **data: object) -> None:
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"kind": kind, "t": time.time(), **data}) + "\n")

    def mask(state: int) -> list[str]:
        # Tk-Modifier-Masken (nicht die Win32-Werte!):
        # Shift=0x0001, Lock=0x0002, Control=0x0004, Mod1/Alt=0x0008,
        # Mod2=0x0010, Button1=0x0100 ...
        return [n for b, n in ((0x0001, "shift"), (0x0004, "ctrl"),
                               (0x0008, "alt")) if state & b]

    def down(event) -> None:
        log("down", x=event.x_root, y=event.y_root, state=int(event.state),
            modifiers=mask(event.state))

    def motion(event) -> None:
        log("move", x=event.x_root, y=event.y_root, state=int(event.state),
            modifiers=mask(event.state))

    def up(event) -> None:
        log("up", x=event.x_root, y=event.y_root, state=int(event.state),
            modifiers=mask(event.state))

    def wheel(event) -> None:
        log("wheel", delta=int(event.delta), x=event.x_root, y=event.y_root,
            state=int(event.state), modifiers=mask(event.state))

    def key_down(event) -> None:
        log("key_down", key=event.keysym)

    def key_up(event) -> None:
        log("key_up", key=event.keysym)

    canvas.bind("<ButtonPress-1>", down)
    canvas.bind("<ButtonPress-2>", down)
    canvas.bind("<B1-Motion>", motion)
    canvas.bind("<B2-Motion>", motion)
    canvas.bind("<ButtonRelease-1>", up)
    canvas.bind("<ButtonRelease-2>", up)
    canvas.bind("<MouseWheel>", wheel)
    root.bind("<KeyPress>", key_down)
    root.bind("<KeyRelease>", key_up)

    def close_when_done() -> None:
        root.after(90_000, root.destroy)

    close_when_done()
    root.mainloop()


def read_events() -> list[dict]:
    if not LOG.is_file():
        return []
    out = []
    for line in LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def wait_for_target(timeout: float = 25.0) -> bool:
    from pcbediener.modules import gui

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if gui.find_window("MOUSETARGET"):
                return True
        except gui.WindowNotFound:
            pass
        time.sleep(0.4)
    return False


# --- Prüfungen ----------------------------------------------------------------

def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    return ok


def measure(action, settle: float = 0.5) -> list[dict]:
    """Führt eine Aktion aus und liefert **nur** ihre Ereignisse.

    Wichtig: das Log wird vorher geleert und danach gewartet. Ein blosses
    ``events[n:]``-Abschneiden ist unzuverlaessig - Tk stellt Events
    asynchron zu, Restereignisse des vorigen Schritts rutschen sonst in die
    Messung hinein (das hat in einer ersten Fassung vier Fehlschlaege
    erzeugt, die alle im Messskript lagen, nicht in der Maussteuerung).
    """
    time.sleep(0.25)
    LOG.write_text("", encoding="utf-8")
    time.sleep(0.25)
    action()
    time.sleep(settle)
    return read_events()


def main() -> int:
    print(f"Ziel-Fenster: {WINDOW_W}x{WINDOW_H}+{WINDOW_X}+{WINDOW_Y} "
          "(Monitor links vom Hauptmonitor)\n")

    env = dict(os.environ)
    proc = subprocess.Popen([sys.executable, __file__, "--target"], env=env)
    failures = 0
    try:
        if not wait_for_target():
            print("FEHLER: Zielfenster nicht erschienen.")
            return 1

        from pcbediener.modules import gui

        size = gui.screen_size()
        print("screen_info:", json.dumps(size))
        failures += not check(
            "Screen-Geometrie nutzt den virtuellen Desktop",
            size.get("multi_monitor") is True and size.get("x", 0) < 0,
            f"x={size.get('x')} breite={size.get('width')}",
        )

        cx, cy = WINDOW_X + WINDOW_W // 2, WINDOW_Y + WINDOW_H // 2

        # 1) Bewegen auf den *linken* Monitor (negative x).
        gui.sendinput_move(cx, cy)
        pos = gui.mouse_position()
        failures += not check(
            "sendinput_move auf negative x-Koordinate landet pixelgenau",
            pos["x"] == cx and pos["y"] == cy,
            f"erwartet ({cx},{cy}) war {pos}",
        )

        # 2) Linksklick.
        ev = measure(lambda: gui.sendinput_click(cx, cy, "left", clicks=1))
        downs = [e for e in ev if e["kind"] == "down"]
        ups = [e for e in ev if e["kind"] == "up"]
        failures += not check(
            "Linksklick wird zugestellt (1x runter, 1x los)",
            len(downs) == 1 and len(ups) == 1,
            f"{len(downs)} down / {len(ups)} up",
        )

        # 3) Drag mit 24 Einzelschritten.
        ev = measure(lambda: gui.sendinput_drag(cx, cy, cx, cy - 100,
                                                steps=24, duration_ms=240))
        moves = [e for e in ev if e["kind"] == "move"]
        ys = [m["y"] for m in moves]
        failures += not check(
            "Drag liefert viele Zwischenbewegungen (kein Sprung)",
            len(moves) >= 20, f"{len(moves)} move-Events fuer 24 Schritte")
        failures += not check(
            "Drag endet exakt am Ziel",
            bool(ys) and ys[-1] == cy - 100,
            f"Endpunkt y={ys[-1] if ys else None}, erwartet {cy - 100}")
        # Das erste geloggte move-Event steht bereits NACH dem ersten Schritt.
        # Der Gesamtweg ist deshalb: erster Schritt (Start -> erstes Event)
        # plus Weg zwischen den Events.
        if ys:
            first_step = cy - ys[0]
            between = ys[0] - ys[-1]
            travelled = first_step + between
        else:
            travelled = 0
        failures += not check(
            "Drag-Gesamtweg exakt (divmod, kein Rundungsfehler)",
            travelled == 100, f"zurueckgelegt {travelled} px statt 100")
        failures += not check(
            "Echter Cursor steht danach am Ziel",
            gui.cursor_position() == (cx, cy - 100),
            f"{gui.cursor_position()}")

        # 4) Drag mit Ctrl (FL-Studio-Feinabstimmung).
        ev = measure(lambda: gui.sendinput_drag(cx, cy, cx, cy - 30, steps=10,
                                                duration_ms=120, modifiers=["ctrl"]))
        ctrl_moves = [e for e in ev if e["kind"] == "move" and "ctrl" in e["modifiers"]]
        all_moves = [e for e in ev if e["kind"] == "move"]
        ups = [e for e in ev if e["kind"] == "up"]
        failures += not check(
            "Ctrl bleibt waehrend des gesamten Drags gedrueckt",
            len(all_moves) >= 8 and len(ctrl_moves) == len(all_moves),
            f"{len(ctrl_moves)}/{len(all_moves)} move-Events mit ctrl")
        after_up = ev[ev.index(ups[0]) + 1:] if ups else []
        failures += not check(
            "Ctrl wird nach dem Loslassen wieder frei",
            not any("ctrl" in e.get("modifiers", []) for e in after_up),
            f"{len(after_up)} Ereignisse nach dem Loslassen, ctrl="
            f"{sum('ctrl' in e.get('modifiers', []) for e in after_up)}")

        # 5) Mausrad.
        gui.sendinput_move(cx, cy)
        ev = measure(lambda: gui.sendinput_scroll(3))
        wheels = [e for e in ev if e["kind"] == "wheel"]
        failures += not check(
            "Mausrad-Rastungen werden zugestellt (positiv = aufwaerts)",
            [w["delta"] for w in wheels] == [120, 120, 120],
            f"delta={[w['delta'] for w in wheels]}",
        )
        ev = measure(lambda: gui.sendinput_scroll(-2))
        wheels = [e for e in ev if e["kind"] == "wheel"]
        failures += not check(
            "Negative Rastungen = abwaerts (Vorzeichen stimmt)",
            [w["delta"] for w in wheels] == [-120, -120],
            f"delta={[w['delta'] for w in wheels]}",
        )

        # 6) Alt-Klick = Reset eines FL-Reglers auf den Defaultwert.
        ev = measure(lambda: gui.sendinput_click(cx, cy, "left", modifiers=["alt"]))
        alt_downs = [e for e in ev if e["kind"] == "down" and "alt" in e["modifiers"]]
        failures += not check(
            "Alt+Linksklick erreicht die Anwendung als Alt-Klick",
            len(alt_downs) == 1, f"{len(alt_downs)} down-Events mit alt")

        # 7) Shift (FL: Rastpunkte aus) und Ctrl-Klick gemeinsam.
        ev = measure(lambda: gui.sendinput_drag(cx, cy, cx, cy - 20, steps=6,
                                                duration_ms=80,
                                                modifiers=["ctrl", "shift"]))
        both = [e for e in ev if e["kind"] == "move"
                and {"ctrl", "shift"} <= set(e.get("modifiers", []))]
        failures += not check(
            "Ctrl+Shift gleichzeitig waehrend des Drags",
            len(both) >= 5, f"{len(both)} move-Events mit ctrl+shift")

        # 8) Hold-Klick: Taste gedrueckt halten (Slider, Tempo-Anzeige).
        gui.sendinput_move(cx, cy)
        ev = measure(lambda: gui.sendinput_click(cx, cy, "left", hold_ms=250),
                     settle=0.8)
        gaps = []
        for kind in ("down", "up"):
            hits = [e for e in ev if e["kind"] == kind]
            if hits:
                gaps.append(hits[0]["t"])
        failures += not check(
            "hold_ms haelt die Taste wirklich gedrueckt",
            len(gaps) == 2 and (gaps[1] - gaps[0]) >= 0.2,
            f"Abstand down->up = {round(gaps[1] - gaps[0], 3) if len(gaps) == 2 else 'n/a'} s",
        )

        # 9) Zurueck auf die Ausgangsposition des Users.
        gui.sendinput_move(pos["x"], pos["y"])
        time.sleep(0.3)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    print(f"\n{'ALLE PRUEFUNGEN BESTANDEN' if not failures else f'{failures} PRUEFUNG(EN) FEHLGESCHLAGEN'}")
    return 0 if not failures else 1


if __name__ == "__main__":
    if "--target" in sys.argv:
        run_target()
    else:
        raise SystemExit(main())