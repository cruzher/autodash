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
# Linux — XDG autostart (works across all Raspberry Pi OS desktop sessions)
# ---------------------------------------------------------------------------

_XDG_AUTOSTART_DIR  = Path.home() / ".config" / "autostart"
_XDG_AUTOSTART_FILE = _XDG_AUTOSTART_DIR / "autodash.desktop"


def _desktop_entry(py: Path) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=autodash\n"
        f'Exec="{py}" "{_SCRIPT}"\n'
        "X-GNOME-Autostart-enabled=true\n"
    )


def _linux_check() -> bool:
    return _XDG_AUTOSTART_FILE.exists()


def _linux_enable() -> None:
    _XDG_AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
    _XDG_AUTOSTART_FILE.write_text(_desktop_entry(_venv_python()), encoding="utf-8")


def _linux_disable() -> None:
    try:
        _XDG_AUTOSTART_FILE.unlink(missing_ok=True)
    except OSError:
        pass


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
