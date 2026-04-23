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
        ensure_xdotool()
    venv_created  = ensure_venv()
    deps_updated  = install_deps(venv_created)
    install_playwright(deps_updated)
    launch_monitor()


if __name__ == "__main__":
    main()
