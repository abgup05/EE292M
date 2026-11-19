"""A claim's typed test written as JSON, and the strict validation of a reading into it.

Pure: no I/O, no model. A second reader of a claim (the model parser,
:mod:`app.engines.claim_reader`) answers under :data:`READING_SCHEMA`;
:func:`from_reading` validates that answer into the grammar's own
:class:`~app.core.claimtest.ClaimTest`, or refuses it with a
:class:`~app.core.claimtest.NotNumeric` naming what it got wrong. Anything outside
what the grammar itself can produce is refused: an unknown measure, form,
comparison, function, period or unit, or a shape that does not fit the form (a
direction between two different measures, a growth threshold in dollars, a share
with no member). "Not a claim this tool can compute" is a valid answer.
:func:`as_reading` writes a compiled test in the same JSON, so the two readings
compare on equal terms (their ``canonical`` text).
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, get_args

from ed_v14.core.claimtest import (
    FORMS,
    METRICS,
    SHARE_AXES,
    ClaimTest,
    Function,
    NotNumeric,
    Number,
    Op,
    Period,
    PeriodKind,
    Term,
    member_label,
)
from ed_v14.core.limits import MAX_EACH_PERIODS
from ed_v14.core.measures import PART_AXES, PART_MEASURES

FUNCTIONS: tuple[str, ...] = get_args(Function)
OPS: tuple[str, ...] = get_args(Op)
PERIOD_KINDS: tuple[str, ...] = get_args(PeriodKind)
UNITS = ("percent", "USD", "count")
MAX_REASON_CHARS = 300
MAX_MEMBER_CHARS = 80
MAX_BACK = 40
YEARS = (1990, 2100)
CAGR_YEARS = (2, 30)
REFUSED = "the model's reading is refused: "
NOT_COMPUTABLE = "the model reader: "

# What each form compares: the functions its left term may use, and what its right side
# is ("term" with the same function, or a constant in one of the units given).
FORM_SHAPES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "direction": (("value",), ("term",)),
    "acceleration": (("yoy", "qoq"), ("term",)),
    "streak": (("streak",), ("count",)),
    "threshold": (("value",), ("percent", "USD")),
    "growth_threshold": (("yoy", "qoq", "change"), ("percent",)),
    "faster_than": (("yoy", "qoq", "change"), ("term",)),
    "compound": (("cagr",), ("percent",)),
    "share": (("share", "max_share"), ("percent",)),
    "compare": (("value",), ("term",)),
}
SAME_SUBJECT = ("direction", "acceleration")
# The forms a test held in each of several periods may take; "since" a named year only a
# change on the year before.
EACH_FORMS = (
    "direction",
    "acceleration",
    "threshold",
    "growth_threshold",
    "faster_than",
    "compare",
)
WHAT_IT_COMPARES = {
    "direction": "a direction compares a measure's value",
    "acceleration": "an acceleration compares a measure's growth (yoy or qoq)",
    "streak": "a streak counts rises (streak)",
    "threshold": "a threshold compares a measure's value",
    "growth_threshold": "a growth threshold compares a measure's growth (yoy, qoq or change)",
    "faster_than": "a faster-than compares two measures' growth (yoy, qoq or change)",
    "compound": "a compound rate is a cagr",
    "share": "a share is a share or the largest customer's share (max_share)",
    "compare": "a comparison of two measures compares their values",
}

# The API refuses a schema with many nullable or union-typed parameters, so absence is
# written as a value: 0 for a fiscal year, a quarter or each_since that is not named, a base
# whose ``used`` is false, and a right_term or right_number that the form does not read.
# A reading that writes null for any of these is read the same way.
_INT_OR_ZERO: dict[str, Any] = {"type": "integer"}
_PERIOD: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(PERIOD_KINDS)},
        "back": {"type": "integer"},
        "fiscal_year": _INT_OR_ZERO,
        "quarter": _INT_OR_ZERO,
    },
    "required": ["kind", "back", "fiscal_year", "quarter"],
    "additionalProperties": False,
}
_BASE: dict[str, Any] = {
    "type": "object",
    "properties": {"used": {"type": "boolean"}, **_PERIOD["properties"]},
    "required": ["used", *_PERIOD["required"]],
    "additionalProperties": False,
}
_TERM: dict[str, Any] = {
    "type": "object",
    "properties": {
        "fn": {"type": "string", "enum": list(FUNCTIONS)},
        "subject": {"type": "string"},
        "member": {"type": "string"},
        "axis": {"type": "string", "enum": ["", *PART_AXES]},
        "years": {"type": "integer"},
        "period": _PERIOD,
        "base": _BASE,
    },
    "required": ["fn", "subject", "member", "axis", "years", "period", "base"],
    "additionalProperties": False,
}
_NUMBER: dict[str, Any] = {
    "type": "object",
    "properties": {
        "value": {"type": "number"},
        "unit": {"type": "string", "enum": list(UNITS)},
    },
    "required": ["value", "unit"],
    "additionalProperties": False,
}
_TEST_FIELDS: dict[str, Any] = {
    "form": {"type": "string", "enum": list(FORMS)},
    "left": _TERM,
    "op": {"type": "string", "enum": list(OPS)},
    "right_term": _TERM,
    "right_number": _NUMBER,
    "each": {"type": "integer"},
    "each_since": _INT_OR_ZERO,
}
_TEST: dict[str, Any] = {
    "type": "object",
    "properties": _TEST_FIELDS,
    "required": list(_TEST_FIELDS),
    "additionalProperties": False,
}
# One test as a reader writes it; the proposing model's implications use it too
# (app.engines.analyser).
TEST_SCHEMA: dict[str, Any] = _TEST
# ``tests`` holds no test (not computable), one, or two joined by "and". A list states the
# test's shape once: the API also refused a schema that spelled out a second test inside the
# first ("The compiled grammar is too large").
READING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "computable": {"type": "boolean"},
        "reason": {"type": "string"},
        "tests": {"type": "array", "items": _TEST},
    },
    "required": ["computable", "reason", "tests"],
    "additionalProperties": False,
}
MAX_JOINED_TESTS = 2


class Refused(ValueError):
    """A reading that does not validate; the message says what is wrong, in words."""


def as_reading(result: ClaimTest | NotNumeric) -> dict[str, Any]:
    """``result`` written as a reader answers it under :data:`READING_SCHEMA`."""
    if isinstance(result, NotNumeric):
        return {"computable": False, "reason": result.reason, "tests": []}
    tests = [_test_json(result)]
    if result.also is not None:
        tests.append(_test_json(result.also))
    return {"computable": True, "reason": "", "tests": tests}


def _test_json(test: ClaimTest) -> dict[str, Any]:
    right = test.right
    return {
        "form": test.form,
        "left": _term_json(test.left),
        "op": test.op,
        # The one the form does not read is filled in, never null: see the schema's note.
        "right_term": _term_json(right if isinstance(right, Term) else test.left),
        "right_number": (
            {"value": right.value, "unit": right.unit}
            if isinstance(right, Number)
            else {"value": 0, "unit": UNITS[0]}
        ),
        "each": test.each,
        "each_since": test.each_since or 0,
    }


def _period_json(period: Period) -> dict[str, Any]:
    return {
        "kind": period.kind,
        "back": period.back,
        "fiscal_year": period.fiscal_year or 0,
        "quarter": period.quarter or 0,
    }


_NO_BASE: dict[str, Any] = {"used": False, "kind": "Q", "back": 0, "fiscal_year": 0, "quarter": 0}


def _term_json(term: Term) -> dict[str, Any]:
    return {
        "fn": term.fn,
        "subject": term.subject,
        "member": term.member,
        "axis": term.axis,
        "years": term.years,
        "period": _period_json(term.period),
        "base": (
            {"used": True, **_period_json(term.base)} if term.base is not None else dict(_NO_BASE)
        ),
    }


def from_reading(answer: object) -> ClaimTest | NotNumeric:
    """The test a reader's answer states, validated; or why it is not one.

    A valid "not computable" answer gives a :class:`NotNumeric` with the reader's reason
    (prefixed :data:`NOT_COMPUTABLE`); an answer that does not validate gives one prefixed
    :data:`REFUSED` and saying what is wrong. Never raises.
    """
    try:
        return _validated(answer)
    except Refused as exc:
        return NotNumeric(REFUSED + str(exc))


def _validated(answer: object) -> ClaimTest | NotNumeric:
    data = _object(answer, "the answer")
    computable = data.get("computable")
    if not isinstance(computable, bool):
        raise Refused("'computable' is not true or false")
    reason = data.get("reason")
    if not isinstance(reason, str):
        raise Refused("'reason' is not text")
    if not computable:
        said = " ".join(reason.split())[:MAX_REASON_CHARS] or "no reason given"
        return NotNumeric(NOT_COMPUTABLE + said)
    tests = data.get("tests")
    if tests is None and data.get("test") is not None:
        # The earlier shape: one test with its second inside it as and_test.
        earlier = _object(data.get("test"), "the test")
        second = earlier.get("and_test")
        if isinstance(second, dict) and second.get("and_test") is not None:
            raise Refused("a claim joins at most two tests with 'and'")
        tests = [earlier] if second is None else [earlier, second]
    if not isinstance(tests, list) or not tests:
        raise Refused("a computable answer states a test; there is none")
    if len(tests) > MAX_JOINED_TESTS:
        raise Refused("a claim joins at most two tests with 'and'")
    first = _test(_object(tests[0], "the test"))
    if len(tests) == 1:
        return first
    return replace(first, also=_test(_object(tests[1], "the second test")))


def _test(test: dict[str, Any]) -> ClaimTest:
    """One test of the answer (the first, or the one joined by "and"), validated."""
    form = _choice(test.get("form"), FORMS, "form")
    op = _choice(test.get("op"), OPS, "comparison")
    functions, rights = FORM_SHAPES[form]
    left_fn = _choice(_object(test.get("left"), "a term").get("fn"), FUNCTIONS, "function")
    if left_fn not in functions:
        raise Refused(f"{WHAT_IT_COMPARES[form]}, not {left_fn}")
    left = _term(test["left"])
    right: Term | Number
    if rights == ("term",):
        if test.get("right_term") is None:
            raise Refused(f"a {form.replace('_', ' ')} compares two terms; there is one")
        right = _term(test["right_term"])
        if right.fn != left.fn:
            raise Refused(f"the two terms of a {form.replace('_', ' ')} use the same function")
        same = (right.subject, right.member, right.axis) == (left.subject, left.member, left.axis)
        if form in SAME_SUBJECT and not same:
            raise Refused(f"a {form} compares one measure with itself at another time")
        if form in ("faster_than", "compare") and same:
            raise Refused(f"a {form.replace('_', ' ')} compares two different measures")
        if form == "faster_than" and (left.period, left.base) != (right.period, right.base):
            raise Refused("a faster-than compares two measures' growth over the same span")
        if form == "compare":
            _comparable(left, right)
        if right.text() == left.text():
            raise Refused("the test compares a term with itself")
    else:
        right = _number(test.get("right_number"))
        if right.unit not in rights:
            raise Refused(
                f"the unit of a {form.replace('_', ' ')} is {' or '.join(rights)}, not {right.unit}"
            )
        if form == "threshold":
            wanted = "percent" if METRICS[left.subject][1] == "ratio" else "USD"
            if right.unit != wanted:
                raise Refused(f"the unit of {left.subject} is {wanted}, not {right.unit}")
    each = _integer(test.get("each", 0), "each", 0, MAX_EACH_PERIODS)
    since = test.get("each_since") or None
    if since is not None:
        since = _integer(since, "each_since", *YEARS)
    result = ClaimTest(form, left, op, right, each=each, each_since=since)  # type: ignore[arg-type]
    if each or since is not None:
        _each(result)
    return result


def _comparable(left: Term, right: Term) -> None:
    """Two measures compared level with level: one period, one kind of number."""
    if left.period != right.period:
        raise Refused("a comparison of two measures reads both in the same period")

    def kind(term: Term) -> str:
        return "flow" if term.axis else METRICS[term.subject][1]

    if kind(left) != kind(right):
        raise Refused(
            f"{left.subject} ({kind(left)}) and {right.subject} ({kind(right)}) are not "
            "the same kind of number"
        )


def _each(test: ClaimTest) -> None:
    """A test held in each of several periods, or every fiscal year since a named one."""
    if test.each and test.each_since is not None:
        raise Refused("a test is held in each of the last N periods or every year since one")
    if test.each == 1:
        raise Refused("'each' counts two periods or more; a test of one period has each 0")
    if test.form not in EACH_FORMS or test.from_filing:
        raise Refused(
            f"a {test.form.replace('_', ' ')} is not tested in each of several periods "
            "(a share or a part is read from one filing)"
        )
    kinds = {term.period.kind for term in test.terms} | {
        term.base.kind for term in test.terms if term.base is not None
    }
    if len(kinds) != 1 or kinds - {"Q", "FY"}:
        raise Refused("each steps back one quarter (kind Q) or one fiscal year (kind FY)")
    if test.each_since is None:
        return
    rise = (
        test.form == "direction"
        and isinstance(test.right, Term)
        and test.right.period == test.left.period.step_back()
    ) or (test.form == "growth_threshold" and test.left.fn == "yoy")
    if test.left.period != Period("FY") or not rise:
        raise Refused(
            "every year since a named one is a change on the year before (a direction or a "
            "yoy growth threshold at FY): whether that year itself counts is unclear for a level"
        )


def _object(value: object, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Refused(f"{what} is not a JSON object")
    return value


def _choice(value: object, allowed: tuple[str, ...], what: str) -> Any:
    if not isinstance(value, str) or value not in allowed:
        raise Refused(f"the {what} {value!r} is not one of {', '.join(allowed)}")
    return value


def _integer(value: object, what: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise Refused(f"{what} {value!r} is not a whole number from {low} to {high}")
    return value


def _term(value: object) -> Term:
    data = _object(value, "a term")
    fn = _choice(data.get("fn"), FUNCTIONS, "function")
    subject = data.get("subject")
    member = data.get("member")
    if not isinstance(subject, str) or not isinstance(member, str):
        raise Refused("a term's subject and member are text")
    period = _period(data.get("period"))
    years = data.get("years")
    axis = data.get("axis", "")
    if not isinstance(axis, str) or axis not in ("", *PART_AXES):
        raise Refused(f"a part's axis {axis!r} is not one of {', '.join(PART_AXES)}")
    raw_base = data.get("base")
    if isinstance(raw_base, dict) and "used" in raw_base:
        # The shape the API accepts: a base is always written, and used says whether it is.
        used = raw_base["used"]
        if not isinstance(used, bool):
            raise Refused("a base's used is true or false")
        raw_base = {key: item for key, item in raw_base.items() if key != "used"} if used else None
    base = _period(raw_base) if raw_base is not None else None
    if (fn == "change") != (base is not None):
        raise Refused("a change, and only a change, names the period it is from (base)")
    if axis:
        return _part_term(fn, subject, member, axis, period, years)
    if fn in ("share", "max_share"):
        if subject not in SHARE_AXES:
            raise Refused(f"a share's axis {subject!r} is not one of {', '.join(SHARE_AXES)}")
        _from_a_filing(period, "a share")
        if fn == "max_share" and (subject != "customer" or member):
            raise Refused("the largest share is the largest customer's, with no member")
        if fn == "share":
            if subject == "customer":
                raise Refused("a single customer's share is read as the largest (max_share)")
            if not member.strip() or len(member) > MAX_MEMBER_CHARS:
                raise Refused(f"a share names its member in 1 to {MAX_MEMBER_CHARS} characters")
            member = member_label(member, subject)
    else:
        if subject not in METRICS:
            raise Refused(f"the measure {subject!r} is not one of {', '.join(METRICS)}")
        if member:
            raise Refused("only a share names a member")
        if period.kind == "filing":
            raise Refused("only a share is read from the newest filing")
    if fn == "cagr":
        years = _integer(years, "a compound rate's years", *CAGR_YEARS)
    elif years != 0:
        raise Refused("only a compound rate (cagr) has years")
    if base is not None:
        _span(subject, period, base)
    return Term(fn, subject, period, member=member, years=int(years or 0), base=base)


def _span(subject: str, period: Period, base: Period) -> None:
    """A change's span: the same kind of period, the base earlier, a measure with a level."""
    if METRICS[subject][1] == "ratio":
        raise Refused("a change in a percentage is ambiguous (points or percent)")
    if base.kind != period.kind or period.kind not in ("Q", "FY"):
        raise Refused("a change runs from one fiscal year (or quarter) to another of the kind")
    if base.named == period.named:
        since = (base.fiscal_year or 0, base.quarter or 0)
        until = (period.fiscal_year or 0, period.quarter or 0)
        earlier = since < until if base.named else base.back > period.back
        if not earlier:
            raise Refused("a change's base is earlier than its period")


def _from_a_filing(period: Period, what: str) -> None:
    """A share or a part is read from a filing's tags: its newest period, or a fiscal year
    or quarter that filing reports; four quarters are not tagged."""
    if period.kind not in ("filing", "FY", "Q"):
        raise Refused(f"{what} is read for the newest filing, a fiscal year (FY) or a quarter (Q)")


def _part_term(
    fn: str, subject: str, member: str, axis: str, period: Period, years: object
) -> Term:
    """A part of the company's measure: revenue (or a segment's operating income) of one
    member, or its change on a year earlier, from the newest filing."""
    if fn not in ("value", "yoy"):
        raise Refused("a part's measure is its value or its change on a year earlier (yoy)")
    if subject not in PART_MEASURES:
        raise Refused(f"a part's measure {subject!r} is not one of {', '.join(PART_MEASURES)}")
    if subject == "operating_income" and axis != "segment":
        raise Refused("only a segment's operating income is tagged")
    _from_a_filing(period, "a part's measure")
    if not member.strip() or len(member) > MAX_MEMBER_CHARS:
        raise Refused(f"a part names its member in 1 to {MAX_MEMBER_CHARS} characters")
    if years != 0:
        raise Refused("only a compound rate (cagr) has years")
    label = member_label(member, axis)
    return Term(fn, subject, period, member=label, axis=axis)  # type: ignore[arg-type]


def _period(value: object) -> Period:
    data = _object(value, "a period")
    kind = _choice(data.get("kind"), PERIOD_KINDS, "period kind")
    back = _integer(data.get("back"), "a period's back", 0, MAX_BACK)
    year, quarter = data.get("fiscal_year") or None, data.get("quarter") or None
    if year is not None:
        year = _integer(year, "a fiscal year", *YEARS)
        if back:
            raise Refused("a named fiscal year has no back")
        if kind != ("Q" if quarter is not None else "FY"):
            raise Refused("a named year is kind FY, a named quarter kind Q")
    if quarter is not None:
        if year is None:
            raise Refused("a quarter needs a fiscal year")
        quarter = _integer(quarter, "a quarter", 1, 4)
    if kind == "filing" and back:
        raise Refused("the newest filing has no back")
    return Period(kind, back=back, fiscal_year=year, quarter=quarter)


def _number(value: object) -> Number:
    data = _object(value, "the constant")
    number, unit = data.get("value"), _choice(data.get("unit"), UNITS, "unit")
    if isinstance(number, bool) or not isinstance(number, int | float) or not math.isfinite(number):
        raise Refused(f"the constant {number!r} is not a finite number")
    if unit == "count" and (number != int(number) or number < 1):
        raise Refused("a count of periods is a whole number of at least 1")
    return Number(float(number), unit)
