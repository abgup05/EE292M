"""Probe which catalogue measures live companies report (run through ``make measures-probe``).

``python -m app.measures_probe TICKER [TICKER ...]`` reads each company's XBRL company
facts and newest 10-K through :class:`app.sources.edgar.EdgarClient`. For every measure
of :data:`app.core.measures.CATALOGUE` it computes the newest fiscal year as a claim test
does (:func:`app.core.claim_eval.evaluate` on ``measure[FY]``), so a value here is a value
a claim test gets, and a miss carries the reason a claim test would give. From the newest
10-K's tagged breakdowns it says whether the filing tags a segment's revenue, both years of
it, a segment's operating income (a breakdown read only for claim tests), a product's
revenue and a geography's.

The table, per measure: how many of the companies read have a value, and which do not,
with the reason; then a row per company on its parts. A company that fails is listed with
its error and is not in any denominator. Written to ``results/measures-<UTC time>.md``.
A diagnostic, not part of a thesis run, and it computes nothing of its own: every value is
the evaluator's.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from ed_v14.core.breakdown_models import BreakdownReport
from ed_v14.core.breakdowns import CLAIM_SPECS, SPECS, build_report
from ed_v14.core.claim_eval import evaluate
from ed_v14.core.claimtest import ClaimTest, Number, Period, Term
from ed_v14.core.facts import FactBook
from ed_v14.core.measures import ADDED, CATALOGUE
from ed_v14.core.models import Company
from ed_v14.core.periods import fiscal_calendar
from ed_v14.core.ports import SourceError, UnknownTicker
from ed_v14.services.breakdowns import BreakdownSource, filing_info
from ed_v14.sources.edgar import EdgarClient
from ed_v14.sources.ixbrl import read_tagged_facts

RESULTS_DIR = Path("results")
MAX_REASON_CHARS = 160
NEWEST_YEAR = Period("FY")


class MeasuresSource(BreakdownSource, Protocol):
    """A company's facts and its newest 10-K (:class:`app.sources.edgar.EdgarClient` has both)."""

    def company_facts(self, company: Company) -> dict[str, Any]:
        """The SEC company-facts body. Raises SourceError."""
        ...


@dataclass
class PartsRow:
    """What the newest 10-K tags of a company's parts, or why it could not be read."""

    form: str = ""
    period_end: str = ""
    accession: str = ""
    segment_revenue: bool = False
    segment_both_years: bool = False
    segment_operating_income: bool = False
    product_revenue: bool = False
    product_both_years: bool = False
    geography_revenue: bool = False
    error: str | None = None


@dataclass
class CompanyMeasures:
    """Each measure's newest fiscal year for one company, or why it has none."""

    ticker: str
    name: str = ""
    fiscal_year: str = ""
    values: dict[str, str] = field(default_factory=dict)  # measure -> display
    misses: dict[str, str] = field(default_factory=dict)  # measure -> reason
    parts: PartsRow = field(default_factory=PartsRow)
    error: str | None = None


def _threshold(key: str) -> ClaimTest:
    """``key[FY] > 0``: the test whose left side is the measure's newest fiscal year."""
    unit = "percent" if CATALOGUE[key].kind == "ratio" else "USD"
    return ClaimTest("threshold", Term("value", key, NEWEST_YEAR), ">", Number(0, unit))


def _parts(company: Company, source: MeasuresSource) -> PartsRow:
    """The parts the newest 10-K tags; a failure is recorded on the row, never raised."""
    try:
        ref = source.latest_of_form(company, "10-K")
        html = source.fetch(ref).html
    except SourceError as exc:
        return PartsRow(error=str(exc)[:MAX_REASON_CHARS])
    specs = (*SPECS, *CLAIM_SPECS)
    report = build_report(
        read_tagged_facts(html), company=company, filing=filing_info(ref), specs=specs
    )
    return _parts_of(report)


def _parts_of(report: BreakdownReport) -> PartsRow:
    def tagged(*ids: str) -> tuple[bool, bool]:
        items = [b for b in report.breakdowns if b.id in ids and b.rows]
        both = any(v.change is not None for b in items for r in b.rows for v in r.values)
        return bool(items), both

    segment, segment_both = tagged("revenue_by_segment")
    product, product_both = tagged("revenue_by_product")
    income, _ = tagged("operating_income_by_segment")
    geography, _ = tagged("revenue_by_geography")
    return PartsRow(
        form=report.filing.form,
        period_end=report.filing.period_end,
        accession=report.filing.accession,
        segment_revenue=segment,
        segment_both_years=segment_both,
        segment_operating_income=income,
        product_revenue=product,
        product_both_years=product_both,
        geography_revenue=geography,
    )


def probe_company(source: MeasuresSource, ticker: str) -> CompanyMeasures:
    """Every catalogue measure of ``ticker``; a failure is recorded on the result."""
    result = CompanyMeasures(ticker=ticker.upper())
    try:
        company = source.company(ticker)
        payload = source.company_facts(company)
    except (UnknownTicker, SourceError) as exc:
        result.error = str(exc)[:MAX_REASON_CHARS]
        return result
    result.ticker, result.name = company.ticker, company.name
    book = FactBook(payload)
    calendar = fiscal_calendar(payload)
    for key in CATALOGUE:
        computed = evaluate(_threshold(key), book, calendar=calendar)
        left = computed.left
        if left is not None and left.value is not None:
            result.values[key] = left.display
            result.fiscal_year = result.fiscal_year or left.term.partition("[")[2].rstrip("]")
        else:
            result.misses[key] = " ".join(computed.reason.split())[:MAX_REASON_CHARS]
    result.parts = _parts(company, source)
    return result


def probe_all(source: MeasuresSource, tickers: Iterable[str]) -> list[CompanyMeasures]:
    """Probe each ticker in turn; one failure does not stop the rest."""
    return [probe_company(source, ticker) for ticker in tickers]


def _line(cells: Iterable[str]) -> str:
    return "| " + " | ".join(cell.replace("|", "/") for cell in cells) + " |"


def build_table(results: list[CompanyMeasures]) -> str:
    """Per measure, how many companies have a value and which miss; then the parts."""
    read = [r for r in results if r.error is None]
    added = {m.key for m in ADDED}
    lines = [
        f"Companies read: {len(read)} of {len(results)}. Each value is the newest fiscal year "
        "of a claim test's `measure[FY]`.",
        "",
        _line(("Measure", "Kind", "In the panel", "Have a value", "Misses")),
        _line(("---",) * 5),
    ]
    for key, measure in CATALOGUE.items():
        have = sum(1 for r in read if key in r.values)
        misses = "; ".join(f"{r.ticker}: {r.misses[key]}" for r in read if key in r.misses)
        panel = "no" if key in added else "yes"
        lines.append(_line((key, measure.kind, panel, f"{have} of {len(read)}", misses or "")))
    lines += [
        "",
        "## The newest 10-K's parts",
        "",
        _line(
            (
                "Ticker",
                "10-K period end",
                "Segment revenue",
                "Both years",
                "Segment operating income",
                "Product revenue",
                "Both years",
                "Geography revenue",
            )
        ),
        _line(("---",) * 8),
    ]
    for r in read:
        p = r.parts
        if p.error is not None:
            lines.append(_line((r.ticker, f"not read: {p.error}", *("",) * 6)))
            continue
        flags = (
            p.segment_revenue,
            p.segment_both_years,
            p.segment_operating_income,
            p.product_revenue,
            p.product_both_years,
            p.geography_revenue,
        )
        lines.append(_line((r.ticker, p.period_end, *("yes" if f else "no" for f in flags))))
    failed = [r for r in results if r.error is not None]
    if failed:
        lines += ["", "## Not read", ""]
        lines += [f"- {r.ticker}: {r.error}" for r in failed]
    lines += ["", "Fiscal years read: " + ", ".join(f"{r.ticker} {r.fiscal_year}" for r in read)]
    return "\n".join(lines) + "\n"


def main(
    argv: list[str] | None = None,
    *,
    source: MeasuresSource | None = None,
    now: datetime | None = None,
    out_dir: Path = RESULTS_DIR,
) -> int:
    """Probe the tickers on the command line, print the table and save it under ``out_dir``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tickers", nargs="+", help="tickers to probe, such as NVDA COST")
    args = parser.parse_args(argv)
    if source is None:
        with EdgarClient.from_env() as client:
            results = probe_all(client, args.tickers)
    else:
        results = probe_all(source, args.tickers)
    report = build_table(results)
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"measures-{stamp}.md"
    path.write_text(f"# Measures probe, {stamp}\n\n{report}")
    print(report)
    print(f"measures-probe: wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
