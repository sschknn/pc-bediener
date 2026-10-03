"""Modul C – System-Wahrnehmung: Screenshots und Systemstatus.

Damit die KI Oberflächen visuell analysieren und Systemzustände abfragen kann.
"""

from __future__ import annotations

import os
import platform
import socket
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..config import Config


@dataclass
class ScreenshotInfo:
    """Ergebnis einer Screenshot-Aufnahme."""

    path: str
    width: int
    height: int
    mode: str
    size_bytes: int
    created: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def screenshot_dir(cfg: Config) -> Path:
    """Sicherstellt und liefert den Screenshot-Ordner."""
    base = Path(cfg.screenshot_dir)
    base.mkdir(parents=True, exist_ok=True)
    return base


def screenshot(
    cfg: Config,
    path: str | Path | None = None,
    region: tuple[int, int, int, int] | None = None,
    save: bool = True,
    max_width: int = 0,
) -> dict[str, Any]:
    """Nimmt einen Screenshot auf.

    Args:
        region: ``(links, oben, breite, hoehe)`` – Standard ist der ganze Bildschirm.
        path: Zielpfad; Standard ist ein Zeitstempel im Screenshot-Ordner.
        max_width: Skaliert das Bild auf diese Breite (0 = Original). Spart
            Token, wenn die KI nur ein Layout grob erkennen muss.
    """
    try:
        import pyautogui
    except Exception as exc:  # pragma: no cover - plattformabhängig
        raise RuntimeError("pyautogui fehlt – pip install pyautogui") from exc

    box = region or cfg.screenshot_max_region
    image = pyautogui.screenshot(region=box)

    if max_width and image.width > max_width:
        ratio = max_width / image.width
        image = image.resize((max_width, max(1, int(image.height * ratio))))

    info = None
    if save:
        target = Path(path) if path else screenshot_dir(cfg) / f"shot_{time.strftime('%Y%m%d_%H%M%S')}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target)
        info = ScreenshotInfo(
            path=str(target),
            width=image.width,
            height=image.height,
            mode=image.mode,
            size_bytes=target.stat().st_size,
            created=time.time(),
        )
    return {
        **(info.to_dict() if info else {}),
        "region": list(box) if box else None,
        "screen": {"width": image.width, "height": image.height},
    }


def system_status(cfg: Config, include_disk: bool = True, disk_path: str | None = None) -> dict[str, Any]:
    """Sammelt CPU-, RAM-, Disk- und System-Informationen."""
    import psutil

    vm = psutil.virtual_memory()
    disk_info: dict[str, Any] = {}
    if include_disk:
        try:
            target = disk_path or (cfg.exec_cwd or str(Path.home()))
            usage = psutil.disk_usage(target)
            disk_info = {
                "path": target,
                "total_gb": round(usage.total / 1_073_741_824, 1),
                "used_gb": round(usage.used / 1_073_741_824, 1),
                "free_gb": round(usage.free / 1_073_741_824, 1),
                "percent": usage.percent,
            }
        except (OSError, PermissionError) as exc:
            disk_info = {"error": str(exc)}

    battery: dict[str, Any] = {}
    if hasattr(psutil, "sensors_battery"):
        try:
            batt = psutil.sensors_battery()
            battery = (
                {"percent": round(batt.percent, 1), "plugged": batt.power_plugged, "seconds_left": batt.secsleft}
                if batt
                else {"present": False}
            )
        except Exception:
            battery = {"present": False}

    boot = psutil.boot_time()
    return {
        "hostname": socket.gethostname(),
        "os": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "cpu": {
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(logical=True),
            "percent": psutil.cpu_percent(interval=0.2),
            "per_core": psutil.cpu_percent(interval=0.2, percpu=True),
            "load_avg": list(getattr(os, "getloadavg", lambda: (0, 0, 0))()),
        },
        "memory": {
            "total_gb": round(vm.total / 1_073_741_824, 1),
            "available_gb": round(vm.available / 1_073_741_824, 1),
            "used_gb": round(vm.used / 1_073_741_824, 1),
            "percent": vm.percent,
        },
        "disk": disk_info,
        "battery": battery,
        "uptime_hours": round((time.time() - boot) / 3600, 2),
        "boot_time": boot,
        "process_count": len(psutil.pids()),
        "safety_mode": cfg.safety_mode,
        "cwd": os.getcwd(),
    }


def find_on_screen(cfg: Config, needle: str, region: tuple[int, int, int, int] | None = None, tolerance: int = 60) -> dict[str, Any]:
    """Sucht ein Bild auf dem Bildschirm und liefert dessen Position.

    Ermöglicht der KI, ein Element ohne manuelles Abschätzen der Koordinaten zu
    finden – der wichtigste Trick für zuverlässiges GUI-Automation.

    Args:
        needle: Pfad zu einem Bild (z.B. der Screenshot eines Buttons).
        tolerance: Farbabweichung 0-255; höher bedeutet großzügiger.
    """
    try:
        import pyautogui
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("pyautogui fehlt – pip install pyautogui") from exc

    source = Path(needle).expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"Suchbild nicht gefunden: {source}")

    box = region or cfg.screenshot_max_region
    try:
        location = pyautogui.locateCenterOnScreen(str(source), confidence=0.9, grayscale=True)
    except Exception:
        # Ohne opencv gibt es kein `confidence` – dann eben exakt vergleichen.
        location = pyautogui.locateCenterOnScreen(str(source), grayscale=True)

    if location is None:
        # Ein zweiter, toleranterer Versuch ohne Graustufen.
        location = pyautogui.locateCenterOnScreen(str(source), grayscale=False)

    if location is None:
        return {"found": False, "needle": str(source), "region": list(box) if box else None}
    return {
        "found": True,
        "needle": str(source),
        "x": int(location[0]),
        "y": int(location[1]),
        "center": [int(location[0]), int(location[1])],
        "tolerance": tolerance,
    }


def wait_for_image(
    cfg: Config, needle: str, timeout_s: float = 10.0, poll_interval: float = 0.5
) -> dict[str, Any]:
    """Wartet darauf, dass ein Bild auf dem Bildschirm erscheint.

    Nützlich nach einem Klick oder Start eines Programms: die KI wartet, bis
    das Ziel-Fenster wirklich da ist, statt zu raten.
    """
    deadline = time.monotonic() + timeout_s
    attempts = 0
    while time.monotonic() < deadline:
        attempts += 1
        result = find_on_screen(cfg, needle)
        if result.get("found"):
            return {**result, "attempts": attempts, "waited_s": round(timeout_s - (deadline - time.monotonic()), 2)}
        time.sleep(poll_interval)
    return {"found": False, "needle": needle, "timeout_s": timeout_s, "attempts": attempts}