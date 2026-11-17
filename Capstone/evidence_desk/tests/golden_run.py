"""The tripwire: the whole example run, reduced to a record that changes when any answer does.

:func:`build_golden` runs the example thesis with the deterministic extractive
engine on NVIDIA's three recorded filings and recorded XBRL facts, with a
clock that never moves, and returns a JSON-serialisable record without
timestamps or run ids. The record is grouped into :data:`STAGES`, in pipeline
order, so a difference names the first stage that moved:

    sources    form, period, sections, characters, content hash, Item coverage
    limits     every public constant of app.core.limits
    prompts    SHA-256 of every Claude system prompt and output schema
    retrieval  passages indexed; per claim, its queries and the passages offered
    evidence   per excerpt: source, start, length, locator, SHA-256 of the text
    verdicts   per claim: verdict and finding ids
    coverage   the run status and every coverage count
    figures    every metric of the newest quarter and newest fiscal year

``tests/golden/golden.json`` is the checked-in record and ``tests/test_golden.py``
compares against it. ``make golden-baseline`` (``python -m tests.golden_run``)
rewrites it, prints which stages changed, and rewrites ``tests/golden/replay.json``
from the cassette replay when that replay has nothing pending.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

from app.core import limits
from app.core.documents import Document, Passage
from app.core.metric_models import Metric
from app.core.models import Claim, Company, Finding, Run, ThesisRequest
from app.core.ports import ClaimDraft, SummaryDraft
from app.engines import claude
from app.engines.extractive import ExtractiveAnalyst
from app.services import ingest
from app.services.examples import EXAMPLE_THESIS
from app.services.thesis_run import execute_run, new_run
from app.sources.filing import item_coverage
from app.store import Store
from tests.fakes import FakePages, ManualClock
from tests.replay_run import DEFAULT_CASSETTE, recorded_filings, replay

GOLDEN_DIR = Path(__file__).parent / "golden"
GOLDEN_PATH = GOLDEN_DIR / "golden.json"
REPLAY_PATH = GOLDEN_DIR / "replay.json"
STAGES: tuple[str, ...] = (
    "sources",
    "limits",
    "prompts",
    "retrieval",
    "evidence",
    "verdicts",
    "coverage",
    "figures",
)
SIGNIFICANT_DIGITS = 6


def sha256_text(text: str) -> str:
    """Hex SHA-256 of ``text`` encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(value: object) -> str:
    """Sorted keys, no whitespace, non-ASCII kept: the form every hash here is taken over."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class RecordingAnalyst:
    """The extractive engine, noting the passages offered for each claim id.

    It keeps the extractive engine's ``name``, so the pipeline treats it as the
    deterministic engine and wraps it in no fallback. Safe to call from
    several threads at once.
    """

    def __init__(self) -> None:
        """Wrap a fresh :class:`ExtractiveAnalyst`."""
        self._inner = ExtractiveAnalyst()
        self.name = self._inner.name
        self.detail = getattr(self._inner, "detail", "")
        self.offered: dict[str, list[Passage]] = {}
        self._lock = threading.Lock()

    def plan(self, request: ThesisRequest, company: Company) -> list[list[str]]:
        """The extractive engine's queries."""
        return self._inner.plan(request, company)

    def assess(
        self,
        request: ThesisRequest,
        company: Company,
        claim: Claim,
        passages: list[Passage],
        figures: Sequence[Metric] = (),
    ) -> ClaimDraft:
        """Record the passages offered for ``claim``, then assess as the extractive engine."""
        with self._lock:
            self.offered[claim.id] = list(passages)
        return self._inner.assess(request, company, claim, passages, figures=figures)

    def summarize(
        self, request: ThesisRequest, company: Company, claims: list[Claim], findings: list[Finding]
    ) -> SummaryDraft:
        """The extractive engine's summary."""
        return self._inner.summarize(request, company, claims, findings)


@contextmanager
def _recording_parsed_filings() -> Iterator[dict[str, Document]]:
    """Note every document the ingest step parses, by filing URL, without parsing twice."""
    parsed: dict[str, Document] = {}
    original = ingest.parse_filing

    def recording(html: str, *, url: str, title: str, published_date: str | None) -> Document:
        document = original(html, url=url, title=title, published_date=published_date)
        parsed[url] = document
        return document

    with mock.patch.object(ingest, "parse_filing", recording):
        yield parsed


def run_example(data_dir: Path) -> tuple[Run, RecordingAnalyst, dict[str, Document]]:
    """The example thesis on the recorded filings, with the extractive engine and a still clock."""
    analyst = RecordingAnalyst()
    with _recording_parsed_filings() as parsed:
        run = execute_run(
            new_run(EXAMPLE_THESIS.model_copy(deep=True)),
            Store(data_dir / "golden.sqlite"),
            filings=recorded_filings(),
            analyst=analyst,
            fetch_page=FakePages({}),
            clock=ManualClock(),
        )
    return run, analyst, parsed


def _round(value: float | None) -> float | None:
    return None if value is None else float(f"{value:.{SIGNIFICANT_DIGITS}g}")


def limits_snapshot() -> dict[str, Any]:
    """Every public constant of :mod:`app.core.limits`, by name."""
    return {
        name: value
        for name, value in sorted(vars(limits).items())
        if name.isupper() and not name.startswith("_")
    }


def prompt_hashes() -> dict[str, str]:
    """SHA-256 of every Claude system prompt (``*_SYSTEM*``) and output schema (``*_SCHEMA``)."""
    hashes: dict[str, str] = {}
    for name, value in sorted(vars(claude).items()):
        if name.startswith("_") or not name.isupper():
            continue
        if "_SYSTEM" in name and isinstance(value, str):
            hashes[name] = sha256_text(value)
        elif name.endswith("_SCHEMA") and isinstance(value, dict):
            hashes[name] = sha256_text(canonical_json(value))
    return hashes


def _sources(run: Run, parsed: dict[str, Document]) -> list[dict[str, Any]]:
    out = []
    for source in run.sources:
        document = parsed.get(source.url)
        out.append(
            {
                "id": source.id,
                "kind": source.kind.value,
                "form": source.form,
                "period_end": source.period_end,
                "extraction_status": source.extraction_status.value,
                "sections": source.sections,
                "characters": source.characters,
                "content_hash": source.content_hash,
                "item_coverage": _round(item_coverage(document)) if document else None,
            }
        )
    return out


def _figures(run: Run) -> list[dict[str, Any]]:
    """Every metric of the newest quarter and of the newest fiscal year, in report order."""
    newest = {
        period: max((m.period_end for m in run.metrics if m.period == period), default=None)
        for period in ("quarter", "annual")
    }
    return [
        {"id": m.id, "value": _round(m.value), "display": m.display}
        for m in run.metrics
        if m.period in newest and m.period_end == newest[m.period]
    ]


def golden_record(run: Run, analyst: RecordingAnalyst, parsed: dict[str, Document]) -> dict:
    """The stages of :data:`STAGES` for one finished run, plus their ``sha256``."""
    record: dict[str, Any] = {
        "sources": _sources(run, parsed),
        "limits": limits_snapshot(),
        "prompts": prompt_hashes(),
        "retrieval": {
            "passages_indexed": run.coverage.passages_indexed,
            "claims": [
                {
                    "id": claim.id,
                    "queries": list(claim.queries),
                    "offered": [
                        {"id": passage.id, "locator": passage.locator}
                        for passage in analyst.offered.get(claim.id, [])
                    ],
                }
                for claim in run.claims
            ],
        },
        "evidence": [
            {
                "id": item.id,
                "finding_id": item.finding_id,
                "source_id": item.source_id,
                "start": item.start,
                "length": len(item.excerpt),
                "locator": item.locator,
                "excerpt_sha256": sha256_text(item.excerpt),
            }
            for item in run.evidence
        ],
        "verdicts": [
            {
                "id": claim.id,
                "verdict": claim.verdict.value if claim.verdict else None,
                "finding_ids": list(claim.finding_ids),
            }
            for claim in run.claims
        ],
        "coverage": {
            "status": run.status.value,
            "counts": run.coverage.model_dump(mode="json"),
        },
        "figures": _figures(run),
    }
    record["sha256"] = sha256_text(canonical_json(record))
    return record


def build_golden() -> dict:
    """Run the example offline and return its golden record (see the module docstring)."""
    with tempfile.TemporaryDirectory() as scratch:
        run, analyst, parsed = run_example(Path(scratch))
    return golden_record(run, analyst, parsed)


def changed_stages(old: dict, new: dict) -> list[str]:
    """The stages of :data:`STAGES` whose content differs between two records, in order."""
    return [stage for stage in STAGES if old.get(stage) != new.get(stage)]


def replay_record(run: Run) -> dict:
    """Per claim of a replayed run: verdict, verified finding count and withheld count."""
    return {
        "claims": [
            {
                "id": claim.id,
                "verdict": claim.verdict.value if claim.verdict else None,
                "findings": len(claim.finding_ids),
                "withheld": sum(1 for f in run.unsupported_findings if f.claim_id == claim.id),
            }
            for claim in run.claims
        ]
    }


def replay_copy(cassette: Path, scratch: Path) -> tuple[Run, list[str]]:
    """Replay a copy of ``cassette`` under ``scratch``, so a miss never writes into the original."""
    copy = scratch / "cassette"
    shutil.copytree(cassette, copy)
    return replay(copy, scratch)


def _write(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def write_baseline(cassette: Path = DEFAULT_CASSETTE) -> int:
    """Rewrite golden.json (and replay.json when the replay is complete); print what moved."""
    new = build_golden()
    old = json.loads(GOLDEN_PATH.read_text()) if GOLDEN_PATH.exists() else {}
    moved = changed_stages(old, new)
    _write(GOLDEN_PATH, new)
    if not old:
        print(f"golden: wrote a first baseline to {GOLDEN_PATH} (sha256 {new['sha256']})")
    elif moved or old.get("sha256") != new["sha256"]:
        print(f"golden: stages changed: {', '.join(moved) or 'none (record shape only)'}")
        print(f"golden: sha256 {old.get('sha256')} -> {new['sha256']}")
    else:
        print(f"golden: unchanged (sha256 {new['sha256']})")
    with tempfile.TemporaryDirectory() as scratch:
        run, pending = replay_copy(cassette, Path(scratch))
    if pending:
        print(
            f"replay: {len(pending)} model request(s) pending in {cassette}; "
            f"{REPLAY_PATH} left unchanged"
        )
    else:
        replay_new = replay_record(run)
        replay_old = json.loads(REPLAY_PATH.read_text()) if REPLAY_PATH.exists() else None
        _write(REPLAY_PATH, replay_new)
        state = "unchanged" if replay_old == replay_new else "rewritten"
        print(f"replay: {REPLAY_PATH} {state}")
    print("Read the diff (git diff tests/golden) before committing a new baseline.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """``--write``: rewrite the baselines. Without it: print the current record's sha256."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="rewrite tests/golden/*.json")
    parser.add_argument("--cassette", type=Path, default=DEFAULT_CASSETTE)
    args = parser.parse_args(argv)
    if args.write:
        return write_baseline(args.cassette)
    print(build_golden()["sha256"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
