"""The judge's file explains every construct a counted reading can contain.

Set C's judge marked two readings unsure because the notation did not explain ``each(N):``
or ``change(m, BASE)``. The notation is now built from the grammar's own lists (its forms,
functions and period kinds) and a table of constructs; these tests fail when one of them has
no explanation, and when a reading in any claim set or result file uses a construct the
notation does not explain.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import get_args

import pytest

from app.core.claimtest import FORMS, ClaimTest, Function, PeriodKind, compile_claim
from app.evaluation import claim_readers
from app.evaluation.claim_readers import constructs, notation

RESULTS = Path("eval/results")


def test_every_form_has_an_explanation_and_an_example_of_that_form() -> None:
    assert set(claim_readers.FORM_NOTES) == set(FORMS)
    for form, (sentence, _) in claim_readers.FORM_NOTES.items():
        test = compile_claim(sentence)
        assert isinstance(test, ClaimTest), sentence
        assert test.form == form, sentence


def test_every_function_and_period_kind_has_an_explanation() -> None:
    assert set(get_args(Function)) <= set(claim_readers.CONSTRUCT_NOTES)
    assert set(get_args(PeriodKind)) <= {
        name.removeprefix("period ") for name in claim_readers.CONSTRUCT_NOTES
    }


@pytest.mark.parametrize(
    ("reading", "construct"),
    [
        ("each(4): gross_margin[Q] > 70%", "each"),
        ("each(since FY2023): revenue[FY] > revenue[FY-1]", "each since"),
        ("change(revenue, FY2023)[FY] > 100%", "change"),
        ("(gross_margin[Q] > 70%) and (yoy(revenue)[Q] > 50%)", "and"),
        ('revenue(segment "data center")[FY2026] > $100B', "part at a period"),
        ('revenue(segment "data center")[filing] > $10B', "part"),
        ("revenue[Q2 FY2027] > revenue[Q1 FY2027]", "period named quarter"),
        ("revenue[TTM] > revenue[TTM-4]", "period TTM"),
    ],
)
def test_the_notation_explains_each_construct_a_reading_can_contain(
    reading: str, construct: str
) -> None:
    assert construct in constructs(reading)
    assert construct in claim_readers.CONSTRUCT_NOTES
    assert claim_readers.CONSTRUCT_NOTES[construct] in notation()


def _readings() -> list[str]:
    found = []
    for path in sorted(RESULTS.glob("claim-readers-*.csv")):
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                found += [row.get(key, "") for key in ("counted", "grammar", "model", "model_2")]
    labels = json.loads(Path("eval/claim-tests.json").read_text(encoding="utf-8"))
    found += [label["expected"] for key in ("development", "held_out") for label in labels[key]]
    results = json.loads(Path("eval/claim-results.json").read_text(encoding="utf-8"))
    found += [case["canonical"] for case in results["cases"]]
    return [text for text in found if text and text != "none"]


def test_every_construct_of_every_recorded_reading_is_explained() -> None:
    readings = _readings()
    assert len(readings) > 300
    missing = {
        name: text
        for text in readings
        for name in constructs(text)
        if name not in claim_readers.CONSTRUCT_NOTES
    }
    assert missing == {}


def test_the_judge_file_carries_the_notation() -> None:
    row = {"id": "x1", "company": "NVDA", "claim": "Margin is up.", "counted": "a[Q] > a[Q-4]"}
    text = claim_readers.judge_file("x", [row])
    assert notation() in text
    for form, (sentence, _) in claim_readers.FORM_NOTES.items():
        assert sentence in text, form
