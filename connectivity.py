import asyncio
import urllib.error
import urllib.request

INTERNET_CHECK_HOST    = "8.8.8.8"
INTERNET_CHECK_PORT    = 53
INTERNET_CHECK_TIMEOUT = 3
SITE_CHECK_TIMEOUT     = 8


async def check_internet() -> bool:
    """Return True if a TCP connection to the check host succeeds."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(INTERNET_CHECK_HOST, INTERNET_CHECK_PORT),
            timeout=INTERNET_CHECK_TIMEOUT,
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


async def check_site_available(url: str) -> bool:
    """Return True if the site responds with a non-5xx HTTP status.
    4xx (e.g. 401 on a login page) counts as available — the server is up."""
    def _check():
        try:
            req = urllib.request.Request(url, method="HEAD")
            try:
                resp   = urllib.request.urlopen(req, timeout=SITE_CHECK_TIMEOUT)
                status = resp.status
                resp.close()
            except urllib.error.HTTPError as exc:
                status = exc.code
            return status < 500
        except Exception:
            return False

    try:
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(None, _check),
            timeout=SITE_CHECK_TIMEOUT + 2,
        )
    except Exception:
        return False
