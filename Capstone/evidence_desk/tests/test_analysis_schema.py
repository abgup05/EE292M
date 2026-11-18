"""The analyse schema stays small enough for the API, and the flat answer regroups into the record.

The API compiles a schema into a grammar. It accepted ``PROPOSE_SCHEMA`` (which holds the
typed claim test) and refused the first ``ANALYSE_SCHEMA``, which spelled the sentence
object out under nine sections, a condition and a scenario: HTTP 400, "The compiled grammar
is too large". Its exact limit is not known, so the flat schema is held well under the one
known to be accepted, by a rough measure of size: schema nodes plus enum members.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core import analysis_policy as rules
from app.engines.analyser import ANALYSE_SCHEMA, PROPOSE_SCHEMA, parse_argument
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


def test_the_analyse_schema_is_well_under_the_one_the_api_accepted() -> None:
    accepted, flat = size(PROPOSE_SCHEMA), size(ANALYSE_SCHEMA)
    assert flat <= accepted * MOST_OF_ACCEPTED, (flat, accepted)
    # The sentence object is spelled out once: the answer, a lean, a sentence, a condition.
    assert objects(ANALYSE_SCHEMA) == 4
    assert union_parameters(ANALYSE_SCHEMA) == 0
    enums = [v for v in _walk(ANALYSE_SCHEMA) if "enum" in v]
    assert len(enums) == 1, "one enum only: the section"


def _walk(schema: Any) -> list[dict[str, Any]]:
    if isinstance(schema, list):
        return [found for item in schema for found in _walk(item)]
    if not isinstance(schema, dict):
        return []
    return [schema, *(found for value in schema.values() for found in _walk(value))]


def _s(about: str, section: str, text: str, scenario: str = "") -> dict[str, Any]:
    return {"about": about, "section": section, "scenario": scenario, "text": text, "cites": ["x"]}


def _c(about: str, text: str, **more: Any) -> dict[str, Any]:
    base = {"measure": "", "comparison": "none", "threshold": 0, "unit": "none"}
    return {"about": about, "text": text, "cites": ["x"], "event_category": "none"} | base | more


def _answer(**parts: Any) -> dict[str, Any]:
    empty = {"leans": [], "sentences": [], "conditions": [], "leans_on": [], "weakest_link": ""}
    return empty | parts


def test_a_flat_answer_is_regrouped_by_claim_and_section_in_order() -> None:
    draft = parse_argument(
        _answer(
            leans=[{"claim_id": "c1", "lean": "supports"}, {"claim_id": "c2", "lean": "sideways"}],
            sentences=[
                _s("thesis", "bottom_line", "First."),
                _s("c2", "case_for", "For c2."),
                _s("c1", "assessment", "One."),
                _s("thesis", "scenario", "Margins stay.", "Holds"),
                _s("c1", "assessment", "Two."),
                _s("thesis", "scenario", "Margins fall.", "Breaks"),
                _s("thesis", "scenario", "Growth stays.", "Holds"),
                _s("thesis", "weakest_why", "Because."),
                _s("c1", "decides", "R&amp;D decides."),
            ],
            conditions=[
                _c(
                    "c1",
                    "Below 70%.",
                    measure="gross_margin",
                    comparison="<",
                    threshold=70,
                    unit="percent",
                ),
                _c("c1", "A new chief executive.", event_category="leadership"),
                _c(
                    "c2",
                    "Odd.",
                    measure="gross_margin",
                    comparison="roughly",
                    threshold=1,
                    unit="furlongs",
                    event_category="weather",
                ),
            ],
            leans_on=["c2", "c9", "c2", "c1"],
            weakest_link="c2",
        ),
        CLAIMS,
    )
    c1, c2 = draft.claims
    assert (c1.claim_id, c1.lean) == ("c1", "supports")
    assert [s.text for s in c1.assessment] == ["One.", "Two."]
    assert [s.text for s in c1.decides] == ["R&D decides."]  # unescaped on the way out
    assert c2.lean == "unclear" and [s.text for s in c2.case_for] == ["For c2."]
    measured, event = c1.would_change
    assert (measured.measure, measured.comparison, measured.threshold, measured.unit) == (
        "gross_margin",
        "<",
        70.0,
        "percent",
    )
    assert (event.measure, event.event_category) == ("", "leadership")
    # What code cannot read in a condition is cleared, never guessed.
    odd = c2.would_change[0]
    assert (odd.comparison, odd.unit, odd.event_category) == ("none", "none", "")
    thesis = draft.thesis
    assert thesis is not None
    assert thesis.leans_on == ["c2", "c1"] and thesis.weakest_link == "c2"
    assert [s.text for s in thesis.bottom_line] == ["First."]
    assert [s.text for s in thesis.weakest_why] == ["Because."]
    assert [(s.name, [c.text for c in s.conditions]) for s in thesis.scenarios] == [
        ("Holds", ["Margins stay.", "Growth stays."]),
        ("Breaks", ["Margins fall."]),
    ]
    assert draft.cut == 0 and draft.problems == []


def test_what_cannot_be_placed_or_is_over_a_cap_is_cut_and_counted_with_why() -> None:
    over = rules.ASSESSMENT_SENTENCES + 2
    draft = parse_argument(
        _answer(
            leans=[{"claim_id": "c1", "lean": "mixed"}, {"claim_id": "c7", "lean": "mixed"}],
            sentences=[
                *[_s("c1", "assessment", f"Sentence {n}.") for n in range(over)],
                _s("c7", "assessment", "About no claim of the run."),
                _s("c1", "bottom_line", "A thesis section about a claim."),
                _s("thesis", "case_for", "A claim section about the thesis."),
                _s("c1", "case_for", ""),  # no text: nothing, and not counted
                *[_s("thesis", "scenario", "x.", f"S{n}") for n in range(rules.MAX_SCENARIOS + 1)],
                *[_s("thesis", "scenario", f"y{n}.", "S0") for n in range(rules.SECTION_SENTENCES)],
            ],
            conditions=[
                *[_c("c1", f"Condition {n}.") for n in range(rules.MAX_CONDITIONS + 1)],
                _c("thesis", "A condition about the thesis."),
            ],
            weakest_link="c7",
        ),
        CLAIMS,
    )
    c1 = draft.claims[0]
    assert [s.text for s in c1.assessment] == [
        f"Sentence {n}." for n in range(rules.ASSESSMENT_SENTENCES)
    ]
    assert len(c1.would_change) == rules.MAX_CONDITIONS
    thesis = draft.thesis
    assert thesis is not None and thesis.weakest_link == ""
    assert [s.name for s in thesis.scenarios] == [f"S{n}" for n in range(rules.MAX_SCENARIOS)]
    assert len(thesis.scenarios[0].conditions) == rules.SECTION_SENTENCES
    # 2 over the assessment's cap, 3 misplaced, 1 scenario too many, 1 over a scenario's cap,
    # 1 condition over the cap and 1 about no claim.
    assert draft.cut == 2 + 3 + 1 + 1 + 1 + 1
    told = " | ".join(draft.problems)
    for reason in (
        "over the cap of 6 in assessment of a claim",
        "about 'c7', which is no claim of the run",
        "in section 'bottom_line', which is not one of a claim",
        "in section 'case_for', which is not one of the thesis",
        "a scenario over the cap of 3",
        "over the cap of 3 in a scenario",
        "conditions over the cap of 3",
        "a condition about 'thesis'",
        "a lean for 'c7'",
        "no argument written for c2",
        "the weakest link named is not a claim id",
    ):
        assert reason in told, reason


def test_a_malformed_answer_is_refused() -> None:
    for broken in (
        "text",
        _answer(sentences="none"),
        _answer(sentences=["a sentence that is not an object"]),
        _answer(sentences=[{"about": "c1", "section": "assessment", "text": "x", "cites": "y"}]),
        _answer(leans_on="c1"),
        {"leans": [], "sentences": [], "leans_on": [], "weakest_link": ""},
    ):
        with pytest.raises(EngineError):
            parse_argument(broken, CLAIMS)
