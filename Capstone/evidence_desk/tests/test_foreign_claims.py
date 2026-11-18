"""The claim compiler on claims another model wrote: the set, the judgements, the numbers.

``eval/claim-tests-foreign.json`` was written by Claude Sonnet 5.5 without sight of the
grammar; ``eval/claim-tests-foreign-judgements.json`` judges each reading the compiler
prints, by hand, by the grammar's author. These tests pin the final scoring (``make
claim-foreign``), so a change to the grammar that moves a reading fails here until the
new reading is judged and the numbers below are changed on purpose.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.claimtest import NO_PERIOD_REASON, NotNumeric, compile_claim
from app.evaluation import foreign_claims as foreign
from app.evaluation.claim_tests import compiled_text, load_labels


@pytest.fixture(scope="module")
def judged() -> list[foreign.Judged]:
    return foreign.judge(foreign.load_claims(), foreign.load_judgements())


def test_the_set_is_120_distinct_claims_in_two_halves_of_60() -> None:
    claims = foreign.load_claims()
    assert len(claims) == 120
    halves = [c.half for c in claims]
    assert halves.count("development") == halves.count("held_out") == 60
    assert {c.company for c in claims} == {"NVDA", "AAPL", "MSFT"}


def test_every_reading_the_compiler_prints_has_been_judged(judged) -> None:
    assert [j.claim.id for j in judged if j.reading == "unjudged"] == []


def _numbers(t: foreign.Tally) -> tuple[int, ...]:
    return (
        t.numeric,
        t.right,
        t.wrong,
        *(t.not_compiled[cause] for cause in foreign.CAUSES),
        t.not_numeric,
        t.not_numeric_compiled_wrongly,
        t.not_numeric_label_wrong,
    )


# (numeric, right, wrong, not compiled: metric, form, period, phrasing,
#  not_numeric, not_numeric compiled wrongly, not_numeric compiled with the label wrong)
# Set A after rule 3 (eval/results/claim-tests-foreign-rule3.txt): f048, f091 and f095, a flow
# against an amount with no period named, are refused. After the forms round
# (claim-tests-foreign-forms.txt), (83, 42, 0, 22, 15, 1, 3, 37, 0, 0) for all; after the
# measure catalogue (claim-tests-foreign-catalogue.txt), (83, 31, 0, 26, 21, 2, 3, 37, 0, 0);
# before it, (83, 23, 0, 33, 21, 2, 4, 37, 0, 0).
FINAL = {
    "all": (83, 39, 0, 22, 15, 4, 3, 37, 0, 0),
    "development": (43, 21, 0, 13, 7, 2, 0, 17, 0, 0),
    "held_out": (40, 18, 0, 9, 8, 2, 3, 20, 0, 0),
}
# Set B after rule 3 (eval/results/claim-tests-foreign-b-rule3.txt): g106 is refused. After the
# forms round (claim-tests-foreign-b-forms.txt), (80, 23, 0, 33, 8, 2, 14, 40, 0, 0); after the
# measure catalogue (claim-tests-foreign-b-catalogue.txt), (80, 19, 1, 33, 8, 3, 16, 40, 0, 0);
# scored once before it (claim-tests-foreign-b.txt): (80, 5, 1, 47, 8, 3, 16, 40, 0, 0).
FINAL_B = (80, 22, 0, 33, 8, 3, 14, 40, 0, 0)


@pytest.mark.parametrize("half", list(FINAL))
def test_the_final_scoring(judged, half: str) -> None:
    chosen = [j for j in judged if half == "all" or j.claim.half == half]
    assert _numbers(foreign.tally(chosen)) == FINAL[half]


def test_the_scoring_of_set_b() -> None:
    claims = foreign.load_claims(Path("eval/claim-tests-foreign-b.json"))
    judgements = foreign.load_judgements(Path("eval/claim-tests-foreign-b-judgements.json"))
    judged = foreign.judge(claims, judgements)
    assert [j.claim.id for j in judged if j.reading == "unjudged"] == []
    assert _numbers(foreign.tally(judged)) == FINAL_B


def test_the_scoring_before_any_change_is_kept() -> None:
    before = Path("eval/results/claim-tests-foreign-before.txt").read_text(encoding="utf-8")
    assert "compiled and right 15, compiled and wrong 21, not compiled 47" in before
    assert "unjudged" not in before


def test_an_unjudged_reading_fails_the_command(tmp_path: Path, capsys) -> None:
    empty = tmp_path / "judgements.json"
    empty.write_text(json.dumps({"judgements": []}), encoding="utf-8")
    assert foreign.main(["--judgements", str(empty)]) == 1
    assert "unjudged readings: 120" in capsys.readouterr().out


def test_a_judgement_without_its_reason_is_refused(tmp_path: Path) -> None:
    bad = tmp_path / "judgements.json"
    entry = {"id": "f001", "canonical": "none", "reading": "not_compiled", "why": " "}
    bad.write_text(json.dumps({"judgements": [entry]}), encoding="utf-8")
    with pytest.raises(ValueError, match="reason"):
        foreign.load_judgements(bad)


def test_a_reading_judged_again_needs_a_revision_and_the_later_judgement_counts(
    tmp_path: Path,
) -> None:
    # Judgements are only appended. When a later rule makes the compiler print a reading it
    # printed before (none, refused for another cause), the new judgement says why in
    # ``revision``; the earlier one stays in the file and no longer counts.
    path = tmp_path / "judgements.json"
    first = {
        "id": "f001",
        "canonical": "none",
        "reading": "not_compiled",
        "why": "a metric",
        "cause": "metric",
    }
    again = {**first, "why": "rule 3: names no period", "cause": "period"}
    path.write_text(json.dumps({"judgements": [first, again]}), encoding="utf-8")
    with pytest.raises(ValueError, match="judged twice"):
        foreign.load_judgements(path)
    revised = {**again, "revision": "rule 3, 18 November 2026"}
    path.write_text(json.dumps({"judgements": [first, revised]}), encoding="utf-8")
    assert foreign.load_judgements(path)[("f001", "none")]["cause"] == "period"
    lone = tmp_path / "lone.json"
    lone.write_text(json.dumps({"judgements": [revised]}), encoding="utf-8")
    with pytest.raises(ValueError, match="revises nothing"):
        foreign.load_judgements(lone)


def test_the_own_labels_still_compile_exactly() -> None:
    # The grammar changed for the foreign development half; both labelled sets must still
    # print exactly their labels. This is a pass/fail pin, not a scoring of the held-out set.
    development, held_out = load_labels(Path("eval/claim-tests.json"))
    labels = (*development, *held_out)
    wrong = [
        label.id
        for label in labels
        if label.id not in RULE_3_REFUSES and compiled_text(label.claim) != label.expected
    ]
    assert wrong == []
    for label in labels:
        if label.id in RULE_3_REFUSES:
            assert label.expected != "none" and compiled_text(label.claim) == "none", label.id
            result = compile_claim(label.claim)
            assert isinstance(result, NotNumeric) and result.reason == NO_PERIOD_REASON


# Rule 3 (made after set C): these four labels expect the latest fiscal year for a flow against
# an amount in a sentence that names no period ("Revenue is over $100 billion."), the default
# the grammar had when they were written. The rule refuses them now. The labels are an answer
# key and were not changed: the disagreement is listed here and in docs/claim-tests.md.
RULE_3_REFUSES = {"d040", "d043", "d121", "h050"}
