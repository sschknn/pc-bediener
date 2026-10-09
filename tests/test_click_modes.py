"""Tests für die Klick-Modi (PyDirectInput-/AHK-Erkenntnisse)."""

from __future__ import annotations

import pytest

from pcbediener.modules import gui as mod_gui


class TestClickModes:
    def test_unbekannter_modus_abgelehnt(self, cfg, fake_gui):
        with pytest.raises(ValueError, match="Klick-Modus"):
            mod_gui.click(10, 10, cfg, confirm=True, mode="telepathie")

    def test_negativer_hold_abgelehnt(self, cfg, fake_gui):
        with pytest.raises(ValueError, match="hold_ms"):
            mod_gui.click(10, 10, cfg, confirm=True, hold_ms=-5)

    def test_sendinput_pfad(self, cfg, fake_gui, monkeypatch):
        """mode='sendinput' nutzt SendInput statt pyautogui – ohne echten Klick."""
        calls: list = []

        def _fake_sendinput_click(x, y, button, clicks, interval,
                                  hold_ms=0, modifiers=None):
            calls.append((x, y, button, clicks, hold_ms, modifiers))
            return {
                "method": "sendinput",
                "clicked": {"x": x, "y": y},
                "button": button, "clicks": clicks, "hold_ms": hold_ms,
                "modifiers": modifiers or [],
                "events": clicks * 2,
            }

        monkeypatch.setattr(mod_gui, "sendinput_click", _fake_sendinput_click)
        result = mod_gui.click(400, 300, cfg, button="right", clicks=2,
                               confirm=True, mode="sendinput", hold_ms=40,
                               modifiers="alt")
        # hold_ms und modifiers dürfen im SendInput-Modus nicht mehr
        # stillschweigend verloren gehen.
        assert calls == [(400, 300, "right", 2, 40, ["alt"])]
        assert result["method"] == "sendinput"
        assert result["hold_ms"] == 40
        assert "click" not in fake_gui.names()  # pyautogui blieb unbenutzt

    def test_hold_klick(self, cfg, fake_gui):
        """hold_ms>0: runter, halten, loslassen – für Slider/Regler."""
        result = mod_gui.click(400, 300, cfg, confirm=True, hold_ms=50)
        names = fake_gui.names()
        assert "mouseDown" in names and "mouseUp" in names
        assert "click" not in names
        assert result["hold_ms"] == 50
        assert result["clicked"] == {"x": 400, "y": 300}

    def test_koordinaten_normierung(self):
        # PyDirectInput-Formel: (x*65536)//breite + 1
        assert mod_gui._to_windows_coordinates(0, 0, 1920, 1080) == (1, 1)
        assert mod_gui._to_windows_coordinates(960, 540, 1920, 1080) == (32769, 32769)
        assert mod_gui._to_windows_coordinates(1919, 1079, 1920, 1080) == (65502, 65476)


class TestVirtualDesktopKoordinaten:
    """Absolute SendInput-Koordinaten auf dem *virtuellen* Desktop.

    Live gemessen (siehe ``tools/verify_mouse.py``): die reine PyDirectInput-
    Formel landet auf einem 2-Monitor-Setup bis zu 1 px daneben, weil Windows
    ``MOUSEEVENTF_ABSOLUTE`` pro Monitor rundet. Deshalb wird mittig im
    16-Bit-Fach adressiert.
    """

    @pytest.fixture(autouse=True)
    def _zwei_monitore(self, monkeypatch):
        # virtueller Desktop: Monitor links (x=-1920..0) + Hauptmonitor
        monkeypatch.setattr(
            mod_gui, "virtual_metrics", lambda: (-1920, 0, 3840, 1297))

    @staticmethod
    def _roundtrip(nx: int, ny: int, left=-1920, top=0, w=3840, h=1297):
        """Windows' Abbildung: floor(n * span / 65536) + Ursprung."""
        return (int(nx) * w) // 65536 + left, (int(ny) * h) // 65536 + top

    @pytest.mark.parametrize("px", [-1920, -1500, -1150, -1000, 0, 960, 1919, 1918])
    def test_x_landet_pixelgenau(self, px):
        nx, _ = mod_gui._to_virtual_coordinates(px, 540)
        assert self._roundtrip(nx, 0)[0] == px

    @pytest.mark.parametrize("py", [0, 1, 300, 540, 1080, 1296])
    def test_y_landet_pixelgenau(self, py):
        _, ny = mod_gui._to_virtual_coordinates(100, py)
        assert self._roundtrip(0, ny)[1] == py

    def test_ohne_virtuelle_metriken_fallback(self, monkeypatch):
        monkeypatch.setattr(mod_gui, "virtual_metrics", lambda: None)
        monkeypatch.setattr(mod_gui, "_primary_size", lambda: (1920, 1080))
        assert mod_gui._to_virtual_coordinates(0, 0) == (1, 1)


class TestModifier:
    def test_normalformen(self):
        assert mod_gui.normalise_modifiers(None) == []
        assert mod_gui.normalise_modifiers("ctrl") == ["ctrl"]
        assert mod_gui.normalise_modifiers("ctrl+shift") == ["ctrl", "shift"]
        assert mod_gui.normalise_modifiers(["Control", "alt"]) == ["ctrl", "alt"]
        assert mod_gui.normalise_modifiers("cmd") == ["win"]
        assert mod_gui.normalise_modifiers("ctrl, ctrl") == ["ctrl"]  # dedupliziert

    def test_unbekannt_ist_fehler(self):
        # Ein still ignorierter Modifier waere genau die Art Fehler, die man
        # am Bildschirm nicht sieht (Ctrl-Drag ohne Ctrl = wertloser Drag).
        with pytest.raises(ValueError, match="Modifier"):
            mod_gui.normalise_modifiers("super")


class TestSendinputDrag:
    def test_schritte_summieren_exakt(self, monkeypatch):
        """Auch bei negativer Strecke darf kein Pixel verloren gehen."""
        moves: list[tuple[int, int]] = []
        monkeypatch.setattr(mod_gui, "sendinput_move", lambda x, y: {})
        monkeypatch.setattr(
            mod_gui, "_send_mouse_flags",
            lambda flags, dx=0, dy=0, mouse_data=0: (
                moves.append((dx, dy)) if flags & 0x0001
                and not flags & 0x8000 else 1
            ) or 1,
        )
        monkeypatch.setattr(mod_gui.time, "sleep", lambda *_a, **_k: None)
        mod_gui.sendinput_drag(500, 500, 500, 400, steps=7)
        assert sum(dy for _dx, dy in moves) == -100
        assert len([m for m in moves if m != (0, 0)]) == 7

    def test_ungueltige_schritte(self):
        with pytest.raises(ValueError, match="steps"):
            mod_gui.sendinput_drag(0, 0, 10, 10, steps=0)


class TestKnob:
    """Drehregler: die drei Bedienarten, die FL Studio wirklich kennt."""

    def test_ohne_parameter_nutzenlos(self, cfg, fake_gui):
        with pytest.raises(ValueError, match="delta_px"):
            mod_gui.knob(100, 100, cfg, confirm=True)

    def test_ziehen_nach_oben_erhoeht(self, cfg, fake_gui, monkeypatch):
        calls: list = []
        monkeypatch.setattr(mod_gui, "drag",
                            lambda *a, **k: calls.append((a[:4], k)) or {})
        mod_gui.knob(100, 100, cfg, delta_px=40, confirm=True, settle_ms=0)
        coords, kwargs = calls[0]
        # FL: Wert steigt bei Zug nach OBEN -> y2 < y1
        assert coords == (100, 100, 100, 60)
        assert kwargs["modifiers"] == []

    def test_ziehen_nach_unten_senkt(self, cfg, fake_gui, monkeypatch):
        calls: list = []
        monkeypatch.setattr(mod_gui, "drag",
                            lambda *a, **k: calls.append((a[:4], k)) or {})
        mod_gui.knob(100, 100, cfg, delta_px=-25, confirm=True, settle_ms=0)
        assert calls[0][0] == (100, 100, 100, 125)

    def test_fine_ist_ctrl_und_no_snap_ist_shift(self, cfg, fake_gui, monkeypatch):
        calls: list = []
        monkeypatch.setattr(mod_gui, "drag",
                            lambda *a, **k: calls.append((a[:4], k)) or {})
        mod_gui.knob(100, 100, cfg, delta_px=10, fine=True, no_snap=True,
                     confirm=True, settle_ms=0)
        assert calls[0][1]["modifiers"] == ["ctrl", "shift"]

    def test_horizontaler_fader(self, cfg, fake_gui, monkeypatch):
        calls: list = []
        monkeypatch.setattr(mod_gui, "drag",
                            lambda *a, **k: calls.append((a[:4], k)) or {})
        mod_gui.knob(100, 100, cfg, delta_px=30, axis="horizontal",
                     confirm=True, settle_ms=0)
        assert calls[0][0] == (100, 100, 130, 100)

    def test_unbekannte_achse(self, cfg, fake_gui):
        with pytest.raises(ValueError, match="Achse"):
            mod_gui.knob(100, 100, cfg, delta_px=5, axis="diagonal",
                         confirm=True)

    def test_mausrad_ruft_scroll_mit_position(self, cfg, fake_gui):
        mod_gui.knob(100, 100, cfg, clicks=5, settle_ms=0)
        assert fake_gui.calls[-1] == ("scroll", (5,), {})

    def test_reset_ist_alt_klick(self, cfg, fake_gui):
        """FL-Reset: Alt + Linksklick setzt den Regler auf den Defaultwert."""
        mod_gui.knob(100, 100, cfg, reset=True, confirm=True, settle_ms=0)
        assert fake_gui.keys_down == []          # Alt wurde wieder losgelassen
        clicks = [c for c in fake_gui.calls if c[0] == "click"]
        assert clicks and clicks[0][2]["button"] == "left"
        keydowns = [c[1][0] for c in fake_gui.calls if c[0] == "keyDown"]
        assert keydowns == ["alt"]
        # Und der Modifier muss VOR dem Klick gedrueckt sein - FL wertet die
        # Tastenlage beim MouseDown aus, nicht beim MouseUp.
        names = fake_gui.names()
        assert names.index("keyDown") < names.index("click")

    def test_klick_fuer_modifier(self, cfg, fake_gui):
        mod_gui.click(10, 10, cfg, confirm=True, modifiers="alt")
        names = fake_gui.names()
        assert names.index("keyDown") < names.index("click")
        assert fake_gui.keys_down == []

    def test_modifier_bleibt_nicht_haengen(self, cfg, fake_gui, monkeypatch):
        """Auch bei einem Fehler muss die Taste los – sonst 'klebt' Ctrl."""
        monkeypatch.setattr(fake_gui, "click",
                            lambda **_k: (_ for _ in ()).throw(RuntimeError("boom")))
        with pytest.raises(RuntimeError):
            mod_gui.click(10, 10, cfg, confirm=True, modifiers="ctrl")
        assert fake_gui.keys_down == []


class TestSteppedDrag:
    def test_schritte_zaehlen(self, cfg, fake_gui):
        result = mod_gui.drag(0, 0, 100, 100, cfg, steps=4, confirm=True)
        names = fake_gui.names()
        assert names[0] == "moveTo" and names[-1] == "mouseUp"
        assert names.count("moveTo") == 5  # Start + 4 Zwischenpunkte
        assert result["steps"] == 4

    def test_ungueltige_schritte(self, cfg, fake_gui):
        with pytest.raises(ValueError, match="steps"):
            mod_gui.drag(0, 0, 10, 10, cfg, steps=0)

    def test_bestaetigung_erforderlich(self, cfg, fake_gui):
        """Ein Drag verändert Zustand und braucht im confirm-Modus confirm."""
        with pytest.raises(Exception, match="destruktive"):
            mod_gui.drag(0, 0, 10, 10, cfg, steps=2)

    def test_modifier_wird_vor_der_maustaste_gedrueckt(self, cfg, fake_gui):
        """FL Studio wertet die Tastenlage beim MouseDown aus, nicht beim MouseUp."""
        mod_gui.drag(0, 0, 0, -50, cfg, steps=2, confirm=True,
                     modifiers=["ctrl", "shift"])
        names = fake_gui.names()
        assert names.index("keyDown") < names.index("mouseDown")
        assert names[-1] == "keyUp"
        # Und nichts bleibt hängen: der Test endet mit keiner gedrückten Taste.
        assert fake_gui.keys_down == []

    def test_unbekannter_modifier(self, cfg, fake_gui):
        with pytest.raises(ValueError, match="Modifier"):
            mod_gui.drag(0, 0, 0, 10, cfg, steps=1, confirm=True,
                         modifiers="hyper")
