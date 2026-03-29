"""
sites.py — site list for autodash.
Copy this file to sites.py and fill in your details.
See README.md for full documentation of all options.
"""

from config import SiteConfig, LoginStep

SITES: list[SiteConfig] = [
    SiteConfig(
        name          = "EXAMPLE",
        url           = "https://example.com",
        username      = "USERNAME",
        password      = "PASSWORD",

        fullscreen    = False,          # True = kiosk mode (ignores position/size below)
        window_x      = 0,
        window_y      = 0,
        window_width  = 1280,
        window_height = 900,

        post_login_url = "",            # navigate here after login; "" = stay on landing page

        auto_login = True,              # set to False for public pages that need no login

        # Simple login — auto-detected selectors (works for most sites)
        username_selector = "input[type='text'], input[name='username'], input[name='email'], input[id*='user'], input[id*='email']",
        password_selector = "input[type='password']",
        submit_selector   = "button[type='submit'], input[type='submit']",

        # Multi-step or extra-field login — replaces the simple selectors above when set.
        # See README.md § "Multi-step and multi-field login" for details.
        # login_steps = [
        #     LoginStep("fill",     "input[name='loginfmt']", "{username}"),
        #     LoginStep("click",    "input[type='submit']"),
        #     LoginStep("wait_for", "input[type='password']"),
        #     LoginStep("fill",     "input[type='password']", "{password}"),
        #     LoginStep("click",    "input[type='submit']"),
        # ],

        logged_in_selector     = "",   # CSS selector present only when logged in
        logged_in_url_fragment = "",   # URL fragment present only when logged in

        availability_check_selector = "",  # CSS selector checked via headless browser before opening; e.g. "#login-form"

        schedule = [],   # always active; see README.md § Scheduling for time-window syntax
        # schedule = [("Mon-Fri", "09:00", "17:00")],
        # schedule = [("Mon-Fri", "08:00", "18:00"), ("Sat", "09:00", "13:00")],
    ),
]
