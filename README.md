# autodash

A lightweight dashboard monitor that opens one or more web dashboards in dedicated Chromium windows, logs in automatically, keeps sessions alive, and self-heals if a window is closed or a session expires. When internet connectivity is lost every window is replaced by a fullscreen offline notice and resumes automatically once the connection is restored.

---

## Requirements

- Git
- Python 3.9+

**Windows** — install both with winget:
```powershell
winget install Git.Git
winget install Python.Python.3.14
```

**Linux (Debian/Ubuntu)**:
```bash
sudo apt install git python3
```

Everything else (virtualenv, Playwright, Chromium, system packages) is handled automatically by `start.py`.

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/cruzher/autodash.git
cd autodash
```

### 2. Run the setup and start

```bash
python start.py
```

> On Linux you may need `python3 start.py`.

`start.py` creates a virtual environment, installs all dependencies, and launches the monitor. Re-running it is safe — steps that are already complete are skipped.

---

## First login

Once the monitor is running, open a browser and navigate to:

```
http://<machine-ip>:8080/ui
```

The machine's IP address is shown on screen — if no dashboard is currently scheduled, a fullscreen notice displays it. On the first visit you will be prompted to create a username and password. Subsequent visits require those credentials to log in (sessions expire after 8 hours).

Add one entry per dashboard. Each entry opens one Chromium window. Changes are picked up automatically within 60 seconds — no restart needed.

---

## Multi-step login

Some sites split the login process across multiple pages or use non-standard form layouts (e.g. username on one page, password on the next, or a modal that appears after clicking a button). The multi-step login feature lets you define a custom sequence of actions that replaces the standard username/password/submit flow entirely.

### How to configure

Open the web UI, expand a site, and scroll to the **Multi-step login** section (visible when **Auto login** is enabled). Click **+ Add step** to add actions one at a time. Each step has three fields:

| Field | Description |
|---|---|
| Action | What to do: `fill`, `click`, `click_xy`, `delay`, `wait_for`, or `press` |
| CSS selector | The element to target (ignored by `click_xy` and `delay`) |
| Value | Text to type (`fill`), `x, y` position (`click_xy`), milliseconds (`delay`), key name (`press`), or empty (`click` / `wait_for`) |

Use `{username}` and `{password}` as placeholders in the **Value** field — they are substituted with the credentials stored for that site.

Two selector formats are supported in the **CSS selector** field:

| Format | Example | Equivalent Playwright call |
|---|---|---|
| `role=<role>[name="<text>"]` | `role=textbox[name="Username"]` | `get_by_role("textbox", name="Username")` |
| CSS selector | `input[type='password']` | `locator("input[type='password']")` |

The `role=` format maps directly to what Playwright's codegen produces — copy the role and name from a `get_by_role(...)` call and write it as `role=<role>[name="<text>"]`.

### Actions

| Action | What it does |
|---|---|
| `fill` | Clicks the element then types the given value into it |
| `click` | Clicks the element and waits 1 second |
| `click_xy` | Clicks a fixed `x, y` viewport position (value field) and waits 1 second — for content with no reliable selector. Use the ⌖ Find button next to the step to pick coordinates from a live screenshot of the page |
| `delay` | Pauses for the given number of milliseconds (value field) |
| `wait_for` | Pauses until the element appears in the DOM (timeout: 15 s) |
| `press` | Presses a keyboard key on the element (or the whole page if no selector) |

### Examples

**Standard two-field form using Playwright codegen role selectors**
```
fill    role=textbox[name="Username"]    {username}
fill    role=textbox[name="Password"]    {password}
click   role=button[name="Sign In"]
```

**Username on page 1, password on page 2 (role selectors)**
```
fill      role=textbox[name="Username"]    {username}
click     role=button[name="Sign In"]
wait_for  role=textbox[name="Password"]
fill      role=textbox[name="Password"]    {password}
click     role=button[name="Sign In"]
```

**Standard two-field form using CSS selectors**
```
fill    input[name='username']      {username}
fill    input[type='password']      {password}
click   button[type='submit']
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

Schedules are configured in the web UI. Each entry is a time window with an optional day specifier:

| Format | Example | Meaning |
|---|---|---|
| `HH:MM – HH:MM` | `09:00 – 17:00` | Active every day between those times |
| `day HH:MM – HH:MM` | `Mon-Fri 09:00 – 17:00` | Active on specified days only |

**Day specifiers:**

| Specifier | Meaning |
|---|---|
| `*` | Every day |
| `Mon`, `Tue`, … `Sun` | Single day |
| `Mon-Fri` | Inclusive day range |
| `Sat,Sun` | Comma-separated list |

Multiple windows can be added per site (e.g. weekdays plus a Saturday half-day). Overnight ranges are supported — if the end time is earlier than the start time the window wraps past midnight (e.g. `22:00 – 06:00`).

---

## Offline behaviour

When internet connectivity is lost all browser windows navigate to a local offline page. The monitor polls for connectivity every 30 seconds and automatically resumes normal operation once the connection is restored.

---

## Screenshot

The **Home** tab shows a snapshot of the display. Click the image or the **Refresh** button to take a new screenshot on demand. A monitor selector appears when more than one physical monitor is detected. The **▶ Running / ⏸ Paused** button toggles the scheduler and turns orange while paused.

This view is available on all platforms (Windows and Raspberry Pi).

---

## Remote control (Raspberry Pi only)

A full interactive remote desktop session is available from the **Remote Control** nav item, which is only shown when running on a Raspberry Pi.

Clicking **Start** launches an `x11vnc` server on the Pi and a `websockify` WebSocket proxy, then embeds a [noVNC](https://novnc.com) client directly in the browser — no additional software needed on the client side. Clicking **Stop** tears both processes down.

**Requirements (installed automatically by `start.py` on Raspberry Pi):**
- `novnc` — provides the noVNC web client and `websockify`
- `x11vnc` — standard VNC server for the X11 display (used instead of RealVNC for noVNC compatibility)

> The remote session has no VNC password — access is gated by autodash's own login. Port 6080 (websockify) is open on the Pi's network interface while the session is active.

---

## Borderless kiosk windows (Raspberry Pi only)

On Raspberry Pi OS, `start.py` disables window decorations (titlebar, min/max/close buttons) globally in openbox, so the Chromium dashboard windows are fully borderless even on a freshly imaged Pi.

It seeds `~/.config/openbox/rpd-rc.xml` from the OS default (`/etc/xdg/openbox/rpd-rc.xml`) if it doesn't exist yet, then adds a `<decor>no</decor>` rule to it using `xmlstarlet` and reloads openbox (`openbox --reconfigure`) to apply the change immediately, without a reboot.

**Requirements (installed automatically by `start.py` on Raspberry Pi):**
- `xmlstarlet` — used to edit `rpd-rc.xml` safely instead of raw text manipulation

---

## Windows auto-login

autodash includes a CLI tool to configure Windows to log in automatically on boot — useful for unattended kiosk machines that need to start without a password prompt.

> **Requires Administrator.** The tool writes to `HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon`, which requires an elevated terminal.

### Usage

Open PowerShell **as Administrator**, then run from the autodash directory:

```powershell
# Enable (defaults to the current logged-in user)
python autologin.py enable

# Enable for a specific user or domain
python autologin.py enable --username kevin
python autologin.py enable --username kevin --domain WORKGROUP

# Disable auto-login
python autologin.py disable

# Check current state
python autologin.py status
```

The password is always entered interactively via a secure prompt — it is never passed as a command-line argument and is not stored by autodash. The password is written to the registry by Windows itself as part of the standard auto-login mechanism.

The **Settings** page in the web UI shows the current auto-login state.

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for release notes.
