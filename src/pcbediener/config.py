"""Konfiguration für den PC-Bediener.

Die Konfiguration lässt sich auf drei Wegen beeinflussen (später gewinnt):

1. Standardwerte in :class:`Config`
2. JSON-Datei (Standard: ``%APPDATA%\\pcbediener\\config.json``)
3. Umgebungsvariablen mit dem Präfix ``PCB_``

Sicherheitsmodus
-----------------
``safety_mode = "confirm"`` (Standard)
    Destruktive Aktionen (Löschen, Registry, Prozess-Kill, Codeausführung)
    laufen nur, wenn der Aufrufer ausdrücklich ``confirm=True`` setzt.

``safety_mode = "auto"``
    Die KI handelt vollautonom. Die verbotenen Muster aus
    :data:`pcbediener.safety.FORBIDDEN` gelten trotzdem *immer*.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Literal

SafetyMode = Literal["confirm", "auto"]

CONFIG_ENV_PREFIX = "PCB_"
APP_DIR_NAME = "pcbediener"


def default_config_path() -> Path:
    """Pfad der globalen JSON-Konfiguration."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(base) / APP_DIR_NAME / "config.json"


def default_screenshot_dir() -> Path:
    """Ordner für Screenshots der KI."""
    env = os.environ.get("PCB_SCREENSHOT_DIR")
    return Path(env) if env else (Path.cwd() / "screenshots")


@dataclass
class Config:
    """Laufzeit-Konfiguration."""

    # --- Sicherheit -------------------------------------------------------
    safety_mode: SafetyMode = "confirm"
    # Verzeichnisse, in denen der Dateisystem-Zugriff erlaubt ist.
    # Leer bedeutet: nur der Benutzer-Ordner (%USERPROFILE%).
    allowed_paths: list[str] = field(default_factory=list)
    # Zusätzliche Regex-Muster (ignore-case), die NIE ausgeführt werden dürfen.
    forbidden_patterns: list[str] = field(default_factory=list)

    # --- Modul A: Codeausführung -----------------------------------------
    exec_timeout: int = 60
    exec_max_output_chars: int = 20_000
    # Arbeitsverzeichnis für ausgeführten Code (None = aktuelles Verzeichnis).
    exec_cwd: str | None = None
    # Umgebungsvariablen, die zusätzlich an Subprozesse durchgereicht werden.
    exec_env: dict[str, str] = field(default_factory=dict)

    # --- Modul B/C: GUI, Vision, Status ----------------------------------
    screenshot_dir: str = ""
    screenshot_max_region: tuple[int, int, int, int] | None = None
    click_delay_ms: int = 0
    key_delay_ms: int = 0

    # --- Meta ------------------------------------------------------------
    source_path: str = ""

    # --- Vision-Modell-Routing -------------------------------------------
    # Primärmodell für Bild-/Screenshot-Analyse (free); Fallback, wenn das
    # Primärmodell nicht liefert (z.B. Rate-Limit, Session hängt).
    vision_primary: str = "opencode/space-bunny-free"
    vision_fallback: str = "opencode/fledge-alpha-free"

    # --- LLM-Fallback-Kette -----------------------------------------------
    # Priorisierte Liste aller kostenlosen Text-Modelle, die bei Rate-Limit,
    # Quota- oder Credits-Fehlern automatisch als Nächstes probiert werden.
    # Die Reihenfolge orientiert sich am Latenz-Test (schnellste zuerst).
    model_chain: list[str] = field(
        default_factory=lambda: [
            "opencode/ling-3.1-flash-free",
            "opencode/space-bunny-free",
            "opencode/fledge-alpha-free",
            "opencode/longcat-2.5-preview-free",
            "opencode/mimo-v2.6-flash-free",
            "opencode/muse-spark-1.3-contributor-free",
            "opencode/nemotron-3.5-lightning-free",
            "google/gemma-4-31b-it",
            "openrouter/apodex/apodex-1.1-mini:free",
            "openrouter/stealth/space-bunny-alpha",
            "openrouter/poolside/laguna-s-2.1:free",
            "openrouter/dots-studio/dots-3-note-preview:free",
            "openrouter/cohere/north-mini-code:free",
            "openrouter/liquid/lfm-2.5-2.6b:free",
            "openrouter/poolside/laguna-xs-2.1:free",
            "openrouter/openrouter/free",
        ]
    )
    # Wie lange ein Modell nach einem Fehler nicht erneut versucht wird (Sekunden).
    model_cooldown_s: int = 60
    # Wie oft hintereinander ein Modell Fehlerzeichen zeigen darf, bevor es
    # komplett aus der Kette entfernt wird.
    model_max_failures: int = 3

    def __post_init__(self) -> None:
        if not self.screenshot_dir:
            self.screenshot_dir = str(default_screenshot_dir())
        if self.safety_mode not in ("confirm", "auto"):
            raise ValueError(
                f"safety_mode muss 'confirm' oder 'auto' sein, nicht {self.safety_mode!r}"
            )
        if self.exec_timeout <= 0:
            raise ValueError("exec_timeout muss > 0 sein")

    # -- Ableitungen ------------------------------------------------------
    @property
    def requires_confirmation(self) -> bool:
        """True, wenn destruktive Aktionen ein ``confirm=True`` brauchen."""
        return self.safety_mode == "confirm"

    def resolved_allowed_paths(self) -> list[Path]:
        """Pfade, in denen Dateioperationen erlaubt sind."""
        raw = self.allowed_paths or [os.environ.get("USERPROFILE") or str(Path.home())]
        out: list[Path] = []
        for entry in raw:
            try:
                out.append(Path(entry).expanduser().resolve())
            except OSError:
                continue
        return out

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: str | Path | None = None) -> Path:
        """Konfiguration als JSON persistieren."""
        target = Path(path) if path else default_config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return target


def _coerce(raw: str, current: Any) -> Any:
    """Umgebungswert anhand des aktuellen Werts in den richtigen Typ wandeln."""
    if isinstance(current, bool):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(current, int):
        return int(raw)
    if isinstance(current, tuple):
        return tuple(int(x) for x in raw.split(",") if x.strip())
    if isinstance(current, list):
        return [p.strip() for p in raw.split(os.pathsep) if p.strip()]
    if isinstance(current, dict):
        return json.loads(raw)
    return raw


def config_path() -> Path:
    """Aktiver Konfigurationspfad (Env-Override vor Default)."""
    override = os.environ.get(f"{CONFIG_ENV_PREFIX}CONFIG")
    return Path(override) if override else default_config_path()


def load_config(path: str | Path | None = None) -> Config:
    """Konfiguration aus Defaults, Datei und Umgebungsvariablen aufbauen."""
    resolved = Path(path) if path else config_path()
    defaults = Config()

    data: dict[str, Any] = {}
    if resolved.is_file():
        data = json.loads(resolved.read_text(encoding="utf-8"))

    known = {f.name for f in fields(Config)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(
            f"Unbekannte Konfigurationsschlüssel in {resolved}: "
            + ", ".join(sorted(unknown))
        )

    kwargs: dict[str, Any] = {}
    for f in fields(Config):
        if f.name == "source_path":
            continue
        current = getattr(defaults, f.name)
        value = data.get(f.name, current)

        env_name = f"{CONFIG_ENV_PREFIX}{f.name.upper()}"
        if env_name in os.environ:
            value = _coerce(os.environ[env_name], current)

        # Aus JSON kommt immer eine Liste, kein Tupel.
        if f.name == "screenshot_max_region" and value is not None:
            value = tuple(value)
        kwargs[f.name] = value

    return Config(source_path=str(resolved), **kwargs)