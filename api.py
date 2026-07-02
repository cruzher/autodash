import asyncio
import json
import os
import platform
import shutil
import socket
import subprocess
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

import autostart as _autostart
import autologin as _autologin
import settings as _settings
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

_SITES_JSON_PATH = Path(__file__).parent / "sites.json"
_UI_HTML_PATH    = Path(__file__).parent / "ui.html"
_LOGIN_HTML_PATH = Path(__file__).parent / "login.html"
_LOG_PATH        = Path(__file__).parent / "logs" / "autodash.log"

WEB_PORT = int(os.environ.get("WEB_PORT", 8080))

_scheduler_paused: bool = False

# Populated by monitor.py with the live list of SiteMonitor instances (same
# list object it mutates), so endpoints here can look up a running site's page.
monitors: list = []

_NOVNC_PATH = Path("/usr/share/novnc")
_WEBSOCKIFY_PORT = 6080
_X11VNC_PORT = 5901
_novnc_process = None   # websockify subprocess
_x11vnc_process = None  # x11vnc subprocess


def _is_raspberry_pi() -> bool:
    try:
        model = Path("/proc/device-tree/model").read_text()
        return "Raspberry Pi" in model
    except OSError:
        return False


api = FastAPI(title="autodash config")

if _NOVNC_PATH.exists():
    from fastapi.staticfiles import StaticFiles
    api.mount("/novnc-static", StaticFiles(directory=str(_NOVNC_PATH)), name="novnc")


@api.on_event("shutdown")
def _on_shutdown():
    for proc in (_novnc_process, _x11vnc_process):
        if proc and proc.poll() is None:
            proc.terminate()


@api.get("/scheduler/pause")
def api_get_scheduler_pause(_: None = Depends(require_auth)):
    return JSONResponse(content={"paused": _scheduler_paused})


@api.post("/scheduler/pause")
async def api_set_scheduler_pause(request: Request, _: None = Depends(require_auth)):
    global _scheduler_paused
    body = await request.json()
    _scheduler_paused = bool(body.get("paused", False))
    return {"ok": True}


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


@api.post("/sites/{name}/pause")
async def api_pause_site(name: str, request: Request, _: None = Depends(require_auth)):
    body = await request.json()
    paused = bool(body.get("paused", False))
    data = json.loads(_SITES_JSON_PATH.read_text(encoding="utf-8"))
    for site in data:
        if site.get("name") == name:
            site["schedule_paused"] = paused
            break
    _SITES_JSON_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True}


@api.get("/settings")
def api_get_settings(_: None = Depends(require_auth)):
    return JSONResponse(content=_settings.load())


@api.put("/settings")
async def api_put_settings(request: Request, _: None = Depends(require_auth)):
    body = await request.json()
    _settings.save(body)
    return {"ok": True}


@api.get("/sysinfo")
def api_get_sysinfo(_: None = Depends(require_auth)):
    import sys
    return JSONResponse(content={
        "os":              platform.system(),
        "os_version":      platform.version(),
        "os_release":      platform.release(),
        "machine":         platform.machine(),
        "hostname":        platform.node(),
        "python":          sys.version.split()[0],
        "is_raspberry_pi": _is_raspberry_pi(),
    })


@api.get("/autostart")
def api_get_autostart(_: None = Depends(require_auth)):
    return JSONResponse(content={
        "enabled":   _autostart.is_enabled(),
        "supported": _autostart.supported(),
    })


@api.get("/autologin")
def api_get_autologin(_: None = Depends(require_auth)):
    return JSONResponse(content={
        "enabled":   _autologin.is_enabled(),
        "supported": _autologin.supported(),
    })


@api.post("/autostart")
async def api_set_autostart(request: Request, _: None = Depends(require_auth)):
    body = await request.json()
    try:
        if body.get("enabled"):
            _autostart.enable()
        else:
            _autostart.disable()
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})
    return {"ok": True}


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
    if validate_session(request.cookies.get("session")):
        return RedirectResponse("/ui")
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


@api.get("/sites/{name}/page-screenshot")
async def api_site_page_screenshot(name: str, _: None = Depends(require_auth)):
    """Return a PNG screenshot of the given site's live page.

    Unlike /screenshot (a physical-display grab), this is taken directly from
    the site's Playwright page, so pixel coordinates match click_xy exactly -
    no window position or OS display-scaling correction needed.
    """
    m = next((m for m in monitors if m.cfg.name == name), None)
    if m is None or m.page is None:
        return JSONResponse(status_code=404, content={"detail": "Site is not currently running"})
    try:
        png = await m.page.screenshot()
        return Response(content=png, media_type="image/png")
    except Exception as exc:
        return JSONResponse(status_code=503, content={"detail": str(exc)})


@api.post("/sites/{name}/page-click")
async def api_site_page_click(name: str, request: Request, _: None = Depends(require_auth)):
    """Perform a real mouse.click(x, y) on the given site's live page.

    Used by the click_xy coordinate picker when the user opts to also apply
    the click (e.g. to advance a multi-step sequence to its next state).
    """
    body = await request.json()
    try:
        x, y = float(body["x"]), float(body["y"])
    except (KeyError, TypeError, ValueError):
        return JSONResponse(status_code=400, content={"detail": "x and y are required numbers"})
    m = next((m for m in monitors if m.cfg.name == name), None)
    if m is None or m.page is None:
        return JSONResponse(status_code=404, content={"detail": "Site is not currently running"})
    try:
        await m.page.mouse.click(x, y)
    except Exception as exc:
        return JSONResponse(status_code=503, content={"detail": str(exc)})
    return {"ok": True}


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


def _check_port(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            return True
    except OSError:
        return False


def _wait_for_port(port: int, retries: int = 10, delay: float = 0.3) -> bool:
    for _ in range(retries):
        time.sleep(delay)
        if _check_port(port):
            return True
    return False


def _start_x11vnc():
    global _x11vnc_process
    if _x11vnc_process is not None and _x11vnc_process.poll() is None:
        return None
    x11 = shutil.which("x11vnc")
    if not x11:
        return "x11vnc not found — run: sudo apt install x11vnc"
    if _check_port(_X11VNC_PORT):
        return None  # already something running on the port
    log = open(_LOG_PATH, "a", encoding="utf-8")
    _x11vnc_process = subprocess.Popen(
        [x11, "-nopw", "-forever", "-display", ":0", "-rfbport", str(_X11VNC_PORT)],
        stdout=log, stderr=log,
    )
    if not _wait_for_port(_X11VNC_PORT):
        if _x11vnc_process.poll() is not None:
            return "x11vnc exited immediately — check autodash.log"
        return "x11vnc did not bind port in time"
    return None


@api.get("/novnc/status")
def api_novnc_status(_: None = Depends(require_auth)):
    if not _is_raspberry_pi():
        return JSONResponse(status_code=403, content={"error": "Raspberry Pi only"})
    proxy_running = _novnc_process is not None and _novnc_process.poll() is None
    return JSONResponse(content={
        "x11vnc_available": bool(shutil.which("x11vnc")),
        "files_available":  _NOVNC_PATH.exists(),
        "proxy_running":    proxy_running,
        "proxy_port":       _WEBSOCKIFY_PORT,
    })


@api.post("/novnc/start")
def api_novnc_start(_: None = Depends(require_auth)):
    if not _is_raspberry_pi():
        return JSONResponse(status_code=403, content={"error": "Raspberry Pi only"})
    global _novnc_process
    if _novnc_process is not None and _novnc_process.poll() is None:
        return JSONResponse(content={"port": _WEBSOCKIFY_PORT})
    err = _start_x11vnc()
    if err:
        return JSONResponse(status_code=503, content={"error": err})
    ws = shutil.which("websockify")
    if not ws:
        return JSONResponse(status_code=503, content={"error": "websockify not found — run: sudo apt install novnc"})
    try:
        log = open(_LOG_PATH, "a", encoding="utf-8")
        _novnc_process = subprocess.Popen(
            [ws, str(_WEBSOCKIFY_PORT), f"localhost:{_X11VNC_PORT}"],
            stdout=log, stderr=log,
        )
        if not _wait_for_port(_WEBSOCKIFY_PORT):
            if _novnc_process.poll() is not None:
                return JSONResponse(status_code=500, content={"error": "websockify exited immediately — check autodash.log"})
        return JSONResponse(content={"port": _WEBSOCKIFY_PORT})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@api.post("/novnc/stop")
def api_novnc_stop(_: None = Depends(require_auth)):
    if not _is_raspberry_pi():
        return JSONResponse(status_code=403, content={"error": "Raspberry Pi only"})
    global _novnc_process, _x11vnc_process
    for proc in (_novnc_process, _x11vnc_process):
        if proc and proc.poll() is None:
            proc.terminate()
    _novnc_process = None
    _x11vnc_process = None
    return {"ok": True}
