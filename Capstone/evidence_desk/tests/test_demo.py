"""The demo's measured summary reads every number from the run record it was given."""

from __future__ import annotations

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

    text = "\n".join(summarize(record, meta, health, 12.34, [(0.0, "queued"), (1.5, "done")]))
    assert f"- Run: {run.id}; status **PARTIAL**" in text
    assert "- Wall time (POST to finished record): 12.3 s" in text
    assert "- Engine: extractive; model: none; server version 0.2.0" in text
    for claim in run.claims:
        assert f"| {claim.id}. {claim.text} | {meta['verdict_labels'][claim.verdict]} |" in text
    c = run.coverage
    assert "- Sources read: 1 of 2" in text
    assert (
        f"- Quotes offered: {c.quotes_offered}; verified excerpts: {c.excerpts_verified}; "
        f"rejected: {c.quotes_rejected}"
    ) in text
    assert "| s1 | 10-Q | 2026-07-26 | 2026-08-26 |" in text
    assert f"failed: EDGAR answered HTTP 404 for {Q1_2027.url} |" in text
    assert "- 1 of 2 source(s) could not be read." in text
    assert "-    1.5 s: done" in text
