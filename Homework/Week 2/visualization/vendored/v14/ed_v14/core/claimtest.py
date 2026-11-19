"""The claim compiler: a thesis claim's text to a typed test, or why it is not a numeric claim.

Pure: no I/O, no model. :func:`compile_claim` reads a claim with a small grammar of
regular expressions and returns a :class:`ClaimTest` (what to compute and how to
compare it) or a :class:`NotNumeric` with the reason. Evaluation is
:mod:`app.core.claim_eval`; the labels that score this grammar are
``eval/claim-tests.json`` (``make claim-labels``).

A test prints in a canonical form, such as ``gross_margin[Q] > gross_margin[Q-4]``,
``yoy(revenue)[Q2 FY2027] > 50%`` or ``share(segment "Data Center")[filing] > 80%``.
Its periods are *unbound* (``Q`` is the latest quarter, ``Q-4`` the same quarter a year
earlier, ``FY2026`` fiscal 2026); evaluation binds them to dates in one company's facts.

The forms:

- **direction**: a measure is growing, expanding, rising (``>``) or shrinking,
  declining, falling (``<``) against a year earlier (or the previous quarter with
  "sequentially", or N years earlier with "over the last N years");
- **acceleration**: its growth is accelerating or decelerating;
- **streak**: it has grown for N consecutive quarters or years;
- **threshold**: it is above, over, at least, below, under a percent or an amount;
- **growth_threshold**: it grew more than N% year over year or sequentially;
- **faster_than**: one measure is growing faster (or more slowly) than another;
- **compound**: it has compounded at over N% for K years;
- **share**: a segment, a geography or the largest customer is more than N% of revenue,
  from the newest filing's tagged breakdowns.

Measures are those of the catalogue (:mod:`app.core.measures`): the panel's own
(:mod:`app.core.metrics`) plus the facts behind them (gross profit, operating income, net
income, R&D) and operating expenses, which this version derives as gross profit less
operating income; and, since the catalogue, buybacks, dividends, debt and its parts, net
cash, the diluted share count, total operating expenses, SG&A and its parts, stock-based
compensation, income tax and the effective tax rate, interest, depreciation, deferred
revenue, cash and marketable securities, total assets, liabilities and equity, and the
others it lists, each named by the words its ``names`` pattern gives. "Has no debt" is
a threshold at zero. A part of the company (a segment, a product, a geography) is not read
by this grammar: the catalogue computes a part's revenue for the model readers.

A claim is *not* numeric when it is a valuation, a cause, a forecast, a judgement,
about peers or expectations, a measure outside that set, a segment's or a geography's
growth (breakdowns come from one filing and have no history in the facts), a top-N
share (only single customers are tagged), a margin it does not name, or when it
states no direction, threshold or comparison.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Literal

from ed_v14.core.limits import MAX_CLAIM_CHARS, MAX_EACH_PERIODS
from ed_v14.core.measures import CATALOGUE
from ed_v14.core.measures import RATIO_OF as CATALOGUE_RATIO_OF

Form = Literal[
    "direction",
    "acceleration",
    "streak",
    "threshold",
    "growth_threshold",
    "faster_than",
    "compound",
    "share",
    "compare",
]
Op = Literal[">", ">=", "<", "<="]
PeriodKind = Literal["Q", "FY", "TTM", "filing"]
Function = Literal["value", "yoy", "qoq", "streak", "cagr", "share", "max_share", "change"]
MetricKind = Literal["flow", "ratio", "per_share", "instant", "shares"]

FORMS: tuple[str, ...] = (
    "direction",
    "acceleration",
    "streak",
    "threshold",
    "growth_threshold",
    "faster_than",
    "compound",
    "share",
    "compare",
)
# The forms a test held in each of several periods may take.
EACH_FORMS: tuple[str, ...] = (
    "direction",
    "acceleration",
    "threshold",
    "growth_threshold",
    "faster_than",
    "compare",
)

# Every measure a test can name, its label and what kind of number it is.
METRICS: dict[str, tuple[str, MetricKind]] = {
    "revenue": ("Revenue", "flow"),
    "gross_profit": ("Gross profit", "flow"),
    "operating_income": ("Operating income", "flow"),
    "net_income": ("Net income", "flow"),
    "rnd": ("Research and development", "flow"),
    "operating_expenses": ("Operating expenses", "flow"),
    "operating_cash_flow": ("Operating cash flow", "flow"),
    "capex": ("Capital expenditure", "flow"),
    "free_cash_flow": ("Free cash flow", "flow"),
    "gross_margin": ("Gross margin", "ratio"),
    "operating_margin": ("Operating margin", "ratio"),
    "net_margin": ("Net margin", "ratio"),
    "rnd_ratio": ("R&D as a share of revenue", "ratio"),
    "fcf_margin": ("Free cash flow margin", "ratio"),
    "eps_diluted": ("Diluted EPS", "per_share"),
    "cash": ("Cash and cash equivalents", "instant"),
    "inventory": ("Inventory", "instant"),
    "receivables": ("Accounts receivable", "instant"),
}
# The catalogue's further measures (app.core.measures), after the panel's.
METRICS |= {
    key: (measure.label, measure.kind) for key, measure in CATALOGUE.items() if key not in METRICS
}
# A measure "as a share of revenue" is its ratio.
RATIO_OF: dict[str, str] = dict(CATALOGUE_RATIO_OF)
# Each ratio's numerator and denominator, as the claim may name them ("13% of pre-tax income").
RATIO_PARTS: dict[str, tuple[str, str]] = {
    **{
        measure.key: (measure.plus[0], measure.over)
        for measure in CATALOGUE.values()
        if measure.computed == "ratio"
    },
    **{ratio: (top, "revenue") for top, ratio in RATIO_OF.items()},
}
SHARE_AXES = ("segment", "geography", "customer")


# The typed test


@dataclass(frozen=True)
class Period:
    """An unbound period: the latest quarter (``Q``), fiscal year (``FY``), four quarters
    (``TTM``) or the newest filing's breakdowns (``filing``), ``back`` steps earlier
    (quarters for ``Q`` and ``TTM``, years for ``FY``); or a named fiscal year or quarter.
    """

    kind: PeriodKind
    back: int = 0
    fiscal_year: int | None = None
    quarter: int | None = None

    @property
    def named(self) -> bool:
        """True for a fiscal year or quarter named by its label ("fiscal 2026")."""
        return self.fiscal_year is not None

    def text(self) -> str:
        """The canonical form: ``Q``, ``Q-4``, ``FY-3``, ``FY2026``, ``Q2 FY2027``, ``TTM``."""
        if self.kind == "filing":
            return "filing"
        if self.fiscal_year is not None:
            if self.quarter is not None:
                return f"Q{self.quarter} FY{self.fiscal_year}"
            return f"FY{self.fiscal_year}"
        return self.kind + (f"-{self.back}" if self.back else "")

    def years_back(self, years: int) -> Period:
        """The same period ``years`` fiscal years earlier."""
        if self.fiscal_year is not None:
            return replace(self, fiscal_year=self.fiscal_year - years)
        steps = years if self.kind == "FY" else 4 * years
        return replace(self, back=self.back + steps)

    def step_back(self) -> Period:
        """The period before: the previous quarter, or the previous fiscal year."""
        if self.fiscal_year is not None and self.quarter is not None:
            if self.quarter > 1:
                return replace(self, quarter=self.quarter - 1)
            return replace(self, fiscal_year=self.fiscal_year - 1, quarter=4)
        if self.fiscal_year is not None:
            return replace(self, fiscal_year=self.fiscal_year - 1)
        return replace(self, back=self.back + 1)


@dataclass(frozen=True)
class Term:
    """One side of a test: a function of a measure over a period.

    ``value`` is the measure itself; ``yoy`` and ``qoq`` its growth on a year earlier
    and on the previous quarter; ``streak`` the number of periods in a row it rose;
    ``cagr`` its compound annual growth over ``years``; ``share`` one ``member``'s share
    of revenue along an axis (``subject`` is "segment" or "geography");
    ``max_share`` the largest tagged customer's share. A term with an ``axis`` is a part
    of the company's measure (``subject`` "revenue" or "operating_income" of ``member``
    along ``axis``), read from a filing's tags (:data:`app.core.measures.PART_MEASURES`):
    the newest filing's newest period (``filing``), or the fiscal year or quarter named.
    ``change`` is the growth from the earlier period ``base`` to ``period`` ("between fiscal
    2023 and fiscal 2025", "tripled over three years").
    """

    fn: Function
    subject: str
    period: Period
    member: str = ""
    years: int = 0
    axis: str = ""
    base: Period | None = None

    def text(self) -> str:
        """The canonical form of the term."""
        at = f"[{self.period.text()}]"
        if self.axis:
            inner = f'{self.subject}({self.axis} "{self.member}")'
            return f"{inner}{at}" if self.fn == "value" else f"{self.fn}({inner}){at}"
        match self.fn:
            case "value":
                return f"{self.subject}{at}"
            case "cagr":
                return f"cagr({self.subject}, {self.years}y){at}"
            case "change":
                since = self.base.text() if self.base is not None else "?"
                return f"change({self.subject}, {since}){at}"
            case "share":
                return f'share({self.subject} "{self.member}"){at}'
            case "max_share":
                return f"max(share({self.subject})){at}"
            case _:
                return f"{self.fn}({self.subject}){at}"


@dataclass(frozen=True)
class Number:
    """A constant: a percent (55.6 for 55.6%), an amount in USD, or a count of periods."""

    value: float
    unit: Literal["percent", "USD", "count"]

    def text(self) -> str:
        """``50%``, ``-10%``, ``$100B``, ``$500M``, ``$3``, ``8``."""
        if self.unit == "percent":
            return f"{self.value:g}%"
        if self.unit == "count":
            return f"{self.value:g}"
        size = abs(self.value)
        sign = "-" if self.value < 0 else ""
        if size >= 1e9:
            return f"{sign}${size / 1e9:g}B"
        if size >= 1e6:
            return f"{sign}${size / 1e6:g}M"
        return f"{sign}${size:g}"


@dataclass(frozen=True)
class ClaimTest:
    """A compiled claim: ``left op right``, of one :data:`Form`.

    ``each`` > 0 asks that the test hold in each of the last ``each`` periods (its periods
    stepped back one quarter, or one fiscal year, at a time); ``each_since`` that a change
    test hold in every fiscal year after the one named. ``also`` is a second test joined
    by "and": the claim holds only when both do. A test has at most one ``also``, which
    has none of its own.
    """

    form: Form
    left: Term
    op: Op
    right: Term | Number
    each: int = 0
    each_since: int | None = None
    also: ClaimTest | None = None

    @property
    def canonical(self) -> str:
        """The test as the labels write it."""
        text = f"{self.left.text()} {self.op} {self.right.text()}"
        if self.each:
            text = f"each({self.each}): {text}"
        elif self.each_since is not None:
            text = f"each(since FY{self.each_since}): {text}"
        if self.also is not None:
            return f"({text}) and ({self.also.canonical})"
        return text

    @property
    def parts(self) -> tuple[ClaimTest, ...]:
        """The tests joined by "and": this one alone, or it and ``also``."""
        if self.also is None:
            return (self,)
        return (replace(self, also=None), *self.also.parts)

    @property
    def terms(self) -> tuple[Term, ...]:
        """Every term of every part, left first."""
        return tuple(
            term
            for part in self.parts
            for term in (part.left, part.right)
            if isinstance(term, Term)
        )

    @property
    def from_filing(self) -> bool:
        """True when a term is read from a filing's tags (a share or a part), not the facts."""
        return any(t.fn in ("share", "max_share") or t.axis for t in self.terms)


@dataclass(frozen=True)
class NotNumeric:
    """A claim this version cannot compute, and why, in words a reader can check."""

    reason: str


# Words

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
ORDINAL_QUARTERS = {"first": 1, "second": 2, "third": 3, "fourth": 4}

# Comparison words, longest first.
COMPARATORS: tuple[tuple[str, Op], ...] = (
    ("at or above", ">="),
    ("at or below", "<="),
    ("no more than", "<="),
    ("no less than", ">="),
    ("more than", ">"),
    ("greater than", ">"),
    ("better than", ">"),
    ("in excess of", ">"),
    ("at least", ">="),
    ("at most", "<="),
    ("less than", "<"),
    ("fewer than", "<"),
    ("surpassed", ">"),
    ("exceeded", ">"),
    ("exceeds", ">"),
    ("exceed", ">"),
    ("topped", ">"),
    ("passed", ">"),
    ("reached", ">="),
    ("hit", ">="),
    ("tops", ">"),
    ("above", ">"),
    ("over", ">"),
    ("under", "<"),
    ("below", "<"),
)
CMP = "|".join(re.escape(words) for words, _ in COMPARATORS)
OP_OF = dict(COMPARATORS)
NEGATED: dict[Op, Op] = {">": "<=", ">=": "<", "<": ">=", "<=": ">"}
FLIPPED: dict[Op, Op] = {">": "<", ">=": "<=", "<": ">", "<=": ">="}

_W = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
PERCENT = re.compile(rf"(?P<cmp>{CMP})\s+(?P<num>-?\d+(?:\.\d+)?)\s*(?:%|percent\b)")
AMOUNT = re.compile(
    rf"(?P<cmp>{CMP})\s+\$\s?(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<scale>billion|million|thousand|bn|b|m|k)?\b"
)
BARE_PERCENT = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?\s*(?:%|percent\b)")
BARE_AMOUNT = re.compile(r"\$\s?\d")
SCALES = {"billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "m": 1e6, "thousand": 1e3, "k": 1e3}

# The measures, as a claim names them; longer names first so that they win (the catalogue's
# order: its added measures, then the panel's, whose names are as they were).
METRIC_PHRASES: tuple[tuple[str, str], ...] = tuple(
    (measure.names, key) for key, measure in CATALOGUE.items()
)
METRIC_RE = re.compile(
    "|".join(
        rf"(?P<m{i}>(?<![\w&])(?:{pattern})(?![\w&]))"
        for i, (pattern, _) in enumerate(METRIC_PHRASES)
    )
)

# A business segment or a geography, as a claim might name one before "revenue".
PARTS = (
    r"data cent(?:er|re)|gaming|automotive|networking|compute|professional visualization|"
    r"iphone|ipad|mac|wearables|services|cloud|intelligent cloud|azure|productivity|"
    r"personal computing|segment|product|hardware|software|subscription|advertising|"
    r"china|taiwan|united states|u\.s\.|us|europe|emea|americas|asia|asia pacific|japan|"
    r"singapore|international|domestic|greater china|rest of (?:the )?world"
)
GEOGRAPHIES = re.compile(
    r"^(?:china|taiwan|the united states|united states|u\.s\.|us|europe|emea|americas|"
    r"the americas|asia|asia pacific|japan|singapore|greater china|international|"
    r"rest of (?:the )?world|other countries|india|korea|canada|mexico|germany)$"
)
PART_BEFORE_REVENUE = re.compile(rf"(?<![\w])(?:{PARTS})(?:'s)?\s+(?:net )?(?:revenues?|sales)\b")

# What makes a claim not numeric, checked in this order.
TRAPS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\brun[- ]rate\b|\bannuali[sz]ed\b|"
            r"\brunning at\b.*\b(?:a year|per year|annual(?:ly)?|yearly)\b"
        ),
        "an annualised run rate: this tool reads the amounts a filing reports, not a quarter "
        "annualised",
    ),
    (
        re.compile(
            r"\b(?:will|would|should|could|might|may|expects?|expected|guidance|forecasts?|"
            r"next (?:year|quarter)|by year[- ]end|likely|implies|projected)\b|^if\b"
        ),
        "a forecast or a conditional: filed facts are past",
    ),
    (
        re.compile(
            r"\b(?:because|thanks to|due to|driven by|driving|drives|as a result of|"
            r"on the back of|after the|restricting|hurting|caused by)\b"
        ),
        "a cause, not only arithmetic: the facts can test a change, not why it happened",
    ),
    (
        re.compile(
            r"\b(?:peers?|industry|competitors?|competition|market share|consensus|analysts?|"
            r"expectations)\b"
        ),
        "about peers, the market or expectations, which one company's filed facts do not hold",
    ),
    (
        re.compile(r"\btop \w+\b|\b(?:\d+|two|three|four|five|ten) largest\b|largest customers"),
        "a top-N share: filings tag single customers' shares, not their top few together",
    ),
    (
        re.compile(
            r"\b(?:headcount|employees?|(?<!diluted )shares outstanding|backlog|"
            r"return on (?:equity|assets|invested capital)|roe|roic|inventory turns|"
            r"(?:free )?cash flow per share|dilut(?:ing|ion)|interest rates?)\b"
        ),
        "names a measure that is not in the metric set this version computes",
    ),
    (
        re.compile(
            r"\b(?:priced in|valuation|valued|cheap|expensive|p/e|price[- ]to|multiples?|"
            r"yield|stock price|share price)\b"
        ),
        "a valuation: it needs the share price, which is not filed",
    ),
    (
        re.compile(r"\bcalendar\b|\b(?:in|during|for|of) (?:19|20)\d\d\b"),
        "names a calendar year: this version tests fiscal periods (say 'fiscal 2026')",
    ),
)
JUDGEMENT = re.compile(r"\b(?:quality|story|moat|warning|aggressive|discipline)\b")
UNNAMED_MARGIN = re.compile(
    r"(?<!gross )(?<!operating )(?<!net )(?<!profit )(?<!flow )(?<!fcf )\bmargins?\b"
)

UP = (
    r"grow(?:ing|s|n)?|grew|ris(?:ing|en|es)|rose|increas(?:ing|ed|es)|expand(?:ing|ed|s)?|"
    r"improv(?:ing|ed|es)|widen(?:ing|ed|s)?|gone up|up|higher|climb(?:ing|ed|s)?"
)
DOWN = (
    r"shrink(?:ing|s)?|shrank|shrunk|declin(?:ing|ed|es)|fall(?:ing|en|s)?|fell|gone down|"
    r"contract(?:ing|ed|s)?|deteriorat(?:ing|ed|es)|slipp(?:ing|ed)|slips?|lower|down|"
    r"drop(?:ping|ped|s)?|decreas(?:ing|ed|es)|weaken(?:ing|ed|s)?|compress(?:ing|ed|es)?"
)
UP_RE = re.compile(rf"\b(?:{UP})\b")
DOWN_RE = re.compile(rf"\b(?:{DOWN})\b")
GROWTH_WORD = re.compile(rf"\b(?:{UP}|{DOWN}|growth)\b")

SEQUENTIAL = re.compile(
    r"\bsequential(?:ly)?\b|\bquarter[- ]over[- ]quarter\b|\bq/q\b|\bqoq\b|"
    r"\bfrom the (?:previous|prior|preceding) quarter\b|\bon the (?:previous|prior) quarter\b"
)
TTM = re.compile(
    r"\btrailing[- ](?:twelve|12)[- ]months?\b|\blast[- ](?:twelve|12)[- ]months?\b|"
    r"\bttm\b|\bltm\b|"
    r"\bon a trailing(?: (?:twelve|12)[- ]months?)? basis\b"
)
NAMED_QUARTER = re.compile(
    r"\b(?:q(?P<q>[1-4])|(?:the )?(?P<ord>first|second|third|fourth) quarter)\s+(?:of\s+)?"
    r"(?:fiscal(?: year)?\s*|fy\s?)(?P<year>\d{4})\b"
)
NAMED_YEAR = re.compile(r"\b(?:fiscal(?: year)?\s*|fy\s?)(?P<year>\d{4})\b")
_FISCAL = r"(?:fiscal(?: year)?\s*|fy\s?)"
# A span of fiscal years: "between fiscal 2023 and fiscal 2025", "over fiscal 2023 to 2025";
# "since fiscal 2023" runs to the latest fiscal year.
SPAN = re.compile(
    rf"\b(?:between|from|over|across) {_FISCAL}(?P<a>\d{{4}}) (?:and|to|through) "
    rf"{_FISCAL}?(?P<b>\d{{4}})\b"
)
SINCE_YEAR = re.compile(rf"\bsince {_FISCAL}(?P<year>\d{{4}})\b")
# "more than three times its fiscal 2023 level": a change from that year, (N - 1) x 100%.
TIMES_LEVEL = re.compile(
    rf"\b(?:(?P<more>more than )|at least )?(?P<n>two|three|four|five|\d+) times (?:its|the) "
    rf"{_FISCAL}(?P<year>\d{{4}}) (?:level|figure|amount)\b"
)
# A test held in each of several periods, besides EACH_PERIOD's "in each of the last N".
EACH_SINCE = re.compile(
    rf"\b(?:in )?(?:every|each) (?:fiscal )?year since {_FISCAL}(?P<year>\d{{4}})\b"
)
EACH_ORDINAL = re.compile(
    r"\bfor (?:the|a) (?P<ord>second|third|fourth|fifth|sixth) "
    r"(?:consecutive|straight|successive) (?:fiscal )?(?P<unit>year|quarter)\b"
)
EACH_QUARTER_OF = re.compile(
    rf"\b(?:in )?(?:each|every) (?:fiscal )?quarter of {_FISCAL}(?P<year>\d{{4}})\b"
)
ORDINAL_COUNTS = {"second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6}
# "between fiscal 2024 and fiscal 2025", "from fiscal 2024 to fiscal 2025": the later year,
# against the one before it.
BETWEEN_YEARS = re.compile(
    r"\b(?:between|from) (?:fiscal(?: year)?\s*|fy\s?)(?P<a>\d{4}) (?:and|to) "
    r"(?:fiscal(?: year)?\s*|fy\s?)?(?P<b>\d{4})\b"
)
OVER_YEARS = re.compile(
    rf"\b(?:over|in|during|across) the (?:last|past|previous) (?P<n>{_W}) (?:fiscal )?years\b"
)
ANNUAL = re.compile(
    r"\bannual(?:ly)?\b|\bfiscal year\b|\blast (?:fiscal )?year\b|\bper year\b|"
    r"\ba year\b(?! (?:ago|earlier|before))|\byearly\b"
)
# "Now running at $40 billion" is the latest quarter's amount; "running at $160 billion a year"
# is an annualised run rate, refused among the traps.
QUARTERLY = re.compile(
    r"\bquarterly\b|\b(?:last|latest|most recent|this) quarter(?:'s)?\b|\ba quarter\b|"
    r"\b(?:now |currently )?running at\b"
)
STREAK = re.compile(
    rf"\bfor (?P<n1>{_W}) (?:consecutive|straight|successive) (?P<u1>quarters|years)\b|"
    rf"\b(?P<n2>{_W}) (?P<u2>quarters|years) in a row\b|"
    rf"\b(?P<n3>{_W}) (?:consecutive|straight|successive) (?P<u3>quarters|years)\b"
)
FASTER = re.compile(
    r"\b(?:growing|grew|grows|grown|rising|rose|rises|increasing|increased|expanding|expanded)"
    r" (?P<how>faster|more quickly|more slowly|slower|less quickly) than (?P<tail>.+)$"
)
ACCELERATION = re.compile(
    r"\bgrowth\b.*?\b(?P<how>accelerat\w*|speeding up|sped up|decelerat\w*|slow(?:ing|ed|s)?|"
    r"slowing down)\b"
)
COMPOUND = re.compile(r"\bcompound(?:ed|ing|s)?\b|\bcagr\b")
COMPOUND_YEARS = re.compile(
    rf"\b(?P<a>{_W})[- ]year\b|\bfor (?P<b>{_W}) years\b|"
    rf"\b(?:over|in|during) the (?:last|past|previous) (?P<c>{_W}) (?:fiscal )?years\b"
)
DOUBLED = re.compile(
    r"\b(?:(?P<more>more than )|at least )?(?P<times>doubled|tripled|quadrupled)\b"
)
MULTIPLE = {"doubled": 100.0, "tripled": 200.0, "quadrupled": 300.0}
SHARE = re.compile(
    rf"^(?:the )?(?P<subject>.+?) (?:is|are|was|were|accounts? for|accounted for|"
    rf"represents?|represented|makes? up|made up|comprises?|comprised) (?:now |still )?"
    rf"(?P<cmp>{CMP}) (?P<num>-?\d+(?:\.\d+)?\s*(?:%|percent)|half|a half|a quarter|a third)"
    r" of (?:(?:total |the company's |its |all |net )?(?:net )?(?:revenues?|sales)|the total)"
    # The fiscal year or quarter, when it names one the filings report.
    rf"(?P<when>,? (?:last (?:fiscal )?year|last quarter|"
    rf"in (?:the )?(?:latest|last|most recent) (?:fiscal year|quarter)|"
    rf"(?:in |for )?{_FISCAL}\d{{4}}|"
    rf"in (?:q[1-4]|the (?:first|second|third|fourth) quarter of) {_FISCAL}\d{{4}}))?$"
)
# "Japan and Rest of Asia Pacific together": a sum of several parts, which no tag gives.
SUM_OF_PARTS = re.compile(r"\b(?:together|combined|collectively)\b")
# "iPad sales", "revenue from the United States": the part, without the revenue words.
SHARE_SUBJECT_REVENUE = re.compile(
    r"^(?:(?:net )?(?:revenues?|sales) (?:from|in) (?P<before>.+)|(?P<after>.+?)(?:'s)?"
    r" (?:net )?(?:revenues?|sales))$"
)
# A condition held in each of several periods ("for the last four quarters", "every year",
# "in all four quarters"): one test of one period would be half the claim.
EACH_PERIOD = re.compile(
    rf"\b(?:in |for )?(?:each|every|all) (?:of )?(?:the )?(?:last |past |previous )?"
    rf"(?:(?P<n>{_W}) )?(?:fiscal )?(?P<unit>quarters?|years?)\b|"
    rf"\bfor the (?:last|past|previous) (?P<n2>{_W}) (?:fiscal )?(?P<unit2>quarters|years)\b"
)
# Two statements joined by a contrast: one test would be half the claim.
CONTRAST = re.compile(r"(?:,| )but\b|\b(?:although|though|despite|whereas)\b")
# Two tests joined by "and" (read only when each part is a whole test on its own).
AND_SPLIT = re.compile(r",?\s+and\s+", re.IGNORECASE)
# The levels of two measures compared ("operating cash flow was above net income").
LEVEL_COMPARATORS: tuple[tuple[str, Op], ...] = (
    ("higher than", ">"),
    ("larger than", ">"),
    ("bigger than", ">"),
    ("lower than", "<"),
    ("smaller than", "<"),
)
COMPARE_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w, _ in (*LEVEL_COMPARATORS, *COMPARATORS)) + r")\b"
)
CUSTOMER_SUBJECT = re.compile(
    r"^(?P<neg>no|not one)? ?(?:a |one |any |the largest |the biggest |a single |single )?"
    r"(?:single )?customer$|^(?:the )?(?:largest|biggest) customer$"
)
FRACTIONS = {"half": 50.0, "a half": 50.0, "a quarter": 25.0, "a third": 100 / 3}
# "The company has no debt": a threshold at zero; "was negative", "is positive" too.
HAS_NONE = re.compile(r"\b(?:has|have|had|carries|carried|pays|paid) no\b")
SIGN = re.compile(
    r"\b(?:is|are|was|were|turned|remained|remains|stayed|stays|became) "
    r"(?P<sign>negative|positive)\b"
)
# A company named before its verb opens a claim ("Apple repurchased ..."): the subject.
COMPANY_VERB = re.compile(
    r"\s*([A-Z][\w&.-]*) (?=(?:repurchased|returned|bought|spent|paid|generated|earned|"
    r"reported|holds|held|carries|carried|has|had)\b)"
)
# "fell below $10 billion", "rose above 40%": the verb before a threshold's comparison.
MOVED = r"(?:fell|dropped|declined|rose|climbed|grew|increased|decreased)"
MOVED_TO = rf"\b{MOVED}\b(?= (?:{CMP}) )"
MOVED_BEFORE = re.compile(rf"\b{MOVED}\s+$")


# Reading the claim


def _normalised(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("–", "-")
    text = re.sub(r"\s+", " ", text.casefold()).strip()
    return text.rstrip(".!?;: ").strip()


def _count(word: str) -> int:
    return int(word) if word.isdigit() else NUMBER_WORDS[word]


def _metrics(text: str) -> list[tuple[int, int, str]]:
    """Every measure the text names, as (start, end, key), in order."""
    found: list[tuple[int, int, str]] = []
    for match in METRIC_RE.finditer(text):
        group = match.lastgroup
        assert group is not None
        found.append((match.start(), match.end(), METRIC_PHRASES[int(group[1:])][1]))
    return found


def measures_named(text: str) -> list[str]:
    """Every catalogue measure ``text`` names, as keys in order of first mention.

    The words alone: a claim that names gross margin names it whether or not it states a
    test this version computes (:mod:`app.core.relevance` uses it).
    """
    return list(dict.fromkeys(key for _, _, key in _metrics(_normalised(text))))


def _named_period(text: str) -> Period | None:
    between = BETWEEN_YEARS.search(text)
    if between is not None and int(between["b"]) == int(between["a"]) + 1:
        return Period("FY", fiscal_year=int(between["b"]))
    quarter = NAMED_QUARTER.search(text)
    if quarter:
        number = int(quarter["q"]) if quarter["q"] else ORDINAL_QUARTERS[quarter["ord"]]
        return Period("Q", fiscal_year=int(quarter["year"]), quarter=number)
    year = NAMED_YEAR.search(text)
    if year:
        return Period("FY", fiscal_year=int(year["year"]))
    return None


def _base_period(text: str, metric: str, *, amount: bool) -> Period:
    """The period the claim is about: named, trailing, annual, quarterly, else the default.

    The default is the latest quarter, except for an amount of money or a per-share
    amount of a flow, which reads the latest fiscal year: since rule 3 that default is
    reached only by the sign of a flow ("free cash flow is positive") and by a comparison
    of two flows; a flow against any other amount with no period named is refused
    (:func:`unplaced_amount`).
    """
    named = _named_period(text)
    if named is not None:
        return named
    if TTM.search(text):
        return Period("TTM")
    if ANNUAL.search(text) or OVER_YEARS.search(text):
        return Period("FY")
    if QUARTERLY.search(text) or SEQUENTIAL.search(text):
        return Period("Q")
    kind = METRICS[metric][1]
    if amount and kind in ("flow", "per_share"):
        return Period("FY")
    return Period("Q")


def _percent(match: re.Match[str]) -> float:
    return float(match["num"])


def _amount(match: re.Match[str]) -> float:
    value = float(match["num"].replace(",", ""))
    return value * SCALES.get(match["scale"] or "", 1.0)


# The forms


def _share(text: str) -> ClaimTest | NotNumeric | None:
    match = SHARE.match(text)
    if match is None:
        return None
    subject = match["subject"].strip()
    plural = re.search(r" (?:are|were) ", text[: match.end("subject") + 6]) is not None
    if SUM_OF_PARTS.search(subject) or (plural and " and " in subject):
        return NotNumeric(
            "a sum of several parts: a filing tags each part's revenue, not their sum"
        )
    when = match["when"] or ""
    period = Period("filing")
    if when:
        period = _named_period(when) or Period("Q" if "quarter" in when else "FY")
    revenue_of = SHARE_SUBJECT_REVENUE.match(subject)
    if revenue_of is not None and not _metrics(revenue_of["before"] or revenue_of["after"]):
        subject = (revenue_of["before"] or revenue_of["after"]).strip()
    raw = match["num"].replace("percent", "%").replace(" ", "")
    value = FRACTIONS[match["num"]] if match["num"] in FRACTIONS else float(raw.rstrip("%"))
    op = OP_OF[match["cmp"]]
    number = Number(value, "percent")
    named = [key for _, _, key in _metrics(subject)]
    if named:
        key = named[0]
        if key not in RATIO_OF and METRICS[key][1] != "ratio":
            return NotNumeric(f"a share of revenue for {METRICS[key][0].lower()}, which has none")
        ratio = RATIO_OF.get(key, key)
        period = _base_period(text, ratio, amount=False)
        return ClaimTest("threshold", Term("value", ratio, period), op, number)
    customer = CUSTOMER_SUBJECT.match(subject)
    if customer:
        negated = bool(customer["neg"])
        return ClaimTest(
            "share",
            Term("max_share", "customer", period),
            NEGATED[op] if negated else op,
            number,
        )
    if "customer" in subject:
        return NotNumeric("a group of customers: filings tag single customers' shares")
    axis = "geography" if GEOGRAPHIES.match(subject) else "segment"
    label = member_label(subject, axis)
    return ClaimTest("share", Term("share", axis, period, member=label), op, number)


def member_label(member: str, axis: str) -> str:
    """A segment's or a geography's name as a test writes it: "Data Center", "US"."""
    words = member.casefold().strip()
    if axis == "geography":
        words = words.removeprefix("the ")
    return " ".join(w.upper() if w in ("us", "u.s.") else w.title() for w in words.split())


def _compound(text: str, metric: str) -> ClaimTest | NotNumeric:
    years = COMPOUND_YEARS.search(text)
    span = SPAN.search(text)
    rate = PERCENT.search(text)
    if years is None and span is None:
        return NotNumeric("a compound rate needs a number of years")
    if rate is None:
        return NotNumeric("a compound rate needs a threshold (more than, at least, under N%)")
    period = Period("FY")
    if span is not None and years is None:
        # "from fiscal 2022 to fiscal 2025": three years, to fiscal 2025.
        count = int(span["b"]) - int(span["a"])
        period = Period("FY", fiscal_year=int(span["b"]))
    else:
        assert years is not None
        count = _count(years["a"] or years["b"] or years["c"])
    if count < 1:
        return NotNumeric("a compound rate needs at least one year")
    term = Term("cagr", metric, period, years=count)
    return ClaimTest("compound", term, OP_OF[rate["cmp"]], Number(_percent(rate), "percent"))


def _streak(text: str, metric: str, match: re.Match[str]) -> ClaimTest | NotNumeric:
    if DOWN_RE.search(text) or not UP_RE.search(text):
        return NotNumeric("a streak of declines is not a form this version computes")
    count = _count(match["n1"] or match["n2"] or match["n3"])
    unit = match["u1"] or match["u2"] or match["u3"]
    period = Period("Q" if unit == "quarters" else "FY")
    return ClaimTest("streak", Term("streak", metric, period), ">=", Number(count, "count"))


def _each_period(text: str, metric: str) -> ClaimTest | NotNumeric:
    """A test held in each of several periods: "in each of the last three fiscal years",
    "for the last four quarters", "every year since fiscal 2023", "for the second
    consecutive year", "in each quarter of fiscal 2026".

    The phrase is taken out and the rest read as a test of one period (the latest quarter
    or fiscal year, or the period it names), which then holds in each period stepped back
    from it. A rise in each of the last N periods stays a streak. Refused when the periods
    and the test disagree (quarters and years), when "grew in each quarter" does not say
    on what, and when "since" a year is said of a level, not of a change.
    """
    since = EACH_SINCE.search(text)
    ordinal = EACH_ORDINAL.search(text)
    quarter_of = EACH_QUARTER_OF.search(text)
    if since is not None:
        unit, count, spans = "year", 0, [since.span()]
    elif ordinal is not None:
        unit, count, spans = ordinal["unit"], ORDINAL_COUNTS[ordinal["ord"]], [ordinal.span()]
    elif quarter_of is not None:
        unit, count, spans = "quarter", 4, [quarter_of.span()]
    else:
        matches = list(EACH_PERIOD.finditer(text))
        units = {(m["unit"] or m["unit2"]).rstrip("s") for m in matches}
        counts = {_count(m["n"] or m["n2"]) for m in matches if m["n"] or m["n2"]}
        if len(units) != 1 or len(counts) != 1:
            return NotNumeric(
                "a condition held in each of several periods needs one number of quarters or "
                "years ('in each of the last three fiscal years')"
            )
        unit, count, spans = units.pop(), counts.pop(), [m.span() for m in matches]
        streak = _rises_in_a_row(text, metric, unit, count)
        if streak is not None:
            return streak
    if not 2 <= count <= MAX_EACH_PERIODS and since is None:
        return NotNumeric(f"each of 2 to {MAX_EACH_PERIODS} periods is what this version tests")
    rest = text
    for start, end in sorted(spans, reverse=True):
        rest = f"{rest[:start]} {rest[end:]}"
    if quarter_of is not None:
        rest += f" in the fourth quarter of fiscal {quarter_of['year']}"
    elif _named_period(rest) is None:
        rest += " in the latest fiscal year" if unit == "year" else " in the latest quarter"
    inner = _parse(_normalised(rest))
    if isinstance(inner, NotNumeric):
        return inner
    kind = "Q" if unit == "quarter" else "FY"
    kinds = {t.period.kind for t in inner.terms} | {t.base.kind for t in inner.terms if t.base}
    if inner.each or inner.each_since is not None or inner.also is not None:
        return NotNumeric("one test held in each of several periods, not several")
    if inner.form not in EACH_FORMS or inner.from_filing or kinds != {kind}:
        return NotNumeric(
            f"a {inner.form.replace('_', ' ')} of {', '.join(sorted(kinds))} held in each of "
            f"several {unit}s is not a test this version computes"
        )
    said = SEQUENTIAL.search(text) or re.search(YEAR_ON_YEAR, text)
    if inner.form == "direction" and unit == "quarter" and not said:
        return NotNumeric(
            "a rise or fall in each of several quarters: on the quarter before, or on a year "
            "earlier? Say 'sequentially' or 'year over year'"
        )
    if since is not None:
        rise = inner.form == "direction" and inner.right == replace(
            inner.left, period=inner.left.period.step_back()
        )
        growth = inner.form == "growth_threshold" and inner.left.fn == "yoy"
        if inner.left.period != Period("FY") or not (rise or growth):
            return NotNumeric(
                "every year since a named one, said of a level: whether that year itself "
                "counts is unclear; say 'in each of the last N fiscal years'"
            )
        return replace(inner, each_since=int(since["year"]))
    return replace(inner, each=count)


def _rises_in_a_row(text: str, metric: str, unit: str, count: int) -> ClaimTest | None:
    """A plain rise in each of the last N periods: the streak form (sequential quarters)."""
    rises = UP_RE.search(text) and not DOWN_RE.search(text)
    stated = PERCENT.search(text) or AMOUNT.search(text) or BARE_PERCENT.search(text)
    if not rises or stated or FASTER.search(text) or ACCELERATION.search(text):
        return None
    if _comparing_two(text) is not None:
        return None
    if unit == "quarter" and not SEQUENTIAL.search(text):
        return None
    period = Period("Q" if unit == "quarter" else "FY")
    return ClaimTest("streak", Term("streak", metric, period), ">=", Number(count, "count"))


def _faster(text: str, first: str, match: re.Match[str]) -> ClaimTest | NotNumeric:
    tail = [key for _, _, key in _metrics(match["tail"])]
    if not tail:
        return NotNumeric("the measure it is compared with is not in the metric set")
    second = tail[0]
    if METRICS[first][1] == "ratio" or METRICS[second][1] == "ratio":
        return NotNumeric("growth of a percentage is ambiguous (points or percent)")
    period = _base_period(text, first, amount=False)
    if period.kind == "TTM":
        period = Period("Q")
    op: Op = ">" if match["how"] in ("faster", "more quickly") else "<"
    return ClaimTest("faster_than", Term("yoy", first, period), op, Term("yoy", second, period))


def _acceleration(text: str, metric: str, match: re.Match[str]) -> ClaimTest | NotNumeric:
    if METRICS[metric][1] == "ratio":
        return NotNumeric("growth of a percentage is ambiguous (points or percent)")
    period = _base_period(text, metric, amount=False)
    if period.kind == "TTM":
        period = Period("Q")
    op: Op = ">" if match["how"].startswith(("accelerat", "speed", "sped")) else "<"
    left = Term("yoy", metric, period)
    return ClaimTest("acceleration", left, op, Term("yoy", metric, period.step_back()))


def _span(text: str) -> tuple[Period, Period] | NotNumeric | None:
    """(period, base) of a change over more than one fiscal year: "between fiscal 2023 and
    fiscal 2025", "since fiscal 2023", "over the past three fiscal years", "three times its
    fiscal 2023 level"; None for none (or for one year, which is a year-over-year change)."""
    times = TIMES_LEVEL.search(text)
    if times is not None:
        rest = text[: times.start()] + text[times.end() :]
        return _named_period(rest) or Period("FY"), Period("FY", fiscal_year=int(times["year"]))
    span = SPAN.search(text)
    if span is not None:
        first, last = int(span["a"]), int(span["b"])
        if last <= first:
            return NotNumeric("names a span of fiscal years that ends before it starts")
        if last == first + 1:
            return None
        return Period("FY", fiscal_year=last), Period("FY", fiscal_year=first)
    since = SINCE_YEAR.search(text)
    if since is not None:
        return Period("FY"), Period("FY", fiscal_year=int(since["year"]))
    years = OVER_YEARS.search(text)
    if years is not None and _count(years["n"]) > 1:
        return Period("FY"), Period("FY", _count(years["n"]))
    return None


def _multiple(text: str) -> tuple[Op, float] | None:
    """The growth a multiple states: "more than doubled" is > 100%, "tripled" >= 200%."""
    times = TIMES_LEVEL.search(text)
    if times is not None:
        return (">" if times["more"] else ">="), (_count(times["n"]) - 1) * 100.0
    doubled = DOUBLED.search(text)
    if doubled is not None:
        return (">" if doubled["more"] else ">="), MULTIPLE[doubled["times"]]
    return None


def _growth_threshold(text: str, metric: str) -> ClaimTest | NotNumeric | None:
    multiple = _multiple(text)
    rate = PERCENT.search(text)
    if multiple is None and rate is None:
        return None
    if METRICS[metric][1] == "ratio":
        if rate is not None and MOVED_BEFORE.search(text[: rate.start()]):
            return None  # "rose above 16%": a level, read as a threshold
        return NotNumeric("a change in a percentage is ambiguous (points or percent)")
    span = _span(text)
    if isinstance(span, NotNumeric):
        return span
    if span is not None:
        if SEQUENTIAL.search(text):
            return NotNumeric("sequential growth is a quarter's: it names a span of years")
        period, base = span
        op, value = multiple or _rate(text, rate)
        term = Term("change", metric, period, base=base)
        return ClaimTest("growth_threshold", term, op, Number(value, "percent"))
    fn: Function = "qoq" if SEQUENTIAL.search(text) else "yoy"
    period = _base_period(text, metric, amount=False)
    if period.kind == "TTM":
        period = Period("Q")
    if fn == "qoq" and period.kind != "Q":
        return NotNumeric("sequential growth is a quarter's: it names a fiscal year")
    op, value = multiple or _rate(text, rate)
    return ClaimTest("growth_threshold", Term(fn, metric, period), op, Number(value, "percent"))


def _rate(text: str, rate: re.Match[str] | None) -> tuple[Op, float]:
    """A growth rate's comparison and value; "declined more than 10%" is below -10%."""
    assert rate is not None
    op = OP_OF[rate["cmp"]]
    value = _percent(rate)
    before = text[: rate.start()]
    if DOWN_RE.search(before) and not UP_RE.search(before) and value > 0:
        op, value = FLIPPED[op], -value
    return op, value


def _threshold(text: str, metric: str) -> ClaimTest | NotNumeric | None:
    kind = METRICS[metric][1]
    rate, amount = PERCENT.search(text), AMOUNT.search(text)
    if rate is None and amount is None:
        return None
    if rate is not None and (amount is None or rate.start() < amount.start()):
        if kind != "ratio":
            ratio = _ratio_named_after(text[rate.end() :], metric)
            if ratio is None:
                return NotNumeric("a percent threshold on an amount: say what it is a percent of")
            period = _base_period(text, ratio, amount=False)
            number = Number(_percent(rate), "percent")
            return ClaimTest("threshold", Term("value", ratio, period), OP_OF[rate["cmp"]], number)
        period = _base_period(text, metric, amount=False)
        number = Number(_percent(rate), "percent")
        return ClaimTest("threshold", Term("value", metric, period), OP_OF[rate["cmp"]], number)
    assert amount is not None
    if kind == "ratio":
        return NotNumeric("an amount of money as the threshold of a percentage")
    period = _base_period(text, metric, amount=True)
    number = Number(_amount(amount), "USD")
    return ClaimTest("threshold", Term("value", metric, period), OP_OF[amount["cmp"]], number)


def _ratio_named_after(after: str, metric: str) -> str | None:
    """The ratio of ``metric`` to the measure named after a percent ("15% of revenue")."""
    if not re.match(r"\s*of\b", after):
        return None
    named = _metrics(after)
    if not named:
        return None
    over = named[0][2]
    return next(
        (ratio for ratio, (top, bottom) in RATIO_PARTS.items() if top == metric and bottom == over),
        None,
    )


def _comparing_two(text: str) -> tuple[str, str, re.Match[str]] | None:
    """Two different measures with a comparison word between them: (first, second, word)."""
    named = _metrics(text)
    keys = list(dict.fromkeys(key for _, _, key in named))
    if len(keys) != 2:
        return None
    first = named[0]
    second = next(n for n in named if n[2] != first[2])
    word = COMPARE_RE.search(text, first[1], second[0])
    return (first[2], second[2], word) if word is not None else None


def _compare(text: str) -> ClaimTest | NotNumeric | None:
    """The levels of two measures in one period: "operating cash flow was above net income"."""
    found = _comparing_two(text)
    if found is None:
        return None
    first, second, word = found
    rest = text[: word.start()] + " " + text[word.end() :]
    stated = (PERCENT, AMOUNT, BARE_PERCENT, BARE_AMOUNT, DOUBLED, TIMES_LEVEL, GROWTH_WORD)
    if any(pattern.search(rest) for pattern in stated):
        return None
    if METRICS[first][1] != METRICS[second][1]:
        return NotNumeric(
            f"compares {METRICS[first][0].lower()} with {METRICS[second][0].lower()}, "
            "which are not the same kind of number"
        )
    op = dict(LEVEL_COMPARATORS).get(word.group(0)) or OP_OF[word.group(0)]
    period = _base_period(text, first, amount=True)
    return ClaimTest("compare", Term("value", first, period), op, Term("value", second, period))


def _direction(text: str, metric: str) -> ClaimTest | None:
    up, down = UP_RE.search(text), DOWN_RE.search(text)
    if bool(up) == bool(down):
        return None
    op: Op = ">" if up else "<"
    span = _span(text)
    if isinstance(span, tuple) and not TIMES_LEVEL.search(text):
        period, base = span
        now, then = Term("value", metric, period), Term("value", metric, base)
        return ClaimTest("direction", now, op, then)
    years = OVER_YEARS.search(text)
    named = _named_period(text)
    if named is not None:
        base = named.step_back() if named.quarter is None else named.years_back(1)
        if SEQUENTIAL.search(text) and named.quarter is not None:
            base = named.step_back()
        return ClaimTest("direction", Term("value", metric, named), op, Term("value", metric, base))
    if years is not None:
        period = Period("FY")
        earlier = period.years_back(_count(years["n"]))
    elif TTM.search(text):
        period = Period("TTM")
        earlier = period.years_back(1)
    elif SEQUENTIAL.search(text):
        period = Period("Q")
        earlier = period.step_back()
    elif ANNUAL.search(text):
        period = Period("FY")
        earlier = period.step_back()
    else:
        period = Period("Q")
        earlier = period.years_back(1)
    return ClaimTest("direction", Term("value", metric, period), op, Term("value", metric, earlier))


def compile_claim(text: str) -> ClaimTest | NotNumeric:
    """The typed test a claim states, or why it is not a numeric claim this version computes.

    A claim compiles only when the test explains every content word of it
    (:func:`unexplained`); otherwise it is refused, naming the words left over. A claim
    refused whole may be two tests joined by "and" (:func:`_joined`).
    """
    whole = _compile_one(text)
    if isinstance(whole, ClaimTest):
        result: ClaimTest | NotNumeric = whole
    else:
        joined = _joined(text)
        result = whole if joined is None else joined
    if isinstance(result, ClaimTest):
        unplaced = unplaced_amount(text, result)
        if unplaced is not None:
            return NotNumeric(unplaced)
    return result


def _compile_one(text: str) -> ClaimTest | NotNumeric:
    claim = _normalised(text)
    result = _parse(claim)
    if isinstance(result, NotNumeric) or SHARE.match(claim):
        # A share is read by one anchored pattern, which explains the sentence whole.
        return result
    if isinstance(result.right, Term) and result.right.text() == result.left.text():
        left_over = unexplained(text, result)
        return NotNumeric(_not_understood(left_over) or "compares a measure with itself")
    left_over = unexplained(text, result)
    if left_over:
        return NotNumeric(_not_understood(left_over))
    return result


def _joined(text: str) -> ClaimTest | NotNumeric | None:
    """Two tests joined by "and", each a whole claim by itself; None when it is not that.

    Not tried when a contrast, a trap or a judgement is anywhere in the claim. Refused when
    a period is named in one part only (it may be meant for both), and when the claim
    splits into two tests at more than one "and".
    """
    claim = _normalised(text)
    if CONTRAST.search(claim) or JUDGEMENT.search(claim):
        return None
    if any(pattern.search(claim) for pattern, _ in TRAPS):
        return None
    found = []
    for match in AND_SPLIT.finditer(text):
        first = _compile_one(text[: match.start()])
        second = _compile_one(text[match.end() :])
        if isinstance(first, ClaimTest) and isinstance(second, ClaimTest):
            found.append((match, first, second))
    if not found:
        return None
    if len(found) > 1:
        return NotNumeric("reads as two tests joined by 'and' in more than one way")
    match, first, second = found[0]
    if _names_period(_normalised(text[: match.start()])) != _names_period(
        _normalised(text[match.end() :])
    ):
        return NotNumeric(
            "two tests joined by 'and', with a period named in one of them only: it may be "
            "meant for both; name it in each"
        )
    return replace(first, also=second)


# Rule 3, made on 18 November 2026 after set C was read and scored (set C's score does not
# reflect it): a flow compared with an amount of money in a sentence that names no period.
NO_PERIOD_REASON = "names no period: a quarter's amount or a year's?"


def unplaced_amount(claim: str, test: ClaimTest) -> str | None:
    """:data:`NO_PERIOD_REASON` when ``test`` compares a flow with an amount and ``claim``
    names no period; None otherwise.

    A flow is an amount over a period (revenue, an expense, a cash flow), a per-share amount
    of one, or a part's figure; a quarter's and a year's differ about four times over, so
    whichever period a reader picks, the sentence did not say it. Applies to every reader's
    test, the grammar's and the models'. A ratio or a balance is not a flow, and the sign of
    a flow (an amount of zero) is not a size, so neither is refused.
    """
    if _names_period(_normalised(claim)):
        return None
    for part in test.parts:
        right = part.right
        if not isinstance(right, Number) or right.unit == "percent" or right.value == 0:
            continue
        if part.form != "threshold" or part.left.fn != "value":
            continue
        if part.left.axis or METRICS[part.left.subject][1] in ("flow", "per_share"):
            return NO_PERIOD_REASON
    return None


# A fiscal year written with two digits ("FY26", "fiscal '25"): the grammar does not read it,
# but a sentence that says it names its period.
SHORT_FISCAL_YEAR = re.compile(r"\bfy\s?'?\d{2}\b|\bfiscal (?:year )?'\d{2}\b")


def _names_period(claim: str) -> bool:
    """True when the claim names its period (a fiscal year or quarter, the latest year, a span)."""
    patterns = (
        SHORT_FISCAL_YEAR,
        NAMED_QUARTER,
        NAMED_YEAR,
        TTM,
        ANNUAL,
        QUARTERLY,
        OVER_YEARS,
        SPAN,
        SINCE_YEAR,
        EACH_PERIOD,
        EACH_SINCE,
        EACH_ORDINAL,
        EACH_QUARTER_OF,
    )
    return any(pattern.search(claim) for pattern in patterns)


def _parse(claim: str) -> ClaimTest | NotNumeric:
    """The test the grammar reads in a normalised claim, before the whole-sentence check."""
    if not claim:
        return NotNumeric("an empty claim")
    if len(claim) > MAX_CLAIM_CHARS:
        return NotNumeric(f"longer than {MAX_CLAIM_CHARS} characters: state one test per claim")
    for pattern, reason in TRAPS:
        if pattern.search(claim):
            return NotNumeric(reason)
    if UNNAMED_MARGIN.search(claim):
        return NotNumeric("does not say which margin (gross, operating, net or free cash flow)")
    if JUDGEMENT.search(claim):
        return NotNumeric("a judgement, not a quantity")
    if CONTRAST.search(claim):
        return NotNumeric(
            "two statements joined by a contrast: one test would be half the claim; "
            "state each as a claim of its own"
        )
    share = _share(claim)
    if share is not None:
        return share
    part = PART_BEFORE_MEASURE.search(claim)
    if part is not None and PART_BEFORE_REVENUE.search(claim):
        return NotNumeric(
            f"'{part['part']}' names a part of the company (a segment, a product "
            "or a geography), whose revenue is "
            "not the company's: only a part's share of revenue is read, from the newest "
            "filing's tags, and it has no history in the facts"
        )
    if part is not None:
        return NotNumeric(
            f"'{part['part']}' qualifies the measure, and a segment's, a product's "
            "or a geography's figure is not the company's; only its share of revenue is read, "
            "from the newest filing's tags"
        )
    named = _metrics(claim)
    if not named:
        if re.search(r"\bgrowth\b", claim):
            return NotNumeric("does not say growth of what")
        return NotNumeric("does not name a measure in the metric set")
    metric = named[0][2]
    if METRICS[metric][1] in ("instant", "flow"):
        sign = SIGN.search(claim)
        if HAS_NONE.search(claim) or sign:
            op: Op = "<=" if not sign else "<" if sign["sign"] == "negative" else ">"
            period = _base_period(claim, metric, amount=True)
            return ClaimTest("threshold", Term("value", metric, period), op, Number(0.0, "USD"))
    if any(p.search(claim) for p in (EACH_SINCE, EACH_ORDINAL, EACH_QUARTER_OF, EACH_PERIOD)):
        return _each_period(claim, metric)
    faster = FASTER.search(claim)
    if faster is not None:
        return _faster(claim, metric, faster)
    if COMPOUND.search(claim):
        return _compound(claim, metric)
    streak = STREAK.search(claim)
    if streak is not None:
        return _streak(claim, metric, streak)
    acceleration = ACCELERATION.search(claim)
    if acceleration is not None:
        return _acceleration(claim, metric, acceleration)
    compare = _compare(claim)
    if compare is not None:
        return compare
    if GROWTH_WORD.search(claim) or DOUBLED.search(claim) or TIMES_LEVEL.search(claim):
        growth = _growth_threshold(claim, metric)
        if growth is not None:
            return growth
    threshold = _threshold(claim, metric)
    if threshold is not None:
        return threshold
    if BARE_PERCENT.search(claim) or BARE_AMOUNT.search(claim):
        return NotNumeric(
            "states an exact figure: this version tests a threshold "
            "(more than, at least, under) or a direction"
        )
    direction = _direction(claim, metric)
    if direction is not None:
        return direction
    return NotNumeric("states no direction, threshold or comparison that can be computed")


# The whole-sentence rule

# Words that carry no meaning for a test, whatever it is. Kept short on purpose: a word not
# here must be explained by the test the claim compiled to, or the claim is refused.
NO_MEANING = frozenset(
    "a an the is are was were be been being has have had it its their this that of in on at "
    "for to from by with as and than company company's still now currently total reported "
    "also".split()
)
PART_BEFORE_MEASURE = re.compile(
    rf"(?<![\w&])(?P<part>{PARTS})(?:'s)?\s+(?:{'|'.join(f'(?:{p})' for p, _ in METRIC_PHRASES)})"
    r"(?![\w&])"
)
CURRENT = r"\b(?:latest|most recent|last|this|current|newest|recent|reported)\b"
YEAR_ON_YEAR = (
    r"\byear[- ]over[- ]year\b|\byoy\b|\by/y\b|\b(?:from|than|versus|vs\.?|compared (?:with|to)|"
    r"on|over) (?:a|the|one) (?:year|prior year|year earlier)(?: earlier| ago| before)?\b|"
    r"\ba year (?:earlier|ago|before)\b|"
    r"\b(?:the )?(?:same|year-ago) quarter(?: a year (?:ago|earlier))?\b"
)
QUARTER_ON_QUARTER = rf"{SEQUENTIAL.pattern}|\b(?:the )?(?:previous|prior|preceding|last) quarter\b"
YEAR_END = r"\b(?:at |as of )?(?:the )?(?:fiscal )?year[- ]end\b|\bend of the (?:fiscal )?year\b"
COMPARING = r"\b(?:versus|vs\.?|compared (?:with|to)|against)\b"
LEVEL_VERBS = r"\b(?:held|holds|stood|stands|came in|sits|sat|remained|remains|stayed|stays)\b"
GROWTH_NOUNS = r"\b(?:growth|rate|grew|growing|grown)\b"
COMPOUND_WORDS = r"\b(?:annual(?:ly)?|a year|per year|rate|growth|at)\b"
_TOKEN = re.compile(r"¦|[^\s,;:()¦]+")


def _period_words(term: Term, first: bool) -> list[str]:
    """Patterns for the words that name ``term``'s period."""
    period = term.period
    words: list[str] = []
    if period.fiscal_year is not None:
        # Only the years this test is bound to are explained, never any other year named.
        year = period.fiscal_year
        fiscal = r"(?:fiscal(?: year)?\s*|fy\s?)"
        if period.quarter is not None:
            ordinal = {v: k for k, v in ORDINAL_QUARTERS.items()}[period.quarter]
            words.append(
                rf"\b(?:q{period.quarter}|(?:the )?{ordinal} quarter)\s+(?:of\s+)?{fiscal}{year}\b"
            )
            return words
        words.append(rf"\b{fiscal}?{year}\b")
        if term.fn == "yoy":
            # Growth in a fiscal year is against the year before, which may be named too.
            words.append(rf"\b(?:between|from) {fiscal}{year - 1} (?:and|to) {fiscal}?{year}\b")
        if term.fn == "cagr":
            # "from fiscal 2022 to fiscal 2025": the span of a compound rate to a named year.
            words.append(rf"\b(?:between|from|over) {fiscal}{year - term.years}\b")
            words.append(r"\b(?:to|through)\b")
        if not first:
            words.append(rf"\b(?:between|from|over|across|since) {fiscal}{year}\b")
            words.append(r"\bthrough\b")
        return words + _base_words(term)
    if period.kind == "TTM":
        words.append(TTM.pattern)
        words.append(r"\b(?:over|in|during|for)\b(?= (?:the )?(?:trailing|last)[- ](?:twelve|12))")
        if period.back:
            words.append(YEAR_ON_YEAR)
        return words
    if period.kind == "FY":
        words += [ANNUAL.pattern, YEAR_END]
        if period.back == 0:
            words.append(CURRENT)
        else:
            prior = r"\b(?:the )?(?:prior|previous) (?:fiscal )?year\b"
            words += [OVER_YEARS.pattern, YEAR_ON_YEAR, prior]
        return words + _base_words(term)
    if period.kind == "Q":
        words.append(QUARTERLY.pattern)
        if period.back == 0:
            words.append(CURRENT)
        elif period.back == 1:
            words.append(QUARTER_ON_QUARTER)
        elif period.back == 4:
            words.append(YEAR_ON_YEAR)
    return words


def _base_words(term: Term) -> list[str]:
    """The words naming where a change runs from: "since fiscal 2023", "over the past three
    fiscal years", "between fiscal 2023 and fiscal 2025", "its fiscal 2023 level"."""
    base = term.base
    if base is None:
        return []
    if base.fiscal_year is None:
        return [OVER_YEARS.pattern]
    fiscal = r"(?:fiscal(?: year)?\s*|fy\s?)"
    year = base.fiscal_year
    return [
        rf"\b(?:between|from|over|across|since) {fiscal}{year}\b",
        rf"\b(?:its|the) {fiscal}{year} (?:level|figure|amount)\b",
        r"\b(?:to|through)\b",
    ]


def _explaining(test: ClaimTest) -> list[str]:
    """Every pattern whose words the test explains: measures, comparison, periods, form."""
    terms = [test.left] + ([test.right] if isinstance(test.right, Term) else [])
    words: list[str] = _form_words(test)
    for index, term in enumerate(terms):
        words += [pattern for pattern, key in METRIC_PHRASES if key == term.subject]
        if term.subject in CATALOGUE and CATALOGUE[term.subject].also:
            words.append(CATALOGUE[term.subject].also)
        if term.subject in RATIO_PARTS:
            # "operating expenses were under 15% of revenue": the ratio's two measures.
            over = RATIO_PARTS[term.subject][1]
            tops = [top for top, ratio in RATIO_OF.items() if ratio == term.subject]
            tops.append(RATIO_PARTS[term.subject][0])
            words += [CATALOGUE[top].names for top in tops]
            words.append(rf"\bof (?:the )?(?:total |net )?(?:{CATALOGUE[over].names})(?![\w&])")
        words += _period_words(term, index == 0)
        if term.fn in ("yoy", "qoq", "cagr"):
            words.append(GROWTH_NOUNS)
        if term.fn == "yoy":
            words.append(YEAR_ON_YEAR)
        if term.fn == "qoq":
            words.append(QUARTER_ON_QUARTER)
    if isinstance(test.right, Term):
        words.append(COMPARING)
    return words


def _form_words(test: ClaimTest) -> list[str]:
    """The words of the test's form, longest phrases first, so they are struck out whole."""
    words: list[str] = []
    if test.each or test.each_since is not None:
        each = (EACH_PERIOD, EACH_SINCE, EACH_ORDINAL, EACH_QUARTER_OF)
        words += [pattern.pattern for pattern in each]
    up_or_down = UP if test.op in (">", ">=") else DOWN
    match test.form:
        case "direction":
            words.append(rf"\b(?:{up_or_down})\b")
        case "threshold":
            words += [PERCENT.pattern, AMOUNT.pattern, LEVEL_VERBS, MOVED_TO]
            if isinstance(test.right, Number) and test.right.value == 0:
                words.append(HAS_NONE.pattern if test.op == "<=" else SIGN.pattern)
        case "growth_threshold":
            words += [PERCENT.pattern, DOUBLED.pattern, rf"\b(?:{UP}|{DOWN})\b", GROWTH_NOUNS]
            words.append(TIMES_LEVEL.pattern)
        case "faster_than":
            words += [FASTER.pattern.split(" than ")[0] + " than", GROWTH_NOUNS]
        case "acceleration":
            words += [ACCELERATION.pattern, GROWTH_NOUNS]
        case "compound":
            words += [COMPOUND.pattern, COMPOUND_YEARS.pattern, PERCENT.pattern, COMPOUND_WORDS]
        case "streak":
            words += [STREAK.pattern, EACH_PERIOD.pattern, rf"\b(?:{UP})\b", QUARTER_ON_QUARTER]
        case "compare":
            words += [COMPARE_RE.pattern, LEVEL_VERBS]
    return words


def unexplained(text: str, test: ClaimTest) -> list[str]:
    """The phrases of ``text`` that ``test`` does not explain, in order; empty when none.

    Every match of a pattern the test explains (:func:`_explaining`), each found in the
    whole claim so that the order of the patterns does not matter, is struck out; then
    the words left are read in runs: a run with any word not in :data:`NO_MEANING` is
    unexplained. A possessive name opening the claim ("NVIDIA's") names the company.
    """
    claim = _normalised(text)
    subject = re.match(r"\s*([A-Z][\w&.-]*)(?:'s|’s)\b", text)
    if subject is not None:
        claim = re.sub(rf"^{re.escape(subject.group(1).casefold())}'s\b", "¦", claim)
    company = COMPANY_VERB.match(text)
    if company is not None:
        claim = re.sub(rf"^{re.escape(company.group(1).casefold())}\b", "¦", claim)
    covered = [False] * len(claim)
    for pattern in _explaining(test):
        for match in re.finditer(pattern, claim):
            covered[match.start() : match.end()] = [True] * (match.end() - match.start())
    claim = "".join(" ¦ " if hit else char for char, hit in zip(claim, covered, strict=True))
    runs: list[list[str]] = [[]]
    for token in _TOKEN.findall(claim):
        if token == "¦":
            runs.append([])
        else:
            runs[-1].append(token.strip(".'\""))
    phrases = []
    for run in runs:
        words = [w for w in run if w]
        while words and words[0] in NO_MEANING:
            words.pop(0)
        while words and words[-1] in NO_MEANING:
            words.pop()
        if words:
            phrases.append(" ".join(words))
    return phrases


def _not_understood(phrases: list[str]) -> str:
    if not phrases:
        return ""
    named = ", ".join(f"'{phrase}'" for phrase in phrases)
    verb = "is" if len(phrases) == 1 else "are"
    return f"not compiled: {named} {verb} not understood"
