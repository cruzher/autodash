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
| Action | What to do: `fill`, `click`, `wait_for`, or `press` |
| CSS selector | The element to target (optional for `press`) |
| Value | Text to type (`fill`), key name (`press`), or empty (`click` / `wait_for`) |

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

## Remote control

The web UI includes a live remote control view accessible from the **Home** tab. It shows a continuously updated screenshot of the display and lets you interact with the machine from any browser on the network.

**Available controls:**

| Control | Description |
|---|---|
| Click on screenshot | Sends a mouse click at that position |
| Keyboard (while hovering) | All key presses are forwarded to the display |
| **Send text** button | Types or pastes a block of text, with an option to press Enter after |
| **F11 / Win / Esc / Enter** buttons | Quick single-key shortcuts |
| **Pause / Resume** button | Temporarily suspends the scheduler (button turns red while paused) |
| Monitor selector | Switch between physical monitors on multi-monitor setups |

The screenshot refresh rate adjusts automatically — faster while you are actively clicking or typing, slower when idle. Both intervals are configurable in the **Settings** page under **Remote control**.
