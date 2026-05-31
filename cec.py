import logging
import re
import subprocess

import settings

_log = logging.getLogger("cec")


def _list_adapters() -> list:
    try:
        result = subprocess.run(
            ["cec-client", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return re.findall(r"com port:\s+(\S+)", result.stdout)
    except FileNotFoundError:
        _log.warning("cec-client not found — CEC command skipped.")
        return []
    except Exception as exc:
        _log.warning("CEC adapter listing failed: %s", exc)
        return []


def _send(command: str) -> None:
    if not settings.cec_enabled:
        return
    adapters = _list_adapters()
    if not adapters:
        return
    for adapter in adapters:
        try:
            proc = subprocess.Popen(
                ["cec-client", "-s", "-d", "1", adapter],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            proc.stdin.write(command + "\n")
            proc.stdin.close()
            proc.wait()
        except Exception as exc:
            _log.warning("CEC command failed for adapter %s: %s", adapter, exc)


def standby() -> None:
    if not settings.cec_enabled:
        return
    _log.info("CEC: sending standby.")
    _send("standby 0")


def power_on() -> None:
    if not settings.cec_enabled:
        return
    _log.info("CEC: sending power on.")
    _send("on 0")
