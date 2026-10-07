"""Gemeinsame Test-Fixtures.

Wichtig: Die Tests dürfen weder die echte Maus noch die echte Tastatur
beeinflussen. GUI- und Vision-Tests bekommen darum eine Attrappe statt
``pyautogui`` (siehe :class:`FakePyAutoGUI`).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from pcbediener import runtime
from pcbediener.config import Config


class FakePyAutoGUI:
    """Minimaler pyautogui-Ersatz, der nur protokolliert."""

    FAILSAFE = True
    PAUSE = 0

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.position_at = (100, 200)
        self.size_at = (1920, 1080)
        self.image = None  # wird von Bedarf gesetzt

    # -- Maus ------------------------------------------------------------
    def size(self) -> tuple[int, int]:
        return self.size_at

    def position(self) -> tuple[int, int]:
        return self.position_at

    def moveTo(self, x=None, y=None, duration=0.0, **_):  # noqa: N802
        self.calls.append(("moveTo", (x, y), {"duration": duration}))
        self.position_at = (int(x or 0), int(y or 0))

    def click(self, x=None, y=None, button="left", clicks=1, interval=0.0, duration=0.0, **_):  # noqa: N802
        self.calls.append(("click", (x, y), {"button": button, "clicks": clicks}))
        if x is not None and y is not None:
            self.position_at = (int(x), int(y))

    def mouseDown(self, button="left", **_):  # noqa: N802
        self.calls.append(("mouseDown", (), {"button": button}))

    def mouseUp(self, button="left", **_):  # noqa: N802
        self.calls.append(("mouseUp", (), {"button": button}))

    def scroll(self, clicks: int, **_):
        self.calls.append(("scroll", (clicks,), {}))

    def hscroll(self, clicks: int, **_):
        self.calls.append(("hscroll", (clicks,), {}))

    # -- Tastatur --------------------------------------------------------
    def write(self, text: str, interval=0.0, **_):
        self.calls.append(("write", (text,), {"interval": interval}))

    def press(self, key: str, presses=1, interval=0.0, **_):
        self.calls.append(("press", (key,), {"presses": presses}))

    def hotkey(self, *keys: str, interval=0.0, **_):
        self.calls.append(("hotkey", keys, {"interval": interval}))

    # -- Bild ------------------------------------------------------------
    def screenshot(self, region=None, **_):
        self.calls.append(("screenshot", (region,), {}))
        return self.image

    def locateCenterOnScreen(self, image, confidence=None, grayscale=False, **_):  # noqa: N802
        self.calls.append(("locate", (image,), {"confidence": confidence, "grayscale": grayscale}))
        return getattr(self, "locate_result", None)

    # -- Testhilfen ------------------------------------------------------
    def names(self) -> list[str]:
        return [call[0] for call in self.calls]


@pytest.fixture
def fake_gui(monkeypatch) -> FakePyAutoGUI:
    """Setzt die pyautogui-Attrappe für GUI- und Vision-Tests.

    ``gui`` bekommt die Attrappe direkt gesetzt; ``vision`` importiert
    ``pyautogui`` inline, weshalb der Eintrag in ``sys.modules`` genügt.

    Zusätzlich wird ``gui._hard_set_cursor`` auf ``moveTo`` umgeleitet.
    Ohne das ruft :func:`pcbediener.modules.gui.click` das echte
    ``win32api.SetCursorPos`` auf und schiebt beim Testlauf den **echten**
    Cursor des Users auf dem Desktop herum. Weil die Verifikation danach
    aus der Attrappe liest, stimmen die Koordinaten sonst nicht überein und
    die Tests schlagen mit einer irreführenden UIPI-Meldung fehl.
    """
    from pcbediener.modules import gui

    fake = FakePyAutoGUI()
    monkeypatch.setattr(gui, "_pyautogui", lambda: fake)
    monkeypatch.setitem(sys.modules, "pyautogui", fake)
    monkeypatch.setattr(
        gui, "_hard_set_cursor",
        lambda x, y, pg, cfg=None: pg.moveTo(x, y),
    )
    return fake


@pytest.fixture(autouse=True)
def _no_real_cursor_control():
    """Netz: kein Test darf je den echten Cursor/Tastatur-Desktop bewegen.

    ``fake_gui`` deckt den Normalfall ab. Dieser autouse-Wächter fängt die
    Restpfade ab, die direkt an Win32 vorbeizielen – z.B.
    ``ctypes.windll.user32.SetCursorPos`` in ``modules/background.py`` oder
    ein ``import win32api`` innerhalb einer Funktion. Ein Test, der den
    Desktop des Users anfasst, ist ein Test, der beim Ausführen flackert.
    """
    import win32api

    def _blocked(*_args, **_kwargs):
        raise AssertionError(
            "Test hat den echten Cursor bewegt. Nutze die fake_gui-Fixture "
            "und leite gui._hard_set_cursor darauf um."
        )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(win32api, "SetCursorPos", _blocked, raising=False)
    try:
        yield
    finally:
        monkeypatch.undo()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    return root


@pytest.fixture
def cfg(workspace: Path) -> Config:
    """Config im Sicherheitsmodus 'confirm', erlaubt ist nur tmp_path."""
    return Config(
        safety_mode="confirm",
        allowed_paths=[str(workspace)],
        exec_cwd=str(workspace),
        screenshot_dir=str(workspace / "shots"),
        exec_timeout=15,
    )


@pytest.fixture(autouse=True)
def _reset_runtime():
    """Setzt den globalen Runtime-Zustand nach jedem Test zurück."""
    original = runtime.get_config()
    yield
    runtime.set_config(original)