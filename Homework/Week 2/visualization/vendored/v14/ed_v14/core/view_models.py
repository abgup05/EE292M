"""Record types of the outside view and the market view: one shape for every result.

Pure data. Every result carries a stable ``id``, a ``label``, an unrounded ``value``
with its ``unit`` and a ``display`` string, the ``formula`` written out with the numbers
used, the ``inputs`` with their sources and dates, the reference class or the
``assumptions``, one templated sentence of ``reading``, and the ``data_origin``:
``sec_frames`` (SEC's XBRL frames, one value per filer and period) or
``market_prices`` (a price, supplied or fetched, with the company's own facts).

The values are computed by :mod:`app.core.frames`, :mod:`app.core.base_rates`,
:mod:`app.core.peers`, :mod:`app.core.valuation` and :mod:`app.core.reaction`; a view
only draws them. ``outcome`` is ``computed`` or ``cannot_compute``, with ``reason``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ed_v14.core.models import Company

DataOrigin = Literal["sec_frames", "market_prices"]
ResultUnit = Literal["USD", "USD_per_share", "percent", "multiple", "count", "shares", "ratio"]
ResultOutcome = Literal["computed", "cannot_compute"]


class ResultInput(BaseModel):
    """One number a result used: what it is, its value, where it came from and its date.

    ``source`` names the source in words ("SEC XBRL frame us-gaap/Revenues/USD/CY2024",
    "SEC company facts, 10-Q 0001045810-26-000075", "price supplied on the request");
    ``date`` is the date the value is of (a period's end, a balance-sheet date, a
    trading day); ``filed`` the filing date when the source gives one (frames do not).
    """

    label: str
    value: float | None
    display: str
    source: str
    date: str = ""
    filed: str = ""
    url: str = ""


class AnalysisResult(BaseModel):
    """One result of the outside or the market view, in the shape every view shares."""

    id: str
    kind: str
    label: str
    outcome: ResultOutcome = "computed"
    reason: str = ""
    value: float | None = None
    unit: ResultUnit = "percent"
    display: str = "n/a"
    formula: str = ""
    inputs: list[ResultInput] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    reading: str = ""
    data_origin: DataOrigin
    as_of: str = ""
    note: str = ""


# The outside view


class YearCount(BaseModel):
    """One year of a base rate: how many company-years of the class held the test.

    ``in_class`` counts the filers of the class that year; ``computable`` those of them
    the test could be computed for; ``held`` those for which it held.
    """

    year: int
    in_class: int
    computable: int
    held: int


class Case(BaseModel):
    """One company-year for which the test held: who, when, the value and what followed.

    ``value`` is the test's left side that year (a growth in percent, a margin, an
    amount); ``revenue`` the filer's revenue that year; ``period_end`` the end of the
    period the frame placed in that year. ``next_year`` says whether the test held a
    year later: "held", "did not hold", or "" when it could not be computed.
    """

    name: str
    cik: int
    year: int
    period_end: str
    value: float
    display: str
    revenue: float | None = None
    revenue_display: str = ""
    next_year: str = ""


class ConceptResolution(BaseModel):
    """How a concept group was resolved across concepts, filer by filer, in one frame year.

    ``filers`` had a value under at least one concept; ``several`` under more than one;
    ``differing`` of those, a second concept's value differs from the one taken by more
    than one percent; ``scale_breaks`` of those, two concepts differ by a factor near a
    thousand, and the filer has no value that year. ``rule`` says which value is taken.
    """

    group: str
    year: int
    filers: int
    several: int
    differing: int
    scale_breaks: int = 0
    rule: str


class BaseRate(AnalysisResult):
    """How often a compiled claim test held among a reference class, year by year.

    ``value`` is held ÷ computable over all years, in percent, never shown without
    ``held`` and ``computable``. ``persisted`` of ``persist_base`` company-years for
    which it held in a year still held a year later. ``cases`` are the nearest
    company-years that held (the company itself left out), ``own`` the company's own.
    """

    test: str = ""
    annual_test: str = ""
    class_name: str = ""
    class_definition: str = ""
    years: list[YearCount] = Field(default_factory=list)
    held: int = 0
    computable: int = 0
    persisted: int = 0
    persist_base: int = 0
    cases: list[Case] = Field(default_factory=list)
    own: list[Case] = Field(default_factory=list)
    resolution: list[ConceptResolution] = Field(default_factory=list)


class Neighbour(BaseModel):
    """A peer next to the company in a ranking: its rank, name, value and display."""

    rank: int
    name: str
    cik: int
    value: float
    display: str


class Standing(BaseModel):
    """The company's place among its class on one measure in one frame year.

    ``rank`` 1 is the highest value; ``percentile`` is the share of the other members
    the company's value is above, in percent: 100 × (n − rank) ÷ (n − 1).
    """

    year: int
    period_end: str = ""
    n: int = 0
    rank: int | None = None
    percentile: float | None = None
    value: float | None = None
    display: str = "n/a"
    median: float | None = None
    median_display: str = "n/a"
    above: list[Neighbour] = Field(default_factory=list)
    below: list[Neighbour] = Field(default_factory=list)
    reason: str = ""


class PeerStanding(AnalysisResult):
    """Where the company's value of one measure sits among its industry, now and a year ago."""

    measure: str = ""
    class_name: str = ""
    class_definition: str = ""
    now: Standing | None = None
    year_before: Standing | None = None


class Distribution(BaseModel):
    """A distribution of a value across company-spans: its count and percentiles."""

    n: int = 0
    percentiles: dict[str, float] = Field(default_factory=dict)
    displays: dict[str, str] = Field(default_factory=dict)
    at_least: int = 0
    at_least_of: float | None = None
    dropped: int = 0
    definition: str = ""
    band: str = ""
    window: str = ""


class OutsideView(BaseModel):
    """The outside view of one company and one claim: base rates and peer standing."""

    company: Company
    claim: str = ""
    sic: str = ""
    sic_description: str = ""
    as_of: str = ""
    test: str = ""
    test_measures: list[str] = Field(default_factory=list)
    compile_note: str = ""
    base_rates: list[BaseRate] = Field(default_factory=list)
    peers: list[PeerStanding] = Field(default_factory=list)
    years_read: list[int] = Field(default_factory=list)
    frames_read: int = 0
    notes: list[str] = Field(default_factory=list)
    covered_measures: list[str] = Field(default_factory=list)
    not_covered_measures: list[str] = Field(default_factory=list)


# The market view


class GridCell(BaseModel):
    """One cell of the reverse-DCF sensitivity grid: a discount rate, a margin, the growth."""

    discount_rate: float
    operating_margin: float
    implied_growth: float | None
    display: str


class ReverseDcf(AnalysisResult):
    """The constant ten-year revenue growth at which the stated model's value equals the price.

    Arithmetic under stated assumptions, not a forecast. ``grid`` varies the discount
    rate and the margin; ``comparisons`` are the company's own trailing growth and the
    outside view's distribution of ten-year growth for companies of its size.
    ``scenarios`` solve the same model with one assumption replaced (the margin at the
    industry's median); ``implied_revenue`` is the revenue the growth reaches in the
    model's last year.
    """

    target: str = ""
    grid: list[GridCell] = Field(default_factory=list)
    comparisons: list[AnalysisResult] = Field(default_factory=list)
    scenarios: list[AnalysisResult] = Field(default_factory=list)
    distribution: Distribution | None = None
    implied_revenue: float | None = None
    implied_revenue_display: str = ""
    label_note: str = ""


class ReactionWindow(BaseModel):
    """The stock's move over one window after an event, against the index and its normal move.

    ``days`` is the number of trading days from the close before the filing (``start``)
    to ``end``. ``excess`` is the stock's return minus the index's, in percent;
    ``normal`` the stock's typical move over as many days (the daily standard deviation
    of its excess return times the square root of the days), and ``ratio`` excess ÷ normal.
    """

    name: str
    days: int
    start: str
    end: str
    stock_return: float
    index_return: float | None = None
    excess: float
    normal: float | None = None
    ratio: float | None = None
    line: str = ""


class EventReaction(AnalysisResult):
    """The market's move around one 8-K: the stock against an index and its own normal move."""

    accession: str = ""
    filed: str = ""
    items: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    windows: list[ReactionWindow] = Field(default_factory=list)
    estimation: str = ""


class MarketView(BaseModel):
    """The market view of one company: valuation now, what the price implies, reactions."""

    company: Company
    claim: str = ""
    as_of: str = ""
    price_source: str = ""
    price_provider: str = ""
    price_day: str = ""
    price_known: str = ""
    price_note: str = ""
    valuation: list[AnalysisResult] = Field(default_factory=list)
    reverse_dcf: ReverseDcf | None = None
    reactions: list[EventReaction] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
