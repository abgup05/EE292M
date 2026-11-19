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
  written as so many periods back from the newest one, when the newest is known (a
  share's or a part's too: the newest filing's own period, ``filing``, stays apart, since
  which filing is newest is not known here).
- **Equivalent thresholds and spans.** Growth above (or below) zero is a rise (or fall) on
  the same span: ``yoy(m)[P] > 0%`` is ``m[P] > m[P a year earlier]``, ``qoq`` the quarter
  before, ``cagr(m, Ny)[P] > 0%`` against ``N`` years earlier; a compound rate over one
  year is the growth on a year earlier; a change over one year (or quarter) is that growth
  (``change(m, FY-1)[FY]`` is ``yoy(m)[FY]``), and a change above zero a rise on its span; a
  count of rises is a whole number, so ``> 3`` is ``>= 4``; a number is compared to six
  significant digits (two decimals of a percent).
- **Several periods, and two tests.** A test held in each of one period is the test; every
  year since a named one is so many years when the newest is known; a rise on the period
  before, held in each of the last N, is a streak of at least N; two tests joined by "and"
  are put in one order, and a comparison of two measures (compare) either way round.
- **A member's name** is compared without case, extra spaces, or "&" for "and".

What it does not do: decide that two different measures mean the same (that is the
catalogue's job), or treat ``>`` and ``>=`` as one for an amount or a percent.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ed_v14.core.claimtest import ClaimTest, Number, Op, Period, Term

FLIP: dict[Op, Op] = {">": "<", "<": ">", ">=": "<=", "<=": ">="}
TWO_TERMS = ("direction", "acceleration", "faster_than", "compare")
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
    if test.also is not None:
        first, second = sorted((normalize(p, newest) for p in test.parts), key=_canonical)
        return replace(first, also=second)
    left = _term(test.left, at)
    right = _term(test.right, at) if isinstance(test.right, Term) else _number(test.right)
    each, since = test.each, test.each_since
    test = ClaimTest(test.form, left, test.op, right)
    test = _as_growth(test)
    test = _as_rise(test)
    test = _whole_count(test)
    if test.form in TWO_TERMS and isinstance(test.right, Term):
        if _order(test.right) < _order(test.left):
            test = ClaimTest(test.form, test.right, FLIP[test.op], test.left)
    if since is not None and at.fiscal_year is not None and at.fiscal_year > since:
        each, since = at.fiscal_year - since, None
    if each == 1:
        each = 0
    if each and _rise_on_the_period_before(test):
        streak = Term("streak", test.left.subject, test.left.period)
        return ClaimTest("streak", streak, ">=", Number(float(each), "count"))
    return replace(test, each=each, each_since=since)


def _canonical(test: ClaimTest) -> str:
    return test.canonical


def _rise_on_the_period_before(test: ClaimTest) -> bool:
    """``m[P] > m[P before]`` at the newest quarter or fiscal year: one rise of a streak."""
    left, right = test.left, test.right
    return (
        test.form == "direction"
        and test.op == ">"
        and isinstance(right, Term)
        and left.period in (Period("Q"), Period("FY"))
        and right.period == left.period.step_back()
        and right.subject == left.subject
        and not left.axis
    )


# Terms and periods


def _member(name: str) -> str:
    return " ".join(name.casefold().replace("&", " and ").split())


def _term(term: Term, newest: Newest) -> Term:
    period = _relative(term.period, newest)
    base = _relative(term.base, newest) if term.base is not None else None
    member = _member(term.member) if term.member else ""
    return replace(term, period=period, member=member, base=base)


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


def _as_growth(test: ClaimTest) -> ClaimTest:
    """A change over one year as the growth on a year earlier, over one quarter as qoq."""
    terms = [test.left] + ([test.right] if isinstance(test.right, Term) else [])
    rewritten = []
    for term in terms:
        if term.fn == "change" and term.base == term.period.years_back(1):
            term = Term("yoy", term.subject, term.period)
        elif (
            term.fn == "change" and term.period.kind == "Q" and term.base == term.period.step_back()
        ):
            term = Term("qoq", term.subject, term.period)
        rewritten.append(term)
    right = rewritten[1] if len(rewritten) == 2 else test.right
    return replace(test, left=rewritten[0], right=right)


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
        case "change" if left.base is not None:
            earlier = left.base
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
