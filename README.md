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

Open the web UI in a browser:

```
http://<machine-ip>:8080/ui
```

On the first visit you will be prompted to create a username and password. Subsequent visits require those credentials to log in (sessions expire after 8 hours).

Add one entry per dashboard. Each entry opens one Chromium window. Changes are picked up automatically within 60 seconds — no restart needed.

> The port defaults to `8080`. Override with the `WEB_PORT` environment variable:
> ```
> WEB_PORT=9090 python monitor.py
> ```

---

## Multi-step login

Some sites split the login process across multiple pages or use non-standard form layouts (e.g. username on one page, password on the next, or a modal that appears after clicking a button). The multi-step login feature lets you define a custom sequence of actions that replaces the standard username/password/submit flow entirely.

### How to configure

Open the web UI, expand a site, and scroll to the **Multi-step login** section (visible when **Auto login** is enabled). Click **+ Add step** to add actions one at a time. Each step has three fields:

| Field | Description |
|---|---|
| Action | What to do: `fill`, `click`, `wait_for`, or `press` |
| CSS selector | The element to target (optional for `press`) |
| Value | Text to type (`fill`), key name (`press`), or empty (`click` / `wait_for`) |

Use `{username}` and `{password}` as placeholders in the **Value** field — they are substituted with the credentials stored for that site.

### Actions

| Action | What it does |
|---|---|
| `fill` | Clicks the element then types the given value into it |
| `click` | Clicks the element and waits 1 second |
| `wait_for` | Pauses until the element appears in the DOM (timeout: 15 s) |
| `press` | Presses a keyboard key on the element (or the whole page if no selector) |

### Examples

**Standard two-field form (equivalent to the built-in flow)**
```
fill    input[name='username']      {username}
fill    input[type='password']      {password}
click   button[type='submit']
```

**Username on page 1, password on page 2**
```
fill    input[name='email']         {username}
click   button[type='submit']
wait_for  input[type='password']
fill    input[type='password']      {password}
press   input[type='password']      Enter
```

**Login behind a button that opens a modal**
```
click   #open-login-modal
wait_for  #login-modal input[name='user']
fill    #login-modal input[name='user']      {username}
fill    #login-modal input[name='pass']      {password}
click   #login-modal button.submit
```

> When `login_steps` is non-empty it replaces the standard selector-based flow completely. The **Username selector**, **Password selector**, and **Submit selector** fields are ignored.

---

## Scheduling

Each site can optionally be given one or more active time windows. When a site is outside its schedule its window is closed automatically. When no site is scheduled, a fullscreen **"No Dashboard Scheduled"** notice is shown. The windows reopen automatically when a schedule window starts.

Schedules are configured in the web UI. Overnight windows (e.g. 22:00–06:00) are supported.

---

## Offline behaviour

When internet connectivity is lost all browser windows navigate to a local offline page. The monitor polls for connectivity every 30 seconds and automatically resumes normal operation once the connection is restored.

---

## Window management (Linux)

On Linux the monitor uses `xdotool` and `wmctrl` to position and track windows. Install them if not already present:

```bash
sudo apt install xdotool wmctrl
```

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
| `monitor.py` | Main monitor — browser management, login, session keeping, web API |
| `config.py` | `SiteConfig` dataclass and JSON helpers |
| `auth.py` | Web UI authentication — password hashing and session management |
| `auth.json` | Hashed web UI credentials (created on first login setup) |
| `sites.json` | Site list — managed via the web UI |
| `settings.json` | Global settings — managed via the web UI |
| `ui.html` | Web-based configuration editor (served at `/ui`) |
| `login.html` | Web UI login page |
| `offline.html` | Fullscreen page shown when internet is unavailable |
| `no_schedule.html` | Fullscreen page shown when no site is currently scheduled |
| `site_unavailable.html` | Fullscreen page shown when a site cannot be reached |
| `start.sh` | Bootstrap and launch script (Linux) |
| `install.ps1` | Dependency install script (Windows) |
| `uninstall.ps1` | Remove startup entry and virtual environment (Windows) |
| `requirements.txt` | Python dependencies |
