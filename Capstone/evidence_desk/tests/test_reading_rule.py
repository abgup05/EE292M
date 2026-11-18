"""Up to three readers of a claim and the rule that counts a computed test.

The grammar reads every claim; up to two model readers (different models) may read it
too. A computed test counts when at least two readers reach the same normal form
(:func:`app.core.claim_normal.normal_form`). When the grammar and one model agree and
the other model writes a different test, it counts, marked "counted, with one dissenting
reading", with the dissent shown; a refusal is not a dissent. When no two agree, every
reading is shown and nothing counts. With the grammar alone it counts as before, and the
run says that is one reader.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import wiring
from app.core import policy
from app.core.claim_reading import as_reading
from app.core.claimtest import ClaimTest, compile_claim
from app.core.measures import CATALOGUE, PART_MEASURES
from app.core.models import ThesisRequest, Verdict
from app.core.ports import ClaimDraft
from app.engines.claim_reader import (
    DEFAULT_SECOND_READER_MODEL,
    READ_SYSTEM,
    SECOND_READ_STEP,
    ModelClaimReader,
    read_request,
    second_reader,
)
from app.services.thesis_run import execute_run, new_run
from app.store import FilingCache, Store
from tests.fakes import FakePages, ScriptedAnalyst
from tests.replay_run import recorded_filings
from tests.test_claim_reading import Answers

MARGIN = "Gross margin is expanding."
GROWTH = "Revenue grew more than 200% year over year."
REFUSED = "Free cash flow per employee is rising."  # the grammar reads no test
REFUSE = {"computable": False, "reason": "not one test", "tests": []}


def _compiled(text: str) -> ClaimTest:
    test = compile_claim(text)
    assert isinstance(test, ClaimTest), test
    return test


# The rule, on normal forms


def test_one_reader_counts_what_the_grammar_compiled() -> None:
    rule = policy.reading_agreement({"grammar": "revenue[Q] > revenue[Q-4]"})
    assert rule.conclusion == policy.ONE_READER and rule.counts
    assert rule.agreeing == ("grammar",) and rule.dissenting == ()
    assert not policy.reading_agreement({"grammar": policy.NO_TEST}).counts


def test_two_of_three_agree_and_a_refusal_is_not_a_dissent() -> None:
    form = "revenue[Q] > revenue[Q-4]"
    rule = policy.reading_agreement({"grammar": form, "model": form, "model_2": policy.NO_TEST})
    assert rule.conclusion == policy.AGREED and rule.counts
    assert rule.agreeing == ("grammar", "model") and rule.dissenting == ()


def test_a_third_readers_different_test_is_a_dissent_and_still_counts() -> None:
    form, other = "revenue[Q] > revenue[Q-4]", "revenue[Q] > revenue[Q-1]"
    rule = policy.reading_agreement({"grammar": form, "model": form, "model_2": other})
    assert rule.conclusion == policy.AGREED_WITH_DISSENT and rule.counts
    assert rule.dissenting == ("model_2",) and rule.form == form
    assert policy.AGREEMENT_LABELS[rule.conclusion] == "counted, with one dissenting reading"


def test_the_two_models_may_agree_without_the_grammar() -> None:
    form = "total_assets[Q] > $100B"
    rule = policy.reading_agreement({"grammar": policy.NO_TEST, "model": form, "model_2": form})
    assert rule.conclusion == policy.AGREED and rule.agreeing == ("model", "model_2")


@pytest.mark.parametrize(
    "forms",
    [
        {"grammar": "a[Q] > $1B", "model": "a[Q] > $2B", "model_2": "a[Q] > $3B"},
        {"grammar": "a[Q] > $1B", "model": policy.NO_TEST, "model_2": policy.NO_TEST},
        {"grammar": "a[Q] > $1B", "model": "a[Q] > $2B"},
    ],
)
def test_when_no_two_agree_nothing_counts(forms: dict[str, str]) -> None:
    rule = policy.reading_agreement(forms)
    assert rule.conclusion == policy.NOT_AGREED and not rule.counts


def test_when_every_reader_refuses_there_is_no_test() -> None:
    rule = policy.reading_agreement({"grammar": policy.NO_TEST, "model": policy.NO_TEST})
    assert rule.conclusion == policy.NO_TEST_READ and not rule.counts


# The readers


def test_the_prompt_is_built_from_the_catalogue() -> None:
    for key in CATALOGUE:
        assert f"- {key}:" in READ_SYSTEM, key
    assert "net cash and marketable securities" not in READ_SYSTEM  # no stale definitions
    assert CATALOGUE["net_cash"].definition in READ_SYSTEM
    for part in PART_MEASURES:
        assert f'{part}(segment "' in READ_SYSTEM or part in READ_SYSTEM
    assert "axis" in READ_SYSTEM and "no history" in READ_SYSTEM


def test_the_second_reader_has_its_own_model_and_step(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_READER_MODEL_2", raising=False)
    reader = second_reader(transport=Answers({}))
    assert reader.name == "model_2" and reader.model == DEFAULT_SECOND_READER_MODEL
    assert DEFAULT_SECOND_READER_MODEL == "claude-sonnet-5-5"
    assert reader.request(MARGIN).step == SECOND_READ_STEP != read_request(MARGIN).step
    monkeypatch.setenv("ANTHROPIC_READER_MODEL_2", "claude-opus-5-5")
    assert second_reader(transport=Answers({})).model == "claude-opus-5-5"


def test_the_env_example_documents_the_second_reader() -> None:
    example = Path(".env.example").read_text(encoding="utf-8")
    assert "ANTHROPIC_READER_MODEL_2=" in example and '"models"' in example


def test_two_model_readers_are_chosen_by_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(wiring.READER_VARIABLE, "models")
    monkeypatch.delenv(wiring.CASSETTE_VARIABLE, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-key")
    readers = wiring.claim_reader_from_env()
    assert isinstance(readers, tuple) and [r.name for r in readers] == ["model", "model_2"]
    monkeypatch.setenv(wiring.CASSETTE_VARIABLE, str(tmp_path))
    first, second = wiring.claim_reader_from_env()
    assert first.request(MARGIN).step != second.request(MARGIN).step


# A run with three readers


def _run(tmp_path: Path, claims: list[str], readers):
    request = ThesisRequest(
        ticker="NVDA", decision="Whether to keep an overweight position", claims=claims
    )
    return execute_run(
        new_run(request),
        Store(tmp_path / "record.sqlite"),
        filings=recorded_filings(),
        analyst=ScriptedAnalyst(lambda claim, passages: ClaimDraft()),
        fetch_page=FakePages({}),
        cache=FilingCache(),
        claim_reader=readers,
    )


def _readers(first: dict, second: dict) -> tuple[ModelClaimReader, ModelClaimReader]:
    return ModelClaimReader(transport=Answers(first)), second_reader(transport=Answers(second))


def test_with_the_grammar_alone_the_run_says_it_is_one_reader(tmp_path: Path) -> None:
    run = _run(tmp_path, [MARGIN], None)
    assert run.claim_reading_rule == policy.READING_RULE_ONE
    assert "One reader" in run.claim_reading_rule
    computed = run.claims[0].computed
    assert computed is not None and computed.agreement == policy.ONE_READER
    assert computed.counted_as == "supports"


def test_written_the_other_way_round_a_models_reading_agrees(tmp_path: Path) -> None:
    margin = _compiled(MARGIN)
    flipped = ClaimTest(margin.form, margin.right, "<", margin.left)  # type: ignore[arg-type]
    run = _run(tmp_path, [MARGIN], _readers({MARGIN: as_reading(flipped)}, {MARGIN: REFUSE}))

    computed = run.claims[0].computed
    assert computed is not None and computed.agreement == policy.AGREED
    assert computed.read_by == ["grammar", "model"] and computed.counted_as == "supports"
    assert computed.canonical == margin.canonical  # the grammar's own writing is computed
    forms = [r.normal_form for r in run.claims[0].readings]
    assert forms[0] == forms[1] and forms[2] == policy.NO_TEST
    assert run.claim_readers == "grammar, model and model_2"
    assert "Three readers" in run.claim_reading_rule


def test_a_dissenting_third_reading_counts_marked_and_shown(tmp_path: Path) -> None:
    margin = _compiled(MARGIN)
    other = _compiled("Gross margin rose from the previous quarter.")
    run = _run(
        tmp_path, [MARGIN], _readers({MARGIN: as_reading(margin)}, {MARGIN: as_reading(other)})
    )

    claim = run.claims[0]
    assert claim.computed is not None
    assert claim.computed.agreement == policy.AGREED_WITH_DISSENT
    assert claim.computed.agreement_label == "counted, with one dissenting reading"
    assert claim.computed.counted_as == "supports" and claim.verdict == Verdict.supported
    assert [(d.reader, d.canonical) for d in claim.computed.dissent] == [
        ("model_2", other.canonical)
    ]
    assert other.canonical in claim.computed.note


def test_when_the_two_models_agree_the_grammars_refusal_does_not_stop_the_count(
    tmp_path: Path,
) -> None:
    assert not isinstance(compile_claim(REFUSED), ClaimTest)
    test = _compiled("Free cash flow is rising.")
    reading = as_reading(test)
    run = _run(tmp_path, [REFUSED], _readers({REFUSED: reading}, {REFUSED: reading}))

    claim = run.claims[0]
    assert claim.computed is not None and claim.computed.canonical == test.canonical
    assert claim.computed.agreement == policy.AGREED
    assert claim.computed.read_by == ["model", "model_2"]
    assert claim.computed.counted_as in ("supports", "challenges")
    assert claim.compile_note == ""
    assert run.coverage.claims_compiled == 1


def test_when_no_two_agree_every_reading_is_shown_and_nothing_counts(tmp_path: Path) -> None:
    growth = _compiled(GROWTH)
    hundred = _compiled("Revenue grew more than 100% year over year.")
    fifty = _compiled("Revenue grew more than 50% year over year.")
    readers = _readers({GROWTH: as_reading(hundred)}, {GROWTH: as_reading(fifty)})
    run = _run(tmp_path, [GROWTH], readers)

    computed = run.claims[0].computed
    assert computed is not None and computed.agreement == policy.NOT_AGREED
    assert computed.counted_as == "" and computed.canonical == growth.canonical
    for text in (growth.canonical, hundred.canonical, fifty.canonical):
        assert text in computed.note
