"""Tests für Modul B (GUI/Prozesse) und Modul C (Vision).

Die Maus und Tastatur werden durch eine Attrappe ersetzt – diese Tests dürfen
den echten Desktop nicht beeinflussen.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from pcbediener.config import Config
from pcbediener.modules import gui as mod_gui
from pcbediener.modules import proc as mod_proc
from pcbediener.modules import vision as mod_vision
from pcbediener.safety import ConfirmationRequired


class TestMouse:
    def test_move(self, cfg: Config, fake_gui):
        result = mod_gui.move_mouse(500, 600, cfg)
        assert result["moved_to"] == {"x": 500, "y": 600}
        assert fake_gui.position_at == (500, 600)

    def test_move_outside_screen_rejected(self, cfg: Config, fake_gui):
        with pytest.raises(ValueError, match="außerhalb"):
            mod_gui.move_mouse(99999, 99999, cfg)

    def test_click_moves_first(self, cfg: Config, fake_gui):
        mod_gui.click(300, 400, cfg, button="right", clicks=2, confirm=True)
        move_call, click_call = fake_gui.calls
        assert move_call[0] == "moveTo" and move_call[1] == (300, 400)
        assert click_call[2]["button"] == "right"
        assert click_call[2]["clicks"] == 2

    def test_click_without_position(self, cfg: Config, fake_gui):
        mod_gui.click(cfg=cfg, confirm=True)
        assert "moveTo" not in fake_gui.names()

    def test_click_needs_confirmation(self, cfg: Config, fake_gui):
        with pytest.raises(ConfirmationRequired):
            mod_gui.click(10, 10, cfg, confirm=False)
        assert "click" not in fake_gui.names()

    def test_invalid_button(self, cfg: Config, fake_gui):
        with pytest.raises(ValueError, match="Maustaste"):
            mod_gui.click(1, 1, cfg, button="seitlich", confirm=True)

    def test_invalid_click_count(self, cfg: Config, fake_gui):
        with pytest.raises(ValueError, match="clicks"):
            mod_gui.click(1, 1, cfg, clicks=99, confirm=True)

    def test_drag(self, cfg: Config, fake_gui):
        result = mod_gui.drag(10, 20, 300, 400, cfg)
        assert result["from"] == {"x": 10, "y": 20}
        assert result["to"] == {"x": 300, "y": 400}
        names = fake_gui.names()
        assert names[0] == "moveTo" and names[-1] == "mouseUp"

    def test_scroll(self, cfg: Config, fake_gui):
        mod_gui.scroll(-5)
        assert fake_gui.calls[-1] == ("scroll", (-5,), {})
        mod_gui.scroll(3, horizontal=True)
        assert fake_gui.calls[-1] == ("hscroll", (3,), {})

    def test_screen_size_and_position(self, fake_gui):
        assert mod_gui.screen_size() == {"width": 1920, "height": 1080}
        assert mod_gui.mouse_position() == {"x": 100, "y": 200}


class TestKeyboard:
    def test_type_ascii(self, fake_gui):
        result = mod_gui.type_text("hallo")
        assert result["method"] == "keyboard"
        assert fake_gui.calls[-1][1] == ("hallo",)

    def test_type_unicode_uses_clipboard(self, fake_gui, monkeypatch):
        import pyperclip

        monkeypatch.setattr(pyperclip, "copy", lambda text: None)
        result = mod_gui.type_text("Grüße 😀")
        assert result["method"] == "clipboard"
        assert "hotkey" in fake_gui.names()

    def test_press_multiple(self, fake_gui):
        mod_gui.press_key("enter", presses=3)
        assert fake_gui.calls[-1][2]["presses"] == 3

    def test_hotkey(self, cfg: Config, fake_gui):
        result = mod_gui.hotkey("ctrl", "shift", "s", cfg=cfg)
        assert result["hotkey"] == ["ctrl", "shift", "s"]
        assert fake_gui.calls[-1][1] == ("ctrl", "shift", "s")

    def test_hotkey_needs_two_keys(self, fake_gui):
        with pytest.raises(ValueError, match="mindestens 2"):
            mod_gui.hotkey("ctrl")

    def test_type_rejects_non_string(self, fake_gui):
        with pytest.raises(TypeError):
            mod_gui.type_text(123)  # type: ignore[arg-type]


@pytest.mark.skipif(sys.platform != "win32", reason="Fensterzugriff nur unter Windows")
class TestWindows:
    def test_all_pywin32_attributes_exist(self):
        """Regression: pywin32 verteilt seine Funktionen auf mehrere Module.

        ``win32gui`` hat weder ``GetWindowThreadProcessId`` noch ``IsZoomed``,
        und ``GetCurrentThreadId`` liegt in ``win32api``. Solche Attribute
        scheitern erst zur *Laufzeit* – und wurden von einem ``except: pass``
        noch verschluckt. Dieser Test prüft alle verwendeten Namen statisch.
        """
        import importlib
        import pathlib
        import re

        source = pathlib.Path(mod_gui.__file__).read_text(encoding="utf-8")
        used = set(re.findall(r"\b(win32\w+)\.(\w+)", source))

        assert used, "keine pywin32-Aufrufe gefunden – Regex anpassen"
        missing = [
            f"{mod}.{attr}"
            for mod, attr in sorted(used)
            if not hasattr(importlib.import_module(mod), attr)
        ]
        assert not missing, f"Diese pywin32-Attribute existieren nicht: {missing}"

    def test_list_windows_returns_dicts(self):
        result = mod_gui.list_windows()
        assert set(result) >= {"count", "windows"}
        assert result["count"] == len(result["windows"])
        for win in result["windows"]:
            assert {"hwnd", "title", "pid", "x", "y", "width", "height"} <= set(win)

    def test_list_windows_finds_what_win32_sees(self):
        """Regression: ein Fehler in ``_window_info`` wurde früher verschluckt.

        Damals lieferte ``list_windows()`` eine leere Liste, während Windows
        dutzende Fenster hatte. Der Test vergleicht deshalb direkt mit der
        rohen ``EnumWindows``-Zählung.
        """
        import win32gui

        raw: list[str] = []

        def collect(hwnd, _):
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
                raw.append(win32gui.GetWindowText(hwnd))
            return True

        win32gui.EnumWindows(collect, None)
        if not raw:
            pytest.skip("keine sichtbaren Fenster in dieser Sitzung (Headless)")

        found = mod_gui.list_windows()["count"]
        assert found == len(raw), (
            f"list_windows() fand {found}, EnumWindows sieht {len(raw)} – "
            "ein Fehler wird vermutlich still geschluckt"
        )

    def test_window_info_has_usable_pid(self):
        """Regression: ``win32gui.GetWindowThreadProcessId`` existiert nicht."""
        windows = mod_gui.list_windows()["windows"]
        if not windows:
            pytest.skip("keine sichtbaren Fenster in dieser Sitzung (Headless)")
        for win in windows:
            assert win["pid"] > 0, f"Fenster {win['title']!r} hat keine PID"
            assert win["class_name"], f"Fenster {win['title']!r} hat keine Klasse"

    def test_find_window_exact_match(self):
        """Regression: ``EnumWindows`` wurde nach dem ersten Fenster beendet.

        ``return not exact`` stoppt bei jedem Fenster, nicht erst nach dem
        Treffer – ein exakter Titel war dadurch nie auffindbar.
        """
        windows = mod_gui.list_windows()["windows"]
        if not windows:
            pytest.skip("keine sichtbaren Fenster in dieser Sitzung (Headless)")

        target = windows[-1]  # nicht das erste Fenster im Z-Stapel
        hwnd = mod_gui.find_window(target["title"], exact=True)
        assert hwnd == target["hwnd"]

    def test_find_window_substring_and_filter_agree(self):
        windows = mod_gui.list_windows()["windows"]
        if len(windows) < 2:
            pytest.skip("nicht genug sichtbare Fenster")
        title = windows[0]["title"]
        needle = title[: max(1, len(title) // 2)].strip()
        if not needle:
            pytest.skip("Titel zu kurz zum Testen")
        filtered = mod_gui.list_windows(needle)["windows"]
        assert filtered, f"Filter {needle!r} findet nichts, obwohl es passt"
        assert all(needle.lower() in w["title"].lower() for w in filtered)

    def test_focus_unknown_window_raises(self):
        with pytest.raises(mod_gui.WindowNotFound, match="Kein Fenster"):
            mod_gui.focus_window("Fenster-das-es-nicht-gibt-12345xyz")

    def test_find_unknown_window_raises(self):
        with pytest.raises(mod_gui.WindowNotFound, match="Kein Fenster"):
            mod_gui.find_window("Fenster-das-es-nicht-gibt-12345xyz")

    def test_invalid_window_action(self):
        with pytest.raises(Exception):
            mod_gui.window_action("egal", "unbekannte-aktion")


class TestProcesses:
    def test_list_processes(self, cfg: Config):
        result = mod_proc.list_processes(cfg, limit=5)
        procs = result["processes"]
        assert len(procs) <= 5
        assert result["count"] == len(procs)
        assert all({"pid", "name"} <= set(p) for p in procs)

    def test_filter_by_name(self, cfg: Config):
        procs = mod_proc.list_processes(cfg, filter_text="python", limit=5)["processes"]
        assert procs, "mindestens ein Python-Prozess erwartet"
        assert all("python" in p["name"].lower() for p in procs)

    def test_sort_by_memory(self, cfg: Config):
        procs = mod_proc.list_processes(cfg, limit=10, sort_by="memory")["processes"]
        values = [p["memory_mb"] for p in procs]
        assert values == sorted(values, reverse=True)

    def test_invalid_sort_key(self, cfg: Config):
        with pytest.raises(ValueError, match="sort_by"):
            mod_proc.list_processes(cfg, sort_by="nonsense")

    def test_process_info_unknown_pid(self):
        with pytest.raises(ValueError, match="Kein Prozess"):
            mod_proc.process_info(999_999)

    def test_cannot_kill_own_process(self, cfg: Config):
        with pytest.raises(ValueError, match="eigene Prozess"):
            mod_proc.kill_process(os.getpid(), cfg, confirm=True)

    def test_protected_process_refused(self, cfg: Config):
        import psutil

        for proc in psutil.process_iter(["name"]):
            if (proc.info["name"] or "").lower() == "explorer.exe":
                with pytest.raises(ValueError, match="geschützt"):
                    mod_proc.kill_process(proc.pid, cfg, confirm=True)
                return
        pytest.skip("kein geschützter Prozess zum Testen gefunden")

    def test_kill_unknown_pid(self, cfg: Config):
        with pytest.raises(ValueError, match="Kein Prozess"):
            mod_proc.kill_process(999_999, cfg, confirm=True)

    def test_start_unknown_program(self, cfg: Config):
        with pytest.raises(FileNotFoundError, match="nicht im PATH"):
            mod_proc.start_process("programm-das-es-nicht-gibt-xyz", cfg, confirm=True)

    def test_start_and_kill_foreground(self, cfg: Config):
        """Hintergrund-Prozess starten, kurz warten, wieder beenden."""
        result = mod_proc.start_process(
            sys.executable, cfg, background=True, arguments=["-c", "import time; time.sleep(5)"], confirm=True
        )
        assert result["running"] is True
        try:
            killed = mod_proc.kill_process(result["pid"], cfg, confirm=True)
            assert killed["terminated"] is True
        finally:
            import psutil

            if psutil.pid_exists(result["pid"]):
                psutil.Process(result["pid"]).kill()

    def test_kill_needs_confirmation(self, cfg: Config):
        result = mod_proc.start_process(
            sys.executable, cfg, background=True, arguments=["-c", "import time; time.sleep(5)"], confirm=True
        )
        try:
            with pytest.raises(ConfirmationRequired):
                mod_proc.kill_process(result["pid"], cfg, confirm=False)
            assert mod_proc.process_info(result["pid"])["pid"] == result["pid"]
        finally:
            mod_proc.kill_process(result["pid"], cfg, force=True, confirm=True)


class TestVision:
    def test_screenshot_saves_png(self, cfg: Config, fake_gui, monkeypatch):
        from PIL import Image as PILImage

        fake_gui.image = PILImage.new("RGB", (1920, 1080), "red")
        result = mod_vision.screenshot(cfg)
        path = Path(result["path"])
        assert path.is_file()
        assert path.suffix == ".png"
        assert result["width"] == 1920 and result["height"] == 1080

    def test_screenshot_max_width_scales(self, cfg: Config, fake_gui):
        from PIL import Image as PILImage

        fake_gui.image = PILImage.new("RGB", (1920, 1080), "blue")
        result = mod_vision.screenshot(cfg, max_width=480)
        assert result["width"] == 480
        assert result["height"] == 270  # Seitenverhältnis bleibt erhalten

    def test_screenshot_region_passed_through(self, cfg: Config, fake_gui):
        from PIL import Image as PILImage

        fake_gui.image = PILImage.new("RGB", (100, 100), "green")
        mod_vision.screenshot(cfg, region=(0, 0, 100, 100))
        assert fake_gui.calls[-1][0] == "screenshot"
        assert fake_gui.calls[-1][1] == ((0, 0, 100, 100),)

    def test_screenshot_without_save(self, cfg: Config, fake_gui):
        from PIL import Image as PILImage

        fake_gui.image = PILImage.new("RGB", (50, 50), "white")
        result = mod_vision.screenshot(cfg, save=False)
        assert "path" not in result
        assert result["screen"] == {"width": 50, "height": 50}

    def test_find_image_found(self, cfg: Config, fake_gui, workspace: Path):
        needle = workspace / "knopf.png"
        needle.write_bytes(b"\x89PNG\r\n")
        fake_gui.locate_result = (640, 480)
        result = mod_vision.find_on_screen(cfg, needle)
        assert result["found"] is True
        assert result["x"] == 640 and result["y"] == 480

    def test_find_image_missing_file(self, cfg: Config, fake_gui, workspace: Path):
        with pytest.raises(FileNotFoundError):
            mod_vision.find_on_screen(cfg, workspace / "gibtsnicht.png")

    def test_find_image_not_found(self, cfg: Config, fake_gui, workspace: Path):
        needle = workspace / "knopf.png"
        needle.write_bytes(b"\x89PNG\r\n")
        fake_gui.locate_result = None
        assert mod_vision.find_on_screen(cfg, needle)["found"] is False

    def test_wait_for_image_times_out(self, cfg: Config, fake_gui, workspace: Path):
        needle = workspace / "knopf.png"
        needle.write_bytes(b"\x89PNG\r\n")
        fake_gui.locate_result = None
        result = mod_vision.wait_for_image(cfg, needle, timeout_s=0.3, poll_interval=0.1)
        assert result["found"] is False
        assert result["attempts"] >= 2

    def test_wait_for_image_succeeds(self, cfg: Config, fake_gui, workspace: Path):
        needle = workspace / "knopf.png"
        needle.write_bytes(b"\x89PNG\r\n")
        fake_gui.locate_result = (10, 20)
        result = mod_vision.wait_for_image(cfg, needle, timeout_s=1.0, poll_interval=0.1)
        assert result["found"] is True

    def test_system_status_shape(self, cfg: Config):
        status = mod_vision.system_status(cfg)
        assert status["memory"]["total_gb"] > 0
        assert status["cpu"]["logical_cores"] >= 1
        assert status["disk"]["total_gb"] > 0
        assert status["safety_mode"] == "confirm"
        assert "uptime_hours" in status

    def test_system_status_disk_error_handled(self, cfg: Config):
        status = mod_vision.system_status(cfg, disk_path="Z:\\gibt-es-nicht")
        assert "error" in status["disk"] or "total_gb" in status["disk"]