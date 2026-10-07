"""Laufzeit-Zustand: die aktuell gültige :class:`~pcbediener.config.Config`.

Die MCP-Tools lesen und schreiben die Konfiguration über diese Funktionen, damit
der Sicherheitsmodus auch **während** einer laufenden Sitzung umgeschaltet werden
kann (z.B. von ``confirm`` auf ``auto``), ohne den Server neu zu starten.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from .config import Config, load_config
from .safety import SafetyError

_lock = threading.RLock()
_config: Config | None = None

#: Pro-Modell-Status: { model_id: {"failures": int, "last_failure": float | None, "cooldown_until": float | None} }
_model_state: dict[str, dict[str, float | int | None]] = {}


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
        "model_state": dict(_model_state),
    }


def get_model_state(model_id: str) -> dict[str, float | int | None]:
    """Liefert (und erzeugt) den Status eines Modells."""
    with _lock:
        state = _model_state.setdefault(
            model_id,
            {"failures": 0, "last_failure": None, "cooldown_until": None},
        )
        return dict(state)


def record_model_failure(model_id: str) -> None:
    """Erhöht den Fehlerzähler und setzt den Cooldown-Timer für ein Modell."""
    cfg = get_config()
    now = time.monotonic()
    with _lock:
        state = _model_state.setdefault(
            model_id,
            {"failures": 0, "last_failure": None, "cooldown_until": None},
        )
        state["failures"] = int(state["failures"]) + 1
        state["last_failure"] = now
        state["cooldown_until"] = now + cfg.model_cooldown_s


def reset_model_state(model_id: str | None = None) -> None:
    """Setzt den Status eines oder aller Modelle zurück (nach Erfolg)."""
    with _lock:
        if model_id:
            _model_state.pop(model_id, None)
        else:
            _model_state.clear()


def model_available(model_id: str) -> bool:
    """Prüft, ob ein Modell momentan nicht im Cooldown/Sperrliste ist."""
    cfg = get_config()
    state = get_model_state(model_id)
    now = time.monotonic()
    cooldown_until = state.get("cooldown_until")
    if cooldown_until is not None and now < float(cooldown_until):
        return False
    if int(state.get("failures", 0)) >= cfg.model_max_failures:
        return False
    return True


def next_available_model() -> str | None:
    """Liefert das erste Modell aus der Kette, das momentan verwendbar ist."""
    cfg = get_config()
    for model in cfg.model_chain:
        if model_available(model):
            return model
    return None