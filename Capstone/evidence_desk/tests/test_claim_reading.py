"""The second reader of a claim: a model parser behind a port, and the rule that counts readings.

The model is given the claim and the supported measures, forms and periods, and answers
a typed test as JSON under a schema, through the same transport and cassettes as every
model step. Its answer is validated into the grammar's own :class:`ClaimTest` and refused
when it does not validate or names anything unsupported; "not a claim this tool can
compute" is a valid answer. With it off (the default) nothing is asked. With it on, a
computed test counts toward a verdict only when both readers arrive at the same test.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app import wiring
from app.core import policy
from app.core.claim_reading import READING_SCHEMA, as_reading, from_reading
from app.core.claimtest import ClaimTest, NotNumeric, compile_claim
from app.core.models import ThesisRequest, Verdict
from app.core.ports import ClaimDraft
from app.engines.cassette import CassetteTransport
from app.engines.claim_reader import (
    DEFAULT_READER_MODEL,
    READ_STEP,
    ModelClaimReader,
)
from app.engines.transport import EngineError, ModelRequest
from app.evaluation.claim_tests import load_labels
from app.services.export import render_markdown
from app.services.thesis_run import execute_run, new_run
from app.store import FilingCache, Store
from tests.fakes import FakePages, ScriptedAnalyst
from tests.replay_run import recorded_filings

GRAMMAR_TESTS = [
    "Gross margin is expanding.",
    "Revenue grew more than 50% year over year.",
    "Revenue has grown for eight consecutive quarters.",
    "Operating expenses grew slower than revenue.",
    "Data center is more than 80% of revenue.",
    "Revenue has compounded at over 20% for five years.",
    "Net income was down in fiscal 2023 versus 2022.",
    "Operating cash flow was over $120 billion on a trailing basis.",
]


def _compiled(text: str) -> ClaimTest:
    test = compile_claim(text)
    assert isinstance(test, ClaimTest), test
    return test


# The validation: into the grammar's own type, or refused


@pytest.mark.parametrize("text", GRAMMAR_TESTS)
def test_a_reading_of_a_grammar_test_validates_to_the_same_test(text: str) -> None:
    test = _compiled(text)
    assert from_reading(json.loads(json.dumps(as_reading(test)))) == test


def test_every_test_the_grammar_compiles_from_the_labels_is_a_valid_reading() -> None:
    # Not a scoring of the labels: only that each compiled test survives the round trip.
    development, held_out = load_labels(Path("eval/claim-tests.json"))
    compiled = [compile_claim(label.claim) for label in (*development, *held_out)]
    tests = [test for test in compiled if isinstance(test, ClaimTest)]
    assert len(tests) > 100
    for test in tests:
        assert from_reading(as_reading(test)) == test, test.canonical


def test_not_a_claim_this_tool_can_compute_is_a_valid_answer() -> None:
    answer = {"computable": False, "reason": "a valuation", "test": None}
    result = from_reading(answer)
    assert isinstance(result, NotNumeric)
    assert result.reason == "the model reader: a valuation"


def _with(test: ClaimTest, **changes: Any) -> dict[str, Any]:
    answer = as_reading(test)
    for path, value in changes.items():
        node = answer["test"]
        *parents, leaf = path.split("__")
        for parent in parents:
            node = node[parent]
        node[leaf] = value
    return answer


@pytest.mark.parametrize(
    ("changes", "words"),
    [
        ({"left__subject": "sga"}, "measure 'sga'"),
        ({"form": "valuation"}, "form 'valuation'"),
        ({"op": "=="}, "comparison '=='"),
        ({"left__fn": "share"}, "a direction compares a measure's value"),
        ({"left__period__kind": "H1"}, "period kind 'H1'"),
        ({"left__period__back": -2}, "back"),
        ({"left__period__quarter": 3}, "a quarter needs a fiscal year"),
        ({"right_term": None}, "a direction compares two terms"),
    ],
)
def test_a_reading_that_names_anything_unsupported_is_refused(
    changes: dict[str, Any], words: str
) -> None:
    result = from_reading(_with(_compiled("Gross margin is expanding."), **changes))
    assert isinstance(result, NotNumeric)
    assert result.reason.startswith("the model's reading is refused: ")
    assert words in result.reason


def test_a_reading_with_a_wrong_unit_or_a_missing_member_is_refused() -> None:
    growth = _compiled("Revenue grew more than 50% year over year.")
    result = from_reading(_with(growth, right_number__unit="USD"))
    assert isinstance(result, NotNumeric) and "unit" in result.reason
    share = _compiled("Data center is more than 80% of revenue.")
    result = from_reading(_with(share, left__member=""))
    assert isinstance(result, NotNumeric) and "member" in result.reason


@pytest.mark.parametrize("answer", [None, [], "x", {"computable": True}, {"test": {}}])
def test_a_malformed_answer_is_refused(answer: object) -> None:
    result = from_reading(answer)
    assert isinstance(result, NotNumeric)
    assert result.reason.startswith("the model's reading is refused: ")


def test_the_schema_requires_every_field_and_allows_no_other() -> None:
    assert READING_SCHEMA["additionalProperties"] is False
    assert set(READING_SCHEMA["required"]) == {"computable", "reason", "test"}


# The model reader behind the port


class Answers:
    """A fake transport: answers each claim as a table says, and keeps the requests."""

    model = "fake-reader"
    via = "a test"

    def __init__(self, answers: dict[str, dict[str, Any]]) -> None:
        self.answers = answers
        self.requests: list[ModelRequest] = []

    def __call__(self, request: ModelRequest) -> dict[str, Any]:
        self.requests.append(request)
        claim = request.user.split("<claim>")[1].split("</claim>")[0]
        if claim not in self.answers:
            raise EngineError("no answer for this claim")
        return self.answers[claim]


def test_the_model_reader_sends_one_read_request_and_validates_the_answer() -> None:
    test = _compiled("Gross margin is expanding.")
    transport = Answers({"Gross margin is expanding.": as_reading(test)})
    reader = ModelClaimReader(transport=transport)
    assert reader.read("Gross margin is expanding.") == test
    (request,) = transport.requests
    assert request.step == READ_STEP == "read"
    assert request.schema == READING_SCHEMA
    for word in ("gross_margin", "faster_than", "Q-4", "FY2026", "TTM", "filing"):
        assert word in request.system
    assert reader.name == "model"


def test_the_claim_travels_escaped() -> None:
    transport = Answers({})
    with pytest.raises(EngineError):
        ModelClaimReader(transport=transport).read("Revenue <b>grew</b> & more.")
    assert "Revenue &lt;b&gt;grew&lt;/b&gt; &amp; more." in transport.requests[0].user


def test_the_model_reader_defaults_to_haiku_and_the_id_is_configurable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_READER_MODEL", raising=False)
    assert DEFAULT_READER_MODEL == "claude-haiku-5-5"
    assert ModelClaimReader().model == "claude-haiku-5-5"
    monkeypatch.setenv("ANTHROPIC_READER_MODEL", "claude-sonnet-5-5")
    assert ModelClaimReader().model == "claude-sonnet-5-5"


def test_the_model_reader_answers_from_a_cassette(tmp_path: Path) -> None:
    test = _compiled("Gross margin is expanding.")
    live = Answers({"Gross margin is expanding.": as_reading(test)})
    recording = ModelClaimReader(transport=CassetteTransport(tmp_path, live=live))
    assert recording.read("Gross margin is expanding.") == test
    replay = ModelClaimReader(transport=CassetteTransport(tmp_path, read_only=True))
    assert replay.read("Gross margin is expanding.") == test
    assert len(live.requests) == 1


# Off by default, chosen by the environment


def test_the_model_reader_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(wiring.READER_VARIABLE, raising=False)
    assert wiring.claim_reader_from_env() is None
    monkeypatch.setenv(wiring.READER_VARIABLE, "grammar")
    assert wiring.claim_reader_from_env() is None


def test_the_model_reader_is_chosen_by_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(wiring.READER_VARIABLE, "model")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-key")
    monkeypatch.delenv(wiring.CASSETTE_VARIABLE, raising=False)
    reader = wiring.claim_reader_from_env()
    assert isinstance(reader, ModelClaimReader)
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv(wiring.CASSETTE_VARIABLE, str(tmp_path))
    reader = wiring.claim_reader_from_env()
    assert isinstance(reader, ModelClaimReader)
    assert isinstance(reader.transport, CassetteTransport)


def test_the_model_reader_without_a_key_or_a_cassette_is_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(wiring.READER_VARIABLE, "model")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv(wiring.CASSETTE_VARIABLE, raising=False)
    with pytest.raises(wiring.ConfigurationError, match="ANTHROPIC_API_KEY"):
        wiring.claim_reader_from_env()
    monkeypatch.setenv(wiring.READER_VARIABLE, "both")
    with pytest.raises(wiring.ConfigurationError, match="grammar"):
        wiring.claim_reader_from_env()


def test_the_env_example_documents_the_reader() -> None:
    example = Path(".env.example").read_text(encoding="utf-8")
    assert f"{wiring.READER_VARIABLE}=" in example
    assert "ANTHROPIC_READER_MODEL=" in example


# The counting rule


def test_with_one_reader_a_test_counts_when_the_grammar_compiled_the_whole_sentence() -> None:
    assert policy.reading_counts("gross_margin[Q] > gross_margin[Q-4]", None)
    assert not policy.reading_counts("none", None)


def test_with_two_readers_a_test_counts_only_when_they_agree() -> None:
    same = "gross_margin[Q] > gross_margin[Q-4]"
    assert policy.reading_counts(same, same)
    assert not policy.reading_counts(same, "gross_margin[Q] > gross_margin[Q-1]")
    assert not policy.reading_counts(same, "none")
    assert not policy.reading_counts("none", same)
    assert not policy.reading_counts("none", "none")


CLAIMS = [
    "Gross margin is expanding.",
    "Revenue grew more than 200% year over year.",
    "Data center is more than 80% of revenue.",
    "Revenue grew in fiscal 2008.",
]


def _run(tmp_path: Path, reader: ModelClaimReader | None):
    request = ThesisRequest(
        ticker="NVDA", decision="Whether to keep an overweight position", claims=CLAIMS
    )
    return execute_run(
        new_run(request),
        Store(tmp_path / "record.sqlite"),
        filings=recorded_filings(),
        analyst=ScriptedAnalyst(lambda claim, passages: ClaimDraft()),
        fetch_page=FakePages({}),
        cache=FilingCache(),
        claim_reader=reader,
    )


def test_with_the_reader_off_the_run_records_the_grammar_alone(tmp_path: Path) -> None:
    run = _run(tmp_path, None)
    assert run.claim_readers == "grammar"
    margin = run.claims[0]
    assert margin.computed is not None and margin.computed.read_by == ["grammar"]
    assert margin.computed.counted_as == "supports" and margin.verdict == Verdict.supported
    assert [(r.reader, r.canonical) for r in margin.readings] == [
        ("grammar", "gross_margin[Q] > gross_margin[Q-4]")
    ]


def test_with_two_readers_a_test_counts_only_when_both_read_it_the_same(tmp_path: Path) -> None:
    margin = _compiled(CLAIMS[0])
    growth = _compiled(CLAIMS[1])
    other = _compiled("Revenue grew more than 100% year over year.")
    answers = {
        CLAIMS[0]: as_reading(margin),  # agree
        CLAIMS[1]: as_reading(other),  # differ
        CLAIMS[2]: {"computable": False, "reason": "a segment", "test": None},  # only one
        # CLAIMS[3]: the model reader fails
    }
    transport = Answers(answers)
    run = _run(tmp_path, ModelClaimReader(transport=transport))
    assert run.claim_readers == "grammar and model"
    assert "fake-reader" in run.claim_reader_detail

    agreed = run.claims[0]
    assert agreed.computed is not None and agreed.computed.read_by == ["grammar", "model"]
    assert agreed.computed.counted_as == "supports" and agreed.verdict == Verdict.supported

    differ = run.claims[1]
    assert differ.computed is not None and differ.computed.canonical == growth.canonical
    assert differ.computed.outcome == "fails" and differ.computed.counted_as == ""
    assert differ.computed.read_by == ["grammar"]
    assert "Readings differ: not counted" in differ.computed.note
    assert other.canonical in differ.computed.note
    assert differ.verdict == Verdict.not_addressed  # the findings alone: there are none
    assert [(r.reader, r.canonical) for r in differ.readings] == [
        ("grammar", growth.canonical),
        ("model", other.canonical),
    ]

    one = run.claims[2]
    assert one.computed is not None and one.computed.counted_as == ""
    assert "Readings differ: not counted" in one.computed.note
    assert one.readings[1].canonical == "none" and "a segment" in one.readings[1].reason

    failed = run.claims[3]
    assert failed.readings[1].canonical == "none"
    assert "could not read" in failed.readings[1].reason
    assert any("model reader" in error for error in run.errors)
    assert len(transport.requests) == len(CLAIMS)

    brief = render_markdown(run)
    assert "- Read by: grammar and model" in brief
    assert "Readings differ: not counted" in brief


def test_a_run_the_watch_starts_reads_its_claims_as_the_app_does(tmp_path: Path) -> None:
    from app.store import FactStore
    from app.watch.service import run_executor

    request = ThesisRequest(
        ticker="NVDA", decision="Whether to keep an overweight position", claims=CLAIMS[:1]
    )
    margin = _compiled(CLAIMS[0])
    facts = FactStore()
    execute = run_executor(
        Store(tmp_path / "record.sqlite"),
        recorded_filings(),
        ScriptedAnalyst(lambda claim, passages: ClaimDraft()),
        FilingCache(),
        fetch_page=FakePages({}),
        facts_store=facts,
        claim_reader=ModelClaimReader(transport=Answers({CLAIMS[0]: as_reading(margin)})),
    )

    run = execute(new_run(request))

    assert run.claim_readers == "grammar and model"
    assert run.claims[0].computed is not None
    assert run.claims[0].computed.read_by == ["grammar", "model"]
    assert facts.companies()
