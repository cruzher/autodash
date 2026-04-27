"""
monitor.py - Entry point: schedule coordinator and application bootstrap.
"""

import asyncio
import logging
import logging.handlers as _log_handlers
import os
import tempfile
from pathlib import Path

import uvicorn
from playwright.async_api import async_playwright

import settings
from api import WEB_PORT, api
from config import load_sites_json
from display import (
    IS_LINUX,
    IS_WAYLAND,
    check_tools,
    disable_display_sleep,
    display_keepalive,
    enable_display_sleep,
    get_chromium_env,
    wake_display,
)
from scheduler import is_scheduled_now
from site_monitor import SiteMonitor

_SITES_JSON_PATH = Path(__file__).parent / "sites.json"
_LOG_DIR         = Path(__file__).parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_LOG_PATH        = _LOG_DIR / "autodash.log"

SCHEDULE_CHECK_SECONDS = 60

_LOG_FORMAT  = "%(asctime)s  [%(levelname)s]  %(name)s  - %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _setup_logging():
    logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT, datefmt=_LOG_DATEFMT)
    fh = _log_handlers.RotatingFileHandler(
        _LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT))
    logging.getLogger().addHandler(fh)


def _load_sites() -> list:
    if not _SITES_JSON_PATH.exists():
        return []
    return load_sites_json(_SITES_JSON_PATH)


async def _heartbeat_loop():
    log = logging.getLogger("heartbeat")
    while True:
        await asyncio.sleep(settings.heartbeat_interval)
        url = settings.heartbeat_url
        if url:
            try:
                import urllib.request
                urllib.request.urlopen(url, timeout=10)
                log.debug("Heartbeat OK: %s", url)
            except Exception as exc:
                log.warning("Heartbeat failed (%s): %s", url, exc)


class _NoticeWindow:
    """Manages the fullscreen 'no dashboard scheduled' Chromium window."""

    _URL = (Path(__file__).parent / "no_schedule.html").as_uri()

    def __init__(self, pw):
        self._pw      = pw
        self._context = None
        self._log     = logging.getLogger("coordinator")

    async def open(self):
        if self._context is not None:
            try:
                if self._context.pages and not self._context.pages[0].is_closed():
                    return
            except Exception:
                pass
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None

        self._log.info("No monitors active — showing 'No dashboard scheduled' notice.")
        if settings.sleep_when_idle:
            enable_display_sleep()
        launch_env = get_chromium_env()
        args = [
            f"--app={self._URL}",
            "--start-fullscreen",
            "--disable-infobars",
            "--test-type",
            "--no-default-browser-check",
            "--no-first-run",
            "--disable-extensions",
            "--password-store=basic",
        ]
        if IS_WAYLAND:
            args.append("--ozone-platform=wayland")
        try:
            self._context = await self._pw.chromium.launch_persistent_context(
                user_data_dir       = str(Path(tempfile.mkdtemp(prefix="pw_notice_"))),
                headless            = False,
                args                = args,
                ignore_default_args = ["--enable-automation"],
                no_viewport         = True,
                ignore_https_errors = True,
                env                 = launch_env,
            )
        except Exception as exc:
            self._log.error("Failed to open notice window: %s", exc)
            self._context = None

    async def close(self):
        disable_display_sleep()
        wake_display()
        if self._context is None:
            return
        self._log.info("A monitor became active — closing notice window.")
        try:
            await self._context.close()
        except Exception:
            pass
        self._context = None


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

    active_tasks = {}
    was_active   = {m: None for m in monitors}
    sites_mtime  = _SITES_JSON_PATH.stat().st_mtime if _SITES_JSON_PATH.exists() else 0.0
    notice       = _NoticeWindow(pw)

    while True:
        any_active = False

        for m in monitors:
            active = is_scheduled_now(m.cfg.schedule)
            if active:
                any_active = True

            prev = was_active[m]

            if active and (prev is None or not prev):
                existing = active_tasks.get(m)
                if not (existing and not existing.done()):
                    log.info("Starting monitor '%s'.", m.cfg.name)
                    try:
                        await m.start()
                        t = asyncio.create_task(m.run_loop(), name=m.cfg.name)
                        t.add_done_callback(_make_task_done_cb(m.cfg.name, log))
                        active_tasks[m] = t
                    except Exception as exc:
                        log.error("Failed to start '%s': %s", m.cfg.name, exc, exc_info=True)

            elif not active and prev:
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
            await notice.close()
        else:
            await notice.open()

        # Hot-reload sites.json
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

                for name, m in list(old_by_name.items()):
                    if name not in new_by_name:
                        log.info("config: removing '%s'.", name)
                        await _stop_monitor(m)

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


async def main():
    _setup_logging()
    check_tools()
    disable_display_sleep()
    settings.apply(settings.load())
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
        coordinator = asyncio.create_task(
            schedule_coordinator(monitors, pw), name="coordinator"
        )
        keepalive  = asyncio.create_task(display_keepalive(), name="keepalive")
        heartbeat  = asyncio.create_task(_heartbeat_loop(), name="heartbeat")
        web_config = uvicorn.Config(api, host="0.0.0.0", port=WEB_PORT, log_level="warning")
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
