"""Daily closing prices from a public source, through a bounded and allow-listed fetch.

Only the hosts in :data:`ALLOWED_HOSTS` are contacted, over HTTPS, with a generic
User-Agent that names the tool and no person; a redirect is followed only to another
allow-listed host. Bodies are streamed and cut off at :data:`MAX_BYTES`; requests are
spaced at least :data:`MIN_SECONDS_BETWEEN` apart. Every failure is a
:class:`PriceFetchError` whose message is safe to show.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

ALLOWED_HOSTS = frozenset({"stooq.com", "stooq.pl", "fred.stlouisfed.org", "api.nasdaq.com"})
USER_AGENT = "EvidenceDesk/0.14 (research tool; daily closes for one ticker)"
TIMEOUT_SECONDS = 20.0
MAX_BYTES = 8 * 1024 * 1024
MAX_REDIRECTS = 3
MIN_SECONDS_BETWEEN = 1.0


class PriceFetchError(RuntimeError):
    """A price page could not be retrieved; the message is safe to show."""


@dataclass(frozen=True)
class FetchedBody:
    """One body as retrieved: the URL finally answered, its content type and bytes."""

    url: str
    content_type: str
    body: bytes


_spacing_lock = threading.Lock()
_next_slot = [float("-inf")]


def _wait_for_slot(sleep: Callable[[float], None], monotonic: Callable[[], float]) -> None:
    with _spacing_lock:
        now = monotonic()
        wait = _next_slot[0] - now
        if wait > 0:
            sleep(wait)
            now += wait
        _next_slot[0] = now + MIN_SECONDS_BETWEEN


def check_url(url: str) -> str:
    """``url`` when it is plain HTTPS to an allow-listed host; else PriceFetchError."""
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.hostname not in ALLOWED_HOSTS
        or parts.username is not None
        or parts.password is not None
        or parts.port not in (None, 443)
    ):
        raise PriceFetchError("Refused to contact an address that is not an allowed price source")
    return url


def fetch_public_csv(
    url: str,
    *,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> FetchedBody:
    """GET ``url`` from an allow-listed host within the time, size and redirect limits."""
    owned = client is None
    client = client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False)
    headers = {"user-agent": USER_AGENT, "accept": "text/csv, application/json, */*"}
    try:
        current = check_url(url)
        for _ in range(MAX_REDIRECTS + 1):
            _wait_for_slot(sleep, monotonic)
            try:
                with client.stream("GET", current, headers=headers) as response:
                    if response.is_redirect:
                        location = response.headers.get("location", "")
                        current = check_url(urljoin(current, location))
                        continue
                    if response.status_code != 200:
                        raise PriceFetchError(f"HTTP {response.status_code} from {current}")
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > MAX_BYTES:
                            raise PriceFetchError("The price response exceeded the size limit")
                        chunks.append(chunk)
                    return FetchedBody(
                        current, response.headers.get("content-type", ""), b"".join(chunks)
                    )
            except httpx.TimeoutException as exc:
                raise PriceFetchError(f"The price source timed out after {TIMEOUT_SECONDS:.0f} s") from exc
            except httpx.HTTPError as exc:
                raise PriceFetchError(
                    f"The price source could not be reached ({exc.__class__.__name__})"
                ) from exc
        raise PriceFetchError(f"Too many redirects (more than {MAX_REDIRECTS})")
    finally:
        if owned:
            client.close()
