"""The breakdowns tagged in a company's latest annual or quarterly report (``make breakdowns``).

``python -m app.breakdowns TICKER [--form 10-K|10-Q]`` reads the latest filing of
the form (:mod:`app.services.breakdowns`): revenue by business segment, by
product or service and by geography, and the share of revenue (and, apart, of
receivables) of major customers, as the filing's own inline XBRL tags them. It
prints them as Markdown and writes ``results/breakdowns-<ticker>-<form>-<UTC
time>.md`` and, as the record, ``.json``. No model is involved. Exit codes: 0
done, 1 EDGAR could not list or deliver the filing, 2 unknown ticker.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from ed_v14.core.breakdown_models import Breakdown, BreakdownReport, BreakdownValue
from ed_v14.core.ports import SourceError, UnknownTicker
from ed_v14.services.breakdowns import FORMS, BreakdownSource, filing_breakdowns
from ed_v14.sources.edgar import EdgarClient

RESULTS_DIR = Path("results")
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_~\[\]<>|])")
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9-]")
TOTAL_LABEL = "Total (tagged, no dimension)"
ADDS_UP = {True: "yes", False: "NO", None: "not checked"}
HOW_TO_READ = (
    "Amounts are in millions of the unit shown, computed from each tagged number and its scale; "
    "the JSON record keeps every number exactly as the filing shows it, with its period's dates. "
    "In brackets: the change from the same period one year earlier, (current − earlier) ÷ "
    "earlier, computed from the tagged values; each formula is written out in the JSON record. "
    "Shares of revenue or receivables are percentages and have no change. Member labels are "
    "derived from the tag names, not the company's own labels."
)


def escape(text: str) -> str:
    """``text`` with every Markdown-active character backslash-escaped (filing text is data)."""
    return _MARKDOWN_SPECIAL.sub(r"\\\1", " ".join(text.split()))


def _row(cells: list[str]) -> str:
    return "|" + "|".join(f" {cell} " if cell else " " for cell in cells) + "|"


def _cell(value: BreakdownValue) -> str:
    """The record's display strings, set side by side; nothing is computed here."""
    if value.change_display:
        return f"{value.display} ({value.change_display})"
    return value.display


def _filing_table(report: BreakdownReport) -> list[str]:
    filing = report.filing
    read = f"{report.facts_read} ({report.facts_unparsed} could not be read)"
    rows = [
        ("Form", filing.form),
        ("Period end", filing.period_end),
        ("Filed", filing.filed_date),
        ("Accession", filing.accession),
        ("Document", f"[open]({filing.url})"),
        ("Numeric facts tagged", read),
    ]
    return [_row(["", "Filing"]), "|---|---|", *(_row([name, value]) for name, value in rows)]


def _table(item: Breakdown) -> list[str]:
    """The breakdown's table: its periods as columns, in the record's order and headings."""
    keys = [(period.period_start, period.period_end) for period in item.periods]
    names = [period.label for period in item.periods]
    lines = [_row(["Member", *names]), "|" + "---|" * (len(names) + 1)]
    for label, row_values in [(escape(r.label), r.values) for r in item.rows] + (
        [(TOTAL_LABEL, item.total)] if item.total else []
    ):
        by_period = {(v.period_start, v.period_end): v for v in row_values}
        lines.append(_row([label, *(_cell(by_period[k]) if k in by_period else "" for k in keys)]))
    return lines


def _breakdown(item: Breakdown) -> list[str]:
    lines = [
        f"## {escape(item.title)}",
        "",
        f"Concept `{item.concept}` on `{item.axis}`; periods: {item.period_kind}; "
        f"{item.unit_label}. "
        f"Members add up to the tagged total: {ADDS_UP[item.adds_up]}.",
        "",
        *_table(item),
        "",
    ]
    if item.notes:
        lines += [*(f"- {escape(note)}" for note in item.notes), ""]
    return lines


def render_markdown(report: BreakdownReport) -> str:
    """The report as Markdown: the filing, how to read it, then one table per breakdown."""
    form = report.filing.form
    lines = [f"# Tagged breakdowns: {escape(report.company.name)}, {form}", ""]
    lines += [
        f"The {form} for the period ended {report.filing.period_end}, as its inline XBRL tags it.",
        "",
        *_filing_table(report),
        "",
    ]
    if report.notes:
        lines += [*(f"- {escape(note)}" for note in report.notes), ""]
    lines += [HOW_TO_READ, ""]
    if not report.breakdowns:
        lines += ["No breakdown is tagged in this filing.", ""]
    for item in report.breakdowns:
        lines += _breakdown(item)
    return "\n".join(lines).rstrip("\n") + "\n"


def main(
    argv: list[str] | None = None,
    *,
    source: BreakdownSource | None = None,
    now: datetime | None = None,
    out_dir: Path = RESULTS_DIR,
) -> int:
    """Read the breakdowns of the filing named on the command line, print them and save them."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ticker", help="the company's ticker, such as NVDA")
    parser.add_argument("--form", choices=FORMS, default="10-K", help="10-K (default) or 10-Q")
    args = parser.parse_args(argv)
    try:
        if source is None:
            with EdgarClient.from_env() as client:
                report = filing_breakdowns(args.ticker, args.form, filings=client)
        else:
            report = filing_breakdowns(args.ticker, args.form, filings=source)
    except UnknownTicker as exc:
        print(f"ticker: {exc}", file=sys.stderr)
        return 2
    except SourceError as exc:
        print(f"SEC EDGAR: {exc}", file=sys.stderr)
        return 1
    markdown = render_markdown(report)
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    ticker = _UNSAFE_NAME.sub("", report.company.ticker.upper())
    stem = out_dir / f"breakdowns-{ticker}-{args.form}-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem.with_name(stem.name + ".md").write_text(markdown)
    stem.with_name(stem.name + ".json").write_text(report.model_dump_json(indent=2) + "\n")
    print(markdown)
    print(f"breakdowns: wrote {stem}.md and .json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
