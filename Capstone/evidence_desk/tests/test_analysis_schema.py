"""The argument's schemas stay small enough for the API, and a flat answer regroups into the record.

The API compiles a schema into a grammar. It accepted ``PROPOSE_SCHEMA`` (which holds the
typed claim test) and refused the first schema of the argument, which spelled the sentence
object out under nine sections, a condition and a scenario: HTTP 400, "The compiled grammar
is too large". Its exact limit is not known, so the flat schemas (one for a claim, one for
the thesis) are each held well under the one known to be accepted, by a rough measure of
size: schema nodes plus enum members.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core import analysis_policy as rules
from app.engines.analyser import (
    CLAIM_SCHEMA,
    PROPOSE_SCHEMA,
    THESIS_SCHEMA,
    parse_claim_argument,
    parse_thesis_argument,
)
from app.engines.transport import EngineError
from tests.test_reading_schema import union_parameters

CLAIMS = ["c1", "c2"]
# The most the flat schema may be of the accepted one, by the measure below.
MOST_OF_ACCEPTED = 0.5


def size(schema: Any) -> int:
    """Schema nodes (every object with a type) plus enum members, fully expanded."""
    if isinstance(schema, list):
        return sum(size(item) for item in schema)
    if not isinstance(schema, dict):
        return 0
    here = int("type" in schema) + len(schema.get("enum", []))
    return here + sum(size(value) for key, value in schema.items() if key != "enum")


def objects(schema: Any) -> int:
    """How many object definitions the schema spells out."""
    if isinstance(schema, list):
        return sum(objects(item) for item in schema)
    if not isinstance(schema, dict):
        return 0
    return int(schema.get("type") == "object") + sum(objects(v) for v in schema.values())


def test_the_measure_counts_nodes_and_enum_members() -> None:
    one = {"type": "object", "properties": {"a": {"type": "string", "enum": ["x", "y"]}}}
    assert size(one) == 4 and objects(one) == 1


def test_each_schema_is_well_under_the_one_the_api_accepted() -> None:
    accepted = size(PROPOSE_SCHEMA)
    for schema, definitions in ((CLAIM_SCHEMA, 3), (THESIS_SCHEMA, 2)):
        assert size(schema) <= accepted * MOST_OF_ACCEPTED, (size(schema), accepted)
        # The sentence object is spelled out once (with the answer, and a claim's condition).
        assert objects(schema) == definitions
        assert union_parameters(schema) == 0
        enums = [v for v in _walk(schema) if "enum" in v]
        assert len(enums) == 1, "one enum only: the section"


def _walk(schema: Any) -> list[dict[str, Any]]:
    if isinstance(schema, list):
        return [found for item in schema for found in _walk(item)]
    if not isinstance(schema, dict):
        return []
    return [schema, *(found for value in schema.values() for found in _walk(value))]


def _s(section: str, text: str, scenario: str = "") -> dict[str, Any]:
    return {"section": section, "scenario": scenario, "text": text, "cites": ["x"]}


def _c(text: str, **more: Any) -> dict[str, Any]:
    base = {"measure": "", "comparison": "none", "threshold": 0, "unit": "none"}
    return {"text": text, "cites": ["x"], "event_category": "none"} | base | more


def _claim(**parts: Any) -> dict[str, Any]:
    return {"lean": "mixed", "sentences": [], "conditions": []} | parts


def _thesis(**parts: Any) -> dict[str, Any]:
    return {"leans_on": [], "weakest_link": "", "sentences": []} | parts


def test_a_claims_flat_answer_is_regrouped_by_section_in_order() -> None:
    draft = parse_claim_argument(
        _claim(
            lean="supports",
            sentences=[
                _s("case_for", "For."),
                _s("assessment", "One."),
                _s("assessment", "Two."),
                _s("decides", "R&amp;D decides."),
            ],
            conditions=[
                _c(
                    "Below 70%.",
                    measure="gross_margin",
                    comparison="<",
                    threshold=70,
                    unit="percent",
                ),
                _c("A new chief executive.", event_category="leadership"),
                _c(
                    "Odd.",
                    measure="gross_margin",
                    comparison="roughly",
                    threshold=1,
                    unit="furlongs",
                    event_category="weather",
                ),
            ],
        ),
        "c1",
    )
    assert draft.thesis is None and len(draft.claims) == 1
    c1 = draft.claims[0]
    assert (c1.claim_id, c1.lean) == ("c1", "supports")
    assert [s.text for s in c1.assessment] == ["One.", "Two."]
    assert [s.text for s in c1.case_for] == ["For."] and c1.case_against == []
    assert [s.text for s in c1.decides] == ["R&D decides."]  # unescaped on the way out
    measured, event, odd = c1.would_change
    assert (measured.measure, measured.comparison, measured.threshold, measured.unit) == (
        "gross_margin",
        "<",
        70.0,
        "percent",
    )
    assert (event.measure, event.event_category) == ("", "leadership")
    # What code cannot read in a condition is cleared, never guessed.
    assert (odd.comparison, odd.unit, odd.event_category) == ("none", "none", "")
    assert draft.cut == 0 and draft.problems == []
    assert parse_claim_argument(_claim(lean="sideways"), "c1").claims[0].lean == "unclear"


def test_the_thesiss_flat_answer_is_regrouped_with_its_scenarios() -> None:
    draft = parse_thesis_argument(
        _thesis(
            leans_on=["c2", "c9", "c2", "c1"],
            weakest_link="c2",
            sentences=[
                _s("bottom_line", "First."),
                _s("scenario", "Margins stay.", "Holds"),
                _s("scenario", "Margins fall.", "Breaks"),
                _s("scenario", "Growth stays.", "Holds"),
                _s("weakest_why", "Because."),
            ],
        ),
        CLAIMS,
    )
    thesis = draft.thesis
    assert thesis is not None and draft.claims == []
    assert thesis.leans_on == ["c2", "c1"] and thesis.weakest_link == "c2"
    assert [s.text for s in thesis.bottom_line] == ["First."]
    assert [s.text for s in thesis.weakest_why] == ["Because."]
    assert [(s.name, [c.text for c in s.conditions]) for s in thesis.scenarios] == [
        ("Holds", ["Margins stay.", "Growth stays."]),
        ("Breaks", ["Margins fall."]),
    ]
    assert draft.cut == 0 and draft.problems == []


def test_what_is_over_a_cap_or_in_a_section_not_its_own_is_cut_and_counted_with_why() -> None:
    over = rules.ASSESSMENT_SENTENCES + 2
    claim = parse_claim_argument(
        _claim(
            sentences=[
                *[_s("assessment", f"Sentence {n}.") for n in range(over)],
                _s("bottom_line", "A thesis section in a claim's answer."),
                _s("case_for", ""),  # no text: nothing, and not counted
            ],
            conditions=[_c(f"Condition {n}.") for n in range(rules.MAX_CONDITIONS + 1)],
        ),
        "c1",
    )
    c1 = claim.claims[0]
    assert [s.text for s in c1.assessment] == [
        f"Sentence {n}." for n in range(rules.ASSESSMENT_SENTENCES)
    ]
    assert len(c1.would_change) == rules.MAX_CONDITIONS
    assert claim.cut == 2 + 1 + 1  # over the assessment's cap, misplaced, a condition over
    told = " | ".join(claim.problems)
    for reason in (
        "over the cap of 6 in assessment of a claim",
        "in section 'bottom_line', which is not one of a claim",
        "conditions over the cap of 3",
    ):
        assert reason in told, reason
    thesis = parse_thesis_argument(
        _thesis(
            weakest_link="c7",
            sentences=[
                *[_s("bottom_line", f"B{n}.") for n in range(rules.BOTTOM_LINE_SENTENCES + 1)],
                _s("case_for", "A claim's section in the thesis's answer."),
                *[_s("scenario", "x.", f"S{n}") for n in range(rules.MAX_SCENARIOS + 1)],
                *[_s("scenario", f"y{n}.", "S0") for n in range(rules.SECTION_SENTENCES)],
            ],
        ),
        CLAIMS,
    )
    found = thesis.thesis
    assert found is not None and found.weakest_link == ""
    assert len(found.bottom_line) == rules.BOTTOM_LINE_SENTENCES
    assert [s.name for s in found.scenarios] == [f"S{n}" for n in range(rules.MAX_SCENARIOS)]
    assert len(found.scenarios[0].conditions) == rules.SECTION_SENTENCES
    assert thesis.cut == 1 + 1 + 1 + 1  # bottom line, misplaced, a fourth scenario, S0's fourth
    told = " | ".join(thesis.problems)
    for reason in (
        "over the cap of 6 in bottom_line",
        "in section 'case_for', which is not one of the thesis",
        "a scenario over the cap of 3",
        "over the cap of 3 in a scenario",
        "the weakest link named is not a claim id",
    ):
        assert reason in told, reason


def test_a_malformed_answer_is_refused() -> None:
    for broken in (
        "text",
        _claim(sentences="none"),
        _claim(sentences=["a sentence that is not an object"]),
        _claim(sentences=[{"section": "assessment", "text": "x", "cites": "y"}]),
        _claim(lean=3),
        {"lean": "mixed", "sentences": []},
    ):
        with pytest.raises(EngineError):
            parse_claim_argument(broken, "c1")
    for broken in ("text", _thesis(leans_on="c1"), _thesis(sentences={}), {"leans_on": []}):
        with pytest.raises(EngineError):
            parse_thesis_argument(broken, CLAIMS)
