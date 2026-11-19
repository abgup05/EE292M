"""The outside and market views on the eight probe companies (``make market-check``).

Live: SEC's frames (through the disposable cache), each company's industry list, its
XBRL facts, and the 13F filings the quarter-end price is read from. For each company it
prints what the views computed and what they could not: the price with its source and
whether a second manager's filing confirms it, the valuation, what the price implies,
the base rates of one fixed test (:data:`CLAIM`) and three peer standings with the
neighbours' names, so that a reader can judge whether the industry class is sensible.

Writes the table to ``results/market-check-<UTC>.md``. Exit code 1 when a company's
views could not be made at all; a result that cannot be computed is a line, not a failure.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from ed_v14 import wiring
from ed_v14.core.ports import FilingSource, SourceError, UnknownTicker
from ed_v14.services.market_view import market_view
from ed_v14.services.outside_view import outside_view
from ed_v14.services.view_analytics import DEFAULT_PEER_MEASURES
from ed_v14.sources.frames import FramesSource
from ed_v14.sources.prices import PriceProvider
from ed_v14.sources.thirteenf import QuarterEndPrices, ThirteenFSource

TICKERS = ("NVDA", "AAPL", "MSFT", "KO", "JPM", "TSLA", "COST", "AMZN")
CLAIM = "Revenue grew more than 10% year over year"
RESULTS = Path("results")


def check(
    ticker: str,
    edgar: FilingSource,
    frames: FramesSource,
    prices: PriceProvider,
    today: date,
    as_of: date | None,
) -> list[str]:
    """One company's lines of the table."""
    company = edgar.company(ticker)
    outside = outside_view(company, CLAIM, edgar, frames, today=today, as_of=as_of)
    market = market_view(company, edgar, frames, prices=prices, today=today, as_of=as_of)
    lines = [
        f"## {company.ticker}: {company.name} (SIC {outside.sic} {outside.sic_description})",
        "",
        f"- price: {market.price_source or 'none'}",
    ]
    if market.price_note:
        lines.append(f"  - {market.price_note}")
    for result in market.valuation:
        lines.append(f"- {result.label}: {result.display}; {result.reading or result.reason}")
        if result.note and result.kind != "market_value":
            lines.append(f"  - {result.note}")
    dcf = market.reverse_dcf
    if dcf is not None:
        lines.append(f"- {dcf.label}: {dcf.display}; {dcf.reading or dcf.reason}")
        lines.extend(f"  - {a}" for a in dcf.assumptions[:6])
        if dcf.note:
            lines.append(f"  - {dcf.note}")
    for rate in outside.base_rates:
        lines.append(f"- base rate, {rate.class_name}: {rate.display or rate.reason}")
        if rate.reading:
            lines.append(f"  - {rate.reading}")
        if rate.cases:
            lines.append(
                "  - nearest: "
                + "; ".join(f"{c.name} {c.year} {c.display}" for c in rate.cases[:3])
            )
    for peer in outside.peers:
        if peer.measure not in ("revenue", *DEFAULT_PEER_MEASURES):
            continue
        lines.append(f"- {peer.reading}")
        if peer.now is not None and peer.now.rank is not None:
            near = [*peer.now.above, *peer.now.below]
            named = "; ".join(f"{n.rank}. {n.name} {n.display}" for n in near)
            lines.append(f"  - next to it: {named}")
    lines.extend(f"- note: {note}" for note in market.notes)
    lines.append("")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    """Check every ticker; print and write the table."""
    parser = argparse.ArgumentParser(prog="market-check")
    parser.add_argument("tickers", nargs="*", default=list(TICKERS))
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    lines = [
        f"# Market check, {now.isoformat(timespec='seconds')}"
        + (f", as of {args.as_of.isoformat()}" if args.as_of else ""),
        "",
        f"Test: {CLAIM}",
        "",
    ]
    failed = 0
    with wiring.filings_from_env() as edgar:
        frames = FramesSource(edgar.get, wiring.frames_dir())
        thirteenf = ThirteenFSource(edgar.get, wiring.thirteenf_dir())
        prices = QuarterEndPrices(thirteenf)
        for ticker in args.tickers or TICKERS:
            try:
                lines += check(ticker, edgar, frames, prices, now.date(), args.as_of)
            except (SourceError, UnknownTicker) as exc:
                failed += 1
                lines += [f"## {ticker}", "", f"- failed: {exc}", ""]
        lines.append(
            f"{frames.requests} frame or list request(s), {thirteenf.requests} 13F request(s); "
            f"{failed} of {len(args.tickers or TICKERS)} companies failed."
        )
    text = "\n".join(lines)
    print(text)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"market-check-{now.strftime('%Y%m%dT%H%M%SZ')}.md"
    out.write_text(text + "\n", encoding="utf-8")
    print(f"market-check: written to {out}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
