"""Load companies' XBRL company facts into the fact store (``make facts-load TICKERS="..."``).

For each ticker: resolve it through SEC's company list, read its industry code from
its submissions index and its company facts from the XBRL API (two requests), and
keep every us-gaap fact in ``data/facts/facts.sqlite`` with the filing that
reported it. A body already stored unchanged is left as it is. One line per
company says what is stored; a company that cannot be read is named with the
reason and the others continue.

Exit codes: 0 when every company was loaded, 1 when any could not be.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime

from ed_v14 import wiring
from ed_v14.core.ports import FilingSource, SourceError
from ed_v14.services.numbers import content_hash, keep_facts
from ed_v14.store import FactStore

PERIODIC = ("10-K", "10-Q")


def load(tickers: Sequence[str], filings: FilingSource, store: FactStore) -> int:
    """Load each ticker into ``store``; print one line each; the number that failed."""
    failed = 0
    for ticker in tickers:
        try:
            company = filings.company(ticker)
            payload = filings.company_facts(company)
        except SourceError as exc:
            print(f"facts-load: {ticker.upper()} could not be read: {exc}")
            failed += 1
            continue
        error = keep_facts(
            store, company, filings, payload, content_hash(payload), datetime.now(UTC)
        )
        if error is not None:
            print(f"facts-load: {company.ticker} could not be stored ({error})")
            failed += 1
            continue
        stored = store.company(company.cik)
        assert stored is not None
        periodic = store.filings(company.cik, PERIODIC)
        industry = f"SIC {stored.sic} {stored.sic_description}" if stored.sic else "no SIC code"
        first = periodic[0].filed if periodic else "none"
        last = periodic[-1].filed if periodic else "none"
        print(
            f"facts-load: {stored.ticker} {stored.name} (CIK {stored.cik}, {industry}): "
            f"{stored.facts:,} us-gaap facts kept, {stored.skipped} unusable entries skipped; "
            f"{len(periodic)} 10-K and 10-Q filings from {first} to {last}"
        )
    return failed


def main(argv: Sequence[str] | None = None) -> int:
    """Load every ticker named on the command line into the configured fact store."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tickers", nargs="+", help="tickers to load, such as NVDA AAPL")
    args = parser.parse_args(argv)
    store = wiring.facts_from_env()
    with wiring.filings_from_env() as filings:
        failed = load(args.tickers, filings, store)
    print(f"facts-load: fact store at {store.path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
