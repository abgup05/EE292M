"""The analysis of a run: two model requests through a fake transport, read, computed and audited.

The run is the NVIDIA example on the recorded filings and facts, with no finding (so every
verdict is the computed test's). The analysing model is a fake transport that answers each
step with a hand-built answer and records what it was asked: no model is called, and no
cassette is written or read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.core import analysis_policy as rules
from app.core.claim_reading import as_reading
from app.core.claimtest import ClaimTest, compile_claim
from app.core.models import Run, ThesisRequest
from app.core.ports import ClaimDraft
from app.engines.analyser import ANALYSE_SCHEMA, PROPOSE_SCHEMA, ClaudeAnalyser, parse_proposals
from app.engines.transport import EngineError, ModelRequest
from app.services.thesis_run import execute_run, new_run
from app.store import FilingCache, Store
from tests.fakes import FakePages, ScriptedAnalyst
from tests.replay_run import recorded_filings
from tests.test_reading_schema import union_parameters

CLAIMS = [
    "Gross margin is expanding.",
    "Revenue grew more than 200% year over year.",
    "Data center demand is still accelerating.",
]


def _typed(sentence: str) -> dict[str, Any]:
    test = compile_claim(sentence)
    assert isinstance(test, ClaimTest), test
    return as_reading(test)["tests"][0]


def _implication(sentence: str, expect: str, typed_from: str | None = None) -> dict[str, Any]:
    return {
        "sentence": sentence,
        "expect": expect,
        "why": "a consequence a skeptic would check",
        "test": _typed(typed_from or sentence) if typed_from != "" else {},
    }


PROPOSAL = {
    "claims": [
        {
            "claim_id": "c1",
            "implications": [
                _implication("Gross margin is above 70%.", "holds"),
                # The typed form says something else: not agreed.
                _implication(
                    "Operating margin is expanding.",
                    "holds",
                    "Revenue grew more than 50% year over year.",
                ),
                _implication("Net margin is above 40%.", "holds"),
                _implication("Net margin is above 41%.", "holds"),  # over the cap of three
            ],
        },
        {
            "claim_id": "c2",
            "implications": [
                _implication("Revenue grew more than 500% year over year.", "holds"),
                _implication("Revenue grew more than 900% year over year.", "holds"),
            ],
        },
        {
            "claim_id": "c3",
            "implications": [_implication("The moon is made of cheese &amp; rock.", "holds", "")],
        },
        {"claim_id": "c99", "implications": []},
    ]
}


def _sentence(text: str, *cites: str) -> dict[str, Any]:
    return {"text": text, "cites": list(cites)}


ARGUMENT = {
    "claims": [
        {
            "claim_id": "c1",
            "lean": "challenges",  # its verdict is supported: a flag, never a change
            "assessment": [
                _sentence(
                    "Gross margin rose 2.6 percentage points on a year earlier.",
                    "an:gross_margin:yoy",
                ),
                _sentence(
                    "Gross margin rose 9.9 percentage points on a year earlier.",
                    "an:gross_margin:yoy",
                ),
                _sentence("Something an id does not back.", "an:nope"),
                _sentence("This claim is about margins.", "c1"),
                _sentence("The test holds.", "test:c1"),
                _sentence("Its history is mixed.", "an:c1:history"),
                _sentence("A seventh sentence, over the cap.", "test:c1"),
            ],
            "case_for": [],
            "case_against": [],
            "decides": [],
            "would_change": [
                {
                    **_sentence("Gross margin below 72.4% would fail the test.", "test:c1"),
                    "measure": "gross_margin",
                    "comparison": "<",
                    "threshold": 72.4,
                    "unit": "percent",
                    "event_category": "none",
                },
                {
                    **_sentence("A bogus measure.", "test:c1"),
                    "measure": "bogus",
                    "comparison": "<",
                    "threshold": 1,
                    "unit": "percent",
                    "event_category": "none",
                },
            ],
        }
    ],
    "thesis": {
        "leans_on": ["c1", "c9"],
        "weakest_link": "c2",
        "weakest_why": [],
        "strongest_for": [],
        "strongest_against": [],
        "bottom_line": [
            _sentence(
                "Revenue grew 105.9% on a year earlier, short of the 500% a corollary asks.",
                "cor:c2:1",
            )
        ],
        "scenarios": [
            {
                "name": "Margins hold",
                "conditions": [_sentence("Gross margin stays above 70%.", "cor:c1:1")],
            }
        ],
    },
}


class FakeTransport:
    """Answers each step from ``answers`` (or raises what is given), recording each request."""

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.requests: list[ModelRequest] = []

    def __call__(self, request: ModelRequest) -> dict[str, Any]:
        self.requests.append(request)
        answer = self.answers[request.step]
        if isinstance(answer, Exception):
            raise answer
        return answer


def _run(tmp_path: Path, analyser: Any = None, name: str = "record") -> Run:
    request = ThesisRequest(
        ticker="NVDA", decision="Whether to keep an overweight position in NVIDIA", claims=CLAIMS
    )
    return execute_run(
        new_run(request),
        Store(tmp_path / f"{name}.sqlite"),
        filings=recorded_filings(),
        analyst=ScriptedAnalyst(lambda claim, passages: ClaimDraft()),
        fetch_page=FakePages({}),
        cache=FilingCache(),
        analyser=analyser,
    )


@pytest.fixture(scope="module")
def analysed(tmp_path_factory: pytest.TempPathFactory) -> tuple[Run, FakeTransport, Run]:
    scratch = tmp_path_factory.mktemp("analysis")
    transport = FakeTransport({"propose": PROPOSAL, "analyse": ARGUMENT})
    run = _run(scratch, ClaudeAnalyser(transport=transport, model="fake"), "with")
    plain = _run(scratch, None, "without")
    return run, transport, plain


def test_two_requests_and_the_second_sees_the_corollaries(analysed: Any) -> None:
    _, transport, _ = analysed
    assert [r.step for r in transport.requests] == ["propose", "analyse"]
    assert all(r.timeout == rules.MODEL_TIMEOUT_SECONDS for r in transport.requests)
    assert "cor:c2:1" not in transport.requests[0].user
    assert 'id="cor:c2:1"' in transport.requests[1].user
    assert 'id="an:gross_margin:yoy"' in transport.requests[1].user


def test_the_analysis_never_changes_a_verdict_or_the_status(analysed: Any) -> None:
    run, _, plain = analysed
    assert [c.verdict for c in run.claims] == [c.verdict for c in plain.claims]
    assert run.status == plain.status
    assert not any("analysis step failed" in e or "corollary step" in e for e in run.errors)


def test_corollaries_are_read_by_two_readers_and_computed(analysed: Any) -> None:
    run, _, _ = analysed
    c1, c2, c3 = (claim.analysis.corollaries for claim in run.claims)
    assert [c.status for c in c1] == ["agreed", "not_agreed", "agreed"]
    assert c1[1].computed is not None
    assert c1[1].computed.canonical == c1[1].proposer != c1[1].grammar
    assert c1[1].read_by == rules.READ_BY["not_agreed"]
    assert [c.result for c in c2] == ["against", "against"]
    assert c3[0].status == "not_computable" and c3[0].computed is None
    assert c3[0].sentence == "The moon is made of cheese & rock."  # unescaped on the way out
    assert run.claims[1].analysis.corollary_flag.startswith("Most of this claim's")
    assert not run.claims[0].analysis.corollary_flag
    coverage = run.coverage
    assert coverage.corollaries_proposed == 6
    assert coverage.corollaries_computed == (
        coverage.corollaries_as_expected + coverage.corollaries_against
    )
    assert coverage.corollaries_against >= 2
    note = run.analysis.corollaries_note
    assert "c99" in note and "over the cap" in note


def test_every_sentence_is_audited_and_counted(analysed: Any) -> None:
    run, _, _ = analysed
    argument = run.claims[0].analysis.argument
    assert argument is not None
    good, wrong, unknown, claim_only, holds, history = argument.assessment
    assert good.verified and not good.problems
    assert not wrong.verified
    assert wrong.problems == ["writes 9.9 percentage points, which nothing it cites carries"]
    assert not unknown.verified and any("an:nope" in p for p in unknown.problems)
    assert not claim_only.verified and claim_only.problems == ["cites nothing that is evidence"]
    assert holds.verified and history.verified
    condition = argument.would_change[0]
    assert condition.verified and condition.measure == "gross_margin"
    assert condition.threshold == 72.4
    assert argument.would_change[1].measure == ""  # not in the catalogue: cleared
    assert argument.lean_flag and run.coverage.analysis_lean_flags == 1
    thesis = run.analysis.thesis
    assert thesis is not None and thesis.leans_on == ["c1"] and thesis.weakest_link == "c2"
    assert thesis.bottom_line[0].verified, thesis.bottom_line[0].problems
    coverage = run.coverage
    assert coverage.analysis_sentences_cut == 1
    assert coverage.analysis_sentences_written == 6 + 2 + 1 + 1
    assert coverage.analysis_sentences_written == (
        coverage.analysis_sentences_verified + coverage.analysis_sentences_unverified
    )
    assert coverage.analysis_unverified_number == 1
    assert coverage.analysis_unverified_unknown_id == 1
    assert coverage.analysis_unverified_no_evidence == 2
    assert run.analysis.argument_by == "model"
    assert run.analysis.flags and any(flag.startswith("c1:") for flag in run.analysis.flags)


def test_relevance_headline_and_analytics_without_a_model(analysed: Any) -> None:
    _, _, plain = analysed
    analysis = plain.analysis
    assert analysis is not None and analysis.argument_by == "none"
    assert rules.NO_MODEL_WHY in analysis.argument_note
    keys = [[m.key for m in c.analysis.relevant] for c in plain.claims]
    assert keys[0] == ["gross_margin"] and keys[1] == ["revenue"]
    assert keys[2] == [] and plain.claims[2].analysis.relevance_note == rules.NO_MEASURE
    assert analysis.headline and analysis.headline[0].claim_ids == ["c1"]
    assert all(item.reading_origin == "code" for item in analysis.analytics)
    assert plain.coverage.analytics_computed == sum(1 for a in analysis.analytics if a.available)
    assert plain.coverage.corollaries_proposed == 0
    assert plain.coverage.analysis_sentences_written == 0
    assert "an:c2:needed" in plain.claims[1].analysis.analytic_ids


def test_a_failed_request_is_one_error_line_and_the_counts_say_0_of_0(tmp_path: Path) -> None:
    failing = FakeTransport(
        {"propose": EngineError("Model request failed: APIError"), "analyse": ARGUMENT}
    )
    run = _run(tmp_path, ClaudeAnalyser(transport=failing, model="fake"))
    assert [e for e in run.errors if "corollary step failed" in e]
    assert run.coverage.corollaries_proposed == 0 and run.coverage.corollaries_computed == 0
    # The argument still came, and its counts hold; a corollary it cites is not in the run.
    assert run.analysis.argument_by == "model"
    bottom = run.analysis.thesis.bottom_line[0]
    assert not bottom.verified and any("cor:c2:1" in p for p in bottom.problems)
    both = FakeTransport({"propose": EngineError("down"), "analyse": EngineError("down")})
    second = _run(tmp_path, ClaudeAnalyser(transport=both, model="fake"), "both")
    assert sum("analysis step failed" in e for e in second.errors) == 1
    assert second.analysis.argument_by == "none"
    assert "the request failed" in second.analysis.argument_note
    assert second.coverage.analysis_sentences_written == 0
    assert second.status == run.status
    assert second.analysis.analytics, "the computed analysis stays"


def test_the_schemas_have_no_union_typed_parameter() -> None:
    assert union_parameters(PROPOSE_SCHEMA) == 0
    assert union_parameters(ANALYSE_SCHEMA) == 0


def test_a_proposal_for_an_unknown_claim_or_with_no_outcome_is_dropped() -> None:
    answer = {
        "claims": [
            {
                "claim_id": "c1",
                "implications": [
                    {
                        "sentence": "R&amp;D as a share of revenue is above 5%.",
                        "expect": "holds",
                        "why": "",
                        "test": {},
                    },
                    {"sentence": "", "expect": "holds", "why": "", "test": {}},
                ],
            }
        ]
    }
    parsed = parse_proposals(answer, ["c1", "c2"])
    assert [i.sentence for i in parsed.implications] == ["R&D as a share of revenue is above 5%."]
    assert any("no sentence" in p for p in parsed.problems)
    assert any("c2" in p for p in parsed.problems)
    with pytest.raises(EngineError):
        parse_proposals({"claims": "no"}, ["c1"])
