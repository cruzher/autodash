import asyncio
import json
import logging
import os
import re
from pathlib import Path
from urllib.parse import quote as _url_quote

import pyotp
from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
)

from connectivity import check_internet, check_site_available
from display import (
    IS_LINUX,
    find_window_id,
    fit_viewport_to_window,
    force_window_geometry,
    get_window_geometry,
    position_window,
)

_OFFLINE_URL          = (Path(__file__).parent / "offline.html").as_uri()
_NO_SCHEDULE_URL      = (Path(__file__).parent / "no_schedule.html").as_uri()
_SITE_UNAVAILABLE_URL = (Path(__file__).parent / "site_unavailable.html").as_uri()

CHECK_INTERVAL_SECONDS  = 30
RECONNECT_DELAY_SECONDS = 5
POSITION_CHECK_SECONDS  = 10
POSITION_TOLERANCE_PX   = 5


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
        self._stable_geom = None
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
            self._window_id   = None
            self._stable_geom = None
            return
        if self._stable_geom is None:
            self._stable_geom = geom
        x, y, w, h = geom
        ex, ey, ew, eh = self._stable_geom
        if max(abs(x - ex), abs(y - ey), abs(w - ew), abs(h - eh)) > POSITION_TOLERANCE_PX:
            self.log.warning(
                "Window drifted to (%d,%d) %dx%d - expected (%d,%d) %dx%d - correcting ...",
                x, y, w, h, ex, ey, ew, eh,
            )
            force_window_geometry(self.cfg, self._window_id, self.log)
            await asyncio.sleep(0.3)
            await fit_viewport_to_window(self.page)
            settled = get_window_geometry(self._window_id)
            if settled:
                self._stable_geom = settled

    async def close_window(self):
        """Close the browser window. Called by the schedule coordinator."""
        self._closed = True
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
        """Launch a temporary headless browser and verify availability_check_selector exists."""
        if self.cfg.availability_check_mode != "selector" or not self.cfg.availability_check_selector:
            return True
        browser = None
        try:
            browser = await self.pw.chromium.launch(headless=True)
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
        await position_window(self.cfg, self.page)

    def _resolve_locator(self, selector: str):
        """Support role=button[name="Sign In"] syntax in addition to CSS/XPath."""
        m = re.fullmatch(
            r'role=([a-zA-Z]+)(?:\[name=["\']?(.*?)["\']?\])?',
            selector.strip(),
        )
        if m:
            role, name = m.group(1), m.group(2)
            return self.page.get_by_role(role, name=name) if name else self.page.get_by_role(role)
        return self.page.locator(selector)

    async def _run_steps(self, steps, label: str, step_timeout: int, wait_timeout: int = None):
        """Execute a list of LoginStep objects. Used for both login and post-login flows."""
        if wait_timeout is None:
            wait_timeout = step_timeout
        totp_token = pyotp.TOTP(self.cfg.totp_secret).now() if self.cfg.totp_secret else ""
        subs = {
            "{username}": self.cfg.username,
            "{password}": self.cfg.password,
            "{totp}":     totp_token,
        }
        for step in steps:
            value = step.value
            for k, v in subs.items():
                value = value.replace(k, v)

            if step.action == "fill":
                loc = self._resolve_locator(step.selector).first
                try:
                    await loc.wait_for(state="visible", timeout=step_timeout)
                    await loc.click()
                    await loc.fill(value)
                except PlaywrightTimeoutError:
                    self.log.error("%s: element not found: %s", label, step.selector)
                    return

            elif step.action == "click":
                loc = self._resolve_locator(step.selector).first
                try:
                    await loc.wait_for(state="visible", timeout=step_timeout)
                    await loc.click()
                    await asyncio.sleep(1)
                except PlaywrightTimeoutError:
                    self.log.error("%s: element not found: %s", label, step.selector)
                    return

            elif step.action == "press":
                if step.selector:
                    loc = self._resolve_locator(step.selector).first
                    try:
                        await loc.wait_for(state="visible", timeout=step_timeout)
                        await loc.press(value or "Enter")
                    except PlaywrightTimeoutError:
                        self.log.error("%s: element not found: %s", label, step.selector)
                        return
                else:
                    await self.page.keyboard.press(value or "Enter")
                await asyncio.sleep(1)

            elif step.action == "wait_for":
                loc = self._resolve_locator(step.selector)
                try:
                    await loc.first.wait_for(state="visible", timeout=wait_timeout)
                except PlaywrightTimeoutError:
                    self.log.error(
                        "%s: timed out waiting for: %s (url: %s)",
                        label, step.selector, self.page.url,
                    )
                    return

            else:
                self.log.warning("%s: unknown action '%s' — skipping.", label, step.action)

    async def login(self):
        self.log.info("Attempting login ...")
        if self.cfg.login_steps:
            await self._run_steps(
                self.cfg.login_steps, "Login step",
                step_timeout=10_000, wait_timeout=15_000,
            )
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
            if self.page.url.rstrip("/") != self.cfg.post_login_url.rstrip("/"):
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
            await self._run_steps(self.cfg.post_login_steps, "Post-login step", step_timeout=30_000)

    async def is_logged_in(self):
        try:
            if self.page is None or self.page.is_closed():
                return False
            if self.cfg.logged_in_selector:
                el = await self.page.query_selector(self.cfg.logged_in_selector)
                if el:
                    self.log.info(
                        "is_logged_in: yes — selector '%s' found on %s",
                        self.cfg.logged_in_selector, self.page.url,
                    )
                    return True
                self.log.info(
                    "is_logged_in: no — selector '%s' not found on %s",
                    self.cfg.logged_in_selector, self.page.url,
                )
            if self.cfg.logged_in_url_fragment:
                if self.cfg.logged_in_url_fragment in self.page.url:
                    self.log.info(
                        "is_logged_in: yes — URL fragment '%s' matched in %s",
                        self.cfg.logged_in_url_fragment, self.page.url,
                    )
                    return True
                self.log.info(
                    "is_logged_in: no — URL fragment '%s' not found in %s",
                    self.cfg.logged_in_url_fragment, self.page.url,
                )
            if not self.cfg.logged_in_selector and not self.cfg.logged_in_url_fragment:
                pw_field = await self.page.query_selector(self.cfg.password_selector)
                if pw_field is None:
                    self.log.info(
                        "is_logged_in: yes — password selector '%s' absent from %s (fallback)",
                        self.cfg.password_selector, self.page.url,
                    )
                    return True
                self.log.info(
                    "is_logged_in: no — password selector '%s' still present on %s (fallback)",
                    self.cfg.password_selector, self.page.url,
                )
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
