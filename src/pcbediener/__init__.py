"""PC-Bediener – lokale Steuerung des Rechners durch eine KI.

Gibt einer KI über MCP vier Kern-Module:

* **A** ``exec``    – Code-Ausführung (Python, PowerShell, Shell)
* **B** ``gui``/``proc`` – Maus, Tastatur, Fenster, Prozesse
* **C** ``vision`` – Screenshots und Systemstatus
* **D** ``files``  – Dateisystem-Zugriff innerhalb erlaubter Pfade

Beispiel::

    from pcbediener import runtime
    from pcbediener.modules import vision

    vision.screenshot(runtime.get_config())
"""

from __future__ import annotations

__version__ = "0.1.0"

from .config import Config, load_config
from .safety import (
    ConfirmationRequired,
    ForbiddenCommand,
    PathNotAllowed,
    SafetyError,
)

__all__ = [
    "__version__",
    "Config",
    "load_config",
    "ConfirmationRequired",
    "ForbiddenCommand",
    "PathNotAllowed",
    "SafetyError",
]