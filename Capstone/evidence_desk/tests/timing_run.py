"""Time a run's stages with stand-ins that wait as model requests do (``make time-analysis``).

No model, no EDGAR: the recorded NVIDIA filings and facts, five claims, an engine, two claim
readers, a meaning checker and an analysing model that each sleep for a set time and then
answer with something well-formed, and the two outside providers answering at once (as from
the reference pack). It prints the run's own ``timings`` and its length, and beside it what
the same requests cost in the order the run made them before the claim readers, the
providers and the corollary proposals were moved off the critical path.

The delays are assumptions, not measurements of a model: they were chosen so that the old
order adds up to about the 218 seconds of the one live run on record (Costco, four claims,
three readers, 18 November 2026). ``SCALE`` multiplies them all (0.1 for a quick look).
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.core.analysis_models import Analytic
from app.core.analytics import AnalyticsRequest, FactsProvider
from app.core.claimtest import ClaimTest, NotNumeric, compile_claim
from app.core.models import Run, ThesisRequest
from app.core.ports import ClaimDraft
from app.engines.analyser import ClaudeAnalyser
from app.engines.transport import ModelRequest
from app.services.thesis_run import execute_run, new_run
from app.store import FilingCache, Store
from tests.examples_analysis import CLAIMS, DECISION
from tests.fakes import FakePages, ScriptedAnalyst, ScriptedChecker, scripted_argument
from tests.replay_run import recorded_filings

# Seconds one request of each kind is taken to need (see the module docstring).
DELAYS = {
    "read": 3.0,
    "plan": 4.0,
    "assess": 17.0,
    "check": 5.0,
    "summarize": 8.0,
    "propose": 25.0,
    "analyse": 22.0,
    "conclude": 35.0,
    "edgar": 8.0,
}
OLD_PROVIDER_TIMEOUTS = 20.0 + 15.0
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


class _Reader:
    detail = "a stand-in that waits"

    def __init__(self, name: str, wait: float) -> None:
        self.name, self._wait = name, wait

    def read(self, claim: str) -> ClaimTest | NotNumeric:
        time.sleep(self._wait)
        return compile_claim(claim)


class _Engine(ScriptedAnalyst):
    def __init__(self, delays: dict[str, float]) -> None:
        super().__init__(
            lambda claim, passages: ClaimDraft(),
            before_assess=lambda: time.sleep(delays["assess"]),
        )
        self._delays = delays

    def plan(self, *args: Any, **kwargs: Any) -> Any:
        time.sleep(self._delays["plan"])
        return super().plan(*args, **kwargs)

    def summarize(self, *args: Any, **kwargs: Any) -> Any:
        time.sleep(self._delays["summarize"])
        return super().summarize(*args, **kwargs)


class _Checker(ScriptedChecker):
    def __init__(self, wait: float) -> None:
        super().__init__()
        self._wait = wait

    def check(self, *args: Any, **kwargs: Any) -> Any:
        time.sleep(self._wait)
        return super().check(*args, **kwargs)


class _Transport:
    detail = "a stand-in that waits"

    def __init__(self, delays: dict[str, float]) -> None:
        self._delays = delays

    def __call__(self, request: ModelRequest) -> dict[str, Any]:
        time.sleep(self._delays[request.step])
        if request.step == "propose":
            return {"claims": []}
        return scripted_argument(EMPTY, request)


class _Instant:
    budget_seconds = 15.0

    def __init__(self, name: str) -> None:
        self.name = name

    def provide(self, request: AnalyticsRequest) -> list[Analytic]:
        return []


def timed(scale: float, data_dir: Path) -> Run:
    """One run with every request waiting ``scale`` times its delay."""
    delays = {key: value * scale for key, value in DELAYS.items()}
    filings = recorded_filings()
    began = time.sleep(delays["edgar"])  # the filings and facts arrive from EDGAR
    del began
    request = ThesisRequest(ticker="NVDA", decision=DECISION, claims=CLAIMS)
    return execute_run(
        new_run(request),
        Store(data_dir / "timed.sqlite"),
        filings=filings,
        analyst=_Engine(delays),
        fetch_page=FakePages({}),
        cache=FilingCache(),
        checker=_Checker(delays["check"]),
        claim_reader=(_Reader("model", delays["read"]), _Reader("model_2", delays["read"])),
        analyser=ClaudeAnalyser(transport=_Transport(delays), model="stand-in"),
        analytics_providers=(FactsProvider(), _Instant("outside_view"), _Instant("market_view")),
    )


def before(claims: int, readers: int = 2) -> float:
    """What the same requests cost in the order of the run of 18 November 2026: the readers
    one after another, both providers waited for until their budgets ran out on a cold
    cache, the proposals after the summary, the claims argued three at once."""
    rounds = -(-claims // 3)
    return (
        DELAYS["edgar"]
        + claims * readers * DELAYS["read"]
        + DELAYS["plan"]
        + rounds * (DELAYS["assess"] + DELAYS["check"])
        + DELAYS["summarize"]
        + OLD_PROVIDER_TIMEOUTS
        + DELAYS["propose"]
        + rounds * DELAYS["analyse"]
        + DELAYS["conclude"]
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run once and print the timings beside the old order's arithmetic."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--scale", type=float, default=1.0)
    args = parser.parse_args(argv)
    began = time.monotonic()
    with tempfile.TemporaryDirectory() as scratch:
        run = timed(args.scale, Path(scratch))
    length = (time.monotonic() - began) / args.scale
    print(f"time-analysis: {len(CLAIMS)} claims, 2 model readers, delays x{args.scale:g}")
    for item in run.timings:
        where = " (in the background)" if item.background else ""
        note = f" [{item.note}]" if item.note else ""
        print(f"  {item.seconds / args.scale:7.1f} s  {item.stage}{where}{note}")
    print(f"  {length:7.1f} s  the whole run, with {DELAYS['edgar']:g} s for EDGAR, at full scale")
    print(f"  {before(len(CLAIMS)):7.1f} s  the same requests in the old order (arithmetic)")
    print(f"  {before(4):7.1f} s  the old order for four claims (the live run took 218 s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
