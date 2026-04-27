import asyncio
import logging
import os
import platform
import shutil
import subprocess

IS_LINUX    = platform.system() == "Linux"
HAS_XDOTOOL = IS_LINUX and shutil.which("xdotool") is not None
HAS_WMCTRL  = IS_LINUX and shutil.which("wmctrl") is not None

_display_sleep_disabled = False


def check_tools():
    """Log warnings for missing Linux window-management tools."""
    if IS_LINUX:
        if not HAS_XDOTOOL:
            logging.warning("xdotool not found. Install: sudo apt install xdotool")
        if not HAS_WMCTRL:
            logging.warning("wmctrl not found. Install: sudo apt install wmctrl")


def get_env():
    env = os.environ.copy()
    if "DISPLAY" not in env:
        env["DISPLAY"] = ":0"
    return env


def run_cmd(cmd, timeout=5):
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=get_env(),
    )


def disable_display_sleep():
    global _display_sleep_disabled
    if _display_sleep_disabled:
        return
    _display_sleep_disabled = True
    if IS_LINUX and shutil.which("xset"):
        for args in (
            ["xset", "s", "off"],
            ["xset", "s", "0", "0"],
            ["xset", "-dpms"],
            ["xset", "s", "noblank"],
        ):
            r = run_cmd(args)
            if r.returncode != 0:
                logging.warning("xset command failed: %s", " ".join(args))
        logging.info("Display sleep disabled via xset.")
    elif platform.system() == "Windows":
        import ctypes
        ES_CONTINUOUS       = 0x80000000
        ES_DISPLAY_REQUIRED = 0x00000002
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_DISPLAY_REQUIRED
        )
        logging.info("Display sleep disabled via SetThreadExecutionState.")


def wake_display():
    """Force the display on after it may have gone to sleep."""
    if IS_LINUX and shutil.which("xset"):
        r = run_cmd(["xset", "dpms", "force", "on"])
        if r.returncode != 0:
            logging.warning("xset dpms force on failed.")
    elif platform.system() == "Windows":
        import ctypes
        ctypes.windll.user32.mouse_event(0x0001, 0, 0, 0, 0)


def enable_display_sleep():
    global _display_sleep_disabled
    if not _display_sleep_disabled:
        return
    _display_sleep_disabled = False
    if IS_LINUX and shutil.which("xset"):
        for args in (
            ["xset", "s", "on"],
            ["xset", "+dpms"],
            ["xset", "s", "blank"],
        ):
            r = run_cmd(args)
            if r.returncode != 0:
                logging.warning("xset command failed: %s", " ".join(args))
        logging.info("Display sleep re-enabled via xset.")
    elif platform.system() == "Windows":
        import ctypes
        ES_CONTINUOUS = 0x80000000
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        logging.info("Display sleep re-enabled via SetThreadExecutionState.")


def find_window_id(title):
    if HAS_XDOTOOL:
        for search_arg, search_val in [
            ("--name",  title),
            ("--class", "chromium"),
            ("--class", "chrome"),
        ]:
            r = run_cmd(["xdotool", "search", search_arg, search_val])
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip().splitlines()[-1]
        r = run_cmd(["xdotool", "getactivewindow"])
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    if HAS_WMCTRL:
        r = run_cmd(["wmctrl", "-l"])
        if r.returncode == 0:
            for line in reversed(r.stdout.splitlines()):
                if "chromium" in line.lower() or title.lower() in line.lower():
                    return line.split()[0]
    return None


def get_window_geometry(wid):
    if not HAS_XDOTOOL:
        return None
    try:
        r = run_cmd(["xdotool", "getwindowgeometry", "--shell", wid])
        if r.returncode != 0:
            return None
        props = {}
        for line in r.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()
        x      = int(props.get("X",      0))
        y      = int(props.get("Y",      0))
        width  = int(props.get("WIDTH",  0))
        height = int(props.get("HEIGHT", 0))
        return x, y, width, height
    except Exception:
        return None


def force_window_geometry(cfg, wid, log):
    try:
        if HAS_WMCTRL:
            run_cmd(["wmctrl", "-i", "-r", wid, "-b",
                     "remove,maximized_vert,maximized_horz,fullscreen"])
            geom = f"0,{cfg.window_x},{cfg.window_y},{cfg.window_width},{cfg.window_height}"
            run_cmd(["wmctrl", "-i", "-r", wid, "-e", geom])
        if HAS_XDOTOOL:
            run_cmd(["xdotool", "windowfocus", "--sync", wid])
            run_cmd(["xdotool", "windowmove",  "--sync", wid,
                     str(cfg.window_x), str(cfg.window_y)])
            run_cmd(["xdotool", "windowsize",  "--sync", wid,
                     str(cfg.window_width), str(cfg.window_height)])
        log.info(
            "Window corrected to (%d,%d) %dx%d",
            cfg.window_x, cfg.window_y, cfg.window_width, cfg.window_height,
        )
        return True
    except subprocess.TimeoutExpired:
        log.warning("Window correction timed out.")
    except Exception as exc:
        log.warning("Window correction error: %s", exc)
    return False


async def fit_viewport_to_window(page):
    try:
        inner = await page.evaluate(
            "() => ({ width: window.innerWidth, height: window.innerHeight })"
        )
        await page.set_viewport_size({
            "width":  inner["width"],
            "height": inner["height"],
        })
    except Exception as exc:
        logging.getLogger("viewport").debug("fit_viewport_to_window (non-fatal): %s", exc)


async def position_window(cfg, page):
    if cfg.fullscreen:
        return
    if IS_LINUX:
        await asyncio.sleep(1.5)
        try:
            title = await page.title()
        except Exception:
            title = "chromium"
        wid = find_window_id(title)
        if wid:
            force_window_geometry(cfg, wid, logging.getLogger(cfg.name))
        else:
            logging.getLogger(cfg.name).warning(
                "Could not find window ID for initial positioning."
            )
    else:
        try:
            session = await page.context.new_cdp_session(page)
            result  = await session.send("Browser.getWindowForTarget")
            win_id  = result["windowId"]
            await session.send("Browser.setWindowBounds", {
                "windowId": win_id,
                "bounds": {
                    "left":   cfg.window_x,
                    "top":    cfg.window_y,
                    "width":  cfg.window_width,
                    "height": cfg.window_height,
                },
            })
            await session.detach()
        except Exception as exc:
            logging.getLogger(cfg.name).warning("CDP positioning failed: %s", exc)
    await asyncio.sleep(0.3)
    await fit_viewport_to_window(page)


async def display_keepalive():
    """Periodically reset the X11 screensaver timer to prevent blanking on Linux.
    Runs only when display sleep is currently disabled."""
    if not IS_LINUX or not shutil.which("xset"):
        return
    while True:
        await asyncio.sleep(50)
        if _display_sleep_disabled:
            run_cmd(["xset", "s", "reset"])
