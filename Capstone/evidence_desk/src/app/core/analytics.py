"""Analytics: the numbers an analyst works out from a company's dated facts, with their arithmetic.

Pure: no I/O, no model. Everything is computed from one :class:`~app.core.facts.FactBook`
(as of the run's date when it has one, so nothing filed later is seen) through the same
:class:`~app.core.claim_eval.Measures` the computed tests read, so an analytic and a test
never disagree about a value. Each result is an :class:`~app.core.analysis_models.Analytic`
with a stable id, its formula with the numbers used, its inputs (each fact with its
filing) and one plain reading written from a template.

Four families (``docs/analysis.md`` defines each):

- per measure (``an:<measure>:<what>``): level, change on the year and on the quarter,
  the 4- and 8-quarter trend, whether growth is speeding up or slowing, the 8-quarter
  range and the typical quarterly move;
- per computed test (``an:<claim>:<what>``): headroom in units and in typical moves, the
  value at which the outcome flips, needed against actual for a failing growth test, and
  how often the test held across its history;
- bridges (``an:bridge:<what>``): free cash flow from operating cash flow and capex, net
  income to operating cash flow, the operating-margin change split into its parts, and
  each part's contribution to growth from the tagged breakdowns the run already read;
- earnings quality and operating signals (``an:eq:<what>``): cash conversion, accruals as
  a share of net income, receivable and inventory days, stock compensation and capex
  against revenue, deferred revenue, and a DuPont split of return on equity.

An analytic the facts cannot give is still returned, with ``available`` False and a note
saying why, so the record shows what was tried. :class:`FactsProvider` is the first
:class:`AnalyticsProvider`; a later provider (peers, prices) returns analytics of the same
shape with its own ``provider`` and ``data_origin``.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from app.core import analysis_policy as rules
from app.core.analysis_models import Analytic, AnalyticInput, AnalyticUnit
from app.core.breakdown_models import Breakdown, BreakdownReport, BreakdownValue
from app.core.claim_eval import Measures, Slot
from app.core.claim_test_models import ComputedTest, HistoryPoint
from app.core.claimtest import METRICS, ClaimTest, Number
from app.core.facts import FactBook, PeriodValue
from app.core.metrics import MINUS, Outcome, eps_text, percent_text, usd_text
from app.core.periods import FiscalCalendar

PROVIDER = "facts"
ORIGIN = "sec_xbrl_facts"
BREAKDOWN_ORIGIN = "sec_tagged_breakdowns"
NO_FACTS = "The run could not read the company's XBRL facts{why}."
AMOUNT_KINDS = ("flow", "instant", "per_share", "shares")
SEGMENT_BREAKDOWNS = ("revenue_by_segment", "revenue_by_product", "revenue_by_geography")
YEAR_DAYS = (350, 380)
QUARTER_DAYS = (80, 100)
SAME_END_DAYS = 10


# The shape


@dataclass(frozen=True)
class AnalyticsRequest:
    """What a provider is asked for: the run's facts and what its claims bear on.

    ``measures`` maps each claim id to the catalogue keys it bears on, in order (parts are
    not keys here). ``tests`` maps a claim id to its compiled test and the computed result.
    ``reports`` are the tagged breakdowns the run already read (none read for this).
    ``error`` says why there are no facts when ``book`` is None.
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


# Reading a measure quarter by quarter


@dataclass(frozen=True)
class Point:
    """One measure over one bound quarter (or at one balance date)."""

    slot: Slot
    value: float
    used: tuple[PeriodValue, ...]


def _point_input(key: str, point: Point) -> AnalyticInput:
    """One quarter of a measure as an input, with the newest filing among its facts."""
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


def quarterly(measures: Measures, key: str, count: int) -> tuple[list[Point], str]:
    """Up to ``count`` consecutive quarters of ``key``, newest first, and why it stopped.

    The walk stops at the first quarter with no value (a gap is never bridged), so every
    pair of neighbours is one quarter apart.
    """
    slot = latest_slot(measures, key)
    if slot is None:
        return [], f"The facts hold no quarter of {_lower(_label(key))}."
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


def _change(now: float, before: float, ratio: bool) -> float | None:
    """Points for a ratio; percent growth on a positive base for an amount."""
    if ratio:
        return now - before
    if before <= 0:
        return None
    return (now - before) / before * 100


# Per measure


def _base(
    key: str, kind: str, label: str, claim_ids: Sequence[str], period: str = ""
) -> dict[str, object]:
    return {
        "id": f"an:{key}:{kind}",
        "provider": PROVIDER,
        "data_origin": ORIGIN,
        "kind": kind,
        "label": label,
        "claim_ids": list(claim_ids),
        "measure": key,
        "period": period,
    }


def _missing(fields: dict[str, object], unit: AnalyticUnit, note: str) -> Analytic:
    return Analytic(**fields, unit=unit, available=False, note=note)  # type: ignore[arg-type]


def _verb(value: float, ratio: bool) -> str:
    if value > 0:
        return "rose" if ratio else "grew"
    if value < 0:
        return "fell" if ratio else "shrank"
    return "was unchanged"


def measure_analytics(
    measures: Measures, key: str, claim_ids: Sequence[str] = ()
) -> list[Analytic]:
    """Every per-measure analytic of ``key``: level, changes, trends, acceleration, range
    and typical move. Each one the facts cannot give is returned unavailable, with why."""
    ratio = METRICS[key][1] == "ratio"
    label = _label(key)
    unit = _unit_of(key)
    change_unit: AnalyticUnit = "points" if ratio else "percent"
    history = max(rules.LONG_WINDOW, 4 + rules.SHORT_WINDOW) + 1
    points, why = quarterly(measures, key, history)
    out: list[Analytic] = []
    if not points:
        note = why or f"The facts hold no quarter of {_lower(label)}."
        for kind, what in (
            ("level", unit),
            ("yoy", change_unit),
            ("qoq", change_unit),
        ):
            out.append(_missing(_base(key, kind, f"{label}: {kind}", claim_ids), what, note))
        return out
    latest = points[0]
    level = Analytic(
        **_base(key, "level", f"{label}, latest quarter", claim_ids, latest.slot.label),  # type: ignore[arg-type]
        value=latest.value,
        unit=unit,
        display=display(latest.value, unit),
        formula=measures.outcome(key, latest.slot).formula,
        inputs=_fact_inputs(latest.used),
        reading=f"{label} was {display(latest.value, unit)} in {latest.slot.label}.",
    )
    out.append(level)
    out.append(_step_change(measures, key, latest, "yoy", claim_ids))
    out.append(_step_change(measures, key, latest, "qoq", claim_ids, points))
    for window in (rules.SHORT_WINDOW, rules.LONG_WINDOW):
        out.append(_trend(key, points, window, claim_ids))
    if not ratio:
        out.append(_acceleration(measures, key, points, claim_ids))
    out.append(_range(key, points, claim_ids))
    out.append(_typical_move(key, points, claim_ids))
    return out


def _step_change(
    measures: Measures,
    key: str,
    latest: Point,
    kind: str,
    claim_ids: Sequence[str],
    points: Sequence[Point] = (),
) -> Analytic:
    ratio = METRICS[key][1] == "ratio"
    label = _label(key)
    unit: AnalyticUnit = "points" if ratio else "percent"
    on = "a year earlier" if kind == "yoy" else "the quarter before"
    fields = _base(key, kind, f"{label}, change on {on}", claim_ids, latest.slot.label)
    if kind == "yoy":
        earlier = measures.year_before(latest.slot, key)
    else:
        earlier = points[1].slot if len(points) > 1 else None
    if earlier is None:
        return _missing(fields, unit, f"No quarter {on} than {latest.slot.label} is in the facts.")
    before = measures.outcome(key, earlier)
    if before.value is None:
        return _missing(fields, unit, before.note)
    value = _change(latest.value, before.value, ratio)
    if value is None:
        return _missing(
            fields, unit, f"Growth is not meaningful: {earlier.label} is not positive."
        )
    shown_now = display(latest.value, _unit_of(key))
    shown_before = display(before.value, _unit_of(key))
    formula = (
        f"{shown_now} {MINUS} {shown_before}"
        if ratio
        else f"({shown_now} {MINUS} {shown_before}) ÷ {shown_before}"
    )
    text = display(value, unit, signed=True)
    return Analytic(
        **fields,  # type: ignore[arg-type]
        value=value,
        unit=unit,
        display=text,
        formula=formula,
        inputs=_fact_inputs((*latest.used, *before.used)),
        reading=(
            f"{label} {_verb(value, ratio)} {text.lstrip('+')} on {earlier.label} "
            f"({shown_before} to {shown_now})."
            if value
            else f"{label} was unchanged on {earlier.label} ({shown_now})."
        ),
    )


def compound_rate(first: float, last: float, steps: int) -> float | None:
    """The compound rate per step, in percent, from ``first`` to ``last``; None unless both
    are positive."""
    if first <= 0 or last <= 0 or steps <= 0:
        return None
    return ((last / first) ** (1 / steps) - 1) * 100


def _trend(key: str, points: Sequence[Point], window: int, claim_ids: Sequence[str]) -> Analytic:
    ratio = METRICS[key][1] == "ratio"
    label = _label(key)
    unit: AnalyticUnit = "points" if ratio else "percent"
    kind = f"trend{window}"
    what = (
        f"change over the last {window} quarters"
        if ratio
        else f"compound quarterly growth over the last {window} quarters"
    )
    fields = _base(key, kind, f"{label}, {what}", claim_ids, points[0].slot.label)
    if len(points) <= window:
        return _missing(
            fields,
            unit,
            f"{window + 1} consecutive quarters are needed; the facts hold {len(points)}.",
        )
    first, last = points[window], points[0]
    shown = (display(first.value, _unit_of(key)), display(last.value, _unit_of(key)))
    inputs = [_point_input(key, first), _point_input(key, last)]
    if ratio:
        value: float | None = last.value - first.value
        formula = f"{shown[1]} {MINUS} {shown[0]}"
    else:
        value = compound_rate(first.value, last.value, window)
        formula = f"({shown[1]} ÷ {shown[0]})^(1/{window}) {MINUS} 1"
    if value is None:
        return _missing(fields, unit, "A compound rate needs both ends positive.")
    text = display(value, unit, signed=True)
    if ratio:
        reading = (
            f"Over the last {window} quarters {_lower(label)} moved {text} "
            f"({shown[0]} in {first.slot.label} to {shown[1]} in {last.slot.label})."
        )
    else:
        reading = (
            f"Over the last {window} quarters {_lower(label)} grew at a compound {text} a quarter "
            f"({shown[0]} in {first.slot.label} to {shown[1]} in {last.slot.label})."
        )
    return Analytic(
        **fields,  # type: ignore[arg-type]
        value=value,
        unit=unit,
        display=text,
        formula=formula,
        inputs=inputs,
        reading=reading,
    )


def _acceleration(
    measures: Measures, key: str, points: Sequence[Point], claim_ids: Sequence[str]
) -> Analytic:
    """Growth on a year earlier now, a quarter ago and a year ago: speeding up or slowing."""
    label = _label(key)
    fields = _base(
        key,
        "acceleration",
        f"{label}, growth on a year earlier now against a quarter before",
        claim_ids,
        points[0].slot.label,
    )

    def growth_at(index: int) -> tuple[float, Point, Point] | None:
        if index >= len(points):
            return None
        point = points[index]
        earlier = measures.year_before(point.slot, key)
        if earlier is None:
            return None
        before = measures.outcome(key, earlier)
        if before.value is None:
            return None
        value = _change(point.value, before.value, False)
        if value is None:
            return None
        return value, point, Point(earlier, before.value, before.used)

    now, previous, year_ago = growth_at(0), growth_at(1), growth_at(4)
    if now is None or previous is None:
        return _missing(
            fields,
            "points",
            "Growth on a year earlier is needed for the latest two quarters; the facts do "
            "not give both.",
        )
    value = now[0] - previous[0]
    g = [percent_text(item[0], signed=True) for item in (now, previous)]
    inputs = [_point_input(key, now[1]), _point_input(key, now[2])]
    inputs += [_point_input(key, previous[1]), _point_input(key, previous[2])]
    pace = "speeding up" if value > 0 else "slowing" if value < 0 else "steady"
    reading = (
        f"{label} growth on a year earlier is {g[0]} in {now[1].slot.label} against {g[1]} a "
        f"quarter before: {pace} by {abs(round(value, 1)):.1f} percentage points"
    )
    formula = f"{g[0]} {MINUS} {g[1]}"
    if year_ago is not None:
        g4 = percent_text(year_ago[0], signed=True)
        reading += f", and against {g4} four quarters before"
        inputs += [_point_input(key, year_ago[1]), _point_input(key, year_ago[2])]
    return Analytic(
        **fields,  # type: ignore[arg-type]
        value=value,
        unit="points",
        display=display(value, "points"),
        formula=formula,
        inputs=list({i.id: i for i in inputs}.values()),
        reading=reading + ".",
    )


def _range(key: str, points: Sequence[Point], claim_ids: Sequence[str]) -> Analytic:
    """Where the latest value sits between the low and the high of the last 8 quarters."""
    label = _label(key)
    unit = _unit_of(key)
    window = list(points[: rules.LONG_WINDOW])
    fields = _base(
        key,
        "range8",
        f"{label}, where the latest quarter sits in the last {len(window)} quarters' range",
        claim_ids,
        points[0].slot.label,
    )
    if len(window) < rules.SHORT_WINDOW:
        return _missing(
            fields,
            "percent",
            f"At least {rules.SHORT_WINDOW} quarters are needed; the facts hold {len(window)}.",
        )
    low = min(window, key=lambda p: p.value)
    high = max(window, key=lambda p: p.value)
    latest = window[0]
    span = high.value - low.value
    position = 100.0 if span == 0 else (latest.value - low.value) / span * 100
    shown = (display(low.value, unit), display(high.value, unit), display(latest.value, unit))
    where = (
        "at the high"
        if latest is high
        else "at the low"
        if latest is low
        else f"{position:.0f}% of the way from the low to the high"
    )
    return Analytic(
        **fields,  # type: ignore[arg-type]
        value=position,
        unit="percent",
        display=f"{shown[0]} to {shown[1]}",
        formula=f"({shown[2]} {MINUS} {shown[0]}) ÷ ({shown[1]} {MINUS} {shown[0]})",
        inputs=[_point_input(key, low), _point_input(key, high), _point_input(key, latest)],
        reading=(
            f"Over the last {len(window)} quarters {_lower(label)} ranged from {shown[0]} "
            f"({low.slot.label}) to {shown[1]} ({high.slot.label}); the latest, {shown[2]}, is "
            f"{where}."
        ),
    )


def median_move(values: Sequence[float], ratio: bool) -> float | None:
    """The median absolute change between neighbours of ``values`` (newest first): points for a
    ratio, percent of the earlier value for an amount (a non-positive earlier value is
    skipped)."""
    moves: list[float] = []
    for newer, older in zip(values, values[1:], strict=False):
        change = _change(newer, older, ratio)
        if change is not None:
            moves.append(abs(change))
    return statistics.median(moves) if moves else None


def _typical_move(key: str, points: Sequence[Point], claim_ids: Sequence[str]) -> Analytic:
    ratio = METRICS[key][1] == "ratio"
    label = _label(key)
    unit: AnalyticUnit = "points" if ratio else "percent"
    window = list(points[: rules.LONG_WINDOW + 1])
    fields = _base(
        key,
        "typical_move",
        f"{label}, median quarter-on-quarter move over the last {len(window) - 1} quarters",
        claim_ids,
        points[0].slot.label,
    )
    if len(window) - 1 < rules.SHORT_WINDOW:
        return _missing(
            fields,
            unit,
            f"At least {rules.SHORT_WINDOW} quarterly changes are needed; the facts hold "
            f"{max(len(window) - 1, 0)}.",
        )
    value = median_move([p.value for p in window], ratio)
    if value is None:
        return _missing(fields, unit, "No quarterly change has a positive base.")
    text = display(value, unit).lstrip("+")
    return Analytic(
        **fields,  # type: ignore[arg-type]
        value=value,
        unit=unit,
        display=text,
        formula=f"median of |quarter-on-quarter change| over {len(window) - 1} changes",
        inputs=[_point_input(key, p) for p in window],
        reading=(
            f"A typical quarter-on-quarter move in {_lower(label)} over the last "
            f"{len(window) - 1} quarters is {text} (the median, ignoring direction; a flow's "
            "quarters include any seasonality)."
        ),
    )


# Per computed test

# The id, provider, claim and period of one test's analytics, given its kind and label.
Fields = Callable[[str, str], dict[str, object]]


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


def history_moves(history: Sequence[HistoryPoint]) -> list[float]:
    """The left side's values across a history, oldest first, a repeated value dropped (a
    10-Q leaves a fiscal-year test where the 10-K put it)."""
    values: list[float] = []
    for point in history:
        if point.left is None:
            continue
        if not values or point.left != values[-1]:
            values.append(point.left)
    return values


def history_record(history: Sequence[HistoryPoint]) -> tuple[int, int, int, str]:
    """(held, computed, longest run held, date of the last flip) across a history."""
    computed = [p for p in history if p.outcome != "cannot_compute"]
    held = sum(1 for p in computed if p.outcome == "holds")
    longest = run = 0
    for point in computed:
        run = run + 1 if point.outcome == "holds" else 0
        longest = max(longest, run)
    flips = [p.filed for p in computed if p.flipped]
    return held, len(computed), longest, flips[-1] if flips else ""


def computed_test_analytics(
    claim_id: str, test: ClaimTest, computed: ComputedTest, measures: Measures | None
) -> list[Analytic]:
    """Headroom, its size in typical moves, the flip value, needed against actual for a
    failing growth test, and the test's record across its history."""
    out: list[Analytic] = []
    singles = _single_tests(computed)
    rooms = [(part, _room(part)) for part in singles]
    known = [(part, room) for part, room in rooms if room is not None]

    def fields(kind: str, label: str) -> dict[str, object]:
        return {
            "id": f"an:{claim_id}:{kind}",
            "provider": PROVIDER,
            "data_origin": ORIGIN,
            "kind": kind,
            "label": label,
            "claim_ids": [claim_id],
            "measure": test.left.subject if not test.left.axis else "",
            "period": computed.bound,
        }

    test_input = AnalyticInput(
        ref_kind="computed_test",
        id=f"test:{claim_id}",
        label=computed.canonical,
        display=computed.outcome_label,
    )
    unit = _test_unit(singles[0])
    if not known:
        why = computed.reason or "The test could not be computed."
        out.append(_missing(fields("headroom", "Headroom of the test"), unit, why))
    else:
        part, room = min(known, key=lambda item: item[1])
        assert part.left is not None and part.right is not None
        text = display(room, unit, signed=True) if unit != "count" else f"{room:+g}"
        tightest = " (the tightest of its periods)" if len(singles) > 1 else ""
        out.append(
            Analytic(
                **fields("headroom", "Headroom of the test"),  # type: ignore[arg-type]
                value=room,
                unit=unit,
                display=text,
                formula=(
                    f"{part.left.display} {MINUS} {part.right.display}"
                    if part.comparison in (">", ">=")
                    else f"{part.right.display} {MINUS} {part.left.display}"
                ),
                inputs=[
                    test_input,
                    AnalyticInput(
                        ref_kind="computed_test",
                        id=f"test:{claim_id}",
                        label=part.left.label,
                        value=part.left.value,
                        display=part.left.display,
                    ),
                    AnalyticInput(
                        ref_kind="computed_test",
                        id=f"test:{claim_id}",
                        label=part.right.label,
                        value=part.right.value,
                        display=part.right.display,
                    ),
                ],
                reading=(
                    f"The test {'holds' if room >= 0 else 'fails'}{tightest} with {text} of "
                    f"room: {part.left.display} against {part.right.display}."
                    if room
                    else f"The test sits exactly on its line: {part.left.display}."
                ),
            )
        )
        out.append(_room_in_moves(fields, room, unit, part, computed, test_input))
        flip = _flip(fields, test, part, computed, test_input)
        if flip is not None:
            out.append(flip)
        needed = _needed(fields, test, part, computed, test_input)
        if needed is not None:
            out.append(needed)
    out.append(_record(fields, computed, test_input))
    return out


def _room_in_moves(
    fields: Fields,
    room: float,
    unit: AnalyticUnit,
    part: ComputedTest,
    computed: ComputedTest,
    test_input: AnalyticInput,
) -> Analytic:
    base = fields("headroom_moves", "Headroom in typical moves of the left side")
    values = history_moves(computed.history)
    if len(values) - 1 < rules.SHORT_WINDOW - 1:
        return _missing(
            base,
            "multiple",
            "Too few changes in the test's history to say what a typical move is "
            f"({max(len(values) - 1, 0)}; at least {rules.SHORT_WINDOW - 1} are needed).",
        )
    moves = [abs(b - a) for a, b in zip(values, values[1:], strict=False)]
    typical = statistics.median(moves)
    if typical == 0:
        return _missing(base, "multiple", "The left side did not move across the history.")
    value = room / typical
    move_text = (
        display(typical, "points").lstrip("+") if unit == "points" else _side_display(typical, part)
    )
    return Analytic(
        **base,  # type: ignore[arg-type]
        value=value,
        unit="multiple",
        display=f"{value:.2f}x",
        formula=f"{display(room, unit, signed=True)} ÷ {move_text}",
        inputs=[test_input],
        reading=(
            f"The room is {abs(value):.2f}x the left side's typical move between filings "
            f"({move_text}, the median over {len(moves)} changes in the test's history)"
            + (": one typical move against it would flip it." if abs(value) < 1 else ".")
        ),
    )


def _flip(
    fields: Fields,
    test: ClaimTest,
    part: ComputedTest,
    computed: ComputedTest,
    test_input: AnalyticInput,
) -> Analytic | None:
    """The value of the measure at which the outcome flips."""
    assert part.left is not None and part.right is not None
    if test.form == "streak" or part.right.value is None or part.left.value is None:
        return None
    if test.form == "growth_threshold" and len(part.operands) >= 2 and isinstance(
        test.right, Number
    ):
        current, base = part.operands[0], part.operands[1]
        if base.value is None or current.value is None:
            return None
        level = base.value * (1 + part.right.value / 100)
        unit: AnalyticUnit = "USD" if current.unit == "USD" else "USD_per_share"
        if current.unit not in ("USD", "USD_per_share"):
            return None
        shown = display(level, unit)
        return Analytic(
            **fields("flip", "Value at which the outcome flips"),
            value=level,
            unit=unit,
            display=shown,
            formula=f"{base.display} × (1 + {part.right.display})",
            inputs=[
                test_input,
                AnalyticInput(
                    ref_kind="computed_test",
                    id=f"test:{test_input.id.removeprefix('test:')}",
                    label=base.label,
                    value=base.value,
                    display=base.display,
                ),
            ],
            reading=(
                f"The outcome flips at {shown} for {current.label.split(',')[0].lower()} "
                f"({base.display} grown by {part.right.display}); it was {current.display}."
            ),
        )
    shown = _side_display(part.right.value, part)
    other = "a constant" if isinstance(test.right, Number) else part.right.label
    return Analytic(
        **fields("flip", "Value at which the outcome flips"),
        value=part.right.value,
        unit="percent" if part.left.unit == "percent" else _test_unit(part),
        display=shown,
        formula=f"{part.left.term} {part.comparison} {part.right.display}",
        inputs=[test_input],
        reading=(
            f"The outcome flips when {part.left.label.lower()} crosses {shown} ({other}); "
            f"it is {part.left.display}."
        ),
    )


def _needed(
    fields: Fields,
    test: ClaimTest,
    part: ComputedTest,
    computed: ComputedTest,
    test_input: AnalyticInput,
) -> Analytic | None:
    """For a failing growth test: the growth and the level needed against those reached."""
    if computed.outcome != "fails" or test.form != "growth_threshold":
        return None
    if part.outcome != "fails" or len(part.operands) < 2 or part.right is None:
        return None
    current, base = part.operands[0], part.operands[1]
    if current.value is None or base.value is None or part.right.value is None:
        return None
    if current.unit != "USD" or part.left is None or part.left.value is None:
        return None
    level = base.value * (1 + part.right.value / 100)
    gap = level - current.value
    return Analytic(
        **fields("needed", "Needed against actual"),
        value=gap,
        unit="USD",
        display=usd_text(gap),
        formula=f"{base.display} × (1 + {part.right.display}) {MINUS} {current.display}",
        inputs=[test_input],
        reading=(
            f"To hold it needed growth of {part.right.display} to {usd_text(level)}; it grew "
            f"{part.left.display} to {current.display}, {usd_text(gap)} short."
        ),
    )


def _record(fields: object, computed: ComputedTest, test_input: AnalyticInput) -> Analytic:
    base = fields("history", "How often the test held across its history")
    held, total, longest, last_flip = history_record(computed.history)
    if total == 0:
        return _missing(base, "percent", computed.history_note or "The test has no history.")
    share = held / total * 100
    flip = f"; it last flipped as of the filing of {last_flip}" if last_flip else "; it never flipped"
    return Analytic(
        **base,  # type: ignore[arg-type]
        value=share,
        unit="percent",
        display=f"{held} of {total}",
        formula=f"{held} ÷ {total}",
        inputs=[test_input],
        reading=(
            f"The test held as of {held} of the {total} filing dates it could be computed at "
            f"({percent_text(share)}); its longest run holding was {longest}{flip}."
        ),
    )


# Bridges and earnings quality


def _ttm(measures: Measures, key: str, end: date) -> Outcome:
    return measures.outcome(key, measures.slot("ttm", end))


def _newest_quarter(measures: Measures) -> date | None:
    series = measures.series("quarter", "revenue")
    return max(series) if series else None


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


def _quarter_days(value: PeriodValue | None) -> int:
    if value is None or value.start is None:
        return rules.DEFAULT_QUARTER_DAYS
    return (value.end - value.start).days + 1


def _eq_fields(
    what: str, label: str, period: str, claim_ids: Sequence[str], measure: str = ""
) -> dict[str, object]:
    return {
        "id": f"an:eq:{what}",
        "provider": PROVIDER,
        "data_origin": ORIGIN,
        "kind": "earnings_quality",
        "label": label,
        "claim_ids": list(claim_ids),
        "measure": measure,
        "period": period,
    }


def _bridge_fields(
    what: str, label: str, period: str, claim_ids: Sequence[str], measure: str = ""
) -> dict[str, object]:
    return {
        "id": f"an:bridge:{what}",
        "provider": PROVIDER,
        "data_origin": ORIGIN,
        "kind": "bridge",
        "label": label,
        "claim_ids": list(claim_ids),
        "measure": measure,
        "period": period,
    }


# Which claims each bridge or signal bears on: those relevant to any of these measures.
BEARS_ON: dict[str, tuple[str, ...]] = {
    "fcf": ("free_cash_flow", "operating_cash_flow", "capex", "fcf_margin", "capex_ratio"),
    "ni_to_ocf": ("operating_cash_flow", "net_income", "free_cash_flow", "net_margin", "sbc"),
    "op_margin": ("operating_margin", "gross_margin", "rnd_ratio", "operating_income"),
    "segments": ("revenue", "revenue_yoy"),
    "cash_conversion": ("operating_cash_flow", "net_income", "free_cash_flow", "eps_diluted"),
    "accrual_share": ("operating_cash_flow", "net_income", "eps_diluted", "net_margin"),
    "dso": ("receivables", "revenue"),
    "dio": ("inventory", "gross_margin", "cost_of_revenue"),
    "sbc": ("sbc", "sbc_ratio", "operating_margin", "free_cash_flow", "net_income"),
    "capex": ("capex", "capex_ratio", "free_cash_flow", "fcf_margin"),
    "deferred_revenue": ("deferred_revenue", "revenue", "deferred_revenue_current"),
    "dupont": ("net_income", "net_margin", "equity", "total_assets", "eps_diluted"),
}


def bears_on(topic: str, measures_by_claim: dict[str, list[str]]) -> list[str]:
    """The claims whose measures include any of :data:`BEARS_ON` for ``topic``."""
    keys = set(BEARS_ON[topic])
    return [claim for claim, measures in measures_by_claim.items() if keys & set(measures)]


def _ttm_values(
    measures: Measures, end: date, keys: Sequence[str]
) -> tuple[dict[str, float], list[PeriodValue], str]:
    values: dict[str, float] = {}
    used: list[PeriodValue] = []
    for key in keys:
        outcome = _ttm(measures, key, end)
        if outcome.value is None:
            return values, used, outcome.note or f"{_label(key)} over four quarters is missing."
        values[key] = outcome.value
        used += outcome.used
    return values, used, ""


def bridge_analytics(
    measures: Measures, end: date, period: str, claims: dict[str, list[str]]
) -> list[Analytic]:
    """Free cash flow, net income to operating cash flow, and the operating-margin split."""
    out: list[Analytic] = []
    ttm = f"four quarters to {period}"
    # Free cash flow from operating cash flow and capex.
    fields = _bridge_fields(
        "fcf",
        "Free cash flow: operating cash flow less capital expenditure, four quarters",
        ttm,
        bears_on("fcf", claims),
        "free_cash_flow",
    )
    values, used, why = _ttm_values(measures, end, ("operating_cash_flow", "capex", "revenue"))
    if why:
        out.append(_missing(fields, "USD", why))
    else:
        ocf, capex, revenue = values["operating_cash_flow"], values["capex"], values["revenue"]
        fcf = ocf - capex
        margin = fcf / revenue * 100 if revenue > 0 else None
        tail = f", {percent_text(margin)} of revenue" if margin is not None else ""
        out.append(
            Analytic(
                **fields,  # type: ignore[arg-type]
                value=fcf,
                unit="USD",
                display=usd_text(fcf),
                formula=f"{usd_text(ocf)} {MINUS} {usd_text(capex)}",
                inputs=_fact_inputs(used),
                reading=(
                    f"Over the four quarters to {period}, operating cash flow of {usd_text(ocf)} "
                    f"less capital expenditure of {usd_text(capex)} left free cash flow of "
                    f"{usd_text(fcf)}{tail}."
                ),
            )
        )
    # Net income to operating cash flow.
    fields = _bridge_fields(
        "ni_to_ocf",
        "Net income to operating cash flow, four quarters",
        ttm,
        bears_on("ni_to_ocf", claims),
        "operating_cash_flow",
    )
    values, used, why = _ttm_values(measures, end, ("net_income", "operating_cash_flow"))
    if why:
        out.append(_missing(fields, "USD", why))
    else:
        income, ocf = values["net_income"], values["operating_cash_flow"]
        gap = ocf - income
        parts: list[str] = []
        rest = gap
        formula = f"{usd_text(ocf)} {MINUS} {usd_text(income)}"
        for key, words in (("sbc", "stock-based compensation"), ("d_and_a", "depreciation and amortization")):
            part = _ttm(measures, key, end)
            if part.value is not None:
                used += part.used
                rest -= part.value
                parts.append(f"{words} {usd_text(part.value)}")
        split = (
            f": non-cash charges added back ({', '.join(parts)}) and {usd_text(rest)} of working "
            "capital and other items"
            if parts
            else " (the facts do not tag its non-cash parts)"
        )
        out.append(
            Analytic(
                **fields,  # type: ignore[arg-type]
                value=gap,
                unit="USD",
                display=usd_text(gap),
                formula=formula,
                inputs=_fact_inputs(used),
                reading=(
                    f"Over the four quarters to {period}, operating cash flow of {usd_text(ocf)} "
                    f"was {usd_text(abs(gap))} {'above' if gap >= 0 else 'below'} net income of "
                    f"{usd_text(income)}{split}."
                ),
            )
        )
    out.append(_margin_split(measures, end, claims))
    return out


def _margin_split(measures: Measures, end: date, claims: dict[str, list[str]]) -> Analytic:
    """The change in operating margin on a year earlier, split into gross margin, R&D and the
    rest of operating expenses (each as a share of revenue)."""
    slot = measures.slot("quarter", end)
    fields = _bridge_fields(
        "op_margin",
        "Operating margin change on a year earlier, split into its parts",
        slot.label,
        bears_on("op_margin", claims),
        "operating_margin",
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
    revenue_now, revenue_then = shares["revenue"]
    if revenue_now <= 0 or revenue_then <= 0:
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
    pieces = [f"gross margin {display(d_gm, 'points')}"]
    formula = f"{display(d_gm, 'points')} {MINUS} ({display(d_other, 'points')})"
    if d_rnd is not None:
        pieces.append(f"R&D {display(-d_rnd, 'points')}")
        formula += f" {MINUS} ({display(d_rnd, 'points')})"
    pieces.append(
        ("other operating expenses " if d_rnd is not None else "operating expenses ")
        + display(-d_other, "points")
    )
    return Analytic(
        **fields,  # type: ignore[arg-type]
        value=d_om,
        unit="points",
        display=display(d_om, "points"),
        formula=formula,
        inputs=_fact_inputs(used),
        reading=(
            f"Operating margin moved {display(d_om, 'points')} on {earlier.label} "
            f"({percent_text(om[1])} to {percent_text(om[0])}); by part, as a share of revenue: "
            + "; ".join(pieces)
            + " (a rise in an expense share lowers the margin)."
        ),
    )


def earnings_quality(
    measures: Measures, end: date, period: str, claims: dict[str, list[str]]
) -> list[Analytic]:
    """Cash conversion, accruals, receivable and inventory days, SBC and capex against
    revenue, deferred revenue and a DuPont split of return on equity."""
    out: list[Analytic] = []
    ttm = f"four quarters to {period}"
    values, used, why = _ttm_values(measures, end, ("net_income", "operating_cash_flow"))
    conversion = _eq_fields(
        "cash_conversion",
        "Cash conversion: operating cash flow ÷ net income, four quarters",
        ttm,
        bears_on("cash_conversion", claims),
    )
    accrual = _eq_fields(
        "accrual_share",
        "Accruals as a share of net income (net income less operating cash flow, ÷ net "
        "income; not the balance-sheet accrual ratio)",
        ttm,
        bears_on("accrual_share", claims),
    )
    if why:
        out += [_missing(conversion, "multiple", why), _missing(accrual, "percent", why)]
    elif values["net_income"] <= 0:
        why = "Not meaningful: net income over the four quarters is not positive."
        out += [_missing(conversion, "multiple", why), _missing(accrual, "percent", why)]
    else:
        income, ocf = values["net_income"], values["operating_cash_flow"]
        ratio = ocf / income
        share = (income - ocf) / income * 100
        inputs = _fact_inputs(used)
        out.append(
            Analytic(
                **conversion,  # type: ignore[arg-type]
                value=ratio,
                unit="multiple",
                display=f"{ratio:.2f}x",
                formula=f"{usd_text(ocf)} ÷ {usd_text(income)}",
                inputs=inputs,
                reading=(
                    f"Each dollar of net income came with {ratio:.2f} dollars of operating cash "
                    f"flow over the four quarters to {period} ({usd_text(ocf)} against "
                    f"{usd_text(income)})."
                ),
            )
        )
        out.append(
            Analytic(
                **accrual,  # type: ignore[arg-type]
                value=share,
                unit="percent",
                display=percent_text(share),
                formula=f"({usd_text(income)} {MINUS} {usd_text(ocf)}) ÷ {usd_text(income)}",
                inputs=inputs,
                reading=(
                    f"{percent_text(abs(share))} of net income "
                    + (
                        "was not matched by operating cash in the period (accruals)"
                        if share > 0
                        else "is the amount by which operating cash flow exceeded it"
                    )
                    + f", over the four quarters to {period}."
                ),
            )
        )
    out.append(_days(measures, end, "dso", "receivables", "revenue", claims))
    out.append(_days(measures, end, "dio", "inventory", "cost_of_revenue", claims))
    for what, key in (("sbc", "sbc_ratio"), ("capex", "capex_ratio")):
        fields = _eq_fields(
            f"{what}_ratio", f"{_label(key)}, four quarters", ttm, bears_on(what, claims), key
        )
        outcome = _ttm(measures, key, end)
        if outcome.value is None:
            out.append(_missing(fields, "percent", outcome.note or "Not in the facts."))
            continue
        out.append(
            Analytic(
                **fields,  # type: ignore[arg-type]
                value=outcome.value,
                unit="percent",
                display=percent_text(outcome.value),
                formula=outcome.formula,
                inputs=_fact_inputs(outcome.used),
                reading=(
                    f"{_label(key)} was {percent_text(outcome.value)} over the four quarters "
                    f"to {period}."
                ),
            )
        )
    out.append(_deferred(measures, end, claims))
    out += _dupont(measures, end, period, claims)
    return out


def _days(
    measures: Measures,
    end: date,
    what: str,
    balance_key: str,
    flow_key: str,
    claims: dict[str, list[str]],
) -> Analytic:
    """Days of a quarter's flow a balance stands for at the quarter's end, and a year before."""
    slot = measures.slot("quarter", end)
    name = "Receivable days (DSO)" if what == "dso" else "Inventory days (DIO)"
    flow_words = "revenue" if flow_key == "revenue" else "cost of revenue"
    fields = _eq_fields(
        what,
        f"{name}: {_lower(_label(balance_key))} ÷ the quarter's {flow_words} × its days",
        slot.label,
        bears_on(what, claims),
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
        revenue = measures.series("quarter", "revenue").get(quarter.end)
        days = _quarter_days(revenue)
        return balance[0] / flow.value * days, balance[0], flow.value, days, [balance[1], *flow.used]

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
        reading += f", against {then[0]:.1f} days a year before ({earlier.label})"
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


def _deferred(measures: Measures, end: date, claims: dict[str, list[str]]) -> Analytic:
    key = "deferred_revenue"
    slot = measures.slot("quarter", end)
    fields = _eq_fields(
        "deferred_revenue",
        "Deferred revenue at the quarter's end, and its change on a year earlier",
        slot.label,
        bears_on("deferred_revenue", claims),
        key,
    )
    now = _balance(measures, key, end)
    if now is None:
        return _missing(fields, "USD", "The facts tag no deferred revenue at this quarter's end.")
    earlier = measures.year_before(slot, "revenue")
    then = _balance(measures, key, earlier.end) if earlier is not None else None
    reading = f"Deferred revenue was {usd_text(now[0])} at the end of {slot.label}"
    used = [now[1]]
    if then is not None and then[0] > 0:
        growth = (now[0] - then[0]) / then[0] * 100
        reading += f", {percent_text(growth, signed=True)} on a year earlier ({usd_text(then[0])})"
        used.append(then[1])
    return Analytic(
        **fields,  # type: ignore[arg-type]
        value=now[0],
        unit="USD",
        display=usd_text(now[0]),
        formula=measures.outcome(key, measures.slot("instant", now[1].end)).formula,
        inputs=_fact_inputs(used),
        reading=reading + ".",
    )


def _dupont(
    measures: Measures, end: date, period: str, claims: dict[str, list[str]]
) -> list[Analytic]:
    """Return on equity over four quarters = net margin × asset turnover × equity multiplier,
    on balances averaged over the quarter's end and a year before it."""
    ttm = f"four quarters to {period}"
    names = {
        "roe": "Return on average equity, four quarters",
        "dupont_margin": "DuPont: net margin, four quarters",
        "asset_turnover": "DuPont: asset turnover (revenue ÷ average total assets)",
        "equity_multiplier": "DuPont: equity multiplier (average assets ÷ average equity)",
    }
    claim_ids = bears_on("dupont", claims)
    fields = {what: _eq_fields(what, label, ttm, claim_ids) for what, label in names.items()}
    units: dict[str, AnalyticUnit] = {
        "roe": "percent",
        "dupont_margin": "percent",
        "asset_turnover": "multiple",
        "equity_multiplier": "multiple",
    }

    def missing(why: str) -> list[Analytic]:
        return [_missing(fields[what], units[what], why) for what in names]

    values, used, why = _ttm_values(measures, end, ("net_income", "revenue"))
    if why:
        return missing(why)
    earlier = measures.year_before(measures.slot("quarter", end), "revenue")
    balances: dict[str, list[float]] = {}
    for key in ("total_assets", "equity"):
        found = [_balance(measures, key, end)]
        found.append(_balance(measures, key, earlier.end) if earlier is not None else None)
        if any(item is None for item in found):
            return missing(f"{_label(key)} is not reported at both ends of the four quarters.")
        balances[key] = [item[0] for item in found if item is not None]
        used += [item[1] for item in found if item is not None]
    assets = sum(balances["total_assets"]) / 2
    equity = sum(balances["equity"]) / 2
    income, revenue = values["net_income"], values["revenue"]
    if equity <= 0 or revenue <= 0 or assets <= 0:
        return missing("Not meaningful: average equity, assets or revenue is not positive.")
    margin = income / revenue * 100
    turnover = revenue / assets
    multiplier = assets / equity
    roe = margin * turnover * multiplier
    inputs = _fact_inputs(used)
    a, e = usd_text(assets), usd_text(equity)
    return [
        Analytic(
            **fields["roe"],  # type: ignore[arg-type]
            value=roe,
            unit="percent",
            display=percent_text(roe),
            formula=f"{percent_text(margin)} × {turnover:.2f}x × {multiplier:.2f}x",
            inputs=inputs,
            reading=(
                f"Return on average equity was {percent_text(roe)} over the four quarters to "
                f"{period}: a net margin of {percent_text(margin)}, times asset turnover of "
                f"{turnover:.2f}x, times an equity multiplier of {multiplier:.2f}x."
            ),
        ),
        Analytic(
            **fields["dupont_margin"],  # type: ignore[arg-type]
            value=margin,
            unit="percent",
            display=percent_text(margin),
            formula=f"{usd_text(income)} ÷ {usd_text(revenue)}",
            inputs=inputs,
            reading=f"Net income was {percent_text(margin)} of revenue over the four quarters.",
        ),
        Analytic(
            **fields["asset_turnover"],  # type: ignore[arg-type]
            value=turnover,
            unit="multiple",
            display=f"{turnover:.2f}x",
            formula=f"{usd_text(revenue)} ÷ {a}",
            inputs=inputs,
            reading=f"Revenue was {turnover:.2f}x average total assets of {a}.",
        ),
        Analytic(
            **fields["equity_multiplier"],  # type: ignore[arg-type]
            value=multiplier,
            unit="multiple",
            display=f"{multiplier:.2f}x",
            formula=f"{a} ÷ {e}",
            inputs=inputs,
            reading=f"Average total assets of {a} were {multiplier:.2f}x average equity of {e}.",
        ),
    ]


# Segment contribution, from the tagged breakdowns the run already read


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_") or "part"


def _length(value: BreakdownValue) -> int | None:
    if value.period_start is None:
        return None
    start, end = date.fromisoformat(value.period_start), date.fromisoformat(value.period_end)
    return (end - start).days + 1


def _year_apart(newer: str, older: str) -> bool:
    days = (date.fromisoformat(newer) - date.fromisoformat(older)).days
    return YEAR_DAYS[0] <= days <= YEAR_DAYS[1]


def _columns(item: Breakdown) -> tuple[BreakdownValue, BreakdownValue] | None:
    """The newest total and the total of the same length a year before it."""
    totals = sorted(item.total, key=lambda v: v.period_end, reverse=True)
    if not totals:
        return None
    newest = totals[0]
    length = _length(newest)
    for older in totals[1:]:
        if _length(older) == length and _year_apart(newest.period_end, older.period_end):
            return newest, older
    return None


def _cell(values: Sequence[BreakdownValue], like: BreakdownValue) -> BreakdownValue | None:
    return next(
        (
            v
            for v in values
            if v.period_end == like.period_end and v.period_start == like.period_start
        ),
        None,
    )


def segment_contributions(
    reports: Sequence[BreakdownReport], claims: dict[str, list[str]], parts: dict[str, list[str]]
) -> list[Analytic]:
    """Each tagged part's contribution to total growth, in percentage points, from the newest
    breakdown of revenue by segment, product or geography the run read.

    A part's contribution is (its value now − its value a year before) ÷ the total a year
    before; the contributions add up to the total's growth when the parts add up to it.
    ``parts`` maps a claim id to the part names it names, so a part is tied to the claims
    that name it (and every part to the claims about revenue).
    """
    out: list[Analytic] = []
    revenue_claims = bears_on("segments", claims)
    for report in reports[:1]:
        for item in report.breakdowns:
            if item.id not in SEGMENT_BREAKDOWNS:
                continue
            columns = _columns(item)
            if columns is None:
                continue
            newest, older = columns
            if older.value <= 0:
                continue
            total_growth = (newest.value - older.value) / older.value * 100
            axis = "geography" if "geography" in item.id else "segment"
            for row in item.rows:
                now, then = _cell(row.values, newest), _cell(row.values, older)
                if now is None or then is None:
                    continue
                contribution = (now.value - then.value) / older.value * 100
                named = [
                    claim
                    for claim, names in parts.items()
                    if any(name.casefold() == row.label.casefold() for name in names)
                ]
                claim_ids = list(dict.fromkeys([*named, *revenue_claims]))
                shown = display(contribution, "points")
                out.append(
                    Analytic(
                        id=f"an:bridge:{axis}:{_slug(row.label)}",
                        provider=PROVIDER,
                        data_origin=BREAKDOWN_ORIGIN,
                        kind="bridge",
                        label=f"{row.label}: contribution to {item.title.lower()} growth",
                        claim_ids=claim_ids,
                        measure=f'revenue({axis} "{row.label}")',
                        period=f"{newest.period_start} to {newest.period_end}",
                        value=contribution,
                        unit="points",
                        display=shown,
                        formula=(
                            f"({now.display} {MINUS} {then.display}) ÷ {older.display}"
                        ),
                        inputs=[
                            AnalyticInput(
                                ref_kind="fact",
                                id=f"{report.filing.accession}:{row.member}:{v.period_end}",
                                label=f"{row.label}, {v.period_start} to {v.period_end}",
                                value=v.value,
                                display=v.display,
                                accession=report.filing.accession,
                                form=report.filing.form,
                                filed=report.filing.filed_date,
                            )
                            for v in (now, then)
                        ],
                        reading=(
                            f"{row.label} added {shown} to {item.title.lower()} growth of "
                            f"{percent_text(total_growth, signed=True)} ({then.display} to "
                            f"{now.display}, as the {report.filing.form} of "
                            f"{report.filing.filed_date} tags it)."
                        ),
                    )
                )
            if out:
                return out
    return out


# The provider


class FactsProvider:
    """Analytics from the run's dated XBRL facts and the breakdowns it already read."""

    name = PROVIDER

    def provide(self, request: AnalyticsRequest) -> list[Analytic]:
        """Every analytic of the four families (see the module docstring)."""
        if request.book is None:
            why = f" ({request.error})" if request.error else ""
            return [
                Analytic(
                    id="an:facts",
                    kind="none",
                    label="Analytics from the company's facts",
                    available=False,
                    unit="count",
                    note=NO_FACTS.format(why=why),
                )
            ]
        measures = Measures(request.book, request.calendar)
        out: list[Analytic] = []
        by_measure: dict[str, list[str]] = {}
        for claim_id, keys in request.measures.items():
            for key in keys:
                if key in METRICS:
                    by_measure.setdefault(key, []).append(claim_id)
        for key, claim_ids in by_measure.items():
            out += measure_analytics(measures, key, claim_ids)
        for claim_id, (test, computed) in request.tests.items():
            out += computed_test_analytics(claim_id, test, computed, measures)
        end = _newest_quarter(measures)
        if end is not None:
            label = measures.slot("quarter", end).label
            out += bridge_analytics(measures, end, label, request.measures)
            out += earnings_quality(measures, end, label, request.measures)
        parts = {
            claim_id: [
                key.split('"')[1] for key in keys if '"' in key
            ]
            for claim_id, keys in request.measures.items()
        }
        out += segment_contributions(request.reports, request.measures, parts)
        return out
