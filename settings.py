import json
from pathlib import Path

_PATH = Path(__file__).parent / "settings.json"

DEFAULTS: dict = {
    "sleep_when_idle":        True,
    "heartbeat_url":          "",
    "heartbeat_interval":     60,
    "auto_update":            True,
    "remote_active_interval": 2,
    "remote_idle_interval":   30,
}

# Runtime state — mutated by apply()
sleep_when_idle: bool = True
heartbeat_url:   str  = ""
heartbeat_interval: int = 60


def load() -> dict:
    if not _PATH.exists():
        return dict(DEFAULTS)
    try:
        return {**DEFAULTS, **json.loads(_PATH.read_text(encoding="utf-8"))}
    except Exception:
        return dict(DEFAULTS)


def apply(s: dict) -> None:
    global sleep_when_idle, heartbeat_url, heartbeat_interval
    sleep_when_idle    = bool(s.get("sleep_when_idle", True))
    heartbeat_url      = str(s.get("heartbeat_url", "") or "")
    heartbeat_interval = max(10, int(s.get("heartbeat_interval", 60)))


def save(body: dict) -> None:
    apply(body)
    _PATH.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
