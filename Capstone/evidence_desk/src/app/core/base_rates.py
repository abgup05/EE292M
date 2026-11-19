"""Base rates: how often a compiled claim test held among a reference class, from SEC frames.

Pure. :func:`annual_test` reads a :class:`~app.core.claimtest.ClaimTest` as a test on
fiscal years as SEC's annual frames place them; :func:`base_rate` counts, year by year,
the company-years of a reference class for which it held, and of those, how many still
held a year later; :func:`growth_distribution` gives the spread of ten-year revenue
growth for companies of a given size, for the market view's reverse DCF.

The rules:

- **Only annual frames.** A term over the latest quarter or four quarters is read on the
  fiscal year (``Q-4`` is a year earlier, ``Q`` this year), and the result says so; a
  sequential test (``qoq``, ``Q-1``), a streak of quarters, a test in each of several
  periods, a share of revenue and a part of the company are refused with the reason.
- **Measures** are those a frame panel builds (:data:`app.core.frames.MEASURES`); a
  claim naming another catalogue measure is refused, naming it.
- **Growth** needs a positive base and two period ends a whole number of years apart
  (:func:`app.core.frames.years_apart`); compound growth is
  ``(latest ÷ earlier)^(1/years) − 1``. A streak counts the years in a row, ending with
  the year read, each higher than the year before.
- **The class** is decided in the earliest year the test reads (the base of a growth):
  revenue at least the floor there, and, for an industry class, the filer's current SIC
  code. A company-year in the class whose test cannot be computed is counted as such,
  never as a failure. Deciding it in the base year keeps the outcome out of the class: a
  filer is not admitted because it grew. A test of a *level* of revenue reads no earlier
  year, and its outcome is the very measure the class is chosen on: decided in the year
  read, every filer of a class whose floor is above the threshold would hold by
  construction. So for such a test the class is decided a year earlier
  (:attr:`AnnualTest.class_reach`), and the result says so. For a level of any other
  measure the class is still decided in the year read: revenue admits the filer and
  something else is tested.
- **The company itself is left out** of every count, so that a small class is not the
  company's own history; the years in which the test held for it are listed apart.
- **Persistence**: of the company-years for which the test held in year t, those for
  which it could be computed in t + 1, and of them those for which it held.
- **Nearest cases** are the other filers' company-years that held, nearest to the
  company's own value of the test's left side (else to its revenue), at most
  :data:`MAX_CASES`.
"""

from __future__ import annotations

import math
import operator
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.core.claimtest import ClaimTest, Number, Period, Term
from app.core.facts import GROUPS
from app.core.frames import (
    MEASURES,
    Panel,
    frame_source,
    resolution_rule,
    scale_break,
    years_apart,
)
from app.core.metrics import percent_text, usd_text
from app.core.view_models import (
    BaseRate,
    Case,
    ConceptResolution,
    Distribution,
    ResultInput,
    YearCount,
)

MAX_CASES = 5
# The measure a reference class's floor is on (RefClass.admits).
CLASS_MEASURE = "revenue"
LEVEL_CLASS_NOTE = (
    "The test is a level of revenue, the measure the class is chosen on, so the class is "
    "decided a year earlier (t-1): a filer is not admitted because its revenue was already "
    "over the line in the year read."
)
OPS: dict[str, Callable[[float, float], bool]] = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}
PERCENTILES: tuple[int, ...] = (10, 25, 50, 75, 90)
AnnualFn = Literal["value", "yoy", "cagr", "change", "streak"]


@dataclass(frozen=True)
class AnnualTerm:
    """One side of an annual test: a function of a measure ``offset`` years before year t."""

    fn: AnnualFn
    measure: str
    offset: int = 0
    years: int = 0

    @property
    def reach(self) -> int:
        """How many years before year t the term reads, at most."""
        return self.offset + {"yoy": 1, "cagr": self.years, "change": self.years}.get(self.fn, 0)

    def text(self) -> str:
        """The term in the canonical style, with ``t`` the year read: ``yoy(revenue)[t]``."""
        at = "[t]" if not self.offset else f"[t-{self.offset}]"
        if self.fn == "value":
            return f"{self.measure}{at}"
        if self.fn in ("cagr", "change"):
            return f"{self.fn}({self.measure}, {self.years}y){at}"
        return f"{self.fn}({self.measure}){at}"


@dataclass(frozen=True)
class AnnualPart:
    """``left op right``: right is a term or a constant (a percent, an amount, a count)."""

    left: AnnualTerm
    op: str
    right: AnnualTerm | Number

    def text(self) -> str:
        """The part as text."""
        return f"{self.left.text()} {self.op} {self.right.text()}"


@dataclass(frozen=True)
class AnnualTest:
    """A claim test read on fiscal years: its parts (all must hold) and what was translated."""

    parts: tuple[AnnualPart, ...]
    from_quarters: bool = False

    def text(self) -> str:
        """The test as text, parts joined by "and"."""
        if len(self.parts) == 1:
            return self.parts[0].text()
        return " and ".join(f"({part.text()})" for part in self.parts)

    @property
    def reach(self) -> int:
        """How many years before year t the test reads, at most (a streak of N reads N back)."""
        reaches = [p.right.reach for p in self.parts if isinstance(p.right, AnnualTerm)]
        for part in self.parts:
            reach = part.left.reach
            if part.left.fn == "streak" and isinstance(part.right, Number):
                reach += math.ceil(part.right.value)
            reaches.append(reach)
        return max(reaches)

    @property
    def class_reach(self) -> int:
        """How many years before year t the reference class is decided.

        The earliest year the test reads (:attr:`reach`), but never the year read itself
        when a side of the test is the level of :data:`CLASS_MEASURE` in that year: then
        a year earlier, so that the class is not chosen on the outcome.
        """
        terms = [part.left for part in self.parts]
        terms += [part.right for part in self.parts if isinstance(part.right, AnnualTerm)]
        on_class = any(
            term.fn == "value" and term.measure == CLASS_MEASURE and term.offset == 0
            for term in terms
        )
        return max(self.reach, 1) if on_class else self.reach

    @property
    def unit(self) -> str:
        """The unit of the first part's left side: percent, USD or count."""
        return term_unit(self.parts[0].left)


def term_unit(term: AnnualTerm) -> str:
    """``percent`` for a growth or a ratio, ``count`` for a streak, else the measure's unit."""
    if term.fn in ("yoy", "cagr", "change"):
        return "percent"
    if term.fn == "streak":
        return "count"
    return MEASURES[term.measure].unit


# Reading a claim test on years


def _years_back(period: Period, anchor: int | None) -> int | str:
    """How many fiscal years ``period`` is before the year read, or why it is not whole years."""
    if period.kind == "filing":
        return "it reads a filing's tagged breakdowns, which frames do not hold"
    if period.fiscal_year is not None:
        if period.quarter is not None:
            return "it names a fiscal quarter; only annual frames are read"
        assert anchor is not None
        return anchor - period.fiscal_year
    if period.kind == "FY":
        return period.back
    if period.back % 4:
        return "it compares a quarter with the quarter before; only annual frames are read"
    return period.back // 4


def _term(term: Term, anchor: int | None) -> AnnualTerm | str:
    if term.axis or term.fn in ("share", "max_share"):
        return "it reads a part of the company or a share of revenue, which frames do not hold"
    if term.subject not in MEASURES:
        return f"its measure {term.subject} is not built from frames in this version"
    if term.fn == "qoq":
        return "it compares a quarter with the quarter before; only annual frames are read"
    if term.fn == "streak" and term.period.kind != "FY":
        return "it counts quarters in a row; only annual frames are read"
    back = _years_back(term.period, anchor)
    if isinstance(back, str):
        return back
    if back < 0:
        return "a period it names is later than the year read"
    if term.fn == "change":
        if term.base is None:
            return "its change has no earlier period"
        base = _years_back(term.base, anchor)
        if isinstance(base, str):
            return base
        if base <= back:
            return "its earlier period is not earlier"
        return AnnualTerm("change", term.subject, back, base - back)
    if term.fn == "cagr":
        return AnnualTerm("cagr", term.subject, back, term.years)
    if term.fn in ("value", "yoy", "streak"):
        return AnnualTerm(term.fn, term.subject, back)
    return f"its function {term.fn} is not read on frames"


def _periods(test: ClaimTest) -> list[Period]:
    found: list[Period] = []
    for term in test.terms:
        found.append(term.period)
        if term.base is not None:
            found.append(term.base)
    return found


def annual_test(test: ClaimTest) -> AnnualTest | str:
    """``test`` read on fiscal years, or why it cannot be read on annual frames."""
    if test.each or test.each_since is not None:
        return "a test held in each of several periods is not read on frames in this version"
    periods = _periods(test)
    named = [p.fiscal_year for p in periods if p.fiscal_year is not None]
    if named and len(named) != len(periods):
        return "it mixes a named fiscal year with the latest period"
    anchor = max(named) if named else None
    parts: list[AnnualPart] = []
    for part in test.parts:
        left = _term(part.left, anchor)
        if isinstance(left, str):
            return left
        right: AnnualTerm | Number | str
        right = part.right if isinstance(part.right, Number) else _term(part.right, anchor)
        if isinstance(right, str):
            return right
        parts.append(AnnualPart(left, part.op, right))
    from_quarters = any(p.kind in ("Q", "TTM") for p in periods)
    return AnnualTest(tuple(parts), from_quarters)


# Evaluating a test for one filer and year


@dataclass(frozen=True)
class Value:
    """A term's value for one filer and year (None and why), and the period end it is of."""

    value: float | None
    end: str = ""
    reason: str = ""


def growth_value(
    panel: Panel, measure: str, cik: int, year: int, years: int, compound: bool
) -> Value:
    """Growth of ``measure`` from ``years`` before ``year`` to ``year``, in percent."""
    now = panel.measure(measure, cik, year)
    then = panel.measure(measure, cik, year - years)
    if now.value is None or then.value is None:
        return Value(None, reason=now.reason or then.reason)
    end_now, end_then = now.used[0].row.end, then.used[0].row.end
    if not years_apart(end_now, end_then, years):
        return Value(None, reason="the two periods are not whole years apart")
    if then.value <= 0:
        return Value(None, reason="the base is not positive")
    if scale_break(now.value, then.value):
        return Value(
            None, reason="the two years differ by a factor near a thousand (a scale break)"
        )
    if compound:
        if now.value <= 0:
            return Value(None, reason="the latest value is not positive")
        rate = ((now.value / then.value) ** (1 / years) - 1) * 100
    else:
        rate = (now.value - then.value) / then.value * 100
    return Value(rate, end_now.isoformat())


def _streak(panel: Panel, measure: str, cik: int, year: int, wanted: int) -> Value:
    count = 0
    current = panel.measure(measure, cik, year)
    if current.value is None:
        return Value(None, reason=current.reason)
    end = current.used[0].row.end.isoformat()
    while count < wanted:
        earlier = panel.measure(measure, cik, year - count - 1)
        if earlier.value is None or not years_apart(
            current.used[0].row.end, earlier.used[0].row.end, 1
        ):
            return Value(None, reason="the years ran out before the streak was long enough")
        if current.value <= earlier.value:
            return Value(float(count), end)
        count += 1
        current = earlier
    return Value(float(count), end)


def term_value(panel: Panel, term: AnnualTerm, cik: int, year: int, wanted: int = 0) -> Value:
    """The value of ``term`` for one filer, with ``year`` the year read."""
    at = year - term.offset
    match term.fn:
        case "value":
            found = panel.measure(term.measure, cik, at)
            if found.value is None:
                return Value(None, reason=found.reason)
            return Value(found.value, found.used[0].row.end.isoformat())
        case "yoy":
            return growth_value(panel, term.measure, cik, at, 1, compound=False)
        case "change":
            return growth_value(panel, term.measure, cik, at, term.years, compound=False)
        case "cagr":
            return growth_value(panel, term.measure, cik, at, term.years, compound=True)
        case "streak":
            return _streak(panel, term.measure, cik, at, wanted)
    raise AssertionError(term.fn)  # pragma: no cover


def held(panel: Panel, test: AnnualTest, cik: int, year: int) -> tuple[bool | None, Value]:
    """Whether every part held for one filer and year (None: some part cannot be computed).

    Also returns the first part's left side, the value a case shows.
    """
    shown = Value(None)
    result: bool | None = True
    for index, part in enumerate(test.parts):
        wanted = math.ceil(part.right.value) if isinstance(part.right, Number) else 0
        left = term_value(panel, part.left, cik, year, wanted)
        if index == 0:
            shown = left
        if isinstance(part.right, Number):
            right = Value(part.right.value)
        else:
            right = term_value(panel, part.right, cik, year)
        if left.value is None or right.value is None:
            return None, shown
        if not OPS[part.op](left.value, right.value):
            result = False
    return result, shown


# The base rate


@dataclass
class RefClass:
    """A reference class: a name, its definition, a revenue floor and (optionally) members."""

    name: str
    floor: float
    members: Collection[int] | None = None
    definition: str = ""
    sic: str = ""

    def admits(self, panel: Panel, cik: int, year: int) -> bool:
        """True when the filer is a member and its revenue in ``year`` is at least the floor."""
        if self.members is not None and cik not in self.members:
            return False
        revenue = panel.get("revenue", cik, year)
        return revenue is not None and revenue.value >= self.floor


def value_text(value: float, unit: str) -> str:
    """A test value for reading: a percent with one decimal, an amount, a count, a ratio."""
    if unit == "percent":
        return percent_text(value)
    if unit == "USD":
        return usd_text(value)
    if unit == "ratio":
        return f"{value:.2f}×"
    return f"{value:g}"


@dataclass
class _Tally:
    years: list[YearCount] = field(default_factory=list)
    hits: list[tuple[int, int, Value]] = field(default_factory=list)


def _tally(
    panel: Panel, test: AnnualTest, ref: RefClass, years: Sequence[int], leave_out: int
) -> _Tally:
    tally = _Tally()
    for year in years:
        base = year - test.class_reach
        in_class = computable = count = 0
        for cik in sorted(panel.filers(base)):
            if cik == leave_out or not ref.admits(panel, cik, base):
                continue
            in_class += 1
            outcome, shown = held(panel, test, cik, year)
            if outcome is None:
                continue
            computable += 1
            if outcome:
                count += 1
                tally.hits.append((cik, year, shown))
        tally.years.append(
            YearCount(year=year, in_class=in_class, computable=computable, held=count)
        )
    return tally


def _case(
    panel: Panel, test: AnnualTest, cik: int, year: int, shown: Value, years: Sequence[int]
) -> Case:
    revenue = panel.get("revenue", cik, year)
    following = ""
    if year + 1 in years:
        outcome, _ = held(panel, test, cik, year + 1)
        following = "" if outcome is None else ("held" if outcome else "did not hold")
    assert shown.value is not None
    return Case(
        name=panel.names.get(cik, str(cik)),
        cik=cik,
        year=year,
        period_end=shown.end,
        value=shown.value,
        display=value_text(shown.value, test.unit),
        revenue=revenue.value if revenue else None,
        revenue_display=usd_text(revenue.value) if revenue else "",
        next_year=following,
    )


def base_rate(
    panel: Panel,
    test: AnnualTest,
    ref: RefClass,
    years: Sequence[int],
    *,
    company_cik: int,
    claim_test: str,
    as_of: str,
    result_id: str,
) -> BaseRate:
    """How often ``test`` held among ``ref`` in each of ``years``, and how often it persisted.

    ``years`` are the years t the test is read for; each needs the years it reaches
    back to in ``panel``. Pure: the frames were read by the caller.
    """
    usable = [y for y in years if y - test.class_reach in panel.years and y in panel.years]
    tally = _tally(panel, test, ref, usable, company_cik)
    held_total = sum(y.held for y in tally.years)
    computable = sum(y.computable for y in tally.years)
    persisted = base = 0
    for cik, year, _ in tally.hits:
        if year + 1 not in usable:
            continue
        outcome, _ = held(panel, test, cik, year + 1)
        if outcome is None:
            continue
        base += 1
        persisted += int(outcome)
    own_hits = [
        (company_cik, year, shown)
        for year in usable
        for outcome, shown in [held(panel, test, company_cik, year)]
        if outcome
    ]
    others = tally.hits
    target = _own_value(panel, test, company_cik, usable)
    cases = [
        _case(panel, test, c, y, v, usable)
        for c, y, v in sorted(others, key=lambda hit: _distance(panel, hit, target, company_cik))
    ][:MAX_CASES]
    own = [_case(panel, test, c, y, v, usable) for c, y, v in own_hits]
    span = f"{usable[0]} to {usable[-1]}" if usable else "no year"
    annual = test.text()
    assumptions = [
        f"Class: {ref.definition}",
        "Each year t is a calendar-year frame: SEC places in it, for each filer, the fiscal "
        "year that best fits the calendar year; t-1 is the frame a year earlier, and the two "
        "periods must end a whole number of years apart.",
        "Frames carry no filing date: a value restated later is the restated value.",
        "The company itself is not counted: the rate is of the other filers of the class, and "
        "the years in which the test held for the company are listed apart.",
        "A filer in the class in the base year with no value in year t (it was bought, went "
        "under, stopped filing, or changed its tags) is in the class but not computable: the "
        "rate is of the filers that can still be read.",
        "A parent and a subsidiary that both file are two filers; a filer that reports in "
        "another currency is in no USD frame.",
    ]
    if test.from_quarters:
        assumptions.append(
            "The claim names the latest quarter or four quarters; frames are read on fiscal "
            "years, so the test is read on years ("
            f"{claim_test} read as {annual})."
        )
    if test.class_reach > test.reach:
        assumptions.append(LEVEL_CLASS_NOTE)
    assumptions.append("The SIC code is the filer's code today, not the code it had in year t.")
    if not computable:
        return BaseRate(
            id=result_id,
            kind="base_rate",
            label=f"Base rate of {annual} among {ref.name}",
            outcome="cannot_compute",
            reason="No company-year of the class could be computed for the years read.",
            unit="percent",
            data_origin="sec_frames",
            as_of=as_of,
            test=claim_test,
            annual_test=annual,
            class_name=ref.name,
            class_definition=ref.definition,
            years=tally.years,
            assumptions=assumptions,
            resolution=_resolutions(panel, test),
        )
    share = held_total / computable * 100
    persist_text = (
        f"of the {base} that held and could be read a year later, {persisted} still held"
        if base
        else "none that held could be read a year later"
    )
    reading = (
        f"Among {ref.name} (the company left out), {annual} held in {held_total} of "
        f"{computable} company-years from {span}; {persist_text}."
    )
    return BaseRate(
        id=result_id,
        kind="base_rate",
        label=f"Base rate of {annual} among {ref.name}",
        value=share,
        unit="percent",
        display=f"{held_total} of {computable} ({percent_text(share)})",
        formula=f"held ÷ computable = {held_total} ÷ {computable}",
        inputs=_inputs(panel, test, usable),
        assumptions=assumptions,
        reading=reading,
        data_origin="sec_frames",
        as_of=as_of,
        test=claim_test,
        annual_test=annual,
        class_name=ref.name,
        class_definition=ref.definition,
        years=tally.years,
        held=held_total,
        computable=computable,
        persisted=persisted,
        persist_base=base,
        cases=cases,
        own=own,
        resolution=_resolutions(panel, test),
    )


def _own_value(panel: Panel, test: AnnualTest, cik: int, years: Sequence[int]) -> float | None:
    for year in reversed(years):
        _, shown = held(panel, test, cik, year)
        if shown.value is not None:
            return shown.value
    return None


def _distance(
    panel: Panel, hit: tuple[int, int, Value], target: float | None, company_cik: int
) -> tuple[float, int, int]:
    cik, year, shown = hit
    assert shown.value is not None
    if target is not None:
        return (abs(shown.value - target), -year, cik)
    own = max(
        (v.value for y in panel.years if (v := panel.get("revenue", company_cik, y))),
        default=None,
    )
    revenue = panel.get("revenue", cik, year)
    if own is None or own <= 0 or revenue is None or revenue.value <= 0:
        return (math.inf, -year, cik)
    return (abs(math.log(revenue.value / own)), -year, cik)


def _inputs(panel: Panel, test: AnnualTest, years: Sequence[int]) -> list[ResultInput]:
    """One input per concept group read: its concepts and the frames' years."""
    measures = {p.left.measure for p in test.parts} | {
        p.right.measure for p in test.parts if isinstance(p.right, AnnualTerm)
    }
    groups = sorted({g for m in measures for g in MEASURES[m].groups})
    if not years:
        return []
    span = f"CY{min(years) - test.class_reach} to CY{max(years)}"
    return [
        ResultInput(
            label=f"{GROUPS[group].label}: every filer's row, by the first concept that has one",
            value=None,
            display="",
            source=frame_source("|".join(GROUPS[group].concepts), span),
            date=span,
        )
        for group in groups
    ]


def _resolutions(panel: Panel, test: AnnualTest) -> list[ConceptResolution]:
    measures = {p.left.measure for p in test.parts}
    groups = {g for m in measures for g in MEASURES[m].groups}
    return [
        ConceptResolution(
            group=group,
            year=year,
            filers=filers,
            several=several,
            differing=differing,
            scale_breaks=breaks,
            rule=resolution_rule(group),
        )
        for group, year, filers, several, differing, breaks in panel.resolution
        if group in groups
    ]


# Ten-year growth for companies of a size


def percentile(values: Sequence[float], p: float) -> float:
    """The ``p``-th percentile by linear interpolation between the closest ranks.

    With the values sorted, the position is ``(n − 1) × p ÷ 100`` and the result lies
    that far between the values on either side (numpy's default, method "linear").
    """
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    position = (len(ordered) - 1) * p / 100
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def growth_distribution(
    panel: Panel,
    low: float,
    high: float,
    *,
    span: int = 10,
    at_least: float | None = None,
    exclude: int | None = None,
) -> Distribution:
    """The compound annual revenue growth over ``span`` years of filers of a size.

    A company-span starts in a year t0 in which the filer's revenue was between ``low``
    and ``high``, and ends in t0 + ``span``. One filer can start several spans, so the
    spans overlap and are not independent. A filer in the class at t0 with no revenue
    row at t0 + span (it stopped filing, was bought, or tags revenue otherwise) is
    ``dropped``: the distribution is of survivors.
    """
    rates: list[float] = []
    dropped = 0
    starts = [y for y in panel.years if y + span in panel.years]
    for start in starts:
        for cik, value in panel.group("revenue", start).items():
            if cik == exclude or not low <= value.value <= high:
                continue
            found = growth_value(panel, "revenue", cik, start + span, span, compound=True)
            if found.value is None:
                dropped += 1
                continue
            rates.append(found.value)
    if starts:
        window = f"starts {starts[0]} to {starts[-1]}"
    else:
        window = "no start year with an end year in the frames read"
    definition = (
        f"Compound annual revenue growth over {span} years of filers whose revenue in the "
        f"start year was {usd_text(low)} to {usd_text(high)} ({window}); survivors only."
    )
    band = f"{usd_text(low)} to {usd_text(high)}"
    if not rates:
        return Distribution(dropped=dropped, definition=definition, band=band, window=window)
    points = {f"p{p}": percentile(rates, p) for p in PERCENTILES}
    return Distribution(
        n=len(rates),
        percentiles=points,
        displays={key: percent_text(value) for key, value in points.items()},
        at_least=sum(rate >= at_least for rate in rates) if at_least is not None else 0,
        at_least_of=at_least,
        dropped=dropped,
        definition=definition,
        band=band,
        window=window,
    )
