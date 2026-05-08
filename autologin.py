"""Windows automatic logon — reads status without admin, enable/disable requires admin.

CLI usage (run as Administrator):
    python autologin.py status
    python autologin.py enable [--username kevin] [--domain WORKGROUP]
    python autologin.py disable
"""

import platform
import sys

_SYSTEM   = platform.system()
_KEY_PATH = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"


def supported() -> bool:
    return _SYSTEM == "Windows"


def is_enabled() -> bool:
    if _SYSTEM != "Windows":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _KEY_PATH) as k:
            val, _ = winreg.QueryValueEx(k, "AutoAdminLogon")
            return val == "1"
    except OSError:
        return False


def enable(username: str, password: str, domain: str = "") -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _KEY_PATH, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "AutoAdminLogon",    0, winreg.REG_SZ, "1")
        winreg.SetValueEx(k, "DefaultUserName",   0, winreg.REG_SZ, username)
        winreg.SetValueEx(k, "DefaultPassword",   0, winreg.REG_SZ, password)
        winreg.SetValueEx(k, "DefaultDomainName", 0, winreg.REG_SZ, domain)


def disable() -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _KEY_PATH, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "AutoAdminLogon",    0, winreg.REG_SZ, "0")
        winreg.SetValueEx(k, "DefaultUserName",   0, winreg.REG_SZ, "")
        winreg.SetValueEx(k, "DefaultPassword",   0, winreg.REG_SZ, "")
        winreg.SetValueEx(k, "DefaultDomainName", 0, winreg.REG_SZ, "")


if __name__ == "__main__":
    import argparse
    import getpass
    import os

    if _SYSTEM != "Windows":
        print("This tool is Windows-only.")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Manage Windows automatic logon.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Show current auto-login state.")

    p_enable = sub.add_parser("enable", help="Enable auto-login (requires Administrator).")
    p_enable.add_argument("--username", default=None, help="Windows username (default: current user)")
    p_enable.add_argument("--domain",   default="",   help="Domain or WORKGROUP (optional)")

    sub.add_parser("disable", help="Disable auto-login (requires Administrator).")

    args = parser.parse_args()

    if args.cmd == "status":
        print("Auto-login is", "ENABLED" if is_enabled() else "DISABLED")

    elif args.cmd == "enable":
        username = args.username or os.environ.get("USERNAME") or os.environ.get("USER") or ""
        if not username:
            print("ERROR: Could not determine current user. Pass --username explicitly.", file=sys.stderr)
            sys.exit(1)
        print(f"Username: {username}")
        password = getpass.getpass("Password: ")
        try:
            enable(username, password, args.domain)
            print("Auto-login enabled.")
        except PermissionError:
            print("ERROR: Permission denied. Run this script as Administrator.", file=sys.stderr)
            sys.exit(1)

    elif args.cmd == "disable":
        try:
            disable()
            print("Auto-login disabled.")
        except PermissionError:
            print("ERROR: Permission denied. Run this script as Administrator.", file=sys.stderr)
            sys.exit(1)
