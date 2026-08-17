#!/usr/bin/env python3
"""Cross-platform setup and launcher for autodash."""

import hashlib
import os
import pathlib
import shutil
import subprocess
import sys
import time

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

OPENBOX_DIR = pathlib.Path.home() / ".config" / "openbox"
RC_FILE     = OPENBOX_DIR / "rpd-rc.xml"
RC_SYS      = pathlib.Path("/etc/xdg/openbox/rpd-rc.xml")
RC_ASSET    = DIR / "assets" / "rpd-rc.xml"

TERMINAL_HEIGHT       = 100  # px — height of the console strip
TERMINAL_TOP_OFFSET   = 33   # px — shifted above the top edge to hide lxterminal's menu bar
TERMINAL_WIDTH_EXTRA  = 15   # px — extra width hanging off the right edge to hide the scrollbar


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


def ensure_terminal_position() -> None:
    """On Raspberry Pi: pin this lxterminal window to a strip along the top of the screen.

    Uses the same xdotool-based tools display.py uses to position the kiosk's
    Chromium windows, rather than a separate mechanism. The window is shifted
    above the top edge to crop off lxterminal's menu bar, and made wider than
    the screen to push its scrollbar past the right edge.
    """
    if not is_raspberry_pi():
        return
    import display
    if not display.HAS_XDOTOOL:
        return

    wid  = None
    size = None
    for _ in range(10):
        wid  = wid  or display.find_window_by_class("lxterminal")
        size = size or display.get_screen_size()
        if wid and size:
            break
        time.sleep(0.3)
    if not wid or not size:
        print("[WARN] Could not locate lxterminal window — skipping repositioning.")
        return

    screen_width, _screen_height = size
    x, y     = 0, -TERMINAL_TOP_OFFSET
    width    = screen_width + TERMINAL_WIDTH_EXTRA
    display.run_cmd(["xdotool", "windowmove", "--sync", wid, str(x), str(y)])
    display.run_cmd(["xdotool", "windowsize", "--sync", wid, str(width), str(TERMINAL_HEIGHT)])
    print(f"[OK] Terminal window pinned to top strip ({width}x{TERMINAL_HEIGHT} at {x},{y}).")


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


def _pcmanfm_desktop_confs() -> list[pathlib.Path]:
    """Locate pcmanfm's per-profile desktop-items-0.conf file(s).

    The profile directory name (e.g. "default", "LXDE-pi") varies by OS image,
    so search for whatever is already there instead of assuming one.
    """
    base = pathlib.Path.home() / ".config" / "pcmanfm"
    found = sorted(base.glob("*/desktop-items-0.conf")) if base.exists() else []
    return found or [base / "default" / "desktop-items-0.conf"]


def _set_ini_keys(path: pathlib.Path, updates: dict) -> None:
    """Update (or append) flat key=value lines in an ini-style file, leaving everything else intact."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else ["[*]"]
    seen = set()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if "=" not in stripped or stripped.startswith(("#", "[")):
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            lines[i] = f"{key}={updates[key]}"
            seen.add(key)
    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_desktop_appearance() -> None:
    """Set the kiosk wallpaper and hide desktop icons (Raspberry Pi only)."""
    if not is_raspberry_pi():
        return
    wallpaper = DIR / "assets" / "Logo_dark.png"
    if not wallpaper.exists():
        return

    # Point pcmanfm's desktop folder at an empty directory so stray files a
    # user drops on the real ~/Desktop never show up as icons.
    empty_desktop = pathlib.Path.home() / ".config" / "autodash" / "empty-desktop"
    empty_desktop.mkdir(parents=True, exist_ok=True)

    updates = {
        "wallpaper":      str(wallpaper),
        "wallpaper_mode": "fit",
        "desktop_bg":     "#020414",
        "show_home":      "0",
        "show_trash":     "0",
        "show_mounts":    "0",
        "folder":         str(empty_desktop),
    }
    for conf in _pcmanfm_desktop_confs():
        try:
            _set_ini_keys(conf, updates)
        except OSError as exc:
            print(f"[WARN] Could not update {conf}: {exc}")
            return

    # Best-effort: apply immediately if pcmanfm's desktop manager is already
    # running, so a reboot/relogin isn't required to see the change.
    if shutil.which("pcmanfm"):
        run("pcmanfm", "--reconfigure", check=False)


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


# rpd-rc.xml declares a default xmlns, which xmlstarlet can only match via a
# bound "-N" prefix — but that same prefix can't be used to *create* elements
# (xmlstarlet has no way to assign a new node to a namespace via "-n"; it
# creates a literal, unnamespaced node named e.g. "ob:application" instead,
# which then fails to match any later "ob:"-bound XPath). Sidestepping the
# whole issue with local-name() lets every query/insert use the same,
# consistently-matching XPath regardless of namespace.
_OB_ROOT = "/*[local-name()='openbox_config']"
_OB_APPS = f"{_OB_ROOT}/*[local-name()='applications']"
_OB_NO_DECOR_RULE = (
    f"{_OB_APPS}/*[local-name()='application']"
    "[@name='*'][@class='*']"
    "[*[local-name()='decor']='no']"
)


def _xmlstarlet_count(xpath: str) -> int:
    result = run("xmlstarlet", "sel", "-t", "-v", f"count({xpath})",
                 str(RC_FILE), capture_output=True, text=True)
    return int(result.stdout.strip() or "0")


def _xmlstarlet_edit(*ed_args: str) -> None:
    result = run("xmlstarlet", "ed", "-P", *ed_args,
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
        if _xmlstarlet_count(_OB_NO_DECOR_RULE) > 0:
            return

        apps_exist = _xmlstarlet_count(_OB_APPS) > 0

        print("[..] Disabling window decorations in openbox ...")
        if apps_exist:
            apps_xpath = _OB_APPS
            ed_args = []
        else:
            apps_xpath = f"{_OB_APPS}[last()]"
            ed_args = ["-s", _OB_ROOT, "-t", "elem", "-n", "applications", "-v", ""]

        ed_args += ["-s", apps_xpath, "-t", "elem", "-n", "application", "-v", ""]
        app_xpath = f"{apps_xpath}/*[local-name()='application'][last()]"
        ed_args += [
            "-s", app_xpath, "-t", "attr", "-n", "name",  "-v", "*",
            "-s", app_xpath, "-t", "attr", "-n", "class", "-v", "*",
            "-s", app_xpath, "-t", "elem", "-n", "decor", "-v", "no",
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
        ensure_terminal_position()
        ensure_cec_utils()
        ensure_novnc()
        ensure_x11vnc()
        ensure_xmlstarlet()
        ensure_openbox_config()
        ensure_openbox_no_decor()
        ensure_desktop_appearance()
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
