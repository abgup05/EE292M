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
- **enterprise value** = market value + total debt − cash and marketable securities, both
  **at the newest balance-sheet date** (the newest date the facts give total assets for).
  Debt is the catalogue's ``total_debt``; when the company does not tag its parts on
  that balance sheet, the first of :data:`DEBT_TOTALS` that it does tag there. A balance
  last reported on an older date is never carried forward: the enterprise value is then
  not computed, and says which balance is missing (a bank tags neither, and an
  enterprise value means little for one). Leases, preferred stock and minority
  interests are left out;
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

from ed_v14.core.claim_eval import Measures
from ed_v14.core.claimtest import Period
from ed_v14.core.facts import CLAIM_GROUPS, FactBook, filed_by
from ed_v14.core.frames import years_apart
from ed_v14.core.metric_models import FactRef
from ed_v14.core.metrics import percent_text, usd_text
from ed_v14.core.view_models import AnalysisResult, ResultInput, ResultUnit

SHARE_JUMP = 1.25
DEI_SHARES = "EntityCommonStockSharesOutstanding"
GAAP_SHARES = "CommonStockSharesOutstanding"


@dataclass(frozen=True)
class Price:
    """A price per share on a day, and where it came from in words.

    ``known`` is the day the source made it public, when that is later than ``day`` (a
    13F's filing date): a view as of a date may use a price only when it was known by
    then. ``inputs`` are the numbers the price was computed from, when it was computed;
    ``confirmed`` is True when a second independent source gave the same price.
    ``needs_confirmation`` is True for a price that was inferred, not quoted (a 13F's
    position value over its shares): the market view computes nothing from such a price
    unless it is ``confirmed``. A price supplied on a request needs none: it is used as
    given, and its ``source`` says it was not checked.
    """

    value: float
    day: date
    source: str
    known: date | None = None
    url: str = ""
    note: str = ""
    inputs: tuple[ResultInput, ...] = ()
    confirmed: bool = False
    needs_confirmation: bool = False


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


def _entries(
    facts: object, taxonomy: str, concept: str, unit: str = "shares"
) -> list[dict[str, Any]]:
    try:
        rows = facts["facts"][taxonomy][concept]["units"][unit]  # type: ignore[index]
    except KeyError, TypeError:
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
        except KeyError, TypeError, ValueError:
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
    """A number read from the facts for a valuation, or None and why, with its inputs.

    ``basis`` says what a flow was summed over: "four quarters" or "fiscal year" ("" for
    a balance, and for a flow that could not be read).
    """

    label: str
    value: float | None
    period: str = ""
    formula: str = ""
    inputs: list[ResultInput] = field(default_factory=list)
    note: str = ""
    basis: str = ""


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


FOUR_QUARTERS, FISCAL_YEAR = "four quarters", "fiscal year"


def trailing(measures: Measures, metric: str, label: str, *, year_only: bool = False) -> Figure:
    """The trailing four quarters of a flow; the newest fiscal year when they cannot be summed.

    With ``year_only`` the fiscal year is read whether or not four quarters can be summed,
    to put a figure on the same basis as one that had to fall back.
    """
    notes: list[str] = []
    for period in (Period("FY"),) if year_only else (Period("TTM"), Period("FY")):
        slot = measures.bind(period, metric)
        if isinstance(slot, str):
            notes.append(slot)
            continue
        outcome = measures.outcome(metric, slot)
        if outcome.value is None:
            notes.append(outcome.note)
            continue
        used = [value.refs[0] for value in outcome.used]
        note = (
            "" if period.kind == "TTM" else "Four quarters could not be summed; fiscal year used."
        )
        return Figure(
            label=f"{label}, {slot.words}",
            value=outcome.value,
            period=slot.end.isoformat(),
            formula=outcome.formula,
            inputs=[fact_input(label, ref) for ref in used],
            note="" if year_only else note,
            basis=FOUR_QUARTERS if period.kind == "TTM" else FISCAL_YEAR,
        )
    return Figure(label=label, value=None, note=" ".join(n for n in notes if n))


def margin_sides(
    measures: Measures, revenue: Figure, income: Figure
) -> tuple[Figure, Figure] | None:
    """Operating income and revenue over one and the same period, for a margin; None when
    they cannot be had so.

    Each of the two is read over four quarters, or over the fiscal year when four
    quarters cannot be summed, on its own. When one fell back and the other did not, both
    are read over the fiscal year: a margin of a fiscal year's income over four later
    quarters' revenue is a margin of nothing. (income, revenue).
    """
    if revenue.value is None or income.value is None:
        return None
    if revenue.basis == income.basis and revenue.period == income.period:
        return income, revenue
    year_income = trailing(measures, "operating_income", "Operating income", year_only=True)
    year_revenue = trailing(measures, "revenue", "Revenue", year_only=True)
    if (
        year_income.value is None
        or year_revenue.value is None
        or year_income.period != year_revenue.period
    ):
        return None
    return year_income, year_revenue


# Totals of debt a company may tag instead of the parts the catalogue adds, in the order
# tried; each with what it is, which the result prints. LongTermDebt is last: some filers
# use it for the non-current part alone.
DEBT_TOTALS: tuple[tuple[str, str], ...] = (
    ("DebtLongtermAndShorttermCombinedAmount", "long-term and short-term debt combined"),
    (
        "DebtInstrumentCarryingAmount",
        "the carrying amount of its debt instruments, from the debt note",
    ),
    (
        "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
        "long-term debt and finance leases with their current maturities; short-term "
        "borrowings are not in it",
    ),
    ("LongTermDebt", "long-term debt; it may leave out the current portion"),
)
BALANCE_SHEET_ANCHOR = "total_assets"


def balance_sheet_date(measures: Measures) -> date | None:
    """The newest date the facts give total assets for: the newest balance sheet filed."""
    return max(measures.book.instants(BALANCE_SHEET_ANCHOR), default=None)


def balance(measures: Measures, metric: str, label: str) -> Figure:
    """A balance at the newest balance-sheet date; never one carried from an older date."""
    anchor = balance_sheet_date(measures)
    if anchor is None:
        return Figure(label=label, value=None, note="The facts hold no balance sheet.")
    dates = measures.instants(metric)
    if anchor not in dates:
        last = max(dates, default=None)
        return Figure(
            label=label,
            value=None,
            note=(
                f"Not reported on the newest balance sheet ({anchor.isoformat()})"
                + (f"; last reported for {last.isoformat()}." if last else "; never reported.")
            ),
        )
    slot = measures.slot("instant", anchor)
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


def _raw_at(
    companyfacts: object, concept: str, anchor: date, as_of: date
) -> tuple[float, dict[str, Any]] | None:
    """A us-gaap USD concept's value at ``anchor`` from the newest filing by ``as_of``."""
    rows = [
        row
        for row in _entries(companyfacts, "us-gaap", concept, "USD")
        if row.get("end") == anchor.isoformat() and "start" not in row and filed_by(row, as_of)
    ]
    if not rows:
        return None
    row = max(rows, key=lambda r: (str(r.get("filed", "")), str(r.get("accn", ""))))
    try:
        return float(row["val"]), row
    except KeyError, TypeError, ValueError:
        return None


def _raw_input(label: str, concept: str, value: float, row: dict[str, Any]) -> ResultInput:
    return ResultInput(
        label=f"{label} ({concept})",
        value=value,
        display=usd_text(value),
        source=f"SEC company facts, {row.get('form', '')} {row.get('accn', '')}",
        date=str(row.get("end", "")),
        filed=str(row.get("filed", "")),
    )


def total_debt(measures: Measures, companyfacts: object, as_of: date) -> Figure:
    """Total debt at the newest balance-sheet date: the catalogue's, else a tagged total."""
    label = "Total debt"
    found = balance(measures, "total_debt", label)
    anchor = balance_sheet_date(measures)
    if found.value is not None or anchor is None:
        return found
    for concept, meaning in DEBT_TOTALS:
        raw = _raw_at(companyfacts, concept, anchor, as_of)
        if raw is None:
            continue
        value, row = raw
        return Figure(
            label=f"{label}, as of {anchor.isoformat()}",
            value=value,
            period=anchor.isoformat(),
            inputs=[_raw_input(label, concept, value, row)],
            note=(
                "The company does not tag long-term debt's non-current part on this balance "
                f"sheet; its tagged {concept} is used instead ({meaning})."
            ),
        )
    return Figure(
        label=label,
        value=None,
        note=(
            f"{found.note} No total of debt ({', '.join(c for c, _ in DEBT_TOTALS)}) is tagged "
            "there either. (A bank or an insurer tags its funding otherwise, and an enterprise "
            "value means little for one.)"
        ),
    )


def cash_and_securities(measures: Measures, companyfacts: object, as_of: date) -> Figure:
    """Cash and current marketable securities at the newest balance-sheet date.

    The catalogue's measure, which reads current securities under each tag of its group
    (:data:`app.core.facts.CLAIM_GROUPS`) and counts them as zero when the company tags
    none; then the result says so.
    """
    label = "Cash and marketable securities"
    found = balance(measures, "cash_and_securities", label)
    anchor = balance_sheet_date(measures)
    if found.value is None or anchor is None:
        if found.value is None:
            found.note += (
                " (A bank or an insurer tags its cash otherwise, and an enterprise value means "
                "little for one.)"
            )
        return found
    listed = CLAIM_GROUPS["marketable_securities"].concepts
    if any(concept in i.label for i in found.inputs for concept in listed):
        return found
    found.note = (
        "No current marketable securities are tagged on this balance sheet "
        f"({', '.join(listed)}): counted as zero."
    )
    return found


def money(value: float) -> str:
    """USD for reading, with trillions: "$5.50T"; under a trillion as the app prints it."""
    if abs(value) >= 1e12:
        return f"{'-' if value < 0 else ''}${abs(value) / 1e12:.2f}T"
    return usd_text(value)


# Results


@dataclass
class Valuation:
    """The valuation's results and the numbers the reverse DCF starts from."""

    results: list[AnalysisResult]
    market_value: float | None = None
    enterprise_value: float | None = None
    revenue: Figure | None = None
    operating_income: Figure | None = None
    # Operating income and revenue over one period, for the reverse DCF's margin
    # (margin_sides); None when the two cannot be read over the same period.
    margin: tuple[Figure, Figure] | None = None
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
        filed=price.known.isoformat() if price.known else "",
        url=price.url,
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


def share_count_caution(shares: Shares, later: Shares | str | None) -> str:
    """A caution when the next cover page's share count is far from the one used.

    ``later`` is the count the newest filing by the view's date reports. A count that
    moved by more than :data:`SHARE_JUMP` between the two cover pages is a split or a
    large issue; if it fell between the count's date and the price's, the market value
    is off by that factor, and the facts cannot say on which side it fell.
    """
    if later is None or isinstance(later, str) or later.accession == shares.accession:
        return ""
    ratio = later.value / shares.value
    if 1 / SHARE_JUMP <= ratio <= SHARE_JUMP:
        return ""
    return (
        f"The share count moved by a factor of {ratio:.2f} between the cover page used "
        f"({shares.day.isoformat()}) and the next ({later.day.isoformat()}): a split or a large "
        "issue. If it took effect before the price's date, the market value here is off by "
        "that factor."
    )


def valuation(
    ticker: str,
    price: Price,
    shares: Shares | str,
    measures: Measures,
    as_of: str,
    *,
    companyfacts: object = None,
    later_shares: Shares | str | None = None,
) -> Valuation:
    """Market value, enterprise value and the multiples, each with its inputs and dates.

    ``companyfacts`` is the raw payload, read only for a tagged total of debt when the
    catalogue's parts are not on the newest balance sheet (:func:`total_debt`).
    """
    stamp = f"{ticker}:{price.day.isoformat()}"
    results: list[AnalysisResult] = []
    out = Valuation(results)
    if isinstance(shares, str):
        results.append(
            _result(
                f"market_value:{stamp}",
                "market_value",
                "Market value",
                None,
                "USD",
                "",
                "",
                [_price_input(price)],
                "",
                as_of,
                reason=shares,
            )
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
            money(market),
            f"${price.value:,.2f} × {shares.value:,.0f} shares",
            [_price_input(price), *price.inputs, _shares_input(shares)],
            f"At ${price.value:,.2f} on {price.day.isoformat()}, the {shares.value:,.0f} shares "
            f"outstanding on {shares.day.isoformat()} are worth {money(market)}.",
            as_of,
            note=" ".join(
                n for n in (price.note, class_note, share_count_caution(shares, later_shares)) if n
            ),
        )
    )
    out.debt = total_debt(measures, companyfacts, price.day)
    out.cash = cash_and_securities(measures, companyfacts, price.day)
    out.equity = balance(measures, "equity", "Shareholders' equity")
    out.revenue = trailing(measures, "revenue", "Revenue")
    out.operating_income = trailing(measures, "operating_income", "Operating income")
    out.margin = margin_sides(measures, out.revenue, out.operating_income)
    net_income = trailing(measures, "net_income", "Net income")
    fcf = trailing(measures, "free_cash_flow", "Free cash flow")
    ev_reason = next((f"{f.label}: {f.note}" for f in (out.debt, out.cash) if f.value is None), "")
    if not ev_reason:
        assert out.debt.value is not None and out.cash.value is not None
        out.enterprise_value = market + out.debt.value - out.cash.value
    ev_inputs = [_price_input(price), _shares_input(shares)]
    for figure in (out.debt, out.cash):
        ev_inputs += figure.inputs
    results.append(
        _result(
            f"enterprise_value:{stamp}",
            "enterprise_value",
            "Enterprise value",
            out.enterprise_value,
            "USD",
            money(out.enterprise_value or 0),
            (f"{money(market)} + {money(out.debt.value or 0)} − {money(out.cash.value or 0)}"),
            ev_inputs,
            (
                f"Market value {money(market)} plus total debt {money(out.debt.value or 0)} "
                f"less cash and marketable securities {money(out.cash.value or 0)} "
                f"({out.debt.period}) is {money(out.enterprise_value or 0)}."
            ),
            as_of,
            reason=ev_reason,
            assumptions=[
                "Enterprise value = market value + total debt − cash and marketable securities "
                "(leases, preferred stock and minority interests are left out).",
                "Both balances are of the newest balance sheet filed by the price's date; one "
                "last reported for an older date is not carried forward.",
                "Non-current marketable securities are not subtracted: for a company that "
                "holds a long-dated portfolio the enterprise value here is higher than one "
                "that counts it.",
            ],
            note=" ".join(n for n in (out.debt.note, out.cash.note) if n)
            if out.enterprise_value is not None
            else "",
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
        reason = f"{figure.label} is not positive ({money(figure.value)}): no multiple."
    value: float | None = None
    display = formula = reading = ""
    if not reason:
        assert top is not None and figure.value is not None
        if inverse:
            value = figure.value / top * 100
            display = percent_text(value)
            formula = f"{money(figure.value)} ÷ {money(top)}"
            reading = (
                f"{figure.label} of {money(figure.value)} is {display} of the market value of "
                f"{money(top)}."
            )
        else:
            value = top / figure.value
            display = _multiple(value)
            formula = f"{money(top)} ÷ {money(figure.value)}"
            reading = (
                f"{label} is {display}: {money(top)} over {figure.label[0].lower()}"
                f"{figure.label[1:]} of {money(figure.value)}."
            )
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
                _result(
                    f"{key}:{book.cik}",
                    key,
                    label,
                    None,
                    "percent",
                    "",
                    "",
                    [],
                    "",
                    as_of,
                    reason=f"Fewer than {span + 1} fiscal years of revenue in the facts.",
                )
            )
            continue
        now, then = annual[ends[-1]], annual[ends[-1 - span]]
        value = None
        reason = ""
        if not years_apart(ends[-1], ends[-1 - span], span):
            reason = (
                f"The fiscal years in the facts are not consecutive: {ends[-1 - span].isoformat()} "
                f"is not {span} year(s) before {ends[-1].isoformat()}."
            )
        elif then.value <= 0 or now.value <= 0:
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
