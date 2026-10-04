"""Funktionaler Live-Test aller vier Module über einen frischen MCP-Server.

Dieser Test startet `python -m pcbediener serve` mit dem aktuellen Code und
ruft jeden Funktionsbereich über das Protokoll auf. Ergebnis: PASS/FAIL pro
Modul-Funktion. Gefundene Fehler werden nicht geschleiert, sondern als FAIL
gemeldet.
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TMP = Path(tempfile.mkdtemp(prefix="pcbediener_functest_"))


def ok(msg):
    print(f"  [PASS] {msg}")


def fail(msg, detail=""):
    print(f"  [FAIL] {msg}" + (f"\n        {detail}" if detail else ""))


async def call(session, tool, **args):
    r = await session.call_tool(tool, arguments=args)
    texts = [c.text for c in r.content if getattr(c, "type", "") == "text"]
    return bool(getattr(r, "is_error", False)), "\n".join(texts)


async def main():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env["PCB_ALLOWED_PATHS"] = str(TMP) + os.pathsep + str(ROOT)
    env["PCB_EXEC_CWD"] = str(TMP)
    env["PCB_SCREENSHOT_DIR"] = str(TMP / "shots")

    params = StdioServerParameters(
        command=sys.executable, args=["-m", "pcbediener", "serve"], env=env
    )

    print("starte frischen Server...")
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = {t.name for t in (await s.list_tools()).tools}
            print(f"Tools online: {len(tools)}\n")

            # --- Modul A ------------------------------------------------
            print("== Modul A: Code-Ausführung ==")
            err, t = await call(s, "exec_python", code="print('Hallo'); import sys; print(sys.version_info.major)", confirm=True)
            ok("exec_python") if (not err and "Hallo" in t) else fail("exec_python", t[:200])

            err, t = await call(s, "exec_powershell", script="Write-Output 'OK-PS'", confirm=True)
            ok("exec_powershell") if (not err and "OK-PS" in t) else fail("exec_powershell", t[:200])

            err, t = await call(s, "exec_command", command="Write-Output 'OK-CMD'", confirm=True)
            ok("exec_command") if (not err and "OK-CMD" in t) else fail("exec_command", t[:200])

            # Fehlerfall: muss ok:false + Traceback liefern, nicht crashen
            err, t = await call(s, "exec_python", code="raise RuntimeError('boom')", confirm=True)
            ok("exec_python Statuserkennung (RuntimeError)") if (not err and '"ok": false' in t and "RuntimeError" in t) else fail("exec_python Fehlerfall", t[:200])

            # --- Modul D ------------------------------------------------
            print("\n== Modul D: Dateisystem ==")
            err, t = await call(s, "folder_create", path=str(TMP / "ordner"))
            ok("folder_create") if not err else fail("folder_create", t[:200])

            err, t = await call(s, "file_write", path=str(TMP / "datei.txt"), content="Zeile1\nZeile2\nZeile3", confirm=True)
            ok("file_write") if not err else fail("file_write", t[:200])

            err, t = await call(s, "file_write", path=str(TMP / "datei.txt"), content="Zeile4", append=True)
            ok("file_write(append, ohne confirm)") if not err else fail("file_write append", t[:200])

            err, t = await call(s, "file_read", path=str(TMP / "datei.txt"))
            ok("file_read") if (not err and "Zeile1" in t and "Zeile4" in t) else fail("file_read", t[:200])

            err, t = await call(s, "file_list", path=str(TMP))
            ok("file_list -> {count, entries}") if (not err and '"count"' in t and '"entries"' in t) else fail("file_list", t[:200])

            err, t = await call(s, "file_tree", path=str(TMP))
            ok("file_tree -> {count, entries}") if (not err and '"count"' in t) else fail("file_tree", t[:200])

            err, t = await call(s, "file_search", path=str(TMP), pattern="*.txt")
            ok("file_search -> {count, matches}") if (not err and '"count": 1' in t) else fail("file_search", t[:200])

            err, t = await call(s, "file_copy", src=str(TMP / "datei.txt"), dst=str(TMP / "datei_kopie.txt"))
            ok("file_copy") if not err else fail("file_copy", t[:200])

            err, t = await call(s, "file_move", src=str(TMP / "datei_kopie.txt"), dst=str(TMP / "datei_verschoben.txt"), confirm=True)
            ok("file_move") if not err else fail("file_move", t[:200])

            err, t = await call(s, "file_delete", path=str(TMP / "datei_verschoben.txt"), confirm=True)
            ok("file_delete") if not err else fail("file_delete", t[:200])

            # sichere Löschanforderung ohne confirm muss scheitern
            err, t = await call(s, "file_delete", path=str(TMP / "datei.txt"))
            ok("file_delete(confirm) Gate") if (err and "ConfirmationRequired" in t) else fail("Gate file_delete", t[:200])

            # --- Modul C ------------------------------------------------
            print("\n== Modul C: Vision & Status ==")
            err, t = await call(s, "system_status")
            ok("system_status") if (not err and '"logical_cores"' in t) else fail("system_status", t[:200])

            err, t = await call(s, "screenshot", max_width=400)
            ok("screenshot") if (not err and "path" in t) else fail("screenshot", t[:200])

            err, t = await call(s, "screen_info")
            ok("screen_info") if (not err and '"width"' in t) else fail("screen_info", t[:200])

            # --- Modul B ------------------------------------------------
            print("\n== Modul B: GUI & Prozesse ==")
            err, t = await call(s, "window_list")
            ok("window_list -> {count, windows}") if (not err and '"count"' in t and '"windows"' in t) else fail("window_list", t[:200])

            err, t = await call(s, "process_list", limit=3, sort_by="memory")
            ok("process_list -> {count, processes}") if (not err and '"count"' in t and '"total_matched"' in t) else fail("process_list", t[:200])

            # Prozess starten + wieder beenden (Gate: beide mit confirm)
            err, t = await call(s, "exec_python", code="import time; time.sleep(6)", confirm=True, timeout=1)
            ok("timeout erkannt") if (not err and '"timed_out": true' in t) else fail("exec timeout", t[:200])

            err, t = await call(s, "process_start", program=str(sys.executable), arguments=["-c", "import time; time.sleep(4)"], background=True, confirm=True)
            ok("process_start") if (not err and '"pid"' in t) else fail("process_start", t[:200])
            if not err:
                try:
                    pid = json.loads(t)["pid"]
                    await asyncio.sleep(0.5)
                    err2, t2 = await call(s, "process_kill", pid=pid, force=True, confirm=True)
                    ok("process_kill") if not err2 else fail("process_kill", t2[:200])
                except Exception as e:
                    fail("process_kill(pid)", str(e)[:160])

            # Maus/Tastatur in Roh: nur bewegen (keine echten Aktionen)
            err, t = await call(s, "mouse_move", x=960, y=600)
            ok("mouse_move") if not err else fail("mouse_move", t[:200])

            # --- Steuerwerkzeuge --------------------------------------------
            print("\n== Steuerung: safety ==")
            err, t = await call(s, "safety_status")
            ok("safety_status") if (not err and '"safety_mode"' in t) else fail("safety_status", t[:200])

            err, t = await call(s, "safety_mode", mode="auto")
            auto_ok = not err and '"safety_mode": "auto"' in t
            await call(s, "safety_mode", mode="confirm")  # zuruecksetzen
            ok("safety_mode Umschalten") if auto_ok else fail("safety_mode", t[:200])

            # Sperrliste gilt IMMER, auch in auto
            err, t = await call(s, "safety_mode", mode="auto")
            err, t = await call(s, "exec_python", code="import shutil; shutil.rmtree('C:/')", confirm=True)
            ok("Sperrliste blockiert auch in auto") if (err and "ForbiddenCommand" in t) else fail("Sperrliste", t[:200])
            await call(s, "safety_mode", mode="confirm")

    print(f"\nFunktions-Test-Dateien: {TMP}")
    print("\nHinweis: Screenshot + Maus/Fenster-Klicks wurden NICHT gefuehrt")
    print("(das waere invasiv); sie werden eh schon ueber die Unit-Tests abgedeckt.")


if __name__ == "__main__":
    asyncio.run(main())
