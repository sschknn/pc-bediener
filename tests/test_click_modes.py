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
        monkeypatch.setattr(
            mod_gui, "sendinput_click",
            lambda x, y, button, clicks, interval: calls.append(
                (x, y, button, clicks)) or {"method": "sendinput",
                                            "clicked": {"x": x, "y": y},
                                            "button": button, "clicks": clicks,
                                            "events": clicks * 2},
        )
        result = mod_gui.click(400, 300, cfg, button="right", clicks=2,
                               confirm=True, mode="sendinput")
        assert calls == [(400, 300, "right", 2)]
        assert result["method"] == "sendinput"
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


class TestSteppedDrag:
    def test_schritte_zaehlen(self, cfg, fake_gui):
        result = mod_gui.drag(0, 0, 100, 100, cfg, steps=4)
        names = fake_gui.names()
        assert names[0] == "moveTo" and names[-1] == "mouseUp"
        assert names.count("moveTo") == 5  # Start + 4 Zwischenpunkte
        assert result["steps"] == 4

    def test_ungültige_schritte(self, cfg, fake_gui):
        with pytest.raises(ValueError, match="steps"):
            mod_gui.drag(0, 0, 10, 10, cfg, steps=0)
