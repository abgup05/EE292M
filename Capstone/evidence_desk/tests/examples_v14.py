"""Write the version 14 example payloads to docs/examples/v14 (``make examples``).

Offline, from the recorded NVIDIA fixtures and the extractive engine; no model and no
EDGAR request. Four files, each exactly what the API serves:

- ``run.json``: ``GET /api/runs/{id}`` for a run whose claims compile (or do not) to
  computed tests, with their histories;
- ``as-of-run.json``: the same claims in a run as of :data:`AS_OF`;
- ``restatements.json``: ``GET /api/companies/NVDA/restatements``;
- ``brief.md``: ``GET /api/runs/{id}/export.md`` of the first run;
- ``run-readers.json``: ``GET /api/runs/{id}`` for a run whose claims (six of set C, from
  :data:`READERS_SET`) are read by the grammar and two model readers, their answers replayed
  read-only from :data:`READERS_CASSETTE`. Written only when that cassette answers every read
  under the current prompt; otherwise not written (and removed if stale), and ``make
  examples`` says how to record them.

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
from app.core.ports import ClaimReader
from app.engines.cassette import RESPONSES, CassetteTransport, request_key
from app.engines.claim_reader import (
    DEFAULT_READER_MODEL,
    DEFAULT_SECOND_READER_MODEL,
    READ_STEP,
    SECOND_READ_STEP,
    ModelClaimReader,
    read_request,
    second_reader,
)
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
READERS_FILE = "run-readers.json"
READERS_SET = Path("eval/claim-tests-example-readers.json")
READERS_CASSETTE = Path("eval/cassettes/claim-readers")


def _run(
    run_id: str,
    as_of: str | None,
    data_dir: Path,
    claims: Sequence[str] = CLAIMS,
    readers: tuple[ClaimReader, ClaimReader] | None = None,
) -> Run:
    request = ThesisRequest(
        ticker="NVDA", decision=DECISION, claims=list(claims), as_of=as_of, tagged_figures=True
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
            claim_reader=readers,
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


def reader_claims() -> list[str]:
    """The claims of the example run with two model readers, in order."""
    payload = json.loads(READERS_SET.read_text(encoding="utf-8"))
    return [str(claim["text"]) for claim in payload["claims"]]


def unrecorded_reads(cassette: Path = READERS_CASSETTE) -> int:
    """How many of the example's read requests ``cassette`` does not answer."""
    return sum(
        not (cassette / RESPONSES / f"{request_key(read_request(claim, step))}.json").exists()
        for claim in reader_claims()
        for step in (READ_STEP, SECOND_READ_STEP)
    )


def write_readers(out: Path = OUT, cassette: Path = READERS_CASSETTE) -> Path | None:
    """Write :data:`READERS_FILE` to ``out`` from ``cassette``; None while a read is missing.

    The cassette is read-only here: a missing answer is never saved as pending, and no
    model is asked.
    """
    if unrecorded_reads(cassette):
        return None
    readers = (
        ModelClaimReader(CassetteTransport(cassette, read_only=True), DEFAULT_READER_MODEL),
        second_reader(CassetteTransport(cassette, read_only=True), DEFAULT_SECOND_READER_MODEL),
    )
    with tempfile.TemporaryDirectory() as scratch:
        run = _run("run-example-v14-readers", None, Path(scratch), reader_claims(), readers)
    out.mkdir(parents=True, exist_ok=True)
    path = out / READERS_FILE
    path.write_text(_json(run.model_dump(mode="json")), encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    """Write the examples and list them; say what the readers example still needs."""
    del argv
    for path in write():
        print(f"examples: wrote {path.as_posix()}")
    written = write_readers()
    if written is not None:
        print(f"examples: wrote {written.as_posix()}")
        return 0
    stale = OUT / READERS_FILE
    if stale.exists():
        stale.unlink()
        print(f"examples: removed {stale.as_posix()}: its answers are no longer all recorded")
    missing = unrecorded_reads()
    print(
        f"examples: {READERS_FILE} not written: {missing} of {2 * len(reader_claims())} read "
        f"requests are not recorded in {READERS_CASSETTE.as_posix()} under the current prompt. "
        f"Record them (API calls), then run make examples again: make eval ARGS='claim-readers "
        f"--set {READERS_SET.as_posix()} --record --max-calls {missing}'"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
