"""Die vier Kern-Module der lokalen PC-Steuerung.

A – Code-Ausführung (:mod:`exec`)
B – GUI- & Prozess-Steuerung (:mod:`gui`, :mod:`proc`)
C – System-Wahrnehmung (:mod:`vision`)
D – Dateisystem (:mod:`files`)
"""

from __future__ import annotations

from . import exec, files, flstudio, gui, proc, vision

__all__ = ["exec", "files", "flstudio", "gui", "proc", "vision"]