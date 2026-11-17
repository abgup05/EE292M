"""The SEC EDGAR adapter: ticker lookup, filing selection and document retrieval.

Satisfies :class:`app.core.ports.FilingSource`. Only ``https://www.sec.gov`` and
``https://data.sec.gov`` are ever contacted: the host is checked before every
request and redirects are refused rather than followed. Requests are spaced to
at most :data:`MAX_REQUESTS_PER_SECOND` across threads, retried with back-off on
HTTP 429 or 503, bounded by :data:`TIMEOUT_SECONDS`, and their bodies are
streamed and cut off at :data:`MAX_BYTES`. Every failure is raised as
:class:`SourceError` with a message that is safe to show to the user.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self
from urllib.parse import urlsplit

import httpx

from app.core.documents import FetchedFiling, FilingRef
from app.core.models import Company
from app.core.ports import SourceError, UnknownTicker
from app.sources.xbrl import fetch_company_facts

ALLOWED_HOSTS = frozenset({"www.sec.gov", "data.sec.gov"})
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
# An older page of a company's filing index; the name comes from the index and is checked.
SUBMISSIONS_PAGE_URL = "https://data.sec.gov/submissions/{name}"
OLDER_PAGE_NAME = "CIK{cik:010d}-submissions-"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{document}"

DEFAULT_USER_AGENT = "EvidenceDesk/0.2 (research tool for reading SEC filings)"
TIMEOUT_SECONDS = 30.0
MAX_BYTES = 40 * 1024 * 1024
MAX_REQUESTS_PER_SECOND = 7
RETRY_STATUSES = frozenset({429, 503})
MAX_RETRIES = 2
BACKOFF_SECONDS = (1.0, 2.0)
MAX_RETRY_AFTER_SECONDS = 10.0
TICKER_CACHE_SECONDS = 24 * 60 * 60

ANNUAL_FORM = "10-K"
QUARTERLY_FORM = "10-Q"
INDEX_COLUMNS = ("form", "filingDate", "reportDate", "accessionNumber", "primaryDocument")
# Older index pages read, newest first, to find the filing before the latest of a form.
MAX_OLDER_INDEX_PAGES = 12


def normalize_ticker(ticker: str) -> str:
    """Upper-case a ticker and write its class suffix as EDGAR does (``BRK.B`` -> ``BRK-B``)."""
    return ticker.strip().upper().replace(".", "-")


def archive_url(cik: int, accession: str, document: str) -> str:
    """The EDGAR archive address of one document of one filing."""
    return ARCHIVE_URL.format(cik=cik, folder=accession.replace("-", ""), document=document)


def _check_url(url: str) -> None:
    """Refuse anything but plain HTTPS to an allow-listed SEC host."""
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.hostname not in ALLOWED_HOSTS
        or parts.username is not None
        or parts.password is not None
        or parts.port not in (None, 443)
    ):
        raise SourceError("Refused to contact a URL that is not an SEC address")


class EdgarClient:
    """A rate-limited, bounded client for SEC EDGAR's public JSON and archives.

    ``sleep`` and ``monotonic`` are injectable so tests can check request spacing
    and back-off without waiting. Safe to share between threads.
    """

    def __init__(
        self,
        client: httpx.Client | None = None,
        user_agent: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.user_agent = (user_agent or "").strip() or DEFAULT_USER_AGENT
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False)
        self._sleep = sleep
        self._monotonic = monotonic
        self._spacing_lock = threading.Lock()
        self._next_slot = float("-inf")
        self._tickers_lock = threading.Lock()
        self._tickers: dict[str, Company] | None = None
        self._tickers_loaded_at = 0.0

    @classmethod
    def from_env(cls) -> EdgarClient:
        """A client whose User-Agent comes from ``SEC_USER_AGENT``, or the default."""
        return cls(user_agent=os.environ.get("SEC_USER_AGENT"))

    def close(self) -> None:
        """Close the HTTP client if this object created it."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    # FilingSource

    def company(self, ticker: str) -> Company:
        """Resolve a ticker through SEC's company list (cached for a day)."""
        key = normalize_ticker(ticker)
        company = self._ticker_table().get(key)
        if company is None:
            raise UnknownTicker(f"Ticker {key} is not in SEC's company list")
        return company

    def periodic_filings(self, company: Company, limit: int) -> list[FilingRef]:
        """The newest 10-K and the 10-Qs filed after it, newest first, at most ``limit``.

        The 10-K is always included; amendments (10-K/A, 10-Q/A) are skipped.
        """
        if limit < 1:
            raise ValueError("limit must be at least 1")
        rows = self._index_rows(company)
        annual = next((row for row in rows if row["form"] == ANNUAL_FORM), None)
        if annual is None:
            raise SourceError(
                f"No annual report (10-K) found for {company.name}; "
                "this version reads 10-K and 10-Q filers only"
            )
        quarterlies = [
            row
            for row in rows
            if row["form"] == QUARTERLY_FORM and row["filingDate"] > annual["filingDate"]
        ]
        chosen = [*quarterlies[: limit - 1], annual]
        return [self._ref(company.cik, row) for row in chosen]

    def filings_of_form(self, company: Company, form: str, limit: int) -> list[FilingRef]:
        """The newest ``limit`` filings of exactly ``form`` (amendments skipped), newest first.

        Made for comparing a filing with the one before it, so ``limit`` must be at
        least 2 (else ValueError). EDGAR's recent index holds about a year of a busy
        filer's filings; when it has fewer than two of the form, the older pages of the
        index are read, newest first, until there are two or
        :data:`MAX_OLDER_INDEX_PAGES` have been read. Fewer than two after that is a
        :class:`SourceError` that says how far the search went.
        """
        if limit < 2:
            raise ValueError("limit must be at least 2")
        rows, where = self._rows_of_form(company, form, needed=2)
        if len(rows) < 2:
            raise SourceError(
                f"{company.name} has {len(rows)} {form} filing(s) in {where}; "
                "two are needed to compare"
            )
        return [self._ref(company.cik, row) for row in rows[:limit]]

    def latest_of_form(self, company: Company, form: str) -> FilingRef:
        """The newest filing of exactly ``form`` (amendments skipped).

        One is enough: a company's first annual report has no earlier one. The older
        pages of the index are read only when the recent index has none of the form.
        None after that is a :class:`SourceError` that says how far the search went.
        """
        rows, where = self._rows_of_form(company, form, needed=1)
        if not rows:
            raise SourceError(f"{company.name} has no {form} filing in {where}")
        return self._ref(company.cik, rows[0])

    def _rows_of_form(
        self, company: Company, form: str, needed: int
    ) -> tuple[list[dict[str, str]], str]:
        """Index rows of ``form``, newest first, and a phrase saying where they were sought.

        The recent index first; while it yields fewer than ``needed``, the older pages,
        newest first, at most :data:`MAX_OLDER_INDEX_PAGES`.
        """
        what = f"the filing index of {company.name}"
        payload = self._index_payload(company)
        recent = self._rows(payload["filings"]["recent"], what)
        rows = [row for row in recent if row["form"] == form]
        where = "EDGAR's recent index"
        if len(rows) < needed:
            older = self._older_pages(payload, company, what)
            read = 0
            for name in older[:MAX_OLDER_INDEX_PAGES]:
                page = self._get_json(SUBMISSIONS_PAGE_URL.format(name=name), what)
                rows += [row for row in self._rows(page, what) if row["form"] == form]
                read += 1
                if len(rows) >= needed:
                    break
            if read:
                where += f" and the {read} newest of its {len(older)} older index pages"
        rows.sort(key=lambda row: row["filingDate"], reverse=True)
        return rows, where

    def fetch(self, ref: FilingRef) -> FetchedFiling:
        """Retrieve a filing's primary document, decoded as UTF-8."""
        body = self.get(ref.url)
        return FetchedFiling(
            ref=ref,
            html=body.decode("utf-8", errors="replace"),
            retrieved_at=datetime.now(UTC),
        )

    def company_facts(self, company: Company) -> dict[str, Any]:
        """The company's XBRL company facts from ``data.sec.gov``, parsed.

        Raises :class:`SourceError` when EDGAR fails or the body is not a JSON object.
        """
        return fetch_company_facts(self.get, company.cik)

    # Transport

    def get(self, url: str) -> bytes:
        """GET ``url`` from an SEC host within every limit and return the body.

        Retries HTTP 429 and 503 up to :data:`MAX_RETRIES` times with back-off.
        Raises :class:`SourceError` for any failure.
        """
        _check_url(url)
        for attempt in range(MAX_RETRIES + 1):
            self._wait_for_slot()
            status, retry_after, body = self._get_once(url)
            if status == 200 and body is not None:
                return body
            if status in RETRY_STATUSES and attempt < MAX_RETRIES:
                self._sleep(self._backoff(attempt, retry_after))
                continue
            raise SourceError(f"EDGAR answered HTTP {status} for {url}")
        raise AssertionError("unreachable")  # pragma: no cover

    def _get_once(self, url: str) -> tuple[int, str | None, bytes | None]:
        """One request: (status, Retry-After header, body when the status is 200)."""
        headers = {"user-agent": self.user_agent, "accept-encoding": "gzip, deflate"}
        try:
            with self._client.stream(
                "GET", url, headers=headers, timeout=TIMEOUT_SECONDS, follow_redirects=False
            ) as response:
                if response.is_redirect or 300 <= response.status_code < 400:
                    raise SourceError(
                        f"EDGAR redirected the request for {url}; redirects are not followed"
                    )
                if response.status_code != 200:
                    return response.status_code, response.headers.get("retry-after"), None
                return 200, None, self._read_capped(response)
        except httpx.TimeoutException as exc:
            raise SourceError(
                f"EDGAR request timed out after {TIMEOUT_SECONDS:.0f} seconds"
            ) from exc
        except httpx.HTTPError as exc:
            raise SourceError(f"EDGAR could not be reached ({exc.__class__.__name__})") from exc

    @staticmethod
    def _read_capped(response: httpx.Response) -> bytes:
        limit_note = f"EDGAR response exceeded the {MAX_BYTES // (1024 * 1024)} MB size limit"
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_BYTES:
            raise SourceError(limit_note)
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > MAX_BYTES:
                raise SourceError(limit_note)
            chunks.append(chunk)
        return b"".join(chunks)

    def _wait_for_slot(self) -> None:
        """Space request starts at least 1/MAX_REQUESTS_PER_SECOND apart, across threads."""
        interval = 1.0 / MAX_REQUESTS_PER_SECOND
        with self._spacing_lock:
            now = self._monotonic()
            wait = self._next_slot - now
            if wait > 0:
                self._sleep(wait)
                now += wait
            self._next_slot = now + interval

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None) -> float:
        delay = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
        if retry_after is not None and retry_after.strip().isdigit():
            delay = max(delay, min(float(retry_after.strip()), MAX_RETRY_AFTER_SECONDS))
        return delay

    def _get_json(self, url: str, what: str) -> Any:
        body = self.get(url)
        try:
            return json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SourceError(f"EDGAR returned malformed data for {what}") from exc

    # Company list

    def _ticker_table(self) -> dict[str, Company]:
        with self._tickers_lock:
            fresh = (
                self._tickers is not None
                and self._monotonic() - self._tickers_loaded_at < TICKER_CACHE_SECONDS
            )
            if not fresh:
                self._tickers = self._load_tickers()
                self._tickers_loaded_at = self._monotonic()
            assert self._tickers is not None
            return self._tickers

    def _load_tickers(self) -> dict[str, Company]:
        what = "the company list"
        payload = self._get_json(TICKERS_URL, what)
        if not isinstance(payload, dict):
            raise SourceError(f"EDGAR returned malformed data for {what}")
        table: dict[str, Company] = {}
        for entry in payload.values():
            try:
                company = Company(
                    cik=int(entry["cik_str"]),
                    ticker=str(entry["ticker"]),
                    name=str(entry["title"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise SourceError(f"EDGAR returned malformed data for {what}") from exc
            # The list is ordered by importance; keep the first filer for a ticker.
            table.setdefault(normalize_ticker(company.ticker), company)
        return table

    # Filing index

    def _index_rows(self, company: Company) -> list[dict[str, str]]:
        """``filings.recent`` turned from parallel columns into rows, newest filing first."""
        what = f"the filing index of {company.name}"
        return self._rows(self._index_payload(company)["filings"]["recent"], what)

    def _index_payload(self, company: Company) -> dict[str, Any]:
        """The company's filing index as EDGAR sends it, with ``filings.recent`` present."""
        what = f"the filing index of {company.name}"
        payload = self._get_json(SUBMISSIONS_URL.format(cik=company.cik), what)
        try:
            payload["filings"]["recent"]
        except (KeyError, TypeError) as exc:
            raise SourceError(f"EDGAR returned malformed data for {what}") from exc
        return payload

    @staticmethod
    def _rows(table: Any, what: str) -> list[dict[str, str]]:
        """One index table (``filings.recent`` or an older page) as rows, newest first."""
        malformed = SourceError(f"EDGAR returned malformed data for {what}")
        try:
            columns = [table[name] for name in INDEX_COLUMNS]
        except (KeyError, TypeError) as exc:
            raise malformed from exc
        if not all(isinstance(column, list) for column in columns):
            raise malformed
        try:
            rows = [
                dict(zip(INDEX_COLUMNS, values, strict=True))
                for values in zip(*columns, strict=True)
            ]
        except ValueError as exc:  # the parallel columns differ in length
            raise malformed from exc
        if not all(isinstance(value, str) for row in rows for value in row.values()):
            raise malformed
        rows.sort(key=lambda row: row["filingDate"], reverse=True)
        return rows

    @staticmethod
    def _older_pages(payload: dict[str, Any], company: Company, what: str) -> list[str]:
        """The names of the index's older pages, the page with the newest filings first.

        A name is used to build a URL, so each must be exactly this company's
        ``CIK##########-submissions-###.json``; anything else is malformed data.
        """
        malformed = SourceError(f"EDGAR returned malformed data for {what}")
        files = payload["filings"].get("files", [])
        if not isinstance(files, list):
            raise malformed
        expected = re.compile(re.escape(OLDER_PAGE_NAME.format(cik=company.cik)) + r"\d{3}\.json")
        pages: list[tuple[str, str]] = []
        for entry in files:
            name = entry.get("name") if isinstance(entry, dict) else None
            newest = entry.get("filingTo") if isinstance(entry, dict) else None
            if not (isinstance(name, str) and expected.fullmatch(name) and isinstance(newest, str)):
                raise malformed
            pages.append((newest, name))
        return [name for _, name in sorted(pages, reverse=True)]

    @staticmethod
    def _ref(cik: int, row: dict[str, str]) -> FilingRef:
        return FilingRef(
            cik=cik,
            accession=row["accessionNumber"],
            form=row["form"],
            period_end=row["reportDate"],
            filed_date=row["filingDate"],
            primary_document=row["primaryDocument"],
            url=archive_url(cik, row["accessionNumber"], row["primaryDocument"]),
        )
