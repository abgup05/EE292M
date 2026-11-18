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
FINAL = {
    "all": (83, 22, 11, 28, 18, 1, 3, 37, 0, 0),
    "development": (43, 14, 0, 19, 10, 0, 0, 17, 0, 0),
    "held_out": (40, 8, 11, 9, 8, 1, 3, 20, 0, 0),
}


@pytest.mark.parametrize("half", list(FINAL))
def test_the_final_scoring(judged, half: str) -> None:
    chosen = [j for j in judged if half == "all" or j.claim.half == half]
    assert _numbers(foreign.tally(chosen)) == FINAL[half]


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


def test_the_own_labels_still_compile_exactly() -> None:
    # The grammar changed for the foreign development half; both labelled sets must still
    # print exactly their labels. This is a pass/fail pin, not a scoring of the held-out set.
    development, held_out = load_labels(Path("eval/claim-tests.json"))
    labels = (*development, *held_out)
    wrong = [label.id for label in labels if compiled_text(label.claim) != label.expected]
    assert wrong == []
