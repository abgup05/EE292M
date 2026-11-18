"""The command line: the second entry point onto the same thesis-run use case as the API.

``python -m app.cli run --ticker NVDA --decision "..." --claim "..." [--claim ...]``
tests a thesis; ``python -m app.cli example`` tests the NVIDIA example; with
``--tagged-figures`` either also offers the engine the figures tagged in the
filings (``ThesisRequest.tagged_figures``). Both run
synchronously through :func:`app.services.thesis_run.execute_run`, print each
claim's verdict with the policy's wording, and write ``<out>/<run-id>.json``
(the run record) and ``<out>/<run-id>.md`` (the exported brief).

``--engine cassette --cassette DIR`` replays recorded model answers and never
calls the API; the meaning check answers from the same cassette (with
``--engine claude`` it calls the API with ``ANTHROPIC_CHECK_MODEL``; with
``--engine extractive`` nothing checks meaning). If the run asked for answers
the cassette lacks, they are saved under ``DIR/pending``, no result file is
written and the exit code is 3; answer them (``docs/cassettes.md``) and run
again. ``python -m app.cli cassette DIR`` describes a cassette and lists its
pending requests.

Exit codes: 0 when the run finished (complete or partial), 1 when it failed or
EDGAR could not be consulted, 2 when the thesis or the options are invalid, 3
when model requests are pending in the cassette.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from app import wiring
from app.core import limits
from app.core.models import Run, RunStatus, ThesisRequest
from app.core.policy import STATUS_NOTES, VERDICT_LABELS
from app.core.ports import Analyst, FilingSource, PageFetcher, SourceError, UnknownTicker
from app.engines.cassette import Cassette, CassetteTransport
from app.engines.checker import NoChecker
from app.engines.claude import ClaudeAnalyst
from app.services.examples import EXAMPLE_THESIS
from app.services.export import render_markdown
from app.services.thesis_run import execute_run, new_run
from app.sources.http import fetch_page as default_fetch_page
from app.store import FactStore, FilingCache, Store

DEFAULT_OUT = Path("results")
NOT_ASSESSED = "Not assessed"
EXIT_PENDING = 3


def coverage_sentence(run: Run) -> str:
    """One sentence of the counts the backend recorded in ``run.coverage``."""
    c = run.coverage
    return (
        f"Read {c.sources_read} of {c.sources_requested} source(s); "
        f"{c.claims_with_evidence} of {c.claims_total} claim(s) have verified excerpts or figures; "
        f"{c.findings_verified} finding(s) verified and {c.findings_withheld} withheld; "
        f"{c.quotes_found} of {c.quotes_offered} quote(s) found word for word, "
        f"{c.quotes_rejected} rejected; {c.excerpts_verified} kept as evidence."
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Test an equity thesis against the company's SEC filings.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--engine",
        choices=wiring.ENGINE_CHOICES,
        default="auto",
        help=(
            "auto: Claude when ANTHROPIC_API_KEY is set, else extractive (default); "
            "cassette: replay the recorded answers in --cassette DIR"
        ),
    )
    shared.add_argument(
        "--cassette", type=Path, help="cassette directory replayed by --engine cassette"
    )
    shared.add_argument(
        "--out", type=Path, default=DEFAULT_OUT, help="directory for the record and the brief"
    )
    shared.add_argument(
        "--tagged-figures",
        action="store_true",
        help=(
            "also offer the engine the segment, product, geography and customer figures tagged "
            "in the newest annual and quarterly report read (changes the engine's prompts)"
        ),
    )
    run = commands.add_parser("run", parents=[shared], help="test a thesis")
    run.add_argument("--ticker", required=True)
    run.add_argument("--decision", required=True)
    run.add_argument(
        "--claim",
        action="append",
        required=True,
        dest="claims",
        help=f"one claim; repeat for up to {limits.MAX_CLAIMS}",
    )
    run.add_argument("--filings", type=int, default=limits.DEFAULT_FILINGS)
    run.add_argument("--scope-notes", default="")
    commands.add_parser("example", parents=[shared], help="test the NVIDIA example thesis")
    describe = commands.add_parser(
        "cassette", help="describe a cassette and list its pending requests"
    )
    describe.add_argument("directory", type=Path)
    return parser


def _analyst(args: argparse.Namespace) -> Analyst:
    """The engine the options name; a cassette directory goes only with the cassette engine."""
    if args.cassette is not None and args.engine != "cassette":
        raise wiring.ConfigurationError("--cassette is used only with --engine cassette")
    return wiring.analyst_named(args.engine, cassette=args.cassette)


def _pending_step(path: Path) -> str:
    """The step a pending request file names, or a note that it cannot be read."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError, UnicodeDecodeError, json.JSONDecodeError:
        return "(unreadable)"
    step = data.get("step") if isinstance(data, dict) else None
    return str(step) if step else "(no step)"


def _describe_cassette(directory: Path) -> int:
    """Print what a cassette holds and which requests are pending."""
    if not directory.is_dir():
        print(f"no cassette at {directory}", file=sys.stderr)
        return 2
    cassette = Cassette(directory)
    print(cassette.describe())
    pending = cassette.pending()
    if not pending:
        print("No pending requests.")
        return 0
    print(f"{len(pending)} pending request(s) in {directory / 'pending'}:")
    for path in pending:
        print(f"  {path.stem}  {_pending_step(path)}")
    return 0


def _cassette_of(analyst: Analyst) -> CassetteTransport | None:
    transport = analyst.transport if isinstance(analyst, ClaudeAnalyst) else None
    return transport if isinstance(transport, CassetteTransport) else None


def _thesis(args: argparse.Namespace) -> ThesisRequest:
    if args.command == "example":
        if args.tagged_figures:
            return EXAMPLE_THESIS.model_copy(update={"tagged_figures": True})
        return EXAMPLE_THESIS
    return ThesisRequest(
        ticker=args.ticker,
        decision=args.decision,
        claims=args.claims,
        filings=args.filings,
        scope_notes=args.scope_notes,
        tagged_figures=args.tagged_figures,
    )


def _report(run: Run, out: Path) -> None:
    company = f" ({run.company.name}, {run.company.ticker})" if run.company else ""
    print(f"{run.id}: {run.status.upper()}{company}")
    print(STATUS_NOTES[run.status])
    for claim in run.claims:
        label = VERDICT_LABELS[claim.verdict] if claim.verdict else NOT_ASSESSED
        print(f"  {claim.id}  {label} ({len(claim.finding_ids)} finding(s))  {claim.text}")
    print(coverage_sentence(run))
    if run.checker != NoChecker.name:
        c = run.coverage
        print(
            f"Meaning check ({run.checker}): {c.findings_checked} finding(s) judged, "
            f"{c.findings_partly} partly supported, {c.findings_failed_meaning} withheld."
        )
    for heading, items in (("Coverage limits", run.coverage_limits), ("Errors", run.errors)):
        if items:
            print(f"{heading}:")
            for item in items:
                print(f"  - {item}")
    print(f"Wrote {out / f'{run.id}.json'} and {out / f'{run.id}.md'}")


def main(
    argv: Sequence[str] | None = None,
    *,
    filings: FilingSource | None = None,
    store: Store | None = None,
    fetch_page: PageFetcher = default_fetch_page,
    cache: FilingCache | None = None,
    facts_store: FactStore | None = None,
) -> int:
    """Run the command in ``argv`` and return the exit code.

    ``filings`` and ``store`` default to :mod:`app.wiring`; tests pass fakes.
    ``cache`` and ``facts_store`` default to the configured ones when ``store`` does
    too; a test that passes its own store gets a cache for that run only and no
    fact store.
    """
    args = _parser().parse_args(argv)
    if args.command == "cassette":
        return _describe_cassette(args.directory)
    try:
        thesis = _thesis(args)
        analyst = _analyst(args)
    except ValidationError as exc:
        for error in exc.errors():
            field = ".".join(str(part) for part in error["loc"]) or "thesis"
            message = str(error["msg"]).removeprefix("Value error, ")
            print(f"{field}: {message}", file=sys.stderr)
        return 2
    except wiring.ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    filings = filings or wiring.filings_from_env()
    try:
        filings.company(thesis.ticker)
    except UnknownTicker as exc:
        print(f"ticker: {exc}", file=sys.stderr)
        return 2
    except SourceError as exc:
        print(f"SEC EDGAR could not be consulted: {exc}", file=sys.stderr)
        return 1

    if store is None:
        store = wiring.store_from_env()
        cache = cache or wiring.cache_from_env()
        facts_store = facts_store or wiring.facts_from_env()
    run = new_run(thesis)
    store.save_run(run)
    checker = wiring.checker_named(args.engine, analyst)
    detail = getattr(analyst, "detail", "")
    engine = f"{analyst.name} ({detail})" if detail else analyst.name
    print(f"{run.id}: testing {len(thesis.claims)} claim(s) on {thesis.ticker} with {engine}")
    if not isinstance(checker, NoChecker):
        print(f"{run.id}: meaning checked by {checker.name} ({checker.detail})")
    run = execute_run(
        run,
        store,
        filings=filings,
        analyst=analyst,
        fetch_page=fetch_page,
        cache=cache,
        checker=checker,
        facts_store=facts_store,
    )

    cassette = _cassette_of(analyst)
    if cassette is not None and cassette.pending_keys:
        print(
            f"{len(cassette.pending_keys)} model request(s) are pending in "
            f"{cassette.directory / 'pending'}. Answer them (docs/cassettes.md) and run again."
        )
        return EXIT_PENDING

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{run.id}.json").write_text(run.model_dump_json(indent=2) + "\n")
    (args.out / f"{run.id}.md").write_text(render_markdown(run))
    _report(run, args.out)
    return 1 if run.status == RunStatus.failed else 0


if __name__ == "__main__":
    sys.exit(main())
