# Changelog

### 2026-08-17
- **Autodash logo in the WebUI sidebar and login screen.** `ui.html` and `login.html` now show `assets/Logo_light.png` in place of the plain-text "Autodash" title, sized to fill most of the available width. The separate tagline text under it was dropped since the logo image already includes the wordmark and tagline. A new `/assets` static mount in `api.py` serves the image (and any other files under `assets/`) to the browser.

### 2026-08-15
- **Kiosk wallpaper and hidden desktop icons on Raspberry Pi.** `start.py` now sets `~/.config/pcmanfm/*/desktop-items-0.conf` to display `assets/Logo_dark.png` as the wallpaper (`wallpaper_mode=fit`) and hides desktop icons — disabling the home/trash/mounts icons and pointing pcmanfm's desktop folder at an empty directory, rather than relying on pcmanfm's own icon-visibility settings, which don't cover files a user later drops on the real Desktop folder.
- **Terminal window pinned to a strip along the top of the screen on Raspberry Pi.** `start.py` now repositions the `lxterminal` window at startup using the same xdotool-based tools `display.py` uses to position the kiosk's Chromium windows (`find_window_by_class()` and `get_screen_size()` were added there for this). The new `ensure_terminal_position()` moves the window to `(0, -33)` and resizes it to `screen_width + 15` × `100`, shifted above the top edge to crop off lxterminal's menu bar and wider than the screen to push its scrollbar past the right edge.

### 2026-08-14
- **Borderless kiosk windows on Raspberry Pi.** `start.py` now disables openbox window decorations globally, so a fresh Pi image no longer shows a titlebar on the kiosk Chromium window. It seeds `~/.config/openbox/rpd-rc.xml` from `/etc/xdg/openbox/rpd-rc.xml` (or a bundled fallback at `assets/rpd-rc.xml` if that's missing) and idempotently injects a `<decor>no</decor>` rule via `xmlstarlet`, then reloads openbox to apply it without a reboot. `xmlstarlet` is installed automatically.

### 2026-07-02
- **New login-step actions: `click_xy` and `delay`.** `click_xy` clicks a fixed `x, y` viewport position instead of a CSS selector — useful for canvas/iframe content with no reliable selector. `delay` pauses for a given number of milliseconds. Both are available in **Multi-step login** and **Post-login steps**.
- **Coordinate picker for `click_xy` steps.** A **⌖ Find** button next to each `click_xy` step opens a screenshot taken directly from that site's live page (pixel-exact match for `click_xy`'s coordinate space — no window position or display-scaling correction needed). Clicking the image saves the coordinate into the step, then asks whether to also perform that click on the live page now, so you can advance a multi-step sequence to its next visible state while picking coordinates for it. Requires the site to currently be running.
- **Home screenshot now reports the clicked pixel position.** Clicking the display screenshot on the **Home** tab shows the pixel coordinate under the cursor (with a copy button) instead of just refreshing. Note this is a physical-monitor coordinate, not viewport-relative — it only lines up directly with `click_xy` when a site's window sits at `(0, 0)` and OS display scaling is 100%.
- **Fix: unknown fields in a saved login/post-login step no longer crash startup.** `load_sites_json` now filters each step to known `LoginStep` fields before construction, the same way site-level config already does.

### 2026-06-02
- **Remote control replaced with noVNC (Raspberry Pi only).** The old screenshot-polling + pyautogui input simulation is replaced by two focused features. The **Home** tab now shows a manual-refresh screenshot (click the image or the Refresh button) — available on all platforms. A new **Remote Control** nav item (Raspberry Pi only) provides a full interactive desktop session via [noVNC](https://novnc.com) embedded in the browser, backed by `x11vnc` and `websockify`. Both are installed automatically by `start.py` on Raspberry Pi. Clicking Start/Stop in the UI manages the `x11vnc` and `websockify` processes. RealVNC is not used for this feature as its proprietary authentication is incompatible with noVNC.
- **Removed dependencies: `pyautogui`, `pyperclip`.** No longer needed now that input simulation is handled by noVNC/x11vnc. Added `websockify`.

### 2026-05-31
- **Fix: zombie processes from CEC commands.** Each call to `_send()` in `cec.py` now calls `proc.wait()` after closing stdin, so the subprocess is reaped immediately instead of accumulating as zombies over the lifetime of the process.
- **Fix: socket leak on HTTP availability checks.** `urllib.error.HTTPError` is itself a response object wrapping an open socket. `connectivity.py` now calls `exc.close()` on the error so the socket is released on 4xx responses (e.g. 401 on login-protected dashboards).
- **Fix: CDP session leak on window positioning failure.** `display.py` now uses a `try/finally` block to ensure `session.detach()` is always called, even when a `Browser.getWindowForTarget` or `Browser.setWindowBounds` call fails.
- **Fix: unbounded session token accumulation in auth.** `auth.py` now purges all expired tokens from the in-memory `_sessions` dict each time a new session is created, preventing slow memory growth on long-running instances.

### 2026-05-25
- **HDMI-CEC monitor control (Raspberry Pi only).** autodash can now turn the display on and off via HDMI-CEC based on the schedule — sending a power-on command when a dashboard becomes active and a standby command when nothing is scheduled. Enable it in the Settings page under **Display**. The setting is grayed out with an explanation on non-Raspberry Pi systems. Requires `cec-utils` (`cec-client`), which `start.py` installs automatically on Raspberry Pi.

### 2026-05-21
- **Smart config hot-reload — no unnecessary restarts.** Changing a site's settings no longer always restarts its browser window. Only changes to `url`, `username`, `password`, `totp_secret`, or `fullscreen` require a restart. All other settings (schedule, refresh interval, availability check, selectors, post-login URL, etc.) are picked up immediately without touching the running browser. Window geometry changes (`window_x/y/width/height`) are applied by resizing and repositioning the live window in place.
- **Fix: unrelated sites unaffected by config changes.** The reconciliation loop now exclusively targets the site whose config changed; other running sites are left completely untouched.

### 2026-05-08
- **Fix: Windows autostart not starting on login.** Switched from Task Scheduler to the `HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Run` registry key, which requires no admin rights and reliably triggers for the current user. Errors are now shown in the UI if enabling fails.
- **Windows auto-login CLI tool.** Added `autologin.py`, a standalone script that configures Windows to log in automatically on boot by writing to the `HKLM\...\Winlogon` registry key. Requires an elevated terminal. The password is entered interactively and never stored by autodash. The Settings page now shows the current auto-login status.
- **Fix: site window not raised to top when coming back on-schedule.** The "No Dashboard Scheduled" notice (fullscreen) was being closed after the site window was already opened, causing the site window to appear behind it. The notice is now closed before the site window is launched. Additionally improved the Windows window-raising logic to use `SetWindowPos(HWND_TOPMOST/HWND_NOTOPMOST)` and `AttachThreadInput` as more reliable alternatives to `SetForegroundWindow`.

### 2026-05-01
- When a site is started, its window is now explicitly raised to the top of the z-order as the final step, preventing it from appearing behind other open windows. On Linux this uses `xdotool windowraise`; on Windows it uses the Win32 `SetForegroundWindow` / `BringWindowToTop` API.
