"""
auth.py - Web UI authentication for autodash.

Single-user, file-based. Credentials stored in auth.json (hashed).
Sessions stored in memory (cleared on restart).
"""

import hashlib
import json
import os
import secrets
import time
from pathlib import Path

from fastapi import HTTPException, Request

AUTH_FILE = Path(__file__).parent / "auth.json"
SESSION_TTL = 8 * 3600  # seconds

_sessions: dict[str, float] = {}  # token -> expiry timestamp


# ---- password hashing -------------------------------------------------------

def _hash_password(password: str) -> str:
    """Return 'sha256:<hex-salt>:<hex-key>' using PBKDF2-HMAC-SHA256."""
    salt = os.urandom(16).hex()
    key = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), 260_000
    ).hex()
    return f"sha256:{salt}:{key}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, key_hex = stored.split(":")
        new_key = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 260_000
        ).hex()
        return secrets.compare_digest(new_key, key_hex)
    except Exception:
        return False


# ---- user management --------------------------------------------------------

def user_exists() -> bool:
    return AUTH_FILE.exists() and AUTH_FILE.stat().st_size > 0


def create_user(username: str, password: str) -> None:
    AUTH_FILE.write_text(
        json.dumps({"username": username, "password": _hash_password(password)}, indent=2),
        encoding="utf-8",
    )


def check_credentials(username: str, password: str) -> bool:
    if not user_exists():
        return False
    try:
        data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
        return data["username"] == username and _verify_password(password, data["password"])
    except Exception:
        return False


# ---- session management -----------------------------------------------------

def create_session() -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + SESSION_TTL
    return token


def validate_session(token: str | None) -> bool:
    if not token:
        return False
    expiry = _sessions.get(token)
    if expiry is None or time.time() > expiry:
        _sessions.pop(token, None)
        return False
    return True


def invalidate_session(token: str | None) -> None:
    if token:
        _sessions.pop(token, None)


# ---- FastAPI dependency -----------------------------------------------------

async def require_auth(request: Request) -> None:
    """Raise HTTP 401 if the request has no valid session cookie."""
    token = request.cookies.get("session")
    if not validate_session(token):
        raise HTTPException(status_code=401, detail="Not authenticated")
