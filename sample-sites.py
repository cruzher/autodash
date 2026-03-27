"""
sites.py - Site configuration for monitor.py
=============================================
Add, remove, or edit entries in the SITES list.
Each SiteConfig entry controls one browser window.

fullscreen=True      → window fills the entire screen (ignores window_x/y/width/height)
fullscreen=False     → window uses the position and size you specify

post_login_url       → if set, navigates to this URL after a successful login.
                       leave empty ("") to stay on the post-login landing page.

schedule             → list of active time windows; empty list = always active.
                       Each entry is a 2- or 3-tuple:
                         ("HH:MM", "HH:MM")                  every day
                         ("day-spec", "HH:MM", "HH:MM")      specific days only
                       Day specs: "Mon-Fri", "Sat,Sun", "Mon", "Tue", ..., "*"
                       Examples:
                         schedule = [("Mon-Fri", "09:00", "17:00")]
                         schedule = [("Mon-Fri", "08:00", "18:00"), ("Sat", "08:00", "13:00")]
                         schedule = [("09:00", "17:00")]   # every day, same window
                         schedule = []                     # always active (default)
                       When no site is scheduled a fullscreen notice is shown and
                       the display is allowed to sleep until the next window opens.
"""

from config import SiteConfig

SITES: list[SiteConfig] = [
    SiteConfig(
        name             = "EXAMPLE",
        url              = "https://example.com",
        username         = "USERNAME",
        password         = "PASSWORD",
        fullscreen       = False,
        window_x         = 0,
        window_y         = 0,
        window_width     = 1280,
        window_height    = 900,
        post_login_url   = "https://example.com/loggedin",   # leave "" to stay on landing page
        username_selector      = "input[type='text'], input[name='username'], input[name='email'], input[id*='user'], input[id*='email']",
        password_selector      = "input[type='password']",
        submit_selector        = "button[type='submit'], input[type='submit']",
        logged_in_selector     = "",
        logged_in_url_fragment = "",
        # availability_check_selector: CSS selector that must exist in the fully
        # rendered page (checked via headless Playwright, so JS content is visible).
        # More reliable than a plain HTTP check for JS-heavy sites.
        availability_check_selector = "",  # e.g. "#login-form" or ".dashboard-header"
        schedule               = [],   # always active — replace with time windows to restrict
        # schedule             = [("Mon-Fri", "09:00", "17:00")],
        # schedule             = [("Mon-Fri", "08:00", "18:00"), ("Sat", "09:00", "13:00")],
    ),
]