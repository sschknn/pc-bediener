"""Modul D – Dateisystem-Zugriff.

Suchen, Lesen, Erstellen, Verschieben, Umbenennen und Löschen – ausschließlich
innerhalb der in :func:`pcbediener.paths.resolve_within` erlaubten Wurzeln.
"""

from __future__ import annotations

import base64
import fnmatch
import os
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..config import Config
from ..paths import resolve_within
from ..safety import check_not_forbidden, require_confirm

#: Formate, die nicht als Text gelesen werden können.
BINARY_SUFFIXES = {
    ".exe", ".dll", ".so", ".dylib", ".pyc", ".zip", ".7z", ".rar", ".gz", ".bz2",
    ".mp3", ".mp4", ".avi", ".mkv", ".mov", ".png", ".jpg", ".jpeg", ".gif", ".pdf",
}


@dataclass
class FileInfo:
    """Metadaten eines Pfades."""

    path: str
    name: str
    kind: str  # file | dir
    size: int
    modified: float  # Unix-Timestamp (mtime)
    suffix: str = ""
    hidden: bool = False
    read_only: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MatchInfo:
    """Treffer einer Suche."""

    path: str
    kind: str
    size: int
    modified: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def describe(path: Path) -> FileInfo:
    """Baut :class:`FileInfo` für einen existierenden Pfad."""
    return FileInfo(
        path=str(path),
        name=path.name or str(path),
        kind="dir" if path.is_dir() else "file",
        size=path.stat().st_size,
        modified=path.stat().st_mtime,
        suffix=path.suffix.lower(),
        hidden=path.name.startswith("."),
        read_only=not os.access(path, os.W_OK),
    )


def _sort_key(info: FileInfo) -> tuple[int, str]:
    """Ordner zuerst, dann alphabetisch – wie ein Datei-Explorer."""
    return (0 if info.kind == "dir" else 1, info.name.lower())


# --- Lesen ------------------------------------------------------------------


def read_text(
    path: str | Path, cfg: Config, max_chars: int = 200_000, encoding: str = "utf-8"
) -> dict[str, Any]:
    """Liest eine Textdatei und liefert Inhalt plus Metadaten."""
    target = resolve_within(path, cfg, must_exist=True)
    if target.is_dir():
        raise IsADirectoryError(f"{target} ist ein Ordner, keine Datei")
    if target.suffix.lower() in BINARY_SUFFIXES:
        raise ValueError(
            f"{target.suffix} ist ein Binärformat und nicht als Text lesbar. "
            "Nutze read_binary() für eine Base64-Ausgabe."
        )

    raw = target.read_bytes()
    truncated = len(raw) > max_chars
    if truncated:
        raw = raw[:max_chars]
    text = raw.decode(encoding, errors="replace")
    return {
        **describe(target).to_dict(),
        "content": text,
        "truncated": truncated,
        "lines": text.count("\n") + 1 if text else 0,
    }


def read_binary(path: str | Path, cfg: Config, max_bytes: int = 5_000_000) -> dict[str, Any]:
    """Liest eine Binärdatei und liefert sie Base64-kodiert zurück."""
    target = resolve_within(path, cfg, must_exist=True)
    data = target.read_bytes()
    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]
    return {
        **describe(target).to_dict(),
        "content_base64": base64.b64encode(data).decode("ascii"),
        "truncated": truncated,
        "bytes": len(data),
    }


# --- Schreiben --------------------------------------------------------------


def write_text(
    path: str | Path,
    content: str,
    cfg: Config,
    append: bool = False,
    make_parents: bool = True,
    confirm: bool = False,
) -> dict[str, Any]:
    """Erstellt oder überschreibt eine Textdatei.

    Überschreiben braucht im Modus ``confirm`` ein ``confirm=True``; Anhängen
    an eine existierende Datei ist nicht destruktiv und geht immer.
    """
    target = resolve_within(path, cfg)
    if not append:
        require_confirm(confirm, cfg, "Datei überschreiben", str(target))
    if target.is_dir():
        raise IsADirectoryError(f"{target} ist ein Ordner")
    if make_parents:
        target.parent.mkdir(parents=True, exist_ok=True)

    existed = target.exists()
    with target.open("a" if append else "w", encoding="utf-8", newline="") as fh:
        fh.write(content)
    return {
        **describe(target).to_dict(),
        "written_chars": len(content),
        "append": append,
        "created": not existed,
    }


def make_dir(
    path: str | Path, cfg: Config, parents: bool = True, exist_ok: bool = True
) -> dict[str, Any]:
    """Legt einen Ordner an."""
    target = resolve_within(path, cfg)
    target.mkdir(parents=parents, exist_ok=exist_ok)
    return describe(target).to_dict()


# --- Auflisten & Suchen -----------------------------------------------------


def list_dir(
    path: str | Path, cfg: Config, pattern: str = "*", recursive: bool = False
) -> dict[str, Any]:
    """Listet den Inhalt eines Ordners.

    Liefert ``{"count": n, "entries": [...]}`` statt einer nackten Liste: So
    bekommt der MCP-Client einen einzigen JSON-Block mit Anzahl, statt einen
    Textblock pro Datei.
    """
    target = resolve_within(path, cfg, must_exist=True)
    if not target.is_dir():
        raise NotADirectoryError(f"{target} ist kein Ordner")

    entries: list[FileInfo] = []
    for item in (target.rglob(pattern) if recursive else target.glob(pattern)):
        if item.is_dir():
            entries.append(describe(item))
        else:
            try:
                entries.append(describe(item))
            except OSError:
                continue  # z.B. gesperrte Datei
    entries.sort(key=_sort_key)
    return {"path": str(target), "count": len(entries), "entries": [e.to_dict() for e in entries]}


def search(
    path: str | Path,
    cfg: Config,
    pattern: str = "*",
    filter_glob: str | None = None,
    max_results: int = 500,
    max_depth: int = 12,
) -> dict[str, Any]:
    """Sucht rekursiv nach Dateien/Ordnern, mit Depth- und Mengen-Begrenzung.

    Args:
        pattern: Namensmuster mit ``*``/``?``/``[]``. Standard ``*`` = alles.
        filter_glob: Zusätzlicher Filter auf ``*.py``-Art gegen den Dateinamen.
    """
    root = resolve_within(path, cfg, must_exist=True)
    if not root.is_dir():
        raise NotADirectoryError(f"{root} ist kein Ordner")

    # Ein Muster mit Wildcards -> Regex übersetzen, sonst Namens-Gleichheit.
    matcher = (
        re.compile(fnmatch.translate(pattern)).match
        if any(ch in pattern for ch in "*?[")
        else None
    )

    results: list[MatchInfo] = []
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        if depth >= max_depth:
            dirnames[:] = []  # tiefe SÄume nicht weiter betreten

        for name in (*dirnames, *filenames):
            if filter_glob and not fnmatch.fnmatch(name.lower(), filter_glob.lower()):
                continue
            if matcher is not None and not matcher(name):
                continue
            if matcher is None and pattern not in ("*", "*.*") and pattern.lower() != name.lower():
                continue

            item = Path(dirpath) / name
            try:
                stat = item.stat()
            except OSError:
                continue
            results.append(
                MatchInfo(
                    path=str(item),
                    kind="dir" if item.is_dir() else "file",
                    size=stat.st_size,
                    modified=stat.st_mtime,
                )
            )
            if len(results) >= max_results:
                return {
                    "path": str(root),
                    "count": len(results),
                    "truncated": True,
                    "matches": [r.to_dict() for r in results],
                }

    return {
        "path": str(root),
        "count": len(results),
        "truncated": False,
        "matches": [r.to_dict() for r in results],
    }


def tree(
    path: str | Path, cfg: Config, max_entries: int = 400, max_depth: int = 3
) -> dict[str, Any]:
    """Kompakte Baumansicht – ideal, um die KI Struktur erfassen zu lassen."""
    root = resolve_within(path, cfg, must_exist=True)
    if not root.is_dir():
        return {"path": str(root), "count": 1, "entries": [describe(root).to_dict()]}

    entries: list[dict[str, Any]] = []

    def walk(directory: Path, depth: int) -> None:
        if depth > max_depth or len(entries) >= max_entries:
            return
        try:
            children = sorted(
                directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
            )
        except OSError:
            return
        for child in children:
            if len(entries) >= max_entries:
                return
            try:
                info = describe(child)
            except OSError:
                continue
            entries.append({**info.to_dict(), "depth": depth})
            if child.is_dir():
                walk(child, depth + 1)

    walk(root, 0)
    return {
        "path": str(root),
        "count": len(entries),
        "truncated": len(entries) >= max_entries,
        "entries": entries,
    }


# --- Verschieben, Kopieren, Löschen -----------------------------------------


def move(
    src: str | Path, dst: str | Path, cfg: Config, confirm: bool = False, overwrite: bool = False
) -> dict[str, Any]:
    """Verschiebt eine Datei / einen Ordner (auch Umbenennen)."""
    source = resolve_within(src, cfg, must_exist=True)
    target = resolve_within(dst, cfg)
    require_confirm(confirm, cfg, "Verschieben/Umbenennen", f"{source} -> {target}")
    if target.exists() and not overwrite:
        raise FileExistsError(f"Ziel existiert bereits: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    return {"source": str(source), "destination": str(target), "overwritten": target.exists()}


def copy(
    src: str | Path, dst: str | Path, cfg: Config, overwrite: bool = False
) -> dict[str, Any]:
    """Kopiert eine Datei oder einen Ordner rekursiv."""
    source = resolve_within(src, cfg, must_exist=True)
    target = resolve_within(dst, cfg)
    if target.exists() and not overwrite:
        raise FileExistsError(f"Ziel existiert bereits: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)
    return {"source": str(source), "destination": str(target)}


def delete(
    path: str | Path, cfg: Config, recursive: bool = False, confirm: bool = False
) -> dict[str, Any]:
    """Löscht eine Datei oder einen Ordner.

    Braucht im Modus ``confirm`` zwingend ``confirm=True``. Ordner werden nur
    mit ``recursive=True`` gelöscht, damit kein Versehen den Inhalt mitnimmt.
    """
    target = resolve_within(path, cfg, must_exist=True)
    require_confirm(confirm, cfg, "Löschen", str(target))

    if target.is_dir():
        if not recursive:
            if any(target.iterdir()):
                raise ValueError(
                    f"{target} ist nicht leer. Setze recursive=True, um den Ordner "
                    "mit Inhalt zu löschen."
                )
            target.rmdir()
            return {"path": str(target), "kind": "dir", "items_deleted": 0}
        count = sum(1 for _ in target.rglob("*"))
        shutil.rmtree(target)
        return {"path": str(target), "kind": "dir", "items_deleted": count}

    check_not_forbidden(str(target), cfg, "Löschpfad")
    size = target.stat().st_size
    target.unlink()
    return {"path": str(target), "kind": "file", "bytes_deleted": size}