"""Metrics computed from a :class:`app.core.facts.FactBook`: the reported-numbers report.

Pure. :func:`build_report` returns every metric for the latest quarters, fiscal
years and balance-sheet dates, each with the facts it used and its arithmetic
written out, plus one chart series per quarterly and annual metric. The rules:

- Growth needs a positive base and a margin needs positive revenue; otherwise
  the value is None, displayed "n/a", with a note saying why.
- A missing input gives None with a note naming the concepts looked for. A
  missing value is never replaced by zero.
- Year-over-year comparisons match the period ending within 10 days of one
  year earlier (52/53-week years move the end date by up to a week). The
  previous quarter is the one that ends where this one starts (80 to 120 days
  earlier: a quarter is 12 to 17 weeks). Two quarters whose lengths differ by
  more than 10 days are not compared: a company that reports three quarters of
  12 weeks and one of 16 would otherwise show the calendar as growth.
- ``value`` is unrounded (USD in dollars, a percent as 55.6 for 55.6%);
  ``display`` is rounded for reading. Display negatives use a leading
  hyphen-minus ("-$1.20B", "-2.8%"); formulas use the minus sign "−" and
  write every number in USD millions.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from ed_v11.core.facts import GROUPS, FactBook, PeriodValue
from ed_v11.core.metric_models import (
    FactRef,
    Metric,
    MetricsReport,
    MetricUnit,
    PeriodKind,
    Series,
    SeriesPoint,
)

YEAR_MATCH_DAYS = 10
QUARTER_GAP_DAYS = (80, 120)
QUARTER_LENGTH_MATCH_DAYS = 10
NOT_AVAILABLE = "n/a"
MINUS = "−"
IN_MILLIONS = "; USD millions"


@dataclass(frozen=True)
class MetricSpec:
    """What one metric key is called and the unit of its value."""

    key: str
    label: str
    unit: MetricUnit


SPECS: dict[str, MetricSpec] = {
    spec.key: spec
    for spec in (
        MetricSpec("revenue", "Revenue", "USD"),
        MetricSpec("revenue_yoy", "Revenue growth, year over year", "percent"),
        MetricSpec("revenue_qoq", "Revenue growth, quarter over quarter", "percent"),
        MetricSpec("gross_margin", "Gross margin", "percent"),
        MetricSpec("operating_margin", "Operating margin", "percent"),
        MetricSpec("net_margin", "Net margin", "percent"),
        MetricSpec("eps_diluted", "Diluted EPS", "USD_per_share"),
        MetricSpec("rnd_ratio", "R&D as a share of revenue", "percent"),
        MetricSpec("operating_cash_flow", "Operating cash flow", "USD"),
        MetricSpec("capex", "Capital expenditure", "USD"),
        # The label is part of the prompt (engines.claude._figure_lines), and recorded model
        # answers are keyed by the prompt, so the definition is carried in DEFINITIONS instead.
        MetricSpec("free_cash_flow", "Free cash flow", "USD"),
        MetricSpec("fcf_margin", "Free cash flow margin", "percent"),
        MetricSpec("cash", "Cash and cash equivalents", "USD"),
        MetricSpec("cash_yoy", "Cash and cash equivalents, change over one year", "percent"),
        MetricSpec("inventory", "Inventory", "USD"),
        MetricSpec("inventory_yoy", "Inventory, change over one year", "percent"),
        MetricSpec("receivables", "Accounts receivable", "USD"),
        MetricSpec("receivables_yoy", "Accounts receivable, change over one year", "percent"),
    )
}
FREE_CASH_FLOW_DEFINITION = (
    "Free cash flow here is operating cash flow less purchases of property and equipment "
    "(PaymentsToAcquirePropertyPlantAndEquipment), a house definition that can differ from "
    "the company's own."
)
# Metrics whose definition is the project's, not the filing's: said first in their note.
DEFINITIONS: dict[str, str] = {
    "free_cash_flow": FREE_CASH_FLOW_DEFINITION,
    "fcf_margin": f"{FREE_CASH_FLOW_DEFINITION} The margin divides it by revenue.",
}
ANNUAL_KEYS: tuple[str, ...] = (
    "revenue",
    "revenue_yoy",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "eps_diluted",
    "rnd_ratio",
    "operating_cash_flow",
    "capex",
    "free_cash_flow",
    "fcf_margin",
)
QUARTER_KEYS: tuple[str, ...] = (*ANNUAL_KEYS[:2], "revenue_qoq", *ANNUAL_KEYS[2:])
INSTANT_GROUPS: tuple[str, ...] = ("cash", "inventory", "receivables")
DURATION_GROUPS: tuple[str, ...] = tuple(key for key, g in GROUPS.items() if not g.instant)
PERIOD_WORDS: dict[PeriodKind, str] = {
    "quarter": "Quarter ended",
    "annual": "Fiscal year ended",
    "instant": "As of",
}


# Display


def usd_text(value: float) -> str:
    """USD for reading: "$46.74B", "$812.0M", "$12,345"; negatives as "-$1.20B".

    The unit is chosen by the value as it will be *shown*, not as it is: 999.95
    million rounds to "1000.0M", so it is shown as "$1.00B"; 999,999.5 rounds
    to "1,000,000", so it is shown as "$1.0M".
    """
    sign, size = ("-" if value < 0 else ""), abs(value)
    millions = f"{size / 1e6:.1f}"
    if size >= 1e9 or float(millions) >= 1000:
        return f"{sign}${size / 1e9:.2f}B"
    whole = f"{size:,.0f}"
    if size >= 1e6 or float(whole.replace(",", "")) >= 1e6:
        return f"{sign}${millions}M"
    return f"{sign}${whole}"


def percent_text(value: float, *, signed: bool = False) -> str:
    """A percent number with one decimal ("55.6%"); with ``signed``, "+2.0%" for gains."""
    rounded = round(value, 1) or 0.0  # no "-0.0%"
    return f"{rounded:+.1f}%" if signed else f"{rounded:.1f}%"


def eps_text(value: float) -> str:
    """Earnings per share with two decimals: "$1.08", "-$0.26"."""
    return f"{'-' if value < 0 else ''}${abs(value):.2f}"


def millions_text(value: float) -> str:
    """A USD value in millions for a formula: "46,743", "-2,500", "0.5"."""
    millions = value / 1e6
    if float(millions).is_integer():
        return f"{int(millions):,}"
    return f"{millions:,.3f}".rstrip("0").rstrip(".")


def display_text(value: float | None, unit: MetricUnit, *, signed: bool = False) -> str:
    """The display string for a metric value in its unit."""
    if value is None:
        return NOT_AVAILABLE
    if unit == "USD":
        return usd_text(value)
    if unit == "USD_per_share":
        return eps_text(value)
    return percent_text(value, signed=signed)


# One computed value, before it becomes a Metric


@dataclass(frozen=True)
class Outcome:
    """A computed value (or None and why), the formula, and the values it used."""

    value: float | None
    formula: str = ""
    used: tuple[PeriodValue, ...] = ()
    note: str = ""
    signed: bool = False


def unavailable(note: str, *used: PeriodValue) -> Outcome:
    """No value, with the reason."""
    return Outcome(None, used=used, note=note)


def period_text(kind: PeriodKind, end: date) -> str:
    """ "Quarter ended 2026-07-26", "Fiscal year ended 2026-01-25", "As of 2026-07-26"."""
    return f"{PERIOD_WORDS[kind]} {end.isoformat()}"


def missing_note(group_key: str, kind: PeriodKind, end: date) -> str:
    """Why a value is missing, naming every concept that was looked for."""
    group = GROUPS[group_key]
    looked_for = ", ".join(group.concepts)
    if group_key == "gross_profit":
        cost = ", ".join(GROUPS["cost_of_revenue"].concepts)
        looked_for = f"{looked_for}, or revenue less cost of revenue ({cost})"
    where = period_text(kind, end).lower()
    return f"No value for {group.label.lower()} ({looked_for}) for the {where}."


def direct(value: PeriodValue | None, group_key: str, kind: PeriodKind, end: date) -> Outcome:
    """A value read from the book; a derived one shows its subtraction as the formula."""
    if value is None:
        return unavailable(missing_note(group_key, kind, end))
    formula = ""
    if value.derived and value.operands:
        formula = f" {MINUS} ".join(millions_text(o.value) for o in value.operands) + IN_MILLIONS
    return Outcome(value.value, formula, (value,))


def ratio(numerator: Outcome, revenue: PeriodValue | None, kind: PeriodKind, end: date) -> Outcome:
    """``numerator`` as a percent of revenue; revenue must be present and positive."""
    if revenue is None:
        return unavailable(missing_note("revenue", kind, end))
    if revenue.value <= 0:
        sign = "zero" if revenue.value == 0 else "negative"
        return unavailable(
            f"Not meaningful: revenue for the {period_text(kind, end).lower()} is {sign} "
            f"({millions_text(revenue.value)} USD millions).",
            revenue,
        )
    if numerator.value is None:
        return unavailable(numerator.note, *numerator.used, revenue)
    formula = f"{_operand(numerator)} ÷ {millions_text(revenue.value)}{IN_MILLIONS}"
    return Outcome(numerator.value / revenue.value * 100, formula, (*numerator.used, revenue))


def _operand(outcome: Outcome) -> str:
    """A numerator inside a ratio: its subtraction in parentheses, else its value."""
    assert outcome.value is not None
    body = outcome.formula.removesuffix(IN_MILLIONS)
    return f"({body})" if body and "÷" not in body else millions_text(outcome.value)


def growth(
    current: PeriodValue | None, base: PeriodValue | None, what: str, missing: str
) -> Outcome:
    """Percent change from ``base`` to ``current``; the base must be positive."""
    if current is None:
        return unavailable(missing)
    if base is None:
        return unavailable(f"No {what} to compare with.", current)
    if base.value <= 0:
        sign = "zero" if base.value == 0 else "negative"
        return unavailable(
            f"Growth is not meaningful: the base ({what}, ended {base.end}) is {sign} "
            f"({millions_text(base.value)} USD millions).",
            current,
            base,
        )
    cur, old = millions_text(current.value), millions_text(base.value)
    formula = f"({cur} {MINUS} {old}) ÷ {old}{IN_MILLIONS}"
    value = (current.value - base.value) / base.value * 100
    return Outcome(value, formula, (current, base), signed=True)


def free_cash_flow(ocf: Outcome, capex: Outcome) -> Outcome:
    """Operating cash flow minus capital expenditure; both must be present."""
    for part in (ocf, capex):
        if part.value is None:
            return unavailable(part.note, *ocf.used, *capex.used)
    assert ocf.value is not None and capex.value is not None
    formula = f"{millions_text(ocf.value)} {MINUS} {millions_text(capex.value)}{IN_MILLIONS}"
    return Outcome(ocf.value - capex.value, formula, (*ocf.used, *capex.used))


# Matching periods


def one_year_before(day: date) -> date:
    """The same calendar day a year earlier (28 February for 29 February)."""
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return day.replace(year=day.year - 1, day=28)


def year_earlier(values: dict[date, PeriodValue], end: date) -> PeriodValue | None:
    """The value ending within :data:`YEAR_MATCH_DAYS` of one year before ``end``."""
    target = one_year_before(end)
    near = [d for d in values if d != end and abs((d - target).days) <= YEAR_MATCH_DAYS]
    if not near:
        return None
    return values[min(near, key=lambda d: (abs((d - target).days), -d.toordinal()))]


def days_long(value: PeriodValue) -> int | None:
    """The length of a period in days, counting both ends; None for an instant."""
    return None if value.start is None else (value.end - value.start).days + 1


def quarter_earlier(values: dict[date, PeriodValue], end: date) -> PeriodValue | None:
    """The quarter before the one ending ``end``: the one ending where that one starts.

    It ends 80 to 120 days before ``end`` (:data:`QUARTER_GAP_DAYS`); among several,
    the one closest to this quarter's own length before it (91 days when unknown).
    """
    low, high = QUARTER_GAP_DAYS
    near = [d for d in values if low <= (end - d).days <= high]
    if not near:
        return None
    this = values.get(end)
    wanted = (days_long(this) if this is not None else None) or 91
    return values[min(near, key=lambda d: abs((end - d).days - wanted))]


def sequential_growth(
    current: PeriodValue | None, previous: PeriodValue | None, missing: str
) -> Outcome:
    """Growth on the previous quarter, or why not: the two must be about the same length."""
    if current is not None and previous is not None:
        this_long, that_long = days_long(current), days_long(previous)
        if (
            this_long is not None
            and that_long is not None
            and abs(this_long - that_long) > QUARTER_LENGTH_MATCH_DAYS
        ):
            return unavailable(
                f"Not compared with the previous quarter: this quarter is {round(this_long / 7)} "
                f"weeks long and the one before it (ended {previous.end}) is "
                f"{round(that_long / 7)} weeks long.",
                current,
                previous,
            )
    return growth(current, previous, "previous quarter", missing)


# Building metrics


def _refs(used: tuple[PeriodValue, ...]) -> list[FactRef]:
    """Every fact behind the values used, without repeats, in order of use."""
    refs: list[FactRef] = []
    for value in used:
        for ref in value.refs:
            if ref not in refs:
                refs.append(ref)
    return refs


def _note(outcome: Outcome) -> str:
    """The reason for a missing value, or the derivation and restatement notes of the inputs."""
    if outcome.value is None:
        return outcome.note
    notes: list[str] = []
    for value in outcome.used:
        text = value.refs[0].note
        if text and text not in notes:
            notes.append(text)
    restated = any(r.restated for v in outcome.used for r in v.refs)
    if restated and not any(n.startswith("Restated") for n in notes):
        notes.append("Restated: an input was restated by a later filing; see the inputs.")
    return " ".join(notes)


def to_metric(key: str, kind: PeriodKind, end: date, outcome: Outcome) -> Metric:
    """The record for one computed value."""
    spec = SPECS[key]
    return Metric(
        id=f"{key}:{kind}:{end.isoformat()}",
        key=key,
        label=spec.label,
        period=kind,
        period_end=end.isoformat(),
        period_label=period_text(kind, end),
        value=outcome.value,
        unit=spec.unit,
        display=display_text(outcome.value, spec.unit, signed=outcome.signed),
        formula=outcome.formula if outcome.value is not None else "",
        inputs=_refs(outcome.used),
        note=" ".join(text for text in (DEFINITIONS.get(key, ""), _note(outcome)) if text),
    )


def flow_outcomes(
    values: dict[str, dict[date, PeriodValue]], kind: PeriodKind, end: date
) -> dict[str, Outcome]:
    """Every quarterly or annual metric for the period ending ``end``."""
    at = {key: series.get(end) for key, series in values.items()}
    revenue = at["revenue"]
    revenue_missing = missing_note("revenue", kind, end)
    word = "quarter" if kind == "quarter" else "fiscal year"
    out: dict[str, Outcome] = {"revenue": direct(revenue, "revenue", kind, end)}
    out["revenue_yoy"] = growth(
        revenue,
        year_earlier(values["revenue"], end),
        f"{word} ending about one year earlier (within {YEAR_MATCH_DAYS} days)",
        revenue_missing,
    )
    if kind == "quarter":
        out["revenue_qoq"] = sequential_growth(
            revenue, quarter_earlier(values["revenue"], end), revenue_missing
        )
    for key, group in (
        ("gross_margin", "gross_profit"),
        ("operating_margin", "operating_income"),
        ("net_margin", "net_income"),
        ("rnd_ratio", "rnd"),
    ):
        out[key] = ratio(direct(at[group], group, kind, end), revenue, kind, end)
    out["eps_diluted"] = eps_outcome(at["eps_diluted"], kind, end)
    out["operating_cash_flow"] = direct(at["operating_cash_flow"], "operating_cash_flow", kind, end)
    out["capex"] = direct(at["capex"], "capex", kind, end)
    out["free_cash_flow"] = free_cash_flow(out["operating_cash_flow"], out["capex"])
    out["fcf_margin"] = ratio(out["free_cash_flow"], revenue, kind, end)
    return out


def eps_outcome(value: PeriodValue | None, kind: PeriodKind, end: date) -> Outcome:
    """Diluted EPS as reported; a quarter without a 3-month fact is unavailable."""
    if value is not None:
        return Outcome(value.value, "", (value,))
    if kind == "quarter":
        concepts = ", ".join(GROUPS["eps_diluted"].concepts)
        return unavailable(
            f"Unavailable: no 3-month diluted EPS fact ({concepts}) for the "
            f"{period_text(kind, end).lower()}. EPS cannot be derived by differencing "
            "year-to-date values, because the share count differs between periods."
        )
    return unavailable(missing_note("eps_diluted", kind, end))


def instant_outcomes(values: dict[date, PeriodValue], key: str, end: date) -> dict[str, Outcome]:
    """A balance-sheet value and its change over one year."""
    value = values.get(end)
    level = direct(value, key, "instant", end)
    change = growth(
        value,
        year_earlier(values, end),
        f"balance one year earlier (within {YEAR_MATCH_DAYS} days)",
        level.note,
    )
    return {key: level, f"{key}_yoy": change}


# The report


def _newest_first(ends: set[date]) -> list[date]:
    return sorted(ends, reverse=True)


def _instant_dates(annual_ends: list[date], quarter_ends: list[date], book: FactBook) -> list[date]:
    """The latest two fiscal year ends and the latest quarter end, newest first.

    Without any duration period, the latest balance-sheet date reported.
    """
    dates = set(annual_ends[:2]) | set(quarter_ends[:1])
    if not dates:
        reported = {d for key in INSTANT_GROUPS for d in book.instants(key)}
        dates = set(_newest_first(reported)[:1])
    return _newest_first(dates)


def _flow_metrics(
    values: dict[str, dict[date, PeriodValue]], kind: PeriodKind, ends: list[date]
) -> list[Metric]:
    """Metrics for each key in order, newest period first within the key."""
    keys = QUARTER_KEYS if kind == "quarter" else ANNUAL_KEYS
    by_end = {end: flow_outcomes(values, kind, end) for end in ends}
    return [to_metric(key, kind, end, by_end[end][key]) for key in keys for end in ends]


def _instant_metrics(book: FactBook, dates: list[date]) -> list[Metric]:
    metrics: list[Metric] = []
    for group in INSTANT_GROUPS:
        values = book.instants(group)
        by_date = {end: instant_outcomes(values, group, end) for end in dates}
        for key in (group, f"{group}_yoy"):
            metrics.extend(to_metric(key, "instant", end, by_date[end][key]) for end in dates)
    return metrics


def build_series(metrics: list[Metric]) -> list[Series]:
    """One series per quarterly and annual metric key, oldest point first."""
    series: dict[tuple[str, str], Series] = {}
    for item in metrics:
        if item.period == "instant":
            continue
        line = series.setdefault(
            (item.period, item.key),
            Series(key=item.key, label=item.label, unit=item.unit, period=item.period),
        )
        line.points.insert(
            0, SeriesPoint(period_end=item.period_end, value=item.value, display=item.display)
        )
    return list(series.values())


def _check_window(name: str, count: int) -> None:
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError(f"{name} must be a whole number of at least 0, got {count!r}")


def build_report(book: FactBook, *, quarters: int = 8, years: int = 4) -> MetricsReport:
    """Every metric for the latest ``quarters`` quarters and ``years`` fiscal years.

    Also the cash, inventory and receivables balances at the latest two fiscal
    year ends and the latest quarter end. Raises ValueError for a negative window.
    """
    _check_window("quarters", quarters)
    _check_window("years", years)
    period_values: dict[PeriodKind, Callable[[str], dict[date, PeriodValue]]] = {
        "quarter": book.quarters,
        "annual": book.annuals,
    }
    metrics: list[Metric] = []
    all_ends: dict[PeriodKind, list[date]] = {}
    for kind, count in (("quarter", quarters), ("annual", years)):
        values = {key: period_values[kind](key) for key in DURATION_GROUPS}
        all_ends[kind] = _newest_first({end for series in values.values() for end in series})
        metrics += _flow_metrics(values, kind, all_ends[kind][:count])
    metrics += _instant_metrics(book, _instant_dates(all_ends["annual"], all_ends["quarter"], book))
    notes = list(book.problems)
    if not any(m.value is not None for m in metrics):
        notes.append("No reported values were found for the concepts these metrics read.")
        metrics = []
    return MetricsReport(
        company=book.name,
        cik=book.cik,
        metrics=metrics,
        series=build_series(metrics),
        notes=notes,
    )
