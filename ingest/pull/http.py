"""Tiny retrying HTTP GET/POST for the non-DataSF feeds. Stdlib (+ certifi if present)."""
from __future__ import annotations

import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

RETRY_STATUSES = {429, 500, 502, 503, 504}
USER_AGENT = "transpeaktation-ingest/0.1"


def _ssl_context() -> ssl.SSLContext:
    # Prefer certifi's CA bundle when installed: some Windows cert stores carry an
    # expired intermediate that breaks e.g. overpass-api.de. Verification stays on.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL_CONTEXT = _ssl_context()


class FetchError(RuntimeError):
    pass


def fetch(
    url: str,
    *,
    params: dict[str, str] | None = None,
    data: dict[str, str] | None = None,
    timeout: float = 60,
    retries: int = 3,
) -> bytes:
    """GET (or form POST when `data` is given) and return the body."""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code in RETRY_STATUSES and attempt < retries:
                time.sleep(float(e.headers.get("Retry-After") or 2**attempt))
                continue
            raise FetchError(f"{e.code} from {url.split('?')[0]}: {e.read()[:200]!r}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < retries:
                time.sleep(2**attempt)
                continue
            raise FetchError(f"{url.split('?')[0]}: {e}") from e
    raise AssertionError("unreachable")
