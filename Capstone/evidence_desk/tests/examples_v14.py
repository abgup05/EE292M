"""Write the version 14 example payloads to docs/examples/v14 (``make examples``).

Offline, from the recorded NVIDIA fixtures and the extractive engine; no model and no
EDGAR request. Four files, each exactly what the API serves:

- ``run.json``: ``GET /api/runs/{id}`` for a run whose claims compile (or do not) to
  computed tests, with their histories;
- ``as-of-run.json``: the same claims in a run as of :data:`AS_OF`;
- ``restatements.json``: ``GET /api/companies/NVDA/restatements``;
- ``brief.md``: ``GET /api/runs/{id}/export.md`` of the first run.

Clock times (the run's start and end, when each source was read) are fixed at
:data:`STAMP` so the files change only when a shape or a result does. The fields are
named in ``docs/examples/v14/README.md``.
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.models import Run, ThesisRequest
from app.engines.extractive import ExtractiveAnalyst
from app.services.export import render_markdown
from app.services.restatements import company_restatements
from app.services.thesis_run import execute_run, new_run
from app.store import FilingCache, Store
from tests.fakes import FakePages, ManualClock
from tests.replay_run import recorded_filings

OUT = Path("docs/examples/v14")
FILES = ("run.json", "as-of-run.json", "restatements.json", "brief.md")
STAMP = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
AS_OF = "2026-03-01"
CLAIMS = [
    "Gross margin is expanding.",
    "Revenue grew more than 200% year over year.",
    "Data center revenue is still growing year over year.",
    "Data center is more than 80% of revenue.",
    "Revenue grew in fiscal 2008.",
]
DECISION = "Whether to keep an overweight position in NVIDIA"
CLOCK_FIELDS = ("finished_at", "retrieved_at")


def _run(run_id: str, as_of: str | None, data_dir: Path) -> Run:
    request = ThesisRequest(
        ticker="NVDA", decision=DECISION, claims=CLAIMS, as_of=as_of, tagged_figures=True
    )
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
    """Make the examples and write them to ``out``; returns the paths written."""
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as scratch:
        run = _run("run-example-v14", None, Path(scratch))
        dated = _run("run-example-v14-as-of", AS_OF, Path(scratch))
    filings = recorded_filings()
    ledger = company_restatements(filings.company("NVDA"), filings)
    fixed = _fixed(run.model_dump(mode="json"))
    texts = {
        "run.json": _json(fixed),
        "as-of-run.json": _json(dated.model_dump(mode="json")),
        "restatements.json": _json(ledger.model_dump(mode="json")),
        "brief.md": render_markdown(Run.model_validate(fixed)),
    }
    paths = []
    for name in FILES:
        path = out / name
        path.write_text(texts[name], encoding="utf-8")
        paths.append(path)
    return paths


def main(argv: Sequence[str] | None = None) -> int:
    """Write the examples and list them."""
    del argv
    for path in write():
        print(f"examples: wrote {path.as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
