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
# Linux — lxsession autostart (Raspberry Pi OS)
# Manages ~/.config/lxsession/LXDE-pi/autostart:
#   - seeds from the system file so other desktop items are preserved
#   - strips @lxpanel so the taskbar does not appear
#   - adds the autodash start entry
# ---------------------------------------------------------------------------

_LXSESSION_DIR  = Path.home() / ".config" / "lxsession" / "rpd-x"
_LXSESSION_FILE = _LXSESSION_DIR / "autostart"
_LXSESSION_SYS  = Path("/etc/xdg/lxsession/rpd-x/autostart")
_LXSESSION_MARK = "# autodash"

# XDG files written by a previous version of this code — removed on enable/disable
_XDG_AUTOSTART_DIR  = Path.home() / ".config" / "autostart"
_XDG_LEGACY_FILES   = [
    _XDG_AUTOSTART_DIR / "autodash.desktop",
    _XDG_AUTOSTART_DIR / "lxpanel.desktop",
]


def _lxsession_entry() -> str:
    return f"@lxterminal -e python3 {_SCRIPT}"


def _linux_check() -> bool:
    if not _LXSESSION_FILE.exists():
        return False
    try:
        return _LXSESSION_MARK in _LXSESSION_FILE.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def _linux_enable() -> None:
    for f in _XDG_LEGACY_FILES:
        f.unlink(missing_ok=True)

    if _LXSESSION_FILE.exists():
        content = _LXSESSION_FILE.read_text(encoding="utf-8")
        if _LXSESSION_MARK in content:
            return
    elif _LXSESSION_SYS.exists():
        content = _LXSESSION_SYS.read_text(encoding="utf-8")
    else:
        content = ""

    # Strip lxpanel so the taskbar does not appear
    lines = [l for l in content.splitlines() if not l.strip().startswith("@lxpanel")]
    lines.append(f"\n{_LXSESSION_MARK}")
    lines.append(_lxsession_entry())
    _LXSESSION_DIR.mkdir(parents=True, exist_ok=True)
    _LXSESSION_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _linux_disable() -> None:
    for f in _XDG_LEGACY_FILES:
        f.unlink(missing_ok=True)

    if not _LXSESSION_FILE.exists():
        return
    try:
        lines  = _LXSESSION_FILE.read_text(encoding="utf-8").splitlines()
        result = []
        skip   = False
        for line in lines:
            if _LXSESSION_MARK in line:
                skip = True
                continue
            if skip:
                skip = False
                continue
            result.append(line)
        remaining = "\n".join(result).strip()
        if remaining:
            _LXSESSION_FILE.write_text(remaining + "\n", encoding="utf-8")
        else:
            _LXSESSION_FILE.unlink()
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
