"""Tests für die MCP-Schnittstelle.

Hier wird geprüft, was die KI tatsächlich sieht: Tool-Namen, JSON-Schemas,
Fehlermeldungen und die Sicherheitslogik über den Server-Pfad.

Hinweis: In ``mcp`` 2.x heißt das Schema-Feld ``input_schema``
(JSON-Alias ``inputSchema``) und erwartete Fehler kommen als ``ToolError``
zurück, nicht als ``isError=True``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from pcbediener import runtime
from pcbediener.config import Config
from pcbediener.mcp_server import _expected_errors, server


class TestGuardSichtbarkeit:
    """Modul-E-Fehler müssen lesbar sein, nicht 'Error executing tool X'."""

    def test_automationsfehler_werden_erfasst(self):
        """pywinauto-Fehler erben oft direkt von Exception."""
        pytest.importorskip("pywinauto")
        erfasst = {e.__name__ for e in _expected_errors()}
        for name in ("ElementNotFoundError", "WindowNotFoundError"):
            assert name in erfasst, (
                f"{name} fehlt in _expected_errors() – der Fehler würde "
                f"undurchsichtbar als 'Error executing tool ...' landen."
            )

    def test_com_error_erfasst(self):
        pytest.importorskip("comtypes")
        from comtypes import COMError

        assert COMError in _expected_errors()

    def test_basisfehler_weiterhin_erfasst(self):
        erfasst = _expected_errors()
        for basis in (OSError, ValueError, RuntimeError):
            assert basis in erfasst

    def test_guard_macht_uia_fehler_lesbar(self):
        """Regression: guard muss einen echten pywinauto-Fehler umsetzen."""
        pytest.importorskip("pywinauto")
        from pywinauto import ElementNotFoundError

        from pcbediener.mcp_server import guard

        @guard
        def _tool() -> None:
            raise ElementNotFoundError("kein Element mit diesem Namen")

        with pytest.raises(ToolError) as excinfo:
            _tool()

        text = str(excinfo.value)
        assert "ElementNotFoundError" in text
        assert "kein Element mit diesem Namen" in text


def call(name: str, **arguments) -> tuple[bool, str]:
    """Ruft ein Tool auf und liefert ``(ist_fehler, text)``."""
    try:
        result = asyncio.run(server.call_tool(name, arguments))
    except ToolError as exc:
        return True, str(exc)
    text = "\n".join(
        block.text for block in result.content if getattr(block, "type", "") == "text"
    )
    return bool(getattr(result, "is_error", False)), text


def call_ok(name: str, **arguments) -> str:
    """Wie :func:`call`, bricht aber bei einem Fehler ab."""
    failed, text = call(name, **arguments)
    assert not failed, f"{name} meldete einen Fehler: {text}"
    return text


def call_fail(name: str, **arguments) -> str:
    """Wie :func:`call`, bricht aber ab, wenn *kein* Fehler auftritt."""
    failed, text = call(name, **arguments)
    assert failed, f"{name} hätte fehlschlagen müssen, war aber erfolgreich: {text}"
    return text


def all_tools():
    return asyncio.run(server.list_tools())


# --- Schemas ----------------------------------------------------------------


class TestToolSchemas:
    def test_all_tools_have_valid_json_schemas(self):
        tools = all_tools()
        assert len(tools) >= 30
        for tool in tools:
            assert tool.name, "Tool ohne Namen"
            assert tool.description, f"{tool.name} hat keine Beschreibung"
            schema = tool.input_schema
            assert isinstance(schema, dict), f"{tool.name} hat kein input_schema"
            assert schema.get("type") == "object", f"{tool.name}: unerwartetes Schema"

    def test_all_four_modules_are_covered(self):
        names = {t.name for t in all_tools()}
        module_a = {"exec_python", "exec_powershell", "exec_command"}
        module_b = {
            "mouse_move", "mouse_click", "keyboard_type", "keyboard_press",
            "keyboard_hotkey", "window_list", "window_focus", "process_list",
            "process_start", "process_kill",
        }
        module_c = {"screenshot", "system_status", "screen_find_image"}
        module_d = {"file_read", "file_write", "file_list", "file_search", "file_delete"}
        for group in (module_a, module_b, module_c, module_d):
            assert group <= names, f"fehlend: {group - names}"

    def test_destructive_tools_are_marked(self):
        tools = {t.name: t.annotations for t in all_tools()}
        for name in ("file_delete", "process_kill", "exec_python", "window_action"):
            assert tools[name] is not None, f"{name} hat keine Annotations"
            assert tools[name].destructive_hint is True, f"{name} ist nicht als destruktiv markiert"

    def test_read_only_tools_are_marked(self):
        tools = {t.name: t.annotations for t in all_tools()}
        for name in ("file_read", "system_status", "window_list", "safety_status"):
            assert tools[name].read_only_hint is True, f"{name} ist nicht als nur-lesend markiert"

    def test_confirm_parameter_exists_on_destructive_tools(self):
        for tool in all_tools():
            props = tool.input_schema.get("properties", {})
            if tool.annotations and tool.annotations.destructive_hint:
                assert "confirm" in props, f"{tool.name} hat keinen confirm-Parameter"

    def test_confirm_parameter_is_optional(self):
        for tool in all_tools():
            props = tool.input_schema.get("properties", {})
            if "confirm" in props:
                assert "confirm" not in tool.input_schema.get("required", [])

    def test_every_tool_has_a_description_for_the_ai(self):
        for tool in all_tools():
            assert len(tool.description or "") > 20, f"{tool.name}: Beschreibung zu knapp"


# --- Sicherheit über den Server --------------------------------------------


class TestSafetyOverServer:
    def test_status_and_mode_switching(self, cfg: Config):
        runtime.set_config(cfg)
        assert "confirm" in call_ok("safety_status")
        call_ok("safety_mode", mode="auto")
        assert runtime.get_config().safety_mode == "auto"
        call_ok("safety_mode", mode="confirm")
        assert runtime.get_config().safety_mode == "confirm"

    def test_invalid_mode_is_reported(self, cfg: Config):
        runtime.set_config(cfg)
        assert "confirm" in call_fail("safety_mode", mode="gibtsnicht")

    def test_delete_requires_confirm(self, cfg: Config, workspace: Path):
        runtime.set_config(cfg)
        target = workspace / "opfer.txt"
        target.write_text("wichtig", encoding="utf-8")

        assert "ConfirmationRequired" in call_fail("file_delete", path=str(target))
        assert target.exists(), "Datei wurde trotz Sperre gelöscht!"

        call_ok("file_delete", path=str(target), confirm=True)
        assert not target.exists()

    def test_exec_requires_confirm(self, cfg: Config):
        runtime.set_config(cfg)
        assert "ConfirmationRequired" in call_fail("exec_python", code="print(1)")

    def test_auto_mode_executes_without_confirm(self, workspace: Path):
        cfg = Config(
            safety_mode="auto",
            allowed_paths=[str(workspace)],
            exec_cwd=str(workspace),
            screenshot_dir=str(workspace / "shots"),
        )
        runtime.set_config(cfg)
        assert "lief" in call_ok("exec_python", code="print('lief')")

    def test_forbidden_command_is_blocked_over_server(self, cfg: Config):
        runtime.set_config(cfg)
        blocked = call_fail(
            "exec_python", code="import shutil; shutil.rmtree('C:/')", confirm=True
        )
        assert "ForbiddenCommand" in blocked

    def test_path_outside_allowed_paths_is_blocked(self, cfg: Config, tmp_path: Path):
        runtime.set_config(cfg)
        fremd = tmp_path / "fremd.txt"
        fremd.write_text("x", encoding="utf-8")
        assert "PathNotAllowed" in call_fail("file_read", path=str(fremd))


# --- Verhalten --------------------------------------------------------------


class TestToolBehaviour:
    def test_exec_returns_output(self, cfg: Config):
        runtime.set_config(cfg)
        assert "hallo" in call_ok("exec_python", code="print('hallo')", confirm=True)

    def test_exec_error_is_reported_in_result_not_as_tool_error(self, cfg: Config):
        """Der Tool-Aufruf war erfolgreich – der *Code darin* ist gescheitert.

        Genau so braucht es die KI: stderr im Ergebnis, damit sie den Fehler
        selbst korrigieren kann.
        """
        runtime.set_config(cfg)
        result = call_ok("exec_python", code="raise SystemError('kaputt')", confirm=True)
        assert "SystemError" in result
        assert '"ok": false' in result

    def test_exec_reports_exit_code(self, cfg: Config):
        runtime.set_config(cfg)
        assert '"returncode": 0' in call_ok("exec_python", code="print(1)", confirm=True)

    def test_file_write_and_read(self, cfg: Config, workspace: Path):
        runtime.set_config(cfg)
        call_ok("file_write", path=str(workspace / "a.txt"), content="inhalt", confirm=True)
        assert "inhalt" in call_ok("file_read", path=str(workspace / "a.txt"))

    def test_file_tree_lists(self, cfg: Config, workspace: Path):
        runtime.set_config(cfg)
        (workspace / "unter").mkdir()
        call_ok("file_write", path=str(workspace / "unter" / "x.txt"), content="y", confirm=True)
        assert "x.txt" in call_ok("file_tree", path=str(workspace))

    def test_sleep_validates_range(self, cfg: Config):
        runtime.set_config(cfg)
        assert "seconds" in call_fail("sleep", seconds=999)

    def test_system_status_over_server(self, cfg: Config):
        runtime.set_config(cfg)
        assert "logical_cores" in call_ok("system_status")

    def test_unknown_tool_is_error(self):
        assert "unknown tool" in call_fail("tool_das_es_nicht_gibt").lower()

    def test_bad_argument_is_error(self, cfg: Config):
        runtime.set_config(cfg)
        call_fail("file_read")  # Pflichtargument path fehlt

    def test_wrong_argument_type_is_error(self, cfg: Config):
        runtime.set_config(cfg)
        call_fail("system_status", include_disk="ja-bitte")

    def test_screen_info(self, fake_gui, cfg: Config):
        runtime.set_config(cfg)
        assert "1920" in call_ok("screen_info")


class TestGuardDecorator:
    """Der ``guard``-Wrapper muss erwartete Fehler in ToolError verwandeln."""

    def test_value_error_becomes_tool_error(self, cfg: Config):
        runtime.set_config(cfg)
        with pytest.raises(ToolError, match="ValueError"):
            asyncio.run(server.call_tool("sleep", {"seconds": -5}))

    def test_file_not_found_becomes_tool_error(self, cfg: Config, workspace: Path):
        runtime.set_config(cfg)
        with pytest.raises(ToolError, match="FileNotFoundError"):
            asyncio.run(server.call_tool("file_read", {"path": str(workspace / "gibtsnicht.txt")}))

    def test_window_close_requires_confirm(self, cfg: Config):
        runtime.set_config(cfg)
        # Fenster existiert nicht -> erst die Bestätigung wird geprüft.
        assert "ConfirmationRequired" in call_fail("window_action", title="egal", action="close")