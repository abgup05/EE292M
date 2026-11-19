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
  match each other, because filing tables often omit the dollar sign. A count
  of things ("46 customers", "130 countries": a number with no currency sign
  directly followed by a lower-case word that is not a connective) matches a
  count or a plain number, never a USD amount.
- The tolerance is half a unit in the last digit the *statement* wrote: "56%"
  matches 55.6% and 56.4% but not 55.4%; "$46.7 billion" matches $46,743 million.
  A scale may be a word ("billion") or an abbreviation: "$2.5B", "$45mm", "$46.7bn",
  "$1.2tn", "$46.7 bn" after a dollar amount, "46.7bn" and "1.2tn" without one.
- A plain or USD number in a quote with no scale word (a table cell such as
  "Revenue $ 46,743") also matches at 1e3, 1e6 or 1e9 times its value. A count
  of things does not. The quote gate keeps a quote from making such a bare
  number by stopping before the scale word or unit (:func:`quantity_cut`).
- Direction: an unsigned statement number matches a positive source; it
  matches a *negative* source ("(3)%", "-3%") only when the statement's
  sentence that holds it allows it ("revenue declined 3%" against "(3)%"
  passes; "revenue grew 3%" against it fails). For a percentage the direction
  word that governs the number must be one of decline: the nearest word of
  :data:`DECLINE_WORDS` or :data:`GROWTH_WORDS` before the number in its
  sentence, or with none before it the nearest after it ("revenue grew 3%
  while gross margin fell" fails; "a 3% decline" passes). For an amount a word
  of decline or for an outflow (:data:`OUTFLOW_WORDS`) anywhere in the sentence
  will do, since filings print expenses and payments in parentheses and write
  "purchases rose to". A negative statement number needs a negative source.
  The reverse is not checked: "fell 56%" matches "up 56%".
- Not quantities:

  - a four-digit number from 1900 to 2100 in a date-like context only
    (:func:`is_year`): after "fiscal", "FY", "in", "since", "during", "by",
    "for", "of", "ended", "ending", "due" and similar, after a month or a quarter
    label, after "year-end", "year end", "quarter-end", "end-of-", "versus",
    "vs.", "compared to", "compared with" or "relative to", paired with
    another year ("2024 and 2025", "2023 to 2025"), or directly before a
    financial noun of :data:`YEAR_NOUNS` ("2025 revenue", "2026 net income").
    "2000 employees" and "2025 stores" are checked. After "of", "for", "by" or
    "in", which introduce a count as readily as a year, the number is a count
    when a noun of :data:`COUNTED_NOUNS` directly follows it ("a headcount of
    2000 employees", "in 2000 locations") and a year before anything else
    ("for 2026 remains", "in 2026 we"): a year read as a count would withhold
    a true finding, a count read as a year only goes unchecked, so the list
    is short and a noun not on it ("of 2000 turbines") is still not checked;
  - a reference: a *capitalised* word such as "Note", "Item", "Part",
    "Section", "Rule" or "Form" directly followed by its own number or Roman
    numeral ("Note 5", "Item 1A", "Part II", "Rule 10b5-1"), never a
    lower-case word ("senior notes 3.5%" is checked) and never a number
    followed by a percent sign;
  - form names ("10-K"), quarter and fiscal labels, ordinals, alphanumeric
    product names and numbers inside a date;
  - bare integers from 0 to 12 with no unit. Filings usually spell such counts
    out ("two customers", "three segments"), so a digit the statement writes
    could never be matched to its source and checking it would withhold true
    findings; the cost is that a wrong small count goes unchecked.

What this module reads as a date, a period label or a year is public
(:func:`date_spans`, :func:`period_label_spans`, :func:`year_spans`), so that
:mod:`app.core.periods` reads the years a statement names the same way.

Known gap (not fixable here): table rows are flattened by the parser and lose
their column headers, so a number from the wrong column or period matches.

Pure: no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from ed_v14.core.metric_models import Metric

Unit = Literal["percent", "bps", "usd", "multiple", "plain", "count"]
Status = Literal["none", "passed", "failed"]

SCALES: dict[str, float] = {
    "thousand": 1e3,
    "million": 1e6,
    "billion": 1e9,
    "trillion": 1e12,
}
# Abbreviations recognised only directly after a dollar amount ("$2.5B", "$45mm", "$1.2tn").
# The two-letter ones (lower case only: "TN" is Tennessee) may also follow a dollar amount
# after one space ("$46.7 bn"), and the digits of an amount with no dollar sign directly
# ("46.7bn"); the single letters never after a space ("$5 B shares" is not five billion).
SCALE_ABBREVIATIONS: dict[str, float] = {
    "K": 1e3,
    "M": 1e6,
    "B": 1e9,
    "bn": 1e9,
    "mm": 1e6,
    "mn": 1e6,
    "tn": 1e12,
}
TABLE_SCALES: tuple[float, ...] = (1.0, 1e3, 1e6, 1e9)
MAX_EXEMPT_COUNT = 12
YEARS = range(1900, 2101)
# Financial nouns that make a four-digit number directly before them a year used as an
# adjective ("2025 revenue", "2026 net income"), matched as whole words, case ignored. Kept
# short on purpose: any other noun after a number makes it a count ("2025 employees").
YEAR_NOUNS: tuple[str, ...] = (
    "revenue",
    "revenues",
    "sales",
    "net income",
    "income",
    "earnings",
    "results",
    "margin",
    "margins",
    "guidance",
    "outlook",
    "annual report",
    "10-K",
    "10-Q",
)
# Things a filing counts. After "of", "for", "by" or "in" a four-digit number directly before
# one of these is a count, not a year ("a headcount of 2000 employees"), matched as whole
# words, case ignored. Only these: any other word there may be a verb after a year ("growth
# in 2026 reflects"), and reading that year as a count would withhold a true finding.
COUNTED_NOUNS: tuple[str, ...] = (
    "employees",
    "people",
    "workers",
    "engineers",
    "developers",
    "customers",
    "clients",
    "members",
    "subscribers",
    "users",
    "suppliers",
    "partners",
    "stores",
    "locations",
    "warehouses",
    "restaurants",
    "offices",
    "sites",
    "facilities",
    "countries",
    "markets",
    "shares",
    "units",
    "vehicles",
    "patents",
    "positions",
    "jobs",
)
# Words that let a number written without a sign stand for a negative source figure, matched
# as whole words, case ignored, in the number's own sentence. Two kinds. Words of decline
# say the figure fell or is below zero; they are needed for a percentage, because a
# percentage in parentheses is a fall. Words for an outflow are what a filing uses for
# amounts it prints in parentheses (expenses, purchases, cash paid); they let an amount
# match, never a percentage: "expenses grew 3%" must not match "(3)%".
DECLINE_WORDS: tuple[str, ...] = (
    "decline",
    "declined",
    "declines",
    "declining",
    "decrease",
    "decreased",
    "decreases",
    "decreasing",
    "fell",
    "fall",
    "falls",
    "falling",
    "drop",
    "dropped",
    "drops",
    "down",
    "lower",
    "loss",
    "losses",
    "negative",
    "reduction",
    "reduced",
    "shrank",
    "contraction",
    "contracted",
    "deficit",
)
OUTFLOW_WORDS: tuple[str, ...] = (
    "expense",
    "expenses",
    "outflow",
    "outflows",
    "used in",
    "paid",
    "purchases",
    "repurchases",
    "repurchased",
    "spent",
    "capital expenditure",
    "capital expenditures",
)
NEGATIVE_WORDS: tuple[str, ...] = DECLINE_WORDS + OUTFLOW_WORDS
# Words that say a figure rose. They take a percentage away from a word of decline that is
# about something else: in "revenue grew 3% while gross margin fell" the 3% is growth.
GROWTH_WORDS: tuple[str, ...] = (
    "grew",
    "grow",
    "grows",
    "growing",
    "growth",
    "increase",
    "increased",
    "increases",
    "increasing",
    "rose",
    "rise",
    "rises",
    "rising",
    "up",
    "higher",
    "gain",
    "gained",
    "gains",
    "expanded",
    "expansion",
    "improved",
    "improvement",
    "widened",
)
# A lower-case word directly after a number that does not make it a count of that word.
NOT_COUNTED: frozenset[str] = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "but", "by", "compared", "due", "during", "each",
        "for", "from", "in", "is", "of", "on", "or", "per", "respectively", "than", "that",
        "the", "through", "to", "versus", "vs", "was", "were", "when", "which", "while", "with",
    }
)  # fmt: skip

MONTH_NAMES: tuple[str, ...] = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip
_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
    r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
# Spans whose digits are labels or dates, not quantities, in three groups that
# :mod:`app.core.periods` reads too: dates, references and form names, period labels.
_DATE_MASKS: tuple[re.Pattern[str], ...] = (
    # "March 15, 2026", but not "March 15%": a day of a month is never followed by "%".
    re.compile(rf"\b{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?\b(?!\s?%)"),
    re.compile(rf"\b{_MONTH}\.?,?\s+\d{{4}}\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"),
)
_NAME_MASKS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b\d{1,2}-[A-Z]{1,2}(?:/A)?\b"),  # 10-K, 10-Q, 8-K, 20-F, 10-K/A
    # A reference: a capitalised word directly followed by its own number or Roman numeral.
    # Case matters ("senior notes 3.5%" is not a reference), and the possessive match keeps
    # a number followed by a percent sign ("Notes 3.5% due 2030") from being masked.
    re.compile(
        r"\b(?:Items?|Parts?|Rules?|Sections?|Notes?|Form|Schedules?|Exhibits?|Articles?|"
        r"Regulation|Chapter|Level|Tier|Phase|Page)\s+"
        r"(?:[IVXLC]+\b|\d[\w.\-]*+)(?!\s?%|\s?percent)"
    ),
)
_PERIOD_LABEL_MASKS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bfiscal(?:\s+years?)?\s+'?\d{2,4}\b", re.IGNORECASE),
    re.compile(r"\b(?:FY|CY)\s?'?\d{2,4}\b", re.IGNORECASE),
)
_MASKS: tuple[re.Pattern[str], ...] = (*_DATE_MASKS, *_NAME_MASKS, *_PERIOD_LABEL_MASKS)
# What directly before a four-digit number makes it a year: a period word, a preposition
# of time, a month or a quarter label, or another year joined by "and", "to" or a dash.
_YEAR_BEFORE = re.compile(
    r"(?:\b(?:fiscal(?:\s+years?)?|calendar(?:\s+years?)?|years?|FY|CY|in|since|during|by|"
    r"for|of|ended|ending|from|through|until|between|before|after|due|maturing|expiring|"
    r"quarter|half|(?:year|quarter|period|month)[-–\s]end|end-of-|versus|vs\.?|"
    r"compared\s+(?:to|with)|relative\s+to|"
    rf"Q[1-4]|H[12]|{_MONTH}\.?,?)"
    r"|\b(?:19|20|21)\d\d\s*(?:and|to|through|or)|\b(?:19|20|21)\d\d\s*[-–])\s*'?$",
    re.IGNORECASE,
)
_YEAR_AFTER = re.compile(r"\s*(?:(?:and|to|through|or)\s+|[-–]\s*)(?:19|20|21)\d\d\b")
# A financial noun directly after a four-digit number: "2025 revenue" (see YEAR_NOUNS).
_YEAR_NOUN_AFTER = re.compile(
    r"\s+(?:" + "|".join(re.escape(noun).replace(r"\ ", r"\s+") for noun in YEAR_NOUNS) + r")\b",
    re.IGNORECASE,
)


# The prepositions that introduce a count as readily as a year, directly before the number.
_COUNT_OR_YEAR_BEFORE = re.compile(r"\b(?:of|for|by|in)\s+$", re.IGNORECASE)
_COUNTED_NOUN_AFTER = re.compile(r"\s+(?:" + "|".join(COUNTED_NOUNS) + r")\b", re.IGNORECASE)


def _whole_words(words: tuple[str, ...]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(word).replace(r"\ ", r"\s+") for word in words)
    return re.compile(r"\b(?:" + alternatives + r")\b", re.IGNORECASE)


_NEGATIVE = _whole_words(NEGATIVE_WORDS)
_DECLINE = _whole_words(DECLINE_WORDS)
_DIRECTION = _whole_words(DECLINE_WORDS + GROWTH_WORDS)
_WORD_AFTER = re.compile(r"\s([a-z][a-z'’-]*)\b")
_SENTENCE_BREAK = re.compile(r"[.!?;](?=\s)|\n")
_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+")
_CURRENCY_BEFORE = re.compile(r"(?:US\$|\$|\bUSD)\s?$")
_SCALE_AFTER = re.compile(r"\s?(thousand|million|billion|trillion)\b", re.IGNORECASE)
_ABBREVIATION_AFTER = re.compile(r"(K|M|B|bn|mm|mn|tn)\b|\s(bn|mm|mn|tn)\b")
# Without a dollar sign, only the letters of millions, billions and trillions, glued to the
# digits.
_GLUED_SCALE_AFTER = re.compile(r"(M|B|bn|mm|mn|tn)\b")
_UNIT_AFTER: tuple[tuple[re.Pattern[str], Unit], ...] = (
    (re.compile(r"\s?%"), "percent"),
    (re.compile(r"\s?percentage[\s-]points?\b", re.IGNORECASE), "percent"),
    (re.compile(r"\s?(?:percent|per\s+cent)\b", re.IGNORECASE), "percent"),
    (re.compile(r"\s?(?:basis\s+points?|bps|bp)\b", re.IGNORECASE), "bps"),
    # "28.5x" and "28.5×": the multiplication sign is not a word character, so no \b after it.
    (re.compile(r"(?:x\b|×)"), "multiple"),
    (re.compile(r"\s(?:times)\b", re.IGNORECASE), "multiple"),
    (re.compile(r"\s?(?:dollars|USD)\b"), "usd"),
)
_ORDINAL_AFTER = re.compile(r"(?:st|nd|rd|th)\b")
_CAPS_WORD_BEFORE = re.compile(r"\b([A-Z]{2,}[A-Za-z]*)\s$")
_MINUS = "-−–"
# A decimal point or a thousands separator between two digits is part of the number.
NUMBER_SEPARATORS = ".,"


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
    ``quantities`` are the quantities read, in order, ``found`` says of each
    whether it matched and ``offsets`` where its digits begin in the statement,
    for a caller that treats some of them apart.
    """

    status: Status
    details: list[str]
    checked: int
    unmatched: list[str]
    quantities: tuple[Quantity, ...] = ()
    found: tuple[bool, ...] = ()
    offsets: tuple[int, ...] = ()


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
            return SCALE_ABBREVIATIONS[match.group(1) or match.group(2)], match.end()
        return 1.0, position
    match = _GLUED_SCALE_AFTER.match(text, position)
    if match and _glued_number(text, position):
        return SCALE_ABBREVIATIONS[match.group(1)], match.end()
    return 1.0, position


def _glued_number(text: str, end: int) -> bool:
    """True when the digits ending at ``end`` are long enough to be an amount, not a name.

    "46.7B", "2.5M" and "10M" are amounts; "3M" (a company) is a name. Only B, bn, M and mm
    are read without a dollar sign: "4K" and "10K" are a resolution and a filing.
    """
    digits = re.search(r"[0-9][0-9,.]*$", text[:end])
    return digits is not None and ("." in digits.group() or len(digits.group()) >= 2)


def _unit_after(text: str, position: int) -> tuple[Unit | None, int]:
    for pattern, unit in _UNIT_AFTER:
        match = pattern.match(text, position)
        if match:
            return unit, match.end()
    return None, position


def is_year(text: str, begin: int, end: int) -> bool:
    """True when the four digits at ``text[begin:end]`` are a year in a date-like context.

    The number must be from 1900 to 2100 and either follow a period word, a
    preposition of time, a month or a quarter label (:data:`_YEAR_BEFORE`), be
    joined to another year by "and", "to", "through", "or" or a dash, or be
    directly followed by a financial noun of :data:`YEAR_NOUNS` ("2025
    revenue"). Before any other noun it is a count ("2025 employees"). After
    "of", "for", "by" or "in" it is a count when a noun of :data:`COUNTED_NOUNS`
    directly follows ("a headcount of 2000 employees") and a year otherwise.
    """
    digits = text[begin:end]
    if len(digits) != 4 or not digits.isdigit() or int(digits) not in YEARS:
        return False
    before = text[max(0, begin - 40) : begin]
    if _COUNT_OR_YEAR_BEFORE.search(before) and _COUNTED_NOUN_AFTER.match(text, end):
        return False
    return bool(
        _YEAR_BEFORE.search(before)
        or _YEAR_AFTER.match(text, end)
        or _YEAR_NOUN_AFTER.match(text, end)
    )


@dataclass(frozen=True)
class _Written:
    """How far one number reaches around its digits, and what was read there.

    ``start`` is where its opening parenthesis, currency sign or minus begins and
    ``position`` where its closing parenthesis, scale word and unit end. ``head`` is
    ``start``, except that an opening parenthesis nothing closes is left out: it is
    punctuation ("(5% in the prior year)"), not a sign.
    """

    start: int
    head: int
    position: int
    currency: bool
    negative: bool
    scale: float
    unit: Unit | None


_CLOSING = re.compile(r"\s?\)")


def _written(text: str, begin: int, end: int) -> _Written:
    """Read what is written around the digits at ``text[begin:end]``."""
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
    paren_outermost = paren_open and text[start] == "("
    negative = False
    if head and head[-1] in _MINUS and (len(head) < 2 or not head[-2].isalnum()):
        negative = True
        start -= 1
        paren_outermost = False
    # After the digits: a closing parenthesis, a scale word, a unit.
    position = end
    closed = False
    if paren_open:
        closing = _CLOSING.match(text, position)
        if closing:
            closed = True
            negative = True
            position = closing.end()
    scale, position = _scale_after(text, position, currency)
    unit, position = _unit_after(text, position)
    sign_from = start
    if paren_outermost and not closed:
        sign_from = start + 1
        while sign_from < begin and text[sign_from].isspace():
            sign_from += 1
    return _Written(start, sign_from, position, currency, negative, scale, unit)


def _read(text: str, match: re.Match[str]) -> Quantity | None:
    """The quantity at one digit run, or None when it is a label, a date part or a count."""
    begin, end = match.span()
    digits = match.group()
    if begin > 0 and (text[begin - 1].isalnum() or text[begin - 1] in "._"):
        return None  # Q2, H20, FY2026, 10b5: part of an alphanumeric name
    written = _written(text, begin, end)
    start, position, currency = written.start, written.position, written.currency
    negative, scale, unit = written.negative, written.scale, written.unit
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
        if int(number) <= MAX_EXEMPT_COUNT or is_year(text, begin, end):
            return None
        caps = _CAPS_WORD_BEFORE.search(text[max(0, begin - 24) : begin])
        if caps and caps.group(1) != "USD":
            return None  # RTX 5090: a product name
    if unit == "plain" and not negative:
        counted = _WORD_AFTER.match(text, position)
        if counted and counted.group(1) not in NOT_COUNTED:
            unit = "count"  # 46 customers, 4 million developers: a count of that word
    value = number * scale
    return Quantity(
        raw=text[start:position].strip(),
        value=-value if negative else value,
        unit=unit,
        decimals=decimals,
        scale=scale,
        signed=negative,
    )


def counts_a_listed_thing(text: str, offset: int) -> bool:
    """True when the number whose digits begin at ``offset`` of ``text`` is directly followed
    by a noun of :data:`COUNTED_NOUNS` ("2020 customers"), so that it cannot be a year."""
    digits = _NUMBER.match(text, offset)
    return digits is not None and _COUNTED_NOUN_AFTER.match(text, digits.end()) is not None


def _placed_quantities(text: str) -> list[tuple[Quantity, int]]:
    """Every quantity ``text`` writes with the offset of its digits, in order."""
    masks = _masked(text)
    found: list[tuple[Quantity, int]] = []
    for match in _NUMBER.finditer(text):
        if _inside(match.span(), masks):
            continue
        quantity = _read(text, match)
        if quantity is not None:
            found.append((quantity, match.start()))
    return found


# The furthest a number's sign, currency, scale word or unit lies from a boundary beside it:
# "( US$ " before the digits, ") trillion percentage points" after them.
_QUANTITY_REACH = 40
Cut = Literal["", "head", "tail"]


def quantity_cut(text: str, cut: int) -> Cut:
    """Where a boundary at offset ``cut`` of ``text`` falls inside a number as written here.

    "head": between a number's opening parenthesis, currency sign or minus and its
    digits ("-|5%", "$|46.7", "$ |46,743", "(|1,234)"), so that a text beginning there
    reads the number without them. "tail": between its digits and the closing
    parenthesis, scale word or unit that follows ("$46.7| billion", "56|%", "106| %",
    "(1,234|)", "350| basis points", "30| times"), so that a text ending there reads a
    bare number. "" anywhere else, and after the unit ("56%|"). The sign, scale and
    unit are the ones :func:`quantities` reads, found the same way, so a text cut at a
    boundary this function passes reads each of its numbers as the whole text does.
    What is not read as part of a number is not protected: the noun of a count ("46|
    customers") and "per share".
    """
    if cut <= 0 or cut >= len(text):
        return ""
    low = max(0, cut - _QUANTITY_REACH)
    while low > 0 and (text[low - 1].isdigit() or text[low - 1] in NUMBER_SEPARATORS):
        low -= 1  # never start reading inside a run of digits
    for match in _NUMBER.finditer(text, low, min(len(text), cut + _QUANTITY_REACH)):
        begin, end = match.span()
        if begin > 0 and (text[begin - 1].isalnum() or text[begin - 1] in "._"):
            continue  # part of an alphanumeric name, never a quantity
        written = _written(text, begin, end)
        if written.head < cut <= begin:
            return "head"
        if end <= cut < written.position:
            return "tail"
    return ""


def quantities(text: str) -> list[Quantity]:
    """Every quantity ``text`` writes, in order. See the module notes for what is excluded."""
    return [quantity for quantity, _ in _placed_quantities(text)]


# What this module reads as a date or a period, not a quantity. :mod:`app.core.periods` takes
# the years a statement names from these three functions, so the two checks cannot disagree
# about what is a year and what is a quantity.


def date_spans(text: str) -> list[tuple[int, int]]:
    """The ``(begin, end)`` spans of ``text`` read as dates, whose digits are never quantities.

    "January 25, 2026", "July 26", "July 2026", "2026-01-25" and "1/25/2026", in
    the order of the patterns that found them; spans may overlap.
    """
    return [match.span() for pattern in _DATE_MASKS for match in pattern.finditer(text)]


def period_label_spans(text: str) -> list[tuple[int, int]]:
    """The spans of ``text`` read as fiscal or calendar period labels, never quantities.

    "fiscal 2026", "fiscal year 2026", "fiscal years 2025", "fiscal '26",
    "FY2026", "FY 26", "CY2025" (case ignored), in the order found.
    """
    return [match.span() for pattern in _PERIOD_LABEL_MASKS for match in pattern.finditer(text)]


def year_spans(text: str) -> list[tuple[int, int]]:
    """The four-digit runs of ``text`` that are not quantities because they are years.

    Each is outside every date, reference and label span, is a year in a
    date-like context (:func:`is_year`), and is skipped by the reading of
    quantities: "in 2025", "Q2 2026", "2024 and 2025". "2000 employees",
    "$2025" and "2025%" are quantities, not years.
    """
    masks = _masked(text)
    return [
        match.span()
        for match in _NUMBER.finditer(text)
        if not _inside(match.span(), masks)
        and is_year(text, *match.span())
        and _read(text, match) is None
    ]


def _sentence_at(text: str, position: int) -> tuple[str, int]:
    """The sentence of ``text`` that holds ``position``, and where the sentence starts.

    A sentence ends at ".", "!", "?" or ";" followed by white space, or at a line
    break; a decimal point ("46.7") is never followed by white space, so it does
    not end one.
    """
    start = 0
    for found in _SENTENCE_BREAK.finditer(text):
        if found.end() > position:
            return text[start : found.end()], start
        start = found.end()
    return text[start:], start


def says_negative(sentence: str) -> bool:
    """True when ``sentence`` has a word of :data:`NEGATIVE_WORDS`."""
    return _NEGATIVE.search(sentence) is not None


def decline_governs(sentence: str, offset: int) -> bool:
    """True when the direction word governing the number at ``offset`` is one of decline.

    The governing word is the nearest word of :data:`DECLINE_WORDS` or
    :data:`GROWTH_WORDS` that ends before ``offset``; when the sentence has none
    before the number, the nearest that starts after it. No direction word at
    all gives False.
    """
    before: re.Match[str] | None = None
    after: re.Match[str] | None = None
    for found in _DIRECTION.finditer(sentence):
        if found.end() <= offset:
            before = found
        elif found.start() > offset and after is None:
            after = found
    governing = before or after
    return governing is not None and _DECLINE.fullmatch(governing.group()) is not None


# Matching


@dataclass(frozen=True)
class _Candidate:
    """A number a statement may match: its value, unit, whether it may be rescaled, and a label."""

    value: float
    unit: Unit
    rescalable: bool
    shown: str
    where: str
    # A change the backend computed and printed with its sign ("+65.5%"): a statement whose
    # direction word is one of decline may not match it.
    increase: bool = False


_COMPATIBLE: dict[Unit, frozenset[Unit]] = {
    "percent": frozenset({"percent", "bps"}),
    "bps": frozenset({"percent", "bps"}),
    "usd": frozenset({"usd", "plain"}),
    "plain": frozenset({"usd", "plain", "count"}),
    "count": frozenset({"count", "plain"}),
    "multiple": frozenset({"multiple"}),
}


def _as_percent(value: float, unit: Unit) -> float:
    return value / 100 if unit == "bps" else value


def _matches(quantity: Quantity, candidate: _Candidate, negative_allowed: bool) -> bool:
    """True when ``candidate`` gives ``quantity`` within tolerance and in a compatible unit.

    An unsigned ``quantity`` may match a negative candidate only when
    ``negative_allowed`` (its sentence has a word that allows it: see :func:`check_numbers`).
    """
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
        unsigned_against_negative = not quantity.signed and negative_allowed
        if unsigned_against_negative and abs(abs(scaled) - abs(wanted)) <= slack:
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
                    increase=item.unit == "percent" and item.display.startswith("+"),
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

    Quotes are tried before cited figures, and the first match is reported. An
    unsigned quantity matches a negative source only when its own sentence of
    ``statement`` allows it: for a percentage the direction word that governs it
    must be one of decline (:func:`decline_governs`), for an amount the sentence
    must have a word of decline or of an outflow (:data:`NEGATIVE_WORDS`). The
    reverse is checked only against a change the backend computed and printed with
    its sign: a percentage governed by a word of decline does not match a cited
    "+65.5%". Against a quote it is not: "fell 56%" matches a quote that says "up
    56%", because a filing writes most declines as positive numbers with a word,
    and a sign cannot tell the two apart.
    """
    candidates = [*_excerpt_candidates(excerpts), *_metric_candidates(metrics)]
    details: list[str] = []
    unmatched: list[str] = []
    placed = _placed_quantities(statement)
    wanted = [quantity for quantity, _ in placed]
    found: list[bool] = []
    for quantity, position in placed:
        sentence, begins = _sentence_at(statement, position)
        if quantity.unit in ("percent", "bps"):
            negative_allowed = decline_governs(sentence, position - begins)
        else:
            negative_allowed = says_negative(sentence)
        # A decline may not match a computed increase (a quote's sign cannot be known).
        usable = [c for c in candidates if not (negative_allowed and c.increase)]
        hit = next((c for c in usable if _matches(quantity, c, negative_allowed)), None)
        found.append(hit is not None)
        if hit is None:
            unmatched.append(quantity.raw)
            details.append(f"{quantity.raw} was not found in the quotes or the cited figures")
        else:
            details.append(f"{quantity.raw} matched {hit.shown} {hit.where}")
    if not wanted:
        status: Status = "none"
    else:
        status = "failed" if unmatched else "passed"
    return NumberCheck(
        status=status,
        details=details,
        checked=len(wanted),
        unmatched=unmatched,
        quantities=tuple(wanted),
        found=tuple(found),
        offsets=tuple(position for _, position in placed),
    )
