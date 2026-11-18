"""The market's reading of an event: the stock's move after a filing, against an index and its normal move.

Pure. :func:`event_reaction` takes the stock's and an index's daily closes, the day an
8-K was filed, a number of trading days and the as-of date, and returns two windows:

- **N days**: from the last close before the filing day (the price before anyone could
  read the filing; an 8-K filed after the close moves the next day's price) to the Nth
  stock close after it;
- **to the latest close**: from the same close to the last one on or before the as-of
  date.

For each: the stock's return, the index's over the same dates (the index's last close
on or before each date), the excess return (the difference, not adjusted for beta),
and the stock's normal move over as many days: the sample standard deviation of its
daily excess returns over the :data:`ESTIMATION_DAYS` trading days that end at the
close before the filing, times the square root of the days (independent days assumed).
With fewer than :data:`MIN_ESTIMATION_DAYS` returns there is no normal move, and the
line says so. Nothing after the as-of date is read.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date

from app.core.analysis_models import ReactionWindow
from app.core.metrics import percent_text
from app.core.price_series import Close, close_on_or_before, closes_until

ESTIMATION_DAYS = 250
MIN_ESTIMATION_DAYS = 60
MAX_INDEX_GAP_DAYS = 5


def _index_at(index: Sequence[Close] | None, day: date) -> float | None:
    if not index:
        return None
    found = close_on_or_before(index, day)
    if found is None or (day - found.day).days > MAX_INDEX_GAP_DAYS:
        return None
    return found.value


def _excess_returns(
    stock: Sequence[Close], index: Sequence[Close] | None, upto: int
) -> list[float]:
    """Daily excess returns of the closes up to position ``upto``, the last ESTIMATION_DAYS."""
    first = max(1, upto - ESTIMATION_DAYS + 1)
    returns: list[float] = []
    for i in range(first, upto + 1):
        own = stock[i].value / stock[i - 1].value - 1
        if index is None:
            returns.append(own)
            continue
        now, before = _index_at(index, stock[i].day), _index_at(index, stock[i - 1].day)
        if now is None or before is None:
            continue
        returns.append(own - (now / before - 1))
    return returns


def _deviation(values: Sequence[float]) -> float:
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def _window(
    name: str,
    stock: Sequence[Close],
    index: Sequence[Close] | None,
    start: int,
    end: int,
    sigma: float | None,
    estimated: int,
) -> ReactionWindow:
    days = end - start
    stock_return = (stock[end].value / stock[start].value - 1) * 100
    index_return = None
    begin, finish = _index_at(index, stock[start].day), _index_at(index, stock[end].day)
    if begin is not None and finish is not None:
        index_return = (finish / begin - 1) * 100
    excess = stock_return - (index_return or 0.0)
    against = "against the index" if index_return is not None else "with no index to compare"
    head = f"{percent_text(excess, signed=True)} {against} over {days} trading day{'s' * (days != 1)}"
    if sigma is None:
        return ReactionWindow(
            name=name,
            days=days,
            start=stock[start].day.isoformat(),
            end=stock[end].day.isoformat(),
            stock_return=stock_return,
            index_return=index_return,
            excess=excess,
            line=(
                f"{head}; no normal move: fewer than {MIN_ESTIMATION_DAYS} daily returns "
                f"before the filing ({estimated})"
            ),
        )
    normal = sigma * math.sqrt(days) * 100
    ratio = excess / normal if normal > 0 else None
    tail = (
        f", {abs(ratio):.1f} times its normal {days}-day move ({'down' if ratio < 0 else 'up'})"
        if ratio is not None
        else ""
    )
    return ReactionWindow(
        name=name,
        days=days,
        start=stock[start].day.isoformat(),
        end=stock[end].day.isoformat(),
        stock_return=stock_return,
        index_return=index_return,
        excess=excess,
        normal=normal,
        ratio=ratio,
        line=head + tail,
    )


def event_reaction(
    stock: Sequence[Close],
    index: Sequence[Close] | None,
    filed: date,
    *,
    days: int,
    as_of: date,
) -> list[ReactionWindow] | str:
    """The N-day window and the window to the latest close after a filing, or why there are none."""
    if not 1 <= days <= 60:
        raise ValueError("days must be 1 to 60")
    closes = closes_until(stock, as_of)
    index_closes = closes_until(index, as_of) if index else None
    start = next((i for i in range(len(closes) - 1, -1, -1) if closes[i].day < filed), None)
    if start is None:
        return "No close of the stock before the filing day is in the prices given."
    if start == len(closes) - 1:
        return "No close of the stock after the filing day is on or before the as-of date."
    returns = _excess_returns(closes, index_closes, start)
    sigma = _deviation(returns) if len(returns) >= MIN_ESTIMATION_DAYS else None
    windows: list[ReactionWindow] = []
    if start + days < len(closes):
        windows.append(
            _window(f"{days} trading days", closes, index_closes, start, start + days, sigma, len(returns))
        )
    windows.append(
        _window("to the latest close", closes, index_closes, start, len(closes) - 1, sigma, len(returns))
    )
    return windows
