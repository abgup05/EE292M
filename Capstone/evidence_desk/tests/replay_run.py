"""Run the example thesis offline with model answers replayed from a cassette.

The filings and the reported figures are the recorded NVIDIA fixtures, so no
network is used, and the Claude engine's answers come from a cassette
(see ``docs/cassettes.md``), so no model is called. The same prompts are built
every time, which is what lets ``tests/test_replay.py`` assert the result.

``make replay`` runs this. Exit code 3 means the cassette is missing answers:
the requests were saved under ``<cassette>/pending``.
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
from app.engines.cassette import CassetteTransport
from app.engines.claude import ClaudeAnalyst
from app.services.examples import EXAMPLE_THESIS
from app.services.export import render_markdown
from app.services.thesis_run import execute_run, new_run
from app.store import FilingCache, Store
from tests.fakes import FY_2026, Q1_2027, Q2_2027, FakeFilings, recorded_companies, recorded_html

DEFAULT_CASSETTE = Path("demo/cassettes/nvda-example")
RECORDED_DOCUMENTS = {
    Q2_2027.url: "nvda-10q-20260726.htm.gz",
    Q1_2027.url: "nvda-10q-20260426.htm.gz",
    FY_2026.url: "nvda-10k-20260125.htm.gz",
}


def recorded_filings() -> FakeFilings:
    """NVIDIA's three default filings and its XBRL facts, all from recorded fixtures."""
    refs = [Q2_2027, Q1_2027, FY_2026]
    documents = {ref.url: recorded_html(RECORDED_DOCUMENTS[ref.url]) for ref in refs}
    return FakeFilings(refs=refs, documents=documents, companies=recorded_companies())


def replay(cassette: Path, data_dir: Path) -> tuple[Run, list[str]]:
    """Execute the example thesis; return the run and the keys of unanswered requests.

    The record goes to ``data_dir/replay.sqlite`` and the source text to
    ``data_dir/cache.sqlite``.
    """
    transport = CassetteTransport(cassette)
    analyst = ClaudeAnalyst(transport=transport)
    store = Store(data_dir / "replay.sqlite")
    run = execute_run(
        new_run(EXAMPLE_THESIS.model_copy(deep=True)),
        store,
        filings=recorded_filings(),
        analyst=analyst,
        cache=FilingCache(data_dir / "cache.sqlite"),
    )
    return run, list(transport.pending_keys)


def sample_record(run: Run, cassette: Path, data_dir: Path) -> dict[str, object]:
    """The page's sample file: the wording the API serves, and the replayed run."""
    from fastapi.testclient import TestClient  # imported here: it warns on import

    analyst = ClaudeAnalyst(transport=CassetteTransport(cassette))
    app = create_app(
        store=Store(data_dir / "sample.sqlite"), filings=recorded_filings(), analyst=analyst
    )
    with TestClient(app) as client:
        meta = client.get("/api/meta").json()
    return {
        "note": (
            "A recorded run of the NVIDIA example thesis on three recorded filings. The model "
            "answers are replayed from the cassette demo/cassettes/nvda-example; see its "
            "README for how they were produced."
        ),
        "meta": meta,
        "run": json.loads(run.model_dump_json()),
    }


def main(argv: list[str] | None = None) -> int:
    """Replay the example and print its verdicts; write the record when it is complete."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cassette", type=Path, default=DEFAULT_CASSETTE)
    parser.add_argument("--out", type=Path, help="directory for <name>.json and <name>.md")
    parser.add_argument("--name", default="recorded-run")
    parser.add_argument("--sample", type=Path, help="also write the page's sample file here")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as scratch:
        run, pending = replay(args.cassette, Path(scratch))
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
