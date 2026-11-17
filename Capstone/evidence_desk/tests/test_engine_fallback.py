"""Each engine step falls back to the deterministic engine on failure, and says so."""

import pytest

from app.core.documents import Passage
from app.core.models import Claim, Company, ThesisRequest
from app.core.ports import Analyst, ClaimDraft, SummaryDraft
from app.engines.claude import EngineError
from app.engines.fallback import FallbackAnalyst

REQUEST = ThesisRequest(
    ticker="NVDA",
    decision="Keep the position into the next earnings report",
    claims=["Data center revenue is still growing"],
)
COMPANY = Company(cik=1045810, ticker="NVDA", name="NVIDIA CORP")
CLAIM = Claim(id="c-1", text=REQUEST.claims[0])
PASSAGES = [Passage(id="p", source_id="s", locator="L", text="Revenue grew.", start=0)]


class Scripted:
    """An engine whose every step returns ``tag`` results, or raises ``error``."""

    def __init__(self, name: str, error: Exception | None = None) -> None:
        self.name = name
        self.error = error
        self.calls: list[str] = []

    def _step(self, step: str) -> None:
        self.calls.append(step)
        if self.error is not None:
            raise self.error

    def plan(self, request: ThesisRequest, company: Company) -> list[list[str]]:
        self._step("plan")
        return [[self.name]]

    def assess(
        self, request: ThesisRequest, company: Company, claim: Claim, passages: list[Passage]
    ) -> ClaimDraft:
        self._step("assess")
        return ClaimDraft(rationale=self.name)

    def summarize(
        self, request: ThesisRequest, company: Company, claims: list[Claim], findings: list
    ) -> SummaryDraft:
        self._step("summarize")
        return SummaryDraft(summary=self.name)


def run_all(engine: Analyst) -> tuple[object, object, object]:
    return (
        engine.plan(REQUEST, COMPANY),
        engine.assess(REQUEST, COMPANY, CLAIM, PASSAGES),
        engine.summarize(REQUEST, COMPANY, [CLAIM], []),
    )


def test_primary_answers_when_it_works() -> None:
    failures: list[tuple[str, Exception]] = []
    primary, fallback = Scripted("claude"), Scripted("extractive")
    engine: Analyst = FallbackAnalyst(primary, fallback, lambda s, e: failures.append((s, e)))
    plan, draft, summary = run_all(engine)
    assert plan == [["claude"]]
    assert draft.rationale == "claude" and summary.summary == "claude"
    assert failures == [] and fallback.calls == []
    assert engine.name == "claude"


@pytest.mark.parametrize(
    "error", [EngineError("model declined"), RuntimeError("boom"), KeyError("x")]
)
def test_each_failing_step_falls_back_and_is_reported(error: Exception) -> None:
    failures: list[tuple[str, Exception]] = []
    primary, fallback = Scripted("claude", error), Scripted("extractive")
    engine = FallbackAnalyst(primary, fallback, lambda s, e: failures.append((s, e)))
    plan, draft, summary = run_all(engine)
    assert plan == [["extractive"]]
    assert draft.rationale == "extractive" and summary.summary == "extractive"
    assert [step for step, _ in failures] == ["plan", "assess", "summarize"]
    assert all(exc is error for _, exc in failures)
    assert primary.calls == fallback.calls == ["plan", "assess", "summarize"]


def test_a_failing_fallback_is_not_hidden() -> None:
    engine = FallbackAnalyst(
        Scripted("claude", EngineError("a")),
        Scripted("extractive", ValueError("b")),
        lambda s, e: None,
    )
    with pytest.raises(ValueError):
        engine.plan(REQUEST, COMPANY)
