"""Modul B (Teil 2) – Prozess-Steuerung.

Programme starten, laufende Prozesse prüfen und beenden.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import psutil

from ..config import Config
from ..safety import check_not_forbidden, require_confirm

#: Prozesse, die niemals beendet werden dürfen – sonst wird Windows unbrauchbar.
PROTECTED_NAMES = {
    "system", "system idle process", "registry", "memory compression",
    "csrss", "wininit", "winlogon", "smss", "services", "lsass", "svchost",
    "explorer.exe", "dwm.exe", "audiodg.exe", "this pc bediener",
}


@dataclass
class ProcessInfo:
    pid: int
    name: str
    username: str = ""
    status: str = ""
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    created: float = 0.0
    exe: str = ""
    cmdline: str = ""
    cwd: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _to_info(proc: psutil.Process) -> ProcessInfo:
    info = ProcessInfo(pid=proc.pid, name=proc.name())
    try:
        with proc.oneshot():
            info.username = proc.username()
            info.status = proc.status()
            info.cpu_percent = proc.cpu_percent(interval=None)
            info.memory_mb = round(proc.memory_info().rss / 1_048_576, 1)
            info.created = proc.create_time()
            info.exe = proc.exe()
            info.cmdline = " ".join(proc.cmdline())
            info.cwd = proc.cwd()
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        # Felder, die wir ohne Rechte nicht lesen können, bleiben leer.
        pass
    return info


def list_processes(
    cfg: Config, filter_text: str = "", limit: int = 50, sort_by: str = "cpu"
) -> dict[str, Any]:
    """Listet laufende Prozesse, optional nach Name gefiltert.

    Liefert ``{"count": n, "processes": [...]}`` statt einer nackten Liste, damit
    der MCP-Client einen einzigen JSON-Block mit Anzahl bekommt.
    """
    if sort_by not in ("cpu", "memory", "name", "pid"):
        raise ValueError("sort_by muss cpu, memory, name oder pid sein")

    needle = filter_text.lower()
    found: list[ProcessInfo] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = (proc.info["name"] or "").lower()
            if needle and needle not in name and needle not in str(proc.pid):
                continue
            info = _to_info(proc)
            found.append(info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    keys = {
        "cpu": lambda i: -i.cpu_percent,
        "memory": lambda i: -i.memory_mb,
        "name": lambda i: i.name.lower(),
        "pid": lambda i: i.pid,
    }
    found.sort(key=keys[sort_by])
    limited = found[:limit]
    return {
        "count": len(limited),
        "total_matched": len(found),
        "truncated": len(found) > len(limited),
        "sort_by": sort_by,
        "processes": [i.to_dict() for i in limited],
    }


def process_info(pid: int) -> dict[str, Any]:
    """Details zu einem einzelnen Prozess."""
    try:
        return _to_info(psutil.Process(pid)).to_dict()
    except psutil.NoSuchProcess as exc:
        raise ValueError(f"Kein Prozess mit PID {pid}") from exc


def kill_process(pid: int, cfg: Config, force: bool = False, confirm: bool = False) -> dict[str, Any]:
    """Beendet einen Prozess.

    Blockiert im Modus ``confirm`` ohne ``confirm=True``. Systemprozesse und der
    eigene Prozess werden immer geschützt.
    """
    try:
        proc = psutil.Process(pid)
        name = proc.name()
    except psutil.NoSuchProcess as exc:
        raise ValueError(f"Kein Prozess mit PID {pid}") from exc

    if pid == os.getpid():
        raise ValueError("Der eigene Prozess kann nicht beendet werden")
    if name.lower() in PROTECTED_NAMES:
        raise ValueError(
            f"Prozess {name!r} (PID {pid}) ist geschützt und wird nicht beendet."
        )

    require_confirm(confirm, cfg, "Prozess beenden", f"{name} (PID {pid})")

    # Erst höflich, dann hart – wie es ein Mensch tun würde.
    try:
        if force:
            proc.kill()
        else:
            proc.terminate()
        gone, alive = psutil.wait_procs([proc], timeout=3)
        if alive:
            proc.kill()
            psutil.wait_procs([proc], timeout=2)
        return {"pid": pid, "name": name, "terminated": True, "forced": force}
    except psutil.NoSuchProcess:
        return {"pid": pid, "name": name, "terminated": True, "note": "war schon beendet"}
    except psutil.AccessDenied as exc:
        raise PermissionError(
            f"Keine Rechte, um PID {pid} ({name}) zu beenden. "
            "Administratorrechte erforderlich."
        ) from exc


def start_process(
    command: str | list[str],
    cfg: Config,
    background: bool = True,
    arguments: list[str] | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Startet ein Programm.

    Args:
        command: Programmname (``"spotify"``) oder Pfad (``C:\\...\\app.exe``).
        arguments: Zusätzliche Argumente, wenn ``command`` kein Pfad ist.
        background: ``True`` startet entkoppelt und wartet nicht auf Beendigung.
    """
    require_confirm(confirm, cfg, "Programm starten", command if isinstance(command, str) else " ".join(command))

    if isinstance(command, str):
        check_not_forbidden(command, cfg, "Startbefehl")
        exe = command
        args = list(arguments or [])
    else:
        exe, args = command[0], [*command[1:], *(arguments or [])]

    resolved_exe = _which(exe, cfg)
    argv = [resolved_exe, *args]

    env = dict(os.environ)
    if background and os.name == "nt":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: überlebt das Ende
        # des aufrufenden Prozesses und blockiert nicht.
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(
            argv, env=env, cwd=cfg.exec_cwd or None,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
    elif background:
        proc = subprocess.Popen(
            argv, env=env, cwd=cfg.exec_cwd or None,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
    else:
        started = time.monotonic()
        done = subprocess.run(
            argv, env=env, cwd=cfg.exec_cwd or None, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=cfg.exec_timeout, check=False,
        )
        return {
            "command": " ".join(argv),
            "returncode": done.returncode,
            "stdout": (done.stdout or "")[: cfg.exec_max_output_chars],
            "stderr": (done.stderr or "")[: cfg.exec_max_output_chars],
            "duration_s": round(time.monotonic() - started, 3),
            "background": False,
        }

    time.sleep(0.3)  # kurz warten, damit der Prozess sich registriert
    alive = psutil.pid_exists(proc.pid)
    return {"pid": proc.pid, "command": " ".join(argv), "background": True, "running": alive}


def _which(exe: str, cfg: Config) -> str:
    """Findet ein Programm: absoluter Pfad, dann PATH.

    Die Datei-Allowlist aus :mod:`pcbediener.paths` gilt bewusst *nicht* hier:
    sie beschreibt, wo die KI Daten lesen/schreiben darf, nicht wo Programme
    installiert sind. Programme Starten wird stattdessen durch ``require_confirm``
    und das Verbot destruktiver Befehle abgesichert.
    """
    candidate = Path(exe).expanduser()
    if candidate.is_absolute() or candidate.suffix.lower() in (".exe", ".bat", ".cmd"):
        if not candidate.is_file():
            raise FileNotFoundError(f"Programmdatei nicht gefunden: {candidate}")
        return str(candidate.resolve())

    from shutil import which

    found = which(exe) or which(f"{exe}.exe")
    if found:
        return found
    raise FileNotFoundError(
        f"Programm {exe!r} wurde nicht im PATH gefunden. "
        "Nutze den vollständigen Pfad zur .exe-Datei."
    )