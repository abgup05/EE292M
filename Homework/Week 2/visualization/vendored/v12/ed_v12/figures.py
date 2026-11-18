"""Probe the reported figures of live companies (run through ``make figures``).

``python -m app.figures TICKER [TICKER ...]`` reads each company's XBRL company
facts through :class:`app.sources.edgar.EdgarClient`, builds the metrics report a
thesis run builds (:func:`app.services.numbers.load_numbers`) and prints, for each
quarter in it: how long the quarter is, its revenue and whether that is a reported
fact or a value derived from year-to-date facts, the change on the same quarter a
year earlier and on the quarter before, and the operating cash flow. It also says
how many figures a run would offer the engine (only figures with a value are
offered) and how many of the report's metrics have no value. The table is written
to ``results/figures-<UTC time>.md``.

A diagnostic for :mod:`app.core.facts` and :mod:`app.core.metrics`, not part of a
thesis run: a change to how periods are placed is not done until this agrees for
every company it is run on. ``--missing`` also lists every metric that has no
value with the reason the report gives. A company that fails gets a line with the
error and the others still run. Nothing here computes a figure: every cell is the display
the report already carries.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from ed_v12.core.metric_models import Metric, MetricsReport
from ed_v12.core.ports import FilingSource, SourceError, UnknownTicker
from ed_v12.services.numbers import load_numbers, select_figures
from ed_v12.sources.edgar import EdgarClient

RESULTS_DIR = Path("results")
COLUMNS = (
    "Ticker",
    "Quarter ended",
    "Days",
    "Revenue",
    "Revenue is",
    "On a year earlier",
    "On the quarter before",
    "Operating cash flow",
)


@dataclass(frozen=True)
class QuarterRow:
    """One quarter of one company, every value as the report displays it."""

    quarter_end: str
    days: int
    revenue: str
    source: str  # "reported" or "derived"
    on_year_earlier: str
    on_quarter_before: str
    cash_flow: str


@dataclass
class CompanyFigures:
    """The quarters of one company, newest first, or why they could not be read."""

    ticker: str
    name: str = ""
    rows: list[QuarterRow] = field(default_factory=list)
    figures_offered: int = 0
    metrics_total: int = 0
    metrics_without_value: int = 0
    keys_without_value: list[str] = field(default_factory=list)
    missing: list[tuple[str, str]] = field(default_factory=list)  # metric id, the report's note
    error: str | None = None


def _display(report: MetricsReport, key: str, end: str) -> str:
    found = [m for m in report.metrics if m.id == f"{key}:quarter:{end}"]
    return found[0].display if found else "n/a"


def _row(report: MetricsReport, revenue: Metric) -> QuarterRow | None:
    """The row of the quarter ``revenue`` is for, or None when it has no value to show."""
    if revenue.value is None or not revenue.inputs:
        return None
    first = revenue.inputs[0]
    if first.start is None:
        return None
    days = (date.fromisoformat(first.end) - date.fromisoformat(first.start)).days + 1
    end = revenue.period_end
    return QuarterRow(
        quarter_end=end,
        days=days,
        revenue=revenue.display,
        source="derived" if first.derived else "reported",
        on_year_earlier=_display(report, "revenue_yoy", end),
        on_quarter_before=_display(report, "revenue_qoq", end),
        cash_flow=_display(report, "operating_cash_flow", end),
    )


def probe_company(source: FilingSource, ticker: str) -> CompanyFigures:
    """The reported figures of ``ticker``; a failure is recorded on the result, never raised."""
    result = CompanyFigures(ticker=ticker.upper())
    try:
        company = source.company(ticker)
    except (UnknownTicker, SourceError) as exc:
        result.error = str(exc)
        return result
    result.ticker, result.name = company.ticker, company.name
    numbers = load_numbers(company, source)
    if numbers.report is None:
        result.error = numbers.error or "the company facts gave no report"
        return result
    report = numbers.report
    quarters = [m for m in report.metrics if m.key == "revenue" and m.period == "quarter"]
    for revenue in sorted(quarters, key=lambda m: m.period_end, reverse=True):
        row = _row(report, revenue)
        if row is not None:
            result.rows.append(row)
    result.figures_offered = len(select_figures(report))
    result.metrics_total = len(report.metrics)
    result.missing = [(m.id, m.note) for m in report.metrics if m.value is None]
    result.metrics_without_value = len(result.missing)
    result.keys_without_value = sorted({m.key for m in report.metrics if m.value is None})
    return result


def probe_all(source: FilingSource, tickers: Iterable[str]) -> list[CompanyFigures]:
    """Probe each ticker in turn; one failure does not stop the rest."""
    return [probe_company(source, ticker) for ticker in tickers]


def _summary(result: CompanyFigures) -> str:
    """One line on a company: figures a run would offer, and what has no value."""
    text = (
        f"- {result.ticker}: a run would offer {result.figures_offered} figures; "
        f"{result.metrics_without_value} of the report's {result.metrics_total} metrics "
        f"have no value ({result.name})."
    )
    if result.keys_without_value:
        text += f" Without a value in some period: {', '.join(result.keys_without_value)}."
    return text


def build_table(results: list[CompanyFigures]) -> str:
    """The quarters as a Markdown table, then one line per company on its figures."""

    def line(cells: Iterable[str]) -> str:
        return "| " + " | ".join(cells) + " |"

    lines = [line(COLUMNS), line("---" for _ in COLUMNS)]
    for result in results:
        if result.error is not None:
            lines.append(line([result.ticker, f"could not be read: {result.error}"]))
            continue
        for row in result.rows:
            lines.append(
                line(
                    [
                        result.ticker,
                        row.quarter_end,
                        str(row.days),
                        row.revenue,
                        row.source,
                        row.on_year_earlier,
                        row.on_quarter_before,
                        row.cash_flow,
                    ]
                )
            )
    lines.append("")
    for result in results:
        if result.error is None:
            lines.append(_summary(result))
    return "\n".join(lines) + "\n"


def build_missing(results: list[CompanyFigures]) -> str:
    """Every metric without a value, with the reason the report gives, company by company."""
    lines: list[str] = []
    for result in results:
        if result.error is not None or not result.missing:
            continue
        lines += ["", f"## {result.ticker}: metrics without a value", ""]
        lines += [f"- `{metric_id}`: {note}" for metric_id, note in result.missing]
    return "\n".join(lines) + "\n" if lines else ""


def main(
    argv: list[str] | None = None,
    *,
    source: FilingSource | None = None,
    now: datetime | None = None,
    out_dir: Path = RESULTS_DIR,
) -> int:
    """Probe the tickers on the command line, print the table and save it under ``out_dir``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tickers", nargs="+", help="tickers to probe, such as NVDA COST")
    parser.add_argument(
        "--missing", action="store_true", help="also list every metric without a value, and why"
    )
    args = parser.parse_args(argv)
    if source is None:
        with EdgarClient.from_env() as client:
            results = probe_all(client, args.tickers)
    else:
        results = probe_all(source, args.tickers)
    report = build_table(results)
    if args.missing:
        report += build_missing(results)
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"figures-{stamp}.md"
    path.write_text(f"# Reported figures probe, {stamp}\n\n{report}")
    print(report)
    print(f"figures: wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
