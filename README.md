# autodash

A lightweight dashboard monitor that opens one or more web dashboards in dedicated Chromium windows, logs in automatically, keeps sessions alive, and self-heals if a window is closed or a session expires. When internet connectivity is lost every window is replaced by a fullscreen offline notice and resumes automatically once the connection is restored.

---

## Requirements

- Linux (tested) or Windows
- Python 3.9+
- `python3-venv`
- `xdotool` and `wmctrl` (Linux only — for window positioning)

All Python dependencies are installed automatically by the bootstrap script.

---

## Quick start

```bash
bash start.sh
```

The script can be called from any working directory. It will always resolve paths relative to its own location.

On first run it will:
1. Install `xdotool` via `apt-get` if missing (Linux)
2. Create a `.venv` virtual environment
3. Install Python dependencies from `requirements.txt`
4. Download the Playwright Chromium browser
5. Start the monitor

---

## Configuration

### 1. Copy the sample and edit it

```bash
cp sample-sites.py sites.py
```

Edit `sites.py` and fill in one `SiteConfig` entry per dashboard. Each entry opens one browser window.

### 2. `SiteConfig` fields

| Field | Default | Description |
|---|---|---|
| `name` | *(required)* | Label used in logs |
| `url` | *(required)* | URL to open (login page) |
| `username` | *(required)* | Login username / email |
| `password` | *(required)* | Login password |
| `fullscreen` | `False` | Fill entire screen (kiosk mode) |
| `window_x` | `0` | Window left position in pixels |
| `window_y` | `0` | Window top position in pixels |
| `window_width` | `1280` | Window width in pixels |
| `window_height` | `900` | Window height in pixels |
| `post_login_url` | `""` | Navigate here after login; leave empty to stay on the landing page |
| `username_selector` | *(auto)* | CSS selector for the username field |
| `password_selector` | *(auto)* | CSS selector for the password field |
| `submit_selector` | *(auto)* | CSS selector for the submit button |
| `logged_in_selector` | `""` | CSS selector that only exists when logged in |
| `logged_in_url_fragment` | `""` | URL path/fragment that indicates an authenticated page |
| `extra_username_selectors` | `[]` | Additional fallback CSS selectors for the username field |
| `extra_password_selectors` | `[]` | Additional fallback CSS selectors for the password field |

### 3. Example with two windows side by side

```python
from config import SiteConfig

SITES = [
    SiteConfig(
        name     = "Grafana",
        url      = "https://grafana.example.com/login",
        username = "admin",
        password = "secret",
        window_x = 0, window_y = 0,
        window_width = 960, window_height = 1080,
        logged_in_url_fragment = "/d/",
    ),
    SiteConfig(
        name     = "Home Assistant",
        url      = "https://ha.example.com",
        username = "admin",
        password = "secret",
        window_x = 960, window_y = 0,
        window_width = 960, window_height = 1080,
        logged_in_selector = ".toolbar-title",
    ),
]
```

---

## Timing

Timing constants are at the top of `monitor.py`:

| Constant | Default | Description |
|---|---|---|
| `REFRESH_INTERVAL_SECONDS` | `600` | Full page reload interval |
| `CHECK_INTERVAL_SECONDS` | `30` | How often to check session / connectivity |
| `RECONNECT_DELAY_SECONDS` | `5` | Wait before reopening a closed window |
| `POSITION_CHECK_SECONDS` | `10` | How often to check window position (Linux) |
| `POSITION_TOLERANCE_PX` | `5` | Pixel drift allowed before correcting the window |

---

## Offline behaviour

When internet connectivity is lost all browser windows navigate to a local `offline.html` page that displays a "No Internet Connection" notice. The monitor polls for connectivity every `CHECK_INTERVAL_SECONDS` seconds and automatically resumes normal operation once the connection is restored.

Connectivity is checked by attempting a TCP connection to `8.8.8.8:53` (Google DNS). This can be changed via `INTERNET_CHECK_HOST` / `INTERNET_CHECK_PORT` in `monitor.py`.

---

## Window management (Linux)

On Linux the monitor uses `xdotool` and `wmctrl` to position and track windows. Install them if not already present:

```bash
sudo apt install xdotool wmctrl
```

For fullscreen / kiosk mode set `fullscreen=True` in the site config; window position and size fields are ignored in that case.

> **Note:** Run the monitor as a non-root user where possible. Running as root causes Chromium to display a `--no-sandbox` security warning.

---

## File overview

| File | Purpose |
|---|---|
| `monitor.py` | Main monitor — browser management, login, session keeping |
| `config.py` | `SiteConfig` dataclass definition |
| `sites.py` | Your site list (created from `sample-sites.py`) |
| `sample-sites.py` | Template for `sites.py` |
| `offline.html` | Fullscreen page shown when internet is unavailable |
| `start.sh` | Bootstrap and launch script |
| `requirements.txt` | Python dependencies |
