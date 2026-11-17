"""Breakdowns of one filing's tagged facts: revenue by segment, product, geography; customers.

Pure: :func:`build_report` takes the :class:`~app.core.breakdown_models.TaggedFacts`
of one filing and returns a :class:`~app.core.breakdown_models.BreakdownReport`.
The SEC company-facts API carries no dimensional facts; a filing's own inline
XBRL does, and these are what theses are about. The rules:

- **Which facts.** A breakdown takes the facts of one concept whose context has
  the breakdown's axis and nothing else, except the qualifiers its
  :class:`BreakdownSpec` names (segment revenue is often tagged also with
  ``srt:ConsolidationItemsAxis`` = ``us-gaap:OperatingSegmentsMember``, which
  says the same thing). A context with any other dimension, or a typed one, is a
  different breakdown (product revenue within one segment, say) and is left out.
  Where the same member and period are tagged both plainly and with a qualifier,
  the plain fact wins.
- **Which concept.** Revenue is tagged with different concepts by different
  companies (:data:`REVENUE_CONCEPTS`); for each breakdown the concept with the
  most member-period values on the axis is used, and the breakdown records it.
- **Which periods.** Every value is placed by its context's dates, never by the
  filing's fiscal-year fields. A duration's kind follows from its length in
  days (:data:`PERIOD_DAYS`: a quarter is 12 to 17 weeks, so retailers' 12- and
  16-week quarters count). An annual report shows full-year durations; a
  quarterly report shows the quarter alone, or, when only year-to-date values
  are tagged, those, and says so. The two are never mixed in one breakdown.
- **Changes.** Each value's change is from the same kind of period ending about
  one year earlier (within :data:`YEAR_MATCH_DAYS`), computed here and written
  out as a formula. Concentration percentages get no change: a member such as
  "Customer One" is a position in the filing's list, not shown to be the same
  customer each year.
- **Totals.** The concept tagged with no dimension is the total. The members'
  sum is checked against it period by period, within the rounding the tags
  declare (half a unit of ``decimals`` per value). Real filings tag more than a
  flat list, and each shape is named in a note: members that are sums of other
  members (NVIDIA's Data Center is Compute plus Networking; Tesla nests three
  levels) are counted once; two splits of the same total on one axis
  (Microsoft's and Amazon's products against services, and their product
  lines) are recognised; segments whose revenue includes sales to each other
  are reconciled with the eliminations and corporate amounts tagged on
  ``srt:ConsolidationItemsAxis`` alone (Coca-Cola, JPMorgan). Anything else is
  reported as not adding up, with the numbers.
- **Labels** come from the member's tag name (:func:`member_label`), not from the
  company's presentation, and every breakdown says so.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import combinations

from app.core.breakdown_models import (
    Breakdown,
    BreakdownReport,
    BreakdownRow,
    BreakdownValue,
    FilingInfo,
    PeriodColumn,
    TaggedFact,
    TaggedFacts,
    XbrlContext,
)
from app.core.metrics import MINUS, YEAR_MATCH_DAYS, millions_text, percent_text
from app.core.models import Company

# Concepts and axes

REVENUE_CONCEPTS = (
    "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    "us-gaap:Revenues",
    "us-gaap:SalesRevenueNet",
    "us-gaap:RevenueFromContractWithCustomerIncludingAssessedTax",
    "us-gaap:RevenuesNetOfInterestExpense",
    "us-gaap:SalesRevenueGoodsNet",
    "us-gaap:SalesRevenueServicesNet",
)
CONCENTRATION_CONCEPTS = (
    "us-gaap:ConcentrationRiskPercentage1",
    "us-gaap:ConcentrationRiskPercentage",
)
SEGMENT_AXIS = "us-gaap:StatementBusinessSegmentsAxis"
PRODUCT_AXIS = "srt:ProductOrServiceAxis"
GEOGRAPHY_AXIS = "srt:StatementGeographicalAxis"
CUSTOMER_AXIS = "srt:MajorCustomersAxis"
BENCHMARK_AXIS = "us-gaap:ConcentrationRiskByBenchmarkAxis"
RISK_TYPE_AXIS = "us-gaap:ConcentrationRiskByTypeAxis"
CONSOLIDATION_AXIS = "srt:ConsolidationItemsAxis"
OPERATING_SEGMENTS = frozenset({"us-gaap:OperatingSegmentsMember"})
CUSTOMER_RISK = frozenset({"us-gaap:CustomerConcentrationRiskMember"})
# Benchmark members that mean "share of revenue" and "share of accounts receivable".
REVENUE_BENCHMARKS = frozenset(
    {
        "us-gaap:RevenueFromContractWithCustomerMember",
        "us-gaap:RevenueBenchmarkMember",
        "us-gaap:SalesRevenueNetMember",
        "us-gaap:SalesRevenueGoodsNetMember",
        "us-gaap:SalesRevenueServicesNetMember",
        "us-gaap:RevenuesMember",
    }
)
RECEIVABLE_BENCHMARKS = frozenset(
    {"us-gaap:AccountsReceivableMember", "us-gaap:AccountsReceivableBenchmarkMember"}
)

# Sizes

MAX_ROWS = 25  # members shown per breakdown, the largest in the newest period first
MAX_PERIODS = 4  # columns shown; an annual report tags three fiscal years
MAX_NESTED_SEARCH = 16  # members searched for the ones a nested member is made of
MAX_REASONS = 5  # distinct reasons listed for facts that could not be read
MAX_PROBLEMS = 5

# Periods

ANNUAL = "annual"
QUARTER = "quarter"
YEAR_TO_DATE = "year_to_date"
INSTANT = "instant"
PURE = "pure"  # the unit of a fraction, such as a share of revenue
# A duration's kind by its length in days, inclusive. A quarter is 12 to 17 weeks: retailers
# report 12- and 16-week quarters (Costco's first three are 12 weeks), and a 53-week year adds
# one. Year to date is anything between a quarter and a year (Costco's 24 and 36 weeks are
# 168 and 252 days, outside the six- and nine-month bands of core/facts.py). A fiscal year is
# 52 or 53 weeks.
PERIOD_DAYS: tuple[tuple[str, int, int], ...] = (
    (QUARTER, 80, 125),
    (YEAR_TO_DATE, 126, 300),
    (ANNUAL, 350, 380),
)
KIND_WORDS = {
    ANNUAL: "fiscal year",
    QUARTER: "quarter",
    YEAR_TO_DATE: "year to date",
    INSTANT: "instant",
}

# Wording

LABEL_NOTE = (
    'Labels are derived from each member\'s tag name (the "Member" suffix dropped and the words '
    "split); they are not the company's own labels."
)
PLACEMENT_NOTE = (
    "Every value is placed by its context's start and end dates; the filing's fiscal-year "
    "fields are not read."
)
NO_CHANGE_CONCENTRATION = (
    "Not computed: a customer member names a position in the filing's list (such as Customer "
    "One), which the tags do not show to be the same customer in each period."
)
NO_COMPARABLE = "No value for the same period one year earlier is tagged."
# Lower-cased inside a label. "In" is not among them: "LinkedIn" is a name, not "Linked in".
CONNECTORS = frozenset({"and", "or", "of", "the", "for"})
WORD = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]+|[A-Z]?[a-z]+|\d+")


@dataclass(frozen=True)
class BreakdownSpec:
    """What one breakdown takes from the tagged facts.

    ``required`` axes must be present with one of the members given;
    ``allowed`` axes may be present, with one of the members given, as
    qualifiers that say nothing new. Facts tagged with ``reconciling_axis`` alone
    (eliminations, corporate) are not members but may close the gap between the
    members and the total. An axis in ``row_axes`` makes the row a
    separate, labelled row (a customer's share "within one segment"). A context
    with any other axis is left out: a geography or a product changes what the
    share is a share of (NVIDIA tags "76% of Data Center revenue from
    Taiwan-headquartered customers" with the same concept and benchmark).
    """

    id: str
    title: str
    axis: str
    concepts: tuple[str, ...]
    required: Mapping[str, frozenset[str]] = field(default_factory=dict)
    allowed: Mapping[str, frozenset[str]] = field(default_factory=dict)
    row_axes: frozenset[str] = frozenset()
    reconciling_axis: str | None = None
    instants: bool = False
    sums_to_total: bool = True
    changes: bool = True
    share_of: str | None = None  # for a share (a pure fraction): what it is a share of


SPECS: tuple[BreakdownSpec, ...] = (
    BreakdownSpec(
        "revenue_by_segment",
        "Revenue by business segment",
        SEGMENT_AXIS,
        REVENUE_CONCEPTS,
        allowed={CONSOLIDATION_AXIS: OPERATING_SEGMENTS},
        reconciling_axis=CONSOLIDATION_AXIS,
    ),
    BreakdownSpec(
        "revenue_by_product", "Revenue by product or service", PRODUCT_AXIS, REVENUE_CONCEPTS
    ),
    BreakdownSpec("revenue_by_geography", "Revenue by geography", GEOGRAPHY_AXIS, REVENUE_CONCEPTS),
    BreakdownSpec(
        "revenue_concentration_by_customer",
        "Share of revenue by major customer",
        CUSTOMER_AXIS,
        CONCENTRATION_CONCEPTS,
        required={BENCHMARK_AXIS: REVENUE_BENCHMARKS},
        allowed={RISK_TYPE_AXIS: CUSTOMER_RISK},
        row_axes=frozenset({SEGMENT_AXIS}),
        sums_to_total=False,
        changes=False,
        share_of="revenue",
    ),
    BreakdownSpec(
        "receivables_concentration_by_customer",
        "Share of accounts receivable by major customer",
        CUSTOMER_AXIS,
        CONCENTRATION_CONCEPTS,
        required={BENCHMARK_AXIS: RECEIVABLE_BENCHMARKS},
        allowed={RISK_TYPE_AXIS: CUSTOMER_RISK},
        row_axes=frozenset({SEGMENT_AXIS}),
        instants=True,
        sums_to_total=False,
        changes=False,
        share_of="accounts receivable",
    ),
)

type Period = tuple[date | None, date]
type RowKey = tuple[str, tuple[tuple[str, str], ...]]


@dataclass(frozen=True)
class _Cell:
    """One candidate value for one row and period, and how it was tagged."""

    fact: TaggedFact
    context: XbrlContext
    unit: str
    rank: int  # qualifiers on the context; the plainest wins


# Labels


def member_label(member: str) -> str:
    """A readable label from a member's qualified name, keeping acronyms.

    ``nvda:OEMAndOtherMember`` -> "OEM and Other"; ``country:US`` -> "US". The
    prefix and a trailing "Member" are dropped, words are split at capitals and
    digits, a lone capital letter stays joined to what follows ("IPhone",
    "A2060"), and short connecting words are lower-cased. It is not the
    company's own label.
    """
    local = member.rsplit(":", 1)[-1]
    if local.endswith("Member") and len(local) > len("Member"):
        local = local[: -len("Member")]
    tokens = WORD.findall(local)
    words: list[str] = []
    carry = ""
    for token in tokens:
        if len(token) == 1 and token.isupper():
            carry += token
            continue
        words.append(carry + token)
        carry = ""
    if carry:
        words.append(carry)
    if not words:
        return local
    return " ".join(
        word.lower() if index and word.lower() in CONNECTORS else word
        for index, word in enumerate(words)
    )


def _row_label(key: RowKey) -> str:
    member, extras = key
    label = member_label(member)
    if extras:
        label += " · " + "; ".join(member_label(extra) for _, extra in extras)
    return label


# Periods


def _kind(context: XbrlContext) -> str | None:
    """``instant``, or a duration's kind by its length (:data:`PERIOD_DAYS`), else None."""
    if context.start is None:
        return INSTANT
    days = (context.end - context.start).days
    return next((kind for kind, low, high in PERIOD_DAYS if low <= days <= high), None)


def _period(context: XbrlContext) -> Period:
    return (context.start, context.end)


def _year_before(end: date) -> date:
    try:
        return end.replace(year=end.year - 1)
    except ValueError:  # 29 February
        return end - timedelta(days=365)


def _period_words(kind: str, period: Period) -> str:
    if kind == INSTANT:
        return f"value at {period[1].isoformat()}"
    return f"{KIND_WORDS[kind]} ended {period[1].isoformat()}"


# Matching facts to a breakdown


def _match(spec: BreakdownSpec, context: XbrlContext) -> tuple[RowKey, int] | None:
    """The row this context belongs to in ``spec`` and its qualifier count, or None."""
    dims = context.dimensions
    if context.typed_axes or spec.axis not in dims:
        return None
    if any(dims.get(axis) not in members for axis, members in spec.required.items()):
        return None
    rank = 0
    extras: list[tuple[str, str]] = []
    for axis, member in dims.items():
        if axis == spec.axis or axis in spec.required:
            continue
        if axis in spec.allowed:
            if member not in spec.allowed[axis]:
                return None
            rank += 1
        elif axis in spec.row_axes:
            extras.append((axis, member))
            rank += 1
        else:
            return None
    return (dims[spec.axis], tuple(sorted(extras))), rank


@dataclass
class _Index:
    """The filing's facts joined to their contexts and units, read once for every breakdown."""

    by_concept: dict[str, list[tuple[TaggedFact, XbrlContext, str]]]

    @classmethod
    def of(cls, facts: TaggedFacts) -> _Index:
        by_concept: dict[str, list[tuple[TaggedFact, XbrlContext, str]]] = defaultdict(list)
        for fact in facts.facts:
            context = facts.contexts[fact.context_ref]
            unit = facts.units.get(fact.unit_ref or "", fact.unit_ref or "")
            by_concept[fact.concept].append((fact, context, unit))
        return cls(dict(by_concept))


def _cells(
    spec: BreakdownSpec, index: _Index, concept: str
) -> dict[RowKey, dict[Period, list[_Cell]]]:
    cells: dict[RowKey, dict[Period, list[_Cell]]] = defaultdict(lambda: defaultdict(list))
    for fact, context, unit in index.by_concept.get(concept, []):
        matched = _match(spec, context)
        if matched is not None and _kind(context) is not None:
            key, rank = matched
            cells[key][_period(context)].append(_Cell(fact, context, unit, rank))
    return cells


def _choose_kind(
    kinds: Counter[str], annual: bool, spec: BreakdownSpec
) -> tuple[str | None, list[str]]:
    """The period kind to show and the notes on what is not shown."""
    notes: list[str] = []
    if annual:
        if ANNUAL in kinds:
            if spec.instants and INSTANT in kinds:
                notes.append("Values at instants are also tagged and are not shown.")
            return ANNUAL, notes
        if spec.instants and INSTANT in kinds:
            return INSTANT, notes
        return None, notes
    if QUARTER in kinds:
        if YEAR_TO_DATE in kinds:
            notes.append(
                "Year-to-date values are also tagged and are not shown: this breakdown shows "
                "the quarter alone, never mixed with year to date."
            )
        return QUARTER, notes
    if YEAR_TO_DATE in kinds:
        notes.append(
            "Only year-to-date values are tagged on this axis; the quarter alone is not, so "
            "year to date is shown."
        )
        return YEAR_TO_DATE, notes
    if spec.instants and INSTANT in kinds:
        return INSTANT, notes
    return None, notes


# Values and changes


def _half_unit(fact: TaggedFact) -> float:
    """Half the rounding unit the tag declares (``decimals="-6"`` -> 500,000); 0 for INF."""
    try:
        return 0.5 * 10.0 ** (-int(fact.decimals or "INF"))
    except ValueError:
        return 0.0


def _change(
    spec: BreakdownSpec, kind: str, current: _Cell, row: Mapping[Period, _Cell]
) -> tuple[float | None, str]:
    if not spec.changes:
        return None, NO_CHANGE_CONCENTRATION
    target = _year_before(current.context.end)
    earlier = [
        (period, cell)
        for period, cell in row.items()
        if _kind(cell.context) == kind and abs((period[1] - target).days) <= YEAR_MATCH_DAYS
    ]
    if not earlier:
        return None, NO_COMPARABLE
    period, base = min(earlier, key=lambda item: abs((item[0][1] - target).days))
    where = _period_words(kind, period)
    if base.fact.value <= 0:
        sign = "zero" if base.fact.value == 0 else "negative"
        return None, f"Not computed: the {where} is {sign}, so a per-cent change has no meaning."
    change = (current.fact.value - base.fact.value) / base.fact.value * 100
    cur, old = millions_text(current.fact.value), millions_text(base.fact.value)
    formula = (
        f"({cur} {MINUS} {old}) ÷ {old} = {percent_text(change, signed=True)}: the change from "
        f"the {where}, in {current.unit} millions"
    )
    return change, formula


def _value(
    spec: BreakdownSpec, kind: str, cell: _Cell, row: Mapping[Period, _Cell]
) -> BreakdownValue:
    change, formula = _change(spec, kind, cell, row)
    start = cell.context.start
    return BreakdownValue(
        period_start=start.isoformat() if start else None,
        period_end=cell.context.end.isoformat(),
        value=cell.fact.value,
        unit=cell.unit,
        shown=cell.fact.shown,
        display=_display(cell.fact.value, cell.unit),
        change=change,
        change_display="" if change is None else percent_text(change, signed=True),
        change_formula=formula,
    )


# What a table shows: one formatting path, here, for the command line and the page alike


def _display(value: float, unit: str) -> str:
    """``value`` in its breakdown's display unit: a fraction as a percent, else millions.

    The value already has its tag's scale applied, so a tag in thousands beside
    tags in millions displays in the same unit as its neighbours.
    """
    return percent_text(value * 100) if unit == PURE else millions_text(value)


def _unit_label(spec: BreakdownSpec, unit: str) -> str:
    """The unit every ``display`` of a breakdown is in."""
    if unit == PURE:
        return f"percent of {spec.share_of or 'the benchmark'}"
    return f"{unit} millions"


def _column(kind: str, period: Period) -> PeriodColumn:
    """One shown period and its heading.

    "Fiscal year ended …", "Quarter ended …", "As of …"; year to date names both
    dates, because its length depends on the quarter ("Year to date, … to …").
    """
    start, end = period
    if kind == INSTANT or start is None:
        label = f"As of {end.isoformat()}"
    elif kind == YEAR_TO_DATE:
        label = f"Year to date, {start.isoformat()} to {end.isoformat()}"
    else:
        label = f"{KIND_WORDS[kind].capitalize()} ended {end.isoformat()}"
    return PeriodColumn(
        period_start=start.isoformat() if start else None, period_end=end.isoformat(), label=label
    )


def _pick(candidates: list[_Cell], conflicts: list[str], what: str) -> _Cell:
    """The plainest candidate; a different value tagged as plainly is noted, not hidden."""
    ordered = sorted(candidates, key=lambda cell: cell.rank)
    chosen = ordered[0]
    rivals = {c.fact.value for c in ordered if c.rank == chosen.rank} - {chosen.fact.value}
    if rivals:
        others = ", ".join(millions_text(value) for value in sorted(rivals))
        conflicts.append(
            f"{what} is tagged with more than one value ({millions_text(chosen.fact.value)} "
            f"shown; also {others}, in millions)."
        )
    return chosen


# Adding up


type Member = tuple[RowKey, float, float]  # a member, its value and half its rounding unit


def _subset_summing_to(
    target: float, members: list[Member], *, smallest: int, slack: float = 0.0
) -> list[RowKey]:
    """The fewest members (at least ``smallest``) adding up to ``target`` within rounding.

    Only the first :data:`MAX_NESTED_SEARCH` members are searched. The members
    found are returned largest first.
    """
    searched = members[:MAX_NESTED_SEARCH]
    for size in range(smallest, len(searched) + 1):
        for group in combinations(searched, size):
            tolerance = sum(half for _, _, half in group) + slack
            if abs(sum(value for _, value, _ in group) - target) <= tolerance:
                return [key for key, _, _ in sorted(group, key=lambda m: m[1], reverse=True)]
    return []


@dataclass(frozen=True)
class _Shape:
    """How the members of one period relate to the total.

    ``direct``: they add up. ``nested``: they add up once the members in ``keys``,
    each the sum of other members, are counted only through those parts.
    ``splits``: they are two splits of the total, and ``keys`` is the smaller one.
    ``none``: none of these.
    """

    kind: str
    keys: tuple[RowKey, ...] = ()


def _parts(parent: Member, members: list[Member]) -> list[RowKey]:
    """The fewest other members, each no larger than ``parent``, that add up to it."""
    key, value, _ = parent
    smaller = [m for m in members if m[0] != key and 0 < m[1] <= value]
    return _subset_summing_to(value, smaller, smallest=2)


def _shape(members: list[tuple[RowKey, _Cell]], total: _Cell) -> tuple[_Shape, float]:
    """The shape of one period's members against the total, and the members' sum.

    Tried cheapest first: a direct sum; one member whose value is the excess; two
    splits (the sum is twice the total); then, among at most
    :data:`MAX_NESTED_SEARCH` members, every member that is the sum of others,
    leaving the rest to add up to the total.
    """
    target = total.fact.value
    values = [(key, cell.fact.value, _half_unit(cell.fact)) for key, cell in members]
    added = sum(value for _, value, _ in values)
    slack = _half_unit(total.fact) + 1e-9 * abs(target)
    tolerance = sum(half for _, _, half in values) + slack
    if abs(added - target) <= tolerance:
        return _Shape("direct"), added
    for key, value, _ in values:
        if abs(added - value - target) <= tolerance:
            return _Shape("nested", (key,)), added
    if abs(added - 2 * target) <= tolerance:
        split = _subset_summing_to(target, values, smallest=1, slack=slack)
        if split:
            return _Shape("splits", tuple(split)), added
    if len(values) <= MAX_NESTED_SEARCH:
        parents = tuple(member[0] for member in values if _parts(member, values))
        leaves = [member for member in values if member[0] not in parents]
        leaf_tolerance = sum(half for _, _, half in leaves) + slack
        if parents and abs(sum(value for _, value, _ in leaves) - target) <= leaf_tolerance:
            return _Shape("nested", parents), added
    return _Shape("none"), added


def _nested_note(
    parents: tuple[RowKey, ...],
    periods: list[Period],
    checked: int,
    rows: Mapping[RowKey, Mapping[Period, _Cell]],
) -> str:
    """Name what each nested member is made of, when its parts add up to it in every period."""
    newest = periods[0]
    members = [
        (key, row[newest].fact.value, _half_unit(row[newest].fact))
        for key, row in rows.items()
        if newest in row
    ]
    sentences: list[str] = []
    for parent in parents:
        parts = _parts((parent, rows[parent][newest].fact.value, 0.0), members)
        consistent = bool(parts) and all(
            all(period in rows[part] for part in parts)
            and abs(
                sum(rows[part][period].fact.value for part in parts)
                - rows[parent][period].fact.value
            )
            <= sum(_half_unit(rows[part][period].fact) for part in parts)
            for period in periods
        )
        name = _row_label(parent)
        sentences.append(
            f"{name} equals {' plus '.join(_row_label(part) for part in parts)}"
            if consistent
            else f"{name} contains other members' values"
        )
    names = ", ".join(_row_label(parent) for parent in parents)
    return (
        f"{'; '.join(sentences)}; these parts are tagged as members too. With {names} counted "
        f"once, the members add up to the tagged total in {len(periods)} of the {checked} "
        "period(s) checked."
    )


def _splits_note(split: tuple[RowKey, ...], periods: list[Period], checked: int, rows: int) -> str:
    named = " plus ".join(_row_label(key) for key in split)
    rest = rows - len(split)
    return (
        f"The members are two splits of the same total: {named} add up to it, and so do the "
        f"other {rest} member(s); each split adds up to the tagged total in {len(periods)} of "
        f"the {checked} period(s) checked."
    )


def _check_sum(
    item: Breakdown,
    kind: str,
    columns: list[Period],
    rows: Mapping[RowKey, Mapping[Period, _Cell]],
    totals: Mapping[Period, _Cell],
    reconciling: Mapping[Period, list[tuple[str, _Cell]]],
) -> tuple[bool | None, list[str]]:
    """Whether the members add up to the tagged total in every period, and the notes saying so.

    Each period is checked on its own, within the rounding the tags declare. The
    members may add up directly, with nested members counted once, as two splits
    of the same total, or with the period's ``reconciling`` items added (for
    segments: eliminations and corporate amounts). Anything else is reported with
    the numbers and the reconciling items found.
    """
    checked = 0
    failures: list[str] = []
    reconciled: list[str] = []
    shapes: dict[_Shape, list[Period]] = defaultdict(list)
    for period in columns:
        total = totals.get(period)
        members = [(key, row[period]) for key, row in rows.items() if period in row]
        if total is None or not members:
            continue
        checked += 1
        shape, added = _shape(members, total)
        if shape.kind != "none":
            shapes[shape].append(period)
            continue
        member_halves = sum(_half_unit(cell.fact) for _, cell in members)
        items, subtotals = [], []
        for member, cell in reconciling.get(period, []):
            # An item equal to the members' own sum is their subtotal, not a reconciling item.
            same = abs(cell.fact.value - added) <= member_halves + _half_unit(cell.fact)
            (subtotals if same else items).append((member, cell))
        listed = ", ".join(
            f"{member_label(member)} ({millions_text(cell.fact.value)})" for member, cell in items
        )
        listed += "".join(
            f"; {member_label(member)} ({millions_text(cell.fact.value)}) equals the members' "
            "own sum and is not added"
            for member, cell in subtotals
        )
        when = _period_words(kind, period).capitalize()
        with_items = added + sum(cell.fact.value for _, cell in items)
        tolerance = (
            sum(_half_unit(cell.fact) for _, cell in members)
            + sum(_half_unit(cell.fact) for _, cell in items)
            + _half_unit(total.fact)
            + 1e-9 * abs(total.fact.value)
        )
        if items and abs(with_items - total.fact.value) <= tolerance:
            reconciled.append(
                f"{when}: the members add up to the tagged total once the reconciling items "
                f"tagged on {CONSOLIDATION_AXIS} alone are added ({total.unit} millions): {listed}."
            )
            continue
        found = (
            f" Reconciling items tagged on {CONSOLIDATION_AXIS} alone: {listed}; with them the "
            f"sum is {millions_text(with_items)}."
            if items
            else ""
        )
        failures.append(
            f"{when}: the members add up to {millions_text(added)}, not the tagged total of "
            f"{millions_text(total.fact.value)} ({total.unit} millions); they do not add up, a "
            f"difference of {millions_text(added - total.fact.value)}.{found}"
        )
    if checked == 0:
        return None, [
            f"The filing tags no total of {item.concept} without dimensions for these periods, "
            "so the members' sum is not checked."
        ]
    notes: list[str] = []
    for shape, periods in shapes.items():
        if shape.kind == "direct":
            every = "each of the" if len(periods) == checked else f"{len(periods)} of the"
            notes.append(
                f"The members add up to the tagged total in {every} {checked} period(s) checked, "
                "within the rounding the tags declare."
            )
        elif shape.kind == "nested":
            notes.append(_nested_note(shape.keys, periods, checked, rows))
        else:
            notes.append(_splits_note(shape.keys, periods, checked, len(rows)))
    return not failures, notes + reconciled + failures


# One breakdown


def _choose_concept(
    spec: BreakdownSpec, index: _Index, annual: bool
) -> tuple[str, dict[RowKey, dict[Period, list[_Cell]]], list[str]] | None:
    """The concept with the most member-period values of a usable kind, and notes on the rest."""
    counted: list[tuple[int, int, str, dict[RowKey, dict[Period, list[_Cell]]]]] = []
    for order, concept in enumerate(spec.concepts):
        cells = _cells(spec, index, concept)
        kinds = Counter(_kind(c[0].context) or "" for row in cells.values() for c in row.values())
        if _choose_kind(kinds, annual, spec)[0] is None:
            continue
        size = sum(len(row) for row in cells.values())
        counted.append((-size, order, concept, cells))
    if not counted:
        return None
    counted.sort(key=lambda entry: entry[:2])
    _, _, concept, cells = counted[0]
    notes = [
        f"{other} is also tagged on this axis ({-size} value(s)) and is not used."
        for size, _, other, _ in counted[1:]
    ]
    return concept, cells, notes


def _only_unit(
    cells: dict[RowKey, dict[Period, list[_Cell]]], notes: list[str]
) -> tuple[str, dict[RowKey, dict[Period, list[_Cell]]]]:
    units = Counter(cell.unit for row in cells.values() for c in row.values() for cell in c)
    unit = units.most_common(1)[0][0]
    if len(units) > 1:
        dropped = sum(count for name, count in units.items() if name != unit)
        notes.append(f"{dropped} value(s) in units other than {unit} are left out.")
    kept: dict[RowKey, dict[Period, list[_Cell]]] = {}
    for key, row in cells.items():
        periods = {p: [c for c in cs if c.unit == unit] for p, cs in row.items()}
        periods = {p: cs for p, cs in periods.items() if cs}
        if periods:
            kept[key] = periods
    return unit, kept


def build_breakdown(spec: BreakdownSpec, index: _Index, *, annual: bool) -> Breakdown | None:
    """One breakdown from the indexed facts, or None when the filing does not tag it."""
    chosen = _choose_concept(spec, index, annual)
    if chosen is None:
        return None
    concept, cells, notes = chosen
    # The period first, then the unit among the values of that period: choosing the commoner
    # unit first could leave no value of a period this report shows.
    kinds = Counter(_kind(c[0].context) or "" for row in cells.values() for c in row.values())
    kind, kind_notes = _choose_kind(kinds, annual, spec)
    if kind is None:  # not expected: _choose_concept keeps only concepts with a usable kind
        return None
    notes += kind_notes
    of_kind: dict[RowKey, dict[Period, list[_Cell]]] = {}
    for key, periods in cells.items():
        shown = {p: found for p, found in periods.items() if _kind(found[0].context) == kind}
        if shown:
            of_kind[key] = shown
    unit, cells = _only_unit(of_kind, notes)

    conflicts: list[str] = []
    rows: dict[RowKey, dict[Period, _Cell]] = {}
    for key, periods in cells.items():
        row = {
            period: _pick(candidates, conflicts, f"{_row_label(key)} for {period[1]}")
            for period, candidates in periods.items()
            if _kind(candidates[0].context) == kind
        }
        if row:
            rows[key] = row
    tagged_totals: dict[Period, list[_Cell]] = defaultdict(list)
    reconciling: dict[Period, dict[str, _Cell]] = defaultdict(dict)
    for fact, context, fact_unit in index.by_concept.get(concept, []):
        if fact_unit != unit or _kind(context) != kind or context.typed_axes:
            continue
        cell = _Cell(fact, context, fact_unit, 0)
        dims = context.dimensions
        if not dims:
            tagged_totals[_period(context)].append(cell)
        elif len(dims) == 1 and spec.reconciling_axis in dims:
            member = dims[spec.reconciling_axis]
            if member not in spec.allowed.get(spec.reconciling_axis, frozenset()):
                reconciling[_period(context)].setdefault(member, cell)
    totals = {
        period: _pick(found, conflicts, f"The total for {period[1]}")
        for period, found in tagged_totals.items()
    }

    columns = sorted(
        {period for row in rows.values() for period in row},
        key=lambda period: (period[1], period[0] or period[1]),
        reverse=True,
    )
    if len(columns) > MAX_PERIODS:
        notes.append(
            f"{len(columns)} periods are tagged; the newest {MAX_PERIODS} are shown "
            "(older ones still serve as the base of a change)."
        )
        columns = columns[:MAX_PERIODS]

    def order(item: tuple[RowKey, dict[Period, _Cell]]) -> tuple[float, ...]:
        row = item[1]
        return tuple(-row[p].fact.value if p in row else float("inf") for p in columns)

    ranked = sorted(rows.items(), key=order)
    if len(ranked) > MAX_ROWS:
        notes.append(
            f"{len(ranked)} members are tagged; the {MAX_ROWS} largest in the newest period are "
            "shown (the sum check uses all of them)."
        )
    shown_rows = [
        BreakdownRow(
            member=key[0],
            label=_row_label(key),
            values=[_value(spec, kind, row[p], row) for p in columns if p in row],
        )
        for key, row in ranked[:MAX_ROWS]
    ]
    shown_rows = [row for row in shown_rows if row.values]
    item = Breakdown(
        id=spec.id,
        title=spec.title,
        concept=concept,
        axis=spec.axis,
        period_kind=KIND_WORDS[kind],
        unit_label=_unit_label(spec, unit),
        periods=[_column(kind, period) for period in columns],
        rows=shown_rows,
        total=[_value(spec, kind, totals[p], totals) for p in columns if p in totals]
        if spec.sums_to_total
        else [],
    )
    if spec.sums_to_total:
        items = {period: list(found.items()) for period, found in reconciling.items()}
        item.adds_up, sum_notes = _check_sum(item, kind, columns, rows, totals, items)
        notes = sum_notes + notes
    else:
        notes = _concentration_notes(spec, rows) + notes
    item.notes = [*notes, *conflicts, LABEL_NOTE]
    return item


def _concentration_notes(
    spec: BreakdownSpec, rows: Mapping[RowKey, Mapping[Period, _Cell]]
) -> list[str]:
    """What a concentration breakdown's values are shares of, and what the rows' marks mean."""
    benchmarks = sorted(
        {
            cell.context.dimensions[BENCHMARK_AXIS]
            for row in rows.values()
            for cell in row.values()
            if BENCHMARK_AXIS in cell.context.dimensions
        }
    )
    of_what = spec.share_of or "the benchmark"
    notes = [
        f"Each value is one customer's share of {of_what} (benchmark {', '.join(benchmarks)} on "
        f"{BENCHMARK_AXIS}), as a fraction: 0.22 is 22%. Only the customers the filing "
        "discloses are tagged (usually those of 10% or more), so the shares have no total."
    ]
    if of_what == "accounts receivable":
        notes.append(
            "Kept apart from the share of revenue: a share of receivables at a date says who "
            "owes the company money, not who it sells most to."
        )
    extras = sorted({extra for key in rows for extra in key[1]})
    if extras:
        named = "; ".join(f"{axis} = {member}" for axis, member in extras)
        notes.append(
            f"Rows marked with · are also tagged with a business segment ({named}); the label "
            "after the · names it. The tags do not say whether such a share is of total revenue "
            "or of the segment's revenue; the filing's text does. Shares tagged with any other "
            "dimension (a geography, a product) are left out: they are shares of something else."
        )
    return notes


# The report


def _unread_note(facts: TaggedFacts) -> str | None:
    if not facts.unparsed:
        return None
    reasons = Counter(fact.reason for fact in facts.unparsed)
    listed = "; ".join(f"{count} × {reason}" for reason, count in reasons.most_common(MAX_REASONS))
    more = len(reasons) - MAX_REASONS
    suffix = f"; and {more} other reason(s)" if more > 0 else ""
    return (
        f"{len(facts.unparsed)} of {facts.facts_read} numeric facts could not be read and are "
        f"left out: {listed}{suffix}."
    )


def _absent_note(spec: BreakdownSpec) -> str:
    looked = ", ".join(spec.concepts)
    extra = ""
    if spec.required:
        extra = " with " + "; ".join(
            f"{axis} = one of {', '.join(sorted(members))}"
            for axis, members in spec.required.items()
        )
    return f"No {spec.title.lower()} is tagged (looked for {looked} on {spec.axis}{extra})."


def build_breakdowns(facts: TaggedFacts, *, annual: bool) -> tuple[list[Breakdown], list[str]]:
    """Every breakdown the facts hold, and a note for each one they do not."""
    index = _Index.of(facts)
    breakdowns: list[Breakdown] = []
    absent: list[str] = []
    for spec in SPECS:
        item = build_breakdown(spec, index, annual=annual)
        if item is None:
            absent.append(_absent_note(spec))
        else:
            breakdowns.append(item)
    return breakdowns, absent


def _is_annual(form: str) -> bool:
    upper = form.upper()
    if upper.startswith("10-K"):
        return True
    if upper.startswith("10-Q"):
        return False
    raise ValueError(f"form must be a 10-K or a 10-Q, not {form!r}")


def build_report(facts: TaggedFacts, *, company: Company, filing: FilingInfo) -> BreakdownReport:
    """The breakdowns of one filing's tagged facts, with notes on what was not read or found.

    ``filing.form`` decides the periods: full years for a 10-K, the quarter for
    a 10-Q (anything else is ValueError).
    """
    annual = _is_annual(filing.form)
    notes: list[str] = []
    if facts.reason is not None:
        notes.append(facts.reason)
    notes += facts.problems[:MAX_PROBLEMS]
    if len(facts.problems) > MAX_PROBLEMS:
        notes.append(f"{len(facts.problems) - MAX_PROBLEMS} more contexts could not be read.")
    unread = _unread_note(facts)
    if unread:
        notes.append(unread)
    breakdowns: list[Breakdown] = []
    if facts.facts:
        breakdowns, absent = build_breakdowns(facts, annual=annual)
        notes += absent
        notes.append(PLACEMENT_NOTE)
    return BreakdownReport(
        company=company,
        filing=filing,
        breakdowns=breakdowns,
        facts_read=facts.facts_read,
        facts_unparsed=len(facts.unparsed),
        notes=notes,
    )
