"""Probe how well live 8-Ks split into their items (run through ``make events-probe``).

``python -m app.events_probe TICKER [TICKER ...]`` lists every 8-K and 8-K/A each
company filed in the last 12 months (:meth:`EdgarClient.current_reports`), fetches
each one, splits it with :func:`app.sources.current_report.parse_current_report`
and checks, for every item EDGAR's index lists for the filing, whether the
splitter found a section headed with that item. It prints a Markdown report: found
over listed per company and overall, then every miss with its accession and
reason. It writes the report to ``results/events-probe-<UTC time>.md``. A filing
that cannot be fetched counts each of its items as missed, with the reason. This
is a diagnostic for the splitter, not part of a thesis run.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from ed_v13.core import events as rules
from ed_v13.core.documents import FilingRef
from ed_v13.core.ports import FilingSource, SourceError
from ed_v13.sources.current_report import parse_current_report
from ed_v13.sources.edgar import EdgarClient

RESULTS_DIR = Path("results")
WINDOW_DAYS = 365
NO_HEADING = "no section headed with this item"
NO_ITEMS = "the document has no item heading at all"
NOT_LISTED = "the index lists no item for this filing"
MAX_MENTIONS = 3
MENTION_CHARS = 160


@dataclass
class Miss:
    """One listed item the splitter did not find, and why."""

    ticker: str
    filed: str
    accession: str
    item: str
    reason: str
    url: str
    context: list[str] = field(default_factory=list)


@dataclass
class CompanyProbe:
    """What the splitter made of one company's 8-Ks."""

    ticker: str
    filings: int = 0
    listed: int = 0
    found: int = 0
    unlisted: int = 0
    misses: list[Miss] = field(default_factory=list)
    error: str = ""


def mentions(text: str, number: str) -> list[str]:
    """Up to :data:`MAX_MENTIONS` lines of ``text`` naming item ``number``, shortened."""
    lines = [line.strip() for line in text.splitlines() if number in line]
    return [
        line if len(line) <= MENTION_CHARS else line[: MENTION_CHARS - 1] + "…"
        for line in lines[:MAX_MENTIONS]
    ]


def probe_filing(ticker: str, ref: FilingRef, html: str, result: CompanyProbe) -> None:
    """Count the listed items of one fetched 8-K that its split document heads."""
    document = parse_current_report(
        html, url=ref.url, title=f"{ticker} {ref.form}", published_date=ref.filed_date
    )
    sections = rules.item_sections(document)
    if not ref.items:
        result.misses.append(Miss(ticker, ref.filed_date, ref.accession, "-", NOT_LISTED, ref.url))
    for number in ref.items:
        result.listed += 1
        if number in sections:
            result.found += 1
            continue
        reason = NO_HEADING if sections else NO_ITEMS
        miss = Miss(ticker, ref.filed_date, ref.accession, number, reason, ref.url)
        miss.context = mentions(document.text, number)
        result.misses.append(miss)
    result.unlisted += len(set(sections) - set(ref.items))


def probe_company(ticker: str, filings: FilingSource, since: str) -> CompanyProbe:
    """List and split every 8-K one company filed after ``since``."""
    result = CompanyProbe(ticker)
    try:
        company = filings.company(ticker)
        refs = filings.current_reports(company, since)
    except SourceError as exc:
        result.error = str(exc)
        return result
    for ref in refs:
        result.filings += 1
        try:
            html = filings.fetch(ref).html
        except SourceError as exc:
            for number in ref.items:
                result.listed += 1
                result.misses.append(
                    Miss(ticker, ref.filed_date, ref.accession, number, str(exc), ref.url)
                )
            continue
        probe_filing(ticker, ref, html, result)
    return result


def _share(found: int, listed: int) -> str:
    return f"{found}/{listed} ({found / listed:.1%})" if listed else "0/0"


def render(results: Iterable[CompanyProbe], since: str, stamp: str) -> str:
    """The report: per company and overall found over listed, then every miss."""
    rows = list(results)
    lines = [
        f"# 8-K splitter probe, {stamp}",
        "",
        f"Every 8-K and 8-K/A filed after {since} (the last {WINDOW_DAYS} days), as EDGAR's "
        "index lists them. An item is found when the split document has a section headed "
        "with its number. Denominator: the items the index lists.",
        "",
        "| Ticker | 8-Ks | Items listed | Items found | Headed but not listed | Error |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row.ticker} | {row.filings} | {row.listed} | {_share(row.found, row.listed)} "
            f"| {row.unlisted} | {row.error} |"
        )
    total_listed = sum(r.listed for r in rows)
    total_found = sum(r.found for r in rows)
    lines.append(
        f"| All | {sum(r.filings for r in rows)} | {total_listed} "
        f"| {_share(total_found, total_listed)} | {sum(r.unlisted for r in rows)} | |"
    )
    misses = [miss for row in rows for miss in row.misses]
    lines += ["", f"## Misses ({len(misses)})", ""]
    if not misses:
        lines.append("None.")
    else:
        lines += ["| Ticker | Filed | Accession | Item | Reason |", "|---|---|---|---|---|"]
        lines += [
            f"| {m.ticker} | {m.filed} | [{m.accession}]({m.url}) | {m.item} | {m.reason} |"
            for m in misses
        ]
        lines += ["", "Lines of each missed document that name the item:", ""]
        for m in misses:
            found = "; ".join(f"`{line.replace('`', ' ')}`" for line in m.context) or "none"
            lines.append(f"- {m.ticker} {m.accession}, Item {m.item}: {found}")
    return "\n".join(lines) + "\n"


def main(
    argv: list[str] | None = None,
    *,
    source: FilingSource | None = None,
    today: date | None = None,
    out_dir: Path = RESULTS_DIR,
) -> int:
    """Probe the companies named on the command line; print and save the report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tickers", nargs="+", help="tickers, such as NVDA AAPL")
    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    since = ((today or now.date()) - timedelta(days=WINDOW_DAYS)).isoformat()
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    if source is None:
        with EdgarClient.from_env() as client:
            results = [probe_company(t.upper(), client, since) for t in args.tickers]
    else:
        results = [probe_company(t.upper(), source, since) for t in args.tickers]
    report = render(results, since, stamp)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"events-probe-{stamp}.md"
    path.write_text(report)
    print(report)
    print(f"events-probe: wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
