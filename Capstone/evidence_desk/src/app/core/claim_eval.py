"""Evaluate a compiled claim against one company's dated facts, now and as of past filings.

Pure. :func:`evaluate` binds a :class:`~app.core.claimtest.ClaimTest`'s periods to
dates in a :class:`~app.core.facts.FactBook` (the latest quarter, the same quarter a
year earlier, fiscal 2026 ...), reads every value it needs through the same
arithmetic as :mod:`app.core.metrics`, compares the two sides and returns a
:class:`~app.core.claim_test_models.ComputedTest`: holds, fails, or cannot be
computed and why, with every operand's facts (accession, form, filing date), the
arithmetic written out and the margin. :func:`claim_history` does the same as of
each 10-K and 10-Q filing date of the last :data:`~app.core.limits.HISTORY_YEARS`
years, each from only the facts filed by that day (``FactBook(as_of=...)``), and
marks where the outcome flips.

Rules a reader can check:

- **Periods.** ``Q`` is the newest quarter with revenue; ``Q-4`` the quarter ending
  about a year before it (:func:`app.core.metrics.year_earlier`); ``Q-1`` the one
  before it (:func:`~app.core.metrics.quarter_earlier`). ``FY`` is the newest fiscal
  year an annual report gave. A named year or quarter is found by the company's fiscal
  calendar (:func:`app.core.periods.fiscal_calendar`); without one, by the calendar
  year of the period's end, and the test says so. A balance-sheet amount is read at
  its newest date for ``Q``, and at the fiscal year's end for ``FY``.
- **Measures.** Those of :mod:`app.core.metrics`, computed by its own functions, plus
  the reported facts behind them. Operating expenses are gross profit less operating
  income (a house definition, said in the operand's note). Four quarters (``TTM``) are
  the sum of four consecutive standalone quarters; a ratio over them is the sum of its
  numerators over the sum of revenue. Earnings per share and balances have no TTM.
- **Growth** needs a positive base. A **streak** counts the periods in a row, ending
  with the bound one, each higher than the period before it (the previous quarter, or
  the previous fiscal year); when the facts run out before the streak is long enough
  and before any fall, it cannot be computed. **Compound** growth is
  ``(latest ÷ earlier)^(1/years) − 1`` over fiscal years.
- **Shares of revenue** are read from the newest filing's tagged breakdowns
  (:mod:`app.core.breakdowns`), newest period: a segment or product, or a geography,
  over the breakdown's total; the largest customer's tagged share (rows also tagged
  with a segment are left out: the tags do not say what they are a share of). They
  have no history.
"""

from __future__ import annotations

import operator
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from app.core import limits, policy
from app.core.breakdown_models import Breakdown, BreakdownReport, BreakdownRow, BreakdownValue
from app.core.claim_test_models import (
    ComputedOutcome,
    ComputedTest,
    HistoryPoint,
    Operand,
    OperandUnit,
)
from app.core.claimtest import METRICS, RATIO_OF, ClaimTest, Number, Period, Term
from app.core.facts import GROUPS, FactBook, PeriodValue
from app.core.metric_models import FactRef
from app.core.metrics import (
    DEFINITIONS,
    DURATION_GROUPS,
    IN_MILLIONS,
    MINUS,
    YEAR_MATCH_DAYS,
    Outcome,
    direct,
    display_text,
    eps_text,
    flow_outcomes,
    millions_text,
    one_year_before,
    percent_text,
    quarter_earlier,
    unavailable,
    usd_text,
    year_earlier,
)
from app.core.periods import FiscalCalendar, fiscal_calendar

SlotKind = Literal["quarter", "annual", "instant", "ttm"]
OPS: dict[str, Callable[[float, float], bool]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}
OPEX_NOTE = (
    "Operating expenses here are gross profit less operating income, a house definition that "
    "can differ from the total the company reports."
)
NO_CALENDAR_NOTE = (
    "The fiscal calendar could not be read from the facts: a fiscal year here is the calendar "
    "year its period ends in."
)
PERIODIC_FORMS = ("10-K", "10-Q")
UNIT_OF: dict[str, OperandUnit] = {
    "flow": "USD",
    "instant": "USD",
    "ratio": "percent",
    "per_share": "USD_per_share",
}
# A ratio's numerator, for a ratio over four quarters.
NUMERATOR_OF = {ratio: measure for measure, ratio in RATIO_OF.items()}
RAW_GROUPS = ("gross_profit", "operating_income", "net_income", "rnd")
SEGMENT_BREAKDOWNS = ("revenue_by_segment", "revenue_by_product")
GEOGRAPHY_BREAKDOWNS = ("revenue_by_geography",)
CUSTOMER_BREAKDOWNS = ("revenue_concentration_by_customer",)


@dataclass(frozen=True)
class Slot:
    """A bound period: its kind, its end, and its label in a bound test ("Q2 FY2027")."""

    kind: SlotKind
    end: date
    label: str
    words: str


@dataclass
class Side:
    """One side of a test once computed: the number, every value read, and the arithmetic."""

    operand: Operand
    operands: list[Operand] = field(default_factory=list)
    arithmetic: list[str] = field(default_factory=list)
    reason: str = ""
    # A streak whose facts ran out before it was long enough and before any fall.
    open_ended: bool = False


# Display


def _unit_of(metric: str) -> OperandUnit:
    return UNIT_OF[METRICS[metric][1]]


def _display(value: float | None, unit: OperandUnit, *, signed: bool = False) -> str:
    if unit == "count":
        return "n/a" if value is None else f"{value:g}"
    return display_text(value, unit, signed=signed)


def _plain(value: float, unit: OperandUnit) -> str:
    """A value inside a formula: USD in millions, per share with cents, percents as shown."""
    if unit == "USD":
        return millions_text(value)
    if unit == "USD_per_share":
        return eps_text(value)
    if unit == "percent":
        return percent_text(value)
    return f"{value:g}"


def _margin_text(margin: float, unit: OperandUnit) -> str:
    if unit == "percent":
        return f"{margin:+.1f} points"
    if unit == "USD":
        return ("+" if margin >= 0 else "") + usd_text(margin)
    if unit == "USD_per_share":
        return ("+" if margin >= 0 else "") + eps_text(margin)
    return f"{margin:+g}"


def _refs(used: Sequence[PeriodValue]) -> list[FactRef]:
    refs: list[FactRef] = []
    for value in used:
        for ref in value.refs:
            if ref not in refs:
                refs.append(ref)
    return refs


# The company's measures


class Measures:
    """Every measure of one company, by period, read once from a :class:`FactBook`."""

    def __init__(self, book: FactBook, calendar: FiscalCalendar | None) -> None:
        self.book = book
        self.calendar = calendar
        self._values = {
            "quarter": {key: book.quarters(key) for key in DURATION_GROUPS},
            "annual": {key: book.annuals(key) for key in DURATION_GROUPS},
        }
        self._flows: dict[tuple[str, date], dict[str, Outcome]] = {}

    # Periods

    def series(self, kind: SlotKind, metric: str) -> dict[date, PeriodValue]:
        """The values whose dates anchor a period of ``kind`` for ``metric``."""
        if METRICS[metric][1] == "instant":
            return self.book.instants(metric)
        values = self._values["annual" if kind == "annual" else "quarter"]
        anchor = values["revenue"]
        if anchor:
            return anchor
        merged: dict[date, PeriodValue] = {}
        for series in values.values():
            merged |= series
        return merged

    def fiscal_year(self, end: date) -> int:
        """The fiscal year label of a period ending ``end``."""
        return self.calendar.fiscal_year(end) if self.calendar else end.year

    def label(self, kind: SlotKind, end: date) -> tuple[str, str]:
        """(label in a bound test, words) for a period."""
        year = self.fiscal_year(end)
        if kind == "annual":
            return f"FY{year}", f"fiscal year ended {end.isoformat()}"
        if kind == "instant":
            return end.isoformat(), f"as of {end.isoformat()}"
        quarter = self.calendar.fiscal_quarter(end) if self.calendar else None
        name = f"Q{quarter} FY{year}" if quarter else f"quarter ended {end.isoformat()}"
        if kind == "ttm":
            return f"TTM to {name}", f"four quarters ended {end.isoformat()}"
        return name, f"quarter ended {end.isoformat()}"

    def slot(self, kind: SlotKind, end: date) -> Slot:
        """A bound period of ``kind`` ending ``end``."""
        label, words = self.label(kind, end)
        return Slot(kind, end, label, words)

    def bind(self, period: Period, metric: str) -> Slot | str:
        """The dates a period stands for, for ``metric``; or why the facts hold none."""
        instant = METRICS[metric][1] == "instant"
        if period.kind == "TTM" and instant:
            return "a balance is at a date; it has no trailing four quarters"
        if period.kind == "FY":
            series = self.series("annual", "revenue")
            if period.fiscal_year is not None:
                ends = [e for e in series if self.fiscal_year(e) == period.fiscal_year]
                if not ends:
                    return (
                        f"The facts hold no {period.text()} "
                        "(no fiscal year labelled so ends in them)."
                    )
                end = max(ends)
            else:
                end_or_none = self._walk(series, max(series, default=None), years=period.back)
                if end_or_none is None:
                    return f"The facts hold no fiscal year for {period.text()}."
                end = end_or_none
            return self._at(metric, "annual", end, instant)
        series = self.series("quarter", "revenue")
        if period.fiscal_year is not None:
            ends = [
                e
                for e in series
                if self.fiscal_year(e) == period.fiscal_year
                and self.calendar is not None
                and self.calendar.fiscal_quarter(e) == period.quarter
            ]
            if not ends:
                return f"The facts hold no {period.text()} (no quarter labelled so ends in them)."
            end = max(ends)
        else:
            latest = max(self.series("quarter", metric) if instant else series, default=None)
            source = self.series("quarter", metric) if instant else series
            walked = self._walk(source, latest, years=period.back // 4, quarters=period.back % 4)
            if walked is None:
                return f"The facts hold no quarter for {period.text()}."
            end = walked
        if instant:
            return self._at(metric, "instant", end, instant)
        return self.slot("ttm" if period.kind == "TTM" else "quarter", end)

    def _at(self, metric: str, kind: SlotKind, end: date, instant: bool) -> Slot | str:
        if not instant:
            return self.slot(kind, end)
        balances = self.book.instants(metric)
        near = [d for d in balances if abs((d - end).days) <= YEAR_MATCH_DAYS]
        if not near:
            return f"No {METRICS[metric][0].lower()} balance is reported near {end.isoformat()}."
        return self.slot("instant", min(near, key=lambda d: abs((d - end).days)))

    @staticmethod
    def _walk(
        series: dict[date, PeriodValue], end: date | None, *, years: int = 0, quarters: int = 0
    ) -> date | None:
        for _ in range(years):
            if end is None:
                return None
            found = year_earlier(series, end)
            end = found.end if found is not None else None
        for _ in range(quarters):
            if end is None:
                return None
            found = quarter_earlier(series, end)
            end = found.end if found is not None else None
        return end

    def year_before(self, slot: Slot, metric: str, years: int = 1) -> Slot | None:
        """The same kind of period ``years`` years before ``slot``."""
        kind: SlotKind = slot.kind
        if kind == "instant":
            series = self.book.instants(metric)
        else:
            series = self.series("annual" if kind == "annual" else "quarter", metric)
        end = self._walk(series, slot.end, years=years)
        return None if end is None else self.slot(kind, end)

    def period_before(self, slot: Slot, metric: str) -> Slot | None:
        """The period before ``slot``: the previous quarter, or the previous fiscal year."""
        if slot.kind == "annual":
            return self.year_before(slot, metric)
        series = (
            self.book.instants(metric) if slot.kind == "instant" else self.series("quarter", metric)
        )
        end = self._walk(series, slot.end, quarters=1)
        return None if end is None else self.slot(slot.kind, end)

    # Values

    def outcome(self, metric: str, slot: Slot) -> Outcome:
        """The value of ``metric`` over ``slot``, by the arithmetic of :mod:`app.core.metrics`."""
        if slot.kind == "instant":
            return direct(self.book.instants(metric).get(slot.end), metric, "instant", slot.end)
        if slot.kind == "ttm":
            return self._ttm(metric, slot.end)
        kind = "annual" if slot.kind == "annual" else "quarter"
        values = self._values[kind]
        if metric in RAW_GROUPS:
            return direct(values[metric].get(slot.end), metric, kind, slot.end)
        if metric == "operating_expenses":
            gross = direct(values["gross_profit"].get(slot.end), "gross_profit", kind, slot.end)
            income = direct(
                values["operating_income"].get(slot.end), "operating_income", kind, slot.end
            )
            for part in (gross, income):
                if part.value is None:
                    return unavailable(part.note, *gross.used, *income.used)
            assert gross.value is not None and income.value is not None
            formula = (
                f"{millions_text(gross.value)} {MINUS} {millions_text(income.value)}{IN_MILLIONS}"
            )
            return Outcome(gross.value - income.value, formula, (*gross.used, *income.used))
        key = (kind, slot.end)
        if key not in self._flows:
            self._flows[key] = flow_outcomes(values, kind, slot.end)
        return self._flows[key][metric]

    def _ttm(self, metric: str, end: date) -> Outcome:
        if METRICS[metric][1] == "per_share":
            return unavailable(
                "Earnings per share over four quarters is not the sum of the quarters: the share "
                "count differs between them."
            )
        ends = [end]
        series = self.series("quarter", "revenue")
        for _ in range(3):
            found = quarter_earlier(series, ends[-1])
            if found is None:
                return unavailable(
                    f"Four consecutive quarters to {end.isoformat()} are not all in the facts."
                )
            ends.append(found.end)
        if METRICS[metric][1] == "ratio":
            top = self._sum(NUMERATOR_OF.get(metric, ""), ends) if metric in NUMERATOR_OF else None
            bottom = self._sum("revenue", ends)
            if top is None or bottom is None or top.value is None or bottom.value is None:
                missing = top if top is not None and top.value is None else bottom
                return unavailable(missing.note if missing else "The four quarters are incomplete.")
            if bottom.value <= 0:
                return unavailable("Not meaningful: revenue over four quarters is not positive.")
            formula = f"{millions_text(top.value)} ÷ {millions_text(bottom.value)}{IN_MILLIONS}"
            return Outcome(top.value / bottom.value * 100, formula, (*top.used, *bottom.used))
        total = self._sum(metric, ends)
        assert total is not None
        return total

    def _sum(self, metric: str, ends: list[date]) -> Outcome | None:
        parts = [self.outcome(metric, self.slot("quarter", end)) for end in ends]
        missing = next((part for part in parts if part.value is None), None)
        used = tuple(value for part in parts for value in part.used)
        if missing is not None:
            return unavailable(missing.note, *used)
        values = [part.value for part in parts if part.value is not None]
        formula = " + ".join(millions_text(v) for v in values) + IN_MILLIONS
        return Outcome(sum(values), formula, used)


# The sides of a test


def _operand(measures: Measures, metric: str, slot: Slot) -> Operand:
    """One measure over one bound period, as an operand with its facts."""
    outcome = measures.outcome(metric, slot)
    unit = _unit_of(metric)
    notes = [DEFINITIONS.get(metric, ""), OPEX_NOTE if metric == "operating_expenses" else ""]
    if outcome.value is None:
        notes.append(outcome.note)
    return Operand(
        term=f"{metric}[{slot.label}]",
        label=f"{METRICS[metric][0]}, {slot.words}",
        value=outcome.value,
        unit=unit,
        display=_display(outcome.value, unit),
        formula=outcome.formula if outcome.value is not None else "",
        inputs=_refs(outcome.used),
        note=" ".join(n for n in notes if n),
    )


def _read_line(operand: Operand) -> str:
    """How an operand was read, as one line of the arithmetic."""
    if operand.value is None:
        return f"{operand.term}: {operand.note}"
    if operand.formula:
        return f"{operand.term} = {operand.formula} = {operand.display}"
    if operand.inputs:
        ref = operand.inputs[0]
        return f"{operand.term} = {operand.display} ({ref.concept}, {ref.form} filed {ref.filed})"
    return f"{operand.term} = {operand.display}"


def _missing(term: str, unit: OperandUnit, reason: str, *read: Operand) -> Side:
    operand = Operand(term=term, label=term, value=None, unit=unit, display="n/a", note=reason)
    return Side(operand, list(read), [_read_line(o) for o in read], reason=reason)


def _first_reason(*operands: Operand) -> str:
    return next((o.note for o in operands if o.value is None), "")


def _value_side(measures: Measures, term: Term) -> Side:
    bound = measures.bind(term.period, term.subject)
    if isinstance(bound, str):
        return _missing(term.text(), _unit_of(term.subject), bound)
    operand = _operand(measures, term.subject, bound)
    side = Side(operand, [operand], [_read_line(operand)])
    if operand.value is None:
        side.reason = operand.note
    return side


def _growth_side(measures: Measures, term: Term) -> Side:
    metric = term.subject
    bound = measures.bind(term.period, metric)
    name = term.fn
    if isinstance(bound, str):
        return _missing(term.text(), "percent", bound)
    earlier = (
        measures.year_before(bound, metric)
        if name == "yoy"
        else measures.period_before(bound, metric)
    )
    label = f"{name}({metric})[{bound.label}]"
    current = _operand(measures, metric, bound)
    if earlier is None:
        what = "a year earlier" if name == "yoy" else "the quarter before"
        return _missing(label, "percent", f"No {what} than {bound.words} is in the facts.", current)
    base = _operand(measures, metric, earlier)
    reason = _first_reason(current, base)
    if reason:
        return _missing(label, "percent", reason, current, base)
    assert current.value is not None and base.value is not None
    if base.value <= 0:
        return _missing(
            label,
            "percent",
            f"Growth is not meaningful: the base ({base.label}) is not positive.",
            current,
            base,
        )
    value = (current.value - base.value) / base.value * 100
    unit = current.unit
    formula = (
        f"({_plain(current.value, unit)} {MINUS} {_plain(base.value, unit)}) ÷ "
        f"{_plain(base.value, unit)}" + (IN_MILLIONS if unit == "USD" else "")
    )
    operand = Operand(
        term=label,
        label=f"{METRICS[metric][0]} growth, {bound.words} on {earlier.words}",
        value=value,
        unit="percent",
        display=percent_text(value, signed=True),
        formula=formula,
        inputs=[*current.inputs, *(r for r in base.inputs if r not in current.inputs)],
    )
    lines = [_read_line(current), _read_line(base), _read_line(operand)]
    return Side(operand, [current, base], lines)


def _cagr_side(measures: Measures, term: Term) -> Side:
    metric = term.subject
    label = term.text()
    bound = measures.bind(term.period, metric)
    if isinstance(bound, str):
        return _missing(label, "percent", bound)
    label = f"cagr({metric}, {term.years}y)[{bound.label}]"
    earlier = measures.year_before(bound, metric, term.years)
    current = _operand(measures, metric, bound)
    if earlier is None:
        return _missing(
            label,
            "percent",
            f"No fiscal year {term.years} years before {bound.words} is in the facts.",
            current,
        )
    base = _operand(measures, metric, earlier)
    reason = _first_reason(current, base)
    if reason:
        return _missing(label, "percent", reason, current, base)
    assert current.value is not None and base.value is not None
    if base.value <= 0 or current.value <= 0:
        return _missing(
            label, "percent", "A compound rate needs both years positive.", current, base
        )
    value = ((current.value / base.value) ** (1 / term.years) - 1) * 100
    formula = (
        f"({millions_text(current.value)} ÷ {millions_text(base.value)})^(1/{term.years}) {MINUS} 1"
    )
    operand = Operand(
        term=label,
        label=f"{METRICS[metric][0]}, compound annual growth from {earlier.label} to {bound.label}",
        value=value,
        unit="percent",
        display=percent_text(value, signed=True),
        formula=formula,
        inputs=[*current.inputs, *(r for r in base.inputs if r not in current.inputs)],
    )
    lines = [_read_line(current), _read_line(base), _read_line(operand)]
    return Side(operand, [current, base], lines)


def _streak_side(measures: Measures, term: Term, wanted: float) -> Side:
    metric = term.subject
    bound = measures.bind(term.period, metric)
    if isinstance(bound, str):
        return _missing(term.text(), "count", bound)
    label = f"streak({metric})[{bound.label}]"
    current = _operand(measures, metric, bound)
    read = [current]
    rises, fell, slot = 0, False, bound
    while rises < limits.MAX_STREAK_PERIODS and current.value is not None:
        before = measures.period_before(slot, metric)
        if before is None:
            break
        previous = _operand(measures, metric, before)
        read.append(previous)
        if previous.value is None:
            break
        if current.value <= previous.value:
            fell = True
            break
        rises += 1
        current, slot = previous, before
    if read[0].value is None:
        return _missing(label, "count", read[0].note, read[0])
    step = "quarter" if bound.kind != "annual" else "fiscal year"
    operand = Operand(
        term=label,
        label=(
            f"{METRICS[metric][0]}: {step}s in a row higher than the {step} before, "
            f"to {bound.label}"
        ),
        value=rises,
        unit="count",
        display=f"{rises}",
        formula=f"{rises} rise(s) in a row" + (", then a fall or no rise" if fell else ""),
        inputs=[ref for o in read for ref in o.inputs[:1]],
    )
    side = Side(operand, read, [*(_read_line(o) for o in read), _read_line(operand)])
    if not fell and rises < wanted:
        side.open_ended = True
        side.reason = (
            f"{rises} rise(s) in a row are known, and the facts reach no further back than "
            f"{slot.words}: whether the streak is {wanted:g} long cannot be told."
        )
    return side


# Shares of revenue


def _key(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def _newest(row: BreakdownRow, item: Breakdown) -> BreakdownValue | None:
    if not item.periods:
        return None
    first = item.periods[0]
    return next(
        (
            v
            for v in row.values
            if v.period_end == first.period_end and v.period_start == first.period_start
        ),
        None,
    )


def _share_ref(
    report: BreakdownReport, item: Breakdown, member: str, value: BreakdownValue
) -> FactRef:
    return FactRef(
        concept=item.concept,
        unit=value.unit,
        start=value.period_start,
        end=value.period_end,
        value=value.value,
        accession=report.filing.accession,
        form=report.filing.form,
        filed=report.filing.filed_date,
        note=f"Tagged on {item.axis} as {member}" if member else "Tagged without a member",
    )


def _share_side(term: Term, reports: Sequence[BreakdownReport]) -> Side:
    label = term.text()
    if not reports:
        return _missing(
            label,
            "percent",
            "No filing's tagged breakdowns were read, so no share of revenue can be computed.",
        )
    ids = {
        "segment": SEGMENT_BREAKDOWNS,
        "geography": GEOGRAPHY_BREAKDOWNS,
        "customer": CUSTOMER_BREAKDOWNS,
    }[term.subject]
    for report in reports:
        for item in report.breakdowns:
            if item.id not in ids or not item.periods:
                continue
            found = (
                _largest_customer(term, report, item)
                if term.fn == "max_share"
                else _member_share(term, report, item)
            )
            if found is not None:
                return found
    filings = ", ".join(f"{r.filing.form} filed {r.filing.filed_date}" for r in reports)
    what = (
        "no customer's share of revenue"
        if term.fn == "max_share"
        else f'no {term.subject} "{term.member}"'
    )
    return _missing(label, "percent", f"The tagged breakdowns read ({filings}) hold {what}.")


def _where(report: BreakdownReport, item: Breakdown) -> str:
    column = item.periods[0]
    return f"{report.filing.form} filed {report.filing.filed_date}, {column.label}"


def _member_share(term: Term, report: BreakdownReport, item: Breakdown) -> Side | None:
    wanted = _key(term.member)
    rows = [row for row in item.rows if _key(row.label) == wanted] or [
        row for row in item.rows if _key(row.label).startswith(wanted)
    ]
    if not rows:
        return None
    row = rows[0]
    value = _newest(row, item)
    if value is None:
        return None
    column = item.periods[0]
    total = next(
        (
            v
            for v in item.total
            if v.period_end == column.period_end and v.period_start == column.period_start
        ),
        None,
    )
    where = _where(report, item)
    label = f'share({term.subject} "{term.member}")[{where}]'
    part = Operand(
        term=f'{term.subject} "{row.label}"[{where}]',
        label=f"{item.title}: {row.label}, {column.label}",
        value=value.value,
        unit="USD",
        display=usd_text(value.value),
        inputs=[_share_ref(report, item, row.member, value)],
    )
    if total is None:
        return _missing(
            label, "percent", f"{item.title} in the {where} tags no total to divide by.", part
        )
    whole = Operand(
        term=f"revenue[{where}]",
        label=f"{item.title}: total, {column.label}",
        value=total.value,
        unit="USD",
        display=usd_text(total.value),
        inputs=[_share_ref(report, item, "", total)],
    )
    if total.value <= 0:
        return _missing(label, "percent", "The tagged total is not positive.", part, whole)
    share = value.value / total.value * 100
    operand = Operand(
        term=label,
        label=f"{row.label} as a share of revenue, {column.label} ({report.filing.form})",
        value=share,
        unit="percent",
        display=percent_text(share),
        formula=f"{millions_text(value.value)} ÷ {millions_text(total.value)}{IN_MILLIONS}",
        inputs=[*part.inputs, *whole.inputs],
    )
    return Side(operand, [part, whole], [_read_line(part), _read_line(whole), _read_line(operand)])


def _largest_customer(term: Term, report: BreakdownReport, item: Breakdown) -> Side | None:
    shares: list[Operand] = []
    where = _where(report, item)
    for row in item.rows:
        if "·" in row.label:
            continue  # also tagged with a segment: a share of what, the tags do not say
        value = _newest(row, item)
        if value is None:
            continue
        percent = value.value * 100 if value.unit == "pure" else value.value
        shares.append(
            Operand(
                term=f'share(customer "{row.label}")[{where}]',
                label=f"{row.label}'s share of revenue, {item.periods[0].label}",
                value=percent,
                unit="percent",
                display=percent_text(percent),
                inputs=[_share_ref(report, item, row.member, value)],
            )
        )
    if not shares:
        return None
    largest = max(shares, key=lambda o: o.value or 0.0)
    operand = largest.model_copy(
        update={
            "term": f"max(share(customer))[{where}]",
            "label": f"Largest tagged customer's share of revenue ({largest.label})",
            "note": (
                "Only the customers a filing discloses are tagged, usually those of 10% or more."
            ),
        }
    )
    lines = [_read_line(o) for o in shares]
    lines.append(f"{operand.term} = max of {len(shares)} tagged = {operand.display}")
    return Side(operand, shares, lines)


# The test


def _side(
    measures: Measures, term: Term, reports: Sequence[BreakdownReport], wanted: float
) -> Side:
    match term.fn:
        case "value":
            return _value_side(measures, term)
        case "yoy" | "qoq":
            return _growth_side(measures, term)
        case "cagr":
            return _cagr_side(measures, term)
        case "streak":
            return _streak_side(measures, term, wanted)
        case _:
            return _share_side(term, reports)


def _constant(number: Number, unit_like: OperandUnit) -> Operand:
    unit: OperandUnit = (
        "count" if number.unit == "count" else "percent" if number.unit == "percent" else unit_like
    )
    if unit == "percent" and number.unit != "percent":
        unit = "USD"
    return Operand(
        term=number.text(),
        label="the threshold",
        value=number.value,
        unit=unit,
        display=number.text(),
    )


def evaluate(
    test: ClaimTest,
    book: FactBook,
    *,
    calendar: FiscalCalendar | None,
    reports: Sequence[BreakdownReport] = (),
) -> ComputedTest:
    """The test computed from ``book`` (only the facts it holds; a book as of a date holds
    only those filed by then), and from ``reports`` for a share of revenue."""
    measures = Measures(book, calendar)
    wanted = test.right.value if isinstance(test.right, Number) else 0.0
    left = _side(measures, test.left, reports, wanted)
    if isinstance(test.right, Number):
        right = Side(_constant(test.right, left.operand.unit))
    else:
        right = _side(measures, test.right, reports, wanted)
    bound = f"{left.operand.term} {test.op} {right.operand.term}"
    operands = [*left.operands, *right.operands]
    arithmetic = [*left.arithmetic, *right.arithmetic]
    shares = test.left.fn in ("share", "max_share")
    notes = [NO_CALENDAR_NOTE] if calendar is None and not shares else []
    l_value, r_value = left.operand.value, right.operand.value
    outcome: ComputedOutcome
    margin: float | None = None
    reason = ""
    if l_value is None or r_value is None:
        outcome = "cannot_compute"
        reason = left.reason or right.reason or "A side could not be computed."
    else:
        holds = OPS[test.op](l_value, r_value)
        margin = l_value - r_value
        if not holds and left.open_ended:
            outcome, reason = "cannot_compute", left.reason
        else:
            outcome = "holds" if holds else "fails"
        arithmetic.append(
            f"{left.operand.display} {test.op} {right.operand.display}: "
            + ("holds" if outcome == "holds" else "fails" if outcome == "fails" else "cannot tell")
        )
    return ComputedTest(
        canonical=test.canonical,
        form=test.form,
        bound=bound,
        outcome=outcome,
        outcome_label=policy.COMPUTED_LABELS[outcome],
        reason=reason,
        comparison=test.op,
        left=left.operand,
        right=right.operand,
        operands=operands,
        arithmetic=arithmetic,
        margin=margin if outcome != "cannot_compute" else None,
        margin_display=(
            _margin_text(margin, left.operand.unit)
            if margin is not None and outcome != "cannot_compute"
            else ""
        ),
        counted_as=policy.COMPUTED_COUNTS.get(outcome, ""),
        note=" ".join(notes),
        as_of=book.as_of.isoformat() if book.as_of else "",
    )


# History


class HistoryBooks:
    """The books of one company as of each of its periodic filing dates, built once each."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self._books: dict[date, tuple[FactBook, FiscalCalendar | None]] = {}
        self._filings: list[tuple[date, str, str]] | None = None

    def at(self, day: date) -> tuple[FactBook, FiscalCalendar | None]:
        """The book and fiscal calendar from the facts filed by ``day``."""
        if day not in self._books:
            self._books[day] = (
                FactBook(self.payload, as_of=day),
                fiscal_calendar(self.payload, as_of=day),
            )
        return self._books[day]

    def filings(self) -> list[tuple[date, str, str]]:
        """Every 10-K and 10-Q that tagged a fact a test reads, one per filing date, oldest first.

        (filed, form, accession); a 10-K wins over a 10-Q filed the same day.
        """
        if self._filings is None:
            concepts = {c for group in GROUPS.values() for c in group.concepts}
            seen: dict[date, tuple[str, str]] = {}
            gaap = self.payload.get("facts", {}).get("us-gaap", {})
            for concept in concepts & set(gaap):
                for entries in gaap[concept].get("units", {}).values():
                    for entry in entries:
                        form = entry.get("form")
                        if form not in PERIODIC_FORMS:
                            continue
                        try:
                            day = date.fromisoformat(entry["filed"])
                        except KeyError, TypeError, ValueError:
                            continue
                        known = seen.get(day)
                        if known is None or (form == "10-K" and known[0] != "10-K"):
                            seen[day] = (form, str(entry.get("accn", "")))
            self._filings = [(day, form, accn) for day, (form, accn) in sorted(seen.items())]
        return self._filings


def claim_history(
    test: ClaimTest,
    payload: dict[str, Any],
    *,
    as_of: date | None = None,
    books: HistoryBooks | None = None,
) -> tuple[list[HistoryPoint], str]:
    """The test as of each 10-K and 10-Q filing date of the last years, oldest first, and a note.

    Only filings on or before ``as_of`` count; the window is the
    :data:`~app.core.limits.HISTORY_YEARS` years to ``as_of`` (or to the newest filing),
    at most :data:`~app.core.limits.MAX_HISTORY_POINTS` points, the newest kept. A share
    of revenue has no history.
    """
    if test.left.fn in ("share", "max_share"):
        return [], policy.COMPUTED_NO_HISTORY
    books = books or HistoryBooks(payload)
    filings = [f for f in books.filings() if as_of is None or f[0] <= as_of]
    if not filings:
        return [], "No 10-K or 10-Q filing date is in the facts, so there is no history."
    last = as_of or filings[-1][0]
    start = last
    for _ in range(limits.HISTORY_YEARS):
        start = one_year_before(start)
    window = [f for f in filings if f[0] > start]
    kept = window[-limits.MAX_HISTORY_POINTS :]
    points: list[HistoryPoint] = []
    previous: str | None = None
    flips = 0
    for day, form, accession in kept:
        book, calendar = books.at(day)
        result = evaluate(test, book, calendar=calendar)
        flipped = (
            result.outcome != "cannot_compute"
            and previous is not None
            and result.outcome != previous
        )
        flips += flipped
        if result.outcome != "cannot_compute":
            previous = result.outcome
        points.append(
            HistoryPoint(
                filed=day.isoformat(),
                form=form,
                accession=accession,
                outcome=result.outcome,
                bound=result.bound,
                left=result.left.value if result.left else None,
                left_display=result.left.display if result.left else "",
                right=result.right.value if result.right else None,
                right_display=result.right.display if result.right else "",
                flipped=flipped,
                reason=result.reason,
            )
        )
    capped = f" (the newest {len(kept)} of {len(window)})" if len(kept) < len(window) else ""
    note = policy.COMPUTED_HISTORY_NOTE.format(
        points=len(points),
        years=limits.HISTORY_YEARS,
        last=last.isoformat(),
        capped=capped,
        flips=flips,
    )
    return points, note
