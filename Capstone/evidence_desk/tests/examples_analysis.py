"""Write the analysis examples to docs/examples/analysis (``make examples-analysis``).

Offline, from the recorded NVIDIA filings and facts; no model is called and no EDGAR request
is made. The claims are those of the live NVIDIA run the page samples
(``src/web/sample-run-live.json``). Files, each exactly what ``GET /api/runs/{id}`` (or its
Markdown export) serves:

- ``run.json`` and ``brief.md``: the extractive engine and no analysing model, so the
  record carries the analysis code computes (relevance, headline, analytics, odds) and says
  no model wrote an argument;
- ``run-hand-built-argument.json``: the same run with the corollaries and the argument
  answered by a fake transport whose answers are BUILT HERE BY CODE from the run's own
  analytics (one sentence per claim, citing an analytic; one corollary per compiled claim,
  its own test). No model wrote them: the file shows the shape a model's answers take on the
  record (``argument_detail`` says so), never what a model would say;
- ``replayed-run.json``: the example thesis replayed from the cassette
  ``demo/cassettes/nvda-example``, with the analysis model's two answers when the cassette
  holds them. Written only then (and removed when stale); otherwise ``make
  examples-analysis`` says how to record them (``make record-analysis``).

Clock times are fixed at :data:`STAMP` so the files change only when a shape or a result
does.
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.claim_reading import as_reading
from app.core.claimtest import ClaimTest, compile_claim
from app.core.models import Run, ThesisRequest
from app.engines.analyser import ClaudeAnalyser
from app.engines.extractive import ExtractiveAnalyst
from app.engines.transport import ModelRequest
from app.services.export import render_markdown
from app.services.thesis_run import execute_run, new_run
from app.store import FilingCache, Store
from tests.fakes import FakePages, ManualClock
from tests.golden_run import replay_copy
from tests.replay_run import DEFAULT_CASSETTE, recorded_filings

OUT = Path("docs/examples/analysis")
FILES = ("run.json", "brief.md", "run-hand-built-argument.json")
REPLAYED = "replayed-run.json"
STAMP = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
CLOCK_FIELDS = ("finished_at", "retrieved_at", "started_at", "recorded_at")
DECISION = "Whether to buy NVIDIA now"
CLAIMS = [
    "Buy NVDA because Jensen is gone",
    "Gross margin has stayed above 70% for the last four quarters",
    "Revenue more than doubled in fiscal 2026",
    "Free cash flow was above net income last fiscal year",
    "Data center demand is still accelerating",
]
HAND_BUILT = "hand-built answers made by tests/examples_analysis.py from the run's analytics (no model)"


class HandBuilt:
    """A fake transport: answers built by code from a run without a model (see the docstring)."""

    detail = HAND_BUILT

    def __init__(self, base: Run) -> None:
        self.base = base

    def __call__(self, request: ModelRequest) -> dict[str, Any]:
        """The propose or analyse answer for the base run's claims."""
        if request.step == "propose":
            return {"claims": [self._proposal(claim.id, claim.text) for claim in self.base.claims]}
        return self._argument()

    @staticmethod
    def _proposal(claim_id: str, text: str) -> dict[str, Any]:
        test = compile_claim(text)
        if not isinstance(test, ClaimTest):
            return {"claim_id": claim_id, "implications": []}
        typed = as_reading(test)["tests"][0]
        return {
            "claim_id": claim_id,
            "implications": [
                {"sentence": text, "expect": "holds", "why": "the claim itself", "test": typed}
            ],
        }

    def _argument(self) -> dict[str, Any]:
        analysis = self.base.analysis
        assert analysis is not None
        by_id = {item.id: item for item in analysis.analytics}
        claims = []
        for claim in self.base.claims:
            mine = [
                by_id[i]
                for i in (claim.analysis.analytic_ids if claim.analysis else [])
                if by_id[i].available
            ]
            sentences = [{"text": item.reading, "cites": [item.id]} for item in mine[:1]]
            claims.append(
                {
                    "claim_id": claim.id,
                    "lean": "unclear",
                    "assessment": sentences,
                    "case_for": [],
                    "case_against": [],
                    "decides": [],
                    "would_change": [],
                }
            )
        return {
            "claims": claims,
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


def _run(run_id: str, data_dir: Path, analyser: ClaudeAnalyser | None = None) -> Run:
    request = ThesisRequest(ticker="NVDA", decision=DECISION, claims=CLAIMS)
    run = new_run(request).model_copy(update={"id": run_id, "started_at": STAMP})
    store = Store(data_dir / f"{run_id}.sqlite")
    try:
        return execute_run(
            run,
            store,
            filings=recorded_filings(),
            analyst=ExtractiveAnalyst(),
            fetch_page=FakePages({}),
            cache=FilingCache(),
            clock=ManualClock(),
            analyser=analyser,
        )
    finally:
        store.close()


def _fixed(value: Any) -> Any:
    """``value`` with every clock time set to :data:`STAMP`."""
    if isinstance(value, dict):
        return {
            key: STAMP.isoformat().replace("+00:00", "Z")
            if key in CLOCK_FIELDS and item
            else _fixed(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_fixed(item) for item in value]
    return value


def _json(data: Any) -> str:
    return json.dumps(_fixed(data), indent=2, ensure_ascii=False) + "\n"


def write(out: Path = OUT) -> list[Path]:
    """Make the computed and hand-built examples and write them to ``out``."""
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as scratch:
        base = _run("run-example-analysis", Path(scratch))
        built = _run(
            "run-example-analysis-hand-built",
            Path(scratch),
            ClaudeAnalyser(transport=HandBuilt(base), model="none"),
        )
    fixed = _fixed(base.model_dump(mode="json"))
    texts = {
        "run.json": _json(fixed),
        "brief.md": render_markdown(Run.model_validate(fixed)),
        "run-hand-built-argument.json": _json(built.model_dump(mode="json")),
    }
    paths = []
    for name in FILES:
        path = out / name
        path.write_text(texts[name], encoding="utf-8")
        paths.append(path)
    return paths


def replayed(cassette: Path = DEFAULT_CASSETTE) -> Run | None:
    """The example thesis replayed from ``cassette`` (read-only for the analysis); None when
    the cassette lacks an engine answer."""
    with tempfile.TemporaryDirectory() as scratch:
        run, pending = replay_copy(cassette, Path(scratch))
    if pending:
        return None
    return run.model_copy(update={"id": "run-example-analysis-replayed"})


def analysis_recorded(run: Run | None) -> bool:
    """True when the replayed run's argument came from the cassette."""
    return run is not None and run.analysis is not None and run.analysis.argument_by == "model"


def write_replayed(out: Path = OUT) -> Path | None:
    """Write :data:`REPLAYED` when the cassette answers the analysis; else None."""
    run = replayed()
    if not analysis_recorded(run):
        return None
    assert run is not None
    path = out / REPLAYED
    path.write_text(_json(run.model_dump(mode="json")), encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    """Write the examples; say what the replayed example still needs."""
    del argv
    for path in write():
        print(f"examples-analysis: wrote {path.as_posix()}")
    written = write_replayed()
    if written is not None:
        print(f"examples-analysis: wrote {written.as_posix()}")
        return 0
    stale = OUT / REPLAYED
    if stale.exists():
        stale.unlink()
        print(f"examples-analysis: removed {stale.as_posix()}: its answers are not recorded")
    print(
        f"examples-analysis: {REPLAYED} not written: the cassette {DEFAULT_CASSETTE.as_posix()} "
        "holds no answer to the analysis model's two requests under the current prompts. "
        "Record them (2 API calls), then run make examples-analysis again: make record-analysis"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
