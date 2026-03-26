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
        name             = "EXAMPLE",
        url              = "https://example.com",
        username         = "USERNAME",
        password         = "PASSWORD",
        fullscreen       = False,
        window_x         = 0,
        window_y         = 0,
        window_width     = 1280,
        window_height    = 900,
        post_login_url   = "https://example.com/loggedin",   # stay on whatever page appears after login
        username_selector      = "input[type='text'], input[name='username'], input[name='email'], input[id*='user'], input[id*='email']",
        password_selector      = "input[type='password']",
        submit_selector        = "button[type='submit'], input[type='submit']",
        logged_in_selector     = "",
        logged_in_url_fragment = "",
    ),
]