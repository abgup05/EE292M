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

from app.core.limits import MAX_CLAIM_CHARS
from app.core.measures import CATALOGUE
from app.core.measures import RATIO_OF as CATALOGUE_RATIO_OF

Form = Literal[
    "direction",
    "acceleration",
    "streak",
    "threshold",
    "growth_threshold",
    "faster_than",
    "compound",
    "share",
]
Op = Literal[">", ">=", "<", "<="]
PeriodKind = Literal["Q", "FY", "TTM", "filing"]
Function = Literal["value", "yoy", "qoq", "streak", "cagr", "share", "max_share"]
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
    along ``axis``), read from the newest filing (:data:`app.core.measures.PART_MEASURES`).
    """

    fn: Function
    subject: str
    period: Period
    member: str = ""
    years: int = 0
    axis: str = ""

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
    """A compiled claim: ``left op right``, of one :data:`Form`."""

    form: Form
    left: Term
    op: Op
    right: Term | Number

    @property
    def canonical(self) -> str:
        """The test as the labels write it."""
        return f"{self.left.text()} {self.op} {self.right.text()}"


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
    r"improv(?:ing|ed|es)|widen(?:ing|ed|s)?|up|higher|climb(?:ing|ed|s)?"
)
DOWN = (
    r"shrink(?:ing|s)?|shrank|declin(?:ing|ed|es)|fall(?:ing|en|s)?|fell|"
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
QUARTERLY = re.compile(
    r"\bquarterly\b|\b(?:last|latest|most recent|this) quarter(?:'s)?\b|\ba quarter\b"
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
DOUBLED = re.compile(r"\b(?:(?P<more>more than )|at least )?(?P<times>doubled|tripled)\b")
SHARE = re.compile(
    rf"^(?:the )?(?P<subject>.+?) (?:is|are|was|were|accounts? for|accounted for|"
    rf"represents?|represented|makes? up|made up|comprises?|comprised) (?:now |still )?"
    rf"(?P<cmp>{CMP}) (?P<num>-?\d+(?:\.\d+)?\s*(?:%|percent)|half|a half|a quarter|a third)"
    r" of (?:(?:total |the company's |its |all |net )?(?:net )?(?:revenues?|sales)|the total)$"
)
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
    amount of a flow, which reads the latest fiscal year.
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
            Term("max_share", "customer", Period("filing")),
            NEGATED[op] if negated else op,
            number,
        )
    if "customer" in subject:
        return NotNumeric("a group of customers: filings tag single customers' shares")
    axis = "geography" if GEOGRAPHIES.match(subject) else "segment"
    label = member_label(subject, axis)
    return ClaimTest("share", Term("share", axis, Period("filing"), member=label), op, number)


def member_label(member: str, axis: str) -> str:
    """A segment's or a geography's name as a test writes it: "Data Center", "US"."""
    words = member.casefold().strip()
    if axis == "geography":
        words = words.removeprefix("the ")
    return " ".join(w.upper() if w in ("us", "u.s.") else w.title() for w in words.split())


def _compound(text: str, metric: str) -> ClaimTest | NotNumeric:
    years = COMPOUND_YEARS.search(text)
    rate = PERCENT.search(text)
    if years is None:
        return NotNumeric("a compound rate needs a number of years")
    if rate is None:
        return NotNumeric("a compound rate needs a threshold (more than, at least, under N%)")
    count = _count(years["a"] or years["b"] or years["c"])
    if count < 1:
        return NotNumeric("a compound rate needs at least one year")
    term = Term("cagr", metric, Period("FY"), years=count)
    return ClaimTest("compound", term, OP_OF[rate["cmp"]], Number(_percent(rate), "percent"))


def _streak(text: str, metric: str, match: re.Match[str]) -> ClaimTest | NotNumeric:
    if DOWN_RE.search(text) or not UP_RE.search(text):
        return NotNumeric("a streak of declines is not a form this version computes")
    count = _count(match["n1"] or match["n2"] or match["n3"])
    unit = match["u1"] or match["u2"] or match["u3"]
    period = Period("Q" if unit == "quarters" else "FY")
    return ClaimTest("streak", Term("streak", metric, period), ">=", Number(count, "count"))


def _each_period(text: str, metric: str, match: re.Match[str]) -> ClaimTest | NotNumeric:
    """A rise in each of the last N periods is a streak; any other condition held over
    several periods is not a form this version computes."""
    held = NotNumeric(
        "a condition held in each of several periods: this version tests one period, "
        "or rises in a row (the streak form)"
    )
    count = match["n"] or match["n2"]
    unit = (match["unit"] or match["unit2"]).rstrip("s")
    rises = UP_RE.search(text) and not DOWN_RE.search(text)
    stated = PERCENT.search(text) or AMOUNT.search(text) or BARE_PERCENT.search(text)
    if count is None or not rises or stated or FASTER.search(text) or ACCELERATION.search(text):
        return held
    if unit == "quarter" and not SEQUENTIAL.search(text):
        # "grew in each of the last six quarters" could be year over year or sequential.
        return held
    period = Period("Q" if unit == "quarter" else "FY")
    return ClaimTest("streak", Term("streak", metric, period), ">=", Number(_count(count), "count"))


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


def _growth_threshold(text: str, metric: str) -> ClaimTest | NotNumeric | None:
    doubled = DOUBLED.search(text)
    rate = PERCENT.search(text)
    if doubled is None and rate is None:
        return None
    if METRICS[metric][1] == "ratio":
        if rate is not None and MOVED_BEFORE.search(text[: rate.start()]):
            return None  # "rose above 16%": a level, read as a threshold
        return NotNumeric("a change in a percentage is ambiguous (points or percent)")
    fn: Function = "qoq" if SEQUENTIAL.search(text) else "yoy"
    period = _base_period(text, metric, amount=False)
    if period.kind == "TTM":
        period = Period("Q")
    if fn == "qoq" and period.kind != "Q":
        return NotNumeric("sequential growth is a quarter's: it names a fiscal year")
    if doubled is not None:
        value = 100.0 if doubled["times"] == "doubled" else 200.0
        op: Op = ">" if doubled["more"] else ">="
        return ClaimTest("growth_threshold", Term(fn, metric, period), op, Number(value, "percent"))
    assert rate is not None
    op = OP_OF[rate["cmp"]]
    value = _percent(rate)
    before = text[: rate.start()]
    if DOWN_RE.search(before) and not UP_RE.search(before) and value > 0:
        # "declined more than 10%": the growth is below -10%.
        op, value = FLIPPED[op], -value
    return ClaimTest("growth_threshold", Term(fn, metric, period), op, Number(value, "percent"))


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


def _direction(text: str, metric: str) -> ClaimTest | None:
    up, down = UP_RE.search(text), DOWN_RE.search(text)
    if bool(up) == bool(down):
        return None
    op: Op = ">" if up else "<"
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
    (:func:`unexplained`); otherwise it is refused, naming the words left over.
    """
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
    each = EACH_PERIOD.search(claim)
    if each is not None:
        return _each_period(claim, metric, each)
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
    if GROWTH_WORD.search(claim) or DOUBLED.search(claim):
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
        if not first:
            words.append(rf"\b(?:between|from) {fiscal}{year}\b")
        return words
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
        return words
    if period.kind == "Q":
        words.append(QUARTERLY.pattern)
        if period.back == 0:
            words.append(CURRENT)
        elif period.back == 1:
            words.append(QUARTER_ON_QUARTER)
        elif period.back == 4:
            words.append(YEAR_ON_YEAR)
    return words


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
        case "faster_than":
            words += [FASTER.pattern.split(" than ")[0] + " than", GROWTH_NOUNS]
        case "acceleration":
            words += [ACCELERATION.pattern, GROWTH_NOUNS]
        case "compound":
            words += [COMPOUND.pattern, COMPOUND_YEARS.pattern, PERCENT.pattern, COMPOUND_WORDS]
        case "streak":
            words += [STREAK.pattern, EACH_PERIOD.pattern, rf"\b(?:{UP})\b", QUARTER_ON_QUARTER]
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
