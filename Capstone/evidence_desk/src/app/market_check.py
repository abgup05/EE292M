"""The outside and market views on the eight probe companies (``make market-check``).

Live: SEC's frames (through the disposable cache), each company's industry list and its
XBRL facts. For each company it prints what the views computed and what they could not:
the two base rates of one fixed test (:data:`CLAIM`), the revenue peer standing, and every
input the valuation and the reverse DCF read from the facts (shares outstanding, debt,
cash, equity, trailing revenue, operating income, net income, free cash flow). No price
is read: there is no source (``docs/market-view.md``), so the market value and the
multiples are not checked here, only the facts they are built from.

Writes the table to ``results/market-check-<UTC>.md``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from app import wiring
from app.core.claim_eval import Measures
from app.core.facts import FactBook, FactsError
from app.core.metrics import usd_text
from app.core.periods import fiscal_calendar
from app.core.ports import SourceError, UnknownTicker
from app.core.valuation import Figure, balance, shares_outstanding, trailing
from app.services.outside_view import outside_view
from app.sources.frames import FramesSource

TICKERS = ("NVDA", "AAPL", "MSFT", "KO", "JPM", "TSLA", "COST", "AMZN")
CLAIM = "Revenue grew more than 10% year over year"
RESULTS = Path("results")


def _figure(figure: Figure) -> str:
    if figure.value is None:
        return f"n/a ({figure.note[:60]})"
    return f"{usd_text(figure.value)} ({figure.period})"


def check(ticker: str, edgar: object, frames: FramesSource, today: datetime) -> list[str]:
    """One company's lines of the table."""
    company = edgar.company(ticker)  # type: ignore[attr-defined]
    view = outside_view(company, CLAIM, edgar, frames, today=today.date())  # type: ignore[arg-type]
    lines = [f"## {company.ticker}: {company.name} (SIC {view.sic} {view.sic_description})", ""]
    for rate in view.base_rates:
        lines.append(f"- base rate, {rate.class_name}: {rate.display or rate.reason}")
        if rate.reading:
            lines.append(f"  - {rate.reading}")
    for peer in view.peers:
        if peer.measure == "revenue" and peer.now is not None:
            now = peer.now
            lines.append(
                f"- revenue standing ({peer.class_name}), {now.year}: "
                + (f"rank {now.rank} of {now.n}, {now.display}" if now.rank else now.reason)
            )
    payload = edgar.company_facts(company)  # type: ignore[attr-defined]
    day = today.date()
    try:
        book = FactBook(payload, as_of=day)
    except FactsError as exc:
        return [*lines, f"- facts: could not be read ({exc})", ""]
    measures = Measures(book, fiscal_calendar(payload, as_of=day))
    shares = shares_outstanding(payload, day)
    lines.append(
        "- shares outstanding: "
        + (
            shares
            if isinstance(shares, str)
            else f"{shares.value:,.0f} on {shares.day} ({shares.concept}, {shares.form} "
            f"filed {shares.filed}, {shares.classes} class(es))"
        )
    )
    for metric, label in (
        ("total_debt", "total debt"),
        ("cash_and_securities", "cash and securities"),
        ("equity", "equity"),
    ):
        lines.append(f"- {label}: {_figure(balance(measures, metric, label))}")
    for metric, label in (
        ("revenue", "trailing revenue"),
        ("operating_income", "trailing operating income"),
        ("net_income", "trailing net income"),
        ("free_cash_flow", "trailing free cash flow"),
    ):
        figure = trailing(measures, metric, label)
        lines.append(f"- {label}: {_figure(figure)}" + (f"; {figure.note}" if figure.note else ""))
    lines.append("")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    """Check every ticker; print and write the table."""
    parser = argparse.ArgumentParser(prog="market-check")
    parser.add_argument("tickers", nargs="*", default=list(TICKERS))
    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    lines = [f"# Market check, {now.isoformat(timespec='seconds')}", "", f"Test: {CLAIM}", ""]
    failed = 0
    with wiring.filings_from_env() as edgar:
        frames = FramesSource(edgar.get, wiring.frames_dir())
        for ticker in args.tickers:
            try:
                lines += check(ticker, edgar, frames, now)
            except (SourceError, UnknownTicker) as exc:
                failed += 1
                lines += [f"## {ticker}", "", f"- failed: {exc}", ""]
        lines.append(f"{frames.requests} frame or list request(s).")
    text = "\n".join(lines)
    print(text)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"market-check-{now.strftime('%Y%m%dT%H%M%SZ')}.md"
    out.write_text(text + "\n", encoding="utf-8")
    print(f"market-check: written to {out}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
