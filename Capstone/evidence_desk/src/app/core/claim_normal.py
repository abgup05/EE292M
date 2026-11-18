"""One normal form for a claim test, so two readings of one claim compare as equal text.

The counting rule (:mod:`app.services.computed`) counts a computed test when two readers
reach the same test; readers write one test in several ways, and this function makes each
way one text. Pure: it reads nothing but the test and, optionally, which fiscal year and
quarter are the newest (:class:`Newest`), so that a named period equal to the default one
compares equal to it.

The equivalences, each with a test in ``tests/test_claim_normal.py``:

- **Either way round.** ``a > b`` and ``b < a``, for every form with a term on each side
  (direction, acceleration, faster-than): the terms are put in one order, the more recent
  period first, and the comparator turned to match.
- **An explicit period and the default it equals.** A named fiscal year or quarter is
  written as so many periods back from the newest one, when the newest is known; a share,
  and a part's figure, are always of the newest filing.
- **Equivalent thresholds and spans.** Growth above (or below) zero is a rise (or fall) on
  the same span: ``yoy(m)[P] > 0%`` is ``m[P] > m[P a year earlier]``, ``qoq`` the quarter
  before, ``cagr(m, Ny)[P] > 0%`` against ``N`` years earlier; a compound rate over one
  year is the growth on a year earlier; a count of rises is a whole number, so ``> 3`` is
  ``>= 4``; a number is compared to six significant digits (two decimals of a percent).
- **A member's name** is compared without case, extra spaces, or "&" for "and".

What it does not do: decide that two different measures mean the same (that is the
catalogue's job), or treat ``>`` and ``>=`` as one for an amount or a percent.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.core.claimtest import ClaimTest, Number, Op, Period, Term

FLIP: dict[Op, Op] = {">": "<", "<": ">", ">=": "<=", "<=": ">="}
TWO_TERMS = ("direction", "acceleration", "faster_than")
FROM_FILING = ("share", "max_share")
SIGNIFICANT = 6
PERCENT_DECIMALS = 2


@dataclass(frozen=True)
class Newest:
    """The newest fiscal year and fiscal quarter (year, quarter) the facts hold, if known."""

    fiscal_year: int | None = None
    quarter: tuple[int, int] | None = None


def normal_form(test: ClaimTest, newest: Newest | None = None) -> str:
    """The one text every equivalent writing of ``test`` shares."""
    return normalize(test, newest).canonical


def normalize(test: ClaimTest, newest: Newest | None = None) -> ClaimTest:
    """``test`` in its normal form (see the module's docstring)."""
    at = newest or Newest()
    left = _term(test.left, at)
    right = _term(test.right, at) if isinstance(test.right, Term) else _number(test.right)
    test = ClaimTest(test.form, left, test.op, right)
    test = _as_rise(test)
    test = _whole_count(test)
    if test.form in TWO_TERMS and isinstance(test.right, Term):
        if _order(test.right) < _order(test.left):
            test = ClaimTest(test.form, test.right, FLIP[test.op], test.left)
    return test


# Terms and periods


def _member(name: str) -> str:
    return " ".join(name.casefold().replace("&", " and ").split())


def _term(term: Term, newest: Newest) -> Term:
    period = term.period
    if term.fn in FROM_FILING or term.axis:
        period = Period("filing")
    else:
        period = _relative(period, newest)
    member = _member(term.member) if term.member else ""
    return replace(term, period=period, member=member)


def _relative(period: Period, newest: Newest) -> Period:
    """A named period as so many periods back from the newest, when that is known."""
    if period.fiscal_year is None:
        return period
    if period.quarter is None:
        if period.kind == "FY" and newest.fiscal_year is not None:
            back = newest.fiscal_year - period.fiscal_year
            return Period("FY", back) if back >= 0 else period
        return period
    if newest.quarter is not None and period.kind in ("Q", "TTM"):
        year, quarter = newest.quarter
        back = (year * 4 + quarter) - (period.fiscal_year * 4 + period.quarter)
        return Period(period.kind, back) if back >= 0 else period
    return period


def _order(term: Term) -> tuple[int, int, str]:
    """More recent first: a period counted back sorts by how far, a named one by its date."""
    period = term.period
    if period.fiscal_year is None:
        return (0, period.back, term.text())
    return (1, -(period.fiscal_year * 4 + (period.quarter or 4)), term.text())


# Thresholds and spans


def _number(number: Number) -> Number:
    if number.unit == "percent":
        return Number(round(number.value, PERCENT_DECIMALS) + 0.0, "percent")
    return Number(float(f"{number.value:.{SIGNIFICANT}g}"), number.unit)


def _as_rise(test: ClaimTest) -> ClaimTest:
    """Growth against zero as a rise or fall; a compound rate over one year as growth."""
    left, right = test.left, test.right
    if not isinstance(right, Number) or right.unit != "percent" or left.axis:
        return test
    if test.form == "compound" and left.years == 1:
        growth = Term("yoy", left.subject, left.period)
        return ClaimTest("growth_threshold", growth, test.op, right)
    if right.value != 0 or test.form not in ("growth_threshold", "compound"):
        return test
    match left.fn:
        case "yoy":
            earlier = left.period.years_back(1)
        case "qoq":
            earlier = left.period.step_back()
        case "cagr":
            earlier = left.period.years_back(left.years)
        case _:
            return test
    now = Term("value", left.subject, left.period)
    return ClaimTest("direction", now, test.op, Term("value", left.subject, earlier))


def _whole_count(test: ClaimTest) -> ClaimTest:
    """A count of rises compared as at least, or at most, a whole number."""
    right = test.right
    if test.form != "streak" or not isinstance(right, Number) or not right.value.is_integer():
        return test
    if test.op == ">":
        return ClaimTest(test.form, test.left, ">=", Number(right.value + 1, "count"))
    if test.op == "<":
        return ClaimTest(test.form, test.left, "<=", Number(right.value - 1, "count"))
    return test
