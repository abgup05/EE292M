"""The analysis of a run: two model requests through a fake transport, read, computed and audited.

The run is the NVIDIA example on the recorded filings and facts, with no finding (so every
verdict is the computed test's). The analysing model is a fake transport that answers each
step with a hand-built answer and records what it was asked: no model is called, and no
cassette is written or read.
"""

from __future__ import annotations

import threading
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app.core import analysis_policy as rules
from app.core.claim_reading import as_reading
from app.core.claimtest import ClaimTest, compile_claim
from app.core.models import Confidence, Run, Stance, ThesisRequest
from app.core.ports import ClaimDraft, FindingDraft, Quote
from app.engines.analyser import (
    CLAIM_SCHEMA,
    PROPOSE_SCHEMA,
    THESIS_SCHEMA,
    ClaudeAnalyser,
    parse_proposals,
)
from app.engines.cassette import CassetteTransport
from app.engines.transport import EngineError, ModelRequest
from app.services.thesis_run import execute_run, new_run
from app.store import FilingCache, Store
from tests.fakes import FakePages, ScriptedAnalyst, focus_of, scripted_argument
from tests.replay_run import recorded_filings
from tests.test_reading_schema import union_parameters

CLAIMS = [
    "Gross margin is expanding.",
    "Revenue grew more than 200% year over year.",
    "Data center demand is still accelerating.",
    "Management is excellent.",
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
        self.lock = threading.Lock()

    def __call__(self, request: ModelRequest) -> dict[str, Any]:
        with self.lock:
            self.requests.append(request)
        # One scripted argument, written nested as the record holds it, answers every
        # per-claim request and the thesis's; "analyse:c2" scripts one claim's request apart.
        step = "analyse" if request.step == "conclude" else request.step
        own = f"analyse:{focus_of(request)}" if request.step == "analyse" else ""
        answer = self.answers.get(own, self.answers[step])
        if isinstance(answer, Exception):
            raise answer
        return scripted_argument(answer, request) if step == "analyse" else answer

    def about(self, claim_id: str) -> ModelRequest:
        """The per-claim request about ``claim_id``."""
        return next(r for r in self.requests if r.step == "analyse" and focus_of(r) == claim_id)

    def thesis(self) -> ModelRequest:
        """The thesis's request."""
        return next(r for r in self.requests if r.step == "conclude")


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


def test_one_request_per_claim_then_one_for_the_thesis(analysed: Any) -> None:
    run, transport, _ = analysed
    steps = [r.step for r in transport.requests]
    assert steps[0] == "propose" and steps[-1] == "conclude"
    assert sorted(steps[1:-1]) == ["analyse"] * len(CLAIMS)
    assert sorted(focus_of(r) for r in transport.requests[1:-1]) == ["c1", "c2", "c3", "c4"]
    for request in transport.requests[1:]:
        assert request.timeout == rules.ANALYSE_TIMEOUT_SECONDS
        assert request.max_tokens == rules.ANALYSE_MAX_TOKENS
    assert "cor:c2:1" not in transport.requests[0].user
    # A claim's request holds that claim's material and the other claims' text only.
    c2, c1 = transport.about("c2"), transport.about("c1")
    assert 'id="cor:c2:1"' in c2.user and 'id="cor:c2:1"' not in c1.user
    assert 'id="an:gross_margin:yoy"' in c1.user and 'id="an:gross_margin:yoy"' not in c2.user
    assert "Gross margin is expanding." in c2.user
    # The thesis's request holds everything, and each claim's audited argument.
    thesis = transport.thesis().user
    assert 'id="cor:c2:1"' in thesis and 'id="an:gross_margin:yoy"' in thesis
    assert '<argument claim="c1">Lean: challenges.' in thesis
    assert "9.9 percentage points on a year earlier. [UNVERIFIED: writes 9.9" in thesis
    assert "The model reads the evidence as challenges, but the verdict is supported" in thesis
    analysis = run.analysis
    assert (analysis.argument_step, analysis.thesis_step) == ("answered", "answered")
    assert analysis.argument_claims_asked == analysis.argument_claims_answered == len(CLAIMS)
    assert run.coverage.analysis_claims_answered == len(CLAIMS)
    assert run.coverage.analysis_thesis_answered == 1


def test_the_analysis_never_changes_a_verdict_or_the_status(analysed: Any) -> None:
    run, _, plain = analysed
    assert [c.verdict for c in run.claims] == [c.verdict for c in plain.claims]
    assert run.status == plain.status
    assert not any("analysis" in e for e in run.errors)
    # Without a model the record says so once, as an error line; the status is unmoved.
    assert [e for e in plain.errors if "analysis" in e] == [
        rules.COMPUTED_ONLY_ERROR.format(why=rules.NO_MODEL_WHY)
    ]
    assert plain.analysis.corollaries_step == plain.analysis.argument_step == "not_asked"
    assert run.analysis.corollaries_step == run.analysis.argument_step == "answered"


def test_corollaries_are_read_by_two_readers_and_computed(analysed: Any) -> None:
    run, _, _ = analysed
    c1, c2, c3, _ = (claim.analysis.corollaries for claim in run.claims)
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
    # Every proposed corollary is in exactly one count; the one not agreed counts toward
    # neither outcome, though it was computed and came out as expected.
    assert (coverage.corollaries_not_agreed, coverage.corollaries_no_test) == (1, 1)
    assert c1[1].result == "as_expected"
    assert coverage.corollaries_proposed == (
        coverage.corollaries_as_expected
        + coverage.corollaries_against
        + coverage.corollaries_cannot_tell
        + coverage.corollaries_no_test
        + coverage.corollaries_not_agreed
    )
    assert coverage.corollary_flags == 1
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
    # The part a claim names is read from the tags of the filings the run read, though no
    # computed test asked for them.
    assert keys[2] == ['revenue(segment "Data Center")', "revenue"]
    assert "10-Q filed" in analysis.breakdowns_note and "10-K filed" in analysis.breakdowns_note
    ids = plain.claims[2].analysis.analytic_ids
    assert "an:part:data_center:fy:pace" in ids and "an:revenue:acceleration" in ids
    assert keys[3] == [] and plain.claims[3].analysis.relevance_note == rules.NO_MEASURE
    assert plain.claims[3].analysis.analytic_ids == []
    assert analysis.headline and analysis.headline[0].claim_ids == ["c1"]
    assert analysis.headline[0].source == "computed_test"
    assert all(item.reading_origin == "code" for item in analysis.analytics)
    assert all(item.claim_ids and item.question for item in analysis.analytics)
    assert plain.coverage.analytics_computed == sum(1 for a in analysis.analytics if a.available)
    assert plain.coverage.analytics_computed + plain.coverage.analytics_unavailable == len(
        analysis.analytics
    )
    assert plain.coverage.corollaries_proposed == 0
    assert plain.coverage.analysis_sentences_written == 0
    assert "an:c2:needed" in plain.claims[1].analysis.analytic_ids


def _analysis_errors(run: Run) -> list[str]:
    return [e for e in run.errors if "analysis" in e]


def test_a_failed_request_is_one_error_line_and_the_record_says_which_step(
    tmp_path: Path,
) -> None:
    failing = FakeTransport(
        {"propose": EngineError("Model request failed: APIError"), "analyse": ARGUMENT}
    )
    run = _run(tmp_path, ClaudeAnalyser(transport=failing, model="fake"))
    assert len(_analysis_errors(run)) == 1 and "the corollaries" in _analysis_errors(run)[0]
    assert run.analysis.corollaries_step == "failed" and run.analysis.argument_step == "answered"
    assert "corollaries" in run.analysis.corollaries_note
    assert run.coverage.corollaries_proposed == 0 and run.coverage.corollaries_computed == 0
    # The argument still came, and its counts hold; a corollary it cites is not in the run.
    assert run.analysis.argument_by == "model"
    bottom = run.analysis.thesis.bottom_line[0]
    assert not bottom.verified and any("cor:c2:1" in p for p in bottom.problems)
    both = FakeTransport({"propose": EngineError("down"), "analyse": EngineError("down")})
    second = _run(tmp_path, ClaudeAnalyser(transport=both, model="fake"), "both")
    assert len(_analysis_errors(second)) == 1
    assert "the corollaries" in _analysis_errors(second)[0]
    assert "the argument about c1" in _analysis_errors(second)[0]
    assert "the argument about the thesis" in _analysis_errors(second)[0]
    assert second.analysis.argument_by == "none" and second.analysis.argument_step == "failed"
    assert second.analysis.thesis_step == "failed"
    assert (second.analysis.argument_claims_asked, second.analysis.argument_claims_answered) == (
        len(CLAIMS),
        0,
    )
    assert "every request failed" in second.analysis.argument_note
    assert all("the request failed (down)" in c.analysis.argument_note for c in second.claims)
    assert second.coverage.analysis_sentences_written == 0
    assert second.status == run.status
    assert second.analysis.analytics, "the computed analysis stays"
    assert [c.verdict for c in second.claims] == [c.verdict for c in run.claims]


def test_a_claim_whose_request_fails_has_no_argument_and_the_others_stand(
    tmp_path: Path,
) -> None:
    transport = FakeTransport(
        {"propose": PROPOSAL, "analyse": ARGUMENT, "analyse:c2": EngineError("timed out")}
    )
    run = _run(tmp_path, ClaudeAnalyser(transport=transport, model="fake"))
    analysis = run.analysis
    assert (analysis.argument_step, analysis.thesis_step) == ("partial", "answered")
    assert (analysis.argument_claims_asked, analysis.argument_claims_answered) == (4, 3)
    assert analysis.argument_by == "model"
    assert "A model argued 3 of 4 claim(s); the thesis's argument: answered" in (
        analysis.argument_note
    )
    c1, c2 = run.claims[0].analysis, run.claims[1].analysis
    assert c1.argument is not None and c1.argument_note == ""
    assert c2.argument is None
    assert c2.argument_note == "No model's argument for this claim: the request failed (timed out)."
    # The thesis was argued on what there was, and told which claim has no argument.
    assert analysis.thesis is not None and analysis.thesis.bottom_line
    assert '<argument claim="c2">No model\'s argument for this claim' in transport.thesis().user
    assert (
        len(_analysis_errors(run)) == 1
        and "the argument about c2: timed out" in (_analysis_errors(run)[0])
    )
    coverage = run.coverage
    assert (coverage.analysis_claims_asked, coverage.analysis_claims_answered) == (4, 3)
    assert coverage.analysis_sentences_written == (
        coverage.analysis_sentences_verified + coverage.analysis_sentences_unverified
    )

    # The thesis's request failing leaves the claims' arguments standing.
    class NoThesis(FakeTransport):
        def __call__(self, request: ModelRequest) -> dict[str, Any]:
            if request.step == "conclude":
                with self.lock:
                    self.requests.append(request)
                raise EngineError("The model response was truncated")
            return super().__call__(request)

    second = _run(
        tmp_path,
        ClaudeAnalyser(
            transport=NoThesis({"propose": PROPOSAL, "analyse": ARGUMENT}), model="fake"
        ),
        "nothesis",
    )
    assert (second.analysis.argument_step, second.analysis.thesis_step) == ("partial", "failed")
    assert second.analysis.thesis is None and second.claims[0].analysis.argument is not None
    assert "the thesis's argument: the request failed (The model response was truncated)" in (
        second.analysis.argument_note
    )
    assert second.status == run.status


def test_a_cassette_without_the_answers_leaves_the_computed_analysis(tmp_path: Path) -> None:
    empty = tmp_path / "cassette"
    empty.mkdir()
    replaying = ClaudeAnalyser(transport=CassetteTransport(empty, read_only=True), model="fake")
    run = _run(tmp_path, replaying)
    assert len(_analysis_errors(run)) == 1
    assert run.analysis.corollaries_step == run.analysis.argument_step == "failed"
    assert run.analysis.argument_by == "none" and run.analysis.analytics
    assert not (empty / "pending").exists(), "a read-only cassette saves no pending request"


def test_a_withheld_finding_may_not_be_cited(tmp_path: Path) -> None:
    def draft(claim: Any, passages: Any) -> ClaimDraft:
        # A finding whose quote is in no passage: the gate withholds it.
        return ClaimDraft(
            findings=[
                FindingDraft(
                    statement="Gross margin widened.",
                    stance=Stance.supports,
                    confidence=Confidence.high,
                    rationale="made up",
                    quotes=[Quote(passage_id=passages[0].id, text="no filing says this")],
                )
            ]
            if passages and claim.id == "c1"
            else []
        )

    base = execute_run(
        new_run(ThesisRequest(ticker="NVDA", decision="Whether to hold NVIDIA", claims=CLAIMS[:1])),
        Store(tmp_path / "base.sqlite"),
        filings=recorded_filings(),
        analyst=ScriptedAnalyst(draft),
        fetch_page=FakePages({}),
        cache=FilingCache(),
    )
    assert base.unsupported_findings, "the scripted finding should have been withheld"
    withheld = base.unsupported_findings[0].id
    argument = {
        "claims": [
            {
                "claim_id": "c1",
                "lean": "supports",
                "assessment": [_sentence("A finding says the margin widened.", withheld)],
                "case_for": [],
                "case_against": [],
                "decides": [],
                "would_change": [],
            }
        ],
        "thesis": {**ARGUMENT["thesis"], "bottom_line": [], "scenarios": []},
    }
    transport = FakeTransport({"propose": {"claims": []}, "analyse": argument})
    run = execute_run(
        new_run(ThesisRequest(ticker="NVDA", decision="Whether to hold NVIDIA", claims=CLAIMS[:1])),
        Store(tmp_path / "cited.sqlite"),
        filings=recorded_filings(),
        analyst=ScriptedAnalyst(draft),
        fetch_page=FakePages({}),
        cache=FilingCache(),
        analyser=ClaudeAnalyser(transport=transport, model="fake"),
    )
    sentence = run.claims[0].analysis.argument.assessment[0]
    assert not sentence.verified
    assert f"cites {withheld}, a finding the run withheld" in sentence.problems
    assert run.coverage.analysis_unverified_disallowed_id == 1
    shown = " ".join(r.user for r in transport.requests[1:])
    assert f'<finding id="{withheld}"' not in shown, "a withheld finding is never shown"


def test_as_of_a_date_the_analysis_reads_nothing_filed_later(tmp_path: Path) -> None:
    as_of = date(2026, 6, 15)
    request = ThesisRequest(
        ticker="NVDA", decision="Whether to hold NVIDIA", claims=CLAIMS, as_of=as_of
    )
    transport = FakeTransport({"propose": PROPOSAL, "analyse": ARGUMENT})
    run = execute_run(
        new_run(request),
        Store(tmp_path / "asof.sqlite"),
        filings=recorded_filings(),
        analyst=ScriptedAnalyst(lambda claim, passages: ClaimDraft()),
        fetch_page=FakePages({}),
        cache=FilingCache(),
        analyser=ClaudeAnalyser(transport=transport, model="fake"),
    )
    analytics = run.analysis.analytics
    filed = [i.filed for item in analytics for i in item.inputs if i.filed]
    assert filed and max(filed) <= as_of.isoformat()
    assert sum(item.available for item in analytics) >= 5
    # The newest quarter the run may know is Q1 FY2027 (10-Q filed 2026-05-20), not Q2.
    text = " ".join(item.reading + item.period for item in analytics)
    assert "Q1 FY2027" in text and "Q2 FY2027" not in text and "2026-07-26" not in text
    assert "2026-08-26" not in run.analysis.breakdowns_note
    for claim in run.claims:
        for corollary in claim.analysis.corollaries:
            if corollary.computed is not None:
                assert "Q2 FY2027" not in corollary.computed.bound
                assert all(p.filed <= as_of.isoformat() for p in corollary.computed.history)
    shown = " ".join(r.user for r in transport.requests)
    assert "Q2 FY2027" not in shown and "2026-07-26" not in shown
    assert all("<as_of>2026-06-15</as_of>" in r.user for r in transport.requests[1:])


def test_the_schemas_have_no_union_typed_parameter() -> None:
    assert union_parameters(PROPOSE_SCHEMA) == 0
    assert union_parameters(CLAIM_SCHEMA) == 0
    assert union_parameters(THESIS_SCHEMA) == 0


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


def test_a_second_run_reads_the_parts_from_the_cache_and_fetches_nothing(tmp_path: Path) -> None:
    filings = recorded_filings()
    cache = FilingCache(tmp_path / "cache.sqlite")

    def run_once(name: str) -> Run:
        request = ThesisRequest(ticker="NVDA", decision="Whether to hold NVIDIA", claims=CLAIMS)
        return execute_run(
            new_run(request),
            Store(tmp_path / f"{name}.sqlite"),
            filings=filings,
            analyst=ScriptedAnalyst(lambda claim, passages: ClaimDraft()),
            fetch_page=FakePages({}),
            cache=cache,
        )

    first = run_once("first")
    fetched = list(filings.fetched)
    second = run_once("second")
    assert filings.fetched == fetched, "the second run fetched a filing again"
    assert first.analysis.breakdowns_note == second.analysis.breakdowns_note
    assert "an:part:data_center:fy:pace" in second.claims[2].analysis.analytic_ids
    assert [a.model_dump() for a in first.analysis.analytics] == [
        a.model_dump() for a in second.analysis.analytics
    ]
    # A cache that kept the filings' text but not their tags (one filled before this version):
    # no fetch for the tags, no part, and the record says why.
    with cache._db.transaction(durable=False) as connection:  # noqa: SLF001 - the test's setup
        connection.execute("DELETE FROM tagged")
    third = run_once("third")
    assert filings.fetched == fetched
    assert "No part of the business could be read" in third.analysis.breakdowns_note
    assert [m.key for m in third.claims[2].analysis.relevant] == []
