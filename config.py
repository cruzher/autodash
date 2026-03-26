"""
config.py - SiteConfig dataclass definition
============================================
Imported by both sites.py (for configuration) and monitor.py (for type hints).
"""

from dataclasses import dataclass, field


@dataclass
class SiteConfig:
    name:     str
    url:      str
    username: str
    password: str

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