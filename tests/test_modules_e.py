"""Tests für Modul E – Hintergrund-Automation ohne Fokuswechsel.

Wichtig: Kein Test darf die echte UIA-Schnittstelle des Desktops
berühren. ``_desktop`` wird deshalb durchgehend ersetzt.
"""

from __future__ import annotations

import pytest

from pcbediener.modules import background as bg


class TestComInitialisierung:
    """Regression: CoInitialize() ist ein Zähler, kein Flag."""

    def test_hochzaehlt_nur_einmal_pro_thread(self, monkeypatch):
        """Der Server läuft stundenlang – der Zähler darf nicht wachsen."""
        import pythoncom
        import pywinauto
        import threading

        rufe = []
        monkeypatch.setattr(pythoncom, "CoInitialize", lambda: rufe.append(1))
        monkeypatch.setattr(bg, "_com_state", threading.local())
        # Desktop() stubben, damit kein echtes UIA entsteht.
        monkeypatch.setattr(pywinauto, "Desktop", lambda backend=None: object())

        bg._ensure_com_sta()
        bg._ensure_com_sta()
        bg._ensure_com_sta()

        assert len(rufe) == 1, f"CoInitialize {len(rufe)}-mal aufgerufen"

    def test_neuer_thread_initialisiert_erneut(self, monkeypatch):
        import pythoncom
        import threading

        rufe = []
        monkeypatch.setattr(pythoncom, "CoInitialize", lambda: rufe.append(1))
        monkeypatch.setattr(bg, "_com_state", threading.local())

        bg._ensure_com_sta()
        t = threading.Thread(target=bg._ensure_com_sta)
        t.start()
        t.join()

        assert len(rufe) == 2, "anderer Thread braucht eigenes COM"

    def test_ohne_pythoncom_weiter(self, monkeypatch):
        """Fehlendes pythoncom darf Modul E nicht komplett lahmlegen."""
        import builtins

        echter_import = builtins.__import__

        def kaputt(name, *args, **kwargs):
            if name == "pythoncom":
                raise ImportError("pythoncom fehlt")
            return echter_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", kaputt)
        monkeypatch.setattr(bg, "_com_state", __import__("threading").local())

        bg._ensure_com_sta()  # darf nicht werfen


class TestListenOhneDesktop:
    def test_fehlendes_pywinauto_wird_gelesbar(self, monkeypatch):
        import builtins

        echter_import = builtins.__import__

        def kaputt(name, *args, **kwargs):
            if name == "pywinauto" or name.startswith("pywinauto."):
                raise ImportError("weg")
            return echter_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", kaputt)
        with pytest.raises(RuntimeError, match="pywinauto"):
            bg._desktop()

    def test_fenster_nicht_gefunden_lesbar(self, monkeypatch):
        monkeypatch.setattr(bg, "_desktop_windows", lambda *a, **kw: [])
        monkeypatch.setattr(bg, "_hwnds_by_title", lambda *a, **kw: [])
        with pytest.raises(RuntimeError, match="Kein Fenster"):
            bg.find_window("GibtEsNicht")


@pytest.mark.skipif(True, reason="Platzhalter für echte Desktop-Tests")
class TestEchterDesktop:
    def test_placeholder(self):
        pass