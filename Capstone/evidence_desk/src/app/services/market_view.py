"""The market view of one company: valuation now, what the price implies, and reactions to 8-Ks.

One job: read the company's facts filed by the price's date, read the price (supplied,
or from a price source), and hand them to :mod:`app.core.valuation`,
:mod:`app.core.reverse_dcf` and :mod:`app.core.reaction`; read SEC's revenue frames for
the spread of ten-year growth of companies of the company's size
(:func:`app.core.base_rates.growth_distribution`); list the 8-Ks filed in the
:data:`EVENT_LOOKBACK_DAYS` before the as-of date and pick those of the claim's
categories (:func:`app.core.events.claim_categories`), or the one named.

Nothing is read from after the as-of date: the facts are those filed by the price's
date, the price's date is not after the as-of date, and the closes are cut at it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from app.core import events as event_rules
from app.core.analysis_models import (
    AnalysisResult,
    Distribution,
    EventReaction,
    GridCell,
    MarketView,
    ResultInput,
    ReverseDcf,
)
from app.core.base_rates import growth_distribution
from app.core.claim_eval import Measures
from app.core.documents import FilingRef
from app.core.facts import FactBook, FactsError
from app.core.frames import admitted_years, cutoff
from app.core.metrics import percent_text, usd_text
from app.core.models import Company
from app.core.periods import fiscal_calendar
from app.core.ports import FilingSource, SourceError
from app.core.price_series import PriceSeries, close_on_or_before, closes_until
from app.core.reaction import ESTIMATION_DAYS, event_reaction
from app.core.reverse_dcf import DcfAssumptions, implied_growth, sensitivity
from app.core.valuation import Price, Valuation, shares_outstanding, trailing_growth, valuation
from app.services.outside_view import load_panel
from app.sources.frames import FramesSource

DISCOUNT_RATE = 9.0
TERMINAL_GROWTH = 3.0
TAX_RATE = 21.0
FALLBACK_SALES_TO_CAPITAL = 1.5
DCF_YEARS = 10
SIZE_BAND = 2.0
EVENT_LOOKBACK_DAYS = 400
MAX_REACTIONS = 3
LABEL_NOTE = (
    "Arithmetic under stated assumptions, not a forecast and not advice: it says what "
    "constant growth the price would need if every assumption below held."
)


@dataclass(frozen=True)
class DcfInputs:
    """The reverse DCF's assumptions a request may set; None takes the default."""

    discount_rate: float | None = None
    terminal_growth: float | None = None
    tax_rate: float | None = None
    operating_margin: float | None = None
    sales_to_capital: float | None = None


def _sales_to_capital(found: Valuation) -> tuple[float, str]:
    revenue, equity, debt, cash = found.revenue, found.equity, found.debt, found.cash
    parts = (revenue, equity, debt, cash)
    if any(p is None or p.value is None for p in parts):
        return FALLBACK_SALES_TO_CAPITAL, (
            f"sales-to-capital {FALLBACK_SALES_TO_CAPITAL:g} (a stated default: the company's "
            "invested capital could not be read)"
        )
    assert revenue and equity and debt and cash
    assert revenue.value and equity.value is not None and debt.value is not None
    assert cash.value is not None
    invested = equity.value + debt.value - cash.value
    if invested <= 0:
        return FALLBACK_SALES_TO_CAPITAL, (
            f"sales-to-capital {FALLBACK_SALES_TO_CAPITAL:g} (a stated default: invested capital "
            f"= equity + debt − cash and securities is {usd_text(invested)}, not positive)"
        )
    ratio = revenue.value / invested
    return ratio, (
        f"sales-to-capital {ratio:.2f}: trailing revenue {usd_text(revenue.value)} ÷ invested "
        f"capital {usd_text(invested)} (equity {usd_text(equity.value)} + debt "
        f"{usd_text(debt.value)} − cash and securities {usd_text(cash.value)}, {equity.period}); "
        "each dollar of new revenue is assumed to need capital at this ratio"
    )


def reverse_dcf(
    ticker: str,
    found: Valuation,
    inputs: DcfInputs,
    *,
    own_growth: list[AnalysisResult],
    spread: Callable[[float], Distribution] | None,
    as_of: str,
    price_day: str,
) -> ReverseDcf:
    """The implied ten-year growth, its grid and its comparisons; cannot_compute when inputs lack."""
    rid = f"reverse_dcf:{ticker}:{price_day}"
    base = ReverseDcf(
        id=rid,
        kind="reverse_dcf",
        label="Revenue growth the price implies (reverse DCF)",
        unit="percent",
        data_origin="market_prices",
        as_of=as_of,
        label_note=LABEL_NOTE,
        comparisons=own_growth,
    )
    revenue, income = found.revenue, found.operating_income
    target = found.enterprise_value
    missing = [
        text
        for ok, text in (
            (target is not None, "the enterprise value"),
            (revenue is not None and revenue.value and revenue.value > 0, "a positive trailing revenue"),
            (income is not None and income.value is not None, "the trailing operating income"),
        )
        if not ok
    ]
    if missing:
        base.outcome = "cannot_compute"
        base.reason = f"Needs {', '.join(missing)}."
        base.reading = base.reason
        return base
    assert revenue is not None and revenue.value and income is not None and income.value is not None
    assert target is not None
    margin = inputs.operating_margin
    margin_text = "stated on the request"
    if margin is None:
        margin = income.value / revenue.value * 100
        margin_text = (
            f"the trailing operating margin, {usd_text(income.value)} ÷ {usd_text(revenue.value)}"
        )
    s2c, s2c_text = (
        (inputs.sales_to_capital, f"sales-to-capital {inputs.sales_to_capital:g}, stated on the request")
        if inputs.sales_to_capital is not None
        else _sales_to_capital(found)
    )
    try:
        assumptions = DcfAssumptions(
            revenue=revenue.value,
            operating_margin=margin,
            tax_rate=TAX_RATE if inputs.tax_rate is None else inputs.tax_rate,
            sales_to_capital=s2c,
            discount_rate=DISCOUNT_RATE if inputs.discount_rate is None else inputs.discount_rate,
            terminal_growth=TERMINAL_GROWTH if inputs.terminal_growth is None else inputs.terminal_growth,
            years=DCF_YEARS,
        )
    except ValueError as exc:
        base.outcome = "cannot_compute"
        base.reason = f"The assumptions are impossible: {exc}."
        base.reading = base.reason
        return base
    solved = implied_growth(target, assumptions)
    base.target = f"enterprise value {usd_text(target)}"
    base.inputs = [
        ResultInput(
            label="Enterprise value (the target)",
            value=target,
            display=usd_text(target),
            source="computed: market value + debt − cash and securities",
            date=price_day,
        ),
        *revenue.inputs,
        *income.inputs,
    ]
    base.assumptions = [
        f"Starting revenue {usd_text(revenue.value)} ({revenue.label}).",
        f"Operating margin {assumptions.operating_margin:.1f}%, every year: {margin_text}.",
        f"Tax on operating profit {assumptions.tax_rate:g}%"
        + (" (the US federal rate, a stated default)." if inputs.tax_rate is None else "."),
        s2c_text[0].upper() + s2c_text[1:] + ".",
        f"Discount rate {assumptions.discount_rate:g}% a year"
        + (" (a stated default, near a long-run US equity return)." if inputs.discount_rate is None else "."),
        f"After {assumptions.years} years, growth of {assumptions.terminal_growth:g}% a year forever.",
        "Cash flow = revenue × margin × (1 − tax) − (revenue − last year's revenue) ÷ "
        "sales-to-capital; discounted at the end of each year; compared with the enterprise value.",
    ]
    base.grid = [
        GridCell(
            discount_rate=cell.discount_rate,
            operating_margin=cell.operating_margin,
            implied_growth=cell.implied_growth,
            display=percent_text(cell.implied_growth) if cell.implied_growth is not None else "n/a",
        )
        for cell in sensitivity(target, assumptions)
    ]
    base.note = solved.note
    if solved.growth is None:
        base.outcome = "cannot_compute"
        base.reason = solved.reason
        base.reading = solved.reason
        return base
    base.value = solved.growth
    base.display = f"{percent_text(solved.growth)} a year for {assumptions.years} years"
    base.formula = (
        f"PV(g) = enterprise value {usd_text(target)}, solved for g between −50% and +100%"
    )
    own = next(
        (c for c in own_growth if c.kind.startswith("revenue_cagr") and c.value is not None), None
    )
    compare = (
        f"; the company's own revenue grew {own.display} a year over its last three fiscal years"
        if own
        else ""
    )
    outside = ""
    if spread is not None:
        base.distribution = spread(solved.growth)
        dist = base.distribution
        if dist.n:
            outside = (
                f"; of {dist.n} ten-year spans of companies of its size, {dist.at_least} grew at "
                f"least that fast (median {dist.displays['p50']})"
            )
    base.reading = (
        f"At these assumptions the enterprise value of {usd_text(target)} needs revenue to grow "
        f"{percent_text(solved.growth)} a year for {assumptions.years} years{compare}{outside}."
    )
    return base


def _reactions(
    company: Company,
    filings: FilingSource,
    stock: PriceSeries,
    index: PriceSeries | None,
    *,
    as_of: date,
    claim: str,
    accession: str | None,
    days: int,
) -> tuple[list[EventReaction], list[str]]:
    notes: list[str] = []
    refs = filings.current_reports(
        company,
        (as_of - timedelta(days=EVENT_LOOKBACK_DAYS)).isoformat(),
        as_of.isoformat(),
    )
    if accession:
        chosen = [ref for ref in refs if ref.accession == accession]
        if not chosen:
            notes.append(f"No 8-K {accession} was filed in the {EVENT_LOOKBACK_DAYS} days to {as_of}.")
    else:
        wanted = {str(c) for c in event_rules.claim_categories(claim)}
        if not wanted:
            notes.append("The claim names no 8-K category (by the app's rule); no 8-K is chosen.")
            return [], notes
        chosen = [
            ref
            for ref in refs
            if wanted & {str(c) for c in event_rules.event_categories(ref.items)}
        ][:MAX_REACTIONS]
        if not chosen:
            notes.append(
                f"No 8-K of the claim's categories ({', '.join(sorted(wanted))}) was filed in the "
                f"{EVENT_LOOKBACK_DAYS} days to {as_of.isoformat()}."
            )
    return [_reaction(company, ref, stock, index, as_of=as_of, days=days) for ref in chosen], notes


def _reaction(
    company: Company,
    ref: FilingRef,
    stock: PriceSeries,
    index: PriceSeries | None,
    *,
    as_of: date,
    days: int,
) -> EventReaction:
    filed = date.fromisoformat(ref.filed_date)
    categories = [str(c) for c in event_rules.event_categories(ref.items)]
    result = EventReaction(
        id=f"reaction:{company.ticker}:{ref.accession}:{days}",
        kind="event_reaction",
        label=f"The market's move after the 8-K of {ref.filed_date} (items {', '.join(ref.items) or 'none listed'})",
        unit="percent",
        data_origin="market_prices",
        as_of=as_of.isoformat(),
        accession=ref.accession,
        filed=ref.filed_date,
        items=list(ref.items),
        categories=categories,
        estimation=(
            f"Normal move: the sample standard deviation of the stock's daily excess return over "
            f"the {ESTIMATION_DAYS} trading days to the close before the filing, × √days."
        ),
        assumptions=[
            "Start: the last close before the filing day (an 8-K filed after the close moves the next day's price).",
            "Excess return = the stock's return − the index's over the same dates; not adjusted for beta.",
            "Nothing after the as-of date is read.",
        ],
    )
    windows = event_reaction(
        list(stock.closes),
        list(index.closes) if index else None,
        filed,
        days=days,
        as_of=as_of,
    )
    if isinstance(windows, str):
        result.outcome = "cannot_compute"
        result.reason = windows
        result.reading = windows
        return result
    result.windows = windows
    first = windows[0]
    result.value = first.excess
    result.display = first.line
    index_text = (
        f" − ({index.symbol} {first.end} ÷ {first.start} − 1)" if index and first.index_return is not None else ""
    )
    result.formula = f"({stock.symbol} {first.end} ÷ {first.start} − 1){index_text}"
    result.reading = f"After the 8-K of {ref.filed_date}: {first.line}."
    for series, day in ((stock, first.start), (stock, first.end)):
        close = close_on_or_before(list(series.closes), date.fromisoformat(day))
        if close is not None:
            result.inputs.append(
                ResultInput(
                    label=f"{series.symbol} close",
                    value=close.value,
                    display=f"{close.value:,.2f}",
                    source=series.source,
                    date=close.day.isoformat(),
                    url=series.url,
                )
            )
    if index is not None:
        for day in (first.start, first.end):
            close = close_on_or_before(list(index.closes), date.fromisoformat(day))
            if close is not None:
                result.inputs.append(
                    ResultInput(
                        label=f"{index.symbol} close",
                        value=close.value,
                        display=f"{close.value:,.2f}",
                        source=index.source,
                        date=close.day.isoformat(),
                        url=index.url,
                    )
                )
    return result


def market_view(
    company: Company,
    filings: FilingSource,
    frames: FramesSource | None,
    *,
    price: Price,
    today: date,
    as_of: date | None = None,
    claim: str = "",
    dcf: DcfInputs | None = None,
    stock: PriceSeries | None = None,
    index: PriceSeries | None = None,
    accession: str | None = None,
    days: int = 3,
) -> MarketView:
    """The market view. Raises :class:`SourceError` when EDGAR cannot give the facts.

    Raises ValueError when the price is dated after the as-of date (or after today).
    """
    day = as_of or today
    if price.day > day:
        raise ValueError(f"the price's date {price.day} is after the as-of date {day}")
    view = MarketView(
        company=company,
        claim=claim,
        as_of=day.isoformat(),
        price_source=price.source,
    )
    payload = filings.company_facts(company)
    try:
        book = FactBook(payload, as_of=price.day)
    except FactsError as exc:
        raise SourceError(f"The XBRL company facts could not be read: {exc}") from exc
    measures = Measures(book, fiscal_calendar(payload, as_of=price.day))
    shares = shares_outstanding(payload, price.day)
    found = valuation(company.ticker, price, shares, measures, day.isoformat())
    view.valuation = found.results
    own = trailing_growth(book, as_of=day.isoformat())
    spread: Callable[[float], Distribution] | None = None
    if frames is not None and found.revenue is not None and found.revenue.value:
        years = admitted_years(as_of, today)
        panel, _, _ = load_panel(frames, [("revenue", y) for y in years], cutoff(as_of, today))
        size = found.revenue.value

        def spread(at_least: float) -> Distribution:
            return growth_distribution(
                panel,
                size / SIZE_BAND,
                size * SIZE_BAND,
                span=DCF_YEARS,
                at_least=at_least,
                exclude=company.cik,
            )

        if frames.not_read:
            view.notes.append(f"Frames not on disk, not read: {len(frames.not_read)}.")
    view.reverse_dcf = reverse_dcf(
        company.ticker,
        found,
        dcf or DcfInputs(),
        own_growth=own,
        spread=spread,
        as_of=day.isoformat(),
        price_day=price.day.isoformat(),
    )
    if stock is not None:
        stock = PriceSeries(stock.symbol, tuple(closes_until(stock.closes, day)), stock.source, stock.url, stock.retrieved)
        if index is not None:
            index = PriceSeries(index.symbol, tuple(closes_until(index.closes, day)), index.source, index.url, index.retrieved)
        view.reactions, notes = _reactions(
            company, filings, stock, index, as_of=day, claim=claim, accession=accession, days=days
        )
        view.notes += notes
    else:
        view.notes.append("No daily closes were given; no reaction to an 8-K is computed.")
    return view


def describe(view: MarketView) -> list[str]:
    """The view as lines of text for the command line."""
    lines = [
        f"Market view: {view.company.name} ({view.company.ticker}) as of {view.as_of}",
        f"Price: {view.price_source}",
        "",
    ]
    for result in view.valuation:
        lines.append(f"[{result.id}] {result.label}: {result.display}")
        lines.append(f"  {result.reading or result.reason}")
        if result.formula:
            lines.append(f"  formula: {result.formula}")
        lines.extend(
            f"  input: {i.label} = {i.display} ({i.source}, {i.date}"
            + (f", filed {i.filed}" if i.filed else "")
            + ")"
            for i in result.inputs
        )
    dcf = view.reverse_dcf
    if dcf is not None:
        lines += ["", f"[{dcf.id}] {dcf.label}: {dcf.display}", f"  {dcf.label_note}"]
        lines.append(f"  {dcf.reading or dcf.reason}")
        if dcf.note:
            lines.append(f"  {dcf.note}")
        lines.extend(f"  - {a}" for a in dcf.assumptions)
        if dcf.grid:
            margins = sorted({c.operating_margin for c in dcf.grid})
            lines.append("  grid (rows: discount rate; columns: operating margin " + ", ".join(f"{m:.1f}%" for m in margins) + ")")
            for rate in sorted({c.discount_rate for c in dcf.grid}):
                row = [c.display for c in dcf.grid if c.discount_rate == rate]
                lines.append(f"    {rate:g}%: " + "  ".join(row))
        for comparison in dcf.comparisons:
            lines.append(f"  compare: {comparison.reading or comparison.reason}")
        if dcf.distribution is not None:
            d = dcf.distribution
            lines.append(
                f"  outside: {d.definition} n={d.n}, dropped {d.dropped}; "
                + ", ".join(f"{k} {v}" for k, v in d.displays.items())
            )
    for reaction in view.reactions:
        lines += ["", f"[{reaction.id}] {reaction.label}"]
        lines.append(f"  {reaction.reading or reaction.reason}")
        lines.extend(f"  {w.name}: {w.line} ({w.start} to {w.end})" for w in reaction.windows)
    lines.append("")
    lines.extend(f"Note: {note}" for note in view.notes)
    return lines
