"""Kommandozeile für den PC-Bediener.

    python -m pcbediener serve       # MCP-Server (für OpenCode)
    python -m pcbediener doctor      # Umgebung prüfen
    python -m pcbediener tools       # verfügbare MCP-Tools auflisten
    python -m pcbediener status      # Systemstatus als JSON
    python -m pcbediener shot        # Screenshot aufnehmen
    python -m pcbediener config ...  # Konfiguration ansehen/ändern
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from . import __version__, runtime
from .config import Config, default_config_path, load_config


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


# --- Befehle ----------------------------------------------------------------


def cmd_serve(args: argparse.Namespace) -> int:
    """Startet den MCP-Server auf stdio."""
    cfg = load_config(args.config)
    runtime.set_config(cfg)

    # Der Server schreibt auf stdout – Logs müssen nach stderr, sonst
    # beschädigt eine Log-Zeile das JSON-RPC-Protokoll.
    if args.verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)

    from .mcp_server import main as serve_main

    serve_main()
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Prüft, ob alle Bausteine für den Betrieb vorhanden sind."""
    checks: list[tuple[str, bool, str]] = []

    checks.append(("Python >= 3.11", sys.version_info >= (3, 11), sys.version.split()[0]))

    for module, purpose, required in [
        ("pyautogui", "Maus, Tastatur, Screenshot", True),
        ("psutil", "Prozesse, Systemstatus", True),
        ("PIL", "Bildverarbeitung", True),
        ("win32gui", "Fenstersteuerung", sys.platform == "win32"),
        ("mcp", "MCP-Server", True),
    ]:
        try:
            __import__(module)
            checks.append((module, True, purpose))
        except Exception as exc:
            checks.append((module, False, f"{purpose} – FEHLT ({exc})"))

    # Bildschirm wirklich erreichbar?
    try:
        from .modules import vision

        cfg = load_config(args.config)
        info = vision.screenshot(cfg, save=False)
        checks.append(
            (
                "Screenshot",
                True,
                f"{info['screen']['width']}x{info['screen']['height']} @ {info['screen']['width']}px",
            )
        )
    except Exception as exc:
        checks.append(("Screenshot", False, f"nicht möglich: {exc}"))

    try:
        from .modules import gui

        windows = gui.list_windows()
        checks.append(("Fensterzugriff", True, f"{len(windows)} sichtbare Fenster"))
    except Exception as exc:
        checks.append(("Fensterzugriff", False, str(exc)))

    ok = all(success for _, success, _ in checks)
    for name, success, detail in checks:
        mark = "OK  " if success else "FEHLT"
        print(f"[{mark}] {name:<18} {detail}")
    print()
    print(f"Config:      {runtime.get_config().source_path or default_config_path()}")
    print(f"Sicherheit:  {runtime.get_config().safety_mode}")
    print(f"Gesamt:      {'alle Prüfungen bestanden' if ok else 'PROBLEME GEFUNDEN'}")
    return 0 if ok else 1


def cmd_tools(args: argparse.Namespace) -> int:
    """Listet alle MCP-Tools mit Beschreibung."""
    from .mcp_server import server

    async def _list() -> list[Any]:
        return await server.list_tools()

    for tool in asyncio.run(_list()):
        annotation = ""
        if tool.annotations:
            if tool.annotations.read_only_hint:
                annotation = " [nur lesend]"
            elif tool.annotations.destructive_hint:
                annotation = " [DESTRUKTIV]"
            else:
                annotation = " [schreibend]"
        first_line = (tool.description or "").split("\n\n")[0]
        print(f"{tool.name}{annotation}\n    {first_line}")
    print(f"\n{len(asyncio.run(_list()))} Tools.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Gibt den Systemstatus als JSON aus."""
    from .modules import vision

    _print_json(vision.system_status(runtime.get_config()))
    return 0


def cmd_shot(args: argparse.Namespace) -> int:
    """Nimmt einen Screenshot auf."""
    from .modules import vision

    result = vision.screenshot(runtime.get_config(), args.path, max_width=args.max_width)
    _print_json(result)
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    """Konfiguration anzeigen, anlegen oder ändern."""
    cfg = runtime.get_config()

    if args.config_action == "show":
        _print_json(cfg.to_dict())
        return 0

    if args.config_action == "path":
        print(cfg.source_path or default_config_path())
        return 0

    if args.config_action == "init":
        target = cfg.save(args.config)
        print(f"Config geschrieben: {target}")
        _print_json(cfg.to_dict())
        return 0

    # set
    updates: dict[str, Any] = {}
    if args.safety_mode:
        updates["safety_mode"] = args.safety_mode
    if args.add_allowed_path:
        allowed = list(cfg.allowed_paths)
        allowed.extend(args.add_allowed_path)
        updates["allowed_paths"] = allowed
    if args.exec_timeout is not None:
        updates["exec_timeout"] = args.exec_timeout
    if args.forbidden:
        patterns = list(cfg.forbidden_patterns)
        patterns.extend(args.forbidden)
        updates["forbidden_patterns"] = patterns
    if args.set_cwd:
        updates["exec_cwd"] = args.set_cwd
    if args.set_screenshot_dir:
        updates["screenshot_dir"] = args.set_screenshot_dir

    if not updates:
        print("Nichts zu ändern. Optionen: --safety-mode, --add-allowed-path, "
              "--exec-timeout, --forbidden, --set-cwd, --set-screenshot-dir")
        return 2

    new_cfg = Config(**{**cfg.to_dict(), **updates})
    target = new_cfg.save(args.config)
    runtime.set_config(new_cfg)
    print(f"Config aktualisiert: {target}")
    _print_json(new_cfg.to_dict())
    return 0


# --- Parser -----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pcbediener",
        description="Lokale PC-Steuerung für eine KI (MCP-Server).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--version", action="version", version=f"pc-bediener {__version__}")
    parser.add_argument("--config", help="Pfad zur Config-JSON (Standard: %APPDATA%\\pcbediener\\config.json)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="MCP-Server auf stdio starten")
    p_serve.add_argument("-v", "--verbose", action="store_true", help="Debug-Logging nach stderr")
    p_serve.set_defaults(func=cmd_serve)

    p_doctor = sub.add_parser("doctor", help="Umgebung auf Laufbereitschaft prüfen")
    p_doctor.set_defaults(func=cmd_doctor)

    p_tools = sub.add_parser("tools", help="Alle MCP-Tools auflisten")
    p_tools.set_defaults(func=cmd_tools)

    p_status = sub.add_parser("status", help="Systemstatus als JSON")
    p_status.set_defaults(func=cmd_status)

    p_shot = sub.add_parser("shot", help="Screenshot aufnehmen")
    p_shot.add_argument("-p", "--path", help="Zielpfad der PNG-Datei")
    p_shot.add_argument("--max-width", type=int, default=0, help="Auf Breite skalieren")
    p_shot.set_defaults(func=cmd_shot)

    p_config = sub.add_parser("config", help="Konfiguration verwalten")
    cfg_sub = p_config.add_subparsers(dest="config_action", required=True)
    cfg_sub.add_parser("show", help="Aktuelle Konfiguration anzeigen").set_defaults()
    cfg_sub.add_parser("path", help="Pfad der Konfigurationsdatei").set_defaults()
    cfg_sub.add_parser("init", help="Standard-Konfiguration anlegen").set_defaults()

    p_set = cfg_sub.add_parser("set", help="Werte ändern und speichern")
    p_set.add_argument("--safety-mode", choices=["confirm", "auto"], help="Sicherheitsmodus umschalten")
    p_set.add_argument("--add-allowed-path", action="append", metavar="PFAD", help="Erlaubten Pfad hinzufügen")
    p_set.add_argument("--exec-timeout", type=int, help="Standard-Timeout für Codeausführung (Sekunden)")
    p_set.add_argument("--forbidden", action="append", metavar="REGEX", help="Zusätzliches gesperrtes Muster")
    p_set.add_argument("--set-cwd", metavar="PFAD", help="Arbeitsverzeichnis für ausgeführten Code")
    p_set.add_argument("--set-screenshot-dir", metavar="PFAD", help="Ordner für Screenshots")
    p_set.set_defaults()

    return parser


def main(argv: list[str] | None = None) -> int:
    # Die Windows-Konsole nutzt cp1252 – ohne das brechen Umlaute und Emoji.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve":
        return cmd_serve(args)

    # Alle anderen Befehle brauchen die aktive Konfiguration.
    try:
        runtime.set_config(load_config(args.config))
    except Exception as exc:
        print(f"Konfiguration ungültig: {exc}", file=sys.stderr)
        return 2

    if args.command == "config":
        # Subparser haben kein func gesetzt -> hier zuordnen.
        actions = {
            "show": cmd_config,
            "path": cmd_config,
            "init": cmd_config,
            "set": cmd_config,
        }
        func = actions[args.config_action]
    else:
        func = {
            "doctor": cmd_doctor,
            "tools": cmd_tools,
            "status": cmd_status,
            "shot": cmd_shot,
        }[args.command]

    try:
        return func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())