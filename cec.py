import logging
import subprocess

import settings

_log = logging.getLogger("cec")


def _send(command: str) -> None:
    if not settings.cec_enabled:
        return
    try:
        proc = subprocess.Popen(
            ["cec-client", "-s", "-d", "1"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        proc.stdin.write(command + "\n")
        proc.stdin.close()
    except FileNotFoundError:
        _log.warning("cec-client not found — CEC command skipped.")
    except Exception as exc:
        _log.warning("CEC command failed: %s", exc)


def standby() -> None:
    _log.info("CEC: sending standby.")
    _send("standby 0")


def power_on() -> None:
    _log.info("CEC: sending power on.")
    _send("on 0")
