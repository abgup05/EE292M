"""What the price implies: the constant revenue growth at which a stated cash-flow model equals it.

Pure arithmetic under stated assumptions; not a forecast and not advice. The model
(:func:`present_value`), with every number an assumption the result prints:

- revenue grows at a constant rate ``g`` for ``years`` years from today's trailing revenue;
- each year's cash flow is the after-tax operating profit at a constant operating margin,
  ``revenue × margin × (1 − tax)``, less the reinvestment that growth needs,
  ``(revenue − last year's revenue) ÷ sales-to-capital`` (a falling revenue releases
  capital, the same arithmetic the other way);
- after the last year, the cash flow of the year after grows at ``terminal_growth``
  forever, worth ``cash ÷ (discount − terminal_growth)`` at the end of the last year;
- every amount is discounted at ``discount_rate`` a year, end of year.

Its value is compared with the enterprise value (market value plus debt less cash and
securities), because the cash flows are before any payment to lenders.
:func:`implied_growth` scans ``g`` from :data:`LOW` to :data:`HIGH` percent a year in
steps of one point for the first crossing of the target, then bisects to
:data:`TOLERANCE`; a target no growth in that range reaches is not solved, and the result
says on which side it lies. When the return on new capital, ``margin × (1 − tax) ×
sales-to-capital``, is under the discount rate, growth lowers the value, a higher price
implies a lower growth, and the result says so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

LOW = -50.0
HIGH = 100.0
STEP = 1.0
TOLERANCE = 1e-9
RATE_STEPS: tuple[float, ...] = (-2.0, -1.0, 0.0, 1.0, 2.0)
MARGIN_STEPS: tuple[float, ...] = (-5.0, 0.0, 5.0)


@dataclass(frozen=True)
class DcfAssumptions:
    """The model's inputs; percents as 9.0 for 9%. Raises ValueError for an impossible one."""

    revenue: float
    operating_margin: float
    tax_rate: float
    sales_to_capital: float
    discount_rate: float
    terminal_growth: float
    years: int = 10

    def __post_init__(self) -> None:
        checks = (
            (self.revenue > 0 and math.isfinite(self.revenue), "revenue must be positive"),
            (-100 < self.operating_margin < 100, "operating margin must be between -100 and 100"),
            (0 <= self.tax_rate < 100, "tax rate must be 0 to under 100"),
            (self.sales_to_capital > 0, "sales-to-capital must be positive"),
            (0 < self.discount_rate <= 50, "discount rate must be above 0 and at most 50"),
            (
                -5 <= self.terminal_growth < self.discount_rate,
                "terminal growth must be at least -5 and under the discount rate",
            ),
            (1 <= self.years <= 30, "years must be 1 to 30"),
        )
        for ok, message in checks:
            if not ok:
                raise ValueError(message)

    @property
    def return_on_new_capital(self) -> float:
        """After-tax operating profit per dollar reinvested, in percent."""
        return self.operating_margin * (1 - self.tax_rate / 100) * self.sales_to_capital


def present_value(growth: float, a: DcfAssumptions) -> float:
    """The model's value today at a constant revenue growth of ``growth`` percent a year."""
    g, r = growth / 100, a.discount_rate / 100
    keep = a.operating_margin / 100 * (1 - a.tax_rate / 100)
    revenue = a.revenue
    value = 0.0
    for year in range(1, a.years + 1):
        grown = revenue * (1 + g)
        cash = grown * keep - (grown - revenue) / a.sales_to_capital
        value += cash / (1 + r) ** year
        revenue = grown
    gt = a.terminal_growth / 100
    after = revenue * (1 + gt)
    terminal_cash = after * keep - (after - revenue) / a.sales_to_capital
    value += terminal_cash / (r - gt) / (1 + r) ** a.years
    return value


@dataclass(frozen=True)
class Solution:
    """The growth that solves the model (None and why), and a note on its direction."""

    growth: float | None
    reason: str = ""
    note: str = ""


def implied_growth(target: float, a: DcfAssumptions) -> Solution:
    """The constant growth in percent at which :func:`present_value` equals ``target``."""
    note = ""
    if a.return_on_new_capital < a.discount_rate:
        note = (
            f"At these assumptions the return on new capital ({a.return_on_new_capital:.1f}%) is "
            f"under the discount rate ({a.discount_rate:g}%): growth lowers the value, so a "
            "higher price implies lower growth."
        )
    steps = round((HIGH - LOW) / STEP)
    points = [LOW + STEP * i for i in range(steps + 1)]
    gaps = [present_value(g, a) - target for g in points]
    for (low, high), (below, above) in zip(
        zip(points, points[1:], strict=False), zip(gaps, gaps[1:], strict=False), strict=True
    ):
        if below == 0:
            return Solution(low, note=note)
        if (below < 0) != (above < 0):
            return Solution(_bisect(target, a, low, high, below), note=note)
    if gaps[-1] == 0:
        return Solution(points[-1], note=note)
    side = "above" if all(gap < 0 for gap in gaps) else "below"
    return Solution(
        None,
        reason=(
            f"The target is {side} the model's value at every growth from {LOW:g}% to "
            f"{HIGH:g}% a year."
        ),
        note=note,
    )


def _bisect(target: float, a: DcfAssumptions, low: float, high: float, low_gap: float) -> float:
    for _ in range(200):
        middle = (low + high) / 2
        gap = present_value(middle, a) - target
        if (gap < 0) == (low_gap < 0):
            low, low_gap = middle, gap
        else:
            high = middle
        if high - low < TOLERANCE:
            break
    return (low + high) / 2


@dataclass(frozen=True)
class Cell:
    """One cell of the sensitivity grid."""

    discount_rate: float
    operating_margin: float
    implied_growth: float | None


def sensitivity(target: float, a: DcfAssumptions) -> list[Cell]:
    """The implied growth at each discount rate ± 1 and 2 points and margin ± 5 points.

    A cell whose assumptions are impossible (a discount rate at or under the terminal
    growth) has no growth.
    """
    cells: list[Cell] = []
    for step in RATE_STEPS:
        for margin_step in MARGIN_STEPS:
            rate = a.discount_rate + step
            margin = a.operating_margin + margin_step
            try:
                varied = replace(a, discount_rate=rate, operating_margin=margin)
            except ValueError:
                cells.append(Cell(rate, margin, None))
                continue
            cells.append(Cell(rate, margin, implied_growth(target, varied).growth))
    return cells
