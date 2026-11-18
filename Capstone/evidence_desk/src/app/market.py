"""The market view from the command line (``make market-view T=NVDA PRICE=... PRICE_DATE=...``).

Live: the company's XBRL facts and 8-K index from EDGAR, SEC's revenue frames through the
disposable cache, and, when asked, FRED's S&P 500 level as the index. The price is the
one given (no source of single-stock prices was found that a script may use without an
account: ``docs/market-view.md``); daily closes for a reaction to an 8-K come from a CSV
file the user put in the repository (``--prices``). Prints the valuation, the reverse
DCF and the reactions, and writes the result as JSON to ``results/market-<ticker>-<UTC>.json``.

Exit codes: 0 when the view was made, 1 when a source failed, 2 for a refused argument.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from app import wiring
from app.core.models import as_of_problem
from app.core.ports import SourceError, UnknownTicker
from app.core.valuation import Price
from app.services.market_view import DcfInputs, describe, market_view
from app.sources.frames import FramesSource
from app.sources.prices import CsvFilePrices, FredSeries, PriceFetchError

RESULTS = Path("results")


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the arguments, make the view, print it and write it."""
    parser = argparse.ArgumentParser(prog="market-view")
    parser.add_argument("ticker")
    parser.add_argument("--price", type=float, required=True, help="USD per share")
    parser.add_argument("--price-date", type=date.fromisoformat, required=True)
    parser.add_argument("--claim", default="")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    parser.add_argument("--prices", type=Path, default=None, help="a CSV of the stock's closes")
    parser.add_argument("--index", default="", help="'fred' for FRED SP500, or a CSV path")
    parser.add_argument("--accession", default=None)
    parser.add_argument("--days", type=int, default=3)
    for name in (
        "discount-rate",
        "terminal-growth",
        "tax-rate",
        "operating-margin",
        "sales-to-capital",
    ):
        parser.add_argument(f"--{name}", type=float, default=None)
    args = parser.parse_args(argv)
    today = datetime.now(UTC).date()
    if args.as_of is not None and (problem := as_of_problem(args.as_of, today)):
        print(f"market-view: {problem}", file=sys.stderr)
        return 2
    if not args.price > 0:
        print("market-view: the price must be positive", file=sys.stderr)
        return 2
    root = Path.cwd()
    try:
        stock = (
            CsvFilePrices(args.prices, root).series(args.ticker.upper()) if args.prices else None
        )
        index = None
        if args.index == "fred":
            index = FredSeries(wiring.prices_dir()).series("SP500")
        elif args.index:
            index = CsvFilePrices(Path(args.index), root).series("INDEX")
    except PriceFetchError as exc:
        print(f"market-view: {exc}", file=sys.stderr)
        return 1
    price = Price(
        args.price, args.price_date, f"price supplied on the command line for {args.price_date}"
    )
    dcf = DcfInputs(
        discount_rate=args.discount_rate,
        terminal_growth=args.terminal_growth,
        tax_rate=args.tax_rate,
        operating_margin=args.operating_margin,
        sales_to_capital=args.sales_to_capital,
    )
    with wiring.filings_from_env() as edgar:
        frames = FramesSource(edgar.get, wiring.frames_dir())
        try:
            company = edgar.company(args.ticker)
            view = market_view(
                company,
                edgar,
                frames,
                price=price,
                today=today,
                as_of=args.as_of,
                claim=args.claim,
                dcf=dcf,
                stock=stock,
                index=index,
                accession=args.accession,
                days=args.days,
            )
        except (SourceError, UnknownTicker) as exc:
            print(f"market-view: {exc}", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(f"market-view: {exc}", file=sys.stderr)
            return 2
    print("\n".join(describe(view)))
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS / f"market-{company.ticker}-{stamp}.json"
    out.write_text(view.model_dump_json(indent=2), encoding="utf-8")
    print(f"market-view: {frames.requests} frame request(s); written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
