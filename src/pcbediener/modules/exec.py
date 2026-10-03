"""Modul A – Code-Ausführung.

Nimmt Code (Python / PowerShell / Shell) entgegen, führt ihn lokal aus und
liefert stdout/stderr/Exit-Code zurück, damit die KI Fehler selbst korrigieren kann.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from ..config import Config
from ..paths import resolve_within
from ..safety import check_not_forbidden, require_confirm

Shell = Literal["powershell", "pwsh", "cmd", "bash", "sh"]


@dataclass
class ExecResult:
    """Ergebnis eines ausgeführten Befehls."""

    command: str
    returncode: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool = False
    truncated: bool = False
    cwd: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["ok"] = self.ok
        return d

    def summary(self) -> str:
        """Kurzfassung für Fehlermeldungen der KI."""
        state = "OK" if self.ok else f"FEHLER (exit {self.returncode})"
        if self.timed_out:
            state = "TIMEOUT"
        parts = [f"[{state}] {self.command}", f"Dauer: {self.duration_s:.2f}s"]
        if self.stdout.strip():
            parts.append("--- stdout ---\n" + self.stdout.rstrip())
        if self.stderr.strip():
            parts.append("--- stderr ---\n" + self.stderr.rstrip())
        if self.truncated:
            parts.append("(Ausgabe gekürzt)")
        return "\n".join(parts)


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    """Kürzt Ausgabe, behält aber Kopf *und* Fuß (Fehler stehen meist am Ende)."""
    if limit <= 0 or len(text) <= limit:
        return text, False
    head = int(limit * 0.3)
    tail = limit - head
    return (
        text[:head]
        + f"\n... [{len(text) - limit} Zeichen ausgegeben] ...\n"
        + text[-tail:],
        True,
    )


def _workdir(cfg: Config) -> str:
    if cfg.exec_cwd:
        return str(resolve_within(cfg.exec_cwd, cfg))
    return str(Path.cwd())


def _base_env(cfg: Config) -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")
    env.update(cfg.exec_env)
    return env


def _dispatch(
    command: list[str],
    label: str,
    cfg: Config,
    timeout: int | None,
    confirm: bool,
) -> ExecResult:
    require_confirm(confirm, cfg, "Codeausführung", label)
    effective_timeout = timeout or cfg.exec_timeout
    cwd = _workdir(cfg)

    start = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.run(  # noqa: S603 - Kernzweck dieses Moduls
            command,
            cwd=cwd,
            env=_base_env(cfg),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=effective_timeout,
            shell=False,
            check=False,
        )
        returncode, stdout, stderr = proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = -1
        stdout = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = (exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        stderr += f"\nZeitüberschreitung nach {effective_timeout}s – Prozess beendet."

    duration = time.monotonic() - start
    limit = cfg.exec_max_output_chars
    stdout, t1 = _truncate(stdout, limit)
    stderr, t2 = _truncate(stderr, limit)

    return ExecResult(
        command=label,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        duration_s=round(duration, 3),
        timed_out=timed_out,
        truncated=t1 or t2,
        cwd=cwd,
    )


# --- Öffentliche API --------------------------------------------------------


def run_python(code: str, cfg: Config, timeout: int | None = None, confirm: bool = False) -> ExecResult:
    """Führt Python-Code im aktuellen Interpreter aus."""
    if not code or not code.strip():
        raise ValueError("code darf nicht leer sein")
    check_not_forbidden(code, cfg, "Python-Code")
    return _dispatch([sys.executable, "-I", "-c", code], "python -c <code>", cfg, timeout, confirm)


def run_powershell(
    script: str, cfg: Config, timeout: int | None = None, confirm: bool = False
) -> ExecResult:
    """Führt ein PowerShell-Skript aus (pwsh bevorzugt, Fallback powershell.exe)."""
    if not script or not script.strip():
        raise ValueError("script darf nicht leer sein")
    check_not_forbidden(script, cfg, "PowerShell-Skript")
    exe = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
    return _dispatch(
        [exe, "-NoProfile", "-NonInteractive", "-Command", script],
        "powershell <script>",
        cfg,
        timeout,
        confirm,
    )


def run_command(
    command: str,
    cfg: Config,
    timeout: int | None = None,
    confirm: bool = False,
    shell: Shell | None = None,
) -> ExecResult:
    """Führt einen beliebigen Shell-Befehl aus.

    ``shell`` erzwingt die Interpreter-Binärdatei. Standard: unter Windows
    PowerShell, sonst ``/bin/sh``.
    """
    if not command or not command.strip():
        raise ValueError("command darf nicht leer sein")
    check_not_forbidden(command, cfg, "Befehl")

    chosen: str = shell or ("powershell" if os.name == "nt" else "sh")
    if chosen in ("powershell", "pwsh"):
        return run_powershell(command, cfg, timeout, confirm)
    if chosen == "cmd":
        return _dispatch(["cmd", "/c", command], "cmd /c <command>", cfg, timeout, confirm)

    exe = shutil.which(chosen)
    if not exe:
        raise ValueError(f"Shell {chosen!r} wurde nicht gefunden")
    return _dispatch([exe, "-c", command], f"{chosen} -c <command>", cfg, timeout, confirm)