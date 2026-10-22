"""URL safety checks and canonicalization.

Only public ``http``/``https`` pages may be fetched. Private, loopback,
link-local and unspecified addresses are rejected both syntactically (literal
IPs) and after DNS resolution (see :func:`resolve_public_address`), so a
hostname that resolves to a private network cannot reach internal services.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ALLOWED_SCHEMES = frozenset({"http", "https"})
TRACKING_PARAMETERS = frozenset(
    {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}
)
DEFAULT_PORTS = {"http": 80, "https": 443}
BLOCKED_HOSTNAMES = frozenset({"localhost", "localhost.localdomain"})


class UnsafeURL(ValueError):
    """Raised when a URL must not be fetched."""


def is_private_address(address: str) -> bool:
    """Return True when ``address`` (IPv4 or IPv6 literal) is not globally routable."""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return True
    return not parsed.is_global


def validate_public_url(url: str) -> str:
    """Validate that ``url`` is a well-formed public ``http(s)`` URL and return it unchanged.

    Raises :class:`UnsafeURL` with a user-facing reason otherwise. Hostnames are
    checked literally here; DNS resolution happens at fetch time.
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError as exc:
        raise UnsafeURL(f"Malformed URL: {exc}") from exc
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURL("Only http and https URLs are supported")
    if not parts.hostname:
        raise UnsafeURL("URL has no host")
    if parts.username is not None or parts.password is not None:
        raise UnsafeURL("URLs with embedded credentials are not allowed")
    host = parts.hostname.lower()
    if host in BLOCKED_HOSTNAMES or host.endswith(".localhost") or host.endswith(".local"):
        raise UnsafeURL("Local hostnames are not allowed")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass  # a hostname, resolved later
    else:
        if is_private_address(host):
            raise UnsafeURL("Private or local network addresses are not allowed")
    return url.strip()


def resolve_public_address(hostname: str, port: int) -> list[str]:
    """Resolve ``hostname`` and return its addresses, rejecting any private result.

    Raises :class:`UnsafeURL` when resolution fails or any address is private,
    so a name that round-robins between public and private targets is refused.
    """
    try:
        infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURL(f"Could not resolve host {hostname!r}") from exc
    addresses = sorted({info[4][0] for info in infos})
    if not addresses:
        raise UnsafeURL(f"Host {hostname!r} has no addresses")
    for address in addresses:
        if is_private_address(address):
            raise UnsafeURL(f"Host {hostname!r} resolves to a private address")
    return addresses


def canonicalize(url: str) -> str:
    """Return a normalized form so mirrors of one page compare equal.

    Lowercases scheme and host, drops default ports, fragments, trailing
    slashes (except the root) and common tracking parameters, and sorts the
    remaining query parameters.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    netloc = host if port is None or DEFAULT_PORTS.get(scheme) == port else f"{host}:{port}"
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    query = sorted(
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMETERS
    )
    return urlunsplit((scheme, netloc, path, urlencode(query), ""))
