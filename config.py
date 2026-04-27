"""
config.py - SiteConfig dataclass and JSON serialisation helpers.
"""

import json
import pathlib
from dataclasses import dataclass, field, fields


@dataclass
class LoginStep:
    """One action in a multi-step or multi-field login sequence.

    action   : "fill" | "click" | "wait_for"
    selector : CSS selector for the target element
    value    : text to type (fill only); {username} and {password} are substituted
    """
    action:   str
    selector: str = ""
    value:    str = ""


@dataclass
class SiteConfig:
    name:        str
    url:         str
    username:    str
    password:    str
    totp_secret: str = ""

    # Window geometry (x, y, width, height) — ignored when fullscreen=True
    window_x:      int = 0
    window_y:      int = 0
    window_width:  int = 1280
    window_height: int = 900

    # Set to True to launch this window in fullscreen (kiosk-style)
    fullscreen: bool = False


    # Optional: navigate to this URL after a successful login.
    # Leave empty to stay on whatever page the site lands on after login.
    post_login_url: str = ""
    post_login_enabled: bool = False

    # ── Login-form selectors (CSS) ───────────────────────────────────────────
    username_selector: str = (
        "input[type='text'], input[name='username'], "
        "input[id*='user'], input[id*='email']"
    )
    password_selector: str = "input[type='password']"
    submit_selector:   str = (
        "button[type='submit'], input[type='submit'], "
        "button:has-text('Login'), button:has-text('Sign in')"
    )

    # ── Logged-in detection ──────────────────────────────────────────────────
    # CSS selector that ONLY exists when logged in (e.g. "#logout-btn").
    # Leave empty to fall back to "password field has disappeared".
    logged_in_selector: str = ""

    # URL fragment/path that indicates an authenticated page (e.g. "/dashboard").
    # Leave empty to skip URL-based detection.
    logged_in_url_fragment: str = ""

    # Extra fallback selectors tried after the primary ones above
    extra_username_selectors: list = field(default_factory=list)
    extra_password_selectors: list = field(default_factory=list)

    # ── Login control ───────────────────────────────────────────────────────
    # Set to False for sites that do not require a login (e.g. public dashboards).
    auto_login: bool = True

    # ── Multi-step / multi-field login ───────────────────────────────────────
    # When set, replaces the simple username/password/submit flow entirely.
    # Each LoginStep is one action: fill a field, click an element, or wait
    # for an element to appear. Leave empty to use the simple flow (default).
    login_steps: list = field(default_factory=list)

    # ── Post-login steps ─────────────────────────────────────────────────────
    # Actions to run after login is verified and post_login_url navigated to.
    post_login_steps: list = field(default_factory=list)

    # ── Availability check ───────────────────────────────────────────────────
    # Set to False to disable availability checking entirely for this site.
    availability_check: bool = True

    # "http"     — HTTP response only (fast, no browser needed)
    # "selector" — HTTP check followed by a headless Playwright session that
    #              verifies availability_check_selector exists in the rendered DOM.
    availability_check_mode: str = "http"

    # CSS selector verified by the headless browser when mode is "selector".
    # Example: availability_check_selector = "#login-form"
    # Example: availability_check_selector = ".dashboard-header"
    availability_check_selector: str = ""

    # ── Schedule ─────────────────────────────────────────────────────────────
    # List of active time windows.  Empty list (default) = always active.
    # Each entry is a 2- or 3-tuple:
    #   ("HH:MM", "HH:MM")                  — active every day
    #   ("day-spec", "HH:MM", "HH:MM")      — restricted to matching days
    # Day specs: "Mon-Fri", "Sat,Sun", "Mon", "Tue", …, "*" (every day)
    # Examples:
    #   schedule = [("Mon-Fri", "09:00", "17:00")]
    #   schedule = [("Mon-Fri", "08:00", "18:00"), ("Sat", "08:00", "13:00")]
    #   schedule = [("09:00", "17:00")]        # every day, 9 to 5
    schedule: list = field(default_factory=list)

    # ── Page refresh ─────────────────────────────────────────────────────────
    # Set auto_refresh to False to disable automatic page reloading for this site.
    # refresh_interval is how often (in seconds) the page is reloaded; min 60.
    auto_refresh:     bool = True
    refresh_interval: int  = 600


# ---------------------------------------------------------------------------
# JSON serialisation helpers
# ---------------------------------------------------------------------------

def load_sites_json(path) -> list:
    """Load SITES from a JSON file and return list[SiteConfig]."""
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    sites = []
    for s in data:
        s = dict(s)
        steps = [LoginStep(**step) for step in s.pop("login_steps", [])]
        post_login_steps = [LoginStep(**step) for step in s.pop("post_login_steps", [])]
        # schedule entries are stored as lists in JSON; convert back to tuples
        schedule = [tuple(entry) for entry in s.pop("schedule", [])]
        known = {f.name for f in fields(SiteConfig)}
        s = {k: v for k, v in s.items() if k in known}
        sites.append(SiteConfig(**s, login_steps=steps, post_login_steps=post_login_steps, schedule=schedule))
    return sites


