"""Reported values from SEC XBRL company facts, selected and placed by their dates.

Pure: a :class:`FactBook` is built from the parsed ``companyfacts`` JSON and
touches nothing else. The rules it applies, each the answer to a quirk of the
data:

- A fact is placed by its ``start`` and ``end`` dates only. ``fy`` and ``fp``
  describe the filing the fact appeared in, not the fact's period, and are
  never read.
- A period's kind follows from its length in days, because fiscal years are 52
  or 53 weeks and some companies report in weeks, not months: a quarter is 12 to
  17 weeks (80-120 days), the first half 24 to 28 weeks (160-200), the first
  three quarters 36 to 40 weeks (245-290) and a year 350-380
  (:func:`period_length`). Costco's year is three quarters of 12 weeks and one
  of 16; with the calendar lengths alone its 24- and 36-week periods were
  dropped and its fourth quarter was never derived.
- A fiscal year is a year-long period that an annual report reported
  (:data:`ANNUAL_FORMS`). Length alone is not enough: Amazon's 10-Qs tag its cash
  flows for the twelve months ended each quarter, and those periods are as long
  as a year. Such a period is kept as a duration and is never a fiscal year.
- The same period is reported again in later filings. For one concept and
  period the value from the latest ``filed`` date is kept; if any other filing
  gave a different value, the kept value is flagged ``restated``.
- One idea is tagged with different concepts over time. For each period the
  first concept of the group (:data:`GROUPS`) with a value for that exact
  period is taken.
- 10-Qs report some items only year to date and no filing reports a fourth
  quarter alone. A standalone quarter is the 3-month fact when one exists,
  otherwise a cumulative value minus the previous cumulative value with the
  same start date (half year minus first quarter, nine months minus half year,
  year minus nine months). Such a value is marked derived and keeps both inputs.
  Earnings per share are never differenced.
- A later filing can restate one input of a difference and not the other
  (Microsoft restated fiscal 2016 revenue for ASC 606 in its fiscal 2018 10-K;
  the nine-month figure was never restated). Differencing the latest value of
  each would mix two bases, so a difference uses the latest pair of reports
  that is consistent: neither period was reported with another value, under
  any concept of the group, between the two filing dates. An input that is not
  the latest report of its period is flagged restated and says so.
- Gross profit is ``GrossProfit`` where reported, otherwise revenue minus cost
  of revenue for the same period, marked derived.
- As of a date (``FactBook(payload, as_of=day)``), a fact filed after that day
  does not exist: every value, derivation and restated flag is what a reader
  could have computed that day (:func:`filed_by`). Without a date every fact is
  read, exactly as before.

Malformed input: a body that is not the expected shape raises
:class:`FactsError`. A single malformed fact inside an otherwise sound body is
skipped and described in :attr:`FactBook.problems`, so one bad entry does not
cost the whole company; callers must show those notes.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any

from app.core.metric_models import FactRef

DAY = timedelta(days=1)

# A period: (start, end), with start None for an instant.
type Period = tuple[date | None, date]


class FactsError(ValueError):
    """Company facts are not the shape this module reads; the message names the problem."""


@dataclass(frozen=True)
class ConceptGroup:
    """One idea and the us-gaap concepts that have tagged it, in order of preference."""

    key: str
    label: str
    concepts: tuple[str, ...]
    unit: str
    instant: bool = False


GROUPS: dict[str, ConceptGroup] = {
    group.key: group
    for group in (
        ConceptGroup(
            "revenue",
            "Revenue",
            (
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues",
                "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax",
                # A bank's total net revenue; last, so a company with one of the above keeps it.
                "RevenuesNetOfInterestExpense",
            ),
            "USD",
        ),
        ConceptGroup(
            "cost_of_revenue",
            "Cost of revenue",
            ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"),
            "USD",
        ),
        ConceptGroup("gross_profit", "Gross profit", ("GrossProfit",), "USD"),
        ConceptGroup("operating_income", "Operating income", ("OperatingIncomeLoss",), "USD"),
        ConceptGroup("net_income", "Net income", ("NetIncomeLoss",), "USD"),
        ConceptGroup("eps_diluted", "Diluted EPS", ("EarningsPerShareDiluted",), "USD/shares"),
        ConceptGroup("rnd", "Research and development", ("ResearchAndDevelopmentExpense",), "USD"),
        ConceptGroup(
            "operating_cash_flow",
            "Operating cash flow",
            ("NetCashProvidedByUsedInOperatingActivities",),
            "USD",
        ),
        ConceptGroup(
            "capex",
            "Capital expenditure",
            (
                "PaymentsToAcquirePropertyPlantAndEquipment",
                "PaymentsToAcquireProductiveAssets",
            ),
            "USD",
        ),
        ConceptGroup(
            "cash",
            "Cash and cash equivalents",
            ("CashAndCashEquivalentsAtCarryingValue",),
            "USD",
            instant=True,
        ),
        ConceptGroup("inventory", "Inventory", ("InventoryNet",), "USD", instant=True),
        ConceptGroup(
            "receivables", "Accounts receivable", ("AccountsReceivableNetCurrent",), "USD", True
        ),
    )
}

ALL_CONCEPTS: frozenset[str] = frozenset(
    concept for group in GROUPS.values() for concept in group.concepts
)

# Keys whose per-share values cannot be differenced (share counts differ by period).
NOT_DIFFERENCEABLE: frozenset[str] = frozenset({"eps_diluted"})

# Period lengths in days from start to end, inclusive bounds; cumulative order within a
# fiscal year. The names are the usual ones; the bounds also take the periods of companies
# that report in weeks (a 12-, 16- or 17-week quarter; 24 or 28 weeks; 36 or 40 weeks).
LENGTHS: tuple[tuple[str, int, int], ...] = (
    ("quarter", 80, 120),
    ("half_year", 160, 200),
    ("nine_months", 245, 290),
    ("annual", 350, 380),
)
CUMULATIVE = tuple(name for name, _, _ in LENGTHS)
LENGTH_WORDS = {
    "quarter": "three months",
    "half_year": "six months year to date",
    "nine_months": "nine months year to date",
    "annual": "fiscal year",
}
# Forms whose year-long periods are fiscal years: an annual report, its amendments and
# transition reports, and a foreign filer's (matched as prefixes of the fact's form).
ANNUAL_FORMS: tuple[str, ...] = ("10-K", "20-F", "40-F")
# The lengths those words are true of. A period of its kind outside them is described in
# weeks (:func:`length_words`): Costco's 36 weeks to date are not "nine months".
CALENDAR_LENGTHS: dict[str, tuple[int, int]] = {
    "quarter": (80, 100),
    "half_year": (170, 195),
    "nine_months": (260, 290),
}


def period_length(start: date, end: date) -> str | None:
    """``quarter``, ``half_year``, ``nine_months`` or ``annual`` by length in days, else None."""
    days = (end - start).days
    for name, low, high in LENGTHS:
        if low <= days <= high:
            return name
    return None


def length_words(start: date, end: date) -> str:
    """What a note calls the period from ``start`` to ``end``: by months, or in weeks.

    "three months", "six months year to date", "nine months year to date" or
    "fiscal year" when the period has that calendar length; otherwise its length
    in weeks ("16 weeks", "36 weeks year to date"); "period" when it is of no kind.
    """
    kind = period_length(start, end)
    if kind is None:
        return "period"
    if kind == "annual":
        return LENGTH_WORDS[kind]
    low, high = CALENDAR_LENGTHS[kind]
    days = (end - start).days
    if low <= days <= high:
        return LENGTH_WORDS[kind]
    weeks = round((days + 1) / 7)
    return f"{weeks} weeks" if kind == "quarter" else f"{weeks} weeks year to date"


def number_text(value: float) -> str:
    """A value as plain text for a note: thousands separators, no needless decimals."""
    return f"{int(value):,}" if float(value).is_integer() else f"{value:,}"


# One fact


@dataclass(frozen=True)
class Fact:
    """One entry of company facts, validated and with its dates parsed."""

    concept: str
    unit: str
    start: date | None
    end: date
    value: float
    accession: str
    form: str
    filed: date

    def ref(self, *, restated: bool = False, note: str = "") -> FactRef:
        """This fact as a :class:`FactRef` record."""
        return FactRef(
            concept=self.concept,
            unit=self.unit,
            start=self.start.isoformat() if self.start else None,
            end=self.end.isoformat(),
            value=self.value,
            accession=self.accession,
            form=self.form,
            filed=self.filed.isoformat(),
            restated=restated,
            note=note,
        )


def filed_by(raw: object, as_of: date | None) -> bool:
    """True when the raw entry ``raw`` had been filed on or before ``as_of``.

    Always True without a date. An entry whose filing date cannot be read is kept,
    so that it is reported as malformed rather than silently dropped.
    """
    if as_of is None or not isinstance(raw, dict):
        return True
    text = raw.get("filed")
    try:
        return date.fromisoformat(text) <= as_of if isinstance(text, str) else True
    except ValueError:
        return True


def _date_field(raw: dict[str, Any], name: str) -> date:
    """Parse ``raw[name]`` as a YYYY-MM-DD date or raise FactsError naming the field."""
    if name not in raw:
        raise FactsError(f"fact has no '{name}' date")
    text = raw[name]
    if not isinstance(text, str) or len(text) != 10:
        raise FactsError(f"fact has an '{name}' that is not a YYYY-MM-DD date: {text!r}")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise FactsError(f"fact has an '{name}' that is not a valid date: {text!r}") from exc


def _text_field(raw: dict[str, Any], name: str) -> str:
    """``raw[name]`` as a non-empty string, or FactsError naming the field."""
    text = raw.get(name)
    if not isinstance(text, str) or not text.strip():
        raise FactsError(f"fact has no '{name}' text")
    return text


def _value_field(raw: dict[str, Any]) -> float:
    """``raw['val']`` as a finite number (not a string or a boolean), or FactsError."""
    val = raw.get("val")
    if isinstance(val, bool) or not isinstance(val, int | float) or not math.isfinite(val):
        raise FactsError(f"fact has a 'val' that is not a finite number: {val!r}")
    return float(val)


def parse_fact(concept: str, unit: str, raw: object) -> Fact:
    """Validate one company-facts entry. Raises FactsError naming what is wrong."""
    if not isinstance(raw, dict):
        raise FactsError(f"fact is not a JSON object: {type(raw).__name__}")
    end = _date_field(raw, "end")
    start = _date_field(raw, "start") if "start" in raw else None
    if start is not None and start > end:
        raise FactsError(f"fact has a start {start} after its end {end}")
    return Fact(
        concept=concept,
        unit=unit,
        start=start,
        end=end,
        value=_value_field(raw),
        accession=_text_field(raw, "accn"),
        form=_text_field(raw, "form"),
        filed=_date_field(raw, "filed"),
    )


# Values for one period


@dataclass(frozen=True)
class PeriodValue:
    """The value of one concept group for one period.

    ``refs[0]`` describes this value: the selected fact, or a derived record
    whose note says how it was computed. When derived, the facts it was
    computed from follow it in ``refs``, and ``operands`` holds the values
    subtracted, in order (``operands[0] - operands[1]``).
    """

    key: str
    start: date | None
    end: date
    value: float
    refs: tuple[FactRef, ...]
    operands: tuple[PeriodValue, ...] = ()

    @property
    def concept(self) -> str:
        """The us-gaap concept the value was read (or derived) as."""
        return self.refs[0].concept

    @property
    def derived(self) -> bool:
        """True when the value was computed rather than read from one fact."""
        return self.refs[0].derived

    @property
    def restated(self) -> bool:
        """True when the value or any input was restated by a later filing."""
        return any(ref.restated for ref in self.refs)


def select_latest(facts: list[Fact]) -> FactRef:
    """The fact from the latest filing among reports of one concept and period.

    Ties on the filing date are broken by accession and then value, so the
    choice does not depend on input order. The result is flagged restated, with
    a note naming the latest differing report, when any report differs.
    """
    chosen = max(facts, key=lambda f: (f.filed, f.accession, f.value))
    differing = [f for f in facts if f.value != chosen.value]
    if not differing:
        return chosen.ref()
    previous = max(differing, key=lambda f: (f.filed, f.accession, f.value))
    note = (
        f"Restated: filing {previous.accession} ({previous.form}, filed {previous.filed}) "
        f"reported {number_text(previous.value)}; the latest filing's value is used."
    )
    return chosen.ref(restated=True, note=note)


def _derived(
    key: str, start: date | None, end: date, value: float, note: str, inputs: list[PeriodValue]
) -> PeriodValue:
    """A computed value whose first ref describes it and whose other refs are its inputs."""
    latest = max((value.refs[0] for value in inputs), key=lambda ref: (ref.filed, ref.accession))
    ref = FactRef(
        concept=inputs[0].concept,
        unit=inputs[0].refs[0].unit,
        start=start.isoformat() if start else None,
        end=end.isoformat(),
        value=value,
        accession=latest.accession,
        form=latest.form,
        filed=latest.filed,
        derived=True,
        restated=any(item.restated for item in inputs),
        note=note,
    )
    refs = (ref, *(r for item in inputs for r in item.refs))
    return PeriodValue(key, start, end, value, refs, tuple(inputs))


def as_reported(key: str, fact: Fact, latest: FactRef) -> PeriodValue:
    """``fact`` as an input value; flagged restated when the latest report differs."""
    if fact.value == latest.value and fact.concept == latest.concept:
        ref = latest
    elif fact.value == latest.value:
        ref = fact.ref()
    else:
        ref = fact.ref(
            restated=True,
            note=(
                f"As reported in {fact.accession} (filed {fact.filed}); the latest filing "
                f"{latest.accession} gives {number_text(latest.value)}. The earlier report is "
                "used so that both inputs of the difference are on the same basis."
            ),
        )
    return PeriodValue(key, fact.start, fact.end, fact.value, (ref,))


def _unchanged_between(reports: list[Fact], member: Fact, low: date, high: date) -> bool:
    """True when no report filed in [low, high] gives this period a different value."""
    return all(r.value == member.value for r in reports if low <= r.filed <= high)


def consistent_pair(totals: list[Fact], earliers: list[Fact]) -> tuple[Fact, Fact] | None:
    """Reports of the two inputs of a difference that are on the same basis.

    A pair is consistent when neither period was reported with a different
    value, under any concept of the group, between the two filing dates. The
    latest consistent pair is taken. None when no pair is consistent.
    """

    def consistent(total: Fact, earlier: Fact) -> bool:
        low, high = sorted((total.filed, earlier.filed))
        return _unchanged_between(totals, total, low, high) and _unchanged_between(
            earliers, earlier, low, high
        )

    def rank(pair: tuple[Fact, Fact]) -> tuple[date, date, str, str, float, float]:
        total, earlier = pair
        return (
            max(total.filed, earlier.filed),
            min(total.filed, earlier.filed),
            total.accession,
            earlier.accession,
            total.value,
            earlier.value,
        )

    pairs = [(t, e) for t in totals for e in earliers if consistent(t, e)]
    return max(pairs, key=rank) if pairs else None


def difference_quarter(key: str, total: PeriodValue, earlier: PeriodValue) -> PeriodValue | None:
    """The quarter after ``earlier`` within ``total`` (same start), or None if not a quarter."""
    assert total.start is not None and earlier.start == total.start
    start = earlier.end + DAY
    if period_length(start, total.end) != "quarter":
        return None
    assert earlier.start is not None
    note = (
        f"Derived: {length_words(total.start, total.end)} {number_text(total.value)} "
        f"({total.refs[0].accession}) − {length_words(earlier.start, earlier.end)} "
        f"{number_text(earlier.value)} ({earlier.refs[0].accession})"
    )
    if total.concept != earlier.concept:
        note += f"; concepts {total.concept} and {earlier.concept}"
    return _derived(key, start, total.end, total.value - earlier.value, note, [total, earlier])


def _by_end(values: list[PeriodValue]) -> dict[date, PeriodValue]:
    """Key values by end date; where two share an end, keep the later start (the shorter)."""
    result: dict[date, PeriodValue] = {}
    for value in sorted(values, key=lambda v: (v.end, v.start or date.min)):
        result[value.end] = value
    return result


# The book


def _require_object(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise FactsError(f"company facts must be a JSON object, got {type(payload).__name__}")
    return payload


def _cik(payload: dict[str, Any]) -> int:
    raw = payload.get("cik")
    if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
        return raw
    if isinstance(raw, str) and raw.isdigit() and int(raw) > 0:
        return int(raw)
    raise FactsError(f"company facts have no valid 'cik' (got {raw!r})")


def _name(payload: dict[str, Any]) -> str:
    raw = payload.get("entityName")
    if not isinstance(raw, str):
        raise FactsError("company facts have no 'entityName' text")
    return raw


def _us_gaap(payload: dict[str, Any]) -> dict[str, Any]:
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        raise FactsError("company facts have no 'facts' object")
    gaap = facts.get("us-gaap", {})
    if not isinstance(gaap, dict):
        raise FactsError("company facts have a 'us-gaap' entry that is not an object")
    return gaap


def _raw_facts(gaap: dict[str, Any], concept: str, unit: str) -> list[object]:
    """The raw entries of one concept in one unit; FactsError if the structure is wrong."""
    entry = gaap.get(concept)
    if entry is None:
        return []
    if not isinstance(entry, dict) or not isinstance(entry.get("units"), dict):
        raise FactsError(f"concept {concept} has no 'units' object")
    raw = entry["units"].get(unit, [])
    if not isinstance(raw, list):
        raise FactsError(f"concept {concept} has a '{unit}' unit that is not a list of facts")
    return raw


class FactBook:
    """The selected, de-duplicated values of every concept group for one company.

    Raises :class:`FactsError` when ``companyfacts`` is not the expected shape.
    Malformed single facts are skipped and described in :attr:`problems`.
    """

    def __init__(self, companyfacts: object, *, as_of: date | None = None) -> None:
        payload = _require_object(companyfacts)
        gaap = _us_gaap(payload)
        self.cik: int = _cik(payload)
        self.name: str = _name(payload)
        # Facts filed after this day are not read at all (None: every fact is read).
        self.as_of: date | None = as_of
        skipped: Counter[str] = Counter()
        self._durations: dict[str, dict[tuple[date, date], PeriodValue]] = {}
        self._instants: dict[str, dict[date, PeriodValue]] = {}
        self._reports: dict[str, dict[Period, list[Fact]]] = {}
        for group in GROUPS.values():
            by_concept = self._group_reports(gaap, group, skipped, as_of)
            self._reports[group.key] = self._pooled(by_concept)
            selected = {
                period: PeriodValue(group.key, period[0], period[1], ref.value, (ref,))
                for period, ref in (
                    (p, select_latest(facts)) for p, facts in self._first_concept(by_concept)
                )
            }
            self._instants[group.key] = {
                end: value for (start, end), value in selected.items() if start is None
            }
            self._durations[group.key] = {
                (start, end): value for (start, end), value in selected.items() if start is not None
            }
        self.problems: list[str] = [
            f"Skipped {count} malformed fact(s) of {what}"
            for what, count in sorted(skipped.items())
        ]

    @staticmethod
    def _group_reports(
        gaap: dict[str, Any], group: ConceptGroup, skipped: Counter[str], as_of: date | None
    ) -> list[dict[Period, list[Fact]]]:
        """Every valid report of each concept of the group filed by ``as_of``, by period."""
        result: list[dict[Period, list[Fact]]] = []
        for concept in group.concepts:
            by_period: dict[Period, list[Fact]] = defaultdict(list)
            for raw in _raw_facts(gaap, concept, group.unit):
                if not filed_by(raw, as_of):
                    continue
                try:
                    parsed = parse_fact(concept, group.unit, raw)
                except FactsError as exc:
                    skipped[f"{concept} ({group.unit}): {exc}"] += 1
                    continue
                if (parsed.start is None) == group.instant:
                    by_period[(parsed.start, parsed.end)].append(parsed)
            result.append(by_period)
        return result

    @staticmethod
    def _first_concept(
        by_concept: list[dict[Period, list[Fact]]],
    ) -> list[tuple[Period, list[Fact]]]:
        """Per period, the reports of the first concept that has a value for it."""
        chosen: dict[Period, list[Fact]] = {}
        for by_period in by_concept:
            for period, facts in by_period.items():
                chosen.setdefault(period, facts)
        return list(chosen.items())

    @staticmethod
    def _pooled(by_concept: list[dict[Period, list[Fact]]]) -> dict[Period, list[Fact]]:
        """Per period, the reports of every concept of the group."""
        pooled: dict[Period, list[Fact]] = defaultdict(list)
        for by_period in by_concept:
            for period, facts in by_period.items():
                pooled[period].extend(facts)
        return dict(pooled)

    def durations(self, key: str) -> dict[tuple[date, date], PeriodValue]:
        """Every selected duration value of a group, keyed by (start, end), as reported."""
        return dict(self._durations[key])

    def instants(self, key: str) -> dict[date, PeriodValue]:
        """Every selected instant (balance-sheet) value of a group, keyed by date."""
        return dict(self._instants[key])

    def periods(self, key: str) -> list[Period]:
        """Every period any concept of the group was reported for, by end then start."""
        return sorted(self._reports[key], key=lambda p: (p[1], p[0] or date.min))

    def reports(self, key: str, start: date | None, end: date) -> list[FactRef]:
        """Every report of one period under any concept of the group, oldest filing first."""
        facts = self._reports[key].get((start, end), [])
        return [f.ref() for f in sorted(facts, key=lambda f: (f.filed, f.accession, f.value))]

    def _of_length(self, key: str, length: str) -> list[PeriodValue]:
        return [
            value
            for (start, end), value in self._durations[key].items()
            if period_length(start, end) == length
        ]

    def direct_quarters(self, key: str) -> dict[date, PeriodValue]:
        """Quarters reported as 3-month facts, keyed by end date."""
        return _by_end(self._of_length(key, "quarter"))

    def differenced_quarters(self, key: str) -> dict[date, PeriodValue]:
        """Quarters computed from cumulative values with the same start, keyed by end date.

        Empty for keys in :data:`NOT_DIFFERENCEABLE` (earnings per share).
        """
        if key in NOT_DIFFERENCEABLE:
            return {}
        derived: list[PeriodValue] = []
        for level, length in enumerate(CUMULATIVE[1:], start=1):
            earlier = defaultdict(list)
            for value in self._of_length(key, CUMULATIVE[level - 1]):
                earlier[value.start].append(value)
            for total in self._of_length(key, length):
                candidates = [e for e in earlier[total.start] if e.end < total.end]
                if candidates:
                    previous = max(candidates, key=lambda e: e.end)
                    quarter = self._difference(key, total, previous)
                    if quarter is not None:
                        derived.append(quarter)
        return _by_end(derived)

    def _difference(self, key: str, total: PeriodValue, earlier: PeriodValue) -> PeriodValue | None:
        """``total`` minus ``earlier``, from reports on the same basis.

        Falls back to the selected (latest) values when no pair of reports is
        consistent; the inputs then carry their own restatement flags.
        """
        reports = self._reports[key]
        pair = consistent_pair(
            reports[(total.start, total.end)], reports[(earlier.start, earlier.end)]
        )
        if pair is None:
            return difference_quarter(key, total, earlier)
        total_fact, earlier_fact = pair
        return difference_quarter(
            key,
            as_reported(key, total_fact, total.refs[0]),
            as_reported(key, earlier_fact, earlier.refs[0]),
        )

    def quarters(self, key: str) -> dict[date, PeriodValue]:
        """Standalone quarters keyed by end date: the 3-month fact, else the derived value.

        Gross profit falls back to revenue minus cost of revenue per quarter.
        """
        result = self.differenced_quarters(key) | self.direct_quarters(key)
        if key == "gross_profit":
            return self._with_gross_fallback(
                result, self.quarters("revenue"), self.quarters("cost_of_revenue")
            )
        return dict(sorted(result.items()))

    def _in_annual_report(self, key: str, value: PeriodValue) -> bool:
        """True when some report of the period of ``value`` came from an annual report."""
        reports = self._reports[key].get((value.start, value.end), [])
        return any(fact.form.upper().startswith(ANNUAL_FORMS) for fact in reports)

    def annuals(self, key: str) -> dict[date, PeriodValue]:
        """Fiscal-year values keyed by end date; gross profit falls back as for quarters.

        A year-long period counts only when an annual report reported it
        (:data:`ANNUAL_FORMS`): twelve months to a quarter end, tagged in a 10-Q,
        is not a fiscal year.
        """
        year_long = self._of_length(key, "annual")
        result = _by_end([value for value in year_long if self._in_annual_report(key, value)])
        if key == "gross_profit":
            return self._with_gross_fallback(
                result, self.annuals("revenue"), self.annuals("cost_of_revenue")
            )
        return result

    @staticmethod
    def _with_gross_fallback(
        gross: dict[date, PeriodValue],
        revenue: dict[date, PeriodValue],
        cost: dict[date, PeriodValue],
    ) -> dict[date, PeriodValue]:
        """Reported gross profit, plus revenue minus cost where none is reported."""
        result = dict(gross)
        for end in sorted(revenue.keys() & cost.keys() - gross.keys()):
            rev, cst = revenue[end], cost[end]
            note = (
                f"Derived: revenue {number_text(rev.value)} ({rev.concept}) − cost of revenue "
                f"{number_text(cst.value)} ({cst.concept}); no GrossProfit fact for the period"
            )
            gross_value = rev.value - cst.value
            value = _derived("gross_profit", rev.start, end, gross_value, note, [rev, cst])
            own = value.refs[0].model_copy(update={"concept": "GrossProfit"})
            result[end] = replace(value, refs=(own, *value.refs[1:]))
        return dict(sorted(result.items()))
