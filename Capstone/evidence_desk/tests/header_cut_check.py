"""Does cutting the inline-XBRL header before parsing change any document? Checked live.

``python -m tests.header_cut_check TICKER [TICKER ...]`` (``make header-cut-check``)
fetches each company's latest 10-K and the newest 10-Q after it, as ``make probe``
does, parses each filing twice, with the parser's header cut and with the cut switched
off (the parse of version 2), and compares the two whole documents: the text, its hash
and every section. It prints one row per filing and exits 1 if any pair differs or any
filing could not be compared.

The parser's one speed change (``docs/speed.md``) was said to change no answer. The
evidence was the offline tripwire, a test on four recorded filings, and, for the other
companies, a comparison of section headings and lengths. Review 6 asked for the whole
document on all of them. This is that check. It shows that the two parses agree on
these filings today; it says nothing about the next filing.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from app.core.ports import FilingSource, SourceError
from app.sources import filing as filing_parser
from app.sources.edgar import EdgarClient
from app.sources.filing import parse_filing

RESULTS_DIR = Path("results")


@dataclass(frozen=True)
class CutRow:
    """One filing parsed both ways, or why it could not be."""

    ticker: str
    form: str = ""
    period_end: str = ""
    has_header: bool = False
    text_chars: int = 0
    content_hash: str = ""
    same: bool = False
    error: str | None = None


def _no_cut(html: str) -> tuple[str, str]:
    """Version 2's parse: the ``ix:header`` block is left in the HTML."""
    return html, ""


def check_company(source: FilingSource, ticker: str) -> list[CutRow]:
    """Rows for one company's latest 10-K and the newest 10-Q filed after it."""
    label = ticker.strip().upper()
    try:
        company = source.company(ticker)
        refs = source.periodic_filings(company, 2)
    except SourceError as exc:
        return [CutRow(ticker=label, error=str(exc))]
    rows: list[CutRow] = []
    for ref in sorted(refs, key=lambda item: item.form != "10-K"):
        try:
            html = source.fetch(ref).html
        except SourceError as exc:
            rows.append(CutRow(label, ref.form, ref.period_end, error=str(exc)))
            continue
        details = {
            "url": ref.url,
            "title": f"{company.name} {ref.form} {ref.period_end}",
            "published_date": ref.filed_date,
        }
        with_cut = parse_filing(html, **details)
        with mock.patch.object(filing_parser, "_cut_ix_headers", _no_cut):
            without_cut = parse_filing(html, **details)
        rows.append(
            CutRow(
                ticker=label,
                form=ref.form,
                period_end=ref.period_end,
                has_header="<ix:header" in html.lower(),
                text_chars=len(with_cut.text),
                content_hash=with_cut.content_hash,
                same=with_cut == without_cut,
            )
        )
    return rows


def build_table(rows: list[CutRow]) -> str:
    """The rows as a Markdown table, then one line of totals."""
    lines = [
        "| Ticker | Form | Period end | Has an ix:header | Text, characters | SHA-256 of the text"
        " | Same document without the cut |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        if row.error is not None:
            lines.append(
                f"| {row.ticker} | {row.form} | {row.period_end} | could not be compared:"
                f" {row.error} | | | |"
            )
            continue
        lines.append(
            f"| {row.ticker} | {row.form} | {row.period_end} | {'yes' if row.has_header else 'no'}"
            f" | {row.text_chars:,} | {row.content_hash[:16]}… | {'yes' if row.same else 'NO'} |"
        )
    compared = [row for row in rows if row.error is None]
    same = sum(1 for row in compared if row.same)
    lines += [
        "",
        f"{same} of {len(compared)} filings parse to the same document with and without the "
        f"header cut; {len(rows) - len(compared)} could not be compared.",
    ]
    return "\n".join(lines) + "\n"


def main(
    argv: list[str] | None = None,
    *,
    source: FilingSource | None = None,
    now: datetime | None = None,
    out_dir: Path = RESULTS_DIR,
) -> int:
    """Check the tickers on the command line, print the table and save it under ``out_dir``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tickers", nargs="+", help="tickers to check, such as NVDA COST")
    args = parser.parse_args(argv)
    if source is None:
        with EdgarClient.from_env() as client:
            rows = [row for ticker in args.tickers for row in check_company(client, ticker)]
    else:
        rows = [row for ticker in args.tickers for row in check_company(source, ticker)]
    report = build_table(rows)
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"header-cut-{stamp}.md"
    path.write_text(f"# Header cut check, {stamp}\n\n{report}")
    print(report)
    print(f"header-cut-check: wrote {path}")
    return 0 if rows and all(row.error is None and row.same for row in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
