"""Daily closing prices: a bounded, allow-listed fetch and the sources behind one interface.

A :class:`PriceSource` gives a symbol's daily closes as a
:class:`~app.core.price_series.PriceSeries`. There are three: :class:`FredSeries` (the
S&P 500 index level from FRED, read live, the index proxy), :class:`StooqDaily` (kept
because its CSV is the common shape, but Stooq now answers a script with a browser
check, so it fails with that reason), and :class:`CsvFilePrices` (a file the user
downloaded and put in the repository); closes may also be supplied on a request
(:func:`supplied_series`). No source of single-stock prices was found that answers a
script without an account and whose terms allow it (``docs/market-view.md``).

Only the hosts in :data:`ALLOWED_HOSTS` are contacted, over HTTPS, with a generic
User-Agent that names the tool and no person; a redirect is followed only to another
allow-listed host. Bodies are streamed and cut off at :data:`MAX_BYTES`; requests are
spaced at least :data:`MIN_SECONDS_BETWEEN` apart. Every failure is a
:class:`PriceFetchError` whose message is safe to show.
"""

from __future__ import annotations

import gzip
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.price_series import Close, PriceSeries, PriceSeriesError, parse_closes

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
                raise PriceFetchError(
                    f"The price source timed out after {TIMEOUT_SECONDS:.0f} s"
                ) from exc
            except httpx.HTTPError as exc:
                raise PriceFetchError(
                    f"The price source could not be reached ({exc.__class__.__name__})"
                ) from exc
        raise PriceFetchError(f"Too many redirects (more than {MAX_REDIRECTS})")
    finally:
        if owned:
            client.close()


# Price sources: one interface, three ways to get a series.

SYMBOL_PATTERN = re.compile(r"^\^?[A-Za-z0-9][A-Za-z0-9.-]{0,11}$")
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
FRED_SERIES = frozenset({"SP500"})
FRED_TERMS = (
    "FRED's SP500 series is S&P Dow Jones Indices' data; S&P's notice on FRED forbids "
    "reproducing it without permission, so it is read live for a computation and never "
    "committed. FRED keeps about ten years of it."
)
STOOQ_URL = "https://stooq.com/q/d/l/?s={symbol}&i=d"
BROWSER_CHECK = "answered with a browser check page instead of CSV (it requires JavaScript)"


class PriceSource(Protocol):
    """Where a daily close series comes from. Raises :class:`PriceFetchError` on failure."""

    name: str

    def series(self, symbol: str) -> PriceSeries:
        """Every daily close of ``symbol`` the source has, oldest first."""
        ...


def check_symbol(symbol: str) -> str:
    """``symbol`` when it is a ticker or an index code (``AAPL``, ``^SPX``, ``BRK-B``)."""
    if not SYMBOL_PATTERN.fullmatch(symbol):
        raise PriceFetchError(f"not a ticker or index symbol: {symbol!r}")
    return symbol


def _parsed(text: str, symbol: str, source: str, url: str) -> PriceSeries:
    try:
        closes = parse_closes(text)
    except PriceSeriesError as exc:
        raise PriceFetchError(f"{source}: {exc}") from exc
    return PriceSeries(
        symbol=symbol,
        closes=tuple(closes),
        source=source,
        url=url,
        retrieved=datetime.now(UTC).isoformat(timespec="seconds"),
    )


class FredSeries:
    """A FRED series by id (only :data:`FRED_SERIES`), read live and kept for the day."""

    name = "FRED"

    def __init__(
        self, cache_dir: Path | None = None, fetch: Callable[[str], FetchedBody] = fetch_public_csv
    ) -> None:
        self._cache_dir = cache_dir
        self._fetch = fetch

    def series(self, symbol: str) -> PriceSeries:
        """The FRED series ``symbol`` (``SP500``)."""
        if symbol not in FRED_SERIES:
            raise PriceFetchError(f"FRED series {symbol!r} is not one this tool reads")
        url = FRED_URL.format(series=symbol)
        today = datetime.now(UTC).date().isoformat()
        kept = self._cache_dir / f"fred-{symbol}-{today}.csv.gz" if self._cache_dir else None
        if kept is not None and kept.is_file():
            text = gzip.decompress(kept.read_bytes()).decode("utf-8")
        else:
            text = self._fetch(url).body.decode("utf-8", errors="replace")
            if kept is not None:
                kept.parent.mkdir(parents=True, exist_ok=True)
                kept.write_bytes(gzip.compress(text.encode("utf-8"), mtime=0))
        return _parsed(text, symbol, f"FRED {symbol} (S&P 500 index level, daily close)", url)


class StooqDaily:
    """Stooq's daily CSV download. Since at least November 2026 it answers a script with a
    browser check, so every call fails with that reason (``make market-probe``)."""

    name = "Stooq"

    def __init__(self, fetch: Callable[[str], FetchedBody] = fetch_public_csv) -> None:
        self._fetch = fetch

    def series(self, symbol: str) -> PriceSeries:
        """The daily closes of ``symbol`` (``aapl.us``, ``^spx``)."""
        check_symbol(symbol.replace(".", "-") if symbol.count(".") == 1 else symbol)
        url = STOOQ_URL.format(symbol=symbol.lower().replace("^", "%5E"))
        body = self._fetch(url).body.decode("utf-8", errors="replace")
        if body.lstrip().lower().startswith(("<!doctype", "<html")):
            raise PriceFetchError(f"Stooq {BROWSER_CHECK}")
        return _parsed(body, symbol, f"Stooq daily CSV ({symbol})", url)


class CsvFilePrices:
    """Closes from a CSV file the user downloaded (``Date`` and ``Close`` columns).

    The file must be a ``.csv`` inside ``root`` (the working directory): a path from the
    command line never reaches outside the repository.
    """

    name = "file"

    def __init__(self, path: Path, root: Path) -> None:
        resolved = path.resolve()
        if resolved.suffix.lower() != ".csv" or not resolved.is_relative_to(root.resolve()):
            raise PriceFetchError("a price file must be a .csv inside the repository")
        if not resolved.is_file():
            raise PriceFetchError(f"no price file at {path}")
        self._path = resolved
        self._shown = path

    def series(self, symbol: str) -> PriceSeries:
        """The file's closes, labelled ``symbol``."""
        text = self._path.read_text(encoding="utf-8", errors="replace")
        return _parsed(text, symbol, f"price file {self._shown} supplied by the user", "")


def supplied_series(symbol: str, closes: list[Close]) -> PriceSeries:
    """Closes given on a request, checked as a file's would be (ascending, unique, positive)."""
    text = "Date,Close\n" + "".join(f"{c.day.isoformat()},{c.value!r}\n" for c in closes)
    return _parsed(text, symbol, "closes supplied on the request", "")
