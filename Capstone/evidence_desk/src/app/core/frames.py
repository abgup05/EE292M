"""SEC XBRL frames: one value per filer for a period, resolved into measures by year.

Pure: a frame body goes in as parsed JSON, a :class:`Panel` of measures by filer and
year comes out. The rules, each the answer to a quirk of the data:

- **A frame is a calendar period** (``CY2024`` a year, ``CY2024Q4I`` an instant at the
  end of 2024's fourth quarter); SEC places in it, for each filer, the one fact whose
  period best fits it. A row is still placed by its own ``start`` and ``end``: an
  annual row whose period is not 350 to 380 days long (the length
  :data:`app.core.facts.LENGTHS` calls a year) is dropped and counted. XBRL's ``fy``
  and ``fp`` are not in a frame and nothing here reads them.
- **One idea, several concepts.** Revenue is tagged as ``Revenues``,
  ``RevenueFromContractWithCustomerExcludingAssessedTax`` and others. For each filer
  and year the first concept of the group, in the order of :data:`app.core.facts.GROUPS`
  (the order the app's own metrics use), that has a row is taken; the others are only
  counted (:class:`~app.core.view_models.ConceptResolution`): how many filers had
  several, and how many of those differ by more than :data:`DIFFER_TOLERANCE`.
- **Measures** are built from one or two groups for the same filer and year
  (:data:`MEASURES`): margins over positive revenue, free cash flow as operating cash
  flow less capital expenditure (the app's house definition), gross profit as reported
  or else revenue less cost of revenue, as the app's facts do.
- **A year a frame cannot yet hold.** Frames carry no filing date. A year is admitted
  only when its frame's window ended :data:`ADMIT_LAG_DAYS_AS_OF` days before the
  ``as_of`` date (a year), or :data:`ADMIT_LAG_DAYS_NOW` days before today without one
  (an annual report is due within 60 to 90 days), and a row whose own period ends
  after that cutoff is dropped. A frame read today can include a value restated
  after the ``as_of`` date: SEC keeps the latest filing's value.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from app.core.facts import GROUPS, LENGTHS

ANNUAL_DAYS: tuple[int, int] = next((low, high) for name, low, high in LENGTHS if name == "annual")
DIFFER_TOLERANCE = 0.01
ADMIT_LAG_DAYS_AS_OF = 365
ADMIT_LAG_DAYS_NOW = 120
# A frame's annual window: SEC places periods within 30 days of the calendar year.
FRAME_SLACK_DAYS = 30
FIRST_FRAME_YEAR = 2009
CONCEPT_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9]{1,150}$")

# The concept groups a frame measure reads: the app's own (app.core.facts.GROUPS), in order.
FRAME_GROUPS: tuple[str, ...] = (
    "revenue",
    "cost_of_revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "rnd",
    "operating_cash_flow",
    "capex",
)
MeasureUnit = Literal["USD", "percent", "ratio"]


class FramesError(ValueError):
    """A frame body is not the shape this module reads; the message names the problem."""


@dataclass(frozen=True)
class FrameRow:
    """One row of one frame: a filer's value of one concept for the frame's period."""

    concept: str
    frame: str
    cik: int
    name: str
    start: date | None
    end: date
    value: float
    accession: str

    @property
    def days(self) -> int | None:
        """The period's length from start to end, in days; None for an instant."""
        return None if self.start is None else (self.end - self.start).days


@dataclass
class ParsedFrame:
    """A frame's rows and the rows it dropped, with the reason for each kind of drop."""

    concept: str
    frame: str
    rows: list[FrameRow]
    dropped: dict[str, int] = field(default_factory=dict)


def frame_name(year: int, quarter: int | None = None, instant: bool = False) -> str:
    """``CY2024``, ``CY2024Q3`` or ``CY2024Q4I``; ValueError for an impossible year or quarter."""
    if not FIRST_FRAME_YEAR <= year <= 2100:
        raise ValueError(f"frame year must be {FIRST_FRAME_YEAR} to 2100, got {year!r}")
    if quarter is None:
        if instant:
            raise ValueError("an instant frame needs a quarter")
        return f"CY{year}"
    if quarter not in (1, 2, 3, 4):
        raise ValueError(f"quarter must be 1 to 4, got {quarter!r}")
    return f"CY{year}Q{quarter}" + ("I" if instant else "")


def check_concept(concept: str) -> str:
    """``concept`` when it is a us-gaap element name; ValueError otherwise (it goes in a URL)."""
    if not CONCEPT_PATTERN.fullmatch(concept):
        raise ValueError(f"not a us-gaap concept name: {concept!r}")
    return concept


def _date(raw: Any, name: str) -> date:
    if not isinstance(raw, str) or len(raw) != 10:
        raise FramesError(f"row has no YYYY-MM-DD '{name}'")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise FramesError(f"row has an invalid '{name}': {raw!r}") from exc


def _row(concept: str, frame: str, raw: Any) -> FrameRow:
    if not isinstance(raw, dict):
        raise FramesError("row is not a JSON object")
    cik = raw.get("cik")
    if isinstance(cik, bool) or not isinstance(cik, int) or cik <= 0:
        raise FramesError("row has no positive integer 'cik'")
    value = raw.get("val")
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise FramesError("row has no finite 'val'")
    name = raw.get("entityName")
    accession = raw.get("accn")
    if not isinstance(name, str) or not isinstance(accession, str):
        raise FramesError("row has no 'entityName' or 'accn' text")
    end = _date(raw.get("end"), "end")
    start = _date(raw["start"], "start") if "start" in raw else None
    if start is not None and start > end:
        raise FramesError("row starts after it ends")
    return FrameRow(concept, frame, cik, name.strip(), start, end, float(value), accession)


def parse_frame(payload: object, concept: str, frame: str) -> ParsedFrame:
    """The rows of one frame body. Raises :class:`FramesError` when the body is not a frame.

    A malformed row is dropped and counted under its reason; so is an annual row whose
    period is not a year long (:data:`ANNUAL_DAYS`), and a row of a duration frame
    with no start.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise FramesError(f"the frame {concept}/{frame} has no 'data' list")
    annual = re.fullmatch(r"CY\d{4}", frame) is not None
    instant = frame.endswith("I")
    parsed = ParsedFrame(concept, frame, [])
    for raw in payload["data"]:
        try:
            row = _row(concept, frame, raw)
        except FramesError as exc:
            parsed.dropped[str(exc)] = parsed.dropped.get(str(exc), 0) + 1
            continue
        if not instant and row.start is None:
            reason = "a duration frame's row has no start"
        elif annual and row.days is not None and not ANNUAL_DAYS[0] <= row.days <= ANNUAL_DAYS[1]:
            reason = f"not a year long ({ANNUAL_DAYS[0]} to {ANNUAL_DAYS[1]} days)"
        else:
            parsed.rows.append(row)
            continue
        parsed.dropped[reason] = parsed.dropped.get(reason, 0) + 1
    return parsed


# Which years a frame may hold, as of a date


def cutoff(as_of: date | None, today: date) -> date:
    """The last period end a frame row may have: a year before ``as_of``, else 120 days ago."""
    if as_of is not None:
        return as_of - timedelta(days=ADMIT_LAG_DAYS_AS_OF)
    return today - timedelta(days=ADMIT_LAG_DAYS_NOW)


def admitted_years(as_of: date | None, today: date, first: int = FIRST_FRAME_YEAR) -> list[int]:
    """Every calendar year whose frame window (to 30 days after its end) ended by the cutoff."""
    last_end = cutoff(as_of, today)
    return [
        year
        for year in range(first, last_end.year + 1)
        if date(year, 12, 31) + timedelta(days=FRAME_SLACK_DAYS) <= last_end
    ]


# Resolving a concept group, filer by filer


@dataclass(frozen=True)
class FrameValue:
    """A group's value for one filer and year: the row taken and how many others there were."""

    group: str
    year: int
    row: FrameRow
    others: tuple[FrameRow, ...] = ()

    @property
    def value(self) -> float:
        """The value taken."""
        return self.row.value


def scale_break(first: float, second: float) -> bool:
    """True when two values differ by a factor within 2% of 1,000, a million or a billion.

    Such a pair is one number tagged at two scales (thousands read as units), not two
    different numbers: one of them is wrong, and which one cannot be told from the pair.
    """
    if first == 0 or second == 0 or (first > 0) != (second > 0):
        return False
    ratio = abs(first / second)
    exponent = math.log10(ratio) / 3
    nearest = round(exponent)
    return nearest != 0 and abs(ratio / 1000.0**nearest - 1) <= 0.02


def resolve_group(
    group: str, year: int, frames: Mapping[str, ParsedFrame], last_end: date | None = None
) -> tuple[dict[int, FrameValue], tuple[int, int, int, int]]:
    """Per filer, the first concept of the group (in :data:`GROUPS` order) with a row.

    ``frames`` maps a concept to its parsed frame for ``year``; a concept with no frame
    has no rows. Rows ending after ``last_end`` are left out. A filer whose concepts
    disagree by a factor near a thousand (:func:`scale_break`) has no value for the group
    that year: which concept is wrong cannot be told. Returns the values and (filers,
    filers with several concepts, filers whose other concepts differ by more than
    :data:`DIFFER_TOLERANCE`, filers dropped for a scale break).
    """
    by_cik: dict[int, list[FrameRow]] = {}
    for concept in GROUPS[group].concepts:
        parsed = frames.get(concept)
        if parsed is None:
            continue
        for row in parsed.rows:
            if last_end is not None and row.end > last_end:
                continue
            by_cik.setdefault(row.cik, []).append(row)
    values: dict[int, FrameValue] = {}
    several = differing = breaks = 0
    for cik, rows in by_cik.items():
        taken, others = rows[0], tuple(rows[1:])
        if others:
            several += 1
            if any(scale_break(taken.value, o.value) for o in others):
                breaks += 1
                continue
            scale = max(abs(taken.value), 1.0)
            if any(abs(o.value - taken.value) / scale > DIFFER_TOLERANCE for o in others):
                differing += 1
        values[cik] = FrameValue(group, year, taken, others)
    return values, (len(by_cik), several, differing, breaks)


RESOLUTION_RULE = (
    "Per filer and year, the first concept of the group with a row is taken, in the order "
    "the app's own metrics use ({concepts}); the others are counted, not used, except that "
    "two concepts differing by a factor near a thousand (one number tagged at two scales) "
    "leave the filer without a value that year."
)


def resolution_rule(group: str) -> str:
    """The sentence that says how a group is resolved across its concepts."""
    return RESOLUTION_RULE.format(concepts=", ".join(GROUPS[group].concepts))


# Measures


@dataclass(frozen=True)
class MeasureDef:
    """A measure a frame panel can compute, its label, unit and the groups it reads."""

    key: str
    label: str
    unit: MeasureUnit
    groups: tuple[str, ...]
    definition: str
    catalogue: str = ""


MEASURES: dict[str, MeasureDef] = {
    m.key: m
    for m in (
        MeasureDef("revenue", "Revenue", "USD", ("revenue",), "Revenue as tagged.", "revenue"),
        MeasureDef(
            "gross_profit",
            "Gross profit",
            "USD",
            ("gross_profit", "revenue", "cost_of_revenue"),
            "GrossProfit as tagged; else revenue − cost of revenue.",
            "gross_profit",
        ),
        MeasureDef(
            "operating_income",
            "Operating income",
            "USD",
            ("operating_income",),
            "OperatingIncomeLoss as tagged.",
            "operating_income",
        ),
        MeasureDef(
            "net_income", "Net income", "USD", ("net_income",), "NetIncomeLoss.", "net_income"
        ),
        MeasureDef("rnd", "Research and development", "USD", ("rnd",), "As tagged.", "rnd"),
        MeasureDef(
            "operating_cash_flow",
            "Operating cash flow",
            "USD",
            ("operating_cash_flow",),
            "NetCashProvidedByUsedInOperatingActivities.",
            "operating_cash_flow",
        ),
        MeasureDef(
            "capex",
            "Capital expenditure",
            "USD",
            ("capex",),
            "PaymentsToAcquirePropertyPlantAndEquipment (else PaymentsToAcquireProductiveAssets).",
            "capex",
        ),
        MeasureDef(
            "free_cash_flow",
            "Free cash flow",
            "USD",
            ("operating_cash_flow", "capex"),
            "Operating cash flow − capital expenditure (the app's house definition).",
            "free_cash_flow",
        ),
        MeasureDef(
            "operating_expenses",
            "Operating expenses",
            "USD",
            ("gross_profit", "revenue", "cost_of_revenue", "operating_income"),
            "Gross profit − operating income (the app's house definition).",
            "operating_expenses",
        ),
        MeasureDef(
            "gross_margin",
            "Gross margin",
            "percent",
            ("gross_profit", "revenue", "cost_of_revenue"),
            "Gross profit ÷ revenue.",
            "gross_margin",
        ),
        MeasureDef(
            "operating_margin",
            "Operating margin",
            "percent",
            ("operating_income", "revenue"),
            "Operating income ÷ revenue.",
            "operating_margin",
        ),
        MeasureDef(
            "net_margin",
            "Net margin",
            "percent",
            ("net_income", "revenue"),
            "Net income ÷ revenue.",
            "net_margin",
        ),
        MeasureDef(
            "rnd_ratio",
            "R&D as a share of revenue",
            "percent",
            ("rnd", "revenue"),
            "Research and development ÷ revenue.",
            "rnd_ratio",
        ),
        MeasureDef(
            "capex_ratio",
            "Capital expenditure as a share of revenue",
            "percent",
            ("capex", "revenue"),
            "Capital expenditure ÷ revenue.",
            "capex_ratio",
        ),
        MeasureDef(
            "fcf_margin",
            "Free cash flow margin",
            "percent",
            ("operating_cash_flow", "capex", "revenue"),
            "(Operating cash flow − capital expenditure) ÷ revenue.",
            "fcf_margin",
        ),
        MeasureDef(
            "cash_conversion",
            "Cash conversion",
            "ratio",
            ("operating_cash_flow", "net_income"),
            "Operating cash flow ÷ net income, when net income is positive.",
        ),
    )
}


@dataclass(frozen=True)
class Computed:
    """A measure's value for one filer and year (or None and why), and the values used."""

    value: float | None
    used: tuple[FrameValue, ...] = ()
    formula: str = ""
    reason: str = ""


def _millions(value: float) -> str:
    millions = value / 1e6
    return f"{millions:,.0f}" if abs(millions) >= 100 else f"{millions:,.1f}"


class Panel:
    """Every filer's resolved groups by year, and the measures computed from them."""

    def __init__(self) -> None:
        self._values: dict[int, dict[str, dict[int, FrameValue]]] = {}
        self.names: dict[int, str] = {}
        self.resolution: list[tuple[str, int, int, int, int, int]] = []

    def add(
        self,
        group: str,
        year: int,
        values: dict[int, FrameValue],
        counts: tuple[int, int, int, int],
    ) -> None:
        """Keep a resolved group's values for ``year``, and its resolution counts."""
        self._values.setdefault(year, {})[group] = values
        for cik, value in values.items():
            self.names.setdefault(cik, value.row.name)
        self.resolution.append((group, year, *counts))

    @property
    def years(self) -> list[int]:
        """The years the panel holds, oldest first."""
        return sorted(self._values)

    def has(self, group: str, year: int) -> bool:
        """True when the group was read for the year (even if no filer reported it)."""
        return group in self._values.get(year, {})

    def group(self, group: str, year: int) -> dict[int, FrameValue]:
        """Every filer's value of a group in a year (empty when not read)."""
        return self._values.get(year, {}).get(group, {})

    def filers(self, year: int) -> set[int]:
        """Every filer with a revenue value in ``year``."""
        return set(self.group("revenue", year))

    def get(self, group: str, cik: int, year: int) -> FrameValue | None:
        """One filer's value of a group in a year, or None."""
        return self.group(group, year).get(cik)

    def measure(self, key: str, cik: int, year: int) -> Computed:
        """The value of measure ``key`` for one filer and year, by :data:`MEASURES`."""
        # Gross profit has a fallback, so neither of its own two groups is required alone.
        needed = [g for g in MEASURES[key].groups if g not in ("gross_profit", "cost_of_revenue")]
        missing = [g for g in needed if not self.has(g, year)]
        if missing:
            return Computed(None, reason=f"the frames of {', '.join(missing)} were not read")
        return _COMPUTE[key](self, cik, year)

    def period_end(self, cik: int, year: int) -> date | None:
        """The end of the filer's revenue period placed in ``year``."""
        value = self.get("revenue", cik, year)
        return value.row.end if value is not None else None


def _one(group: str) -> Callable[[Panel, int, int], Computed]:
    def compute(panel: Panel, cik: int, year: int) -> Computed:
        value = panel.get(group, cik, year)
        if value is None:
            return Computed(None, reason=f"no {GROUPS[group].label.lower()} row")
        return Computed(value.value, (value,), "")

    return compute


def _gross(panel: Panel, cik: int, year: int) -> Computed:
    reported = panel.get("gross_profit", cik, year)
    if reported is not None:
        return Computed(reported.value, (reported,))
    revenue = panel.get("revenue", cik, year)
    cost = panel.get("cost_of_revenue", cik, year)
    if revenue is None or cost is None:
        return Computed(None, reason="no gross profit row, and no revenue and cost of revenue")
    if abs((revenue.row.end - cost.row.end).days) > 0:
        return Computed(None, reason="revenue and cost of revenue are of different periods")
    formula = f"{_millions(revenue.value)} − {_millions(cost.value)}"
    return Computed(revenue.value - cost.value, (revenue, cost), formula)


def _difference(first: Computed, second: Computed) -> Computed:
    if first.value is None or second.value is None:
        return Computed(None, (*first.used, *second.used), reason=first.reason or second.reason)
    a, b = first.used[0].row, second.used[0].row
    if a.end != b.end:
        return Computed(None, reason="the two values are of different periods")
    formula = f"{_millions(first.value)} − {_millions(second.value)}"
    return Computed(first.value - second.value, (*first.used, *second.used), formula)


def _fcf(panel: Panel, cik: int, year: int) -> Computed:
    return _difference(
        _one("operating_cash_flow")(panel, cik, year), _one("capex")(panel, cik, year)
    )


def _opex(panel: Panel, cik: int, year: int) -> Computed:
    return _difference(_gross(panel, cik, year), _one("operating_income")(panel, cik, year))


def _over(top: Computed, bottom: Computed, what: str, scale: float = 100.0) -> Computed:
    if top.value is None or bottom.value is None:
        return Computed(None, (*top.used, *bottom.used), reason=top.reason or bottom.reason)
    if bottom.value <= 0:
        return Computed(None, (*top.used, *bottom.used), reason=f"{what} is not positive")
    if top.used[0].row.end != bottom.used[0].row.end:
        return Computed(None, reason="the two values are of different periods")
    numerator = f"({top.formula})" if top.formula else _millions(top.value)
    formula = f"{numerator} ÷ {_millions(bottom.value)}"
    return Computed(top.value / bottom.value * scale, (*top.used, *bottom.used), formula)


def _ratio(
    numerator: Callable[[Panel, int, int], Computed],
) -> Callable[[Panel, int, int], Computed]:
    def compute(panel: Panel, cik: int, year: int) -> Computed:
        return _over(numerator(panel, cik, year), _one("revenue")(panel, cik, year), "revenue")

    return compute


def _conversion(panel: Panel, cik: int, year: int) -> Computed:
    return _over(
        _one("operating_cash_flow")(panel, cik, year),
        _one("net_income")(panel, cik, year),
        "net income",
        scale=1.0,
    )


_COMPUTE: dict[str, Callable[[Panel, int, int], Computed]] = {
    "revenue": _one("revenue"),
    "gross_profit": _gross,
    "operating_income": _one("operating_income"),
    "net_income": _one("net_income"),
    "rnd": _one("rnd"),
    "operating_cash_flow": _one("operating_cash_flow"),
    "capex": _one("capex"),
    "free_cash_flow": _fcf,
    "operating_expenses": _opex,
    "gross_margin": _ratio(_gross),
    "operating_margin": _ratio(_one("operating_income")),
    "net_margin": _ratio(_one("net_income")),
    "rnd_ratio": _ratio(_one("rnd")),
    "capex_ratio": _ratio(_one("capex")),
    "fcf_margin": _ratio(_fcf),
    "cash_conversion": _conversion,
}


def groups_for(keys: Iterable[str]) -> list[str]:
    """Every concept group the measures ``keys`` read, in :data:`FRAME_GROUPS` order."""
    wanted = {g for key in keys for g in MEASURES[key].groups}
    return [g for g in FRAME_GROUPS if g in wanted]


def frame_source(concept: str, frame: str, unit: str = "USD") -> str:
    """How an input names the frame it came from: ``SEC XBRL frame us-gaap/Revenues/USD/CY2024``."""
    return f"SEC XBRL frame us-gaap/{concept}/{unit}/{frame}"


def years_apart(later: date, earlier: date, years: int) -> bool:
    """True when two period ends are ``years`` years apart, within 10 days a year (52/53 weeks)."""
    days = (later - earlier).days
    return abs(days - 365.25 * years) <= 10 * years
