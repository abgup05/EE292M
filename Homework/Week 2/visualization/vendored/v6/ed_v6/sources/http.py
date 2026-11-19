"""Bounded retrieval of public HTML pages.

Every hop is validated before it is requested: literal private addresses are
refused syntactically and hostnames are resolved and checked, so a redirect
cannot pull the server into a private network. Bodies are streamed and cut off
at :data:`MAX_BYTES`; only HTML content types are accepted.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit

import httpx

from ed_v6.sources.urls import UnsafeURL, resolve_public_address, validate_public_url

TIMEOUT_SECONDS = 12.0
MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 5
HTML_TYPES = ("text/html", "application/xhtml+xml")
USER_AGENT = "Mozilla/5.0 (compatible; EvidenceDesk/0.1; research brief tool; public HTML only)"

Resolver = Callable[[str, int], list[str]]


class FetchError(RuntimeError):
    """A page could not be retrieved; the message is safe to show to the user."""


@dataclass(frozen=True)
class FetchedPage:
    """One successfully retrieved HTML page."""

    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    html: str
    retrieved_at: datetime


def _check_hop(url: str, resolver: Resolver) -> str:
    """Validate one URL in a redirect chain, including DNS resolution."""
    safe = validate_public_url(url)
    parts = urlsplit(safe)
    assert parts.hostname is not None  # guaranteed by validate_public_url
    port = parts.port or (443 if parts.scheme == "https" else 80)
    resolver(parts.hostname, port)
    return safe


def _read_capped(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > MAX_BYTES:
            raise FetchError("Response exceeded the 2 MB page limit")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_page(
    url: str,
    *,
    client: httpx.Client | None = None,
    resolver: Resolver = resolve_public_address,
) -> FetchedPage:
    """Fetch ``url`` as HTML within the time, size and redirect limits.

    Raises :class:`FetchError` for any failure, including unsafe redirects,
    non-HTML content, oversized bodies, HTTP errors and timeouts.
    """
    owned = client is None
    client = client or httpx.Client(
        timeout=TIMEOUT_SECONDS,
        headers={"user-agent": USER_AGENT},
        follow_redirects=False,
    )
    try:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            try:
                current = _check_hop(current, resolver)
            except UnsafeURL as exc:
                raise FetchError(str(exc)) from exc
            try:
                with client.stream("GET", current, follow_redirects=False) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise FetchError("Redirect without a Location header")
                        current = urljoin(current, location)
                        continue
                    if response.status_code != 200:
                        raise FetchError(f"HTTP {response.status_code}")
                    content_type = response.headers.get("content-type", "").lower()
                    if not content_type.startswith(HTML_TYPES):
                        raise FetchError(
                            f"Response is not HTML (content-type {content_type or 'missing'!r})"
                        )
                    body = _read_capped(response)
                    encoding = response.charset_encoding or "utf-8"
            except httpx.TimeoutException as exc:
                raise FetchError("Request timed out after 12 seconds") from exc
            except httpx.HTTPError as exc:
                raise FetchError(f"Network error: {exc.__class__.__name__}") from exc
            return FetchedPage(
                requested_url=url,
                final_url=current,
                status_code=response.status_code,
                content_type=content_type,
                html=body.decode(encoding, errors="replace"),
                retrieved_at=datetime.now(UTC),
            )
        raise FetchError(f"Too many redirects (more than {MAX_REDIRECTS})")
    finally:
        if owned:
            client.close()
