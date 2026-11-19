"""Quarter-end prices from Form 13F filings on SEC EDGAR: the price source that needs no account.

``make market-probe`` found no site that gives a script daily single-stock prices
without an account under terms that allow it (``docs/market-view.md``). SEC itself
holds a price, though: every Form 13F-HR states each position's value and shares at a
quarter's end (:mod:`app.core.thirteenf`). :class:`QuarterEndPrices` reads the newest
13F-HR that each manager of :data:`MANAGERS` filed on or before the as-of date and takes
the company's price from the first that holds it; a second manager's filing for the same
quarter confirms it or the result says they differ.

What it is not: a daily price. It is the close of a quarter's last trading day, public
from this source only once the 13F is filed (up to 45 days later), so the newest price
can be more than four months old. A reaction to an 8-K needs daily closes, which this
source cannot give.

Three requests per manager, through the app's EDGAR client (its User-Agent, allow-list,
limits and retries), spaced :data:`MIN_SECONDS_BETWEEN` apart: the manager's filing index
(reused for :data:`INDEX_REUSE_SECONDS`), the filing's folder listing, and the
information table. Tables are kept gzipped under the disposable cache; a filed table
never changes. A source made with ``get=None`` reads only what is on disk (the recorded
fixtures).
"""

from __future__ import annotations

import gzip
import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from ed_v14.core.models import Company
from ed_v14.core.ports import SourceError
from ed_v14.core.thirteenf import (
    AGREE_TOLERANCE,
    Matched,
    Table,
    ThirteenFError,
    agree,
    implied_price,
    match_issuer,
    parse_information_table,
    rows_of,
    unit_note,
    value_scale,
)
from ed_v14.core.valuation import Price
from ed_v14.core.view_models import ResultInput
from ed_v14.sources.prices import PriceUnavailable

# Managers read, in order: large holders of US shares whose tables are small enough to
# read whole and who file early. The first does not hold banks; the others do.
MANAGERS: tuple[tuple[int, str], ...] = (
    (1582202, "Swiss National Bank"),
    (919079, "California Public Employees Retirement System"),
    (810265, "New York State Common Retirement Fund"),
)
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FOLDER_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{folder}"
FORM = "13F-HR"
MIN_SECONDS_BETWEEN = 0.25
INDEX_REUSE_SECONDS = 6 * 60 * 60
_ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_TABLE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,120}\.xml$")


@dataclass(frozen=True)
class ManagerFiling:
    """One Form 13F-HR in a manager's index: the quarter it reports and when it was filed."""

    manager_cik: int
    manager: str
    accession: str
    period: date
    filed: date

    @property
    def folder(self) -> str:
        """The filing's folder on EDGAR."""
        return FOLDER_URL.format(cik=self.manager_cik, folder=self.accession.replace("-", ""))


class ThirteenFSource:
    """A manager's 13F filings and their information tables, through ``get`` and a directory."""

    def __init__(
        self,
        get: Callable[[str], bytes] | None,
        cache_dir: Path,
        *,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._get = get
        self.cache_dir = cache_dir
        self._sleep = sleep
        self._monotonic = monotonic
        self._clock = clock
        self._lock = threading.Lock()
        self._next = float("-inf")
        self.requests = 0

    @property
    def offline(self) -> bool:
        """True when this source reads only the bodies on disk."""
        return self._get is None

    def _fetch(self, url: str) -> bytes:
        assert self._get is not None
        with self._lock:
            wait = self._next - self._monotonic()
            if wait > 0:
                self._sleep(wait)
            self._next = self._monotonic() + MIN_SECONDS_BETWEEN
        self.requests += 1
        return self._get(url)

    def _keep(self, path: Path, body: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_bytes(gzip.compress(body, mtime=0))
        temporary.replace(path)

    def filings(self, manager_cik: int, manager: str) -> list[ManagerFiling]:
        """The manager's original 13F-HR filings in its recent index, newest filed first.

        Amendments (13F-HR/A) are not read. Raises :class:`SourceError` when EDGAR
        fails or the index is malformed; offline, an index not on disk is an empty list.
        """
        path = self.cache_dir / f"13f-{manager_cik}-filings.json.gz"
        fresh = path.is_file() and (
            self.offline or self._clock() - path.stat().st_mtime < INDEX_REUSE_SECONDS
        )
        if fresh:
            rows = json.loads(gzip.decompress(path.read_bytes()))
        elif self.offline:
            return []
        else:
            rows = _index_rows(self._fetch(SUBMISSIONS_URL.format(cik=manager_cik)))
            self._keep(path, json.dumps(rows).encode("utf-8"))
        found = [
            ManagerFiling(
                manager_cik, manager, acc, date.fromisoformat(period), date.fromisoformat(filed)
            )
            for acc, period, filed in rows
        ]
        return sorted(found, key=lambda f: (f.filed, f.period), reverse=True)

    def holdings(self, filing: ManagerFiling) -> Table | None:
        """The filing's share positions; None when its table cannot be had offline. Raises
        :class:`~app.core.thirteenf.ThirteenFError` when the table cannot be read."""
        text = self.table(filing)
        return None if text is None else parse_information_table(text)

    def table(self, filing: ManagerFiling) -> str | None:
        """The filing's information table as text; offline, None when it is not on disk."""
        path = self.cache_dir / f"13f-{filing.manager_cik}-{filing.accession}.xml.gz"
        if path.is_file():
            return gzip.decompress(path.read_bytes()).decode("utf-8", errors="replace")
        if self.offline:
            return None
        listing = self._fetch(f"{filing.folder}/index.json")
        name = _table_name(listing)
        body = self._fetch(f"{filing.folder}/{name}")
        self._keep(path, body)
        return body.decode("utf-8", errors="replace")


def _index_rows(body: bytes) -> list[tuple[str, str, str]]:
    """(accession, period, filed) of each original 13F-HR in a submissions index body."""
    try:
        recent = json.loads(body)["filings"]["recent"]
        columns = [recent[k] for k in ("form", "accessionNumber", "reportDate", "filingDate")]
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as exc:
        raise SourceError("EDGAR returned a malformed filing index for a 13F manager") from exc
    rows: list[tuple[str, str, str]] = []
    for form, accession, period, filed in zip(*columns, strict=False):
        if form != FORM or not _ACCESSION.fullmatch(str(accession)):
            continue
        try:
            date.fromisoformat(period), date.fromisoformat(filed)
        except TypeError, ValueError:
            continue
        rows.append((accession, period, filed))
    return rows


def _table_name(listing: bytes) -> str:
    """The information table's file name in a filing folder's ``index.json``."""
    try:
        items: list[dict[str, Any]] = json.loads(listing)["directory"]["item"]
        names = [str(item["name"]) for item in items]
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, TypeError) as exc:
        raise SourceError("EDGAR returned a malformed folder listing for a 13F") from exc
    tables = [n for n in names if _TABLE_NAME.fullmatch(n) and n.lower() != "primary_doc.xml"]
    if len(tables) != 1:
        raise SourceError(f"A 13F folder lists {len(tables)} information tables, not one")
    return tables[0]


class QuarterEndPrices:
    """The price provider that reads SEC: a company's quarter-end price from 13F filings."""

    name = "SEC Form 13F"

    def __init__(
        self, source: ThirteenFSource, managers: tuple[tuple[int, str], ...] = MANAGERS
    ) -> None:
        self._source = source
        self._managers = managers

    def price(self, company: Company, as_of: date) -> Price:
        """The company's newest quarter-end price public from a 13F by ``as_of``.

        Raises :class:`PriceUnavailable` with every manager's reason when none gives one,
        and :class:`SourceError` when EDGAR fails.
        """
        reasons: list[str] = []
        newest: list[ManagerFiling] = []
        for cik, manager in self._managers:
            filing = next((f for f in self._source.filings(cik, manager) if f.filed <= as_of), None)
            if filing is None:
                reasons.append(f"{manager}: no 13F-HR filed by {as_of.isoformat()} is in its index")
            else:
                newest.append(filing)
        # The newest quarter first; among managers of one quarter, the order of MANAGERS.
        order = {cik: position for position, (cik, _) in enumerate(self._managers)}
        newest.sort(key=lambda f: (-f.period.toordinal(), order[f.manager_cik]))
        taken: tuple[ManagerFiling, float, Matched, float] | None = None
        confirmations: list[tuple[ManagerFiling, float]] = []
        # Tables read before the price was taken, whose spelling of the issuer did not match:
        # they may still hold the same CUSIP, and then they confirm or contradict the price.
        passed_over: list[tuple[ManagerFiling, Table]] = []
        for filing in newest:
            if taken is not None and filing.period != taken[0].period:
                continue
            try:
                table = self._source.holdings(filing)
            except ThirteenFError as exc:
                reasons.append(f"{filing.manager}: {exc}")
                continue
            if table is None:
                reasons.append(f"{filing.manager}: the 13F for {filing.period} is not on disk")
                continue
            if taken is None:
                matched = match_issuer(table.holdings, company.name)
                if isinstance(matched, str):
                    reasons.append(f"{filing.manager}, quarter ended {filing.period}: {matched}")
                    passed_over.append((filing, table))
                    continue
                scale = value_scale(table.holdings)
                taken = (filing, implied_price(matched.rows, scale), matched, scale)
                for earlier, held in passed_over:
                    rows = rows_of(held.holdings, matched.cusip)
                    if rows and earlier.period == filing.period:
                        confirmations.append(
                            (earlier, implied_price(rows, value_scale(held.holdings)))
                        )
            else:
                rows = rows_of(table.holdings, taken[2].cusip)
                if rows:
                    scale = value_scale(table.holdings)
                    confirmations.append((filing, implied_price(rows, scale)))
        if taken is None:
            raise PriceUnavailable(
                f"No 13F read gives a price for {company.name} by {as_of.isoformat()}: "
                + "; ".join(reasons)
                + "."
            )
        filing, price, matched, scale = taken
        agreeing = [f for f, other in confirmations if agree(price, other)]
        differing = [(f, other) for f, other in confirmations if not agree(price, other)]
        checks: list[str] = []
        if agreeing:
            checks.append(
                f"Confirmed within {AGREE_TOLERANCE:.1%} by the 13F of "
                + " and of ".join(f"{f.manager} ({f.accession})" for f in agreeing)
                + "."
            )
        if differing:
            checks.append(
                "Differs from "
                + "; ".join(f"{f.manager}'s ${p:,.2f} ({f.accession})" for f, p in differing)
                + ": one of the filings is wrong, or a split fell at the quarter's end."
            )
        if not confirmations:
            checks.append("No second manager read holds it that quarter: the price is unconfirmed.")
        if unit_note(scale, filing.filed):
            checks.append(unit_note(scale, filing.filed))
        value = sum(row.value for row in matched.rows) * scale
        shares = sum(row.shares for row in matched.rows)
        source = f"SEC Form 13F-HR {filing.accession}, CUSIP {matched.cusip}"
        inputs = tuple(
            ResultInput(
                label=f"{filing.manager}: {what} ({matched.issuer})",
                value=number,
                display=shown,
                source=source,
                date=filing.period.isoformat(),
                filed=filing.filed.isoformat(),
                url=f"{filing.folder}/",
            )
            for what, number, shown in (
                ("value of the position", value, f"${value:,.0f}"),
                ("shares held", shares, f"{shares:,.0f}"),
            )
        )
        return Price(
            value=price,
            day=filing.period,
            source=(
                f"quarter-end price from SEC Form 13F-HR {filing.accession} of {filing.manager}, "
                f"filed {filing.filed.isoformat()}: the value of its {matched.issuer} position "
                f"(CUSIP {matched.cusip}) ÷ the shares held"
            ),
            known=filing.filed,
            url=f"{filing.folder}/",
            note=(
                "The manager's own valuation of its position at the quarter ended "
                f"{filing.period.isoformat()}, taken to be the close of the quarter's last "
                "trading day and never compared with an exchange; not a price of today. The "
                f"issuer is matched by name ({matched.issuer}), not by ticker. " + " ".join(checks)
            ),
            inputs=inputs,
            confirmed=bool(agreeing) and not differing,
            needs_confirmation=True,
        )
