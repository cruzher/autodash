"""Platform-specific autostart configuration for autodash."""

import getpass
import platform
import shutil
import subprocess
from pathlib import Path

_DIR    = Path(__file__).parent
_SCRIPT = _DIR / "start.py"
_SYSTEM = platform.system()


def _venv_python() -> Path:
    if _SYSTEM == "Windows":
        return _DIR / ".venv" / "Scripts" / "python.exe"
    return _DIR / ".venv" / "bin" / "python"


def supported() -> bool:
    return _SYSTEM in ("Windows", "Linux")


# ---------------------------------------------------------------------------
# Windows — Registry (HKCU Run key, no admin rights needed)
# ---------------------------------------------------------------------------

_REG_RUN  = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
_REG_NAME = "autodash"


def _system_pythonw() -> Path:
    """Return the pythonw.exe from the base Python that created the venv.

    start.py is a bootstrap script that manages the venv itself, so it must
    run with the system Python rather than the venv's own interpreter.
    pyvenv.cfg always records the base interpreter's home directory.
    """
    cfg = _DIR / ".venv" / "pyvenv.cfg"
    try:
        for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.lower().startswith("home"):
                home = Path(line.split("=", 1)[1].strip())
                pythonw = home / "pythonw.exe"
                if pythonw.exists():
                    return pythonw
                python = home / "python.exe"
                if python.exists():
                    return python
    except OSError:
        pass
    import sys
    return Path(sys.executable)


def _win_check() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_RUN) as key:
            winreg.QueryValueEx(key, _REG_NAME)
            return True
    except OSError:
        return False


def _win_enable() -> None:
    import winreg
    py  = _system_pythonw()
    cmd = f'"{py}" "{_SCRIPT}"'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_RUN, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, _REG_NAME, 0, winreg.REG_SZ, cmd)


def _win_disable() -> None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_RUN, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _REG_NAME)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Linux — lxsession (taskbar) + systemd --user service (launching autodash)
#
# The taskbar is stripped via ~/.config/lxsession/rpd-x/autostart, seeded from
# the system file so other desktop items are preserved. Launching autodash
# itself is handled by a systemd --user unit rather than an lxsession autostart
# entry, so it runs supervised (auto-restart, journalctl logs) instead of
# inside a visible lxterminal window. The unit still runs inside the pi user's
# graphical login session (desktop autologin is unchanged) so it inherits that
# session's X11 display — DISPLAY/XAUTHORITY are set explicitly in the unit
# rather than relied on, matching the defaults used elsewhere in this codebase.
# ---------------------------------------------------------------------------

_LXSESSION_DIR  = Path.home() / ".config" / "lxsession" / "rpd-x"
_LXSESSION_FILE = _LXSESSION_DIR / "autostart"
_LXSESSION_SYS  = Path("/etc/xdg/lxsession/rpd-x/autostart")

_SYSTEMD_USER_DIR  = Path.home() / ".config" / "systemd" / "user"
_SYSTEMD_UNIT_FILE = _SYSTEMD_USER_DIR / "autodash.service"
_SYSTEMD_UNIT_NAME = "autodash.service"

# XDG/lxsession files written by previous versions of this code — removed on enable/disable
_XDG_AUTOSTART_DIR  = Path.home() / ".config" / "autostart"
_XDG_LEGACY_FILES   = [
    _XDG_AUTOSTART_DIR / "autodash.desktop",
    _XDG_AUTOSTART_DIR / "lxpanel.desktop",
]


def _systemctl_user(*args, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], **kw)


def _unit_contents() -> str:
    python3 = shutil.which("python3") or "/usr/bin/python3"
    return (
        "[Unit]\n"
        "Description=autodash\n"
        "After=graphical-session.target\n"
        "PartOf=graphical-session.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory={_DIR}\n"
        "Environment=DISPLAY=:0\n"
        "Environment=XAUTHORITY=%h/.Xauthority\n"
        f"ExecStart={python3} {_SCRIPT}\n"
        "Restart=on-failure\n"
        "RestartSec=3\n"
        # start.py may need to create a venv and download Chromium on first
        # run, which can take several minutes on a Pi — never time that out.
        "TimeoutStartSec=0\n"
        "\n"
        "[Install]\n"
        "WantedBy=graphical-session.target\n"
    )


def _strip_lxpanel() -> None:
    """Remove @lxpanel from the lxsession autostart file so the taskbar does not appear."""
    if _LXSESSION_FILE.exists():
        content = _LXSESSION_FILE.read_text(encoding="utf-8")
    elif _LXSESSION_SYS.exists():
        content = _LXSESSION_SYS.read_text(encoding="utf-8")
    else:
        return

    lines = [l for l in content.splitlines() if not l.strip().startswith("@lxpanel")]
    _LXSESSION_DIR.mkdir(parents=True, exist_ok=True)
    _LXSESSION_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _linux_check() -> bool:
    if not _SYSTEMD_UNIT_FILE.exists():
        return False
    try:
        result = _systemctl_user("is-enabled", _SYSTEMD_UNIT_NAME,
                                  check=False, capture_output=True, text=True)
        return result.stdout.strip() == "enabled"
    except OSError:
        return False


def _linux_enable() -> None:
    for f in _XDG_LEGACY_FILES:
        f.unlink(missing_ok=True)

    _strip_lxpanel()

    _SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)
    _SYSTEMD_UNIT_FILE.write_text(_unit_contents(), encoding="utf-8")

    # Not "--now": enabling only takes effect on the next login, same as the
    # old lxsession-entry approach. Starting it immediately here would race
    # with *this* process, which is itself mid-bootstrap the first time this
    # runs (ensure_pi_defaults -> enable() happens before venv setup and
    # launch_monitor()) — two autodash instances would fight over port 8080.
    _systemctl_user("daemon-reload", check=False)
    _systemctl_user("enable", _SYSTEMD_UNIT_NAME, check=False)

    # Best-effort: let the user's systemd instance keep running across brief
    # session hiccups. Not required for the desktop-autologin case, since a
    # real login session already starts one, but cheap insurance.
    try:
        subprocess.run(["sudo", "loginctl", "enable-linger", getpass.getuser()], check=False)
    except OSError:
        pass


def _linux_disable() -> None:
    for f in _XDG_LEGACY_FILES:
        f.unlink(missing_ok=True)

    # Not "--now" — see the note in _linux_enable(). Disabling from the web UI
    # is itself served by the running instance; stopping it immediately would
    # kill that request mid-flight instead of just taking effect next login.
    _systemctl_user("disable", _SYSTEMD_UNIT_NAME, check=False)
    _SYSTEMD_UNIT_FILE.unlink(missing_ok=True)
    _systemctl_user("daemon-reload", check=False)


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
