"""The demo's measured summary reads every number from the run record it was given."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_app
from app.demo import summarize
from app.engines.extractive import ExtractiveAnalyst
from app.services.examples import EXAMPLE_THESIS
from app.services.thesis_run import execute_run, new_run
from app.store import Store
from tests.fakes import Q1_2027, Q2_2027, FakeFilings, FakePages


def test_the_summary_reports_status_claims_coverage_and_sources(tmp_path: Path) -> None:
    store = Store(tmp_path / "runs.sqlite")
    filings = FakeFilings.nvidia(Q2_2027, Q1_2027)
    run = execute_run(
        new_run(EXAMPLE_THESIS),
        store,
        filings=filings,
        analyst=ExtractiveAnalyst(),
        fetch_page=FakePages({}),
    )
    app = create_app(store=store, filings=filings, analyst=ExtractiveAnalyst())
    with TestClient(app) as client:
        meta = client.get("/api/meta").json()
        health = client.get("/api/health").json()
        record = client.get(f"/api/runs/{run.id}").json()

    lines = summarize(record, meta, health, 12.34, [(0.0, "queued"), (1.5, "done")])
    text = "\n".join(lines)

    def line_with(*facts: str) -> str:
        """The one line that states every fact given; how it is formatted is not tested."""
        found = [line for line in lines if all(fact in line for fact in facts)]
        assert len(found) == 1, f"expected one line stating {facts}, found {found}"
        return found[0]

    assert run.id in text and "PARTIAL" in text
    assert "12.3" in line_with("Wall time")
    assert "extractive" in line_with("Engine") and "0.4.0" in line_with("Engine")
    for claim in run.claims:
        withheld = sum(1 for f in run.unsupported_findings if f.claim_id == claim.id)
        row = line_with(claim.text)
        assert meta["verdict_labels"][claim.verdict] in row
        assert _numbers(row) == [
            *_numbers(claim.id + " " + claim.text),
            len(claim.finding_ids),
            withheld,
            claim.passages_considered,
        ]
    c = run.coverage
    assert _numbers(line_with("Sources read")) == [1, 2]
    assert _numbers(line_with("Passages indexed")) == [c.passages_indexed]
    assert _numbers(line_with("Quotes offered")) == [
        c.quotes_offered,
        c.excerpts_verified,
        c.quotes_rejected,
    ]
    assert _numbers(line_with("Findings verified")) == [c.findings_verified, c.findings_withheld]
    assert "10-Q" in line_with("s1", "2026-07-26", "2026-08-26")
    assert "failed" in line_with(f"EDGAR answered HTTP 404 for {Q1_2027.url}")
    assert "1 of 2 source(s) could not be read." in text
    assert "1.5" in line_with(": done")


def _numbers(line: str) -> list[int]:
    """The whole numbers written in ``line``, in order."""
    return [int(number) for number in re.findall(r"\d+", line)]
