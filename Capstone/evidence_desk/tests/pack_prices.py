"""The quarter-end price the reference pack gives each probe company, and whether it stands.

Offline: only the 13F tables shipped in ``src/app/reference`` are read, as of the day the
pack was built. Since version 14.3 the market view computes nothing from a 13F price that
no second manager's filing confirms within the tolerance; ``make pack-prices`` prints, for
each of the eight probe companies, the price, the manager it came from, what the other
managers say, and so whether a valuation would be computed or refused. ``make
market-check`` asks the same of live EDGAR, with the frames and the facts beside it.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from app.core.models import Company
from app.sources import reference
from app.sources.prices import PriceUnavailable
from app.sources.thirteenf import QuarterEndPrices, ThirteenFSource

PROBE: tuple[tuple[str, int], ...] = (
    ("NVDA", 1045810),
    ("AAPL", 320193),
    ("MSFT", 789019),
    ("KO", 21344),
    ("JPM", 19617),
    ("TSLA", 1318605),
    ("COST", 909832),
    ("AMZN", 1018724),
)


def main() -> int:
    """Print one line per probe company; exit 1 when the app ships no pack."""
    pack = reference.load()
    if pack is None:
        print("no reference pack in src/app/reference")
        return 1
    day = pack.prices.built
    print(f"reference pack built {day.isoformat()}; prices as of that day, 13F tables from disk")
    valued = 0
    with tempfile.TemporaryDirectory() as scratch:
        live = ThirteenFSource(None, Path(scratch))
        for ticker, cik in PROBE:
            name = pack.frames.filers.get(cik, ("", ""))[0]
            if not name:
                print(f"{ticker}: not a filer of the pack's frames, so no name to match by")
                continue
            source = reference.PackThirteenF(pack.prices, live, day)
            try:
                company = Company(cik=cik, ticker=ticker, name=name)
                price = QuarterEndPrices(source).price(company, day)
            except PriceUnavailable as exc:
                print(f"{ticker}: no price ({exc})")
                continue
            stands = price.confirmed
            valued += stands
            verdict = "confirmed: valued" if stands else "NOT confirmed: no valuation"
            checks = price.note.split("not by ticker. ", 1)[-1]
            print(f"{ticker}: ${price.value:,.2f} for {price.day.isoformat()}; {verdict}. {checks}")
    print(f"{valued} of {len(PROBE)} would be valued from the pack's 13F price")
    return 0


if __name__ == "__main__":
    sys.exit(main())
