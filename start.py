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

OPENBOX_NS  = "http://openbox.org/3.4/rc"
OPENBOX_DIR = pathlib.Path.home() / ".config" / "openbox"
RC_FILE     = OPENBOX_DIR / "rpd-rc.xml"
RC_SYS      = pathlib.Path("/etc/xdg/openbox/rpd-rc.xml")
RC_ASSET    = DIR / "assets" / "rpd-rc.xml"


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


def ensure_pi_defaults() -> None:
    """On Raspberry Pi: enable autostart and fix Wayland (in that order)."""
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


def ensure_cec_utils() -> None:
    if not is_raspberry_pi():
        return
    if shutil.which("cec-client"):
        return
    if shutil.which("apt-get"):
        print("[..] Installing cec-utils ...")
        run("sudo", "apt-get", "install", "-y", "cec-utils", "-qq",
            stdout=subprocess.DEVNULL)
        print("[OK] cec-utils installed.")
    else:
        print("[WARN] cec-client not found — install manually: sudo apt install cec-utils")


def ensure_novnc() -> None:
    if not is_raspberry_pi():
        return
    if pathlib.Path("/usr/share/novnc").exists():
        return
    if shutil.which("apt-get"):
        print("[..] Installing novnc ...")
        run("sudo", "apt-get", "install", "-y", "novnc", "-qq",
            stdout=subprocess.DEVNULL)
        print("[OK] novnc installed.")
    else:
        print("[WARN] novnc not found — install manually: sudo apt install novnc")


def ensure_x11vnc() -> None:
    if not is_raspberry_pi():
        return
    if shutil.which("x11vnc"):
        return
    if shutil.which("apt-get"):
        print("[..] Installing x11vnc ...")
        run("sudo", "apt-get", "install", "-y", "x11vnc", "-qq",
            stdout=subprocess.DEVNULL)
        print("[OK] x11vnc installed.")
    else:
        print("[WARN] x11vnc not found — install manually: sudo apt install x11vnc")


def ensure_xmlstarlet() -> None:
    if shutil.which("xmlstarlet"):
        return
    if shutil.which("apt-get"):
        print("[..] Installing xmlstarlet ...")
        run("sudo", "apt-get", "install", "-y", "xmlstarlet", "-qq",
            stdout=subprocess.DEVNULL)
        print("[OK] xmlstarlet installed.")
    else:
        print("[WARN] xmlstarlet not found — install manually: sudo apt install xmlstarlet")


def ensure_openbox_config() -> None:
    """On Raspberry Pi: seed ~/.config/openbox/rpd-rc.xml if missing."""
    if not is_raspberry_pi():
        return
    if RC_FILE.exists():
        return
    OPENBOX_DIR.mkdir(parents=True, exist_ok=True)
    if RC_SYS.exists():
        shutil.copyfile(RC_SYS, RC_FILE)
        print(f"[OK] Seeded {RC_FILE} from {RC_SYS}.")
    elif RC_ASSET.exists():
        shutil.copyfile(RC_ASSET, RC_FILE)
        print(f"[WARN] {RC_SYS} not found — seeded {RC_FILE} from bundled fallback "
              f"({RC_ASSET.relative_to(DIR)}); some stock openbox settings may be missing.")
    else:
        print(f"[WARN] No openbox rc.xml source found ({RC_SYS} or "
              f"{RC_ASSET.relative_to(DIR)}) — cannot seed openbox config.")


def _xmlstarlet_count(xpath: str) -> int:
    result = run("xmlstarlet", "sel", "-N", f"ob={OPENBOX_NS}",
                 "-t", "-v", f"count({xpath})",
                 str(RC_FILE), capture_output=True, text=True)
    return int(result.stdout.strip() or "0")


def _xmlstarlet_edit(*ed_args: str) -> None:
    result = run("xmlstarlet", "ed", "-P", "-N", f"ob={OPENBOX_NS}", *ed_args,
                 str(RC_FILE), capture_output=True, text=True)
    if not result.stdout.strip():
        raise RuntimeError("xmlstarlet produced empty output")
    tmp = RC_FILE.with_suffix(RC_FILE.suffix + ".tmp")
    tmp.write_text(result.stdout, encoding="utf-8")
    tmp.replace(RC_FILE)


def reload_openbox() -> None:
    if not shutil.which("openbox"):
        return
    env = dict(os.environ, DISPLAY=os.environ.get("DISPLAY", ":0"))
    result = run("openbox", "--reconfigure", "--config-file", str(RC_FILE),
                 env=env, check=False,
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode == 0:
        print("[OK] openbox reconfigured.")
    else:
        print("[WARN] openbox --reconfigure failed (openbox may not be running yet) — "
              "the change will take effect next time openbox starts.")


def ensure_openbox_no_decor() -> None:
    """On Raspberry Pi: disable window decorations globally in openbox."""
    if not is_raspberry_pi():
        return
    if not RC_FILE.exists():
        return
    if not shutil.which("xmlstarlet"):
        print("[WARN] xmlstarlet not found — cannot disable window decorations; "
              "install manually: sudo apt install xmlstarlet")
        return

    try:
        if _xmlstarlet_count(
            "/ob:openbox_config/ob:applications/"
            "ob:application[@name='*'][@class='*'][ob:decor='no']"
        ) > 0:
            return

        apps_exist = _xmlstarlet_count("/ob:openbox_config/ob:applications") > 0

        print("[..] Disabling window decorations in openbox ...")
        if apps_exist:
            apps_xpath = "/ob:openbox_config/ob:applications"
            ed_args = []
        else:
            apps_xpath = "/ob:openbox_config/ob:applications[last()]"
            ed_args = ["-s", "/ob:openbox_config",
                       "-t", "elem", "-n", "ob:applications", "-v", ""]

        ed_args += ["-s", apps_xpath, "-t", "elem", "-n", "ob:application", "-v", ""]
        app_xpath = f"{apps_xpath}/ob:application[last()]"
        ed_args += [
            "-s", app_xpath, "-t", "attr", "-n", "name",  "-v", "*",
            "-s", app_xpath, "-t", "attr", "-n", "class", "-v", "*",
            "-s", app_xpath, "-t", "elem", "-n", "ob:decor", "-v", "no",
        ]
        _xmlstarlet_edit(*ed_args)
        print("[OK] Window decorations disabled.")
    except (subprocess.CalledProcessError, OSError, RuntimeError) as exc:
        print(f"[WARN] Could not patch {RC_FILE}: {exc}")
        return

    reload_openbox()


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
        ensure_pi_defaults()
        ensure_xdotool()
        ensure_cec_utils()
        ensure_novnc()
        ensure_x11vnc()
        ensure_xmlstarlet()
        ensure_openbox_config()
        ensure_openbox_no_decor()
    venv_created  = ensure_venv()
    deps_updated  = install_deps(venv_created)
    install_playwright(deps_updated)
    launch_monitor()


if __name__ == "__main__":
    if IS_WINDOWS and sys.stdout is None:
        _log = open(DIR / "autostart.log", "a", encoding="utf-8")
        sys.stdout = _log
        sys.stderr = _log
    main()
