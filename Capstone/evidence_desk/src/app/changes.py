"""What changed between a company's two latest annual or quarterly reports (``make changes``).

``python -m app.changes TICKER [--form 10-K|10-Q] [--time N]`` compares the latest
filing of the form with the one before it (:mod:`app.services.filing_changes`),
prints the result as Markdown
and writes it to ``results/changes-<ticker>-<form>-<UTC time>.md`` and, as the
record, ``.json``. Filings are read through the filing cache, so a filing a run
has already read is not fetched again. Exit codes: 0 done, 1 EDGAR could not
give both filings, 2 unknown ticker. ``--time N`` also times the comparison with the
candidate index against all pairs (``docs/filing-changes.md``).
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from app.core.change_models import (
    ChangeCounts,
    FilingChanges,
    ItemChanges,
    Paragraph,
    RewordedParagraph,
)
from app.core.filing_diff import MIN_PARAGRAPH_CHARS, REWORD_THRESHOLD, pairs_near_threshold
from app.core.ports import SourceError, UnknownTicker
from app.services.filing_changes import (
    FORMS,
    FilingPair,
    FormFilingSource,
    compare_pair,
    read_filing_pair,
)
from app.sources.edgar import EdgarClient
from app.store import FilingCache

RESULTS_DIR = Path("results")
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_~\[\]<>|])")
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9-]")
PRESENCE = {"both": "both", "earlier": "earlier only", "later": "later only"}
COUNT_COLUMNS = (
    "Item",
    "In",
    "Unchanged",
    "Numbers only",
    "Reworded",
    "Added",
    "Removed",
    "Short lines and table rows added / removed",
)
HOW_TO_READ = (
    "A paragraph is one line of the text extracted from a filing, compared within its Item. "
    "*Unchanged*: the same text, perhaps moved within the Item. *Numbers only*: the same once "
    "numbers, dates and amounts are masked. *Reworded*: at least {threshold:.0%} of the two "
    "paragraphs' distinct words in common. Lines shorter than {min_chars} characters and table "
    "rows are counted, never listed. The comparison does not know why anything changed."
)


def escape(text: str) -> str:
    """``text`` with every Markdown-active character backslash-escaped (filing text is data)."""
    return _MARKDOWN_SPECIAL.sub(r"\\\1", " ".join(text.split()))


def _row(cells: list[str]) -> str:
    return "|" + "|".join(f" {cell} " if cell else " " for cell in cells) + "|"


def _filings_table(changes: FilingChanges) -> list[str]:
    earlier, later = changes.earlier, changes.later
    rows = [
        ("Form", earlier.form, later.form),
        ("Period end", earlier.period_end, later.period_end),
        ("Filed", earlier.filed_date, later.filed_date),
        ("Accession", earlier.accession, later.accession),
        ("Document", f"[open]({earlier.url})", f"[open]({later.url})"),
        ("Item coverage", f"{earlier.item_coverage:.1%}", f"{later.item_coverage:.1%}"),
    ]
    lines = [_row(["", "Earlier", "Later"]), "|---|---|---|"]
    lines += [_row([name, first, second]) for name, first, second in rows]
    return lines


def _counts(item_name: str, presence: str, counts: ChangeCounts) -> list[str]:
    numbers = (counts.unchanged, counts.numbers_only, counts.reworded, counts.added, counts.removed)
    return [
        item_name,
        presence,
        *(str(number) for number in numbers),
        f"{counts.minor_added} / {counts.minor_removed}",
    ]


def _counts_table(changes: FilingChanges) -> list[str]:
    lines = [_row(list(COUNT_COLUMNS)), "|" + "---|" * len(COUNT_COLUMNS)]
    for item in changes.items:
        lines.append(_row(_counts(escape(item.item), PRESENCE[item.present_in], item)))
    lines.append(_row(_counts("Total", "", changes.totals)))
    return lines


def _heading(kind: str, count: int, shown: int) -> str:
    suffix = f"; the first {shown} shown" if shown < count else ""
    return f"### {kind} ({count}{suffix})"


def _paragraph(paragraph: Paragraph, filing: str) -> list[str]:
    where = f"{escape(paragraph.locator)} · [open in the {filing} filing]({paragraph.link})"
    return [f"- {where}", "", f"  > {escape(paragraph.text)}", ""]


def _reworded(pair: RewordedParagraph) -> list[str]:
    before = " ".join(
        escape(s.text) if s.kind == "same" else f"~~{escape(s.text)}~~"
        for s in pair.segments
        if s.kind != "added"
    )
    after = " ".join(
        escape(s.text) if s.kind == "same" else f"**{escape(s.text)}**"
        for s in pair.segments
        if s.kind != "removed"
    )
    where = escape(pair.after.locator)
    if pair.before.locator != pair.after.locator:
        where += f" (earlier under {escape(pair.before.locator)})"
    links = f"[earlier]({pair.before.link}) · [later]({pair.after.link})"
    return [
        f"- {where} · similarity {pair.similarity:.2f} · {links}",
        "",
        f"  Before: {before}",
        "",
        f"  After: {after}",
        "",
    ]


def _item_detail(item: ItemChanges) -> list[str]:
    lines = [f"## {escape(item.item)}", ""]
    if item.present_in != "both":
        lines += [f"Only in the {item.present_in} filing.", ""]
    if item.added:
        lines += [_heading("Added", item.added, len(item.added_paragraphs)), ""]
        for paragraph in item.added_paragraphs:
            lines += _paragraph(paragraph, "later")
    if item.removed:
        lines += [_heading("Removed", item.removed, len(item.removed_paragraphs)), ""]
        for paragraph in item.removed_paragraphs:
            lines += _paragraph(paragraph, "earlier")
    if item.reworded:
        lines += [_heading("Reworded", item.reworded, len(item.reworded_paragraphs)), ""]
        lines += ["Removed words are ~~struck through~~; added words are **bold**.", ""]
        for pair in item.reworded_paragraphs:
            lines += _reworded(pair)
    return lines


def render_markdown(changes: FilingChanges) -> str:
    """The comparison as a Markdown report: filings, counts per Item, then the paragraphs."""
    form = changes.later.form
    lines = [f"# What changed: {escape(changes.company.name)}, {form}", ""]
    lines += [
        f"The {form} for the period ended {changes.later.period_end} against the one before "
        f"it, for the period ended {changes.earlier.period_end}.",
        "",
        *_filings_table(changes),
        "",
    ]
    if changes.notes:
        lines += [*(f"- {escape(note)}" for note in changes.notes), ""]
    how = HOW_TO_READ.format(threshold=REWORD_THRESHOLD, min_chars=MIN_PARAGRAPH_CHARS)
    lines += [how, "", "## Paragraphs by Item", "", *_counts_table(changes), ""]
    for item in changes.items:
        if item.added or item.removed or item.reworded or item.present_in != "both":
            lines += _item_detail(item)
    return "\n".join(lines).rstrip("\n") + "\n"


def _read_pair(
    ticker: str, form: str, source: FormFilingSource, cache: FilingCache | None
) -> FilingPair:
    """Read the two filings through ``cache``, or the configured filing cache when none is given."""
    if cache is not None:
        return read_filing_pair(ticker, form, filings=source, cache=cache)
    from app import wiring  # the composition root, only when no cache is supplied

    configured = wiring.cache_from_env()
    try:
        return read_filing_pair(ticker, form, filings=source, cache=configured)
    finally:
        configured.close()


def _milliseconds(samples: list[float]) -> str:
    ordered = sorted(samples)
    return " | ".join(
        f"{value * 1000:.1f} ms" for value in (statistics.median(ordered), ordered[0], ordered[-1])
    )


def measure(pair: FilingPair, repeats: int, timer: Callable[[], float] = time.perf_counter) -> str:
    """Time the comparison of ``pair`` with the candidate index and over all pairs.

    One discarded run of each first (it also checks the two records agree), then
    ``repeats`` runs of each, interleaved so both meet the same machine load. Only
    the comparison is timed (:func:`compare_pair`); reading and parsing are not.
    """
    same = compare_pair(pair) == compare_pair(pair, exhaustive=True)
    samples: dict[bool, list[float]] = {False: [], True: []}
    for _ in range(repeats):
        for exhaustive in (False, True):
            began = timer()
            compare_pair(pair, exhaustive=exhaustive)
            samples[exhaustive].append(timer() - began)
    lines = [
        "## Timing",
        "",
        f"The comparison alone (reading and parsing excluded), {repeats} interleaved runs of "
        "each, after one discarded run of each.",
        "",
        "| Pairing | Median | Fastest | Slowest |",
        "|---|---|---|---|",
        f"| Candidate index | {_milliseconds(samples[False])} |",
        f"| All pairs | {_milliseconds(samples[True])} |",
        "",
        f"The two give the same record: {'yes' if same else 'NO'}.",
    ]
    return "\n".join(lines) + "\n"


def review(pair: FilingPair, low: float) -> str:
    """The pairs a person should read before trusting the threshold, as a Markdown section.

    Those the comparison paired with a similarity just above :data:`REWORD_THRESHOLD`,
    and those a threshold of ``low`` would pair, which it reports as one removed and one
    added paragraph. The band above is as wide as the band below.
    """
    high = min(1.0, round(2 * REWORD_THRESHOLD - low, 6))
    above, below = pairs_near_threshold(
        pair.earlier,
        pair.later,
        earlier_url=pair.earlier_ref.url,
        later_url=pair.later_ref.url,
        low=low,
        high=high,
    )
    lines = [
        f"## Pairs to read before trusting the threshold ({REWORD_THRESHOLD})",
        "",
        "For each pair, ask whether the two are one paragraph rewritten. A pair just above "
        'the threshold that is not hides an added paragraph inside "reworded"; a pair just '
        "below it that is shows one rewritten paragraph as one removed and one added. "
        "Removed words are ~~struck through~~; added words are **bold**.",
        "",
        f"### Paired, just above it (similarity {REWORD_THRESHOLD} to under {high:g}): "
        f"{len(above)}",
        "",
    ]
    for _, near in above:
        lines += _reworded(near)
    lines += [
        f"### Not paired, just below it (similarity {low:g} to under {REWORD_THRESHOLD}): "
        f"{len(below)}",
        "",
    ]
    for _, near in below:
        lines += _reworded(near)
    return "\n".join(lines).rstrip("\n") + "\n"


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _below_threshold(value: str) -> float:
    number = float(value)
    if not 0 < number < REWORD_THRESHOLD:
        raise argparse.ArgumentTypeError(f"must be above 0 and below {REWORD_THRESHOLD}")
    return number


def main(
    argv: list[str] | None = None,
    *,
    source: FormFilingSource | None = None,
    cache: FilingCache | None = None,
    now: datetime | None = None,
    out_dir: Path = RESULTS_DIR,
) -> int:
    """Compare the filings named on the command line, print the report and save it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ticker", help="the company's ticker, such as NVDA")
    parser.add_argument("--form", choices=FORMS, default="10-K", help="10-K (default) or 10-Q")
    parser.add_argument(
        "--time",
        type=_positive,
        metavar="N",
        help="also time the comparison N times with the candidate index and N times over all pairs",
    )
    parser.add_argument(
        "--review",
        type=_below_threshold,
        metavar="LOW",
        help="also list the pairs to read before trusting the threshold: those paired just "
        "above it and those a threshold of LOW (such as 0.44) would pair",
    )
    args = parser.parse_args(argv)
    try:
        if source is None:
            with EdgarClient.from_env() as client:
                pair = _read_pair(args.ticker, args.form, client, cache)
        else:
            pair = _read_pair(args.ticker, args.form, source, cache)
    except UnknownTicker as exc:
        print(f"ticker: {exc}", file=sys.stderr)
        return 2
    except SourceError as exc:
        print(f"SEC EDGAR: {exc}", file=sys.stderr)
        return 1
    changes = compare_pair(pair)
    report = render_markdown(changes)
    if args.time:
        report += "\n" + measure(pair, args.time)
    if args.review:
        report += "\n" + review(pair, args.review)
    stamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    ticker = _UNSAFE_NAME.sub("", changes.company.ticker.upper())
    stem = out_dir / f"changes-{ticker}-{args.form}-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem.with_name(stem.name + ".md").write_text(report)
    stem.with_name(stem.name + ".json").write_text(changes.model_dump_json(indent=2) + "\n")
    print(report)
    print(f"changes: wrote {stem}.md and .json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
