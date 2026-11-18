"""Analytics: what an analyst would work out about a claim from the company's dated facts.

Pure: no I/O, no model. Everything is computed from one :class:`~app.core.facts.FactBook`
(as of the run's date when it has one, so nothing filed later is seen) through the same
:class:`~app.core.claim_eval.Measures` the computed tests read, so an analytic and a test
never disagree about a value, and from the tagged breakdowns of the filings the run read.

Every analytic answers a question about a claim, and says which (``question``). None is
computed for the thesis at large: a number no claim asks for is not in the analysis. An
analytic is computed on the claim's own basis: a claim about a fiscal year gets fiscal-year
analytics (and what has happened since), any other claim the newest quarters.

- about a measure a claim bears on, quarterly (``an:<measure>:<what>``): its change on a
  year earlier, whether its growth is speeding up or slowing, and where it stands against
  the last eight quarters;
- about a measure, for a fiscal-year claim (``an:<measure>:<fy>:<what>``): its path over the
  last fiscal years, and the newest quarter since;
- about a computed test (``an:<claim>:<what>``): its room, the room in typical moves, the
  level a growth test needed (or could have given up), how often it held before, and for a
  test of one measure against another, whether the gap is closing;
- bridges (``an:bridge:<what>``): net income to free cash flow, with the balance-sheet
  changes over the same period; the operating-margin change split into its parts; which
  parts drove revenue growth;
- a part a claim names (``an:part:<name>:<what>``): its growth against the company's, its
  share, and whether its growth is speeding up or slowing;
- earnings quality (``an:eq:<what>``): cash conversion, receivable and inventory days,
  stock compensation and capital expenditure against revenue, deferred revenue, and return
  on equity split the DuPont way.

An analytic the facts cannot give is still returned for the claim that asked, with
``available`` False and a note saying why. :class:`FactsProvider` is the first
:class:`AnalyticsProvider`; another provider returns analytics of the same shape with its
own ``provider`` and ``data_origin``.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Protocol

from app.core import analysis_policy as rules
from app.core.analysis_models import Analytic, AnalyticInput, AnalyticUnit
from app.core.breakdown_models import Breakdown, BreakdownReport, BreakdownRow, BreakdownValue
from app.core.claim_eval import Measures, Slot
from app.core.claim_test_models import ComputedTest, HistoryPoint
from app.core.claimtest import METRICS, ClaimTest, Number
from app.core.facts import FactBook, PeriodValue
from app.core.metrics import MINUS, eps_text, percent_text, usd_text
from app.core.periods import FiscalCalendar

PROVIDER = "facts"
ORIGIN = "sec_xbrl_facts"
BREAKDOWN_ORIGIN = "sec_tagged_breakdowns"
NO_FACTS = "The run could not read the company's XBRL facts{why}."
PART_BREAKDOWNS = {
    "revenue_by_segment": "segment",
    "revenue_by_product": "segment",
    "revenue_by_geography": "geography",
}
YEAR_DAYS = (350, 380)
QUARTER_DAYS = (80, 100)
FISCAL_YEARS_SHOWN = 4
READINGS_SHOWN = 4
PARTS_SHOWN = 5
SPAN_SLACK_DAYS = 10

# The question each analytic answers, in the words the record shows.
Q_YOY = "Which way is {what} moving on a year earlier?"
Q_ACCELERATION = "Is {what} growth speeding up or slowing?"
Q_TREND = "Where does {what} stand against the last two years?"
Q_PATH = "What has {what} done over the last fiscal years?"
Q_SINCE = "What has happened to {what} since that fiscal year ended?"
Q_HEADROOM = "How much room does the test have, against how far the figure usually moves?"
Q_NEEDED = "How far short did it fall?"
Q_CUSHION = "How much could it have given up and still held?"
Q_RECORD = "How often has this been true before?"
Q_SIDES = "Is the gap between the two sides closing or widening?"
Q_CASH_WALK = "Where did the cash go between net income and free cash flow?"
Q_MARGIN_SPLIT = "What moved the operating margin?"
Q_DRIVERS = "Which parts of the business drove the growth?"
Q_PART = "Is {what} growing faster or slower than the company?"
Q_PART_PACE = "Is {what} growth speeding up or slowing?"
Q_CONVERSION = "Is net income turning into cash?"
Q_DSO = "Is revenue being collected, or building up in receivables?"
Q_DIO = "Is inventory building ahead of sales?"
Q_SBC = "How much of the cost base is paid in stock, which cash flow does not show?"
Q_CAPEX = "How much of revenue goes back into capital expenditure?"
Q_DEFERRED = "Is revenue billed ahead of delivery growing or shrinking?"
Q_ROE = "What is the return on equity made of?"


# The shape


@dataclass(frozen=True)
class AnalyticsRequest:
    """What a provider is asked for: the run's facts and what its claims bear on.

    ``measures`` maps each claim id to the keys it bears on, in order: catalogue keys, and
    parts as 'revenue(segment "Data Center")'. ``tests`` maps a claim id to its compiled
    test and the computed result. ``reports`` are the tagged breakdowns of the newest
    filings the run read. ``error`` says why there are no facts when ``book`` is None.
    """

    book: FactBook | None
    calendar: FiscalCalendar | None
    measures: dict[str, list[str]] = field(default_factory=dict)
    tests: dict[str, tuple[ClaimTest, ComputedTest]] = field(default_factory=dict)
    reports: Sequence[BreakdownReport] = ()
    error: str = ""


class AnalyticsProvider(Protocol):
    """Something that computes analytics for a run (``name`` is recorded as ``provider``)."""

    name: str

    def provide(self, request: AnalyticsRequest) -> list[Analytic]:
        """Every analytic it can compute for ``request``; an unavailable one says why."""
        ...


@dataclass(frozen=True)
class Basis:
    """The periods a claim is about: the newest quarters, or one fiscal year (``slot``)."""

    kind: Literal["quarter", "annual"] = "quarter"
    slot: Slot | None = None


def claim_basis(test: ClaimTest | None, measures: Measures) -> Basis:
    """Fiscal-year when every period the claim's test names is a fiscal year; else quarterly."""
    if test is None or test.from_filing:
        return Basis()
    if not test.terms or any(term.period.kind != "FY" for term in test.terms):
        return Basis()
    bound = measures.bind(test.left.period, "revenue")
    if isinstance(bound, Slot) and bound.kind == "annual":
        return Basis("annual", bound)
    return Basis()


# Display


def display(value: float | None, unit: AnalyticUnit, *, signed: bool = False) -> str:
    """An analytic's value as the record shows it, in its unit."""
    if value is None:
        return "n/a"
    match unit:
        case "USD":
            text = usd_text(value)
            return f"+{text}" if signed and value > 0 else text
        case "USD_per_share":
            return eps_text(value)
        case "percent" | "probability":
            return percent_text(value, signed=signed)
        case "points":
            rounded = round(value, 1) or 0.0
            return f"{rounded:+.1f} percentage points"
        case "multiple":
            return f"{value:.2f}x"
        case "days":
            return f"{value:.1f} days"
        case "shares":
            return f"{value / 1e6:,.0f}M shares"
        case _:
            return f"{value:g}"


def _points(value: float) -> str:
    """A size in percentage points, unsigned: "2.6 percentage points"."""
    return f"{abs(round(value, 1)):.1f} percentage points"


def _unit_of(key: str) -> AnalyticUnit:
    kind = METRICS[key][1]
    if kind == "ratio":
        return "percent"
    if kind == "per_share":
        return "USD_per_share"
    if kind == "shares":
        return "shares"
    return "USD"


def _label(key: str) -> str:
    return METRICS[key][0]


def _lower(text: str) -> str:
    return text[:1].lower() + text[1:] if text[1:2].islower() or len(text) < 2 else text


def _is_ratio(key: str) -> bool:
    return METRICS[key][1] == "ratio"


def _fact_inputs(used: Sequence[PeriodValue]) -> list[AnalyticInput]:
    """The facts behind values used, one input each, without repeats."""
    seen: set[tuple[str, str]] = set()
    out: list[AnalyticInput] = []
    for value in used:
        ref = value.refs[0]
        key = (ref.concept, f"{ref.start}..{ref.end}")
        if key in seen:
            continue
        seen.add(key)
        unit: AnalyticUnit = "USD" if ref.unit.startswith("USD") else "count"
        out.append(
            AnalyticInput(
                ref_kind="fact",
                id=f"{ref.concept}:{ref.start or ''}..{ref.end}",
                label=ref.concept,
                value=ref.value,
                display=display(ref.value, unit),
                accession=ref.accession,
                form=ref.form,
                filed=ref.filed,
            )
        )
    return out


def _fields(
    analytic_id: str,
    kind: str,
    label: str,
    question: str,
    claim_ids: Sequence[str],
    *,
    measure: str = "",
    period: str = "",
    origin: str = ORIGIN,
) -> dict[str, object]:
    return {
        "id": analytic_id,
        "provider": PROVIDER,
        "data_origin": origin,
        "kind": kind,
        "label": label,
        "question": question,
        "claim_ids": list(claim_ids),
        "measure": measure,
        "period": period,
    }


def _missing(fields: dict[str, object], unit: AnalyticUnit, note: str) -> Analytic:
    return Analytic(**fields, unit=unit, available=False, note=note)  # type: ignore[arg-type]


# Reading a measure period by period


@dataclass(frozen=True)
class Point:
    """One measure over one bound period (or at one balance date)."""

    slot: Slot
    value: float
    used: tuple[PeriodValue, ...]


def _point_input(key: str, point: Point) -> AnalyticInput:
    """One period of a measure as an input, with the newest filing among its facts."""
    refs = [value.refs[0] for value in point.used]
    newest = max(refs, key=lambda ref: ref.filed) if refs else None
    return AnalyticInput(
        ref_kind="fact",
        id=f"{key}[{point.slot.label}]",
        label=f"{_label(key)}, {point.slot.label}",
        value=point.value,
        display=display(point.value, _unit_of(key)),
        accession=newest.accession if newest else "",
        form=newest.form if newest else "",
        filed=newest.filed if newest else "",
    )


def latest_slot(measures: Measures, key: str) -> Slot | None:
    """The newest quarter (or balance date) of ``key`` the facts hold."""
    if METRICS[key][1] == "instant":
        dates = measures.instants(key)
        return measures.slot("instant", max(dates)) if dates else None
    series = measures.series("quarter", key)
    return measures.slot("quarter", max(series)) if series else None


def _walk_back(measures: Measures, key: str, slot: Slot | None, count: int) -> tuple[list, str]:
    points: list[Point] = []
    why = ""
    while slot is not None and len(points) < count:
        outcome = measures.outcome(key, slot)
        if outcome.value is None:
            why = outcome.note
            break
        points.append(Point(slot, outcome.value, outcome.used))
        slot = measures.period_before(slot, key)
    return points, why


def quarterly(measures: Measures, key: str, count: int) -> tuple[list[Point], str]:
    """Up to ``count`` consecutive quarters of ``key``, newest first, and why it stopped.

    The walk stops at the first quarter with no value (a gap is never bridged), so every
    pair of neighbours is one quarter apart.
    """
    slot = latest_slot(measures, key)
    if slot is None:
        return [], f"The facts hold no quarter of {_lower(_label(key))}."
    return _walk_back(measures, key, slot, count)


def _change(now: float, before: float, ratio: bool) -> float | None:
    """Points for a ratio; percent growth on a positive base for an amount."""
    if ratio:
        return now - before
    if before <= 0:
        return None
    return (now - before) / before * 100


def _change_text(value: float, ratio: bool) -> str:
    return display(value, "points" if ratio else "percent", signed=True)


def _verb(value: float, ratio: bool) -> str:
    if value > 0:
        return "rose" if ratio else "grew"
    return "fell" if ratio else "shrank"


def _point_at(measures: Measures, key: str, slot: Slot | None) -> Point | None:
    if slot is None:
        return None
    outcome = measures.outcome(key, slot)
    return None if outcome.value is None else Point(slot, outcome.value, outcome.used)


def _growth_at(measures: Measures, key: str, point: Point) -> tuple[float, Point] | None:
    """``point``'s change on the same period a year earlier, and that earlier point."""
    earlier = _point_at(measures, key, measures.year_before(point.slot, key))
    if earlier is None:
        return None
    value = _change(point.value, earlier.value, _is_ratio(key))
    return None if value is None else (value, earlier)


# About a measure, quarterly


def quarter_analytics(
    measures: Measures, key: str, claim_ids: Sequence[str] = ()
) -> list[Analytic]:
    """The newest quarter of ``key`` on a year earlier, whether its growth is speeding up or
    slowing (an amount only), and where it stands against the last eight quarters."""
    what = _lower(_label(key))
    points, why = quarterly(measures, key, rules.LONG_WINDOW + 1)
    yoy = _fields(
        f"an:{key}:yoy",
        "yoy",
        f"{_label(key)}, change on a year earlier",
        Q_YOY.format(what=what),
        claim_ids,
        measure=key,
    )
    unit: AnalyticUnit = "points" if _is_ratio(key) else "percent"
    if not points:
        return [_missing(yoy, unit, why or f"The facts hold no quarter of {what}.")]
    out = [_year_change(measures, key, points[0], yoy)]
    if not _is_ratio(key) and METRICS[key][1] != "instant":
        out.append(_acceleration(measures, key, points, claim_ids))
    out.append(_trend(key, points, claim_ids))
    return out


def _year_change(
    measures: Measures, key: str, latest: Point, fields: dict[str, object]
) -> Analytic:
    ratio = _is_ratio(key)
    unit: AnalyticUnit = "points" if ratio else "percent"
    fields = {**fields, "period": latest.slot.label}
    found = _growth_at(measures, key, latest)
    if found is None:
        return _missing(
            fields,
            unit,
            f"No comparable quarter a year before {latest.slot.label} is in the facts.",
        )
    value, before = found
    now_text = display(latest.value, _unit_of(key))
    before_text = display(before.value, _unit_of(key))
    formula = (
        f"{now_text} {MINUS} {before_text}"
        if ratio
        else f"({now_text} {MINUS} {before_text}) ÷ {before_text}"
    )
    size = _points(value) if ratio else percent_text(abs(value))
    label = _label(key)
    if round(value, 1):
        reading = (
            f"{label} {_verb(value, ratio)} {size} on a year earlier: {before_text} in "
            f"{before.slot.label}, {now_text} in {latest.slot.label}."
        )
    else:
        reading = (
            f"{label} was about unchanged on a year earlier: {before_text} in "
            f"{before.slot.label}, {now_text} in {latest.slot.label}."
        )
    return Analytic(
        **fields,  # type: ignore[arg-type]
        value=value,
        unit=unit,
        display=_change_text(value, ratio),
        formula=formula,
        inputs=[_point_input(key, latest), _point_input(key, before)],
        reading=reading,
    )


def _acceleration(
    measures: Measures, key: str, points: Sequence[Point], claim_ids: Sequence[str]
) -> Analytic:
    """Growth on a year earlier now, a quarter before and four quarters before."""
    label = _label(key)
    fields = _fields(
        f"an:{key}:acceleration",
        "acceleration",
        f"{label}, growth on a year earlier now against the quarter before",
        Q_ACCELERATION.format(what=_lower(label)),
        claim_ids,
        measure=key,
        period=points[0].slot.label,
    )
    found = [_growth_at(measures, key, points[i]) if i < len(points) else None for i in (0, 1, 4)]
    now, previous, year_ago = found
    if now is None or previous is None:
        return _missing(
            fields,
            "points",
            "Growth on a year earlier is needed for the latest two quarters; the facts do "
            "not give both.",
        )
    value = now[0] - previous[0]
    g = [percent_text(item[0], signed=True) for item in (now, previous)]
    inputs = [
        _point_input(key, points[0]),
        _point_input(key, now[1]),
        _point_input(key, points[1]),
        _point_input(key, previous[1]),
    ]
    if round(value, 1) > 0:
        pace = f"speeding up, by {_points(value)}"
    elif round(value, 1) < 0:
        pace = f"slowing, by {_points(value)}"
    else:
        pace = "steady"
    reading = (
        f"{label} growth on a year earlier was {g[0]} in {points[0].slot.label} and {g[1]} in "
        f"{points[1].slot.label}: {pace}"
    )
    if year_ago is not None:
        reading += (
            f". Four quarters before, in {points[4].slot.label}, it was "
            f"{percent_text(year_ago[0], signed=True)}"
        )
        inputs += [_point_input(key, points[4]), _point_input(key, year_ago[1])]
    return Analytic(
        **fields,  # type: ignore[arg-type]
        value=value,
        unit="points",
        display=display(value, "points"),
        formula=f"{g[0]} {MINUS} {g[1]}",
        inputs=list({i.id: i for i in inputs}.values()),
        reading=reading + ".",
    )


def compound_rate(first: float, last: float, steps: int) -> float | None:
    """The compound rate per step, in percent, from ``first`` to ``last``; None unless both
    are positive."""
    if first <= 0 or last <= 0 or steps <= 0:
        return None
    return ((last / first) ** (1 / steps) - 1) * 100


def _trend(key: str, points: Sequence[Point], claim_ids: Sequence[str]) -> Analytic:
    """The change over the last eight quarters and where the newest sits between their low
    and high: points for a ratio, the compound quarterly rate for an amount."""
    ratio = _is_ratio(key)
    label = _label(key)
    window = rules.LONG_WINDOW
    unit: AnalyticUnit = "points" if ratio else "percent"
    name = (
        f"change over the last {window} quarters"
        if ratio
        else f"compound quarterly growth over the last {window} quarters"
    )
    fields = _fields(
        f"an:{key}:trend8",
        "trend8",
        f"{label}, {name}",
        Q_TREND.format(what=_lower(label)),
        claim_ids,
        measure=key,
        period=points[0].slot.label,
    )
    if len(points) <= window:
        return _missing(
            fields,
            unit,
            f"{window + 1} consecutive quarters are needed; the facts hold {len(points)}.",
        )
    first, last = points[window], points[0]
    shown = (display(first.value, _unit_of(key)), display(last.value, _unit_of(key)))
    span = list(points[: window + 1])
    low, high = min(span, key=lambda p: p.value), max(span, key=lambda p: p.value)
    low_text, high_text = display(low.value, _unit_of(key)), display(high.value, _unit_of(key))
    rising = all(a.value > b.value for a, b in zip(span, span[1:], strict=False))
    if rising:
        where = f"it rose in each of the {window} quarters"
    elif last is high:
        where = "the newest quarter is the highest of them"
    elif last is low:
        where = "the newest quarter is the lowest of them"
    else:
        where = f"the highest was {high_text} ({high.slot.label})"
    if not rising and last is not low:
        where += f"; the lowest was {low_text} ({low.slot.label})"
    if ratio:
        value: float | None = last.value - first.value
        formula = f"{shown[1]} {MINUS} {shown[0]}"
        moved = (
            f"is {_points(last.value - first.value)} "
            f"{'above' if last.value >= first.value else 'below'} where it was"
            if round(last.value - first.value, 1)
            else "is where it was"
        )
        reading = (
            f"{label} {moved} {window} quarters ago ({shown[0]} in {first.slot.label}, "
            f"{shown[1]} in {last.slot.label}); {where}."
        )
    else:
        value = compound_rate(first.value, last.value, window)
        formula = f"({shown[1]} ÷ {shown[0]})^(1/{window}) {MINUS} 1"
        if value is None:
            return _missing(fields, unit, "A compound rate needs both ends positive.")
        reading = (
            f"{label} went from {shown[0]} in {first.slot.label} to {shown[1]} in "
            f"{last.slot.label}, a compound {percent_text(value, signed=True)} a quarter; {where}."
        )
    return Analytic(
        **fields,  # type: ignore[arg-type]
        value=value,
        unit=unit,
        display=_change_text(value, ratio),
        formula=formula,
        inputs=list(
            {i.id: i for i in (_point_input(key, p) for p in (first, last, low, high))}.values()
        ),
        reading=reading,
    )


# About a measure, for a fiscal-year claim


def fiscal_year_analytics(
    measures: Measures, key: str, slot: Slot, claim_ids: Sequence[str] = ()
) -> list[Analytic]:
    """``key`` over the fiscal years up to ``slot``, and the newest quarter since."""
    return [
        item
        for item in (
            _fiscal_path(measures, key, slot, claim_ids),
            _since(measures, key, slot, claim_ids),
        )
        if item is not None
    ]


def _fiscal_path(
    measures: Measures, key: str, slot: Slot, claim_ids: Sequence[str]
) -> Analytic | None:
    ratio = _is_ratio(key)
    label = _label(key)
    unit: AnalyticUnit = "points" if ratio else "percent"
    fields = _fields(
        f"an:{key}:{slot.label.lower()}:path",
        "fiscal_path",
        f"{label} by fiscal year, to {slot.label}",
        Q_PATH.format(what=_lower(label)),
        claim_ids,
        measure=key,
        period=slot.label,
    )
    points, why = _walk_back(measures, key, slot, FISCAL_YEARS_SHOWN)
    if len(points) < 2:
        note = why or f"The facts hold no fiscal year of {_lower(label)} before {slot.label}."
        return _missing(fields, unit, note)
    points.reverse()  # oldest first
    changes = [
        _change(newer.value, older.value, ratio)
        for older, newer in zip(points, points[1:], strict=False)
    ]
    pieces = [f"{display(points[0].value, _unit_of(key))} in {points[0].slot.label}"]
    for point, change in zip(points[1:], changes, strict=True):
        tail = f" ({_change_text(change, ratio)})" if change is not None else ""
        pieces.append(f"{display(point.value, _unit_of(key))} in {point.slot.label}{tail}")
    latest = changes[-1]
    if latest is None:
        return _missing(
            fields, unit, f"Growth is not meaningful: {points[-2].slot.label} is not positive."
        )
    reading = f"{label} by fiscal year: {', '.join(pieces)}."
    known = [c for c in changes if c is not None]
    if not ratio and len(known) >= 2 and len(known) == len(changes):
        before = known[-2]
        if round(latest - before, 1) < 0:
            reading += (
                f" Growth slowed in {points[-1].slot.label}, by {_points(latest - before)} on "
                f"the year before."
            )
        elif round(latest - before, 1) > 0:
            reading += (
                f" Growth sped up in {points[-1].slot.label}, by {_points(latest - before)} on "
                f"the year before."
            )
    now, base = points[-1], points[-2]
    shown = (display(now.value, _unit_of(key)), display(base.value, _unit_of(key)))
    return Analytic(
        **fields,  # type: ignore[arg-type]
        value=latest,
        unit=unit,
        display=_change_text(latest, ratio),
        formula=(
            f"{shown[0]} {MINUS} {shown[1]}"
            if ratio
            else f"({shown[0]} {MINUS} {shown[1]}) ÷ {shown[1]}"
        ),
        inputs=[_point_input(key, point) for point in points],
        reading=reading,
    )


def _since(measures: Measures, key: str, slot: Slot, claim_ids: Sequence[str]) -> Analytic | None:
    """The newest quarter after the fiscal year, on a year earlier; None when there is none."""
    latest = _point_at(measures, key, latest_slot(measures, key))
    if latest is None or latest.slot.end <= slot.end or latest.slot.kind != "quarter":
        return None
    ratio = _is_ratio(key)
    label = _label(key)
    fields = _fields(
        f"an:{key}:{slot.label.lower()}:since",
        "since",
        f"{label} in the newest quarter since {slot.label}, on a year earlier",
        Q_SINCE.format(what=_lower(label)),
        claim_ids,
        measure=key,
    )
    analytic = _year_change(measures, key, latest, fields)
    if not analytic.available:
        return analytic
    whole = _point_at(measures, key, slot)
    tail = ""
    if whole is not None:
        found = _growth_at(measures, key, whole)
        if found is not None:
            tail = f" {slot.label} as a whole: {_change_text(found[0], ratio)}."
    return analytic.model_copy(
        update={"reading": f"Since {slot.label} ended: {_lower(analytic.reading)}{tail}"}
    )


# About a computed test


def _single_tests(computed: ComputedTest) -> list[ComputedTest]:
    return list(computed.parts) if computed.parts else [computed]


def _room(test: ComputedTest) -> float | None:
    """How far the test is from flipping: positive when it holds, in the sides' unit."""
    if test.left is None or test.right is None:
        return None
    left, right = test.left.value, test.right.value
    if left is None or right is None:
        return None
    return left - right if test.comparison in (">", ">=") else right - left


def _test_unit(test: ComputedTest) -> AnalyticUnit:
    unit = test.left.unit if test.left is not None else "percent"
    if unit == "percent":
        return "points"
    if unit in ("USD", "USD_per_share", "shares"):
        return unit
    return "count"


def _side_display(value: float, test: ComputedTest) -> str:
    unit = test.left.unit if test.left is not None else "percent"
    if unit == "percent":
        return percent_text(value)
    if unit == "USD":
        return usd_text(value)
    if unit == "USD_per_share":
        return eps_text(value)
    return f"{value:g}"


def readings(history: Sequence[HistoryPoint]) -> list[HistoryPoint]:
    """The history's distinct readings, oldest first: the points that could be computed, a
    run of filing dates that gave the same two sides counted once (a 10-Q leaves a
    fiscal-year test where the 10-K put it)."""
    out: list[HistoryPoint] = []
    for point in history:
        if point.outcome == "cannot_compute":
            continue
        if out and (out[-1].left, out[-1].right) == (point.left, point.right):
            continue
        out.append(point)
    return out


def history_record(history: Sequence[HistoryPoint]) -> tuple[int, int, int, str]:
    """(held, readings, longest run held, filing date of the last change of outcome) over the
    history's distinct readings."""
    distinct = readings(history)
    held = sum(1 for p in distinct if p.outcome == "holds")
    longest = run = 0
    last_flip = ""
    for before, point in zip([None, *distinct], distinct, strict=False):
        run = run + 1 if point.outcome == "holds" else 0
        longest = max(longest, run)
        if before is not None and before.outcome != point.outcome:
            last_flip = point.filed
    return held, len(distinct), longest, last_flip


def computed_test_analytics(
    claim_id: str, test: ClaimTest, computed: ComputedTest
) -> list[Analytic]:
    """What a computed test's outcome leaves unsaid: its room against how far its left side
    usually moves (and its tightest period, for a test held in several), what a growth test
    needed or could have given up, whether a gap between two measures is closing, and how
    often the test held before. The outcome and its margin are the test's own and are not
    repeated as an analytic."""
    singles = _single_tests(computed)
    known = [(part, room) for part in singles if (room := _room(part)) is not None]
    measure = test.left.subject if not test.left.axis and test.left.subject in METRICS else ""

    def fields(kind: str, label: str, question: str) -> dict[str, object]:
        return _fields(
            f"an:{claim_id}:{kind}",
            kind,
            label,
            question,
            [claim_id],
            measure=measure,
            period=computed.bound,
        )

    test_input = AnalyticInput(
        ref_kind="computed_test",
        id=f"test:{claim_id}",
        label=computed.canonical,
        display=computed.outcome_label,
    )
    if not known:
        return []
    part, room = min(known, key=lambda item: item[1])
    out: list[Analytic] = []
    headroom = _headroom(
        fields("headroom", "Room of the test, against a typical move", Q_HEADROOM),
        room,
        part,
        computed,
        test_input,
    )
    if headroom is not None:
        out.append(headroom)
    level = _growth_level(fields, test, part, test_input)
    if level is not None:
        out.append(level)
    sides = _sides(
        fields("sides", "Left side as a share of the right, reading by reading", Q_SIDES),
        test,
        computed,
        test_input,
    )
    if sides is not None:
        out.append(sides)
    if sides is None or len(readings(computed.history)) > READINGS_SHOWN:
        record = _record(
            fields("history", "How often the test held before", Q_RECORD),
            test,
            computed,
            test_input,
        )
        if record is not None:
            out.append(record)
    return out


def typical_move(history: Sequence[HistoryPoint]) -> tuple[float, int] | None:
    """The median move of a test's left side between its history's distinct readings, either
    way, and how many moves it is the median of; None with fewer than
    :data:`~app.core.analysis_policy.SHORT_WINDOW` moves, or when it never moved."""
    values = [p.left for p in readings(history) if p.left is not None]
    moves = [abs(b - a) for a, b in zip(values, values[1:], strict=False)]
    if len(moves) < rules.SHORT_WINDOW:
        return None
    typical = statistics.median(moves)
    return (typical, len(moves)) if typical > 0 else None


def _headroom(
    base: dict[str, object],
    room: float,
    part: ComputedTest,
    computed: ComputedTest,
    test_input: AnalyticInput,
) -> Analytic | None:
    """The room of the test (of its tightest period when it is held in several), and how many
    typical moves of its left side that is. None when it would only repeat the test's own
    margin: a single test with too short a history to say what a typical move is."""
    assert part.left is not None and part.right is not None
    several = len(_single_tests(computed)) > 1
    typical = typical_move(computed.history)
    if typical is None and not several:
        return None
    unit = _test_unit(part)
    text = display(room, unit, signed=True) if unit != "count" else f"{room:+g}"
    size = text.lstrip("+-")
    where = f" in its tightest period, {part.bound}," if several and part.bound else ""
    if room > 0:
        reading = (
            f"The test holds{where} with {size} to spare: {part.left.display} against "
            f"{part.right.display}."
        )
    elif room < 0:
        reading = (
            f"The test fails{where} by {size}: {part.left.display} against {part.right.display}."
        )
    else:
        reading = f"The test sits exactly on its line{where}: {part.left.display}."
    formula = (
        f"{part.left.display} {MINUS} {part.right.display}"
        if part.comparison in (">", ">=")
        else f"{part.right.display} {MINUS} {part.left.display}"
    )
    if typical is not None:
        move, count = typical
        multiple = abs(room) / move
        move_text = _points(move) if unit == "points" else _side_display(move, part)
        if multiple < 1:
            way = "against it" if room >= 0 else "in its favour"
            verdict = (
                f"so the room is less than one typical move ({multiple:.2f}x): an ordinary "
                f"change {way} would flip the outcome"
            )
        else:
            verdict = f"so the room is {multiple:.2f}x a typical move"
        reading += (
            f" Between one reading of this test and the next its left side has typically "
            f"moved {move_text} (the median of {count} moves, either way), {verdict}."
        )
        formula += f"; ÷ {move_text}"
    return Analytic(
        **base,  # type: ignore[arg-type]
        value=room,
        unit=unit,
        display=text,
        formula=formula,
        inputs=[
            test_input,
            *(
                AnalyticInput(
                    ref_kind="computed_test",
                    id=test_input.id,
                    label=side.label,
                    value=side.value,
                    display=side.display,
                )
                for side in (part.left, part.right)
            ),
        ],
        reading=reading,
    )


def _growth_level(
    fields: Callable[[str, str, str], dict[str, object]],
    test: ClaimTest,
    part: ComputedTest,
    test_input: AnalyticInput,
) -> Analytic | None:
    """For a growth test against a constant: the level it needed, and the gap to the level
    reached (a shortfall when it fails, a cushion when it holds)."""
    if test.form != "growth_threshold" or not isinstance(test.right, Number):
        return None
    if len(part.operands) < 2 or part.right is None or part.left is None:
        return None
    current, base = part.operands[0], part.operands[1]
    if current.value is None or base.value is None or part.right.value is None:
        return None
    if current.unit != "USD" or part.comparison not in (">", ">="):
        return None
    level = base.value * (1 + part.right.value / 100)
    gap = current.value - level
    what = current.label.split(",")[0].lower()
    formula = f"{current.display} {MINUS} {base.display} × (1 + {part.right.display})"
    inputs = [
        test_input,
        *(
            AnalyticInput(
                ref_kind="computed_test",
                id=test_input.id,
                label=side.label,
                value=side.value,
                display=side.display,
            )
            for side in (current, base)
        ),
    ]
    if gap < 0:
        base_fields = fields("needed", "Needed against reached", Q_NEEDED)
        reading = (
            f"To hold, {what} had to reach {usd_text(level)} ({base.display} grown by "
            f"{part.right.display}); it reached {current.display}, {usd_text(-gap)} short."
        )
    else:
        base_fields = fields("cushion", "Reached against needed", Q_CUSHION)
        reading = (
            f"To hold, {what} had to reach {usd_text(level)} ({base.display} grown by "
            f"{part.right.display}); it reached {current.display}, {usd_text(gap)} more than "
            "needed."
        )
    return Analytic(
        **base_fields,  # type: ignore[arg-type]
        value=gap,
        unit="USD",
        display=display(gap, "USD", signed=True),
        formula=formula,
        inputs=inputs,
        reading=reading,
    )


def _sides(
    base: dict[str, object], test: ClaimTest, computed: ComputedTest, test_input: AnalyticInput
) -> Analytic | None:
    """For a test of one amount against another: the left side as a percent of the right at
    each distinct reading of the history, and which way that has gone."""
    if isinstance(test.right, Number) or test.also is not None or test.each:
        return None
    if computed.left is None or computed.left.unit != "USD":
        return None
    distinct = [
        p
        for p in readings(computed.history)
        if p.left is not None and p.right is not None and p.right > 0
    ][-READINGS_SHOWN:]
    if len(distinct) < 2:
        return None
    shares = [p.left / p.right * 100 for p in distinct]  # type: ignore[operator]
    left = computed.left.label.split(",")[0]
    right = computed.right.label.split(",")[0].lower() if computed.right else "the right side"
    pieces = [
        f"{percent_text(share)} as of the {p.form} filed {p.filed}"
        for share, p in zip(shares, distinct, strict=True)
    ]
    steps = [b - a for a, b in zip(shares, shares[1:], strict=False)]
    if all(step < 0 for step in steps):
        trend = "it has fallen at every reading"
    elif all(step > 0 for step in steps):
        trend = "it has risen at every reading"
    else:
        trend = "it has moved both ways"
    newest = distinct[-1]
    return Analytic(
        **base,  # type: ignore[arg-type]
        value=shares[-1],
        unit="percent",
        display=percent_text(shares[-1]),
        formula=f"{newest.left_display} ÷ {newest.right_display}",
        inputs=[
            test_input,
            *(
                AnalyticInput(
                    ref_kind="computed_test",
                    id=test_input.id,
                    label=f"{left} ÷ {right}, as of the {p.form} filed {p.filed}",
                    value=share,
                    display=percent_text(share),
                    accession=p.accession,
                    form=p.form,
                    filed=p.filed,
                )
                for share, p in zip(shares, distinct, strict=True)
            ),
        ],
        reading=f"{left} as a share of {right}: {', '.join(pieces)}; {trend}.",
    )


def _record(
    base: dict[str, object], test: ClaimTest, computed: ComputedTest, test_input: AnalyticInput
) -> Analytic | None:
    """How often the test held over its history's distinct readings; None for a test of a
    named period, whose history is that one period read again."""
    if any(term.period.named for term in test.terms):
        return None
    held, total, longest, last_flip = history_record(computed.history)
    if total == 0:
        return _missing(base, "percent", computed.history_note or "The test has no history.")
    share = held / total * 100
    dates = sum(1 for p in computed.history if p.outcome != "cannot_compute")
    flip = (
        f"its outcome last changed with the filing of {last_flip}"
        if last_flip
        else "its outcome never changed"
    )
    return Analytic(
        **base,  # type: ignore[arg-type]
        value=share,
        unit="percent",
        display=f"{held} of {total}",
        formula=f"{held} ÷ {total}",
        inputs=[test_input],
        reading=(
            f"Run again as of each 10-K and 10-Q filing date of the last five years, the test "
            f"gave {total} distinct readings (over {dates} filing dates) and held in {held} of "
            f"them ({percent_text(share)}); its longest run holding was {longest}, and {flip}."
        ),
    )


# Bridges


def _balance(measures: Measures, key: str, end: date) -> tuple[float, PeriodValue] | None:
    """The balance of ``key`` at the date nearest ``end``, within a few days."""
    dates = measures.instants(key)
    near = [d for d in dates if abs((d - end).days) <= rules.BALANCE_MATCH_DAYS]
    if not near:
        return None
    nearest = min(near, key=lambda d: abs((d - end).days))
    outcome = measures.outcome(key, measures.slot("instant", nearest))
    if outcome.value is None:
        return None
    return outcome.value, dates[nearest]


def _year_start(measures: Measures, slot: Slot) -> date | None:
    """The end of the period a year before ``slot`` (an annual or a four-quarter one)."""
    like = slot if slot.kind == "annual" else measures.slot("quarter", slot.end)
    earlier = measures.year_before(like, "revenue")
    return None if earlier is None else earlier.end


def _period_words(slot: Slot) -> str:
    return (
        slot.label
        if slot.kind == "annual"
        else f"the four quarters to {slot.label.removeprefix('TTM to ')}"
    )


def cash_walk(measures: Measures, slot: Slot, claim_ids: Sequence[str]) -> Analytic:
    """Net income to operating cash flow to free cash flow over ``slot`` (a fiscal year or four
    quarters), with the non-cash charges the facts tag and the change in receivables and
    inventory over the same period."""
    words = _period_words(slot)
    tag = slot.label.lower() if slot.kind == "annual" else "ttm"
    fields = _fields(
        f"an:bridge:cash:{tag}",
        "bridge",
        f"Net income to free cash flow, {words}",
        Q_CASH_WALK,
        claim_ids,
        measure="free_cash_flow",
        period=words,
    )
    values: dict[str, float] = {}
    used: list[PeriodValue] = []
    for key in ("net_income", "operating_cash_flow", "capex"):
        outcome = measures.outcome(key, slot)
        if outcome.value is None:
            return _missing(fields, "USD", outcome.note or f"{_label(key)} is not in the facts.")
        values[key] = outcome.value
        used += outcome.used
    income, ocf, capex = values["net_income"], values["operating_cash_flow"], values["capex"]
    fcf = ocf - capex
    gap = fcf - income
    step = ocf - income
    reading = (
        f"In {words}, net income of {usd_text(income)} became operating cash flow of "
        f"{usd_text(ocf)} ({usd_text(abs(step))} {'more' if step >= 0 else 'less'}) and, after "
        f"capital expenditure of {usd_text(capex)}, free cash flow of {usd_text(fcf)}: "
        f"{usd_text(abs(gap))} {'above' if gap >= 0 else 'below'} net income."
    )
    charges: list[str] = []
    for key, name in (
        ("sbc", "stock-based compensation"),
        ("d_and_a", "depreciation and amortization"),
    ):
        outcome = measures.outcome(key, slot)
        if outcome.value is not None:
            used += outcome.used
            charges.append(f"{name} of {usd_text(outcome.value)}")
    if charges:
        reading += f" Non-cash charges added back on the way: {' and '.join(charges)}."
    start = _year_start(measures, slot)
    moved: list[str] = []
    for key in ("receivables", "inventory"):
        now = _balance(measures, key, slot.end)
        then = _balance(measures, key, start) if start is not None else None
        if now is None or then is None:
            continue
        change = now[0] - then[0]
        used += [now[1], then[1]]
        moved.append(
            f"{_lower(_label(key))} {'rose' if change >= 0 else 'fell'} {usd_text(abs(change))} "
            f"(to {usd_text(now[0])})"
        )
    if moved:
        reading += (
            f" Over the same period {' and '.join(moved)}: a rise in either takes cash without "
            "touching net income."
        )
    return Analytic(
        **fields,  # type: ignore[arg-type]
        value=gap,
        unit="USD",
        display=display(gap, "USD", signed=True),
        formula=(f"({usd_text(ocf)} {MINUS} {usd_text(capex)}) {MINUS} {usd_text(income)}"),
        inputs=_fact_inputs(used),
        reading=reading,
    )


def margin_split(measures: Measures, end: date, claim_ids: Sequence[str]) -> Analytic:
    """The change in operating margin on a year earlier, split into gross margin, R&D and the
    rest of operating expenses (each as a share of revenue)."""
    slot = measures.slot("quarter", end)
    fields = _fields(
        "an:bridge:op_margin",
        "bridge",
        "Operating margin change on a year earlier, split into its parts",
        Q_MARGIN_SPLIT,
        claim_ids,
        measure="operating_margin",
        period=slot.label,
    )
    earlier = measures.year_before(slot, "revenue")
    if earlier is None:
        return _missing(fields, "points", f"No quarter a year before {slot.label} is in the facts.")
    shares: dict[str, tuple[float, float]] = {}
    used: list[PeriodValue] = []
    for key in ("revenue", "gross_profit", "operating_income", "rnd"):
        now, then = measures.outcome(key, slot), measures.outcome(key, earlier)
        if now.value is None or then.value is None:
            if key == "rnd":
                continue
            return _missing(fields, "points", (now if now.value is None else then).note)
        shares[key] = (now.value, then.value)
        used += [*now.used, *then.used]
    if min(shares["revenue"]) <= 0:
        return _missing(fields, "points", "Revenue is not positive in one of the two quarters.")

    def pct(key: str, index: int) -> float:
        return shares[key][index] / shares["revenue"][index] * 100

    gm = (pct("gross_profit", 0), pct("gross_profit", 1))
    om = (pct("operating_income", 0), pct("operating_income", 1))
    rnd = (pct("rnd", 0), pct("rnd", 1)) if "rnd" in shares else None
    opex = (gm[0] - om[0], gm[1] - om[1])
    other = (opex[0] - rnd[0], opex[1] - rnd[1]) if rnd else opex
    d_om, d_gm = om[0] - om[1], gm[0] - gm[1]
    d_rnd = (rnd[0] - rnd[1]) if rnd else None
    d_other = other[0] - other[1]
    # Each piece is its effect on the operating margin: a lower expense share adds to it.
    pieces = [f"gross margin {display(d_gm, 'points')}"]
    formula = f"{display(d_gm, 'points')} {MINUS} ({display(d_other, 'points')})"
    if d_rnd is not None:
        pieces.append(f"a change in R&D as a share of revenue {display(-d_rnd, 'points')}")
        formula += f" {MINUS} ({display(d_rnd, 'points')})"
    pieces.append(
        (
            "a change in other operating expenses "
            if d_rnd is not None
            else "a change in operating expenses "
        )
        + f"as a share of revenue {display(-d_other, 'points')}"
    )
    return Analytic(
        **fields,  # type: ignore[arg-type]
        value=d_om,
        unit="points",
        display=display(d_om, "points"),
        formula=formula,
        inputs=_fact_inputs(used),
        reading=(
            f"Operating margin went from {percent_text(om[1])} in {earlier.label} to "
            f"{percent_text(om[0])} in {slot.label}, {display(d_om, 'points')}. What each part "
            f"added to it: {'; '.join(pieces)}."
        ),
    )


# Parts: the tagged breakdowns of the filings the run read


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_") or "part"


def _length(value: BreakdownValue) -> int | None:
    if value.period_start is None:
        return None
    start, end = date.fromisoformat(value.period_start), date.fromisoformat(value.period_end)
    return (end - start).days + 1


def _same_span(a: BreakdownValue, b: BreakdownValue) -> bool:
    """True when two periods are of one kind: their lengths differ by days only (a leap year,
    a 53-week fiscal year)."""
    first, second = _length(a), _length(b)
    return first is not None and second is not None and abs(first - second) <= SPAN_SLACK_DAYS


def _year_apart(newer: str, older: str) -> bool:
    days = (date.fromisoformat(newer) - date.fromisoformat(older)).days
    return YEAR_DAYS[0] <= days <= YEAR_DAYS[1]


def _span_words(value: BreakdownValue) -> str:
    length = _length(value)
    if length is not None and YEAR_DAYS[0] <= length <= YEAR_DAYS[1]:
        return f"the fiscal year ended {value.period_end}"
    if length is not None and QUARTER_DAYS[0] <= length <= QUARTER_DAYS[1]:
        return f"the quarter ended {value.period_end}"
    return f"{value.period_start} to {value.period_end}"


def _years(values: Sequence[BreakdownValue]) -> list[BreakdownValue]:
    """The newest period and the same-length periods a year and two years before it."""
    ordered = sorted(
        (v for v in values if v.period_start is not None),
        key=lambda v: (v.period_end, -(_length(v) or 0)),
        reverse=True,
    )
    if not ordered:
        return []
    # The newest period, the shortest when a filing tags a quarter and the year to date.
    newest = min(
        (v for v in ordered if v.period_end == ordered[0].period_end), key=lambda v: _length(v) or 0
    )
    chain = [newest]
    for older in ordered:
        if _same_span(older, chain[-1]) and _year_apart(chain[-1].period_end, older.period_end):
            chain.append(older)
    return chain[:3]


def _like(values: Sequence[BreakdownValue], like: BreakdownValue) -> BreakdownValue | None:
    """The value for the same period as ``like``: the same end and the same kind of span."""
    return next(
        (v for v in values if v.period_end == like.period_end and _same_span(v, like)),
        None,
    )


def _growth(now: BreakdownValue, then: BreakdownValue) -> float | None:
    return None if then.value <= 0 else (now.value - then.value) / then.value * 100


def _part_inputs(
    report: BreakdownReport, label: str, values: Sequence[BreakdownValue]
) -> list[AnalyticInput]:
    return [
        AnalyticInput(
            ref_kind="fact",
            id=f"{report.filing.accession}:{_slug(label)}:{v.period_start}..{v.period_end}",
            label=f"{label}, {v.period_start} to {v.period_end}",
            value=v.value,
            display=usd_text(v.value),
            accession=report.filing.accession,
            form=report.filing.form,
            filed=report.filing.filed_date,
        )
        for v in values
    ]


def find_part(report: BreakdownReport, name: str) -> tuple[Breakdown, BreakdownRow] | None:
    """The breakdown of revenue and its row whose label is ``name`` (case apart)."""
    for item in report.breakdowns:
        if item.id not in PART_BREAKDOWNS:
            continue
        for row in item.rows:
            if row.label.casefold() == name.casefold():
                return item, row
    return None


def part_analytics(
    reports: Sequence[BreakdownReport], name: str, key: str, claim_ids: Sequence[str]
) -> list[Analytic]:
    """A named part's growth against the company's, and whether it is speeding up or slowing,
    from each filing that tags it (the newest quarterly report, then the annual one)."""
    out: list[Analytic] = []
    for report in reports:
        found = find_part(report, name)
        if found is None:
            continue
        item, row = found
        chain = _years(row.values)
        if len(chain) < 2:
            continue
        now, then = chain[0], chain[1]
        growth = _growth(now, then)
        if growth is None:
            continue
        span = _span_words(now)
        tag = "fy" if span.startswith("the fiscal year") else "q"
        source = f"the {report.filing.form} filed {report.filing.filed_date}"
        reading = (
            f"{row.label} revenue was {usd_text(now.value)} in {span}, "
            f"{percent_text(growth, signed=True)} on a year earlier ({usd_text(then.value)})"
        )
        inputs = _part_inputs(report, row.label, [now, then])
        total_now, total_then = _like(item.total, now), _like(item.total, then)
        if total_now is not None and total_then is not None and total_then.value > 0:
            total_growth = _growth(total_now, total_then)
            assert total_growth is not None
            share_now = now.value / total_now.value * 100
            share_then = then.value / total_then.value * 100
            reading += (
                f"; the company's revenue grew {percent_text(total_growth, signed=True)}. It was "
                f"{percent_text(share_now)} of revenue, against {percent_text(share_then)} a year "
                "earlier"
            )
            inputs += _part_inputs(report, "Total revenue", [total_now, total_then])
        out.append(
            Analytic(
                **_fields(  # type: ignore[arg-type]
                    f"an:part:{_slug(row.label)}:{tag}:growth",
                    "part_growth",
                    f"{row.label} revenue, growth on a year earlier",
                    Q_PART.format(what=row.label),
                    claim_ids,
                    measure=key,
                    period=span,
                    origin=BREAKDOWN_ORIGIN,
                ),
                value=growth,
                unit="percent",
                display=percent_text(growth, signed=True),
                formula=(
                    f"({usd_text(now.value)} {MINUS} {usd_text(then.value)}) ÷ "
                    f"{usd_text(then.value)}"
                ),
                inputs=inputs,
                reading=f"{reading} (as {source} tags it).",
            )
        )
        pace = _part_pace(report, row, chain, key, claim_ids, tag, source)
        if pace is not None:
            out.append(pace)
    return out


def _part_pace(
    report: BreakdownReport,
    row: BreakdownRow,
    chain: Sequence[BreakdownValue],
    key: str,
    claim_ids: Sequence[str],
    tag: str,
    source: str,
) -> Analytic | None:
    """The part's growth in the newest period against its growth just before: the year before
    when the filing tags three years, else the earlier part of the year to date."""
    now, then = chain[0], chain[1]
    growth = _growth(now, then)
    assert growth is not None
    before: float | None = None
    earlier_words = ""
    used: list[BreakdownValue] = [now, then]
    if len(chain) >= 3:
        before = _growth(then, chain[2])
        earlier_words = _span_words(then)
        used.append(chain[2])
    else:
        ytd_now = next(
            (
                v
                for v in row.values
                if v.period_end == now.period_end
                and v.period_start is not None
                and (_length(v) or 0) > (_length(now) or 0) + SPAN_SLACK_DAYS
            ),
            None,
        )
        ytd_then = next(
            (
                v
                for v in row.values
                if v.period_end == then.period_end
                and v.period_start is not None
                and ytd_now is not None
                and _same_span(v, ytd_now)
            ),
            None,
        )
        if ytd_now is not None and ytd_then is not None:
            rest_now, rest_then = ytd_now.value - now.value, ytd_then.value - then.value
            if rest_then > 0:
                before = (rest_now - rest_then) / rest_then * 100
                earlier_words = (
                    f"the earlier part of the fiscal year to date ({ytd_now.period_start} to the "
                    f"start of the quarter)"
                )
                used += [ytd_now, ytd_then]
    if before is None:
        return None
    value = growth - before
    if round(value, 1) > 0:
        pace = f"speeding up, by {_points(value)}"
    elif round(value, 1) < 0:
        pace = f"slowing, by {_points(value)}"
    else:
        pace = "steady"
    g = (percent_text(growth, signed=True), percent_text(before, signed=True))
    return Analytic(
        **_fields(  # type: ignore[arg-type]
            f"an:part:{_slug(row.label)}:{tag}:pace",
            "part_pace",
            f"{row.label} revenue, growth now against growth before",
            Q_PART_PACE.format(what=row.label),
            claim_ids,
            measure=key,
            period=_span_words(now),
            origin=BREAKDOWN_ORIGIN,
        ),
        value=value,
        unit="points",
        display=display(value, "points"),
        formula=f"{g[0]} {MINUS} {g[1]}",
        inputs=_part_inputs(report, row.label, used),
        reading=(
            f"{row.label} revenue grew {g[0]} on a year earlier in {_span_words(now)}, against "
            f"{g[1]} in {earlier_words}: {pace} (as {source} tags it)."
        ),
    )


def partition(
    rows: Sequence[tuple[BreakdownRow, BreakdownValue, BreakdownValue]], total: float
) -> list[tuple[BreakdownRow, BreakdownValue, BreakdownValue]]:
    """The rows that split ``total`` without overlap, largest first: a filing tags a part and
    its own sub-parts on one axis, so a row is kept only while the rows kept still fit inside
    the total (within half a percent). The largest parts are kept, their sub-parts left out."""
    kept: list[tuple[BreakdownRow, BreakdownValue, BreakdownValue]] = []
    running = 0.0
    for row in sorted(rows, key=lambda item: item[1].value, reverse=True):
        if running + row[1].value <= total * 1.005:
            kept.append(row)
            running += row[1].value
    return kept


def growth_drivers(
    reports: Sequence[BreakdownReport],
    names: Sequence[str],
    claim_ids: Sequence[str],
    *,
    annual: bool = False,
) -> Analytic | None:
    """Each tagged part's contribution to revenue growth, in percentage points, from the
    newest filing whose breakdown tags two years of the wanted length (fiscal years for
    ``annual``, else a shorter period): the breakdown holding a named part, else the first.
    A part's contribution is its change over the total a year before; the parts shown are a
    split of the total without overlap (:func:`partition`)."""
    for report in reports:
        items = [
            item for item in report.breakdowns if item.id in PART_BREAKDOWNS and len(item.rows) > 1
        ]
        named = [
            item
            for item in items
            if any(row.label.casefold() == n.casefold() for row in item.rows for n in names)
        ]
        for item in [*named, *items][:1]:
            chain = _years(item.total)
            if len(chain) < 2 or chain[1].value <= 0:
                continue
            newest, older = chain[0], chain[1]
            if _span_words(newest).startswith("the fiscal year") != annual:
                continue
            total_growth = (newest.value - older.value) / older.value * 100
            rows = [
                (row, now, then)
                for row in item.rows
                if (now := _like(row.values, newest)) is not None
                and (then := _like(row.values, older)) is not None
            ]
            parts = [
                ((now.value - then.value) / older.value * 100, row, now, then)
                for row, now, then in partition(rows, newest.value)
            ]
            if not parts:
                continue
            parts.sort(key=lambda part: abs(part[0]), reverse=True)
            shown = parts[:PARTS_SHOWN]
            pieces = [f"{row.label} {display(c, 'points')}" for c, row, _, _ in shown]
            rest = len(parts) - len(shown)
            top = shown[0]
            inputs = _part_inputs(report, "Total revenue", [newest, older])
            for _, row, now, then in shown:
                inputs += _part_inputs(report, row.label, [now, then])
            return Analytic(
                **_fields(  # type: ignore[arg-type]
                    f"an:bridge:growth:{item.id}:{'fy' if annual else 'q'}",
                    "bridge",
                    f"{item.title}: each part's contribution to growth",
                    Q_DRIVERS,
                    claim_ids,
                    measure="revenue",
                    period=_span_words(newest),
                    origin=BREAKDOWN_ORIGIN,
                ),
                value=top[0],
                unit="points",
                display=display(top[0], "points"),
                formula=(
                    f"({usd_text(top[2].value)} {MINUS} {usd_text(top[3].value)}) ÷ "
                    f"{usd_text(older.value)}"
                ),
                inputs=inputs,
                reading=(
                    f"Revenue grew {percent_text(total_growth, signed=True)} in "
                    f"{_span_words(newest)}. Of that growth, each part's contribution: "
                    f"{'; '.join(pieces)}"
                    + (f"; {rest} smaller part(s) not shown" if rest > 0 else "")
                    + f" (as the {report.filing.form} filed {report.filing.filed_date} tags "
                    "them; the parts shown split the total without overlap)."
                ),
            )
    return None


# Earnings quality


def _eq(
    what: str, label: str, question: str, period: str, claim_ids: Sequence[str], measure: str = ""
) -> dict[str, object]:
    return _fields(
        f"an:eq:{what}",
        "earnings_quality",
        label,
        question,
        claim_ids,
        measure=measure,
        period=period,
    )


def _conversion_at(measures: Measures, slot: Slot) -> tuple[float, float, float, tuple] | str:
    """(ratio, operating cash flow, net income, facts) over ``slot``, or why not."""
    income, ocf = (
        measures.outcome("net_income", slot),
        measures.outcome("operating_cash_flow", slot),
    )
    for outcome, key in ((income, "net_income"), (ocf, "operating_cash_flow")):
        if outcome.value is None:
            return outcome.note or f"{_label(key)} is not in the facts."
    assert income.value is not None and ocf.value is not None
    if income.value <= 0:
        return f"Not meaningful: net income is not positive in {slot.label}."
    return ocf.value / income.value, ocf.value, income.value, (*ocf.used, *income.used)


def cash_conversion(measures: Measures, end: date, claim_ids: Sequence[str]) -> Analytic:
    """Operating cash flow over net income for the four quarters to ``end``, with the newest
    quarter alone and the four quarters a year before."""
    quarter = measures.slot("quarter", end)
    ttm = measures.slot("ttm", end)
    words = f"the four quarters to {quarter.label}"
    fields = _eq(
        "cash_conversion",
        "Cash conversion: operating cash flow ÷ net income",
        Q_CONVERSION,
        words,
        claim_ids,
        "operating_cash_flow",
    )
    now = _conversion_at(measures, ttm)
    if isinstance(now, str):
        return _missing(fields, "multiple", now)
    ratio, ocf, income, used = now
    reading = (
        f"Over {words}, each dollar of net income came with {ratio:.2f} dollars of operating "
        f"cash flow ({usd_text(ocf)} against {usd_text(income)})"
    )
    alone = _conversion_at(measures, quarter)
    if not isinstance(alone, str):
        reading += (
            f". In {quarter.label} alone it was {alone[0]:.2f}x ({usd_text(alone[1])} against "
            f"{usd_text(alone[2])})"
        )
    earlier = measures.year_before(quarter, "revenue")
    if earlier is not None:
        before = _conversion_at(measures, measures.slot("ttm", earlier.end))
        if not isinstance(before, str):
            reading += f", and {before[0]:.2f}x over the four quarters a year before"
            used = (*used, *before[3])
    return Analytic(
        **fields,  # type: ignore[arg-type]
        value=ratio,
        unit="multiple",
        display=f"{ratio:.2f}x",
        formula=f"{usd_text(ocf)} ÷ {usd_text(income)}",
        inputs=_fact_inputs(used),
        reading=reading + ".",
    )


def _quarter_days(value: PeriodValue | None) -> int:
    if value is None or value.start is None:
        return rules.DEFAULT_QUARTER_DAYS
    return (value.end - value.start).days + 1


def balance_days(measures: Measures, end: date, what: str, claim_ids: Sequence[str]) -> Analytic:
    """Days of a quarter's flow a balance stands for at the quarter's end, and a year before:
    receivables over revenue ("dso"), inventory over cost of revenue ("dio")."""
    balance_key, flow_key = (
        ("receivables", "revenue") if what == "dso" else ("inventory", "cost_of_revenue")
    )
    slot = measures.slot("quarter", end)
    name = "Receivable days" if what == "dso" else "Inventory days"
    flow_words = "revenue" if flow_key == "revenue" else "cost of revenue"
    fields = _eq(
        what,
        f"{name}: {_lower(_label(balance_key))} ÷ the quarter's {flow_words} × its days",
        Q_DSO if what == "dso" else Q_DIO,
        slot.label,
        claim_ids,
        balance_key,
    )

    def at(quarter: Slot) -> tuple[float, float, float, int, list[PeriodValue]] | str:
        balance = _balance(measures, balance_key, quarter.end)
        if balance is None:
            return f"No {_lower(_label(balance_key))} balance is reported at {quarter.label}'s end."
        flow = measures.outcome(flow_key, quarter)
        if flow.value is None:
            return flow.note or f"No {flow_words} for {quarter.label}."
        if flow.value <= 0:
            return f"Not meaningful: {flow_words} is not positive in {quarter.label}."
        days = _quarter_days(measures.series("quarter", "revenue").get(quarter.end))
        return (
            balance[0] / flow.value * days,
            balance[0],
            flow.value,
            days,
            [balance[1], *flow.used],
        )

    now = at(slot)
    if isinstance(now, str):
        return _missing(fields, "days", now)
    value, balance, flow, days, used = now
    reading = (
        f"At the end of {slot.label}, {_lower(_label(balance_key))} of {usd_text(balance)} stood "
        f"for {value:.1f} days of the quarter's {flow_words} ({usd_text(flow)} over {days} days)"
    )
    earlier = measures.year_before(slot, "revenue")
    then = at(earlier) if earlier is not None else "no year-earlier quarter"
    if earlier is not None and not isinstance(then, str):
        grew = (balance / then[1] - 1) * 100 if then[1] > 0 else None
        flow_grew = (flow / then[2] - 1) * 100 if then[2] > 0 else None
        reading += f", against {then[0]:.1f} days a year before"
        if grew is not None and flow_grew is not None:
            reading += (
                f": the balance grew {percent_text(grew, signed=True)} while {flow_words} grew "
                f"{percent_text(flow_grew, signed=True)}"
            )
        used = [*used, *then[4]]
    return Analytic(
        **fields,  # type: ignore[arg-type]
        value=value,
        unit="days",
        display=f"{value:.1f} days",
        formula=f"{usd_text(balance)} ÷ {usd_text(flow)} × {days}",
        inputs=_fact_inputs(used),
        reading=reading + ".",
    )


def revenue_share(measures: Measures, end: date, key: str, claim_ids: Sequence[str]) -> Analytic:
    """A cost as a share of revenue over four quarters, and over the four a year before:
    ``sbc_ratio`` or ``capex_ratio``."""
    quarter = measures.slot("quarter", end)
    words = f"the four quarters to {quarter.label}"
    fields = _eq(
        key,
        f"{_label(key)}, four quarters",
        Q_SBC if key == "sbc_ratio" else Q_CAPEX,
        words,
        claim_ids,
        key,
    )
    outcome = measures.outcome(key, measures.slot("ttm", end))
    if outcome.value is None:
        return _missing(fields, "percent", outcome.note or "Not in the facts.")
    reading = f"{_label(key)} was {percent_text(outcome.value)} over {words}"
    used = outcome.used
    earlier = measures.year_before(quarter, "revenue")
    if earlier is not None:
        before = measures.outcome(key, measures.slot("ttm", earlier.end))
        if before.value is not None:
            reading += (
                f", against {percent_text(before.value)} over the four quarters a year before"
            )
            used = (*used, *before.used)
    return Analytic(
        **fields,  # type: ignore[arg-type]
        value=outcome.value,
        unit="percent",
        display=percent_text(outcome.value),
        formula=outcome.formula,
        inputs=_fact_inputs(used),
        reading=reading + ".",
    )


def deferred_revenue(measures: Measures, end: date, claim_ids: Sequence[str]) -> Analytic:
    """Deferred revenue at the quarter's end and its change on a year earlier, beside revenue's."""
    key = "deferred_revenue"
    slot = measures.slot("quarter", end)
    fields = _eq(
        "deferred_revenue",
        "Deferred revenue, change on a year earlier",
        Q_DEFERRED,
        slot.label,
        claim_ids,
        key,
    )
    now = _balance(measures, key, end)
    if now is None:
        return _missing(
            fields, "percent", "The facts tag no deferred revenue at this quarter's end."
        )
    earlier = measures.year_before(slot, "revenue")
    then = _balance(measures, key, earlier.end) if earlier is not None else None
    if then is None or then[0] <= 0:
        return _missing(
            fields, "percent", "The facts tag no deferred revenue a year before to compare with."
        )
    growth = (now[0] - then[0]) / then[0] * 100
    reading = (
        f"Deferred revenue was {usd_text(now[0])} at the end of {slot.label}, "
        f"{percent_text(growth, signed=True)} on a year earlier ({usd_text(then[0])})"
    )
    latest = _point_at(measures, "revenue", slot)
    found = _growth_at(measures, "revenue", latest) if latest is not None else None
    if found is not None:
        reading += f"; revenue grew {percent_text(found[0], signed=True)} over the same year"
    return Analytic(
        **fields,  # type: ignore[arg-type]
        value=growth,
        unit="percent",
        display=percent_text(growth, signed=True),
        formula=f"({usd_text(now[0])} {MINUS} {usd_text(then[0])}) ÷ {usd_text(then[0])}",
        inputs=_fact_inputs([now[1], then[1]]),
        reading=reading + ".",
    )


def return_on_equity(measures: Measures, end: date, claim_ids: Sequence[str]) -> Analytic:
    """Return on average equity over four quarters = net margin × asset turnover × equity
    multiplier (the DuPont split), on balances averaged over the quarter's end and a year
    before it."""
    quarter = measures.slot("quarter", end)
    words = f"the four quarters to {quarter.label}"
    fields = _eq("roe", "Return on average equity, split the DuPont way", Q_ROE, words, claim_ids)
    ttm = measures.slot("ttm", end)
    values: dict[str, float] = {}
    used: list[PeriodValue] = []
    for key in ("net_income", "revenue"):
        outcome = measures.outcome(key, ttm)
        if outcome.value is None:
            return _missing(
                fields, "percent", outcome.note or f"{_label(key)} is not in the facts."
            )
        values[key] = outcome.value
        used += outcome.used
    earlier = measures.year_before(quarter, "revenue")
    averages: dict[str, float] = {}
    for key in ("total_assets", "equity"):
        ends = [_balance(measures, key, end)]
        ends.append(_balance(measures, key, earlier.end) if earlier is not None else None)
        if any(item is None for item in ends):
            return _missing(
                fields,
                "percent",
                f"{_label(key)} is not reported at both ends of the four quarters.",
            )
        averages[key] = sum(item[0] for item in ends if item is not None) / 2
        used += [item[1] for item in ends if item is not None]
    assets, equity = averages["total_assets"], averages["equity"]
    income, revenue = values["net_income"], values["revenue"]
    if equity <= 0 or revenue <= 0 or assets <= 0:
        return _missing(
            fields, "percent", "Not meaningful: average equity, assets or revenue is not positive."
        )
    margin = income / revenue * 100
    turnover = revenue / assets
    multiplier = assets / equity
    roe = margin * turnover * multiplier
    return Analytic(
        **fields,  # type: ignore[arg-type]
        value=roe,
        unit="percent",
        display=percent_text(roe),
        formula=f"{percent_text(margin)} × {turnover:.2f}x × {multiplier:.2f}x",
        inputs=_fact_inputs(used),
        reading=(
            f"Return on average equity was {percent_text(roe)} over {words}: a net margin of "
            f"{percent_text(margin)}, times revenue of {turnover:.2f}x average total assets "
            f"({usd_text(assets)}), times average assets of {multiplier:.2f}x average equity "
            f"({usd_text(equity)})."
        ),
    )


# Which claims each bridge or signal bears on: those tied to any of these measures.
BEARS_ON: dict[str, tuple[str, ...]] = {
    "cash_walk": ("free_cash_flow", "operating_cash_flow", "fcf_margin"),
    "op_margin": ("operating_margin", "operating_income", "rnd_ratio", "opex_ratio", "sga_ratio"),
    "drivers": ("revenue",),
    "cash_conversion": (
        "net_income",
        "eps_diluted",
        "net_margin",
        "operating_cash_flow",
        "free_cash_flow",
        "fcf_margin",
    ),
    # The cash walk already gives a cash-flow claim the change in both balances.
    "dso": ("revenue", "receivables"),
    "dio": ("inventory", "gross_margin", "cost_of_revenue"),
    "sbc_ratio": ("sbc", "sbc_ratio", "free_cash_flow", "fcf_margin", "operating_margin"),
    "capex_ratio": ("capex", "capex_ratio", "free_cash_flow", "fcf_margin"),
    "deferred_revenue": ("deferred_revenue", "deferred_revenue_current", "revenue"),
    "roe": ("equity", "total_assets", "net_margin"),
}


def bears_on(topic: str, measures_by_claim: dict[str, list[str]]) -> list[str]:
    """The claims whose measures include any of :data:`BEARS_ON` for ``topic``."""
    keys = set(BEARS_ON[topic])
    return [claim for claim, measures in measures_by_claim.items() if keys & set(measures)]


def part_name(key: str) -> str:
    """The part a key such as 'revenue(segment "Data Center")' names; "" for a catalogue key."""
    match = re.fullmatch(r'\w+\(\w+ "(.+)"\)', key)
    return match[1] if match else ""


def _two_measures(test: ClaimTest) -> bool:
    """True for a test of one measure against a different one (not against its own past)."""
    return not isinstance(test.right, Number) and test.right.subject != test.left.subject


# The provider


class FactsProvider:
    """Analytics from the run's dated XBRL facts and the tagged breakdowns of its filings."""

    name = PROVIDER

    def provide(self, request: AnalyticsRequest) -> list[Analytic]:
        """Every analytic a claim of ``request`` asks for (see the module docstring)."""
        tied = {claim_id: keys for claim_id, keys in request.measures.items() if keys}
        if request.book is None:
            if not tied and not request.tests:
                return []
            why = f" ({request.error})" if request.error else ""
            return [
                Analytic(
                    id="an:facts",
                    kind="none",
                    label="Analytics from the company's facts",
                    question="What do the company's reported figures say about the claims?",
                    claim_ids=list(dict.fromkeys([*tied, *request.tests])),
                    available=False,
                    unit="count",
                    note=NO_FACTS.format(why=why),
                )
            ]
        measures = Measures(request.book, request.calendar)
        out: list[Analytic] = []
        bases = {
            claim_id: claim_basis(
                request.tests[claim_id][0] if claim_id in request.tests else None, measures
            )
            for claim_id in request.measures
        }
        # A measure's analytics, once per basis, tied to every claim that asks on that basis.
        asked: dict[tuple[str, str], tuple[Slot | None, list[str]]] = {}
        for claim_id, keys in tied.items():
            basis = bases[claim_id]
            pair = request.tests.get(claim_id)
            for key in keys:
                if key not in METRICS:
                    continue
                if pair is not None and _two_measures(pair[0]):
                    # One measure against another: the gap is the subject, and the test's
                    # own analytics and the bridges follow it; neither side's path does.
                    continue
                annual = basis.kind == "annual" and METRICS[key][1] != "instant"
                tag = basis.slot.label if annual and basis.slot else "quarter"
                asked.setdefault((key, tag), (basis.slot if annual else None, []))[1].append(
                    claim_id
                )
        for (key, _), (slot, claim_ids) in asked.items():
            if slot is not None:
                out += fiscal_year_analytics(measures, key, slot, claim_ids)
            else:
                out += quarter_analytics(measures, key, claim_ids)
        for claim_id, (test, computed) in request.tests.items():
            out += computed_test_analytics(claim_id, test, computed)
        out += self._bridges(measures, tied, bases)
        out += self._parts(request.reports, tied, bases)
        return out

    @staticmethod
    def _bridges(
        measures: Measures, tied: dict[str, list[str]], bases: dict[str, Basis]
    ) -> list[Analytic]:
        series = measures.series("quarter", "revenue")
        end = max(series) if series else None
        if end is None:
            return []
        out: list[Analytic] = []
        walkers = bears_on("cash_walk", tied)
        years: dict[str, tuple[Slot, list[str]]] = {}
        for claim_id in walkers:
            basis = bases[claim_id]
            if basis.kind == "annual" and basis.slot is not None:
                years.setdefault(basis.slot.label, (basis.slot, []))[1].append(claim_id)
        for slot, claim_ids in years.values():
            out.append(cash_walk(measures, slot, claim_ids))
        if walkers:
            out.append(cash_walk(measures, measures.slot("ttm", end), walkers))
        if claims := bears_on("op_margin", tied):
            out.append(margin_split(measures, end, claims))
        if claims := bears_on("cash_conversion", tied):
            out.append(cash_conversion(measures, end, claims))
        for what in ("dso", "dio"):
            if claims := bears_on(what, tied):
                out.append(balance_days(measures, end, what, claims))
        for key in ("sbc_ratio", "capex_ratio"):
            if claims := bears_on(key, tied):
                out.append(revenue_share(measures, end, key, claims))
        if claims := bears_on("deferred_revenue", tied):
            out.append(deferred_revenue(measures, end, claims))
        if claims := bears_on("roe", tied):
            out.append(return_on_equity(measures, end, claims))
        return out

    @staticmethod
    def _parts(
        reports: Sequence[BreakdownReport], tied: dict[str, list[str]], bases: dict[str, Basis]
    ) -> list[Analytic]:
        out: list[Analytic] = []
        named: dict[str, tuple[str, list[str]]] = {}
        for claim_id, keys in tied.items():
            for key in keys:
                name = part_name(key)
                if name and key.startswith("revenue("):
                    named.setdefault(name.casefold(), (key, []))[1].append(claim_id)
        for key, claim_ids in named.values():
            out += part_analytics(reports, part_name(key), key, claim_ids)
        names = [part_name(key) for key, _ in named.values()]
        asking = [*bears_on("drivers", tied), *(c for _, ids in named.values() for c in ids)]
        for annual in (False, True):
            claim_ids = [
                claim_id
                for claim_id in dict.fromkeys(asking)
                if (bases[claim_id].kind == "annual") == annual
            ]
            if claim_ids:
                found = growth_drivers(reports, names, claim_ids, annual=annual)
                if found is not None:
                    out.append(found)
        return out
