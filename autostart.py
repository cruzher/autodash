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
# Linux — LXDE-pi lxsession autostart (Raspberry Pi OS)
# ---------------------------------------------------------------------------

_LXSESSION_DIR  = Path.home() / ".config" / "lxsession" / "LXDE-pi"
_LXSESSION_FILE = _LXSESSION_DIR / "autostart"
_LXSESSION_SYS  = Path("/etc/xdg/lxsession/LXDE-pi/autostart")
_LXSESSION_MARK = "# autodash"


def _lxsession_entry(py: Path) -> str:
    return f"@lxterminal -e {py} {_SCRIPT}"


def _linux_check() -> bool:
    if not _LXSESSION_FILE.exists():
        return False
    try:
        return _LXSESSION_MARK in _LXSESSION_FILE.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def _linux_enable() -> None:
    py = _venv_python()
    _LXSESSION_DIR.mkdir(parents=True, exist_ok=True)

    if _LXSESSION_FILE.exists():
        content = _LXSESSION_FILE.read_text(encoding="utf-8")
        if _LXSESSION_MARK in content:
            return  # already present
    elif _LXSESSION_SYS.exists():
        # Seed from system file so desktop items (panel, file manager) are preserved.
        content = _LXSESSION_SYS.read_text(encoding="utf-8")
    else:
        content = ""

    entry = f"\n{_LXSESSION_MARK}\n{_lxsession_entry(py)}\n"
    _LXSESSION_FILE.write_text(content.rstrip("\n") + entry, encoding="utf-8")


def _linux_disable() -> None:
    if not _LXSESSION_FILE.exists():
        return
    try:
        lines  = _LXSESSION_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
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
        _LXSESSION_FILE.write_text("".join(result), encoding="utf-8")
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
