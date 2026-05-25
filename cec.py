import logging
import subprocess

import settings

_log = logging.getLogger("cec")


def _send(command: str) -> None:
    if not settings.cec_enabled:
        return
    try:
        subprocess.run(
            ["cec-client", "-s", "-d", "1"],
            input=command,
            text=True,
            timeout=5,
            capture_output=True,
        )
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
