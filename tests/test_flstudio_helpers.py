"""Tests für die FL-Studio-Erkenntnisse: Clipboard-Fallback, Modal-Diagnose, Wissen."""

from __future__ import annotations

import sys

from pcbediener.modules import flstudio as mod_fl
from pcbediener.modules import gui as mod_gui


class TestFlstudioWissen:
    def test_wid_ids_match_image_line_doku(self):
        assert mod_fl.WID_MIXER == 0
        assert mod_fl.WID_CHANNEL_RACK == 1
        assert mod_fl.WID_PLAYLIST == 2
        assert mod_fl.WID_PIANO_ROLL == 3
        assert mod_fl.WID_BROWSER == 4

    def test_tempo_hint_kartiert(self):
        hints = {h: (x, y) for x, y, h in mod_fl.TOOLBAR_HINTS}
        assert hints["Tempo"] == (462, 26)

    def test_rezepte_vollstaendig(self):
        assert {"set_tempo", "import_audio", "screenshot_truth", "modal_dialog"} <= set(mod_fl.RECIPES)


class TestClipboardFallback:
    def test_type_ohne_pyperclip_nutzt_nativ(self, fake_gui, monkeypatch):
        """Regression: use_clipboard=True schlug ohne pyperclip fehl (kein Pflicht-Dep).

        Jetzt greift das native CF_UNICODETEXT.
        """
        monkeypatch.setitem(sys.modules, "pyperclip", None)
        seen: list[str] = []
        monkeypatch.setattr(mod_gui, "clipboard_set_native", lambda t: seen.append(t) or {"ok": True})
        result = mod_gui.type_text("C:\\temp\\tempo160.mid", use_clipboard=True)
        assert result["method"] == "clipboard"
        assert seen == ["C:\\temp\\tempo160.mid"]
        assert "hotkey" in fake_gui.names()

    def test_type_unicode_ohne_pyperclip(self, fake_gui, monkeypatch):
        monkeypatch.setitem(sys.modules, "pyperclip", None)
        monkeypatch.setattr(mod_gui, "clipboard_set_native", lambda t: {"ok": True})
        result = mod_gui.type_text("Grüße")
        assert result["method"] == "clipboard"


class TestModalState:
    def test_blockierter_dialog_wird_erkannt(self, monkeypatch):
        """Regression (FL Studio): TNameEditForm deaktivierte das Hauptfenster,
        kein Menü reagierte mehr – ohne Diagnose rät man ins Leere."""

        class FakeWin32Gui:
            @staticmethod
            def IsWindowVisible(h):
                return True

            @staticmethod
            def IsWindowEnabled(h):
                return h != 100  # Hauptfenster deaktiviert

            @staticmethod
            def GetWindowText(h):
                return {100: "FL Studio", 200: "Pattern 1 name"}.get(h, "")

            @staticmethod
            def GetClassName(h):
                return {100: "TFruityLoopsMainForm", 200: "TNameEditForm"}.get(h, "")

            @staticmethod
            def GetWindowRect(h):
                return (0, 0, 10, 10)

            @staticmethod
            def GetForegroundWindow():
                return 200

            @staticmethod
            def EnumWindows(cb, _):
                cb(100, None)
                cb(200, None)

        class FakeWin32Process:
            @staticmethod
            def GetWindowThreadProcessId(h):
                return (7, 9)

        monkeypatch.setattr(mod_gui, "_win32", lambda: FakeWin32Gui())
        monkeypatch.setattr(mod_gui, "_win32process", lambda: FakeWin32Process())
        monkeypatch.setattr(
            mod_gui, "_gui_thread_info",
            lambda tid: {"hwnd_active": 200, "hwnd_focus": 200,
                         "hwnd_capture": 0, "hwnd_menu_owner": 0},
        )
        state = mod_gui.modal_state("FL Studio")
        assert state["enabled"] is False
        assert state["blocked"] is True
        assert state["likely_modal_blocker"]["hwnd"] == 200
        assert state["gui_thread"]["hwnd_active"] == 200
