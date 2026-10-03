"""Laufzeit-Zustand: die aktuell gültige :class:`~pcbediener.config.Config`.

Die MCP-Tools lesen und schreiben die Konfiguration über diese Funktionen, damit
der Sicherheitsmodus auch **während** einer laufenden Sitzung umgeschaltet werden
kann (z.B. von ``confirm`` auf ``auto``), ohne den Server neu zu starten.
"""

from __future__ import annotations

import threading
from pathlib import Path

from .config import Config, load_config
from .safety import SafetyError

_lock = threading.RLock()
_config: Config | None = None


def get_config() -> Config:
    """Gibt die aktive Konfiguration zurück (lädt sie beim ersten Mal)."""
    global _config
    with _lock:
        if _config is None:
            _config = load_config()
        return _config


def set_config(cfg: Config) -> Config:
    """Setzt eine neue aktive Konfiguration."""
    global _config
    with _lock:
        _config = cfg
        return _config


def reload_config(path: str | Path | None = None) -> Config:
    """Lädt die Konfiguration neu von der Platte."""
    global _config
    with _lock:
        _config = load_config(path)
        return _config


def set_safety_mode(mode: str) -> Config:
    """Schaltet den Sicherheitsmodus um und hält die restliche Config bei.

    Args:
        mode: ``"confirm"`` (destruktive Aktionen brauchen ``confirm=True``)
            oder ``"auto"`` (vollautonom).
    """
    cfg = get_config()
    if mode not in ("confirm", "auto"):
        raise SafetyError("safety_mode muss 'confirm' oder 'auto' sein")
    updated = Config(**{**cfg.to_dict(), "safety_mode": mode})
    return set_config(updated)


def describe() -> dict[str, object]:
    """Aktueller Zustand in kompakter Form – auch für ``safety_status``."""
    cfg = get_config()
    return {
        "safety_mode": cfg.safety_mode,
        "requires_confirmation": cfg.requires_confirmation,
        "config_file": cfg.source_path,
        "config_exists": Path(cfg.source_path).is_file() if cfg.source_path else False,
        "allowed_paths": [str(p) for p in cfg.resolved_allowed_paths()],
        "exec_timeout_s": cfg.exec_timeout,
        "exec_cwd": cfg.exec_cwd or "Projektordner",
        "screenshot_dir": cfg.screenshot_dir,
        "extra_forbidden_patterns": cfg.forbidden_patterns,
    }