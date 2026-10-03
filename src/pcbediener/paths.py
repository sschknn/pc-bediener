"""Pfad-Guard: Dateioperationen nur innerhalb erlaubter Wurzeln."""

from __future__ import annotations

from pathlib import Path

from .config import Config
from .safety import PathNotAllowed


def resolve_within(path: str | Path, cfg: Config, *, must_exist: bool = False) -> Path:
    """Löst ``path`` auf und prüft, dass er in einer erlaubten Wurzel liegt.

    ``Path.resolve()`` folgt Symlinks und ``..``, damit ein künstlicher Ausbruch
    über ``C:\\Users\\x\\..\\..\\Windows`` nicht funktioniert.

    Raises:
        PathNotAllowed: Pfad liegt außerhalb der erlaubten Wurzeln oder ist
            relativ, ohne ein Arbeitsverzeichnis zu haben.
    """
    raw = Path(path).expanduser()
    if not raw.is_absolute():
        raw = (Path(cfg.exec_cwd or Path.cwd()) / raw).resolve()
    else:
        raw = raw.resolve()

    if must_exist and not raw.exists():
        raise FileNotFoundError(f"Pfad existiert nicht: {raw}")

    allowed = cfg.resolved_allowed_paths()
    for root in allowed:
        if raw == root or root in raw.parents:
            return raw

    raise PathNotAllowed(
        f"Zugriff auf {raw} verweigert: erlaubt sind nur "
        + ", ".join(str(p) for p in allowed)
        + ". Erweitere die Liste über 'allowed_paths' in der Config."
    )


def is_within(path: str | Path, roots: list[Path]) -> bool:
    """True, wenn ``path`` unter einer der Wurzeln liegt."""
    resolved = Path(path).resolve()
    return any(resolved == r or r in resolved.parents for r in roots)