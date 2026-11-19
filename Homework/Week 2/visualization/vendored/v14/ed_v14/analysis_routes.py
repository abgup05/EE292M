"""HTTP routes of the outside view and the market view, added to the app by :func:`add_routes`.

Read-only: nothing is stored. Every input is validated by the schema (bounded numbers,
fixed patterns, a strict body), and the checks that need two fields (a price dated after
the as-of date, impossible model assumptions) are refused the same way: 422
``{"error", "details": [{"field", "message"}]}`` through the app's own handler. 503 when
EDGAR or a price source cannot give what is needed.

    GET  /api/companies/{ticker}/outside             ?claim=&as_of=&min_revenue=&years=
    GET  /api/companies/{ticker}/market              ?price=&price_date=&as_of=&claim=
                                                     &discount_rate=&terminal_growth=&tax_rate=
                                                     &operating_margin=&sales_to_capital=
    GET  /api/companies/{ticker}/analytics           ?claim=&claim_id=&as_of=&price=&price_date=
    POST /api/companies/{ticker}/market/reactions    {"closes": [...], "index": ..., ...}

The market route takes ``price`` and ``price_date`` together (the user's own price) or
neither: without them the price is the newest quarter-end price SEC's 13F filings give
as of the date (:mod:`app.sources.thirteenf`). The analytics route returns both views'
results in the one analytic shape (:mod:`app.services.view_analytics`). The reactions route is
a POST only because the daily closes travel in the body (no source of daily single-stock
prices may be read by a script: ``docs/market-view.md``); it computes and returns, and
keeps nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import FastAPI, Query
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field

from ed_v14.core import limits
from ed_v14.core.models import Company, as_of_problem
from ed_v14.core.ports import FilingSource, SourceError
from ed_v14.core.price_series import Close
from ed_v14.core.view_models import EventReaction, MarketView, OutsideView
from ed_v14.services import market_view as market
from ed_v14.services.outside_view import MAX_YEARS, outside_view
from ed_v14.services.view_analytics import Analytic, market_analytics, outside_analytics
from ed_v14.sources.frames import FramesSource
from ed_v14.sources.prices import (
    FredSeries,
    PriceFetchError,
    PriceProvider,
    SuppliedPrice,
    supplied_series,
)
from ed_v14.sources.thirteenf import QuarterEndPrices, ThirteenFSource

ACCESSION = r"^\d{10}-\d{2}-\d{6}$"
MAX_CLOSES = 20_000
CLAIM_ID = r"^[A-Za-z0-9_.:-]{1,64}$"

Claim = Annotated[str, Query(max_length=limits.MAX_CLAIM_CHARS)]


def _refuse(field: str, message: str) -> RequestValidationError:
    return RequestValidationError(
        [{"loc": ("query", field), "msg": message, "type": "value_error"}]
    )


def _check_as_of(as_of: date | None, today: date, field: str = "as_of") -> None:
    if as_of is not None and (problem := as_of_problem(as_of, today)):
        raise _refuse(field, problem)


class DailyClose(BaseModel):
    """One close on a request: a day and a positive price."""

    model_config = ConfigDict(extra="forbid")

    date: date
    close: float = Field(gt=0, lt=1e9)


class ReactionRequest(BaseModel):
    """The closes of the stock (and of an index, or FRED's S&P 500) and which 8-Ks to read.

    ``accession`` names one 8-K; without it, the 8-Ks of the claim's categories in the
    400 days to the as-of date are read (none when the claim names no category).
    """

    model_config = ConfigDict(extra="forbid")

    closes: list[DailyClose] = Field(min_length=2, max_length=MAX_CLOSES)
    index: Literal["none", "fred_sp500", "supplied"] = "none"
    index_closes: list[DailyClose] = Field(default_factory=list, max_length=MAX_CLOSES)
    claim: str = Field(default="", max_length=limits.MAX_CLAIM_CHARS)
    accession: str | None = Field(default=None, pattern=ACCESSION)
    as_of: date | None = None
    days: int = Field(default=3, ge=1, le=60)


class Analytics(BaseModel):
    """Both views' results for one claim, each in the one analytic shape."""

    company: Company
    claim: str
    as_of: str
    analytics: list[Analytic] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class Reactions(BaseModel):
    """The market's move after each 8-K read, and the notes on which were chosen."""

    company: Company
    as_of: str
    reactions: list[EventReaction] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def add_routes(
    app: FastAPI,
    *,
    filings: FilingSource,
    frames: FramesSource,
    thirteenf: ThirteenFSource,
    resolve: Callable[[str], Company],
    today: Callable[[], date] = lambda: datetime.now(UTC).date(),
    index_source: FredSeries | None = None,
) -> None:
    """Add the outside-view and market-view routes to ``app``."""
    fred = index_source or FredSeries()

    def provider(price: float | None, price_date: date | None, day: date) -> PriceProvider:
        """The user's price when both parts are given, else SEC's quarter-end price."""
        if (price is None) != (price_date is None):
            raise _refuse(
                "price" if price is None else "price_date",
                "price and price_date go together: give both, or neither for the 13F price",
            )
        if price is None or price_date is None:
            return QuarterEndPrices(thirteenf)
        _check_as_of(price_date, day, "price_date")
        return SuppliedPrice(price, price_date)

    @app.get("/api/companies/{ticker}/outside")
    def company_outside(
        ticker: str,
        claim: Claim = "",
        as_of: date | None = None,
        min_revenue: Annotated[float | None, Query(ge=0, le=1e13)] = None,
        years: Annotated[int, Query(ge=1, le=MAX_YEARS)] = 15,
    ) -> OutsideView:
        """Base rates of the claim's test and the company's peer standing, from SEC frames."""
        day = today()
        _check_as_of(as_of, day)
        company = resolve(ticker)
        return outside_view(
            company,
            claim,
            filings,
            frames,
            today=day,
            as_of=as_of,
            min_revenue=min_revenue,
            years=years,
        )

    @app.get("/api/companies/{ticker}/market")
    def company_market(
        ticker: str,
        price: Annotated[float | None, Query(gt=0, lt=1e9)] = None,
        price_date: date | None = None,
        as_of: date | None = None,
        claim: Claim = "",
        discount_rate: Annotated[float | None, Query(gt=0, le=50)] = None,
        terminal_growth: Annotated[float | None, Query(ge=-5, le=20)] = None,
        tax_rate: Annotated[float | None, Query(ge=0, lt=100)] = None,
        operating_margin: Annotated[float | None, Query(gt=-100, lt=100)] = None,
        sales_to_capital: Annotated[float | None, Query(gt=0, le=100)] = None,
    ) -> MarketView:
        """Valuation at the price (the user's, or SEC's quarter-end) and the growth it implies."""
        day = today()
        _check_as_of(as_of, day)
        prices = provider(price, price_date, day)
        if price_date is not None and price_date > (as_of or day):
            raise _refuse("price_date", "price_date must not be after as_of")
        rate = discount_rate if discount_rate is not None else market.DISCOUNT_RATE
        growth = terminal_growth if terminal_growth is not None else market.TERMINAL_GROWTH
        if growth >= rate:
            raise _refuse("terminal_growth", "terminal growth must be under the discount rate")
        company = resolve(ticker)
        return market.market_view(
            company,
            filings,
            frames,
            prices=prices,
            today=day,
            as_of=as_of,
            claim=claim,
            dcf=market.DcfInputs(
                discount_rate=discount_rate,
                terminal_growth=terminal_growth,
                tax_rate=tax_rate,
                operating_margin=operating_margin,
                sales_to_capital=sales_to_capital,
            ),
        )

    @app.get("/api/companies/{ticker}/analytics")
    def company_analytics(
        ticker: str,
        claim: Claim = "",
        claim_id: Annotated[str, Query(pattern=CLAIM_ID)] = "c1",
        as_of: date | None = None,
        price: Annotated[float | None, Query(gt=0, lt=1e9)] = None,
        price_date: date | None = None,
    ) -> Analytics:
        """The outside and market views of one claim as a flat list of analytics."""
        day = today()
        _check_as_of(as_of, day)
        prices = provider(price, price_date, day)
        if price_date is not None and price_date > (as_of or day):
            raise _refuse("price_date", "price_date must not be after as_of")
        company = resolve(ticker)
        outside = outside_view(company, claim, filings, frames, today=day, as_of=as_of)
        viewed = market.market_view(
            company, filings, frames, prices=prices, today=day, as_of=as_of, claim=claim
        )
        return Analytics(
            company=company,
            claim=claim,
            as_of=(as_of or day).isoformat(),
            analytics=[
                *outside_analytics(outside, [claim_id]),
                *market_analytics(viewed, [claim_id]),
            ],
            notes=[*outside.notes, *viewed.notes],
        )

    @app.post("/api/companies/{ticker}/market/reactions")
    def company_reactions(ticker: str, request: ReactionRequest) -> Reactions:
        """The stock's move after each chosen 8-K, against the index and its normal move."""
        day = today()
        _check_as_of(request.as_of, day)
        if request.index == "supplied" and len(request.index_closes) < 2:
            raise _refuse("index_closes", "an index supplied on the request needs its closes")
        company = resolve(ticker)
        as_of = request.as_of or day
        try:
            stock = supplied_series(
                company.ticker, [Close(c.date, c.close) for c in request.closes]
            )
            index = None
            if request.index == "supplied":
                index = supplied_series(
                    "INDEX", [Close(c.date, c.close) for c in request.index_closes]
                )
        except PriceFetchError as exc:
            raise _refuse("closes", str(exc)) from exc
        if request.index == "fred_sp500":
            try:
                index = fred.series("SP500")
            except PriceFetchError as exc:
                raise SourceError(f"FRED could not give the S&P 500: {exc}") from exc
        found, notes = market.reactions(
            company,
            filings,
            stock,
            index,
            as_of=as_of,
            claim=request.claim,
            accession=request.accession,
            days=request.days,
        )
        return Reactions(company=company, as_of=as_of.isoformat(), reactions=found, notes=notes)
