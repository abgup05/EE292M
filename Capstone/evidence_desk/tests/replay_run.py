"""Run the example thesis offline with model answers replayed from a cassette.

The filings and the reported figures are the recorded NVIDIA fixtures, so no
network is used, and the Claude engine's answers, and the meaning checker's,
come from a cassette (see ``docs/cassettes.md``), so no model is called. The same prompts are built
every time, which is what lets ``tests/test_replay.py`` assert the result.

``make replay`` runs this. Exit code 3 means the cassette is missing answers:
the requests were saved under ``<cassette>/pending``.

The analysing model's two requests ("propose" and "analyse", version 0.14.2) are replayed
read-only: a cassette recorded before they existed replays every other request, and the
run records the computed analysis only. ``make record-analysis`` (``--record-analysis``)
asks the analysis model for exactly those two answers through the API and records them; it
needs ``ANTHROPIC_API_KEY`` and refuses to send more than ``--max-calls`` requests.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from app.api import create_app
from app.core import policy
from app.core.models import Run
from app.engines.analyser import ClaudeAnalyser, configured_model
from app.engines.cassette import CassetteTransport
from app.engines.checker import ClaudeChecker
from app.engines.claude import ClaudeAnalyst
from app.engines.transport import AnthropicTransport, EngineError, ModelRequest, Transport
from app.services.examples import EXAMPLE_THESIS
from app.services.export import render_markdown
from app.services.thesis_run import execute_run, new_run
from app.store import FilingCache, Store
from tests.fakes import (
    FY_2026,
    Q1_2027,
    Q2_2027,
    FakeFilings,
    recorded_companies,
    recorded_current_documents,
    recorded_current_reports,
    recorded_html,
)

DEFAULT_CASSETTE = Path("demo/cassettes/nvda-example")
RECORDED_DOCUMENTS = {
    Q2_2027.url: "nvda-10q-20260726.htm.gz",
    Q1_2027.url: "nvda-10q-20260426.htm.gz",
    FY_2026.url: "nvda-10k-20260125.htm.gz",
}


def recorded_filings() -> FakeFilings:
    """NVIDIA's three default filings, its 8-Ks since the 10-K and its XBRL facts, as recorded.

    The 8-Ks give the replayed run a timeline; no claim of the example thesis bears on
    an 8-K's category, so none is offered to the model and the recorded prompts hold.
    """
    refs = [Q2_2027, Q1_2027, FY_2026]
    documents = {ref.url: recorded_html(RECORDED_DOCUMENTS[ref.url]) for ref in refs}
    documents.update(recorded_current_documents())
    return FakeFilings(
        refs=refs,
        documents=documents,
        companies=recorded_companies(),
        current=recorded_current_reports(),
    )


class CappedTransport:
    """A live transport that refuses to send more than ``max_calls`` requests."""

    def __init__(self, live: AnthropicTransport, max_calls: int) -> None:
        self.live = live
        self.model = live.model
        self.via = live.via
        self.max_calls = max_calls
        self.sent = 0

    def __call__(self, request: ModelRequest) -> dict[str, object]:
        """Send ``request`` unless the cap is reached."""
        if self.sent >= self.max_calls:
            raise EngineError(f"the cap of {self.max_calls} model request(s) is reached")
        self.sent += 1
        return self.live(request)


def replay_analyser(cassette: Path, live: Transport | None = None) -> ClaudeAnalyser:
    """The analysing model over ``cassette``: read-only, or recording what ``live`` answers."""
    return ClaudeAnalyser(
        transport=CassetteTransport(cassette, live=live, read_only=live is None),
        model=configured_model(),
    )


def replay(
    cassette: Path,
    data_dir: Path,
    *,
    tagged_figures: bool = False,
    analysis_live: Transport | None = None,
) -> tuple[Run, list[str]]:
    """Execute the example thesis; return the run and the keys of unanswered requests.

    With ``tagged_figures`` the run also offers the figures tagged in the filings,
    which changes every assessment prompt, so it needs a cassette of its own. The
    record goes to ``data_dir/replay.sqlite`` and the source text to
    ``data_dir/cache.sqlite``. The analysing model answers from the cassette, read-only,
    unless ``analysis_live`` is given to record its two answers.
    """
    transport = CassetteTransport(cassette)
    analyst = ClaudeAnalyst(transport=transport)
    store = Store(data_dir / "replay.sqlite")
    thesis = EXAMPLE_THESIS.model_copy(deep=True, update={"tagged_figures": tagged_figures})
    run = execute_run(
        new_run(thesis),
        store,
        filings=recorded_filings(),
        analyst=analyst,
        cache=FilingCache(data_dir / "cache.sqlite"),
        checker=replay_checker(transport),
        analyser=replay_analyser(cassette, analysis_live),
    )
    return run, list(transport.pending_keys)


def replay_checker(transport: CassetteTransport) -> ClaudeChecker:
    """The meaning checker over the engine's own cassette and run: it never calls the API."""
    return ClaudeChecker(transport=transport.sibling())


def sample_note(run: Run, cassette: Path) -> str:
    """What the page says about a sample: the recording it replays, and what the run asked for."""
    note = (
        "A recorded run of the NVIDIA example thesis on three recorded filings and the 8-Ks "
        "NVIDIA filed after the annual report, as recorded on 17 November 2026. The model "
        f"answers are replayed from the cassette {cassette.as_posix()}; see its "
        "README for how they were produced."
    )
    if run.inputs.tagged_figures:
        note += " This run asked to be offered the figures tagged in the filings as well."
    return note


def sample_record(run: Run, cassette: Path, data_dir: Path) -> dict[str, object]:
    """The page's sample file: the wording the API serves, and the replayed run."""
    from fastapi.testclient import TestClient  # imported here: it warns on import

    transport = CassetteTransport(cassette)
    app = create_app(
        store=Store(data_dir / "sample.sqlite"),
        filings=recorded_filings(),
        analyst=ClaudeAnalyst(transport=transport),
        checker=replay_checker(transport),
        analyser=replay_analyser(cassette),
    )
    with TestClient(app) as client:
        meta = client.get("/api/meta").json()
    return {
        "note": sample_note(run, cassette),
        "meta": meta,
        "run": json.loads(run.model_dump_json()),
    }


def period_lines(run: Run) -> list[str]:
    """The period check of a run: its counts, then each year not found with its statement."""
    coverage = run.coverage
    lines = [
        f"periods checked {coverage.periods_checked}, unverified {coverage.periods_unverified} "
        f"({coverage.periods_comparative} comparative)"
    ]
    for finding in run.findings:
        for year in finding.checks.periods_unverified:
            note = " (comparative)" if year.comparative else ""
            lines.append(f"  {finding.id} {year.mention}{note}: {finding.statement}")
    return lines


def analysis_lines(run: Run, live: CappedTransport | None = None) -> list[str]:
    """Who wrote the run's analysis, its counts, and the requests sent to record it."""
    analysis, coverage = run.analysis, run.coverage
    if analysis is None:
        return ["analysis: none"]
    lines = [
        f"analysis: {coverage.analytics_computed} analytics computed by code; corollaries "
        f"proposed {coverage.corollaries_proposed}, computed {coverage.corollaries_computed} "
        f"({coverage.corollaries_as_expected} as implied, {coverage.corollaries_against} "
        "against)",
        f"argument: by {analysis.argument_by} ({analysis.argument_detail or 'no model'}); "
        f"sentences written {coverage.analysis_sentences_written}, verified "
        f"{coverage.analysis_sentences_verified}, unverified "
        f"{coverage.analysis_sentences_unverified}",
    ]
    if analysis.argument_note:
        lines.append(f"  {analysis.argument_note}")
    if analysis.corollaries_note:
        lines.append(f"  {analysis.corollaries_note}")
    if live is not None:
        lines.append(f"analysis requests sent to the API: {live.sent} (cap {live.max_calls})")
    return lines


def main(argv: list[str] | None = None) -> int:
    """Replay the example and print its verdicts; write the record when it is complete."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cassette", type=Path, default=DEFAULT_CASSETTE)
    parser.add_argument("--out", type=Path, help="directory for <name>.json and <name>.md")
    parser.add_argument("--name", default="recorded-run")
    parser.add_argument("--sample", type=Path, help="also write the page's sample file here")
    parser.add_argument(
        "--tagged-figures",
        action="store_true",
        help="also offer the figures tagged in the filings (a cassette recorded with the option)",
    )
    parser.add_argument(
        "--record-analysis",
        action="store_true",
        help="ask the analysis model (API) for the propose and analyse answers the cassette lacks",
    )
    parser.add_argument("--max-calls", type=int, help="the most requests --record-analysis sends")
    args = parser.parse_args(argv)
    live: CappedTransport | None = None
    if args.record_analysis:
        if args.max_calls is None:
            print("--record-analysis needs --max-calls N; nothing was asked.")
            return 2
        live = CappedTransport(AnthropicTransport(model=configured_model()), args.max_calls)
    with tempfile.TemporaryDirectory() as scratch:
        run, pending = replay(
            args.cassette,
            Path(scratch),
            tagged_figures=args.tagged_figures,
            analysis_live=live,
        )
        sample = (
            sample_record(run, args.cassette, Path(scratch))
            if args.sample and not pending
            else None
        )
    if pending:
        print(
            f"{len(pending)} model request(s) are pending in {args.cassette}/pending. "
            "Answer them (docs/cassettes.md) and run again."
        )
        for key in pending:
            print(f"  pending/{key}.json")
        return 3
    print(f"status: {run.status} | engine: {run.engine} | {run.engine_detail}")
    for claim in run.claims:
        label = policy.VERDICT_LABELS[claim.verdict] if claim.verdict else "Not assessed"
        print(f"  {claim.id} {label}: {claim.text} ({len(claim.finding_ids)} finding(s))")
    coverage = run.coverage
    print(
        f"findings verified {coverage.findings_verified}, "
        f"withheld {coverage.findings_withheld}; "
        f"excerpts verified {coverage.excerpts_verified}, "
        f"quotes rejected {coverage.quotes_rejected}"
    )
    print(
        f"meaning check ({run.checker}): judged {coverage.findings_checked}, "
        f"partly {coverage.findings_partly}, withheld {coverage.findings_failed_meaning}"
    )
    for line in period_lines(run):
        print(line)
    for line in analysis_lines(run, live):
        print(line)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / f"{args.name}.json").write_text(run.model_dump_json(indent=2) + "\n")
        (args.out / f"{args.name}.md").write_text(render_markdown(run))
        print(f"wrote {args.out / args.name}.json and .md")
    if sample is not None:
        args.sample.write_text(json.dumps(sample, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {args.sample}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
