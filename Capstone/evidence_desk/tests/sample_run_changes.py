"""Record, for the page's sample run, which changed paragraphs bear on each claim.

``python -m tests.sample_run_changes [--out src/web/sample-run-changes.json]`` loads the
recorded run of ``src/web/sample-run.json``, takes the newest annual and the newest quarterly
report that run read, asks SEC EDGAR for the filing of the same form before each (through
the project's client and filing cache), compares them and
ranks the changed paragraphs against each claim, exactly as
``GET /api/runs/{id}/changes`` does. It writes ``{"note", "changes"}`` for the page's
sample mode and prints one line per claim. No model is involved. Needs the network.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from app import wiring
from app.api import WEB_DIR
from app.core.models import Run
from app.services.claim_changes import run_changes
from app.sources.edgar import EdgarClient

SAMPLE_RUN = WEB_DIR / "sample-run.json"
DEFAULT_OUT = WEB_DIR / "sample-run-changes.json"
NOTE = (
    "Recorded on {day} for the sample run beside it: the newest annual and the newest "
    "quarterly report that run read, each compared with the filing of the same form before it "
    "(from SEC EDGAR or the filing cache), and every changed paragraph ranked against each "
    "claim by keyword overlap. No model is involved."
)


def main(argv: list[str] | None = None) -> int:
    """Write the sample and print what was found for each claim."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    run = Run.model_validate(json.loads(SAMPLE_RUN.read_text(encoding="utf-8"))["run"])
    cache = wiring.cache_from_env()
    try:
        with EdgarClient.from_env() as client:
            changes = run_changes(run, filings=client, cache=cache)
    finally:
        cache.close()
    for pair in changes.compared:
        print(f"compared {pair.form}: {pair.later.period_end} against {pair.earlier.period_end}")
    for note in changes.notes:
        print(f"note: {note}")
    for claim, found in zip(run.claims, changes.claims, strict=True):
        print(
            f"{claim.id}: {len(found.changes)} listed, {found.matched} matched of "
            f"{found.considered} changed paragraphs: {claim.text}"
        )
    if not changes.compared:
        print("nothing was compared; no sample written", file=sys.stderr)
        return 1
    sample = {
        "note": NOTE.format(day=datetime.now(UTC).date().isoformat()),
        "changes": changes.model_dump(mode="json"),
    }
    args.out.write_text(json.dumps(sample, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
