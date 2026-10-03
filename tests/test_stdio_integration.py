"""Integrationstest: echter MCP-Handshake über stdio.

Der Test startet ``python -m pcbediener serve`` als echten Subprozess – genau so,
wie OpenCode es später tut – und spricht über das MCP-Protokoll mit ihm. Damit
werden Fehler abgefangen, die Unit-Tests nicht sehen: falscher Transport,
kaputte stdout-Ausgabe, fehlende Tool-Schemas, Absturz beim Start.

Läuft nur unter Windows (die Module sind Windows-orientiert).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not (sys.platform == "win32" and shutil.which("python")),
    reason="MCP-stdio-Integration läuft nur unter Windows mit python im PATH",
)


def _config_file(tmp_path: Path) -> Path:
    import json

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir(exist_ok=True)
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "safety_mode": "confirm",
                "allowed_paths": [str(sandbox)],
                "exec_cwd": str(sandbox),
                "screenshot_dir": str(sandbox / "shots"),
                "exec_timeout": 20,
            }
        ),
        encoding="utf-8",
    )
    return path


class TestStdioIntegration:
    def test_handshake_lists_and_calls_tools(self, tmp_path: Path):
        """Kompletter Roundtrip: verbinden, Tools listen, Tool aufrufen."""
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        config = _config_file(tmp_path)
        sandbox = tmp_path / "sandbox"
        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        env["PCB_CONFIG"] = str(config)

        async def scenario() -> tuple[int, str, str]:
            from mcp import StdioServerParameters

            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "pcbediener", "--config", str(config), "serve"],
                env=env,
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    tools = await session.list_tools()
                    names = {t.name for t in tools.tools}

                    # Ein echter Tool-Aufruf über das Protokoll.
                    result = await session.call_tool(
                        "file_write",
                        arguments={
                            "path": str(sandbox / "hallo.txt"),
                            "content": "über MCP geschrieben",
                            "confirm": True,
                        },
                    )
                    return len(names), (sandbox / "hallo.txt").read_text(encoding="utf-8"), bool(
                        result.is_error
                    )

        tool_count, file_content, is_error = asyncio.run(scenario())

        assert tool_count >= 30, "Server bietet zu wenige Tools an"
        assert file_content == "über MCP geschrieben"
        assert is_error is False, "Tool-Aufruf meldete einen Fehler"

    def test_safety_gate_works_over_protocol(self, tmp_path: Path):
        """Auch über das Protokoll gilt die Bestätigungspflicht."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        config = _config_file(tmp_path)
        sandbox = tmp_path / "sandbox"
        target = sandbox / "opfer.txt"
        target.write_text("nicht löschen", encoding="utf-8")

        env = dict(os.environ)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        env["PCB_CONFIG"] = str(config)

        async def scenario() -> str:
            params = StdioServerParameters(
                command=sys.executable,
                args=["-m", "pcbediener", "--config", str(config), "serve"],
                env=env,
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "file_delete", arguments={"path": str(target)}
                    )
                    texts = [
                        block.text
                        for block in result.content
                        if getattr(block, "type", "") == "text"
                    ]
                    return "\n".join(texts)

        message = asyncio.run(scenario())
        assert "ConfirmationRequired" in message
        assert target.is_file(), "Datei wurde trotz Bestätigungspflicht gelöscht!"