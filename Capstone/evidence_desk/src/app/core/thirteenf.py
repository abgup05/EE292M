"""Quarter-end share prices read out of Form 13F information tables.

Pure. An institutional manager's Form 13F-HR lists, for the last day of a calendar
quarter, each position's market value and number of shares; value ÷ shares is the price
the manager valued the position at, which for a listed US share is that day's close.
The filing is a public SEC record with a filing date, so the price can be placed in
time exactly: it was public, from this source, on the day the 13F was filed.

The rules, each the answer to a quirk of the form:

- **Rows read** (:func:`parse_information_table`): positions in shares (``SH``), not
  principal amounts (``PRN``), and not options (a row with ``putCall``); value and shares
  positive. Any other row is counted, not read.
- **The unit of value.** SEC changed the form: a 13F filed on or after
  :data:`DOLLARS_FROM` should report value in dollars, one filed before, in thousands.
  Filers do not all follow it (one of the three managers read still reported thousands in
  2025), so the unit is read from the table itself (:func:`value_scale`): when the median
  of value ÷ shares over its positions is under :data:`THOUSANDS_BELOW` dollars, the
  values are thousands. No manager's median holding trades under a dollar; a table of
  thousands has a median a thousand times smaller than its true one. A price from a table
  of thousands is good to a few parts in ten thousand at best.
- **Which issuer** (:func:`match_issuer`). A 13F names an issuer in the manager's own
  abbreviated words and by CUSIP; SEC publishes no table from a filer to its CUSIP. The
  company's EDGAR name and each row's issuer name are reduced to a key
  (:func:`issuer_key`: upper case, punctuation and legal forms dropped, the form's usual
  abbreviations spelled out) and must be equal. Rows of more than one CUSIP under one
  key are several share classes: no price is taken, and the reason lists them.
- **The price** (:func:`implied_price`) is the sum of value over the sum of shares of
  the matched rows (a manager may split one position over several rows).
- **Two managers.** :func:`agree` compares the prices two managers' filings imply for
  one CUSIP and quarter; they are independent filers, so agreement within
  :data:`AGREE_TOLERANCE` checks both the arithmetic and the unit.
"""

from __future__ import annotations

import html
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from statistics import median

DOLLARS_FROM = date(2023, 1, 3)
THOUSANDS_BELOW = 1.0
AGREE_TOLERANCE = 0.005
MAX_ROWS = 60_000

_ENTRY = re.compile(r"<(?:\w+:)?infoTable>(.*?)</(?:\w+:)?infoTable>", re.DOTALL)
_CUSIP = re.compile(r"^[0-9A-Z]{9}$")


def _field(name: str) -> re.Pattern[str]:
    return re.compile(rf"<(?:\w+:)?{name}>\s*([^<]*?)\s*</(?:\w+:)?{name}>")


_NAME, _TITLE, _CUSIP_FIELD = _field("nameOfIssuer"), _field("titleOfClass"), _field("cusip")
_VALUE, _AMOUNT, _TYPE = _field("value"), _field("sshPrnamt"), _field("sshPrnamtType")
_PUT_CALL = _field("putCall")

# How a 13F abbreviates a name, spelled out; then the words that say only a legal form.
_SPELLED: dict[str, str] = {
    "CORPORATION": "CORP",
    "INCORPORATED": "INC",
    "COMPANY": "CO",
    "LIMITED": "LTD",
    "WHSL": "WHOLESALE",
    "HLDGS": "HOLDINGS",
    "HLDG": "HOLDING",
    "INTL": "INTERNATIONAL",
    "FINL": "FINANCIAL",
    "GRP": "GROUP",
    "SVCS": "SERVICES",
    "SYS": "SYSTEMS",
    "TECHNOLOGIES": "TECH",
    "TECHNOLOGY": "TECH",
    "MTRS": "MOTORS",
    "MFG": "MANUFACTURING",
    "LABS": "LABORATORIES",
    "PPTYS": "PROPERTIES",
    "RES": "RESOURCES",
    "COMMUNICATIONS": "COMM",
    "COMMUNICATION": "COMM",
    "COMMUNS": "COMM",
    "PHARMACEUTICALS": "PHARMA",
    "PHARMACEUTICAL": "PHARMA",
    "PHARMACEUTCLS": "PHARMA",
    "BANCORPORATION": "BANCORP",
    "AND": "",
}
_LEGAL = frozenset({"CORP", "INC", "CO", "LTD", "PLC", "NEW", "DEL", "DE", "THE", "NV", "SA", "LP"})


class ThirteenFError(ValueError):
    """An information table is not the shape this module reads; the message says why."""


@dataclass(frozen=True)
class Holding:
    """One position of a 13F information table that is held in shares."""

    issuer: str
    title: str
    cusip: str
    value: float
    shares: float


@dataclass(frozen=True)
class Table:
    """A parsed information table: the share positions, and the rows not read by reason."""

    holdings: tuple[Holding, ...]
    skipped: dict[str, int]


def parse_information_table(text: str) -> Table:
    """Every share position of a 13F information table (XML as filed).

    Raises :class:`ThirteenFError` when the text holds no ``infoTable`` entry or more
    than :data:`MAX_ROWS`.
    """
    entries = _ENTRY.findall(text)
    if not entries:
        raise ThirteenFError("the information table has no infoTable entry")
    if len(entries) > MAX_ROWS:
        raise ThirteenFError(f"the information table has more than {MAX_ROWS:,} entries")
    holdings: list[Holding] = []
    skipped: dict[str, int] = {}

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for entry in entries:
        if _PUT_CALL.search(entry):
            skip("an option (put or call)")
            continue
        kind = _TYPE.search(entry)
        if kind is None or kind.group(1).upper() != "SH":
            skip("not held in shares")
            continue
        name, cusip = _NAME.search(entry), _CUSIP_FIELD.search(entry)
        value, amount = _VALUE.search(entry), _AMOUNT.search(entry)
        title = _TITLE.search(entry)
        if not (name and cusip and value and amount):
            skip("a field is missing")
            continue
        code = cusip.group(1).upper()
        try:
            worth, shares = float(value.group(1)), float(amount.group(1))
        except ValueError:
            skip("a value or share count is not a number")
            continue
        if not _CUSIP.fullmatch(code) or worth <= 0 or shares <= 0:
            skip("no CUSIP, or a value or share count that is not positive")
            continue
        holdings.append(
            Holding(
                issuer=html.unescape(name.group(1)).strip(),
                title=html.unescape(title.group(1)).strip() if title else "",
                cusip=code,
                value=worth,
                shares=shares,
            )
        )
    return Table(tuple(holdings), skipped)


def issuer_key(name: str) -> tuple[str, ...]:
    """A company name reduced to the words that identify it.

    ``COSTCO WHOLESALE CORP /NEW`` and ``COSTCO WHSL CORP NEW`` both give
    ``("COSTCO", "WHOLESALE")``; ``Apple Inc.`` gives ``("APPLE",)``. A state or
    ``/NEW`` after a slash is dropped with the slash.
    """
    text = re.sub(r"[/\\].*$", " ", name.upper())
    text = re.sub(r"[.']", "", text)
    words = [_SPELLED.get(word, word) for word in re.sub(r"[^A-Z0-9]+", " ", text).split()]
    words = [word for word in words if word]
    while len(words) > 1 and words[-1] in _LEGAL:
        words.pop()
    if words and words[0] == "THE":
        words = words[1:]
    return tuple(words)


@dataclass(frozen=True)
class Matched:
    """The rows of one issuer in one table, all of one CUSIP."""

    issuer: str
    title: str
    cusip: str
    rows: tuple[Holding, ...]


def match_issuer(holdings: Sequence[Holding], company_name: str) -> Matched | str:
    """The table's rows for the company named, or why none can be taken."""
    wanted = issuer_key(company_name)
    if not wanted:
        return "The company's name has no word to match."
    rows = [row for row in holdings if issuer_key(row.issuer) == wanted]
    if not rows:
        return f"No position is named like {company_name!r}."
    cusips = sorted({row.cusip for row in rows})
    if len(cusips) > 1:
        listed = "; ".join(
            f"{cusip} ({next(r.title for r in rows if r.cusip == cusip) or 'no class named'})"
            for cusip in cusips
        )
        return (
            f"Positions named like {company_name!r} are of {len(cusips)} securities ({listed}): "
            "several share classes, and no one price is the company's."
        )
    return Matched(rows[0].issuer, rows[0].title, cusips[0], tuple(rows))


def rows_of(holdings: Sequence[Holding], cusip: str) -> tuple[Holding, ...]:
    """The table's rows of one CUSIP."""
    return tuple(row for row in holdings if row.cusip == cusip)


def value_scale(holdings: Sequence[Holding]) -> float:
    """What one unit of a table's ``value`` is in dollars: 1, or 1,000 when it reports thousands.

    Read from the table: the median of value ÷ shares over its positions is under
    :data:`THOUSANDS_BELOW` only when the values are thousands of dollars.
    """
    if not holdings:
        raise ValueError("no holdings")
    typical = median(row.value / row.shares for row in holdings)
    return 1000.0 if typical < THOUSANDS_BELOW else 1.0


def unit_note(scale: float, filed: date) -> str:
    """What to say when a table's unit is not the one the form asks for on its filing date."""
    if scale == 1000.0 and filed >= DOLLARS_FROM:
        return (
            "This filing reports value in thousands of dollars though the form has asked for "
            "dollars since 2023; it is read as thousands."
        )
    if scale == 1.0 and filed < DOLLARS_FROM:
        return (
            "This filing reports value in dollars though the form asked for thousands before "
            "2023; it is read as dollars."
        )
    return ""


def implied_price(rows: Sequence[Holding], scale: float) -> float:
    """Sum of value ÷ sum of shares of ``rows``, in dollars a share; ``scale`` from the table."""
    if not rows:
        raise ValueError("no rows")
    return sum(row.value for row in rows) * scale / sum(row.shares for row in rows)


def agree(first: float, second: float) -> bool:
    """True when two prices differ by at most :data:`AGREE_TOLERANCE` of the first."""
    return abs(first - second) <= AGREE_TOLERANCE * abs(first)
