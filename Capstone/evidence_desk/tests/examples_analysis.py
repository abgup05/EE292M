"""Write the analysis examples to docs/examples/analysis (``make examples-analysis``).

Offline, from the recorded NVIDIA filings and facts; no model is called and no EDGAR request
is made. The claims are those of the live NVIDIA run the page samples
(``src/web/sample-run-live.json``). Files, each exactly what ``GET /api/runs/{id}`` (or its
Markdown export) serves:

- ``run.json`` and ``brief.md``: the extractive engine and no analysing model, so the
  record carries the analysis code computes (relevance, headline, analytics, odds) and says
  no model wrote an argument;
- ``run-hand-built-argument.json``: the same run with the corollaries and the argument
  answered by a fake transport whose answers are SCRIPTED HERE BY CODE (fixed implications;
  sentences that repeat the readings code wrote, and three made to fail the audit). No model
  wrote them: the file shows every shape a model's answers take on the record (each
  corollary status, a verified and an unverified sentence, a condition, a scenario, both
  flags), and ``argument_detail`` says so. It is not an example of what a model would say,
  and its argument is not an argument;
- ``brief-hand-built-argument.md``: its Markdown brief, to show how the export lays an
  argument out;
- ``run-model-argument.json`` and ``brief-model-argument.md``: the same run with a model's
  corollaries and argument, replayed from the cassette ``demo/cassettes/analysis-example``.
  Written only when the cassette holds both answers (and removed when stale); otherwise
  ``make examples-analysis`` says how to record them (``make record-analysis``);
- ``replayed-run.json``: the example thesis replayed from the cassette
  ``demo/cassettes/nvda-example``, with the analysis model's two answers when the cassette
  holds them. Written only then (and removed when stale).

Clock times are fixed at :data:`STAMP` so the files change only when a shape or a result
does.
"""

from __future__ import annotations

import gzip
import json
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.analytics import AnalyticsProvider
from app.core.claim_reading import as_reading
from app.core.claimtest import ClaimTest, compile_claim
from app.core.models import Run, ThesisRequest
from app.engines.analyser import ClaudeAnalyser, configured_model
from app.engines.cassette import CassetteTransport
from app.engines.extractive import ExtractiveAnalyst
from app.engines.transport import ModelRequest, Transport
from app.services.export import render_markdown
from app.services.thesis_run import execute_run, new_run
from app.services.view_providers import run_providers
from app.sources.frames import FramesSource
from app.sources.thirteenf import ThirteenFSource
from app.store import FilingCache, Store
from tests.fakes import FakeFilings, FakePages, ManualClock
from tests.golden_run import replay_copy
from tests.replay_run import DEFAULT_CASSETTE, recorded_filings

OUT = Path("docs/examples/analysis")
FILES = (
    "run.json",
    "brief.md",
    "run-hand-built-argument.json",
    "brief-hand-built-argument.md",
)
REPLAYED = "replayed-run.json"
MODEL_FILES = ("run-model-argument.json", "brief-model-argument.md")
MODEL_CASSETTE = Path("demo/cassettes/analysis-example")
MARKET_FACTS = Path("tests/fixtures/edgar/companyfacts-market-CIK0001045810.json.gz")
FRAMES = Path("tests/fixtures/frames")
THIRTEENF = Path("tests/fixtures/thirteenf")
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
HAND_BUILT = (
    "scripted answers made by tests/examples_analysis.py from the run's own analytics "
    "(no model wrote them)"
)
# Implications scripted to show each way a corollary can come out: (claim, sentence, the
# outcome expected, the sentence whose test stands in for the proposer's typed form; None
# for the sentence's own, "" for none).
SCRIPTED_IMPLICATIONS: tuple[tuple[str, str, str, str | None], ...] = (
    ("c1", "Operating margin is above 60%.", "holds", None),
    # The grammar reads no test in these words; the typed form stands alone.
    ("c1", "Profit per dollar of sales stays healthy.", "holds", "Net margin is above 40%."),
    ("c2", "Gross margin is above 72%.", "holds", None),
    ("c2", "Operating margin is expanding.", "holds", "Revenue grew more than 50% year over year."),
    ("c3", "Revenue grew more than 100% year over year.", "holds", None),
    ("c3", "Net income more than doubled in fiscal 2026.", "holds", None),
    ("c4", "Operating cash flow was above net income in the latest fiscal year.", "holds", None),
    ("c4", "Free cash flow margin is above 50%.", "holds", None),
    ("c5", "Revenue growth is accelerating.", "holds", None),
    ("c5", "Customers keep telling management that demand is strong.", "holds", ""),
)


def _typed(sentence: str) -> dict[str, Any]:
    test = compile_claim(sentence)
    return as_reading(test)["tests"][0] if isinstance(test, ClaimTest) else {}


class HandBuilt:
    """A fake transport: answers scripted from a run without a model (see the docstring).

    The implications are fixed sentences; the argument's sentences repeat readings code wrote
    (so their numbers are the record's), plus one sentence with a wrong number, one citing an
    id the run does not have and one citing nothing, to show how each is marked.
    """

    detail = HAND_BUILT

    def __init__(self, base: Run) -> None:
        self.base = base

    def __call__(self, request: ModelRequest) -> dict[str, Any]:
        """The propose or analyse answer for the base run's claims."""
        if request.step == "propose":
            return {"claims": [self._proposal(claim.id) for claim in self.base.claims]}
        return self._argument()

    @staticmethod
    def _proposal(claim_id: str) -> dict[str, Any]:
        return {
            "claim_id": claim_id,
            "implications": [
                {
                    "sentence": sentence,
                    "expect": expect,
                    "why": "scripted: a consequence the claim commits to",
                    "test": _typed(sentence if typed is None else typed) if typed != "" else {},
                }
                for claim, sentence, expect, typed in SCRIPTED_IMPLICATIONS
                if claim == claim_id
            ],
        }

    def _readings(self, claim_id: str) -> list[dict[str, Any]]:
        analysis = self.base.analysis
        claim = next(c for c in self.base.claims if c.id == claim_id)
        assert analysis is not None and claim.analysis is not None
        by_id = {item.id: item for item in analysis.analytics}
        mine = [by_id[i] for i in claim.analysis.analytic_ids if by_id[i].available]
        return [{"text": item.reading, "cites": [item.id]} for item in mine]

    def _claim(self, claim_id: str) -> dict[str, Any]:
        sentences = self._readings(claim_id)
        extra: list[dict[str, Any]] = []
        conditions: list[dict[str, Any]] = []
        if claim_id == "c2":
            extra = [
                {"text": "Gross margin was 99.9% in the newest quarter.", "cites": ["test:c2"]},
                {"text": "A sentence resting on an id the run does not have.", "cites": ["an:no"]},
                {"text": "A sentence that cites the claim alone.", "cites": ["c2"]},
            ]
            conditions = [
                {
                    "text": "A quarter of gross margin below 70% would fail the test.",
                    "cites": ["test:c2"],
                    "measure": "gross_margin",
                    "comparison": "<",
                    "threshold": 70.0,
                    "unit": "percent",
                    "event_category": "none",
                }
            ]
        return {
            "claim_id": claim_id,
            # Scripted against c2's verdict (supported), to show the flag; unclear elsewhere.
            "lean": "challenges" if claim_id == "c2" else "unclear",
            "assessment": [*sentences[:2], *extra],
            "case_for": sentences[2:3],
            "case_against": sentences[3:4],
            "decides": sentences[4:5],
            "would_change": conditions,
        }

    def _argument(self) -> dict[str, Any]:
        ids = [claim.id for claim in self.base.claims]
        first = [s for claim_id in ids for s in self._readings(claim_id)[:1]]
        return {
            "claims": [self._claim(claim_id) for claim_id in ids],
            "thesis": {
                "leans_on": ids[:2],
                "weakest_link": ids[0],
                "weakest_why": first[:1],
                "strongest_for": first[1:2],
                "strongest_against": first[2:3],
                "bottom_line": first[:3],
                "scenarios": [
                    {"name": "Scripted scenario", "conditions": first[:1]},
                ],
            },
        }


def providers(filings: FakeFilings) -> tuple[AnalyticsProvider, ...]:
    """The run's own facts, and the outside and market views over the recorded SEC frames
    and 13F tables (read from disk only: nothing is fetched)."""
    return run_providers(filings, FramesSource(None, FRAMES), ThirteenFSource(None, THIRTEENF))


def _run(run_id: str, data_dir: Path, analyser: ClaudeAnalyser | None = None) -> Run:
    request = ThesisRequest(ticker="NVDA", decision=DECISION, claims=CLAIMS)
    run = new_run(request).model_copy(update={"id": run_id, "started_at": STAMP})
    store = Store(data_dir / f"{run_id}.sqlite")
    filings = recorded_filings()
    # The facts as the market example recorded them: the pruned fixture the other tests read
    # holds no share count, without which nothing can be valued.
    filings.facts = json.loads(gzip.decompress(MARKET_FACTS.read_bytes()))
    try:
        return execute_run(
            run,
            store,
            filings=filings,
            analytics_providers=providers(filings),
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
    fixed_built = _fixed(built.model_dump(mode="json"))
    texts = {
        "run.json": _json(fixed),
        "brief.md": render_markdown(Run.model_validate(fixed)),
        "run-hand-built-argument.json": _json(fixed_built),
        "brief-hand-built-argument.md": render_markdown(Run.model_validate(fixed_built)),
    }
    paths = []
    for name in FILES:
        path = out / name
        path.write_text(texts[name], encoding="utf-8")
        paths.append(path)
    return paths


def model_run(
    data_dir: Path, cassette: Path = MODEL_CASSETTE, live: Transport | None = None
) -> Run:
    """The example run with the analysing model answering from ``cassette``: read-only, or
    recording what ``live`` answers for a request the cassette lacks."""
    analyser = ClaudeAnalyser(
        transport=CassetteTransport(cassette, live=live, read_only=live is None),
        model=configured_model(),
    )
    return _run("run-example-analysis-model", data_dir, analyser)


def write_model(out: Path = OUT, cassette: Path = MODEL_CASSETTE) -> list[Path]:
    """Write :data:`MODEL_FILES` when ``cassette`` answers both requests; else remove them."""
    with tempfile.TemporaryDirectory() as scratch:
        run = model_run(Path(scratch), cassette)
    analysis = run.analysis
    recorded = (
        analysis is not None
        and analysis.corollaries_step == "answered"
        and analysis.argument_step == "answered"
    )
    paths = [out / name for name in MODEL_FILES]
    if not recorded:
        for path in paths:
            path.unlink(missing_ok=True)
        return []
    fixed = _fixed(run.model_dump(mode="json"))
    paths[0].write_text(_json(fixed), encoding="utf-8")
    paths[1].write_text(render_markdown(Run.model_validate(fixed)), encoding="utf-8")
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
    model = write_model()
    for path in model:
        print(f"examples-analysis: wrote {path.as_posix()}")
    if not model:
        print(
            f"examples-analysis: {' and '.join(MODEL_FILES)} not written: the cassette "
            f"{MODEL_CASSETTE.as_posix()} does not hold the analysis model's two answers "
            "under the current prompts. Record them: make record-analysis"
        )
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
        "Record them, then run make examples-analysis again: make record-analysis"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
