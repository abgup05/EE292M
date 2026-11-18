"""Valuation now: market value, enterprise value and multiples on the trailing figures.

Pure. The price is given (supplied on the request, or read from a price source by the
caller) with its date; every other number comes from the company's XBRL facts filed by
that date, through the same arithmetic the claim tests use (:class:`app.core.claim_eval.Measures`):

- **shares outstanding**: the cover page's ``dei:EntityCommonStockSharesOutstanding`` of
  the newest filing filed by the date, at its newest date; several values for one date
  in one filing are the share classes and are added (:func:`shares_outstanding`). A
  company that tags none falls back to the balance sheet's
  ``us-gaap:CommonStockSharesOutstanding``. The price is one class's; the market value
  prices every class at it, and the result says so when there are several;
- **market value** = price × shares outstanding;
- **enterprise value** = market value + total debt − cash and marketable securities, at
  the newest balance-sheet date (the catalogue's ``total_debt`` and
  ``cash_and_securities``: leases, preferred stock and minority interests are left out);
- **multiples** on the trailing four quarters (the catalogue's ``TTM``; the newest fiscal
  year when four quarters cannot be summed): enterprise value ÷ revenue, market value ÷
  net income, market value ÷ free cash flow, and the free-cash-flow yield. A multiple of a
  figure that is not positive is not computed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.core.analysis_models import AnalysisResult, ResultInput, ResultUnit
from app.core.claim_eval import Measures
from app.core.claimtest import Period
from app.core.facts import FactBook
from app.core.metric_models import FactRef
from app.core.metrics import percent_text, usd_text

DEI_SHARES = "EntityCommonStockSharesOutstanding"
GAAP_SHARES = "CommonStockSharesOutstanding"


@dataclass(frozen=True)
class Price:
    """A price per share on a day, and where it came from in words."""

    value: float
    day: date
    source: str


@dataclass(frozen=True)
class Shares:
    """Shares outstanding on a date, as one filing reported them (summed over classes)."""

    value: float
    day: date
    filed: date
    accession: str
    form: str
    concept: str
    classes: int


def _entries(facts: object, taxonomy: str, concept: str) -> list[dict[str, Any]]:
    try:
        rows = facts["facts"][taxonomy][concept]["units"]["shares"]  # type: ignore[index]
    except (KeyError, TypeError):
        return []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _shares_from(rows: Sequence[dict[str, Any]], concept: str, as_of: date) -> Shares | None:
    usable: list[tuple[date, date, str, str, float]] = []
    for row in rows:
        try:
            filed = date.fromisoformat(str(row["filed"]))
            end = date.fromisoformat(str(row["end"]))
            value = float(row["val"])
            accession, form = str(row["accn"]), str(row.get("form", ""))
        except (KeyError, TypeError, ValueError):
            continue
        if filed <= as_of and value > 0:
            usable.append((filed, end, accession, form, value))
    if not usable:
        return None
    filed, _, accession, form, _ = max(usable, key=lambda u: (u[0], u[2], u[1]))
    newest = max(u[1] for u in usable if u[2] == accession)
    same = [u for u in usable if u[2] == accession and u[1] == newest]
    return Shares(
        value=sum(u[4] for u in same),
        day=newest,
        filed=filed,
        accession=accession,
        form=form,
        concept=concept,
        classes=len(same),
    )


def shares_outstanding(companyfacts: object, as_of: date) -> Shares | str:
    """The shares outstanding the newest filing filed by ``as_of`` reported, or why none."""
    found = _shares_from(_entries(companyfacts, "dei", DEI_SHARES), f"dei:{DEI_SHARES}", as_of)
    if found is None:
        found = _shares_from(
            _entries(companyfacts, "us-gaap", GAAP_SHARES), f"us-gaap:{GAAP_SHARES}", as_of
        )
    if found is None:
        return (
            f"No shares outstanding ({DEI_SHARES} or {GAAP_SHARES}) were filed by "
            f"{as_of.isoformat()}."
        )
    return found


# Figures read from the facts


@dataclass
class Figure:
    """A number read from the facts for a valuation, or None and why, with its inputs."""

    label: str
    value: float | None
    period: str = ""
    formula: str = ""
    inputs: list[ResultInput] = field(default_factory=list)
    note: str = ""


def fact_input(label: str, ref: FactRef) -> ResultInput:
    """A fact as a result input: its concept, value, filing and dates (a derived value says how)."""
    source = f"SEC company facts, {ref.form} {ref.accession}"
    if ref.derived:
        source = f"SEC company facts, derived ({ref.note.removeprefix('Derived: ')})"
    return ResultInput(
        label=f"{label} ({ref.concept}{', derived' if ref.derived else ''})",
        value=ref.value,
        display=usd_text(ref.value),
        source=source,
        date=ref.end,
        filed=ref.filed,
    )


def trailing(measures: Measures, metric: str, label: str) -> Figure:
    """The trailing four quarters of a flow; the newest fiscal year when they cannot be summed."""
    notes: list[str] = []
    for period in (Period("TTM"), Period("FY")):
        slot = measures.bind(period, metric)
        if isinstance(slot, str):
            notes.append(slot)
            continue
        outcome = measures.outcome(metric, slot)
        if outcome.value is None:
            notes.append(outcome.note)
            continue
        used = [value.refs[0] for value in outcome.used]
        note = "" if period.kind == "TTM" else "Four quarters could not be summed; fiscal year used."
        return Figure(
            label=f"{label}, {slot.words}",
            value=outcome.value,
            period=slot.end.isoformat(),
            formula=outcome.formula,
            inputs=[fact_input(label, ref) for ref in used],
            note=note,
        )
    return Figure(label=label, value=None, note=" ".join(n for n in notes if n))


def balance(measures: Measures, metric: str, label: str) -> Figure:
    """A balance at the newest balance-sheet date the facts give for it."""
    slot = measures.bind(Period("Q"), metric)
    if isinstance(slot, str):
        return Figure(label=label, value=None, note=slot)
    outcome = measures.outcome(metric, slot)
    if outcome.value is None:
        return Figure(label=label, value=None, note=outcome.note)
    return Figure(
        label=f"{label}, {slot.words}",
        value=outcome.value,
        period=slot.end.isoformat(),
        formula=outcome.formula,
        inputs=[fact_input(label, value.refs[0]) for value in outcome.used],
    )


# Results


@dataclass
class Valuation:
    """The valuation's results and the numbers the reverse DCF starts from."""

    results: list[AnalysisResult]
    market_value: float | None = None
    enterprise_value: float | None = None
    revenue: Figure | None = None
    operating_income: Figure | None = None
    debt: Figure | None = None
    cash: Figure | None = None
    equity: Figure | None = None


def _price_input(price: Price) -> ResultInput:
    return ResultInput(
        label="Price per share",
        value=price.value,
        display=f"${price.value:,.2f}",
        source=price.source,
        date=price.day.isoformat(),
    )


def _shares_input(shares: Shares) -> ResultInput:
    classes = f", {shares.classes} classes added" if shares.classes > 1 else ""
    return ResultInput(
        label=f"Shares outstanding ({shares.concept}{classes})",
        value=shares.value,
        display=f"{shares.value:,.0f}",
        source=f"SEC company facts, {shares.form} {shares.accession}",
        date=shares.day.isoformat(),
        filed=shares.filed.isoformat(),
    )


def _result(
    rid: str,
    kind: str,
    label: str,
    value: float | None,
    unit: ResultUnit,
    display: str,
    formula: str,
    inputs: list[ResultInput],
    reading: str,
    as_of: str,
    *,
    reason: str = "",
    assumptions: list[str] | None = None,
    note: str = "",
) -> AnalysisResult:
    return AnalysisResult(
        id=rid,
        kind=kind,
        label=label,
        outcome="computed" if value is not None else "cannot_compute",
        reason=reason,
        value=value,
        unit=unit,
        display=display if value is not None else "n/a",
        formula=formula if value is not None else "",
        inputs=inputs,
        assumptions=assumptions or [],
        reading=reading if value is not None else reason,
        data_origin="market_prices",
        as_of=as_of,
        note=note,
    )


def _multiple(value: float) -> str:
    return f"{value:,.1f}×"


def valuation(
    ticker: str, price: Price, shares: Shares | str, measures: Measures, as_of: str
) -> Valuation:
    """Market value, enterprise value and the multiples, each with its inputs and dates."""
    stamp = f"{ticker}:{price.day.isoformat()}"
    results: list[AnalysisResult] = []
    out = Valuation(results)
    if isinstance(shares, str):
        results.append(
            _result(f"market_value:{stamp}", "market_value", "Market value", None, "USD", "", "",
                    [_price_input(price)], "", as_of, reason=shares)
        )
        return out
    market = price.value * shares.value
    out.market_value = market
    class_note = (
        f"The company reports {shares.classes} share classes; every class is priced at the "
        "one price given."
        if shares.classes > 1
        else ""
    )
    results.append(
        _result(
            f"market_value:{stamp}",
            "market_value",
            "Market value",
            market,
            "USD",
            usd_text(market),
            f"${price.value:,.2f} × {shares.value:,.0f} shares",
            [_price_input(price), _shares_input(shares)],
            f"At ${price.value:,.2f} on {price.day.isoformat()}, the {shares.value:,.0f} shares "
            f"outstanding on {shares.day.isoformat()} are worth {usd_text(market)}.",
            as_of,
            note=class_note,
        )
    )
    out.debt = balance(measures, "total_debt", "Total debt")
    out.cash = balance(measures, "cash_and_securities", "Cash and marketable securities")
    out.equity = balance(measures, "equity", "Shareholders' equity")
    out.revenue = trailing(measures, "revenue", "Revenue")
    out.operating_income = trailing(measures, "operating_income", "Operating income")
    net_income = trailing(measures, "net_income", "Net income")
    fcf = trailing(measures, "free_cash_flow", "Free cash flow")
    ev_reason = next(
        (f"{f.label}: {f.note}" for f in (out.debt, out.cash) if f.value is None), ""
    )
    if not ev_reason:
        assert out.debt.value is not None and out.cash.value is not None
        out.enterprise_value = market + out.debt.value - out.cash.value
    ev_inputs = [*results[0].inputs]
    for figure in (out.debt, out.cash):
        ev_inputs += figure.inputs
    results.append(
        _result(
            f"enterprise_value:{stamp}",
            "enterprise_value",
            "Enterprise value",
            out.enterprise_value,
            "USD",
            usd_text(out.enterprise_value or 0),
            (
                f"{usd_text(market)} + {usd_text(out.debt.value or 0)} − "
                f"{usd_text(out.cash.value or 0)}"
            ),
            ev_inputs,
            (
                f"Market value {usd_text(market)} plus total debt {usd_text(out.debt.value or 0)} "
                f"less cash and marketable securities {usd_text(out.cash.value or 0)} "
                f"({out.debt.period}) is {usd_text(out.enterprise_value or 0)}."
            ),
            as_of,
            reason=ev_reason,
            assumptions=[
                "Enterprise value = market value + total debt − cash and marketable securities "
                "(leases, preferred stock and minority interests are left out)."
            ],
        )
    )
    multiples = (
        ("ev_sales", "Enterprise value ÷ revenue", out.enterprise_value, out.revenue, False),
        ("pe", "Market value ÷ net income", market, net_income, False),
        ("p_fcf", "Market value ÷ free cash flow", market, fcf, False),
        ("fcf_yield", "Free cash flow yield", market, fcf, True),
    )
    for key, label, top, figure, inverse in multiples:
        results.append(_ratio_result(key, label, top, figure, inverse, stamp, as_of))
    return out


def _ratio_result(
    key: str,
    label: str,
    top: float | None,
    figure: Figure,
    inverse: bool,
    stamp: str,
    as_of: str,
) -> AnalysisResult:
    reason = ""
    if top is None:
        reason = "The enterprise value could not be computed."
    elif figure.value is None:
        reason = f"{figure.label} could not be computed: {figure.note}"
    elif figure.value <= 0:
        reason = f"{figure.label} is not positive ({usd_text(figure.value)}): no multiple."
    value: float | None = None
    display = formula = reading = ""
    if not reason:
        assert top is not None and figure.value is not None
        if inverse:
            value = figure.value / top * 100
            display = percent_text(value)
            formula = f"{usd_text(figure.value)} ÷ {usd_text(top)}"
            reading = f"{figure.label} is {display} of the market value."
        else:
            value = top / figure.value
            display = _multiple(value)
            formula = f"{usd_text(top)} ÷ {usd_text(figure.value)}"
            reading = f"{label} on {figure.label.lower()} is {display}."
    return _result(
        f"{key}:{stamp}",
        key,
        label,
        value,
        "percent" if inverse else "multiple",
        display,
        formula,
        figure.inputs,
        reading,
        as_of,
        reason=reason,
        note=figure.note,
    )


def trailing_growth(book: FactBook, *, years: int = 3, as_of: str) -> list[AnalysisResult]:
    """The company's own revenue growth: the newest fiscal year's, and compound over ``years``."""
    annual = book.annuals("revenue")
    ends = sorted(annual)
    results: list[AnalysisResult] = []
    for span, key in ((1, "revenue_growth_1y"), (years, f"revenue_cagr_{years}y")):
        label = (
            "Revenue growth, newest fiscal year"
            if span == 1
            else f"Revenue, compound annual growth over {span} fiscal years"
        )
        if len(ends) < span + 1:
            results.append(
                _result(f"{key}:{book.cik}", key, label, None, "percent", "", "", [], "", as_of,
                        reason=f"Fewer than {span + 1} fiscal years of revenue in the facts.")
            )
            continue
        now, then = annual[ends[-1]], annual[ends[-1 - span]]
        value = None
        reason = ""
        if then.value <= 0 or now.value <= 0:
            reason = "A revenue that is not positive: no growth rate."
        else:
            value = ((now.value / then.value) ** (1 / span) - 1) * 100
        results.append(
            _result(
                f"{key}:{book.cik}:{ends[-1].isoformat()}",
                key,
                label,
                value,
                "percent",
                percent_text(value or 0, signed=True),
                f"({usd_text(now.value)} ÷ {usd_text(then.value)})^(1/{span}) − 1",
                [fact_input("Revenue", now.refs[0]), fact_input("Revenue", then.refs[0])],
                f"{label}: {percent_text(value or 0, signed=True)} a year, from fiscal year ended "
                f"{ends[-1 - span].isoformat()} to {ends[-1].isoformat()}.",
                as_of,
                reason=reason,
            )
        )
    return results
