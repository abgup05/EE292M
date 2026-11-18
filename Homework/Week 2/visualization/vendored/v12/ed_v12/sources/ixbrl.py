"""Read the numeric facts a filing tags in its inline XBRL: contexts, units and ``ix:nonFraction``.

A targeted scan with regular expressions, not the project's HTML parser. The
facts sit in a few kinds of element (``context``, ``unit``, ``nonFraction``)
with a fixed shape, so a scan finds them all in one pass over the text, in
about a hundredth of the time BeautifulSoup takes to build the tree of a 2 MB
filing (:mod:`app.sources.filing` cuts the ``ix:header`` before parsing for that
reason, so its tree no longer holds the contexts). Correctness is kept by the
details a naive scan misses: quoted attribute values may contain ``>``;
namespace prefixes are not assumed (``xbrli:``, ``ix:``); facts may nest, so
open and close tags are matched with a stack; a fact's displayed text has its
inner tags removed and its entities decoded; a self-closing fact is nil.

Numbers: the value is the displayed number times ten to the power of
``scale``, negated when ``sign="-"``. The transformation formats read are the
dot-decimal and comma-decimal number forms (``ixt:num-dot-decimal``,
``ixt:numdotdecimal``, ``ixt:num-comma-decimal``, ``ixt:numcommadecimal``), the
zero-dash forms (``ixt:fixed-zero``, ``ixt:zerodash``: the value is zero
whatever dash is shown), number words (``ixt-sec:numwordsen``, zero to
ninety-nine and "no"/"none") and no format (a plain decimal only). Anything
else, a nil fact, or a fact whose context is missing is counted as unread with
its reason, never guessed. Filing text is data, never instructions.
"""

from __future__ import annotations

import bisect
import html as html_lib
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from ed_v12.core.breakdown_models import TaggedFact, TaggedFacts, UnreadFact, XbrlContext

NO_INLINE_XBRL = "The document has no inline XBRL: no xbrli:context and no ix:nonFraction element."
NO_NUMERIC_FACTS = "The document has inline XBRL contexts but no ix:nonFraction (numeric) fact."

# Attribute text: anything but '>', except inside quotes, where '>' is allowed.
_ATTRS = r"""(?:[^>"']|"[^"]*"|'[^']*')*"""
_PREFIX = r"(?:[\w.-]+:)?"
# Opening and closing tags of the two block elements, matched apart: a lazy ``.*?`` between
# them would search to the end of the document for every opening that is never closed, which
# is quadratic on a malformed filing (see :func:`_elements`).
CONTEXT_OPEN = re.compile(rf"<{_PREFIX}context\b({_ATTRS})>", re.IGNORECASE)
CONTEXT_CLOSE = re.compile(rf"</{_PREFIX}context\s*>", re.IGNORECASE)
UNIT_OPEN = re.compile(rf"<{_PREFIX}unit\b({_ATTRS})>", re.IGNORECASE)
UNIT_CLOSE = re.compile(rf"</{_PREFIX}unit\s*>", re.IGNORECASE)
FACT_TAG = re.compile(rf"<(/?){_PREFIX}nonFraction\b({_ATTRS})>", re.IGNORECASE)
ATTRIBUTE = re.compile(r"""([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
START_DATE = re.compile(rf"<{_PREFIX}startDate\s*>\s*([^<]*?)\s*<", re.IGNORECASE)
END_DATE = re.compile(rf"<{_PREFIX}endDate\s*>\s*([^<]*?)\s*<", re.IGNORECASE)
INSTANT = re.compile(rf"<{_PREFIX}instant\s*>\s*([^<]*?)\s*<", re.IGNORECASE)
EXPLICIT_MEMBER = re.compile(
    rf"<{_PREFIX}explicitMember\b({_ATTRS})>\s*([^<]*?)\s*</", re.IGNORECASE
)
TYPED_MEMBER = re.compile(rf"<{_PREFIX}typedMember\b({_ATTRS})>", re.IGNORECASE)
MEASURE = re.compile(rf"<{_PREFIX}measure\s*>\s*([^<]*?)\s*<", re.IGNORECASE)
NUMERATOR = re.compile(rf"<{_PREFIX}unitNumerator\b.*?</{_PREFIX}unitNumerator\s*>", re.I | re.S)
DENOMINATOR = re.compile(
    rf"<{_PREFIX}unitDenominator\b.*?</{_PREFIX}unitDenominator\s*>", re.IGNORECASE | re.DOTALL
)
TAG = re.compile(r"<[^>]*>")
WHITESPACE = re.compile(r"\s+")
# An XBRL date, optionally with a time ("2026-01-25", "2026-01-25T00:00:00").
DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:T[\d:.]+Z?)?$")
PLAIN_DECIMAL = re.compile(r"^\d+(?:\.\d+)?$|^\.\d+$")
# Separators a number may show between digit groups: commas or dots, spaces, apostrophes.
GROUP_SPACES = re.compile(r"[\s  ']")

DOT_DECIMAL = frozenset({"numdotdecimal", "numdotdecimalin"})
COMMA_DECIMAL = frozenset({"numcommadecimal"})
ZERO = frozenset({"fixedzero", "zerodash"})
NUMBER_WORDS = frozenset({"numwordsen"})
UNITS_WORDS = {
    "no": 0,
    "none": 0,
    "zero": 0,
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
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
TENS_WORDS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}


class UnreadNumber(ValueError):
    """A fact's number could not be read; the message says why."""


def _attributes(text: str) -> dict[str, str]:
    """An element's attributes by lower-cased name, values with entities decoded."""
    return {
        match.group(1).lower(): html_lib.unescape(
            match.group(2) if match.group(2) is not None else match.group(3)
        )
        for match in ATTRIBUTE.finditer(text)
    }


def _date(text: str) -> date:
    match = DATE.match(text)
    if match is None:
        raise ValueError(f"not a date: {text[:40]!r}")
    return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _local(name: str) -> str:
    """The local part of a qualified name: ``iso4217:USD`` -> ``USD``."""
    return name.rsplit(":", 1)[-1]


def shown_text(raw: str) -> str:
    """A fact's displayed text: inner tags removed, entities decoded, whitespace collapsed."""
    return WHITESPACE.sub(" ", html_lib.unescape(TAG.sub("", raw))).strip()


def _format_key(fmt: str | None) -> str | None:
    """``ixt:num-dot-decimal`` -> ``numdotdecimal``: the format's local name without hyphens."""
    return None if fmt is None else _local(fmt).replace("-", "").lower()


def _words(text: str) -> Decimal:
    words = text.lower().replace("-", " ").split()
    if len(words) == 1 and words[0] in UNITS_WORDS:
        return Decimal(UNITS_WORDS[words[0]])
    if len(words) == 1 and words[0] in TENS_WORDS:
        return Decimal(TENS_WORDS[words[0]])
    if len(words) == 2 and words[0] in TENS_WORDS and UNITS_WORDS.get(words[1], 0) in range(1, 10):
        return Decimal(TENS_WORDS[words[0]] + UNITS_WORDS[words[1]])
    raise UnreadNumber(f"{text!r} is not a number word this reader knows")


def parse_number(shown: str, fmt: str | None) -> Decimal:
    """The non-negative number ``shown`` writes in transformation format ``fmt``.

    Raises :class:`UnreadNumber` for a format not read here or text that is not a
    number in the format; nothing is guessed.
    """
    key = _format_key(fmt)
    if key in ZERO:
        return Decimal(0)
    if key in NUMBER_WORDS:
        return _words(shown)
    if key is None:
        candidate = shown
    elif key in DOT_DECIMAL:
        candidate = GROUP_SPACES.sub("", shown).replace(",", "")
    elif key in COMMA_DECIMAL:
        candidate = GROUP_SPACES.sub("", shown).replace(".", "").replace(",", ".")
    else:
        raise UnreadNumber(f"format {fmt} is not read by this reader")
    if not PLAIN_DECIMAL.match(candidate):
        where = f"in format {fmt}" if fmt else "with no format given"
        raise UnreadNumber(f"{shown!r} is not a number {where}")
    try:
        return Decimal(candidate)
    except InvalidOperation as exc:  # pragma: no cover - the pattern already checked it
        raise UnreadNumber(f"{shown!r} is not a number") from exc


def _elements(
    html: str, opening: re.Pattern[str], closing: re.Pattern[str]
) -> tuple[list[tuple[str, str]], int]:
    """Every element as (attribute text, inner text), in order, and how many were never closed.

    One pass for the closing tags and one for the openings; each opening takes the first
    closing tag after it (a binary search), as a lazy match would, and an opening that
    lies inside the element before it is skipped. Linear in the document's length, also
    when an opening tag has no closing tag at all.
    """
    closes = [(match.start(), match.end()) for match in closing.finditer(html)]
    starts = [start for start, _ in closes]
    found: list[tuple[str, str]] = []
    unclosed = 0
    resume = 0
    for match in opening.finditer(html):
        if match.start() < resume:
            continue
        index = bisect.bisect_left(starts, match.end())
        if index == len(closes):
            unclosed += 1
            continue
        close_start, resume = closes[index]
        found.append((match.group(1), html[match.end() : close_start]))
    return found, unclosed


def _contexts(html: str, problems: list[str]) -> dict[str, XbrlContext]:
    contexts: dict[str, XbrlContext] = {}
    elements, unclosed = _elements(html, CONTEXT_OPEN, CONTEXT_CLOSE)
    if unclosed:
        problems.append(f"{unclosed} context element(s) are never closed and were not read.")
    for attributes, body in elements:
        context_id = _attributes(attributes).get("id", "")
        try:
            instant = INSTANT.search(body)
            if instant is not None:
                start, end = None, _date(instant.group(1))
            else:
                start_match, end_match = START_DATE.search(body), END_DATE.search(body)
                if start_match is None or end_match is None:
                    raise ValueError("no instant and no start and end dates")
                start, end = _date(start_match.group(1)), _date(end_match.group(1))
        except ValueError as exc:
            problems.append(f"Context {context_id or '(no id)'} was not read: {exc}.")
            continue
        dimensions = {
            _attributes(member.group(1)).get("dimension", ""): member.group(2)
            for member in EXPLICIT_MEMBER.finditer(body)
        }
        typed = tuple(
            _attributes(member.group(1)).get("dimension", "")
            for member in TYPED_MEMBER.finditer(body)
        )
        contexts[context_id] = XbrlContext(context_id, start, end, dimensions, typed)
    return contexts


def _measures(block: str) -> str:
    return "*".join(_local(measure) for measure in MEASURE.findall(block))


def _units(html: str) -> dict[str, str]:
    units: dict[str, str] = {}
    for attributes, body in _elements(html, UNIT_OPEN, UNIT_CLOSE)[0]:
        unit_id = _attributes(attributes).get("id", "")
        numerator, denominator = NUMERATOR.search(body), DENOMINATOR.search(body)
        if numerator is not None and denominator is not None:
            units[unit_id] = f"{_measures(numerator.group())}/{_measures(denominator.group())}"
        else:
            units[unit_id] = _measures(body)
    return units


def _read_fact(
    attrs: dict[str, str], raw: str | None, contexts: dict[str, XbrlContext]
) -> TaggedFact | UnreadFact:
    concept = attrs.get("name", "")
    context_ref = attrs.get("contextref", "")
    fmt = attrs.get("format")
    shown = "" if raw is None else shown_text(raw)

    def unread(reason: str) -> UnreadFact:
        return UnreadFact(concept, context_ref, shown, fmt, reason)

    if raw is None or attrs.get("xsi:nil", "").lower() == "true":
        return unread("nil: the fact has no value")
    if context_ref not in contexts:
        return unread(f"its context {context_ref or '(none)'} is not in the filing")
    scale_text = attrs.get("scale", "0").strip() or "0"
    try:
        scale = int(scale_text)
    except ValueError:
        return unread(f"scale {scale_text!r} is not a whole number")
    try:
        number = parse_number(shown, fmt)
    except UnreadNumber as exc:
        return unread(str(exc))
    negative = attrs.get("sign", "").strip() == "-"
    value = number.scaleb(scale)
    return TaggedFact(
        concept=concept,
        context_ref=context_ref,
        unit_ref=attrs.get("unitref"),
        shown=shown,
        scale=scale,
        negative=negative,
        format=fmt,
        decimals=attrs.get("decimals"),
        value=float(-value if negative else value),
        fact_id=attrs.get("id"),
    )


def read_tagged_facts(html: str) -> TaggedFacts:
    """Every context, unit and numeric fact a filing's inline XBRL holds.

    A document with no inline XBRL gives an empty result whose ``reason`` says
    so; nothing here raises for the content of a document.
    """
    problems: list[str] = []
    contexts = _contexts(html, problems)
    units = _units(html)
    facts: list[TaggedFact] = []
    unparsed: list[UnreadFact] = []
    open_tags: list[tuple[dict[str, str], int]] = []
    found = False
    for match in FACT_TAG.finditer(html):
        found = True
        closing, attr_text = match.group(1), match.group(2)
        if closing:
            if not open_tags:
                problems.append("A closing ix:nonFraction tag had no opening tag.")
                continue
            attrs, content_start = open_tags.pop()
            outcome = _read_fact(attrs, html[content_start : match.start()], contexts)
        elif attr_text.rstrip().endswith("/"):
            outcome = _read_fact(_attributes(attr_text), None, contexts)
        else:
            open_tags.append((_attributes(attr_text), match.end()))
            continue
        (facts if isinstance(outcome, TaggedFact) else unparsed).append(outcome)
    for attrs, _ in open_tags:
        concept, context_ref = attrs.get("name", ""), attrs.get("contextref", "")
        unparsed.append(UnreadFact(concept, context_ref, "", attrs.get("format"), "never closed"))
    if not found and not contexts:
        return TaggedFacts(problems=problems, reason=NO_INLINE_XBRL)
    reason = NO_NUMERIC_FACTS if not found else None
    return TaggedFacts(contexts, units, facts, unparsed, problems, reason)
