"""Probe how well live filings split into Items (run through ``make probe``).

``python -m app.probe TICKER [TICKER ...]`` fetches each company's latest 10-K
and newest 10-Q through :class:`app.sources.edgar.EdgarClient`, parses them with
:func:`app.sources.filing.parse_filing`, prints a Markdown table and writes it
to ``results/probe-<UTC time>.md``. A company or filing that fails gets a row
with the error and the others still run. This is a diagnostic for the parser,
not part of a thesis run.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ed_v13.core.documents import Document, FilingRef
from ed_v13.core.ports import FilingSource, SourceError
from ed_v13.sources.edgar import EdgarClient
from ed_v13.sources.filing import item_coverage, item_labels, parse_filing

RESULTS_DIR = Path("results")
SEGMENTED_AT = 0.8
PARTLY_SEGMENTED_AT = 0.5
COLUMNS = (
    "Ticker",
    "Form",
    "Period end",
    "Accession",
    "HTML size",
    "Text size",
    "Sections",
    "Items found",
    "Item coverage",
    "Parse time",
    "Verdict",
)

Parser = Callable[..., Document]


@dataclass(frozen=True)
class ProbeRow:
    """What the parser made of one filing, or why it could not be probed."""

    ticker: str
    form: str = ""
    period_end: str = ""
    accession: str = ""
    html_bytes: int | None = None
    text_chars: int | None = None
    sections: int | None = None
    items: int | None = None
    coverage: float | None = None
    parse_seconds: float | None = None
    error: str | None = None
    outline: tuple[tuple[str, int], ...] = ()  # (section heading, characters), when asked


def verdict(coverage: float) -> str:
    """Name the segmentation quality of a filing from its item coverage."""
    if coverage >= SEGMENTED_AT:
        return "segmented"
    if coverage >= PARTLY_SEGMENTED_AT:
        return "partly segmented"
    return "not segmented"


def _row_from(ticker: str, ref: FilingRef, **fields: object) -> ProbeRow:
    return ProbeRow(
        ticker=ticker,
        form=ref.form,
        period_end=ref.period_end,
        accession=ref.accession,
        **fields,  # type: ignore[arg-type]
    )


def probe_company(
    source: FilingSource,
    ticker: str,
    *,
    parse: Parser = parse_filing,
    timer: Callable[[], float] = time.perf_counter,
    outline: bool = False,
) -> list[ProbeRow]:
    """Rows for one company's latest 10-K and the newest 10-Q filed after it.

    With ``outline``, each row also carries every section heading and its size.
    """
    label = ticker.strip().upper()
    try:
        company = source.company(ticker)
        refs = source.periodic_filings(company, 2)
    except SourceError as exc:
        return [ProbeRow(ticker=label, error=str(exc))]
    rows: list[ProbeRow] = []
    for ref in sorted(refs, key=lambda item: item.form != "10-K"):
        try:
            fetched = source.fetch(ref)
        except SourceError as exc:
            rows.append(_row_from(label, ref, error=str(exc)))
            continue
        started = timer()
        try:
            document = parse(
                fetched.html,
                url=ref.url,
                title=f"{company.name} {ref.form} {ref.period_end}",
                published_date=ref.filed_date,
            )
        except Exception as exc:  # noqa: BLE001 - a probe reports any parser failure as a row
            rows.append(_row_from(label, ref, error=f"parse failed: {exc.__class__.__name__}"))
            continue
        rows.append(
            _row_from(
                label,
                ref,
                html_bytes=len(fetched.html.encode("utf-8")),
                text_chars=len(document.text),
                sections=len(document.sections),
                items=len(item_labels(document)),
                coverage=item_coverage(document),
                parse_seconds=timer() - started,
                outline=tuple((s.heading, len(s.text)) for s in document.sections)
                if outline
                else (),
            )
        )
    return rows


def probe_all(
    source: FilingSource, tickers: Iterable[str], *, outline: bool = False
) -> list[ProbeRow]:
    """Probe every ticker in order; one company's failure does not stop the rest."""
    return [row for ticker in tickers for row in probe_company(source, ticker, outline=outline)]


def build_outline(rows: Iterable[ProbeRow]) -> str:
    """Every section heading and size of each probed filing, for diagnosing the parser."""
    blocks = []
    for row in rows:
        if row.outline:
            listing = "".join(f"{size:7d}  {heading}\n" for heading, size in row.outline)
            title = f"### {row.ticker} {row.form} {row.period_end} ({row.accession})"
            blocks.append(f"{title}\n\n```\n{listing}```\n")
    return "\n".join(blocks)


def _cell(value: object) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")


def _cells(row: ProbeRow) -> list[str]:
    if row.error is not None:
        filled = [row.ticker, row.form, row.period_end, row.accession]
        return [*filled, *([""] * (len(COLUMNS) - len(filled) - 1)), f"error: {row.error}"]
    assert row.coverage is not None and row.parse_seconds is not None
    return [
        row.ticker,
        row.form,
        row.period_end,
        row.accession,
        f"{row.html_bytes:,} B",
        f"{row.text_chars:,} chars",
        str(row.sections),
        str(row.items),
        f"{row.coverage:.1%}",
        f"{row.parse_seconds:.2f} s",
        verdict(row.coverage),
    ]


def build_table(rows: Iterable[ProbeRow]) -> str:
    """The rows as a Markdown table, one line per filing."""

    def line(cells: list[str]) -> str:
        return "|" + "|".join(f" {_cell(cell)} " if cell else " " for cell in cells) + "|"

    lines = [line(list(COLUMNS)), "|" + "---|" * len(COLUMNS)]
    lines.extend(line(_cells(row)) for row in rows)
    return "\n".join(lines) + "\n"


def main(
    argv: list[str] | None = None,
    *,
    source: FilingSource | None = None,
    now: datetime | None = None,
    out_dir: Path = RESULTS_DIR,
) -> int:
    """Probe the tickers on the command line, print the table and save it under ``out_dir``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tickers", nargs="+", help="tickers to probe, such as NVDA BRK.B")
    parser.add_argument("--outline", action="store_true", help="also list every section")
    args = parser.parse_args(argv)
    if source is None:
        with EdgarClient.from_env() as client:
            rows = probe_all(client, args.tickers, outline=args.outline)
    else:
        rows = probe_all(source, args.tickers, outline=args.outline)
    report = build_table(rows)
    if args.outline:
        report += "\n" + build_outline(rows)
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"probe-{stamp}.md"
    path.write_text(f"# Filing segmentation probe, {stamp}\n\n{report}")
    print(report)
    print(f"probe: wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
