"""What the brief says about who read a computed test, in each configuration (referee 5, 4).

The arithmetic is never a model's. Which test a claim became is: with model readers on, a
test counts when two readers reach it, and two models can reach it without the grammar. The
brief must not say "no model" of that.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.ports import ClaimDraft
from app.services.export import render_markdown
from tests.fakes import ScriptedAnalyst
from tests.test_summary_after_computed import _execute


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory):
    tmp_path: Path = tmp_path_factory.mktemp("readers-note")
    return _execute(tmp_path, ScriptedAnalyst(lambda claim, passages: ClaimDraft()))


def _note(run, readers: str) -> str:
    text = render_markdown(run.model_copy(update={"claim_readers": readers}))
    section = text.split("## Computed tests", 1)[1]
    return section.split("###", 1)[0].replace("\\", "")


def test_the_grammar_alone_is_a_fixed_rule_and_no_model(run) -> None:
    note = _note(run, "grammar")
    assert "no model" in note and "the grammar" in note


def test_the_grammar_and_one_model_must_both_read_the_test(run) -> None:
    note = _note(run, "grammar and model")
    assert "no model was involved" not in note.lower()
    assert "both" in note and "one model" in note


def test_two_model_readers_can_decide_a_test_without_the_grammar(run) -> None:
    note = _note(run, "grammar, model and model_2")
    assert "no model was involved" not in note.lower()
    assert "two models" in note and "without the grammar" in note
    assert "no model wrote" in note  # the arithmetic is still the code's
