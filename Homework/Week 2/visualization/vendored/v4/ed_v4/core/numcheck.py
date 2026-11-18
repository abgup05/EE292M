"""The numeric check: every number a statement writes must appear in what it cites.

The quote gate proves a quote is in the filing; it does not notice a statement
that says "revenue grew 65%" above a quote that says 56%. This module closes
that hole deterministically. :func:`quantities` reads the numbers a text
writes, with their unit, scale and sign; :func:`check_numbers` requires each
number of a statement to match a number of its quotes or of its cited
reported figures.

The rules:

- Units must agree: a percent matches a percent (percentage points count as
  percent); N basis points match N/100 percent; USD matches USD; a multiple
  ("30x", "3 times") matches a multiple. A plain number and a USD amount may
  match each other, because filing tables often omit the dollar sign.
- The tolerance is half a unit in the last digit the *statement* wrote: "56%"
  matches 55.6% and 56.4% but not 55.4%; "$46.7 billion" matches $46,743 million.
- A plain or USD number in a quote with no scale word (a table cell such as
  "Revenue $ 46,743") also matches at 1e3, 1e6 or 1e9 times its value.
- An unsigned statement number matches a source of either sign ("fell 3%"
  against "(3)%"); a negative statement number needs a negative source.
- Not quantities: years 1900-2100 written as four bare digits, form and item
  names, quarter and fiscal labels, ordinals, alphanumeric product names,
  numbers inside a date, and bare integers from 0 to 12 with no unit.

Pure: no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from ed_v4.core.metric_models import Metric

Unit = Literal["percent", "bps", "usd", "multiple", "plain"]
Status = Literal["none", "passed", "failed"]

SCALES: dict[str, float] = {
    "thousand": 1e3,
    "million": 1e6,
    "billion": 1e9,
    "trillion": 1e12,
}
# Abbreviations recognised only directly after a dollar amount ("$2.5B", "$45mm").
SCALE_ABBREVIATIONS: dict[str, float] = {"K": 1e3, "M": 1e6, "B": 1e9, "bn": 1e9, "mm": 1e6}
TABLE_SCALES: tuple[float, ...] = (1.0, 1e3, 1e6, 1e9)
MAX_EXEMPT_COUNT = 12
YEARS = range(1900, 2101)

_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
    r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
# Spans whose digits are labels or dates, not quantities.
_MASKS: tuple[re.Pattern[str], ...] = (
    re.compile(rf"\b{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?\b"),
    re.compile(rf"\b{_MONTH}\.?,?\s+\d{{4}}\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"),
    re.compile(r"\b\d{1,2}-[A-Z]{1,2}(?:/A)?\b"),  # 10-K, 10-Q, 8-K, 20-F, 10-K/A
    re.compile(
        r"\b(?:Items?|Parts?|Rules?|Sections?|Notes?|Form|Schedules?|Exhibits?|Articles?|"
        r"Regulation|Chapter|Level|Tier|Phase|Page)\s+[\w.\-]+",
        re.IGNORECASE,
    ),
    re.compile(r"\bfiscal(?:\s+years?)?\s+'?\d{2,4}\b", re.IGNORECASE),
    re.compile(r"\b(?:FY|CY)\s?'?\d{2,4}\b", re.IGNORECASE),
)
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+")
_CURRENCY_BEFORE = re.compile(r"(?:US\$|\$|\bUSD)\s?$")
_SCALE_AFTER = re.compile(r"\s?(thousand|million|billion|trillion)\b", re.IGNORECASE)
_ABBREVIATION_AFTER = re.compile(r"(K|M|B|bn|mm)\b")
_UNIT_AFTER: tuple[tuple[re.Pattern[str], Unit], ...] = (
    (re.compile(r"\s?%"), "percent"),
    (re.compile(r"\s?percentage[\s-]points?\b", re.IGNORECASE), "percent"),
    (re.compile(r"\s?(?:percent|per\s+cent)\b", re.IGNORECASE), "percent"),
    (re.compile(r"\s?(?:basis\s+points?|bps|bp)\b", re.IGNORECASE), "bps"),
    (re.compile(r"x\b"), "multiple"),
    (re.compile(r"\s(?:times)\b", re.IGNORECASE), "multiple"),
    (re.compile(r"\s?(?:dollars|USD)\b"), "usd"),
)
_ORDINAL_AFTER = re.compile(r"(?:st|nd|rd|th)\b")
_CAPS_WORD_BEFORE = re.compile(r"\b([A-Z]{2,}[A-Za-z]*)\s$")
_MINUS = "-−–"


@dataclass(frozen=True)
class Quantity:
    """One number as a text wrote it.

    ``value`` is normalised: USD in dollars, a percent as 55.6 for 55.6%,
    negative when written in parentheses or with a leading minus.
    ``decimals`` counts the digits written after the decimal point and
    ``scale`` is the multiplier of a scale word (1 when none was written), so
    the precision written is ``10 ** -decimals * scale``.
    """

    raw: str
    value: float
    unit: Unit
    decimals: int
    scale: float = 1.0
    signed: bool = False

    @property
    def tolerance(self) -> float:
        """Half a unit in the last digit written."""
        return 0.5 * 10.0**-self.decimals * self.scale


@dataclass(frozen=True)
class NumberCheck:
    """The outcome of :func:`check_numbers`.

    ``status`` is "none" when the statement has no quantity, "passed" when
    every quantity matched, "failed" otherwise. ``details`` has one sentence
    per quantity; ``unmatched`` lists the raw text of each one not found.
    """

    status: Status
    details: list[str]
    checked: int
    unmatched: list[str]


def _masked(text: str) -> list[tuple[int, int]]:
    return [match.span() for pattern in _MASKS for match in pattern.finditer(text)]


def _inside(span: tuple[int, int], masks: Iterable[tuple[int, int]]) -> bool:
    return any(begin < span[1] and span[0] < end for begin, end in masks)


def _scale_after(text: str, position: int, currency: bool) -> tuple[float, int]:
    """The scale word directly after ``position`` and where it ends; (1, position) if none."""
    match = _SCALE_AFTER.match(text, position)
    if match:
        return SCALES[match.group(1).lower()], match.end()
    if currency:
        match = _ABBREVIATION_AFTER.match(text, position)
        if match:
            return SCALE_ABBREVIATIONS[match.group(1)], match.end()
    return 1.0, position


def _unit_after(text: str, position: int) -> tuple[Unit | None, int]:
    for pattern, unit in _UNIT_AFTER:
        match = pattern.match(text, position)
        if match:
            return unit, match.end()
    return None, position


def _read(text: str, match: re.Match[str]) -> Quantity | None:
    """The quantity at one digit run, or None when it is a label, a date part or a count."""
    begin, end = match.span()
    digits = match.group()
    if begin > 0 and (text[begin - 1].isalnum() or text[begin - 1] in "._"):
        return None  # Q2, H20, FY2026, 10b5: part of an alphanumeric name
    # Before the digits: an opening parenthesis, a currency sign, a minus, in that order inward.
    start = begin
    currency = False
    head = text[max(0, begin - 6) : begin]
    paren_open = False
    if head.endswith("(") or head.endswith("( "):
        paren_open = True
        start = begin - (2 if head.endswith("( ") else 1)
        head = text[max(0, start - 6) : start]
    found = _CURRENCY_BEFORE.search(head)
    if found:
        currency = True
        start -= len(found.group())
        head = text[max(0, start - 6) : start]
        if not paren_open and (head.endswith("(") or head.endswith("( ")):
            paren_open = True
            start -= 2 if head.endswith("( ") else 1
            head = text[max(0, start - 6) : start]
    negative = False
    if head and head[-1] in _MINUS and (len(head) < 2 or not head[-2].isalnum()):
        negative = True
        start -= 1
    # After the digits: a closing parenthesis, a scale word, a unit.
    position = end
    if paren_open:
        closing = re.compile(r"\s?\)").match(text, position)
        if closing:
            negative = True
            position = closing.end()
    scale, position = _scale_after(text, position, currency)
    unit, position = _unit_after(text, position)
    if unit is None:
        if _ORDINAL_AFTER.match(text, end):
            return None
        if position < len(text) and (text[position].isalnum() or text[position] == "_"):
            return None  # 5090Ti, 300GB: alphanumeric
        unit = "usd" if currency else "plain"
    number = float(digits.replace(",", ""))
    decimals = len(digits.split(".", 1)[1]) if "." in digits else 0
    bare = unit == "plain" and scale == 1.0 and decimals == 0 and "," not in digits
    if bare and not negative:
        if int(number) <= MAX_EXEMPT_COUNT or int(number) in YEARS:
            return None
        caps = _CAPS_WORD_BEFORE.search(text[max(0, begin - 24) : begin])
        if caps and caps.group(1) != "USD":
            return None  # RTX 5090: a product name
    value = number * scale
    return Quantity(
        raw=text[start:position].strip(),
        value=-value if negative else value,
        unit=unit,
        decimals=decimals,
        scale=scale,
        signed=negative,
    )


def quantities(text: str) -> list[Quantity]:
    """Every quantity ``text`` writes, in order. See the module notes for what is excluded."""
    masks = _masked(text)
    found: list[Quantity] = []
    for match in _NUMBER.finditer(text):
        if _inside(match.span(), masks):
            continue
        quantity = _read(text, match)
        if quantity is not None:
            found.append(quantity)
    return found


# Matching


@dataclass(frozen=True)
class _Candidate:
    """A number a statement may match: its value, unit, whether it may be rescaled, and a label."""

    value: float
    unit: Unit
    rescalable: bool
    shown: str
    where: str


_COMPATIBLE: dict[Unit, frozenset[Unit]] = {
    "percent": frozenset({"percent", "bps"}),
    "bps": frozenset({"percent", "bps"}),
    "usd": frozenset({"usd", "plain"}),
    "plain": frozenset({"usd", "plain"}),
    "multiple": frozenset({"multiple"}),
}


def _as_percent(value: float, unit: Unit) -> float:
    return value / 100 if unit == "bps" else value


def _matches(quantity: Quantity, candidate: _Candidate) -> bool:
    if candidate.unit not in _COMPATIBLE[quantity.unit]:
        return False
    wanted, tolerance = quantity.value, quantity.tolerance
    source = candidate.value
    if quantity.unit in ("percent", "bps"):
        wanted = _as_percent(wanted, quantity.unit)
        tolerance = _as_percent(tolerance, quantity.unit)
        source = _as_percent(source, candidate.unit)
    factors = TABLE_SCALES if candidate.rescalable else (1.0,)
    slack = tolerance + 1e-9 * max(abs(wanted), 1.0)
    for factor in factors:
        scaled = source * factor
        if abs(scaled - wanted) <= slack:
            return True
        if not quantity.signed and abs(abs(scaled) - abs(wanted)) <= slack:
            return True
    return False


def _excerpt_candidates(excerpts: Sequence[str]) -> list[_Candidate]:
    return [
        _Candidate(
            value=q.value,
            unit=q.unit,
            rescalable=q.scale == 1.0 and q.unit in ("usd", "plain"),
            shown=q.raw,
            where="in a quote",
        )
        for text in excerpts
        for q in quantities(text)
    ]


_METRIC_UNITS: dict[str, Unit] = {"percent": "percent", "USD": "usd", "USD_per_share": "usd"}


def _number_text(value: float) -> str:
    return f"{int(value):,}" if float(value).is_integer() else f"{value:,}"


def _metric_candidates(metrics: Sequence[Metric]) -> list[_Candidate]:
    found: list[_Candidate] = []
    for item in metrics:
        if item.value is not None:
            period = item.period_label[:1].lower() + item.period_label[1:]
            found.append(
                _Candidate(
                    value=item.value,
                    unit=_METRIC_UNITS[item.unit],
                    rescalable=False,
                    shown=f"{item.display} ({item.label}, {period})",
                    where="in a cited figure",
                )
            )
        for ref in item.inputs:
            unit: Unit = "usd" if ref.unit.startswith("USD") else "plain"
            found.append(
                _Candidate(
                    value=ref.value,
                    unit=unit,
                    rescalable=False,
                    shown=f"{_number_text(ref.value)} ({ref.concept}, an input of {item.id})",
                    where="in a cited figure",
                )
            )
    return found


def check_numbers(
    statement: str, excerpts: Sequence[str], metrics: Sequence[Metric]
) -> NumberCheck:
    """Check that every quantity in ``statement`` is in ``excerpts`` or ``metrics``.

    Quotes are tried before cited figures, and the first match is reported.
    """
    candidates = [*_excerpt_candidates(excerpts), *_metric_candidates(metrics)]
    details: list[str] = []
    unmatched: list[str] = []
    wanted = quantities(statement)
    for quantity in wanted:
        hit = next((c for c in candidates if _matches(quantity, c)), None)
        if hit is None:
            unmatched.append(quantity.raw)
            details.append(f"{quantity.raw} was not found in the quotes or the cited figures")
        else:
            details.append(f"{quantity.raw} matched {hit.shown} {hit.where}")
    if not wanted:
        status: Status = "none"
    else:
        status = "failed" if unmatched else "passed"
    return NumberCheck(status=status, details=details, checked=len(wanted), unmatched=unmatched)
