#!/usr/bin/env python3
"""Cross-platform setup and launcher for autodash."""

import hashlib
import os
import pathlib
import shutil
import subprocess
import sys

IS_WINDOWS = sys.platform == "win32"
DIR        = pathlib.Path(__file__).parent
VENV       = DIR / ".venv"
REQS       = DIR / "requirements.txt"
HASH_FILE  = VENV / ".requirements-hash"
MONITOR    = DIR / "monitor.py"

PY         = VENV / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
PIP        = VENV / ("Scripts/pip.exe"    if IS_WINDOWS else "bin/pip")
PLAYWRIGHT = VENV / ("Scripts/playwright.exe" if IS_WINDOWS else "bin/playwright")
CHROMIUM_CACHE = (
    pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    if IS_WINDOWS else
    pathlib.Path.home() / ".cache/ms-playwright"
)


def banner(msg: str) -> None:
    print()
    print("=========================================")
    for line in msg.splitlines():
        print(f" {line}")
    print("=========================================")
    print()


def run(*args, check: bool = True, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(list(args), check=check, **kw)


def check_vcredist() -> None:
    import winreg
    key_path = r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64"
    installed = False
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as k:
            installed = winreg.QueryValueEx(k, "Installed")[0] == 1
    except OSError:
        pass
    if installed:
        return
    print("[WARN] Visual C++ Redistributable not found.")
    if shutil.which("winget"):
        print("[..] Installing Visual C++ Redistributable ...")
        run("winget", "install", "--id", "Microsoft.VCRedist.2015+.x64",
            "-e", "--silent", check=False)
        print("[OK] Visual C++ Redistributable installed.")
    else:
        print("      Install manually: https://aka.ms/vs/17/release/vc_redist.x64.exe")


def is_raspberry_pi() -> bool:
    try:
        model = pathlib.Path("/proc/device-tree/model").read_text(errors="ignore")
        return "raspberry pi" in model.lower()
    except OSError:
        return False


def is_wayland() -> bool:
    return (
        bool(os.environ.get("WAYLAND_DISPLAY")) or
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    )


def fix_wayland() -> None:
    """Switch the Pi session to X11 via raspi-config and prompt for reboot."""
    print("[..] Switching display server to X11 ...")
    result = run("sudo", "raspi-config", "nonint", "do_wayland", "W1", check=False)
    if result.returncode != 0:
        print("[WARN] Could not switch to X11 automatically.")
        print("       Run manually: sudo raspi-config  →  Advanced Options → Wayland → X11")
        return
    print("[OK] X11 configured.")
    print()
    print(" A reboot is required to apply the change.")
    print(" autodash will start automatically after reboot.")
    print()
    input(" Press Enter to reboot now, or Ctrl+C to reboot later ...")
    run("sudo", "reboot", check=False)
    sys.exit(0)


def ensure_pi_autostart() -> None:
    """On Raspberry Pi: enable autostart at login."""
    if not is_raspberry_pi():
        return

    import autostart
    if not autostart.is_enabled():
        print("[..] Raspberry Pi detected — enabling autostart ...")
        try:
            autostart.enable()
            print("[OK] autodash will start automatically after login.")
        except Exception as exc:
            print(f"[WARN] Could not enable autostart: {exc}")


def ensure_pi_display() -> None:
    """On Raspberry Pi: switch to X11 if Wayland is active. Call after all deps are installed."""
    if not is_raspberry_pi():
        return

    if is_wayland():
        banner(
            "Wayland detected — autodash requires X11.\n"
            "The display server will be switched to X11 now."
        )
        fix_wayland()


def ensure_xdotool() -> None:
    if shutil.which("xdotool"):
        return
    if shutil.which("apt-get"):
        print("[..] Installing xdotool ...")
        run("sudo", "apt-get", "install", "-y", "xdotool", "-qq",
            stdout=subprocess.DEVNULL)
        print("[OK] xdotool installed.")
    else:
        print("[WARN] xdotool not found — install manually: sudo apt install xdotool")


def ensure_venv() -> bool:
    activate = VENV / ("Scripts/Activate.ps1" if IS_WINDOWS else "bin/activate")
    if activate.exists():
        return False
    print("[..] Creating virtual environment ...")
    run(sys.executable, "-m", "venv", str(VENV))
    print("[OK] Virtual environment created.")
    return True


def install_deps(venv_created: bool) -> bool:
    current_hash = (
        hashlib.sha256(REQS.read_bytes()).hexdigest() if REQS.exists() else ""
    )
    stored_hash = HASH_FILE.read_text(encoding="ascii").strip() if HASH_FILE.exists() else ""

    if not venv_created and current_hash == stored_hash:
        return False

    print("[..] Installing Python dependencies ...")
    run(str(PY), "-m", "pip", "install", "--upgrade", "pip", "--quiet")
    if REQS.exists():
        run(str(PY), "-m", "pip", "install", "-r", str(REQS), "--quiet")
    else:
        run(str(PY), "-m", "pip", "install", "playwright", "--quiet")
    HASH_FILE.write_text(current_hash, encoding="ascii")
    print("[OK] Dependencies installed.")
    return True


def install_playwright(deps_updated: bool) -> None:
    chromium_installed = any(CHROMIUM_CACHE.glob("chromium-*"))
    if not deps_updated and chromium_installed:
        return
    if not IS_WINDOWS:
        print("[..] Installing Playwright system dependencies ...")
        result = run(str(PLAYWRIGHT), "install-deps", "chromium", check=False)
        if result.returncode == 0:
            print("[OK] System dependencies installed.")
        else:
            print("[WARN] Could not install system deps — run manually:")
            print(f"       sudo {PLAYWRIGHT} install-deps chromium")
    print("[..] Installing Chromium browser ...")
    run(str(PLAYWRIGHT), "install", "chromium")
    print("[OK] Chromium ready.")


def launch_monitor() -> None:
    banner("Starting monitor ...\nPress Ctrl+C to stop.")
    if IS_WINDOWS:
        proc = subprocess.Popen([str(PY), str(MONITOR)])
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.wait()
        sys.exit(proc.returncode)
    else:
        os.execv(str(PY), [str(PY), str(MONITOR)])


def main() -> None:
    banner("autodash")
    if IS_WINDOWS:
        check_vcredist()
    else:
        ensure_pi_autostart()
        ensure_xdotool()
    venv_created  = ensure_venv()
    deps_updated  = install_deps(venv_created)
    install_playwright(deps_updated)
    if not IS_WINDOWS:
        ensure_pi_display()
    launch_monitor()


if __name__ == "__main__":
    main()
