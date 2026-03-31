# autodash

A lightweight dashboard monitor that opens one or more web dashboards in dedicated Chromium windows, logs in automatically, keeps sessions alive, and self-heals if a window is closed or a session expires. When internet connectivity is lost every window is replaced by a fullscreen offline notice and resumes automatically once the connection is restored.

---

## Requirements

- Git
- Python 3.9+
- Linux: `python3-venv`, `xdotool`, `wmctrl`
- Windows: Python from [python.org](https://www.python.org/) with "Add to PATH" checked

All other dependencies are installed automatically by the setup script.

---

## Installation

### 1. Install Git

**Linux (debian)**
```bash
sudo apt install git
```

**Windows**
```powershell
winget install --id Git.Git -e --source winget
```

**Windows — Visual C++ Redistributable** (required by Playwright)
```powershell
winget install --id Microsoft.VCRedist.2015+.x64 -e
```

### 2. Clone the repository

```bash
git clone https://github.com/cruzher/autodash.git
cd autodash
```

### 3. Install dependencies and start

**Linux** — installs dependencies and starts the monitor:
```bash
bash start.sh
```

**Windows** — installs dependencies:
```powershell
.\install.ps1
```

> If PowerShell blocks the script with an execution policy error, run once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

Then start the monitor:
```powershell
.venv\Scripts\python monitor.py
```

On Linux, re-running `start.sh` is safe — dependency installation is skipped automatically if nothing has changed.

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
| `zoom` | `1.0` | Browser zoom level (`1.0` = 100 %, `1.5` = 150 %, `0.8` = 80 %, etc.) |
| `window_x` | `0` | Window left position in pixels |
| `window_y` | `0` | Window top position in pixels |
| `window_width` | `1280` | Window width in pixels |
| `window_height` | `900` | Window height in pixels |
| `post_login_url` | `""` | Navigate here after login; leave empty to stay on the landing page |
| `schedule` | `[]` | List of active time windows (see [Scheduling](#scheduling)). Empty = always active |
| `username_selector` | *(auto)* | CSS selector for the username field |
| `password_selector` | *(auto)* | CSS selector for the password field |
| `submit_selector` | *(auto)* | CSS selector for the submit button |
| `logged_in_selector` | `""` | CSS selector that only exists when logged in |
| `logged_in_url_fragment` | `""` | URL path/fragment that indicates an authenticated page |
| `extra_username_selectors` | `[]` | Additional fallback CSS selectors for the username field |
| `extra_password_selectors` | `[]` | Additional fallback CSS selectors for the password field |
| `auto_login` | `True` | Set to `False` for public pages that need no login |
| `availability_check` | `True` | Set to `False` to skip availability checking for this site |
| `availability_check_selector` | `""` | CSS selector verified via headless browser before opening (more reliable than HTTP for JS-heavy sites); leave empty to use HTTP check only |

### 3. Multi-step and multi-field login (`login_steps`)

Some sites show the username and password on separate pages (e.g. Microsoft, Google, many SSO portals), or include extra fields such as a domain or PIN. Use `login_steps` for these cases. When set it replaces the simple `username_selector` / `password_selector` / `submit_selector` flow entirely.

Import `LoginStep` alongside `SiteConfig`:

```python
from config import SiteConfig, LoginStep
```

Each `LoginStep` takes an **action**, a **CSS selector**, and an optional **value**:

| Action | Behaviour |
|---|---|
| `"fill"` | Finds the field, clears it, and types the value. Use `{username}` or `{password}` as placeholders. |
| `"click"` | Clicks the element and waits 1 second for the page to react. |
| `"press"` | Presses a key. `value` is the key name (e.g. `"Enter"`, `"Tab"`); defaults to `Enter`. When `selector` is omitted the key is sent to whatever element is currently focused. |
| `"wait_for"` | Waits up to 15 seconds for the selector to appear before continuing. |

**Multi-step example** (username page → Next → password page → Sign in):

```python
SiteConfig(
    ...
    login_steps = [
        LoginStep("fill",     "input[name='loginfmt']", "{username}"),
        LoginStep("press",    value="Enter"),
        LoginStep("wait_for", "input[type='password']"),
        LoginStep("fill",     "input[type='password']", "{password}"),
        LoginStep("press",    value="Enter"),
    ],
)
```

Use `"click"` instead of `"press"` if the page has a visible submit button you want to click directly.


**Extra field example** (domain on the same page):

```python
login_steps = [
    LoginStep("fill",  "input[name='username']", "{username}"),
    LoginStep("fill",  "input[type='password']", "{password}"),
    LoginStep("fill",  "input[name='domain']",   "CORP"),
    LoginStep("click", "button[type='submit']"),
]
```

#### Finding the right selector

Right-click the field in the browser → **Inspect** and look at the `<input>` element's attributes. Common patterns:

| Attribute | Selector example |
|---|---|
| `name` attribute | `input[name='Username']` |
| `id` attribute | `#username` |
| `placeholder` text | `input[placeholder='Username']` |
| `aria-label` | `input[aria-label='Username']` |
| ARIA role + name | `role=textbox[name='Username']` |

> **Note:** `textbox` is an ARIA role, not an HTML element. Use `input[...]` for standard HTML fields. The ARIA `role=` syntax is only needed when the element has an explicit `role="textbox"` attribute.

---

### 4. Public pages (no login)

Set `auto_login = False` for sites that do not have a login form. The monitor will still open the page, keep the window alive, and refresh it on the normal schedule — it simply skips all login logic.

```python
SiteConfig(
    name       = "Public Dashboard",
    url        = "https://example.com/public",
    username   = "",
    password   = "",
    auto_login = False,
)
```

---

### 5. Example with two windows side by side

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

## Scheduling

Each site can optionally define a list of active time windows via the `schedule` field. When a site is outside its schedule its window is closed automatically. When no site is scheduled, a fullscreen **"No Dashboard Scheduled"** notice is shown and the display is allowed to sleep. The windows reopen automatically when a schedule window starts.

An empty `schedule` (the default) means the site is **always active** — identical to the pre-scheduling behaviour.

### Entry formats

| Format | Example | Meaning |
|---|---|---|
| `("HH:MM", "HH:MM")` | `("09:00", "17:00")` | Every day, 09:00–17:00 |
| `("day-spec", "HH:MM", "HH:MM")` | `("Mon-Fri", "09:00", "17:00")` | Weekdays only |

**Day specs:**

| Spec | Meaning |
|---|---|
| `"Mon-Fri"` | Monday through Friday |
| `"Sat,Sun"` | Saturday and Sunday |
| `"Mon"` | Monday only |
| `"*"` | Every day |

Multiple windows can be listed in a single schedule:

```python
schedule = [
    ("Mon-Fri", "08:00", "18:00"),
    ("Sat",     "09:00", "13:00"),
]
```

Overnight windows (e.g. `"22:00"` to `"06:00"`) are supported.

### Schedule check interval

The schedule is checked every `SCHEDULE_CHECK_SECONDS` (default `60`) seconds. Windows open/close within one check interval of the boundary time.

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

## Running on boot (Raspberry Pi)

To start autodash automatically when the desktop loads, add an entry to the LXDE autostart file:

```
/home/<username>/.config/lxsession/LXDE-pi/autostart
```

Add this line at the end of the file (create the file if it does not exist):

```
@lxterminal -e /usr/bin/bash /home/<username>/autodash/start.sh
```

Replace the path with the actual location of `start.sh` on your system.

---

## File overview

| File | Purpose |
|---|---|
| `monitor.py` | Main monitor — browser management, login, session keeping |
| `config.py` | `SiteConfig` dataclass definition |
| `sites.py` | Your site list (created from `sample-sites.py`) |
| `sample-sites.py` | Template for `sites.py` |
| `offline.html` | Fullscreen page shown when internet is unavailable |
| `no_schedule.html` | Fullscreen page shown when no site is currently scheduled |
| `start.sh` | Bootstrap and launch script (Linux) |
| `install.ps1` | Dependency install script (Windows) |
| `requirements.txt` | Python dependencies |
