import asyncio
import json
import os
import platform
import subprocess
import threading
from pathlib import Path
from typing import List, Union

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

import autostart as _autostart
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

_pyautogui_lock = threading.Lock()
_scheduler_paused: bool = False


class ClickRequest(BaseModel):
    x: float          # relative ratio 0.0–1.0
    y: float          # relative ratio 0.0–1.0
    monitor: int = 1  # mss monitor index (1 = first physical monitor)
    button: str = "left"


class TypeRequest(BaseModel):
    text: str
    method: str = "paste"   # "paste" = clipboard ctrl+v, "type" = key-by-key
    send_enter: bool = False


class KeyRequest(BaseModel):
    key: Union[str, List[str]]


api = FastAPI(title="autodash config")


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
        "os":         platform.system(),
        "os_version": platform.version(),
        "os_release": platform.release(),
        "machine":    platform.machine(),
        "hostname":   platform.node(),
        "python":     sys.version.split()[0],
    })


@api.get("/autostart")
def api_get_autostart(_: None = Depends(require_auth)):
    return JSONResponse(content={
        "enabled":   _autostart.is_enabled(),
        "supported": _autostart.supported(),
    })


@api.post("/autostart")
async def api_set_autostart(request: Request, _: None = Depends(require_auth)):
    body = await request.json()
    if body.get("enabled"):
        _autostart.enable()
    else:
        _autostart.disable()
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
