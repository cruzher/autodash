"""
sites.py - Site configuration for monitor.py
=============================================
Add, remove, or edit entries in the SITES list.
Each SiteConfig entry controls one browser window.

fullscreen=True      → window fills the entire screen (ignores window_x/y/width/height)
fullscreen=False     → window uses the position and size you specify

post_login_url       → if set, navigates to this URL after a successful login.
                       leave empty ("") to stay on the post-login landing page.
"""

from config import SiteConfig

SITES: list[SiteConfig] = [
    SiteConfig(
        name             = "COMET",
        url              = "https://backup2.hybridprotect.net",
        username         = "dashboard",
        password         = "aet0bfa-hey3TPMfhn",
        fullscreen       = False,
        window_x         = -265,
        window_y         = -15,
        window_width     = 1280,
        window_height    = 900,
        post_login_url   = "https://backup2.hybridprotect.net/#/recentactivity",   # stay on whatever page appears after login
        username_selector      = "input[type='text'], input[name='username'], input[name='email'], input[id*='user'], input[id*='email']",
        password_selector      = "input[type='password']",
        submit_selector        = "button[type='submit'], input[type='submit']",
        logged_in_selector     = "",
        logged_in_url_fragment = "",
    ),
    SiteConfig(
        name             = "NAKIVO",
        url              = "https://backup1.hybridprotect.net",   # <- change to second site URL
        username         = "dashboard",
        password         = "aet0bfa-hey3TPMfhn",
        fullscreen       = False,
        window_x         = 1300,
        window_y         = 0,
        window_width     = 1280,
        window_height    = 900,
        post_login_url   = "",   # <- go here after login
        username_selector      = "input[type='text'], input[name='username'], input[name='email'], input[id*='user'], input[id*='email']",
        password_selector      = "input[type='password']",
        submit_selector        = "button[type='submit'], input[type='submit']",
        logged_in_selector     = "",
        logged_in_url_fragment = "",
    ),
]