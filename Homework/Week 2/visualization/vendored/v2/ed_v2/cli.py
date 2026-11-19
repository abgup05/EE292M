"""The command line: the second entry point onto the same thesis-run use case as the API.

``python -m app.cli run --ticker NVDA --decision "..." --claim "..." [--claim ...]``
tests a thesis; ``python -m app.cli example`` tests the NVIDIA example. Both run
synchronously through :func:`app.services.thesis_run.execute_run`, print each
claim's verdict with the policy's wording, and write ``<out>/<run-id>.json``
(the run record) and ``<out>/<run-id>.md`` (the exported brief).

Exit codes: 0 when the run finished (complete or partial), 1 when it failed or
EDGAR could not be consulted, 2 when the thesis or the options are invalid.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from ed_v2 import wiring
from ed_v2.core import limits
from ed_v2.core.models import Run, RunStatus, ThesisRequest
from ed_v2.core.policy import STATUS_NOTES, VERDICT_LABELS
from ed_v2.core.ports import FilingSource, PageFetcher, SourceError, UnknownTicker
from ed_v2.services.examples import EXAMPLE_THESIS
from ed_v2.services.export import render_markdown
from ed_v2.services.thesis_run import execute_run, new_run
from ed_v2.sources.http import fetch_page as default_fetch_page
from ed_v2.store import Store

DEFAULT_OUT = Path("results")
NOT_ASSESSED = "Not assessed"


def coverage_sentence(run: Run) -> str:
    """One sentence of the counts the backend recorded in ``run.coverage``."""
    c = run.coverage
    return (
        f"Read {c.sources_read} of {c.sources_requested} source(s); "
        f"{c.claims_with_evidence} of {c.claims_total} claim(s) have verified evidence; "
        f"{c.findings_verified} finding(s) verified and {c.findings_withheld} withheld; "
        f"{c.excerpts_verified} of {c.quotes_offered} quote(s) verified."
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
        help="auto: Claude when ANTHROPIC_API_KEY is set, else extractive (default)",
    )
    shared.add_argument(
        "--out", type=Path, default=DEFAULT_OUT, help="directory for the record and the brief"
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
    return parser


def _thesis(args: argparse.Namespace) -> ThesisRequest:
    if args.command == "example":
        return EXAMPLE_THESIS
    return ThesisRequest(
        ticker=args.ticker,
        decision=args.decision,
        claims=args.claims,
        filings=args.filings,
        scope_notes=args.scope_notes,
    )


def _report(run: Run, out: Path) -> None:
    company = f" ({run.company.name}, {run.company.ticker})" if run.company else ""
    print(f"{run.id}: {run.status.upper()}{company}")
    print(STATUS_NOTES[run.status])
    for claim in run.claims:
        label = VERDICT_LABELS[claim.verdict] if claim.verdict else NOT_ASSESSED
        print(f"  {claim.id}  {label} ({len(claim.finding_ids)} finding(s))  {claim.text}")
    print(coverage_sentence(run))
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
) -> int:
    """Run the command in ``argv`` and return the exit code.

    ``filings`` and ``store`` default to :mod:`app.wiring`; tests pass fakes.
    """
    args = _parser().parse_args(argv)
    try:
        thesis = _thesis(args)
        analyst = wiring.analyst_named(args.engine)
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

    store = store or wiring.store_from_env()
    run = new_run(thesis)
    store.save_run(run)
    print(f"{run.id}: testing {len(thesis.claims)} claim(s) on {thesis.ticker} with {analyst.name}")
    run = execute_run(run, store, filings=filings, analyst=analyst, fetch_page=fetch_page)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{run.id}.json").write_text(run.model_dump_json(indent=2) + "\n")
    (args.out / f"{run.id}.md").write_text(render_markdown(run))
    _report(run, args.out)
    return 1 if run.status == RunStatus.failed else 0


if __name__ == "__main__":
    sys.exit(main())
