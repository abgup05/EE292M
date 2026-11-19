"""The market view of one company: valuation now, what the price implies, and reactions to 8-Ks.

One job: ask the price provider for the price as of the date (the user's own, or the
newest quarter-end price SEC's 13F filings give: :mod:`app.sources.prices`,
:mod:`app.sources.thirteenf`), read the company's facts filed by the price's date, and
hand them to :mod:`app.core.valuation`,
:mod:`app.core.reverse_dcf` and :mod:`app.core.reaction`; read SEC's revenue frames for
the spread of ten-year growth of companies of the company's size
(:func:`app.core.base_rates.growth_distribution`); list the 8-Ks filed in the
:data:`EVENT_LOOKBACK_DAYS` before the as-of date and pick those of the claim's
categories (:func:`app.core.events.claim_categories`), or the one named.

The reverse DCF is set beside three things a reader can check it against: the company's
own trailing growth, the spread of ten-year growth among filers that were its size, and
the revenue the implied growth reaches in year ten beside the largest revenue any filer
has reported. It is solved again with the operating margin at the industry's median,
because the margin held for ten years is the assumption a rich margin makes doubtful.

Nothing is read from after the as-of date: the price is dated on or before it and was
public from its source by then, the facts are those filed by the price's date (what the
price could know), and the closes are cut at it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, timedelta

from ed_v14.core import events as event_rules
from ed_v14.core.base_rates import growth_distribution, percentile
from ed_v14.core.claim_eval import Measures
from ed_v14.core.documents import FilingRef
from ed_v14.core.facts import FactBook, FactsError
from ed_v14.core.frames import Panel, admitted_years, cutoff
from ed_v14.core.metrics import percent_text, usd_text
from ed_v14.core.models import Company
from ed_v14.core.periods import fiscal_calendar
from ed_v14.core.ports import FilingSource, SourceError
from ed_v14.core.price_series import PriceSeries, close_on_or_before, closes_until
from ed_v14.core.reaction import ESTIMATION_DAYS, event_reaction
from ed_v14.core.reverse_dcf import DcfAssumptions, implied_growth, sensitivity
from ed_v14.core.valuation import (
    Valuation,
    money,
    shares_outstanding,
    trailing_growth,
    valuation,
)
from ed_v14.core.view_models import (
    AnalysisResult,
    Distribution,
    EventReaction,
    GridCell,
    MarketView,
    ResultInput,
    ReverseDcf,
)
from ed_v14.services.outside_view import INDUSTRY_FLOOR, load_panel
from ed_v14.sources.frames import FramesSource
from ed_v14.sources.prices import PriceProvider, PriceUnavailable

DISCOUNT_RATE = 9.0
TERMINAL_GROWTH = 3.0
TAX_RATE = 21.0
FALLBACK_SALES_TO_CAPITAL = 1.5
DCF_YEARS = 10
SIZE_BAND = 2.0
EVENT_LOOKBACK_DAYS = 400
MAX_REACTIONS = 3
MIN_PEERS_FOR_MARGIN = 5
LABEL_NOTE = (
    "Arithmetic under stated assumptions, not a forecast and not advice: it says what "
    "constant growth the price would need if every assumption below held."
)


@dataclass(frozen=True)
class Outside:
    """What SEC's frames add to the reverse DCF, each None when the frames cannot give it.

    ``spread`` gives the ten-year growth of filers of the company's size, counting those
    at least as fast as a rate; ``largest`` is the largest revenue any filer reported in
    the newest frame year (name, revenue, year); ``peer_margin`` the median and the 90th
    percentile of the operating margin of the company's industry class that year (median,
    90th percentile, members, class name, year).
    """

    spread: Callable[[float], Distribution] | None = None
    largest: tuple[str, float, int] | None = None
    peer_margin: tuple[float, float, int, str, int] | None = None


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
            f"= equity + debt − cash and securities is {money(invested)}, not positive)"
        )
    ratio = revenue.value / invested
    return ratio, (
        f"sales-to-capital {ratio:.2f}: trailing revenue {money(revenue.value)} ÷ invested "
        f"capital {money(invested)} (equity {money(equity.value)} + debt "
        f"{money(debt.value)} − cash and securities {money(cash.value)}, {equity.period}); "
        "each dollar of new revenue is assumed to need capital at this ratio"
    )


def reverse_dcf(
    ticker: str,
    found: Valuation,
    inputs: DcfInputs,
    *,
    own_growth: list[AnalysisResult],
    outside: Outside,
    as_of: str,
    price_day: str,
) -> ReverseDcf:
    """The implied growth, its grid and its comparisons; cannot_compute when inputs lack."""
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
            (
                revenue is not None and revenue.value and revenue.value > 0,
                "a positive trailing revenue",
            ),
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
            f"the trailing operating margin, {money(income.value)} ÷ {money(revenue.value)}"
        )
    s2c, s2c_text = (
        (
            inputs.sales_to_capital,
            f"sales-to-capital {inputs.sales_to_capital:g}, stated on the request",
        )
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
            terminal_growth=TERMINAL_GROWTH
            if inputs.terminal_growth is None
            else inputs.terminal_growth,
            years=DCF_YEARS,
        )
    except ValueError as exc:
        base.outcome = "cannot_compute"
        base.reason = f"The assumptions are impossible: {exc}."
        base.reading = base.reason
        return base
    solved = implied_growth(target, assumptions)
    base.target = f"enterprise value {money(target)}"
    base.inputs = [
        ResultInput(
            label="Enterprise value (the target)",
            value=target,
            display=money(target),
            source="computed: market value + debt − cash and securities",
            date=price_day,
        ),
        *revenue.inputs,
        *income.inputs,
    ]
    base.assumptions = [
        f"Starting revenue {money(revenue.value)} ({revenue.label}).",
        f"Operating margin {assumptions.operating_margin:.1f}%, every year: {margin_text}.",
        f"Tax on operating profit {assumptions.tax_rate:g}%"
        + (" (the US federal rate, a stated default)." if inputs.tax_rate is None else "."),
        s2c_text[0].upper() + s2c_text[1:] + ".",
        f"Discount rate {assumptions.discount_rate:g}% a year"
        + (
            " (a stated default, near a long-run US equity return)."
            if inputs.discount_rate is None
            else "."
        ),
        f"After {assumptions.years} years, growth of {assumptions.terminal_growth:g}% a year "
        "forever.",
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
        cells = [c for c in base.grid if c.implied_growth is not None]
        base.reading = (
            f"With the trailing operating margin of {assumptions.operating_margin:.1f}% held for "
            f"{assumptions.years} years, no constant revenue growth from −50% to +100% a year is "
            f"worth the enterprise value of {money(target)}: the price counts on a margin the "
            f"company does not have now. {len(cells)} of {len(base.grid)} cells of the grid "
            "(discount rate ±2 points, margin ±5 points) solve"
            + (
                f"; at a margin of {max(c.operating_margin for c in cells):.1f}% the growth "
                f"needed starts at {percent_text(min(c.implied_growth or 0 for c in cells))} a "
                "year."
                if cells
                else "."
            )
        )
        return base
    base.value = solved.growth
    base.display = f"{percent_text(solved.growth)} a year for {assumptions.years} years"
    base.formula = f"PV(g) = enterprise value {money(target)}, solved for g between −50% and +100%"
    reached = revenue.value * (1 + solved.growth / 100) ** assumptions.years
    base.implied_revenue = reached
    base.implied_revenue_display = money(reached)
    sentences = [
        f"At these assumptions the enterprise value of {money(target)} needs revenue to grow "
        f"{percent_text(solved.growth)} a year for {assumptions.years} years, from "
        f"{money(revenue.value)} to {money(reached)}."
    ]
    own = next(
        (c for c in own_growth if c.kind.startswith("revenue_cagr") and c.value is not None), None
    )
    if own:
        sentences.append(
            f"The company's own revenue grew {own.display} a year over its last three fiscal years."
        )
    if outside.largest is not None:
        name, most, year = outside.largest
        sentences.append(
            f"The largest revenue any filer reported for {year} is {money(most)} ({name}): "
            f"the implied year-{assumptions.years} revenue is {reached / most:.1f} times that."
        )
    if outside.spread is not None:
        base.distribution = outside.spread(solved.growth)
        dist = base.distribution
        if dist.n:
            sentences.append(
                f"Of {dist.n} ten-year spans of filers that started at its size (revenue of "
                f"{dist.band}; {dist.window}), {dist.at_least} grew at least that fast (median "
                f"{dist.displays['p50']} a year, 90th percentile {dist.displays['p90']}; "
                f"{dist.dropped} more could not be followed for ten years)."
            )
        else:
            sentences.append(
                "No filer that started at its size can be followed for ten years in the frames."
            )
    if outside.peer_margin is not None and inputs.operating_margin is None:
        median, top, members, class_name, year = outside.peer_margin
        for key, words, margin in (
            ("peer_median", "median", median),
            ("peer_p90", "90th percentile", top),
        ):
            base.scenarios.append(
                _margin_scenario(
                    f"{rid}:{key}",
                    words,
                    margin,
                    target,
                    assumptions,
                    members,
                    class_name,
                    year,
                    as_of,
                )
            )
            sentences.append(base.scenarios[-1].reading)
    solved_cells = [c.implied_growth for c in base.grid if c.implied_growth is not None]
    if solved_cells:
        sentences.append(
            f"Across the grid (discount rate ±2 points, margin ±5 points) the implied growth "
            f"runs from {percent_text(min(solved_cells))} to {percent_text(max(solved_cells))} a "
            f"year ({len(solved_cells)} of {len(base.grid)} cells solve)."
        )
    base.reading = " ".join(sentences)
    return base


def _margin_scenario(
    rid: str,
    words: str,
    margin: float,
    target: float,
    assumptions: DcfAssumptions,
    members: int,
    class_name: str,
    year: int,
    as_of: str,
) -> AnalysisResult:
    """The same model solved with the operating margin at a point of the industry's spread."""
    result = AnalysisResult(
        id=rid,
        kind=f"reverse_dcf_{rid.rsplit(':', 1)[-1]}_margin",
        label=f"Implied growth if the operating margin were the industry's {words}",
        unit="percent",
        data_origin="market_prices",
        as_of=as_of,
        assumptions=[
            f"Operating margin {margin:.1f}%: the {words} of the {members} {class_name} with an "
            f"operating margin in {year} (SEC frames); every other assumption unchanged.",
        ],
    )
    lead = (
        f"With the operating margin at the industry's {words} of {margin:.1f}% (n = {members}, "
        f"{year}) instead of {assumptions.operating_margin:.1f}%"
    )
    try:
        varied = replace(assumptions, operating_margin=margin)
    except ValueError as exc:
        result.outcome, result.reason = "cannot_compute", f"The assumptions are impossible: {exc}."
        result.reading = result.reason
        return result
    solved = implied_growth(target, varied)
    result.note = solved.note
    if solved.growth is None:
        result.outcome, result.reason = "cannot_compute", solved.reason
        result.reading = f"{lead}, no growth from −50% to +100% a year reaches the price."
        return result
    result.value = solved.growth
    result.display = f"{percent_text(solved.growth)} a year for {assumptions.years} years"
    result.formula = (
        f"PV(g) = enterprise value {money(target)} with the operating margin {margin:.1f}%"
    )
    result.reading = f"{lead}, the same price needs {percent_text(solved.growth)} a year."
    return result


def reactions(
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
    """The reaction to each 8-K chosen (the one named, else those of the claim's categories).

    The closes are cut at ``as_of`` here, whatever the caller passed.
    """
    stock = PriceSeries(
        stock.symbol,
        tuple(closes_until(stock.closes, as_of)),
        stock.source,
        stock.url,
        stock.retrieved,
    )
    if index is not None:
        index = PriceSeries(
            index.symbol,
            tuple(closes_until(index.closes, as_of)),
            index.source,
            index.url,
            index.retrieved,
        )
    notes: list[str] = []
    refs = filings.current_reports(
        company,
        (as_of - timedelta(days=EVENT_LOOKBACK_DAYS)).isoformat(),
        as_of.isoformat(),
    )
    if accession:
        chosen = [ref for ref in refs if ref.accession == accession]
        if not chosen:
            notes.append(
                f"No 8-K {accession} was filed in the {EVENT_LOOKBACK_DAYS} days to {as_of}."
            )
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
        label=(
            f"The market's move after the 8-K of {ref.filed_date} "
            f"(items {', '.join(ref.items) or 'none listed'})"
        ),
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
            "Start: the last close before the filing day (an 8-K filed after the close moves "
            "the next day's price).",
            "The index gives the filing's day, not its hour: for an 8-K accepted after the "
            "close, the filing day is a day of the window on which nothing was known.",
            "Excess return = the stock's return − the index's over the same dates; not "
            "adjusted for beta.",
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
        f" − ({index.symbol} {first.end} ÷ {first.start} − 1)"
        if index and first.index_return is not None
        else ""
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


def _outside(
    company: Company,
    filings: FilingSource,
    frames: FramesSource,
    size: float,
    *,
    today: date,
    as_of: date | None,
    notes: list[str],
) -> Outside:
    """What the frames add to the reverse DCF for a company of trailing revenue ``size``."""
    years = admitted_years(as_of, today)
    if not years:
        return Outside()
    last_end = cutoff(as_of, today)
    newest = years[-1]
    wanted = [("revenue", y) for y in years] + [("operating_income", newest)]
    panel, _, _ = load_panel(frames, wanted, last_end)

    def spread(at_least: float) -> Distribution:
        return growth_distribution(
            panel,
            size / SIZE_BAND,
            size * SIZE_BAND,
            span=DCF_YEARS,
            at_least=at_least,
            exclude=company.cik,
        )

    largest = max(
        (
            (panel.names.get(cik, str(cik)), value.value, newest)
            for cik, value in panel.group("revenue", newest).items()
            if cik != company.cik
        ),
        key=lambda found: found[1],
        default=None,
    )
    return Outside(spread, largest, _peer_margin(company, filings, frames, panel, newest, notes))


def _peer_margin(
    company: Company,
    filings: FilingSource,
    frames: FramesSource,
    panel: Panel,
    year: int,
    notes: list[str],
) -> tuple[float, float, int, str, int] | None:
    """The median and 90th percentile of the industry class's operating margin in ``year``."""
    try:
        profile = filings.company_profile(company)
    except SourceError as exc:
        notes.append(f"The industry code could not be read ({exc}); no peer-margin scenario.")
        return None
    members = {cik for cik, _ in frames.sic_members(profile.sic)} if profile.sic else set()
    margins = [
        found.value
        for cik in sorted(members - {company.cik})
        if (revenue := panel.get("revenue", cik, year)) is not None
        and revenue.value >= INDUSTRY_FLOOR
        and (found := panel.measure("operating_margin", cik, year)).value is not None
    ]
    if len(margins) < MIN_PEERS_FOR_MARGIN:
        notes.append(
            f"Fewer than {MIN_PEERS_FOR_MARGIN} other SIC {profile.sic or 'none'} filers have an "
            f"operating margin in {year} ({len(margins)}); no peer-margin scenario."
        )
        return None
    name = f"other SIC {profile.sic} filers with revenue of at least {usd_text(INDUSTRY_FLOOR)}"
    return percentile(margins, 50), percentile(margins, 90), len(margins), name, year


def market_view(
    company: Company,
    filings: FilingSource,
    frames: FramesSource | None,
    *,
    prices: PriceProvider,
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

    A provider with no price for the company and date is not an error: the view says
    why in a market value that cannot be computed, and computes nothing from a price.
    """
    day = as_of or today
    view = MarketView(
        company=company, claim=claim, as_of=day.isoformat(), price_provider=prices.name
    )
    try:
        price = prices.price(company, day)
    except PriceUnavailable as exc:
        view.valuation = [
            AnalysisResult(
                id=f"market_value:{company.ticker}:{day.isoformat()}",
                kind="market_value",
                label="Market value",
                outcome="cannot_compute",
                reason=str(exc),
                reading=str(exc),
                unit="USD",
                data_origin="market_prices",
                as_of=day.isoformat(),
            )
        ]
        view.notes.append("No price: no valuation, no reverse DCF.")
        return view
    if price.day > day or (price.known is not None and price.known > day):
        raise ValueError(f"the price's date {price.day} is after the as-of date {day}")
    view.price_source, view.price_note = price.source, price.note
    view.price_day = price.day.isoformat()
    view.price_known = price.known.isoformat() if price.known else ""
    payload = filings.company_facts(company)
    try:
        book = FactBook(payload, as_of=price.day)
    except FactsError as exc:
        raise SourceError(f"The XBRL company facts could not be read: {exc}") from exc
    measures = Measures(book, fiscal_calendar(payload, as_of=price.day))
    shares = shares_outstanding(payload, price.day)
    found = valuation(
        company.ticker,
        price,
        shares,
        measures,
        day.isoformat(),
        companyfacts=payload,
        later_shares=shares_outstanding(payload, day),
    )
    view.valuation = found.results
    view.notes.append(
        f"Facts: those filed by the price's date, {price.day.isoformat()} (what the price could "
        "know); a filing after it is not read."
    )
    own = trailing_growth(book, as_of=day.isoformat())
    outside = Outside()
    if frames is not None and found.revenue is not None and found.revenue.value:
        size = found.revenue.value
        outside = _outside(
            company, filings, frames, size, today=today, as_of=as_of, notes=view.notes
        )
        if frames.not_read:
            view.notes.append(f"Frames not on disk, not read: {len(frames.not_read)}.")
    view.reverse_dcf = reverse_dcf(
        company.ticker,
        found,
        dcf or DcfInputs(),
        own_growth=own,
        outside=outside,
        as_of=day.isoformat(),
        price_day=price.day.isoformat(),
    )
    if stock is not None:
        view.reactions, notes = reactions(
            company, filings, stock, index, as_of=day, claim=claim, accession=accession, days=days
        )
        view.notes += notes
    else:
        view.notes.append(
            "No daily closes were given; no reaction to an 8-K is computed (the 13F price "
            "source has one price a quarter)."
        )
    return view


TRACED_IN_TEXT = frozenset({"market_value", "enterprise_value"})


def _short(source: str) -> str:
    """A source for one line of text: cut at the first colon (the JSON has all of it)."""
    return source.split(":", 1)[0]


def describe(view: MarketView) -> list[str]:
    """The view as lines of text for the command line."""
    lines = [
        f"Market view: {view.company.name} ({view.company.ticker}) as of {view.as_of}",
        f"Price: {view.price_source or '(none)'}",
        *([f"  {view.price_note}"] if view.price_note else []),
        "",
    ]
    for result in view.valuation:
        lines.append(f"[{result.id}] {result.label}: {result.display}")
        lines.append(f"  {result.reading or result.reason}")
        if result.formula:
            lines.append(f"  formula: {result.formula}")
        if result.note and result.kind != "market_value":
            lines.append(f"  note: {result.note}")
        if result.kind not in TRACED_IN_TEXT:
            if result.inputs:
                lines.append(f"  inputs: {len(result.inputs)} facts, listed in the JSON")
            continue
        lines.extend(
            f"  input: {i.label} = {i.display} ({_short(i.source)}, {i.date}"
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
            lines.append(
                "  grid (rows: discount rate; columns: operating margin "
                + ", ".join(f"{m:.1f}%" for m in margins)
                + ")"
            )
            for rate in sorted({c.discount_rate for c in dcf.grid}):
                row = [c.display for c in dcf.grid if c.discount_rate == rate]
                lines.append(f"    {rate:g}%: " + "  ".join(row))
        for comparison in dcf.comparisons:
            lines.append(f"  compare: {comparison.reading or comparison.reason}")
        for scenario in dcf.scenarios:
            lines.append(f"  scenario: {scenario.reading or scenario.reason}")
            if scenario.note:
                lines.append(f"    {scenario.note}")
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
