"""
monitor.py - Multi-Site Auto-Login Monitor using Playwright (Chromium)
"""

import asyncio
import logging
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    async_playwright,
    Page,
    BrowserContext,
    Playwright,
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
)

from config import SiteConfig
from sites import SITES

# ---- TIMING CONFIGURATION -----------------------------------------------

REFRESH_INTERVAL_SECONDS  = 600
CHECK_INTERVAL_SECONDS    = 30
RECONNECT_DELAY_SECONDS   = 5
POSITION_CHECK_SECONDS    = 10
POSITION_TOLERANCE_PX     = 5

# ---- CONNECTIVITY -------------------------------------------------------

INTERNET_CHECK_HOST    = "8.8.8.8"
INTERNET_CHECK_PORT    = 53
INTERNET_CHECK_TIMEOUT = 3

_OFFLINE_HTML_PATH = Path(__file__).parent / "offline.html"
_OFFLINE_URL = _OFFLINE_HTML_PATH.as_uri()


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

logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s  [%(levelname)s]  %(name)s  - %(message)s",
    datefmt= "%Y-%m-%d %H:%M:%S",
)

IS_LINUX    = platform.system() == "Linux"
HAS_XDOTOOL = IS_LINUX and shutil.which("xdotool") is not None
HAS_WMCTRL  = IS_LINUX and shutil.which("wmctrl") is not None

if IS_LINUX:
    if not HAS_XDOTOOL:
        logging.warning("xdotool not found. Install: sudo apt install xdotool")
    if not HAS_WMCTRL:
        logging.warning("wmctrl not found. Install: sudo apt install wmctrl")


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
        "--no-default-browser-check",
        "--no-first-run",
        "--disable-extensions",
        "--disable-background-networking",
    ]
    if cfg.fullscreen:
        args.append("--start-fullscreen")
    else:
        args.append(f"--window-position={cfg.window_x},{cfg.window_y}")
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
        self._showing_offline = False
        self.log          = logging.getLogger(cfg.name)

    async def _launch_context(self):
        if self.context:
            try:
                await self.context.close()
            except Exception:
                pass
            self.context   = None
            self.page      = None
            self._window_id = None

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
            return
        x, y, w, h = geom
        dx = abs(x - self.cfg.window_x)
        dy = abs(y - self.cfg.window_y)
        dw = abs(w - self.cfg.window_width)
        dh = abs(h - self.cfg.window_height)
        if max(dx, dy, dw, dh) > POSITION_TOLERANCE_PX:
            self.log.warning(
                "Window drifted to (%d,%d) %dx%d - expected (%d,%d) %dx%d - correcting ...",
                x, y, w, h,
                self.cfg.window_x, self.cfg.window_y,
                self.cfg.window_width, self.cfg.window_height,
            )
            force_window_geometry(self.cfg, self._window_id, self.log)
            await asyncio.sleep(0.3)
            await fit_viewport_to_window(self.page)

    async def _show_offline_page(self):
        if self._showing_offline:
            return
        self.log.warning("Internet unavailable - showing offline page.")
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

    async def start(self):
        await self._launch_context()
        if not await check_internet():
            await self._show_offline_page()
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
        if not await self.is_logged_in():
            await self.login()
        else:
            self.log.info("Already logged in.")
            await self._maybe_goto_post_login()

    async def login(self):
        self.log.info("Attempting login ...")
        username_field = await self._find_element(
            [self.cfg.username_selector] + self.cfg.extra_username_selectors
        )
        if username_field is None:
            self.log.error("Username field not found - check username_selector in sites.py.")
            return
        password_field = await self._find_element(
            [self.cfg.password_selector] + self.cfg.extra_password_selectors
        )
        if password_field is None:
            self.log.error("Password field not found - check password_selector in sites.py.")
            return
        await username_field.click()
        await username_field.fill("")
        await username_field.type(self.cfg.username, delay=50)
        await password_field.click()
        await password_field.fill("")
        await password_field.type(self.cfg.password, delay=50)
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
            self.log.warning("Login may have failed - check credentials/selectors in sites.py.")

    async def _maybe_goto_post_login(self):
        if not self.cfg.post_login_url:
            return
        if self.page.url.rstrip("/") == self.cfg.post_login_url.rstrip("/"):
            return
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

    async def is_logged_in(self):
        try:
            if self.page is None or self.page.is_closed():
                return False
            if self.cfg.logged_in_selector:
                el = await self.page.query_selector(self.cfg.logged_in_selector)
                if el:
                    return True
            if self.cfg.logged_in_url_fragment:
                if self.cfg.logged_in_url_fragment in self.page.url:
                    return True
            if not self.cfg.logged_in_selector and not self.cfg.logged_in_url_fragment:
                pw_field = await self.page.query_selector(self.cfg.password_selector)
                if pw_field is None:
                    return True
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
        if not await self.is_logged_in():
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

                if self._seconds_since_pos_check >= POSITION_CHECK_SECONDS:
                    await self._check_window_position()
                    self._seconds_since_pos_check = 0
                if seconds_since_refresh >= REFRESH_INTERVAL_SECONDS:
                    await self.refresh()
                    seconds_since_refresh = 0
                else:
                    self.log.debug("Session check ...")
                    if not await self.is_logged_in():
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


# ---- ENTRY POINT --------------------------------------------------------

async def main():
    profile_dirs = [
        Path(tempfile.mkdtemp(prefix=f"pw_profile_{i}_"))
        for i in range(len(SITES))
    ]
    async with async_playwright() as pw:
        monitors = [
            SiteMonitor(cfg, pw, profile_dirs[i])
            for i, cfg in enumerate(SITES)
        ]
        started = []
        for m in monitors:
            try:
                await m.start()
                started.append(m)
            except Exception as exc:
                logging.error("Failed to start '%s': %s", m.cfg.name, exc, exc_info=True)
        if not started:
            logging.critical("No monitors started - exiting.")
            return
        loop_tasks = [
            asyncio.create_task(m.run_loop(), name=m.cfg.name)
            for m in started
        ]
        def _on_task_done(task):
            if task.cancelled():
                return
            try:
                exc = task.exception()
                if exc:
                    logging.error("Monitor '%s' crashed: %s", task.get_name(), exc, exc_info=exc)
            except asyncio.CancelledError:
                pass
        for t in loop_tasks:
            t.add_done_callback(_on_task_done)
        try:
            await asyncio.gather(*loop_tasks, return_exceptions=True)
        except asyncio.CancelledError:
            pass
        finally:
            logging.info("Shutting down ...")
            for m in started:
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
