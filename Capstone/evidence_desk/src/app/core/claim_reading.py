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
from typing import Any, get_args

from app.core.claimtest import (
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
    "growth_threshold": (("yoy", "qoq"), ("percent",)),
    "faster_than": (("yoy", "qoq"), ("term",)),
    "compound": (("cagr",), ("percent",)),
    "share": (("share", "max_share"), ("percent",)),
}
SAME_SUBJECT = ("direction", "acceleration")
WHAT_IT_COMPARES = {
    "direction": "a direction compares a measure's value",
    "acceleration": "an acceleration compares a measure's growth (yoy or qoq)",
    "streak": "a streak counts rises (streak)",
    "threshold": "a threshold compares a measure's value",
    "growth_threshold": "a growth threshold compares a measure's growth (yoy or qoq)",
    "faster_than": "a faster-than compares two measures' growth (yoy or qoq)",
    "compound": "a compound rate is a cagr",
    "share": "a share is a share or the largest customer's share (max_share)",
}

_NULLABLE_INT: dict[str, Any] = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
_PERIOD: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(PERIOD_KINDS)},
        "back": {"type": "integer"},
        "fiscal_year": _NULLABLE_INT,
        "quarter": _NULLABLE_INT,
    },
    "required": ["kind", "back", "fiscal_year", "quarter"],
    "additionalProperties": False,
}
_TERM: dict[str, Any] = {
    "type": "object",
    "properties": {
        "fn": {"type": "string", "enum": list(FUNCTIONS)},
        "subject": {"type": "string"},
        "member": {"type": "string"},
        "years": {"type": "integer"},
        "period": _PERIOD,
    },
    "required": ["fn", "subject", "member", "years", "period"],
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
READING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "computable": {"type": "boolean"},
        "reason": {"type": "string"},
        "test": {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {
                        "form": {"type": "string", "enum": list(FORMS)},
                        "left": _TERM,
                        "op": {"type": "string", "enum": list(OPS)},
                        "right_term": {"anyOf": [_TERM, {"type": "null"}]},
                        "right_number": {"anyOf": [_NUMBER, {"type": "null"}]},
                    },
                    "required": ["form", "left", "op", "right_term", "right_number"],
                    "additionalProperties": False,
                },
                {"type": "null"},
            ]
        },
    },
    "required": ["computable", "reason", "test"],
    "additionalProperties": False,
}


class Refused(ValueError):
    """A reading that does not validate; the message says what is wrong, in words."""


def as_reading(result: ClaimTest | NotNumeric) -> dict[str, Any]:
    """``result`` written as a reader answers it under :data:`READING_SCHEMA`."""
    if isinstance(result, NotNumeric):
        return {"computable": False, "reason": result.reason, "test": None}
    right = result.right
    return {
        "computable": True,
        "reason": "",
        "test": {
            "form": result.form,
            "left": _term_json(result.left),
            "op": result.op,
            "right_term": _term_json(right) if isinstance(right, Term) else None,
            "right_number": (
                {"value": right.value, "unit": right.unit} if isinstance(right, Number) else None
            ),
        },
    }


def _term_json(term: Term) -> dict[str, Any]:
    period = term.period
    return {
        "fn": term.fn,
        "subject": term.subject,
        "member": term.member,
        "years": term.years,
        "period": {
            "kind": period.kind,
            "back": period.back,
            "fiscal_year": period.fiscal_year,
            "quarter": period.quarter,
        },
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
    test = _object(data.get("test"), "the test")
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
        same = right.subject == left.subject
        if form in SAME_SUBJECT and not same:
            raise Refused(f"a {form} compares one measure with itself at another time")
        if form == "faster_than" and same:
            raise Refused("a faster-than compares two different measures")
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
    return ClaimTest(form, left, op, right)  # type: ignore[arg-type]


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
    if fn in ("share", "max_share"):
        if subject not in SHARE_AXES:
            raise Refused(f"a share's axis {subject!r} is not one of {', '.join(SHARE_AXES)}")
        if period.kind != "filing":
            raise Refused("a share is read from the newest filing (period kind 'filing')")
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
    return Term(fn, subject, period, member=member, years=int(years or 0))


def _period(value: object) -> Period:
    data = _object(value, "a period")
    kind = _choice(data.get("kind"), PERIOD_KINDS, "period kind")
    back = _integer(data.get("back"), "a period's back", 0, MAX_BACK)
    year, quarter = data.get("fiscal_year"), data.get("quarter")
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
