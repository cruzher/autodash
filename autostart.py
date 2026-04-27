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
# Linux — systemd user service (primary) + XDG autostart fallback
# ---------------------------------------------------------------------------

_SERVICE_DIR  = Path.home() / ".config" / "systemd" / "user"
_SERVICE_FILE = _SERVICE_DIR / "autodash.service"
_DESKTOP      = Path.home() / ".config" / "autostart" / "autodash.desktop"


def _linux_check() -> bool:
    return _SERVICE_FILE.exists() or _DESKTOP.exists()


def _linux_enable() -> None:
    py = _venv_python()

    # Try systemd user service first — reliable regardless of desktop environment.
    try:
        _SERVICE_DIR.mkdir(parents=True, exist_ok=True)
        _SERVICE_FILE.write_text(
            "[Unit]\n"
            "Description=autodash dashboard monitor\n\n"
            "[Service]\n"
            "Type=simple\n"
            f"ExecStart={py} {_SCRIPT}\n"
            "Restart=on-failure\n"
            "RestartSec=5\n"
            "Environment=DISPLAY=:0\n\n"
            "[Install]\n"
            "WantedBy=default.target\n",
            encoding="utf-8",
        )
        r1 = subprocess.run(
            ["systemctl", "--user", "daemon-reload"], capture_output=True
        )
        r2 = subprocess.run(
            ["systemctl", "--user", "enable", "autodash.service"], capture_output=True
        )
        if r1.returncode == 0 and r2.returncode == 0:
            return
    except Exception:
        pass

    # Fallback: XDG autostart .desktop (lxsession-compatible).
    _DESKTOP.parent.mkdir(parents=True, exist_ok=True)
    _DESKTOP.write_text(
        "[Desktop Entry]\n"
        "Version=1.0\n"
        "Type=Application\n"
        "Name=autodash\n"
        f"Exec={py} {_SCRIPT}\n"
        "Hidden=false\n"
        "NoDisplay=false\n"
        "X-GNOME-Autostart-enabled=true\n",
        encoding="utf-8",
    )


def _linux_disable() -> None:
    subprocess.run(
        ["systemctl", "--user", "disable", "autodash.service"],
        check=False, capture_output=True,
    )
    if _SERVICE_FILE.exists():
        _SERVICE_FILE.unlink()
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
