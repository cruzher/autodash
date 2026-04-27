"""
monitor.py - Multi-Site Auto-Login Monitor using Playwright (Chromium)
"""

import asyncio
import threading
import pyotp
import datetime
import json
import logging
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Union
from urllib.parse import quote as _url_quote

from playwright.async_api import (
    async_playwright,
    Page,
    BrowserContext,
    Playwright,
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
)

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel
import uvicorn

from auth import (
    SESSION_TTL,
    check_credentials,
    create_session,
    create_user,
    invalidate_session,
    require_auth,
    user_exists,
    validate_session,
)
from config import SiteConfig, load_sites_json


class ClickRequest(BaseModel):
    x: float          # relative ratio 0.0–1.0
    y: float          # relative ratio 0.0–1.0
    monitor: int = 1  # mss monitor index (1 = first physical monitor)
    button: str = "left"  # "left" or "right"


class TypeRequest(BaseModel):
    text: str
    method: str = "paste"   # "paste" = clipboard ctrl+v, "type" = key-by-key
    send_enter: bool = False


class KeyRequest(BaseModel):
    key: Union[str, List[str]]


# ---- TIMING CONFIGURATION -----------------------------------------------

REFRESH_INTERVAL_SECONDS  = 600   # mutable — updated by settings API at runtime
CHECK_INTERVAL_SECONDS    = 30
RECONNECT_DELAY_SECONDS   = 5
POSITION_CHECK_SECONDS    = 10
POSITION_TOLERANCE_PX     = 5
SCHEDULE_CHECK_SECONDS    = 60

# ---- CONNECTIVITY -------------------------------------------------------

INTERNET_CHECK_HOST    = "8.8.8.8"
INTERNET_CHECK_PORT    = 53
INTERNET_CHECK_TIMEOUT = 3
SITE_CHECK_TIMEOUT     = 8

_OFFLINE_HTML_PATH          = Path(__file__).parent / "offline.html"
_OFFLINE_URL                = _OFFLINE_HTML_PATH.as_uri()

_NO_SCHEDULE_HTML_PATH      = Path(__file__).parent / "no_schedule.html"
_NO_SCHEDULE_URL            = _NO_SCHEDULE_HTML_PATH.as_uri()

_SITE_UNAVAILABLE_HTML_PATH = Path(__file__).parent / "site_unavailable.html"
_SITE_UNAVAILABLE_URL       = _SITE_UNAVAILABLE_HTML_PATH.as_uri()

_SITES_JSON_PATH    = Path(__file__).parent / "sites.json"
_SETTINGS_JSON_PATH = Path(__file__).parent / "settings.json"
_UI_HTML_PATH       = Path(__file__).parent / "ui.html"
_LOGIN_HTML_PATH    = Path(__file__).parent / "login.html"
_LOG_DIR  = Path(__file__).parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_LOG_PATH = _LOG_DIR / "autodash.log"

WEB_PORT = int(os.environ.get("WEB_PORT", 8080))

# Populated by main() — holds the live SiteMonitor instances so the web API
# can access their Playwright pages (e.g. for screenshots).
_monitors: list = []


def _load_sites() -> list:
    """Reload sites.json from disk and return list[SiteConfig]."""
    if not _SITES_JSON_PATH.exists():
        return []
    return load_sites_json(_SITES_JSON_PATH)


# ---- WEB CONFIG API ---------------------------------------------------------

api = FastAPI(title="autodash config")


@api.get("/sites")
def api_get_sites(_: None = Depends(require_auth)):
    if not _SITES_JSON_PATH.exists():
        return JSONResponse(content=[])
    data = json.loads(_SITES_JSON_PATH.read_text(encoding="utf-8"))
    return JSONResponse(content=data)


@api.put("/sites")
async def api_put_sites(request: Request, _: None = Depends(require_auth)):
    body = await request.json()
    _SITES_JSON_PATH.write_text(
        json.dumps(body, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"ok": True}


_DEFAULT_SETTINGS = {"sleep_when_idle": True, "heartbeat_url": "", "heartbeat_interval": 60, "auto_update": True, "remote_active_interval": 2, "remote_idle_interval": 30}


def _load_settings() -> dict:
    if not _SETTINGS_JSON_PATH.exists():
        return dict(_DEFAULT_SETTINGS)
    try:
        return {**_DEFAULT_SETTINGS, **json.loads(_SETTINGS_JSON_PATH.read_text(encoding="utf-8"))}
    except Exception:
        return dict(_DEFAULT_SETTINGS)


_sleep_when_idle    = True
_heartbeat_url      = ""
_heartbeat_interval = 60
_pyautogui_lock     = threading.Lock()  # serialize all input simulation calls


def _apply_settings(s: dict) -> None:
    global _sleep_when_idle, _heartbeat_url, _heartbeat_interval
    _sleep_when_idle    = bool(s.get("sleep_when_idle", True))
    _heartbeat_url      = str(s.get("heartbeat_url", "") or "")
    _heartbeat_interval = max(10, int(s.get("heartbeat_interval", 60)))


async def _heartbeat_loop():
    log = logging.getLogger("heartbeat")
    while True:
        await asyncio.sleep(_heartbeat_interval)
        url = _heartbeat_url
        if url:
            try:
                import urllib.request
                urllib.request.urlopen(url, timeout=10)
                log.debug("Heartbeat OK: %s", url)
            except Exception as exc:
                log.warning("Heartbeat failed (%s): %s", url, exc)


@api.get("/sysinfo")
def api_get_sysinfo(_: None = Depends(require_auth)):
    import sys
    return JSONResponse(content={
        "os":         platform.system(),
        "os_version": platform.version(),
        "os_release": platform.release(),
        "machine":    platform.machine(),
        "hostname":   platform.node(),
        "python":     sys.version.split()[0],
    })


@api.post("/update")
def api_update(_: None = Depends(require_auth)):
    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            capture_output=True, text=True, timeout=60,
            cwd=Path(__file__).parent,
        )
        output = (result.stdout + result.stderr).strip()
        return JSONResponse(content={"ok": result.returncode == 0, "output": output})
    except Exception as exc:
        return JSONResponse(content={"ok": False, "output": str(exc)})


@api.post("/reboot")
def api_reboot(_: None = Depends(require_auth)):
    if platform.system() == "Windows":
        subprocess.Popen(["shutdown", "/r", "/t", "0"])
    else:
        subprocess.Popen(["reboot"])
    return JSONResponse(content={"ok": True})


@api.get("/settings")
def api_get_settings(_: None = Depends(require_auth)):
    return JSONResponse(content=_load_settings())


@api.put("/settings")
async def api_put_settings(request: Request, _: None = Depends(require_auth)):
    body = await request.json()
    _apply_settings(body)
    _SETTINGS_JSON_PATH.write_text(
        json.dumps(body, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"ok": True}


@api.get("/logs")
def api_get_logs(lines: int = 500, _: None = Depends(require_auth)):
    if not _LOG_PATH.exists():
        return JSONResponse(content={"lines": []})
    with open(_LOG_PATH, encoding="utf-8", errors="replace") as f:
        all_lines = f.readlines()
    return JSONResponse(content={"lines": [l.rstrip("\n") for l in all_lines[-lines:]]})


@api.get("/ui", include_in_schema=False)
def api_serve_ui(request: Request):
    if not validate_session(request.cookies.get("session")):
        return RedirectResponse("/login")
    return FileResponse(_UI_HTML_PATH)


@api.get("/login", include_in_schema=False)
def api_serve_login(request: Request):
    # Already logged in — go straight to UI
    if validate_session(request.cookies.get("session")):
        return RedirectResponse("/ui")
    # No user created yet — redirect to first-run setup (avoid loop if already on setup URL)
    if not user_exists() and "setup" not in request.query_params:
        return RedirectResponse("/login?setup=1")
    return FileResponse(_LOGIN_HTML_PATH)


@api.post("/auth/login", include_in_schema=False)
async def api_auth_login(
    username: str = Form(...),
    password: str = Form(...),
):
    if not username or not password:
        return RedirectResponse("/login?error=empty", status_code=303)
    if not check_credentials(username, password):
        return RedirectResponse("/login?error=invalid", status_code=303)
    token = create_session()
    response = RedirectResponse("/ui", status_code=303)
    response.set_cookie("session", token, httponly=True, samesite="lax", max_age=SESSION_TTL)
    return response


@api.post("/auth/setup", include_in_schema=False)
async def api_auth_setup(
    username: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
):
    if user_exists():
        return RedirectResponse("/login?error=exists", status_code=303)
    if not username or not password:
        return RedirectResponse("/login?setup=1&error=empty", status_code=303)
    if password != password2:
        return RedirectResponse("/login?setup=1&error=mismatch", status_code=303)
    create_user(username, password)
    token = create_session()
    response = RedirectResponse("/ui", status_code=303)
    response.set_cookie("session", token, httponly=True, samesite="lax", max_age=SESSION_TTL)
    return response


@api.post("/auth/logout", include_in_schema=False)
async def api_auth_logout(request: Request):
    invalidate_session(request.cookies.get("session"))
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("session")
    return response


@api.get("/screenshot")
async def api_screenshot(monitor: int = 1, _: None = Depends(require_auth)):
    """Return a PNG screenshot of the selected physical display."""
    import mss
    import mss.tools

    def _grab():
        with mss.mss() as sct:
            idx = max(1, min(monitor, len(sct.monitors) - 1))
            frame = sct.grab(sct.monitors[idx])
            return mss.tools.to_png(frame.rgb, frame.size)

    try:
        loop = asyncio.get_running_loop()
        png = await loop.run_in_executor(None, _grab)
        return Response(content=png, media_type="image/png")
    except Exception as exc:
        return JSONResponse(status_code=503, content={"detail": str(exc)})


@api.get("/monitors")
async def api_monitors(_: None = Depends(require_auth)):
    """Return the list of physical monitors (excludes index-0 virtual aggregate)."""
    import mss
    with mss.mss() as sct:
        return [
            {"index": i, "label": f"Monitor {i} ({m['width']}×{m['height']})",
             "width": m["width"], "height": m["height"]}
            for i, m in enumerate(sct.monitors)
            if i > 0
        ]


@api.post("/click")
async def api_click(req: ClickRequest, _: None = Depends(require_auth)):
    """Simulate a mouse click at relative coordinates on the selected monitor."""
    import mss
    import pyautogui

    def _click():
        with _pyautogui_lock, mss.mss() as sct:
            idx = max(1, min(req.monitor, len(sct.monitors) - 1))
            mon = sct.monitors[idx]
            virtual = sct.monitors[0]
            # HiDPI: pyautogui uses logical coords; mss reports actual pixels.
            # Scale factor maps actual pixel space → pyautogui logical space.
            gui_w, gui_h = pyautogui.size()
            scale_x = gui_w / virtual["width"]
            scale_y = gui_h / virtual["height"]
            abs_x = (mon["left"] + req.x * mon["width"]) * scale_x
            abs_y = (mon["top"]  + req.y * mon["height"]) * scale_y
            pyautogui.click(abs_x, abs_y, button=req.button)

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _click)
        return {"ok": True}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"detail": str(exc)})


@api.post("/type")
async def api_type(req: TypeRequest, _: None = Depends(require_auth)):
    """Simulate keyboard input via clipboard paste for full Unicode support."""
    import pyperclip
    import pyautogui

    def _type():
        with _pyautogui_lock:
            if req.method == "type":
                pyautogui.write(req.text, interval=0.02)
            else:
                pyperclip.copy(req.text)
                pyautogui.hotkey("ctrl", "v")
            if req.send_enter:
                pyautogui.press("enter")

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _type)
        return {"ok": True}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"detail": str(exc)})


@api.post("/key")
async def api_key(req: KeyRequest, _: None = Depends(require_auth)):
    """Simulate a key press or hotkey combo."""
    import pyautogui

    def _press():
        with _pyautogui_lock:
            if isinstance(req.key, list):
                pyautogui.hotkey(*req.key)
            else:
                pyautogui.press(req.key)

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _press)
        return {"ok": True}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"detail": str(exc)})


async def check_site_available(url: str) -> bool:
    """Return True if the site responds with a non-5xx HTTP status.
    4xx (e.g. 401 on a login page) counts as available — the server is up.
    Content-based checks are handled separately by SiteMonitor after Playwright
    has fully rendered the page."""
    import urllib.request
    import urllib.error

    def _check():
        try:
            req = urllib.request.Request(url, method="HEAD")
            try:
                resp   = urllib.request.urlopen(req, timeout=SITE_CHECK_TIMEOUT)
                status = resp.status
                resp.close()
            except urllib.error.HTTPError as exc:
                status = exc.code
            return status < 500
        except Exception:
            return False

    try:
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(None, _check),
            timeout=SITE_CHECK_TIMEOUT + 2,
        )
    except Exception:
        return False


async def check_internet() -> bool:
    """Return True if a TCP connection to the check host succeeds."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(INTERNET_CHECK_HOST, INTERNET_CHECK_PORT),
            timeout=INTERNET_CHECK_TIMEOUT,
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False

# ---- LOGGING ------------------------------------------------------------

import logging.handlers as _log_handlers

_LOG_FORMAT = "%(asctime)s  [%(levelname)s]  %(name)s  - %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"

logging.basicConfig(
    level  = logging.INFO,
    format = _LOG_FORMAT,
    datefmt= _LOG_DATEFMT,
)

_file_handler = _log_handlers.RotatingFileHandler(
    _LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
_file_handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT))
logging.getLogger().addHandler(_file_handler)

IS_LINUX    = platform.system() == "Linux"
HAS_XDOTOOL = IS_LINUX and shutil.which("xdotool") is not None
HAS_WMCTRL  = IS_LINUX and shutil.which("wmctrl") is not None

if IS_LINUX:
    if not HAS_XDOTOOL:
        logging.warning("xdotool not found. Install: sudo apt install xdotool")
    if not HAS_WMCTRL:
        logging.warning("wmctrl not found. Install: sudo apt install wmctrl")


# ---- DISPLAY SLEEP PREVENTION -------------------------------------------

_display_sleep_disabled = False


def disable_display_sleep():
    global _display_sleep_disabled
    if _display_sleep_disabled:
        return
    _display_sleep_disabled = True
    if IS_LINUX and shutil.which("xset"):
        for args in (
            ["xset", "s", "off"],       # disable screensaver
            ["xset", "s", "0", "0"],    # set screensaver timeout to 0 (explicit)
            ["xset", "-dpms"],          # disable DPMS power management
            ["xset", "s", "noblank"],   # disable screen blanking
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
        # Simulate a harmless mouse move to wake the display
        ctypes.windll.user32.mouse_event(0x0001, 0, 0, 0, 0)


def enable_display_sleep():
    global _display_sleep_disabled
    if not _display_sleep_disabled:
        return
    _display_sleep_disabled = False
    if IS_LINUX and shutil.which("xset"):
        for args in (
            ["xset", "s", "on"],        # re-enable screensaver
            ["xset", "+dpms"],          # re-enable DPMS power management
            ["xset", "s", "blank"],     # re-enable screen blanking
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


# ---- HELPERS ------------------------------------------------------------

def is_closed_error(exc):
    msg = str(exc).lower()
    return any(phrase in msg for phrase in (
        "target closed",
        "target page, context or browser has been closed",
        "browser has been closed",
        "context or browser has been closed",
        "page has been closed",
        "connection closed",
    ))


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


def build_args(cfg):
    args = [
        "--disable-infobars",
        "--test-type",
        "--no-default-browser-check",
        "--no-first-run",
        "--disable-extensions",
        "--disable-background-networking",
        "--password-store=basic",
    ]
    args.append(f"--window-position={cfg.window_x},{cfg.window_y}")
    if cfg.fullscreen:
        args.append("--start-fullscreen")
    else:
        args.append(f"--window-size={cfg.window_width},{cfg.window_height}")
    return args


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


# ---- X11 WINDOW MANAGEMENT ----------------------------------------------

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


# ---- SCHEDULING ---------------------------------------------------------

_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _parse_day_spec(spec: str) -> set:
    spec = spec.strip()
    if spec == "*":
        return set(range(7))
    result = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                start_idx = _DAY_NAMES.index(a.strip())
                end_idx   = _DAY_NAMES.index(b.strip())
            except ValueError:
                raise ValueError(f"Unknown day name in schedule: {part!r}")
            if start_idx <= end_idx:
                result.update(range(start_idx, end_idx + 1))
            else:
                result.update(range(start_idx, 7))
                result.update(range(0, end_idx + 1))
        else:
            try:
                result.add(_DAY_NAMES.index(part))
            except ValueError:
                raise ValueError(f"Unknown day name in schedule: {part!r}")
    return result


def _parse_hhmm(s: str) -> datetime.time:
    try:
        h, m = s.strip().split(":")
        return datetime.time(int(h), int(m))
    except Exception:
        raise ValueError(f"Invalid time format (expected HH:MM): {s!r}")


def _time_in_window(t, start, end) -> bool:
    if start <= end:
        return start <= t < end
    return t >= start or t < end   # overnight window


def is_scheduled_now(schedule: list) -> bool:
    """Return True if the current time falls within any window in schedule.
    An empty schedule means always active."""
    if not schedule:
        return True
    now     = datetime.datetime.now()
    current = now.time().replace(second=0, microsecond=0)
    today   = now.weekday()   # 0=Mon … 6=Sun
    for entry in schedule:
        if len(entry) == 2:
            if _time_in_window(current, _parse_hhmm(entry[0]), _parse_hhmm(entry[1])):
                return True
        elif len(entry) == 3:
            if today not in _parse_day_spec(str(entry[0])):
                continue
            if _time_in_window(current, _parse_hhmm(entry[1]), _parse_hhmm(entry[2])):
                return True
    return False


# ---- SITE MONITOR -------------------------------------------------------

class SiteMonitor:

    def __init__(self, cfg, pw, profile_dir):
        self.cfg          = cfg
        self.pw           = pw
        self.profile_dir  = profile_dir
        self.context      = None
        self.page         = None
        self._closed      = False
        self._window_id   = None
        self._seconds_since_pos_check = 0
        self._showing_offline      = False
        self._showing_unavailable  = False
        self._stable_geom = None   # actual geometry as reported by xdotool after positioning
        self.log          = logging.getLogger(cfg.name)

    def _write_profile_prefs(self):
        """Disable password manager before Chromium reads the profile."""
        prefs_dir = self.profile_dir / "Default"
        prefs_dir.mkdir(parents=True, exist_ok=True)
        prefs_file = prefs_dir / "Preferences"
        prefs = {
            "credentials_enable_service": False,
            "profile": {"password_manager_enabled": False},
        }
        prefs_file.write_text(json.dumps(prefs))

    async def _launch_context(self):
        if self.context:
            try:
                await self.context.close()
            except Exception:
                pass
            self.context              = None
            self.page                 = None
            self._window_id           = None
            self._stable_geom         = None
            self._showing_unavailable = False

        self._write_profile_prefs()

        mode = "fullscreen" if self.cfg.fullscreen else (
            f"{self.cfg.window_width}x{self.cfg.window_height} "
            f"at ({self.cfg.window_x},{self.cfg.window_y})"
        )
        self.log.info("Launching Chromium app-mode window [%s] ...", mode)

        launch_env = {"DISPLAY": os.environ.get("DISPLAY", ":0")} if IS_LINUX else {}

        self.context = await self.pw.chromium.launch_persistent_context(
            user_data_dir       = str(self.profile_dir),
            headless            = False,
            args                = [f"--app={self.cfg.url}"] + build_args(self.cfg),
            ignore_default_args = ["--enable-automation"],
            no_viewport         = True,
            ignore_https_errors = True,
            env                 = launch_env,
        )

        self._closed = False
        self.context.on("close", self._on_context_closed)

        pages = self.context.pages
        self.page = pages[0] if pages else await self.context.new_page()

        await position_window(self.cfg, self.page)

        if IS_LINUX and not self.cfg.fullscreen:
            try:
                title = await self.page.title()
            except Exception:
                title = "chromium"
            self._window_id = find_window_id(title)
            if self._window_id:
                self._stable_geom = get_window_geometry(self._window_id)

    def _on_context_closed(self, *_):
        if not self._closed:
            self._closed    = True
            self._window_id = None
            self.log.warning("Browser window was closed - will reopen shortly.")

    def _is_alive(self):
        if self._closed or self.context is None or self.page is None:
            return False
        try:
            _ = self.context.pages
        except Exception:
            return False
        return not self.page.is_closed()

    async def _reopen(self):
        self.log.info("Reopening browser window ...")
        await asyncio.sleep(RECONNECT_DELAY_SECONDS)
        await self._launch_context()
        await self.navigate_and_login()

    async def _check_window_position(self):
        if not IS_LINUX or self.cfg.fullscreen:
            return
        if not self._window_id:
            try:
                title = await self.page.title()
            except Exception:
                title = "chromium"
            self._window_id = find_window_id(title)
        if not self._window_id:
            return
        geom = get_window_geometry(self._window_id)
        if geom is None:
            self._window_id = None
            self._stable_geom = None
            return
        # Capture the stable geometry the first time we see the window
        if self._stable_geom is None:
            self._stable_geom = geom
        x, y, w, h = geom
        ex, ey, ew, eh = self._stable_geom
        dx = abs(x - ex)
        dy = abs(y - ey)
        dw = abs(w - ew)
        dh = abs(h - eh)
        if max(dx, dy, dw, dh) > POSITION_TOLERANCE_PX:
            self.log.warning(
                "Window drifted to (%d,%d) %dx%d - expected (%d,%d) %dx%d - correcting ...",
                x, y, w, h, ex, ey, ew, eh,
            )
            force_window_geometry(self.cfg, self._window_id, self.log)
            await asyncio.sleep(0.3)
            await fit_viewport_to_window(self.page)
            # Record the new settled position as the stable reference
            settled = get_window_geometry(self._window_id)
            if settled:
                self._stable_geom = settled

    async def close_window(self):
        """Close the browser window. Called by the schedule coordinator."""
        self._closed = True   # suppress the "will reopen" warning from _on_context_closed
        if self.context:
            try:
                await self.context.close()
            except Exception:
                pass
            self.context      = None
            self.page         = None
            self._window_id   = None
            self._stable_geom = None
        self._showing_offline     = False
        self._showing_unavailable = False
        self.log.info("Window closed by coordinator.")

    async def _show_offline_page(self):
        if self._showing_offline:
            return
        self.log.warning("Internet unavailable - showing notice in dashboard window.")
        self._showing_offline = True
        try:
            await self.page.goto(_OFFLINE_URL, wait_until="load", timeout=10_000)
        except Exception as exc:
            if not is_closed_error(exc):
                self.log.debug("Offline page navigation (non-fatal): %s", exc)

    async def _restore_from_offline(self):
        self.log.info("Internet restored - resuming.")
        self._showing_offline = False
        await self.navigate_and_login()

    async def _playwright_availability_check(self) -> bool:
        """Launch a temporary headless browser, navigate to the site URL, and
        verify that availability_check_selector exists in the rendered DOM.
        Skipped when mode is 'http' or no selector is configured."""
        if self.cfg.availability_check_mode != "selector" or not self.cfg.availability_check_selector:
            return True
        browser = None
        try:
            browser = await self.pw.chromium.launch(
                headless = True,
            )
            page = await browser.new_page(ignore_https_errors=True)
            await page.goto(self.cfg.url, wait_until="networkidle", timeout=15_000)
            el = await page.query_selector(self.cfg.availability_check_selector)
            available = el is not None
            if not available:
                self.log.warning(
                    "Selector '%s' not found - site unavailable.",
                    self.cfg.availability_check_selector,
                )
            return available
        except Exception as exc:
            self.log.warning("Headless availability check failed: %s", exc)
            return False
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    async def _show_unavailable_page(self):
        if self._showing_unavailable:
            return
        self.log.warning("Site unavailable - showing notice in dashboard window.")
        self._showing_unavailable = True
        url = _SITE_UNAVAILABLE_URL + "#" + _url_quote(self.cfg.name)
        try:
            await self.page.goto(url, wait_until="load", timeout=10_000)
        except Exception as exc:
            if not is_closed_error(exc):
                self.log.debug("Unavailable page navigation (non-fatal): %s", exc)

    async def _restore_from_unavailable(self):
        self.log.info("Site back online - resuming.")
        self._showing_unavailable = False
        await self.navigate_and_login()

    async def start(self):
        await self._launch_context()
        if not await check_internet():
            await self._show_offline_page()
        elif self.cfg.availability_check and not (
            await check_site_available(self.cfg.url)
            and await self._playwright_availability_check()
        ):
            await self._show_unavailable_page()
        else:
            await self.navigate_and_login()

    async def navigate_and_login(self):
        self.log.info("Navigating to %s", self.cfg.url)
        try:
            await self.page.goto(self.cfg.url, wait_until="networkidle", timeout=30_000)
        except PlaywrightTimeoutError:
            self.log.warning("Page load timed out - continuing anyway.")
        except Exception as exc:
            if is_closed_error(exc):
                raise
            self.log.warning("Navigation warning: %s", exc)
        await asyncio.sleep(2)
        if not self.cfg.fullscreen:
            await fit_viewport_to_window(self.page)
        if self.cfg.auto_login:
            if not await self.is_logged_in():
                await self.login()
            else:
                self.log.info("Already logged in.")
                await self._maybe_goto_post_login()

    def _resolve_locator(self, selector: str):
        """Return a Playwright Locator for a selector string.

        Supports:
          role=button[name="Sign In"]   → page.get_by_role("button", name="Sign In")
          role=textbox[name="Username"] → page.get_by_role("textbox", name="Username")
          anything else                 → page.locator(selector)  (CSS / XPath)
        """
        import re
        m = re.fullmatch(
            r'role=([a-zA-Z]+)(?:\[name=["\']?(.*?)["\']?\])?',
            selector.strip(),
        )
        if m:
            role, name = m.group(1), m.group(2)
            return self.page.get_by_role(role, name=name) if name else self.page.get_by_role(role)
        return self.page.locator(selector)

    async def _login_with_steps(self):
        totp_token = pyotp.TOTP(self.cfg.totp_secret).now() if self.cfg.totp_secret else ""
        subs = {"{username}": self.cfg.username, "{password}": self.cfg.password, "{totp}": totp_token}
        for step in self.cfg.login_steps:
            value = step.value
            for k, v in subs.items():
                value = value.replace(k, v)

            if step.action == "fill":
                loc = self._resolve_locator(step.selector).first
                try:
                    await loc.wait_for(state="visible", timeout=10_000)
                    await loc.click()
                    await loc.fill(value)
                except PlaywrightTimeoutError:
                    self.log.error("Login step: element not found: %s", step.selector)
                    return

            elif step.action == "click":
                loc = self._resolve_locator(step.selector).first
                try:
                    await loc.wait_for(state="visible", timeout=10_000)
                    await loc.click()
                    await asyncio.sleep(1)
                except PlaywrightTimeoutError:
                    self.log.error("Login step: element not found: %s", step.selector)
                    return

            elif step.action == "press":
                if step.selector:
                    loc = self._resolve_locator(step.selector).first
                    try:
                        await loc.wait_for(state="visible", timeout=10_000)
                        await loc.press(value or "Enter")
                    except PlaywrightTimeoutError:
                        self.log.error("Login step: element not found: %s", step.selector)
                        return
                else:
                    await self.page.keyboard.press(value or "Enter")
                await asyncio.sleep(1)

            elif step.action == "wait_for":
                loc = self._resolve_locator(step.selector)
                try:
                    await loc.first.wait_for(state="visible", timeout=15_000)
                except PlaywrightTimeoutError:
                    self.log.error("Login step: timed out waiting for: %s", step.selector)
                    return

            else:
                self.log.warning("Login step: unknown action '%s' — skipping.", step.action)

    async def login(self):
        self.log.info("Attempting login ...")
        if self.cfg.login_steps:
            await self._login_with_steps()
            try:
                await self.page.wait_for_load_state("networkidle", timeout=15_000)
            except PlaywrightTimeoutError:
                pass
            await asyncio.sleep(5)
            self.log.info("Login steps completed.")
            await self._maybe_goto_post_login()
        else:
            username_field = await self._find_element(
                [self.cfg.username_selector] + self.cfg.extra_username_selectors
            )
            if username_field is None:
                self.log.error("Username field not found - check username_selector in the config UI.")
                return
            password_field = await self._find_element(
                [self.cfg.password_selector] + self.cfg.extra_password_selectors
            )
            if password_field is None:
                self.log.error("Password field not found - check password_selector in the config UI.")
                return
            await username_field.click()
            await username_field.fill(self.cfg.username)
            await password_field.click()
            await password_field.fill(self.cfg.password)
            submit = await self._find_element([self.cfg.submit_selector])
            if submit:
                await submit.click()
            else:
                self.log.warning("Submit button not found - pressing Enter.")
                await password_field.press("Enter")
            try:
                await self.page.wait_for_load_state("networkidle", timeout=15_000)
            except PlaywrightTimeoutError:
                pass
            await asyncio.sleep(2)
            if await self.is_logged_in():
                self.log.info("Login successful.")
                await self._maybe_goto_post_login()
            else:
                self.log.warning("Login may have failed - check credentials/selectors in the config UI.")

    async def _maybe_goto_post_login(self):
        if not self.cfg.post_login_enabled:
            return
        if self.cfg.post_login_url:
            if self.page.url.rstrip("/") == self.cfg.post_login_url.rstrip("/"):
                pass
            else:
                self.log.info("Navigating to post-login URL: %s", self.cfg.post_login_url)
                try:
                    await self.page.goto(
                        self.cfg.post_login_url, wait_until="networkidle", timeout=30_000
                    )
                    if not self.cfg.fullscreen:
                        await fit_viewport_to_window(self.page)
                except PlaywrightTimeoutError:
                    self.log.warning("Post-login navigation timed out - continuing anyway.")
                except Exception as exc:
                    if is_closed_error(exc):
                        raise
                    self.log.warning("Post-login navigation warning: %s", exc)
        if self.cfg.post_login_steps:
            await self._run_post_login_steps()

    async def _run_post_login_steps(self):
        totp_token = pyotp.TOTP(self.cfg.totp_secret).now() if self.cfg.totp_secret else ""
        subs = {"{username}": self.cfg.username, "{password}": self.cfg.password, "{totp}": totp_token}
        for step in self.cfg.post_login_steps:
            value = step.value
            for k, v in subs.items():
                value = value.replace(k, v)

            if step.action == "fill":
                loc = self._resolve_locator(step.selector).first
                try:
                    await loc.wait_for(state="visible", timeout=30_000)
                    await loc.click()
                    await loc.fill(value)
                except PlaywrightTimeoutError:
                    self.log.error("Post-login step: timed out waiting for: %s (url: %s)", step.selector, self.page.url)
                    return

            elif step.action == "click":
                loc = self._resolve_locator(step.selector).first
                try:
                    await loc.wait_for(state="visible", timeout=30_000)
                    await loc.click()
                    await asyncio.sleep(1)
                except PlaywrightTimeoutError:
                    self.log.error("Post-login step: timed out waiting for: %s (url: %s)", step.selector, self.page.url)
                    return

            elif step.action == "press":
                if step.selector:
                    loc = self._resolve_locator(step.selector).first
                    try:
                        await loc.wait_for(state="visible", timeout=30_000)
                        await loc.press(value or "Enter")
                    except PlaywrightTimeoutError:
                        self.log.error("Post-login step: timed out waiting for: %s (url: %s)", step.selector, self.page.url)
                        return
                else:
                    await self.page.keyboard.press(value or "Enter")
                await asyncio.sleep(1)

            elif step.action == "wait_for":
                loc = self._resolve_locator(step.selector)
                try:
                    await loc.first.wait_for(state="visible", timeout=30_000)
                except PlaywrightTimeoutError:
                    self.log.error("Post-login step: timed out waiting for: %s (url: %s)", step.selector, self.page.url)
                    return

            else:
                self.log.warning("Post-login step: unknown action '%s' — skipping.", step.action)

    async def is_logged_in(self):
        try:
            if self.page is None or self.page.is_closed():
                return False
            if self.cfg.logged_in_selector:
                el = await self.page.query_selector(self.cfg.logged_in_selector)
                if el:
                    self.log.info("is_logged_in: yes — selector '%s' found on %s", self.cfg.logged_in_selector, self.page.url)
                    return True
                self.log.info("is_logged_in: no — selector '%s' not found on %s", self.cfg.logged_in_selector, self.page.url)
            if self.cfg.logged_in_url_fragment:
                if self.cfg.logged_in_url_fragment in self.page.url:
                    self.log.info("is_logged_in: yes — URL fragment '%s' matched in %s", self.cfg.logged_in_url_fragment, self.page.url)
                    return True
                self.log.info("is_logged_in: no — URL fragment '%s' not found in %s", self.cfg.logged_in_url_fragment, self.page.url)
            if not self.cfg.logged_in_selector and not self.cfg.logged_in_url_fragment:
                pw_field = await self.page.query_selector(self.cfg.password_selector)
                if pw_field is None:
                    self.log.info("is_logged_in: yes — password selector '%s' absent from %s (fallback)", self.cfg.password_selector, self.page.url)
                    return True
                self.log.info("is_logged_in: no — password selector '%s' still present on %s (fallback)", self.cfg.password_selector, self.page.url)
        except Exception as exc:
            self.log.debug("is_logged_in check error (non-fatal): %s", exc)
        return False

    async def refresh(self):
        self.log.info("Refreshing page ...")
        try:
            await self.page.reload(wait_until="networkidle", timeout=30_000)
        except PlaywrightTimeoutError:
            self.log.warning("Reload timed out - continuing.")
        await asyncio.sleep(2)
        if self.cfg.auto_login and not await self.is_logged_in():
            self.log.warning("Session expired after refresh - re-logging in.")
            await self.login()

    async def run_loop(self):
        seconds_since_refresh = 0
        self._seconds_since_pos_check = 0
        while True:
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            seconds_since_refresh         += CHECK_INTERVAL_SECONDS
            self._seconds_since_pos_check += CHECK_INTERVAL_SECONDS
            try:
                if not self._is_alive():
                    await self._reopen()
                    seconds_since_refresh         = 0
                    self._seconds_since_pos_check = 0
                    continue

                online = await check_internet()
                if not online:
                    await self._show_offline_page()
                    continue
                if self._showing_offline:
                    await self._restore_from_offline()
                    seconds_since_refresh         = 0
                    self._seconds_since_pos_check = 0
                    continue

                available = not self.cfg.availability_check or (
                    await check_site_available(self.cfg.url)
                    and await self._playwright_availability_check()
                )
                if not available:
                    await self._show_unavailable_page()
                    continue
                if self._showing_unavailable:
                    await self._restore_from_unavailable()
                    seconds_since_refresh         = 0
                    self._seconds_since_pos_check = 0
                    continue

                if self._seconds_since_pos_check >= POSITION_CHECK_SECONDS:
                    await self._check_window_position()
                    self._seconds_since_pos_check = 0
                refresh_interval = max(60, self.cfg.refresh_interval)
                if self.cfg.auto_refresh and seconds_since_refresh >= refresh_interval:
                    await self.refresh()
                    seconds_since_refresh = 0
                else:
                    self.log.debug("Session check ...")
                    if self.cfg.auto_login and not await self.is_logged_in():
                        self.log.warning("Session lost - re-logging in.")
                        await self.navigate_and_login()
            except PlaywrightError as exc:
                if is_closed_error(exc):
                    self.log.warning("Playwright closed-target error - will reopen. (%s)", exc)
                    self._closed = True
                else:
                    self.log.error("Playwright error: %s", exc)
                    await asyncio.sleep(RECONNECT_DELAY_SECONDS)
            except Exception as exc:
                if is_closed_error(exc):
                    self.log.warning("Closed-target error - will reopen. (%s)", exc)
                    self._closed = True
                else:
                    self.log.error("Unexpected error in loop: %s", exc, exc_info=True)
                    await asyncio.sleep(RECONNECT_DELAY_SECONDS)

    async def _find_element(self, selectors):
        for selector in selectors:
            for part in selector.split(","):
                part = part.strip()
                if not part:
                    continue
                try:
                    el = await self.page.query_selector(part)
                    if el and await el.is_visible():
                        return el
                except Exception:
                    continue
        return None


# ---- SCHEDULE COORDINATOR -----------------------------------------------

def _make_task_done_cb(name, log):
    def _cb(task):
        if task.cancelled():
            return
        try:
            exc = task.exception()
            if exc:
                log.error("Monitor '%s' crashed: %s", name, exc, exc_info=exc)
        except asyncio.CancelledError:
            pass
    return _cb


async def schedule_coordinator(monitors, pw):
    log = logging.getLogger("coordinator")

    active_tasks = {}          # SiteMonitor -> asyncio.Task
    was_active   = {m: None for m in monitors}   # None = first tick not yet run
    sites_mtime  = _SITES_JSON_PATH.stat().st_mtime if _SITES_JSON_PATH.exists() else 0.0

    # Notice window state (managed as a bare context, not a SiteMonitor)
    notice_context = None

    async def _open_notice():
        nonlocal notice_context
        if notice_context is not None:
            try:
                # reopen if it was closed by the user
                if notice_context.pages and not notice_context.pages[0].is_closed():
                    return
            except Exception:
                pass
            try:
                await notice_context.close()
            except Exception:
                pass
            notice_context = None

        log.info("No monitors active — showing 'No dashboard scheduled' notice.")
        if _sleep_when_idle:
            enable_display_sleep()
        launch_env = {"DISPLAY": os.environ.get("DISPLAY", ":0")} if IS_LINUX else {}
        try:
            notice_context = await pw.chromium.launch_persistent_context(
                user_data_dir       = str(Path(tempfile.mkdtemp(prefix="pw_notice_"))),
                headless            = False,
                args                = [
                    f"--app={_NO_SCHEDULE_URL}",
                    "--start-fullscreen",
                    "--disable-infobars",
                    "--test-type",
                    "--no-default-browser-check",
                    "--no-first-run",
                    "--disable-extensions",
                    "--password-store=basic",
                ],
                ignore_default_args = ["--enable-automation"],
                no_viewport         = True,
                ignore_https_errors = True,
                env                 = launch_env,
            )
        except Exception as exc:
            log.error("Failed to open notice window: %s", exc)
            notice_context = None

    async def _close_notice():
        nonlocal notice_context
        disable_display_sleep()
        wake_display()
        if notice_context is None:
            return
        log.info("A monitor became active — closing notice window.")
        try:
            await notice_context.close()
        except Exception:
            pass
        notice_context = None

    while True:
        any_active = False

        for m in monitors:
            active = is_scheduled_now(m.cfg.schedule)
            if active:
                any_active = True

            prev = was_active[m]

            if active and (prev is None or not prev):
                # Entering schedule window (or first tick while active)
                existing = active_tasks.get(m)
                if existing and not existing.done():
                    # Already running — nothing to do
                    pass
                else:
                    log.info("Starting monitor '%s'.", m.cfg.name)
                    try:
                        await m.start()
                        t = asyncio.create_task(m.run_loop(), name=m.cfg.name)
                        t.add_done_callback(_make_task_done_cb(m.cfg.name, log))
                        active_tasks[m] = t
                    except Exception as exc:
                        log.error("Failed to start '%s': %s", m.cfg.name, exc, exc_info=True)

            elif not active and prev:
                # Leaving schedule window
                log.info("Monitor '%s' outside schedule — closing.", m.cfg.name)
                t = active_tasks.pop(m, None)
                if t and not t.done():
                    t.cancel()
                    try:
                        await asyncio.wait_for(asyncio.shield(t), timeout=5)
                    except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                        pass
                await m.close_window()

            elif not active and prev is None:
                log.info("Monitor '%s' outside schedule at startup — skipping.", m.cfg.name)

            was_active[m] = active

        if any_active:
            await _close_notice()
        else:
            await _open_notice()

        # ── Hot-reload sites.json ─────────────────────────────────────────
        try:
            mtime = _SITES_JSON_PATH.stat().st_mtime
        except OSError:
            mtime = sites_mtime

        if mtime != sites_mtime:
            sites_mtime = mtime
            try:
                new_cfgs = _load_sites()
                log.info("sites.json changed — reconciling monitors.")
            except Exception as exc:
                log.error("Failed to reload sites.json: %s", exc)
                new_cfgs = None

            if new_cfgs is not None:
                old_by_name = {m.cfg.name: m for m in list(monitors)}
                new_by_name = {cfg.name: cfg for cfg in new_cfgs}

                async def _stop_monitor(m):
                    t = active_tasks.pop(m, None)
                    if t and not t.done():
                        t.cancel()
                        try:
                            await asyncio.wait_for(asyncio.shield(t), timeout=5)
                        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                            pass
                    await m.close_window()
                    monitors.remove(m)
                    was_active.pop(m, None)

                # Remove sites no longer present
                for name, m in list(old_by_name.items()):
                    if name not in new_by_name:
                        log.info("config: removing '%s'.", name)
                        await _stop_monitor(m)

                # Add new sites / restart changed sites
                for cfg in new_cfgs:
                    existing = old_by_name.get(cfg.name)
                    if existing is None:
                        log.info("config: adding '%s'.", cfg.name)
                        profile_dir = Path(tempfile.mkdtemp(prefix=f"pw_profile_{cfg.name}_"))
                        m = SiteMonitor(cfg, pw, profile_dir)
                        monitors.append(m)
                        was_active[m] = None
                    elif existing.cfg != cfg:
                        log.info("config: changed for '%s', restarting.", cfg.name)
                        await _stop_monitor(existing)
                        profile_dir = Path(tempfile.mkdtemp(prefix=f"pw_profile_{cfg.name}_"))
                        m = SiteMonitor(cfg, pw, profile_dir)
                        monitors.append(m)
                        was_active[m] = None

        await asyncio.sleep(SCHEDULE_CHECK_SECONDS)


# ---- ENTRY POINT --------------------------------------------------------

async def display_keepalive():
    """Periodically reset the X11 screensaver timer to prevent blanking on Linux.
    Runs only when display sleep is currently disabled."""
    if not IS_LINUX or not shutil.which("xset"):
        return
    while True:
        await asyncio.sleep(50)
        if _display_sleep_disabled:
            run_cmd(["xset", "s", "reset"])


async def main():
    disable_display_sleep()
    _apply_settings(_load_settings())
    initial_sites = _load_sites()
    profile_dirs = [
        Path(tempfile.mkdtemp(prefix=f"pw_profile_{i}_"))
        for i in range(len(initial_sites))
    ]
    async with async_playwright() as pw:
        monitors = [
            SiteMonitor(cfg, pw, profile_dirs[i])
            for i, cfg in enumerate(initial_sites)
        ]
        global _monitors
        _monitors = monitors  # same list object — coordinator mutations are reflected here
        coordinator = asyncio.create_task(
            schedule_coordinator(monitors, pw), name="coordinator"
        )
        keepalive  = asyncio.create_task(display_keepalive(), name="keepalive")
        heartbeat  = asyncio.create_task(_heartbeat_loop(), name="heartbeat")
        web_config = uvicorn.Config(
            api, host="0.0.0.0", port=WEB_PORT, log_level="warning"
        )
        web_server = uvicorn.Server(web_config)
        web_task   = asyncio.create_task(web_server.serve(), name="webui")
        logging.info("Config UI available at http://0.0.0.0:%d/ui", WEB_PORT)
        try:
            await coordinator
        except asyncio.CancelledError:
            pass
        finally:
            logging.info("Shutting down ...")
            coordinator.cancel()
            keepalive.cancel()
            heartbeat.cancel()
            web_server.should_exit = True
            web_task.cancel()
            for m in monitors:
                try:
                    if m.context:
                        await m.context.close()
                except Exception:
                    pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user.")
