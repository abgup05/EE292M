"""A company's restatement ledger as text (``make restatements T=NVDA``).

``python -m app.restatements TICKER [--as-of YYYY-MM-DD]`` reads the company's XBRL
company facts from EDGAR (one request) and lists every metric and period whose
value differs between filings: the first value and its filing, each later value,
its filing and the change. It writes ``results/restatements-<ticker>-<UTC>.txt``
and, as the record, ``.json``. No model is involved. Exit codes: 0 done, 1 EDGAR
could not give the facts, 2 an unknown ticker or a date that cannot be used.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

from ed_v14 import wiring
from ed_v14.core.fact_models import RestatementLedger
from ed_v14.core.models import as_of_problem
from ed_v14.core.ports import FilingSource, SourceError, UnknownTicker
from ed_v14.services.restatements import company_restatements

RESULTS_DIR = Path("results")
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9-]")


def ledger_lines(ledger: RestatementLedger) -> list[str]:
    """The ledger as lines of text: a heading, the counts, then each restated period."""
    when = f" as of {ledger.as_of}" if ledger.as_of else ""
    lines = [
        f"Restatements of {ledger.company} ({ledger.ticker or 'CIK ' + str(ledger.cik)}){when}",
        (
            f"{ledger.periods_restated} of {ledger.periods_checked} period(s) reported by at "
            "least two filings changed value in a later filing."
        ),
        ledger.tolerance_note,
    ]
    by_metric = Counter(entry.label for entry in ledger.entries)
    if by_metric:
        lines.append(
            "By metric: " + "; ".join(f"{label} {count}" for label, count in by_metric.items())
        )
    lines += [f"Note: {note}" for note in ledger.notes]
    for entry in ledger.entries:
        moved = " (concept changed)" if entry.concept_changed else ""
        lines.append("")
        lines.append(f"{entry.label}, {entry.period_label}{moved}: {entry.reports} report(s)")
        for value in entry.values:
            change = ""
            if value.change is not None:
                shown = value.change_percent_display
                percent = f", {shown}" if shown else ""
                change = f"  change {value.change_display}{percent}"
                if value.returns_to_earlier:
                    change += " (back to an earlier value)"
            lines.append(
                f"    {value.display:>12}  {value.form:<7} filed {value.filed}  "
                f"{value.accession}  {value.concept}{change}"
            )
    return lines


def main(
    argv: list[str] | None = None, *, filings: FilingSource | None = None, out: Path = RESULTS_DIR
) -> int:
    """Print the ledger of one ticker and write it under ``out``; the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ticker")
    parser.add_argument("--as-of", type=date.fromisoformat, help="only facts filed by this date")
    args = parser.parse_args(argv)
    if args.as_of is not None:
        problem = as_of_problem(args.as_of, datetime.now(UTC).date())
        if problem:
            print(problem, file=sys.stderr)
            return 2
    source = filings or wiring.filings_from_env()
    try:
        company = source.company(args.ticker)
        ledger = company_restatements(
            company,
            source,
            facts_store=None if filings is not None else wiring.facts_from_env(),
            as_of=args.as_of,
        )
    except UnknownTicker as exc:
        print(f"ticker: {exc}", file=sys.stderr)
        return 2
    except SourceError as exc:
        print(f"SEC EDGAR could not give the facts: {exc}", file=sys.stderr)
        return 1
    lines = ledger_lines(ledger)
    print("\n".join(lines))
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stem = out / f"restatements-{_UNSAFE_NAME.sub('-', company.ticker)}-{stamp}"
    stem.with_suffix(".txt").write_text("\n".join(lines) + "\n")
    stem.with_suffix(".json").write_text(ledger.model_dump_json(indent=2) + "\n")
    print(f"\nWrote {stem}.txt and .json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
