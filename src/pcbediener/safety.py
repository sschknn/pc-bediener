"""Sicherheits-Gate: Bestätigungen und Muster-Sperrliste.

Dieses Modul ist die einzige Stelle, die entscheidet, ob eine Aktion laufen darf.
Alle Module A-D fragen hier nach, bevor sie etwas Destruktives tun.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import Config


class SafetyError(RuntimeError):
    """Eine Aktion verstößt gegen eine Sicherheitsregel."""


class ConfirmationRequired(SafetyError):
    """Eine destruktive Aktion wurde ohne ``confirm=True`` angefordert."""


class ForbiddenCommand(SafetyError):
    """Der Code/Text enthält ein gesperrtes Muster."""


class PathNotAllowed(SafetyError):
    """Der Pfad liegt außerhalb der erlaubten Wurzeln."""


#: Muster, die in :mod:`exec` und bei Lösch-Aktionen **immer** abgelehnt werden.
#: Wer ``safety_mode="auto"`` setzt, hebt diese Sperre *nicht* auf.
#:
#: Die Muster sind bewusst reihenfolgeunabhängig geschrieben: ``-Recurse`` kann
#: vor *oder* nach dem Pfad stehen, und ``del`` akzeptiert beliebig viele Schalter
#: (``del /s /q C:\*``). Sonst rutschen die gefährlichsten Befehle durch.
FORBIDDEN: tuple[str, ...] = (
    # --- Datenträger / System ---
    r"\bformat\s+[a-z]:",                                # Format-Volume
    r"\bformat\.com\b",
    r"\bdiskpart\b",
    r"\bcipher\s+/w",                                   # freien Speicher überschreiben
    r"\bvssadmin\s+delete\s+shadows",
    r"\bbcdedit\b[^\r\n]*\b(?:recoveryenabled\s+no|bootstatuspolicy\s+ignoreallfailures)",
    # --- Löschen auf Laufwerkswurzel ---
    r"\b(?:rd|rmdir)\s+(?:/[a-z]+\s+)*[a-z]:[\\/]?\s*(?:$|[&|;])",
    r"\bdel\b[^\r\n]*?[a-z]:[\\/]\*",                    # del /s /q C:\*
    r"\brm\s+(?:-[a-zA-Z]+\s+)*[/~]\s*(?:$|[;&|])",     # rm -rf /
    r"\brm\s+(?:-[a-zA-Z]+\s+)*[a-z]:[\\/]",             # rm -rf C:\
    r"\brmtree\b[^\r\n]*?[\"'][a-z]:[\\/]+[\"']",        # shutil.rmtree('C:/')
    r"\brmtree\b[^\r\n]*?[\"'][/~][\"']",                # shutil.rmtree('/')
    # --- Rekursives Löschen an Systemorten (beide Argumentreihenfolgen) ---
    r"\bRemove-Item\b[^\r\n]*[A-Za-z]:[\\/][\"']?\s*(?:$|[;|])",
    r"\bRemove-Item\b[^\r\n]*-Recurse[^\r\n]*(?:Windows|SystemRoot|Program\s?Files|ProgramData|\$env:|%[A-Za-z]+%)",
    r"\bRemove-Item\b[^\r\n]*(?:Windows|SystemRoot|Program\s?Files|ProgramData)[^\r\n]*-Recurse",
    # --- PowerShell-/Skript-Ausführung ---
    r"\bSet-ExecutionPolicy\b[^\r\n]*\bUnrestricted\b",
    r"\b(?:Invoke-Expression|\biex)\b",
    # --- Persistenz / Autostart ---
    r"\breg\s+add\b[^\r\n]*\\Run(?:Once)?\b",
    r"\bNew-ItemProperty\b[^\r\n]*\\Run(?:Once)?\b",
    # --- Systemzustand ---
    r"\b(?:shutdown|stop-computer|restart-computer)\b",
    r":\(\)\s*\{\s*:\|:&\s*\};:",                       # Fork-Bombe
)

_COMPILED_FORBIDDEN = tuple(re.compile(p, re.IGNORECASE) for p in FORBIDDEN)


@dataclass(frozen=True)
class Decision:
    """Ergebnis einer Sicherheitsprüfung."""

    allowed: bool
    reason: str = ""

    def __bool__(self) -> bool:  # pragma: no cover - Bequemlichkeit
        return self.allowed


def find_forbidden(text: str, extra_patterns: tuple[str, ...] = ()) -> str | None:
    """Gibt das erste passende gesperrte Muster zurück, sonst ``None``."""
    patterns = (*_COMPILED_FORBIDDEN, *(re.compile(p, re.IGNORECASE) for p in extra_patterns))
    for pattern in patterns:
        if pattern.search(text):
            return pattern.pattern
    return None


def check_not_forbidden(text: str, cfg: Config, what: str = "Code") -> None:
    """Wirft :class:`ForbiddenCommand`, wenn ``text`` ein Sperrmuster enthält."""
    hit = find_forbidden(text, tuple(cfg.forbidden_patterns))
    if hit:
        raise ForbiddenCommand(
            f"{what} abgelehnt: gesperrtes Muster {hit!r}. "
            "Dies gilt auch im Modus safety_mode='auto' und lässt sich nicht umgehen."
        )


def require_confirm(confirm: bool, cfg: Config, action: str, detail: str = "") -> None:
    """Erzwingt eine explizite Bestätigung für destruktive Aktionen.

    Im Modus ``safety_mode="auto"`` ist keine Bestätigung nötig – das ist der
    Zweck des umschaltbaren Modus. Die Aufrufer sollten ``detail`` mitgeben,
    damit die KI (und der Mensch beim Debuggen) sieht, was gleich passiert.
    """
    if not cfg.requires_confirmation or confirm:
        return
    suffix = f" ({detail})" if detail else ""
    raise ConfirmationRequired(
        f"{action}{suffix} ist eine destruktive Aktion. "
        "Setze confirm=True, um sie auszuführen, oder wechsle die "
        "Konfiguration auf safety_mode='auto'."
    )


def confirm_arg_help() -> str:
    """Text für die Tool-Beschreibungen im MCP-Server."""
    return (
        "Setze True, um die Aktion auch im Sicherheitsmodus 'confirm' auszuführen."
    )