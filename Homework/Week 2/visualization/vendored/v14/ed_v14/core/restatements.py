"""The restatement ledger: every metric and period whose value differs between filings.

Pure. Built from a :class:`app.core.facts.FactBook` (so, as of a date, only from
the facts filed by then). The rules:

- A metric here is a concept group of :data:`app.core.facts.GROUPS` (revenue, net
  income, diluted EPS, cash, ...), and a period is exact start and end dates as
  reported. Every period length is listed: quarters, years, year-to-date periods
  and balance-sheet dates.
- Each filing counts once per period. When one filing tags the period under two
  concepts of the group, the concept earlier in the group's order is taken (a
  broader total tagged beside the preferred concept is not a restatement).
- Reports are read in filing order. A value counts as changed when it differs from
  the last value kept by more than the tolerance: USD 1,000,000 for amounts (most
  of these filings round to the million, and a sum of rounded parts can be one
  million off), USD 0.01 for per-share amounts. Each change is kept with its
  filing and its difference from the value before it, in USD and in percent.
- The denominator is every period of a metric that at least two filings reported
  (``periods_checked``); a period listed is one with at least one change.
- A value that goes back to one the period had before the value it replaces is
  marked ``returns_to_earlier``: one filing in between gave the period another value,
  which is more often a period tagged with the wrong dates than two restatements.

A change by a stock split (every earlier per-share value divided by the split
ratio) is a restatement of presentation, not of results; the ledger lists it like
any other and says so in a note when per-share values changed.
"""

from __future__ import annotations

from ed_v14.core.fact_models import LedgerEntry, LedgerValue, RestatementLedger
from ed_v14.core.facts import GROUPS, FactBook, Period, length_words, period_length
from ed_v14.core.metric_models import FactRef
from ed_v14.core.metrics import eps_text, percent_text, usd_text

TOLERANCE_USD = 1_000_000.0
TOLERANCE_PER_SHARE = 0.01
TOLERANCE_NOTE = (
    "Two values of one period count as the same when they differ by at most USD 1,000,000 "
    "(USD 0.01 for a per-share amount): most of these filings round to the million, and a "
    "total of rounded parts can be one million off."
)
SPLIT_NOTE = (
    "Per-share values are restated after a stock split: a change by a whole-number factor is "
    "most likely one, a change of presentation rather than of results."
)
# A small floating-point allowance, so that a difference of exactly the tolerance is equal.
EPSILON = 1e-9


def same_value(first: float, second: float, unit: str) -> bool:
    """True when two values of one period differ by no more than the tolerance for ``unit``."""
    tolerance = TOLERANCE_PER_SHARE if unit == "USD/shares" else TOLERANCE_USD
    return abs(first - second) <= tolerance + EPSILON


def _display(value: float, unit: str, *, signed: bool = False) -> str:
    text = eps_text(value) if unit == "USD/shares" else usd_text(value)
    return f"+{text}" if signed and value > 0 else text


def period_kind(period: Period) -> str:
    """ "instant", the length's name ("quarter", "half_year", ...), or "other"."""
    start, end = period
    if start is None:
        return "instant"
    return period_length(start, end) or "other"


def period_label(period: Period) -> str:
    """ "As of 2026-07-26", "Three months ended 2026-07-26", "Fiscal year ended 2026-01-25"."""
    start, end = period
    if start is None:
        return f"As of {end.isoformat()}"
    words = length_words(start, end)
    return f"{words[0].upper()}{words[1:]} ended {end.isoformat()}"


def _one_per_filing(refs: list[FactRef], order: tuple[str, ...]) -> list[FactRef]:
    """One report per filing, in filing order: the preferred concept's when several are tagged."""
    rank = {concept: position for position, concept in enumerate(order)}
    chosen: dict[str, FactRef] = {}
    for ref in refs:
        held = chosen.get(ref.accession)
        if held is None or (rank.get(ref.concept, len(order)), ref.value) < (
            rank.get(held.concept, len(order)),
            held.value,
        ):
            chosen[ref.accession] = ref
    return sorted(chosen.values(), key=lambda ref: (ref.filed, ref.accession))


def _ledger_value(ref: FactRef, before: LedgerValue | None, unit: str) -> LedgerValue:
    value = LedgerValue(
        value=ref.value,
        display=_display(ref.value, unit),
        accession=ref.accession,
        form=ref.form,
        filed=ref.filed,
        concept=ref.concept,
    )
    if before is None:
        return value
    change = ref.value - before.value
    value.change = change
    value.change_display = _display(change, unit, signed=True)
    if before.value != 0:
        value.change_percent = change / abs(before.value) * 100
        value.change_percent_display = percent_text(value.change_percent, signed=True)
    return value


def _entry(key: str, period: Period, refs: list[FactRef]) -> LedgerEntry | None:
    """The ledger entry of one period, or None when no filing changed its value."""
    group = GROUPS[key]
    values: list[LedgerValue] = []
    for ref in refs:
        if values and same_value(values[-1].value, ref.value, group.unit):
            continue
        value = _ledger_value(ref, values[-1] if values else None, group.unit)
        value.returns_to_earlier = any(
            same_value(earlier.value, ref.value, group.unit) for earlier in values[:-1]
        )
        values.append(value)
    if len(values) < 2:
        return None
    start, end = period
    return LedgerEntry(
        key=key,
        label=group.label,
        unit=group.unit,
        period=period_kind(period),
        start=start.isoformat() if start else None,
        end=end.isoformat(),
        period_label=period_label(period),
        reports=len(refs),
        values=values,
        concept_changed=len({value.concept for value in values}) > 1,
    )


def build_ledger(book: FactBook, *, ticker: str = "") -> RestatementLedger:
    """Every restated period of every concept group of ``book``, as its facts allow."""
    ledger = RestatementLedger(
        company=book.name,
        cik=book.cik,
        ticker=ticker,
        as_of=book.as_of.isoformat() if book.as_of else "",
        tolerance_note=TOLERANCE_NOTE,
        metrics_checked=list(GROUPS),
        notes=list(book.problems),
    )
    for key, group in GROUPS.items():
        entries: list[LedgerEntry] = []
        for period in book.periods(key):
            refs = _one_per_filing(book.reports(key, *period), group.concepts)
            if len(refs) < 2:
                continue
            ledger.periods_checked += 1
            entry = _entry(key, period, refs)
            if entry is not None:
                entries.append(entry)
        entries.sort(key=lambda e: (e.end, e.start or ""), reverse=True)
        ledger.entries.extend(entries)
    ledger.periods_restated = len(ledger.entries)
    if any(entry.unit == "USD/shares" for entry in ledger.entries):
        ledger.notes.append(SPLIT_NOTE)
    return ledger
