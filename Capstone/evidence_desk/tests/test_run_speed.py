"""What a run does at once instead of in turn, and the timings it records.

Stand-ins wait as a request would; nothing is sent anywhere.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from app.core import analysis_policy as rules
from app.core.analysis_models import Analytic
from app.core.analytics import AnalyticsRequest, FactsProvider
from app.core.claimtest import ClaimTest, NotNumeric, compile_claim
from app.core.models import Run, ThesisRequest
from app.core.ports import ClaimDraft
from app.engines.analyser import ClaudeAnalyser
from app.engines.transport import EngineError, ModelRequest
from app.services.thesis_run import execute_run, new_run
from app.store import FilingCache, Store
from tests.fakes import FakePages, ScriptedAnalyst, scripted_argument
from tests.replay_run import recorded_filings

CLAIMS = [
    "Gross margin is expanding.",
    "Revenue grew more than 200% year over year.",
    "Operating margin is above 60%.",
    "Net margin is above 40%.",
    "Management is excellent.",
]
EMPTY = {
    "claims": [],
    "thesis": {
        "leans_on": [],
        "weakest_link": "",
        "weakest_why": [],
        "strongest_for": [],
        "strongest_against": [],
        "bottom_line": [],
        "scenarios": [],
    },
}


class SlowReader:
    """A claim reader that waits, counts how many reads overlap, and may fail one claim."""

    detail = "a stand-in"

    def __init__(self, name: str, wait: float, fail: str = "") -> None:
        self.name, self._wait, self._fail = name, wait, fail
        self._lock = threading.Lock()
        self._running = 0
        self.peak = 0

    def read(self, claim: str) -> ClaimTest | NotNumeric:
        with self._lock:
            self._running += 1
            self.peak = max(self.peak, self._running)
        time.sleep(self._wait)
        with self._lock:
            self._running -= 1
        if claim == self._fail:
            raise EngineError("the reader did not answer")
        return compile_claim(claim)


class Stamped:
    """Notes when each thing began, by one clock, so their order can be checked."""

    def __init__(self) -> None:
        self.at: dict[str, float] = {}
        self._lock = threading.Lock()

    def note(self, name: str) -> None:
        with self._lock:
            self.at.setdefault(name, time.monotonic())


class SlowProvider:
    name = "slow_view"
    budget_seconds = 10.0

    def __init__(self, stamps: Stamped, wait: float) -> None:
        self._stamps, self._wait = stamps, wait

    def provide(self, request: AnalyticsRequest) -> list[Analytic]:
        self._stamps.note("provider")
        time.sleep(self._wait)
        return [
            Analytic(
                id="an:slow", kind="x", label="late but in time", question="?", scope="company"
            )
        ]


class Transport:
    detail = "a stand-in"

    def __init__(self, stamps: Stamped, wait: float) -> None:
        self._stamps, self._wait = stamps, wait
        self.requests: list[ModelRequest] = []
        self._lock = threading.Lock()

    def __call__(self, request: ModelRequest) -> dict[str, Any]:
        self._stamps.note(request.step)
        with self._lock:
            self.requests.append(request)
        time.sleep(self._wait)
        if request.step == "propose":
            return {"claims": []}
        return scripted_argument(EMPTY, request)


def _run(tmp_path: Path, name: str = "run", **more: Any) -> Run:
    request = ThesisRequest(ticker="NVDA", decision="Whether to hold NVIDIA", claims=CLAIMS)
    return execute_run(
        new_run(request),
        Store(tmp_path / f"{name}.sqlite"),
        filings=recorded_filings(),
        fetch_page=FakePages({}),
        cache=FilingCache(),
        **{"analyst": ScriptedAnalyst(lambda claim, passages: ClaimDraft()), **more},
    )


def test_the_claim_readers_are_asked_at_once_and_recorded_in_order(tmp_path: Path) -> None:
    first, second = SlowReader("model", 0.3), SlowReader("model_2", 0.3, fail=CLAIMS[1])
    began = time.monotonic()
    run = _run(tmp_path, claim_reader=(first, second))
    reading = next(t.seconds for t in run.timings if t.stage == "computed tests and claim readers")
    # Ten reads of 0.3 s: 3 s in turn; six at once they are two rounds.
    assert first.peak + second.peak > 2
    assert reading < 2.0, reading
    assert time.monotonic() - began < 30
    for claim in run.claims:
        assert [r.reader for r in claim.readings] == ["grammar", "model", "model_2"]
    assert run.claims[0].readings[1].canonical == run.claims[0].readings[0].canonical
    failed = run.claims[1].readings[2]
    assert failed.canonical == "none" and "did not answer" in failed.reason
    assert sum("did not answer" in error for error in run.errors) == 1


def test_the_providers_and_the_proposals_start_before_the_claims_are_assessed(
    tmp_path: Path,
) -> None:
    stamps = Stamped()
    engine = ScriptedAnalyst(
        lambda claim, passages: ClaimDraft(),
        before_assess=lambda: (stamps.note("assess"), time.sleep(0.4)),
    )
    transport = Transport(stamps, 0.3)
    run = _run(
        tmp_path,
        analyst=engine,
        analyser=ClaudeAnalyser(transport=transport, model="stand-in"),
        analytics_providers=(FactsProvider(), SlowProvider(stamps, 0.6)),
    )
    at = stamps.at
    assert at["provider"] < at["assess"] and at["propose"] < at["assess"]
    assert at["assess"] < at["analyse"] < at["conclude"]
    # The proposer is asked before any verdict exists, and is shown none.
    proposal = next(r for r in transport.requests if r.step == "propose")
    assert "verdict=" not in proposal.user and '<claim id="c1">' in proposal.user
    # The provider took 0.6 s beside the assessments and the run did not wait for it again.
    analysis = run.analysis
    assert analysis.providers_failed == [] and "an:slow" in {a.id for a in analysis.analytics}
    assert analysis.corollaries_step == "answered" and analysis.argument_step == "answered"
    timings = {t.stage: t for t in run.timings}
    assert timings["analytics: slow_view"].background
    assert timings["corollaries: proposed by the model"].background
    assert timings["analytics: slow_view"].seconds >= 0.5
    waited = timings["analysis (all of it)"].seconds
    assert waited < 0.3 + 0.3 + 0.6, waited  # the claims at once, the thesis; not the provider


def test_a_run_records_how_long_each_stage_took(tmp_path: Path) -> None:
    run = _run(tmp_path)
    stages = [t.stage for t in run.timings if not t.background]
    for stage in (
        "filings",
        "numbers",
        "computed tests and claim readers",
        "planning",
        "assessing",
        "summary",
        "analysis (all of it)",
    ):
        assert stage in stages, stage
    assert stages.index("filings") < stages.index("assessing") < stages.index("summary")
    assert all(t.seconds >= 0 for t in run.timings)
    # The stages that are not parts of another add up to no more than the run took.
    whole = [t.seconds for t in run.timings if not t.background and not t.note]
    assert sum(whole) <= (run.finished_at - run.started_at).total_seconds() + 0.5
    assert rules.MAX_CONCURRENT_READS >= 2 and rules.MAX_CONCURRENT_ARGUMENTS >= 2
