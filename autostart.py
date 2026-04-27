"""Platform-specific autostart configuration for autodash."""

import platform
import subprocess
from pathlib import Path

_DIR    = Path(__file__).parent
_SCRIPT = _DIR / "start.py"
_SYSTEM = platform.system()


def _venv_python() -> Path:
    if _SYSTEM == "Windows":
        return _DIR / ".venv" / "Scripts" / "pythonw.exe"
    return _DIR / ".venv" / "bin" / "python"


def supported() -> bool:
    return _SYSTEM in ("Windows", "Linux")


# ---------------------------------------------------------------------------
# Windows — Scheduled Task
# ---------------------------------------------------------------------------

def _win_check() -> bool:
    r = subprocess.run(
        ["schtasks", "/query", "/tn", "autodash"],
        capture_output=True,
    )
    return r.returncode == 0


def _win_enable() -> None:
    py  = _venv_python()
    cmd = f'"{py}" "{_SCRIPT}"'
    subprocess.run(
        ["schtasks", "/create", "/tn", "autodash",
         "/tr", cmd, "/sc", "onlogon", "/f"],
        check=True, capture_output=True,
    )


def _win_disable() -> None:
    subprocess.run(
        ["schtasks", "/delete", "/tn", "autodash", "/f"],
        check=False, capture_output=True,
    )


# ---------------------------------------------------------------------------
# Linux — XDG autostart .desktop (lxsession-compatible)
# ---------------------------------------------------------------------------

_DESKTOP = Path.home() / ".config" / "autostart" / "autodash.desktop"


def _linux_check() -> bool:
    return _DESKTOP.exists()


def _linux_enable() -> None:
    _DESKTOP.parent.mkdir(parents=True, exist_ok=True)
    py = _venv_python()
    _DESKTOP.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=autodash\n"
        f"Exec={py} {_SCRIPT}\n"
        "Hidden=false\n"
        "NoDisplay=false\n"
        "X-GNOME-Autostart-enabled=true\n",
        encoding="utf-8",
    )


def _linux_disable() -> None:
    if _DESKTOP.exists():
        _DESKTOP.unlink()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_enabled() -> bool:
    if _SYSTEM == "Windows": return _win_check()
    if _SYSTEM == "Linux":   return _linux_check()
    return False


def enable() -> None:
    if _SYSTEM == "Windows": _win_enable()
    elif _SYSTEM == "Linux": _linux_enable()


def disable() -> None:
    if _SYSTEM == "Windows": _win_disable()
    elif _SYSTEM == "Linux": _linux_disable()
