"""Daily closing prices as data: read from a CSV, checked, and cut at a date.

Pure. :func:`parse_closes` reads the two CSV shapes the market view meets: a table with
a ``Date`` and a ``Close`` column (as Stooq, Yahoo and most brokers export it; an
``Adj Close`` column is not read) and FRED's ``observation_date,<SERIES>`` with ``.`` or
nothing for a day without a value. Dates must be ``YYYY-MM-DD`` and each appear once,
closes positive and finite; anything else is a :class:`PriceSeriesError` naming the line.
:func:`closes_until` drops every close after a date: a price is never read from after
the as-of date.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

MAX_ROWS = 40_000
DATE_COLUMNS = ("date", "observation_date")


class PriceSeriesError(ValueError):
    """A price file is not the shape this module reads; the message names the problem."""


@dataclass(frozen=True)
class Close:
    """One trading day's closing price."""

    day: date
    value: float


@dataclass(frozen=True)
class PriceSeries:
    """A symbol's closes, oldest first, and where they came from (in words, with a URL)."""

    symbol: str
    closes: tuple[Close, ...]
    source: str
    url: str = ""
    retrieved: str = ""


def _columns(header: list[str]) -> tuple[int, int]:
    names = [name.strip().lower() for name in header]
    day = next((i for i, name in enumerate(names) if name in DATE_COLUMNS), None)
    if day is None:
        raise PriceSeriesError("the price file has no Date column")
    if "close" in names:
        return day, names.index("close")
    if names[day] == "observation_date" and len(names) == 2:
        return day, 1 - day
    raise PriceSeriesError("the price file has no Close column")


def parse_closes(text: str) -> list[Close]:
    """Every close in a CSV text, oldest first. Raises :class:`PriceSeriesError`."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise PriceSeriesError("the price file is empty")
    if len(rows) > MAX_ROWS:
        raise PriceSeriesError(f"the price file has more than {MAX_ROWS:,} rows")
    day_at, close_at = _columns(rows[0])
    found: dict[date, float] = {}
    for number, row in enumerate(rows[1:], start=2):
        if not row or not any(cell.strip() for cell in row):
            continue
        if len(row) <= max(day_at, close_at):
            raise PriceSeriesError(f"line {number} has too few columns")
        cell = row[close_at].strip()
        if cell in ("", "."):
            continue
        try:
            day = date.fromisoformat(row[day_at].strip())
        except ValueError as exc:
            raise PriceSeriesError(f"line {number} has no YYYY-MM-DD date") from exc
        try:
            value = float(cell)
        except ValueError as exc:
            raise PriceSeriesError(f"line {number} has a close that is not a number") from exc
        if not math.isfinite(value) or value <= 0:
            raise PriceSeriesError(f"line {number} has a close that is not positive")
        if day in found:
            raise PriceSeriesError(f"line {number} repeats the day {day.isoformat()}")
        found[day] = value
    if not found:
        raise PriceSeriesError("the price file has no close")
    return [Close(day, found[day]) for day in sorted(found)]


def closes_until(closes: Sequence[Close], as_of: date) -> list[Close]:
    """The closes on or before ``as_of``, oldest first."""
    return [close for close in closes if close.day <= as_of]


def close_on_or_before(closes: Sequence[Close], day: date) -> Close | None:
    """The last close on or before ``day``, or None."""
    found = None
    for close in closes:
        if close.day > day:
            break
        found = close
    return found
