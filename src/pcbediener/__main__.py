"""Ermöglicht ``python -m pcbediener ...``."""

from __future__ import annotations

from .cli import main

raise SystemExit(main())