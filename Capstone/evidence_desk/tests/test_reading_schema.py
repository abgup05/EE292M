"""The schema a model reader answers under stays within what the API accepts.

The Anthropic API refused the schema of the forms round with HTTP 400: "Schemas contains too
many parameters with union types (28 parameters with type arrays or anyOf)". Absence is now
written as a value (0, or a base whose ``used`` is false), and the tests are a list (none, one
or two), which states the test's shape once: the API also refused the schema that nested a
second test in the first ("The compiled grammar is too large"). These tests fail if a nullable
field is added back.
"""

from __future__ import annotations

from typing import Any

from app.core.claim_reading import READING_SCHEMA, as_reading, from_reading
from app.core.claimtest import ClaimTest, compile_claim

# None remains: no test is an empty list, and a second test is a second item of it.
MAX_UNION_PARAMETERS = 0


def union_parameters(schema: Any) -> int:
    """How many places in ``schema``, fully expanded, are an anyOf or a list of types."""
    if isinstance(schema, list):
        return sum(union_parameters(item) for item in schema)
    if not isinstance(schema, dict):
        return 0
    here = int("anyOf" in schema or isinstance(schema.get("type"), list))
    return here + sum(union_parameters(value) for value in schema.values())


def test_the_schema_has_at_most_two_union_typed_parameters() -> None:
    assert union_parameters(READING_SCHEMA) <= MAX_UNION_PARAMETERS


def test_the_counter_sees_a_nullable_field() -> None:
    either = {"anyOf": [{"type": "integer"}, {"type": "null"}]}
    nullable = {"type": "object", "properties": {"x": either}}
    assert union_parameters(nullable) == 1
    assert union_parameters({"type": ["integer", "null"]}) == 1


CLAIMS = (
    "Gross margin is expanding.",
    "Revenue grew more than 50% year over year.",
    "Revenue has more than doubled since fiscal 2023.",
    "Gross margin has stayed above 70% for the last four quarters.",
    "Operating cash flow was above net income in the latest fiscal year.",
)


def test_a_reading_written_with_values_for_absence_reads_back_as_the_same_test() -> None:
    compiled = [compile_claim(claim) for claim in CLAIMS]
    tests = [result for result in compiled if isinstance(result, ClaimTest)]
    assert len(tests) >= 3, "the grammar should read most of these sentences"
    for test in tests:
        answer = as_reading(test)
        assert all(union_free(item) for item in answer["tests"]), "no null in a written test"
        back = from_reading(answer)
        assert isinstance(back, ClaimTest)
        assert back == test


def union_free(test: dict[str, Any]) -> bool:
    """No value inside ``test`` is null."""

    def nulls(value: Any) -> int:
        if value is None:
            return 1
        if isinstance(value, dict):
            return sum(nulls(item) for item in value.values())
        return 0

    return nulls(test) == 0


def test_null_and_the_value_for_absence_mean_the_same() -> None:
    compiled = (compile_claim(claim) for claim in CLAIMS)
    test = next(result for result in compiled if isinstance(result, ClaimTest))
    answer = as_reading(test)
    with_nulls = as_reading(test)
    left = with_nulls["tests"][0]["left"]
    left["base"] = None
    left["period"]["fiscal_year"] = left["period"]["fiscal_year"] or None
    left["period"]["quarter"] = left["period"]["quarter"] or None
    with_nulls["tests"][0]["each_since"] = None
    first, second = from_reading(answer), from_reading(with_nulls)
    assert isinstance(first, ClaimTest) and isinstance(second, ClaimTest)
    assert first == second
