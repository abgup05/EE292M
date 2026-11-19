"""Figures from a filing's own tagged breakdowns, as metrics an engine may cite by id.

Pure. :func:`tagged_units` turns the :class:`~app.core.breakdown_models.BreakdownReport`
of each filing into :class:`~app.core.metric_models.Metric` records, the shape the
prompt, the citation gate, the number check and every view already know;
:func:`select_tagged` chooses the ones an engine is shown. The rules:

- **What.** For every row of every breakdown, its value in the breakdown's newest
  period and, when the record has one, its change from the same period a year
  earlier, each its own figure. A row with no value in the newest period (a
  customer named only in an earlier year) gives none. The breakdown's total is
  not offered: company-wide revenue is already among the company-facts figures.
- **Ids and keys.** ``tagged:<breakdown>:<member>:<period>:<end>`` and
  ``tagged:<breakdown>:<member>:change:<period>:<end>``; the key is the id without
  its period and end. A row also tagged with a segment ("Customer One · Compute
  and Networking Segment") adds that label's letters to the member, after "+".
  The same filing gives the same ids on every run.
- **Units.** USD in dollars; a share (unit ``pure``, 0.22) as a percent number
  (22.0), as :class:`~app.core.metric_models.Metric` keeps them. A breakdown in
  any other unit, or of year-to-date periods (a 10-Q that tags only those), is left
  out and a note says so.
- **Labels** say what (the breakdown and the member, with its tag name), which
  period, and the filing it is tagged in. The member's label is derived from its
  tag name, not the company's, and every figure's note says so.
- **Selection** (:func:`select_tagged`). A member's value and change go together.
  Members are taken by their place in their breakdown, the largest in the newest
  period first, in every breakdown of every filing at once; among members of the
  same place, the newer filing's period first, then the breakdowns in their usual
  order (segment, product, geography, customers' share of revenue, of
  receivables). Taking stops at the first member whose figures would pass the cap,
  so no smaller member is offered while a larger one is left out.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from ed_v11.core import limits
from ed_v11.core.breakdown_models import Breakdown, BreakdownReport, BreakdownRow, BreakdownValue
from ed_v11.core.metric_models import FactRef, Metric, MetricUnit, PeriodKind
from ed_v11.core.metrics import YEAR_MATCH_DAYS, display_text, one_year_before

TAGGED_PREFIX = "tagged:"
# A breakdown's period kind (Breakdown.period_kind) as a Metric's; year to date has none.
PERIODS: dict[str, PeriodKind] = {
    "fiscal year": "annual",
    "quarter": "quarter",
    "instant": "instant",
}
# A breakdown's unit (BreakdownValue.unit) as a Metric's, and the factor to that unit.
UNITS: dict[str, tuple[MetricUnit, float]] = {"USD": ("USD", 1.0), "pure": ("percent", 100.0)}
_NOT_A_LETTER = re.compile(r"[^A-Za-z0-9]")


@dataclass(frozen=True)
class TaggedUnit:
    """One member's figures from one breakdown of one filing: its value, then its change if any.

    ``rank`` is the member's place in its breakdown (0 for the largest in the
    newest period); ``period_end`` is that period's end; ``order`` is the
    breakdown's place in its filing's report.
    """

    figures: tuple[Metric, ...]
    rank: int
    period_end: str
    order: int


def _filing_words(report: BreakdownReport) -> str:
    filing = report.filing
    return (
        f"as tagged in the {filing.form} filed {filing.filed_date} (accession {filing.accession})"
    )


def _row_key(row: BreakdownRow) -> str:
    """The member's tag name, plus the letters of a qualifying segment's label when there is one."""
    _, _, qualifier = row.label.partition(" · ")
    return f"{row.member}+{_NOT_A_LETTER.sub('', qualifier)}" if qualifier else row.member


def _ref(report: BreakdownReport, item: Breakdown, row: BreakdownRow, v: BreakdownValue) -> FactRef:
    return FactRef(
        concept=item.concept,
        unit=v.unit,
        start=v.period_start,
        end=v.period_end,
        value=v.value,
        accession=report.filing.accession,
        form=report.filing.form,
        filed=report.filing.filed_date,
        note=f"tagged with {item.axis} = {row.member}",
    )


def _year_before(row: BreakdownRow, current: BreakdownValue) -> BreakdownValue | None:
    """The row's value for the same kind of period ending about one year before ``current``."""
    target = one_year_before(date.fromisoformat(current.period_end))
    near = [
        value
        for value in row.values[1:]
        if (value.period_start is None) == (current.period_start is None)
        and abs((date.fromisoformat(value.period_end) - target).days) <= YEAR_MATCH_DAYS
    ]
    return near[0] if near else None


def _row_figures(
    report: BreakdownReport, item: Breakdown, row: BreakdownRow, period: PeriodKind
) -> tuple[Metric, ...]:
    """The value of ``row`` in the newest period, and its change when the record has one."""
    current = row.values[0]
    unit, factor = UNITS[current.unit]
    column = item.periods[0].label
    when = column[:1].lower() + column[1:]
    what = f"{item.title}, {row.label} ({row.member})"
    key = f"{TAGGED_PREFIX}{item.id}:{_row_key(row)}"
    note = (
        f"Read from the filing's inline XBRL: {item.concept} on {item.axis}. The label "
        f"{row.label!r} is derived from the member's tag name ({row.member}); it is not the "
        "company's own label."
    )
    value = current.value * factor
    figures = [
        Metric(
            id=f"{key}:{period}:{current.period_end}",
            key=key,
            label=f"{what}, {when}; {_filing_words(report)}",
            period=period,
            period_end=current.period_end,
            period_label=column,
            value=value,
            unit=unit,
            display=display_text(value, unit),
            inputs=[_ref(report, item, row, current)],
            note=note,
        )
    ]
    if current.change is not None:
        base = _year_before(row, current)
        inputs = [_ref(report, item, row, current)]
        if base is not None:
            inputs.append(_ref(report, item, row, base))
        figures.append(
            Metric(
                id=f"{key}:change:{period}:{current.period_end}",
                key=f"{key}:change",
                label=(
                    f"{what}, change from one year earlier to the {when}; {_filing_words(report)}"
                ),
                period=period,
                period_end=current.period_end,
                period_label=column,
                value=current.change,
                unit="percent",
                display=display_text(current.change, "percent", signed=True),
                formula=current.change_formula,
                inputs=inputs,
                note=note,
            )
        )
    return tuple(figures)


def _left_out(report: BreakdownReport, item: Breakdown, why: str) -> str:
    filing = report.filing
    return (
        f"{item.title} in the {filing.form} for the period ended {filing.period_end} is {why}; "
        "no tagged figure is offered from it."
    )


def tagged_units(reports: Sequence[BreakdownReport]) -> tuple[list[TaggedUnit], list[str]]:
    """Every member's figures from every breakdown of ``reports``; notes on what was left out."""
    units: list[TaggedUnit] = []
    notes: list[str] = []
    for report in reports:
        for order, item in enumerate(report.breakdowns):
            period = PERIODS.get(item.period_kind)
            if period is None:
                notes.append(_left_out(report, item, f"tagged for {item.period_kind} only"))
                continue
            if not item.periods:
                continue
            newest = item.periods[0]
            current = [
                row
                for row in item.rows
                if row.values
                and (row.values[0].period_start, row.values[0].period_end)
                == (newest.period_start, newest.period_end)
            ]
            if any(row.values[0].unit not in UNITS for row in current):
                notes.append(_left_out(report, item, f"in {item.unit_label}"))
                continue
            units += [
                TaggedUnit(_row_figures(report, item, row, period), rank, newest.period_end, order)
                for rank, row in enumerate(current)
            ]
    return units, notes


def _newest_first(unit: TaggedUnit) -> int:
    return -date.fromisoformat(unit.period_end).toordinal()


def _preference(unit: TaggedUnit) -> tuple[int, int, int, str]:
    """Largest members first, the newer period first among equals, then breakdown order."""
    return (unit.rank, _newest_first(unit), unit.order, unit.figures[0].id)


def _reading_order(unit: TaggedUnit) -> tuple[int, int, int, str]:
    """Newest filing first, then breakdown by breakdown, each member from the largest."""
    return (_newest_first(unit), unit.order, unit.rank, unit.figures[0].id)


def select_tagged(
    units: Sequence[TaggedUnit], cap: int = limits.MAX_TAGGED_FIGURES_OFFERED
) -> tuple[list[Metric], list[str]]:
    """The figures an engine is shown, at most ``cap``, in reading order, and a note when cut.

    See the module notes for the rule. The result does not depend on the order of ``units``.
    """
    taken: list[TaggedUnit] = []
    count = 0
    for unit in sorted(units, key=_preference):
        if count + len(unit.figures) > cap:
            break
        taken.append(unit)
        count += len(unit.figures)
    chosen = [figure for unit in sorted(taken, key=_reading_order) for figure in unit.figures]
    built = sum(len(unit.figures) for unit in units)
    notes: list[str] = []
    if count < built:
        notes.append(
            f"{built} tagged figures were read; the {count} offered to the engine take each "
            "breakdown's members from the largest in the newest period, the newer filing first "
            f"among members of the same place, a value always with its change (at most {cap})."
        )
    return chosen, notes
