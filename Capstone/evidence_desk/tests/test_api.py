"""The HTTP boundary: every rejection names its field, runs execute in the background,
and every view's wording comes from /api/meta. EDGAR and the engine are fakes.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.api import WEB_DIR, create_app
from app.core import limits
from app.core.facts import FactBook
from app.core.metrics import build_report
from app.core.models import RunStatus, Verdict
from app.core.policy import (
    FIGURES_NOTE,
    PROVENANCE_NOTE,
    STATUS_NOTES,
    VERDICT_LABELS,
    VERDICT_NOTES,
)
from app.core.ports import SourceError
from app.engines.extractive import ExtractiveAnalyst
from app.services.examples import EXAMPLE_THESIS
from app.store import Store
from tests.fakes import FakeFilings, FakePages, ScriptedAnalyst, filing_html, recorded_facts

DECISION = "Whether to keep an overweight position in NVIDIA into the next earnings report"
CLAIM = "Data center revenue is still growing year over year."
SENTENCE = "Data Center revenue grew 56% from a year ago, driven by demand for Blackwell."
VALID: dict[str, Any] = {"ticker": "NVDA", "decision": DECISION, "claims": [CLAIM], "filings": 1}


def claims(count: int) -> list[str]:
    return [f"Claim number {n} about the company's filings." for n in range(1, count + 1)]


def urls(count: int) -> list[str]:
    return [f"https://investor.example.com/page-{n}" for n in range(1, count + 1)]


@pytest.fixture
def filings() -> FakeFilings:
    return FakeFilings.synthetic(filing_html(SENTENCE))


@pytest.fixture
def client(tmp_path: Path, filings: FakeFilings) -> Iterator[TestClient]:
    app = create_app(
        store=Store(tmp_path / "runs.sqlite"),
        filings=filings,
        analyst=ExtractiveAnalyst(),
        fetch_page=FakePages({}),
    )
    with TestClient(app) as test_client:
        yield test_client


def wait_for(client: TestClient, run_id: str) -> dict[str, Any]:
    for _ in range(200):
        record = client.get(f"/api/runs/{run_id}").json()
        if record["status"] != RunStatus.running:
            return record
        time.sleep(0.02)
    raise AssertionError("the run did not finish")


def fields(response: Any) -> list[str]:
    payload = response.json()
    assert payload["error"] == "Invalid request"
    assert all(detail["message"] for detail in payload["details"])
    return [detail["field"] for detail in payload["details"]]


# Rejections (PROMPT.md section 5)


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"ticker": "nv da$"}, "ticker"),
        ({"claims": []}, "claims"),
        ({"claims": claims(7)}, "claims"),
        ({"claims": ["Too short"]}, "claims"),
        ({"claims": [CLAIM, CLAIM]}, "claims"),
        ({"filings": 0}, "filings"),
        ({"filings": 6}, "filings"),
        ({"filings": "3"}, "filings"),
        ({"decision": "short"}, "decision"),
        ({"scope_notes": "x" * (limits.MAX_SCOPE_CHARS + 1)}, "scope_notes"),
        ({"extra_urls": urls(6)}, "extra_urls"),
        ({"extra_urls": ["http://192.168.1.10/report"]}, "extra_urls.0"),
        ({"extra_urls": [urls(1)[0], "http://localhost:8000/"]}, "extra_urls.1"),
        ({"extra_urls": ["ftp://investor.example.com/q2"]}, "extra_urls.0"),
        ({"extra_urls": [urls(1)[0], urls(1)[0] + "/?utm_source=x"]}, "extra_urls.1"),
    ],
)
def test_each_invalid_request_is_refused_naming_its_field(
    client: TestClient, filings: FakeFilings, change: dict[str, Any], field: str
) -> None:
    response = client.post("/api/runs", json=VALID | change)
    assert response.status_code == 422, response.text
    assert fields(response) == [field]
    assert client.get("/api/runs").json() == {"runs": []}
    assert filings.fetched == []


def test_messages_say_what_is_wrong(client: TestClient) -> None:
    [detail] = client.post("/api/runs", json=VALID | {"ticker": "nv da$"}).json()["details"]
    assert detail["message"].startswith("ticker must be 1 to 6 letters or digits")
    [detail] = client.post("/api/runs", json=VALID | {"extra_urls": ["http://10.0.0.1/"]}).json()[
        "details"
    ]
    assert detail["message"] == "Private or local network addresses are not allowed"
    [detail] = client.post(
        "/api/runs", json=VALID | {"extra_urls": [urls(1)[0], urls(1)[0] + "#top"]}
    ).json()["details"]
    assert detail["message"] == "Repeats URL 1 (the same page)"


def test_malformed_json_is_refused(client: TestClient) -> None:
    response = client.post(
        "/api/runs", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["error"] == "Invalid request"


def test_an_unknown_ticker_is_refused_before_a_run_starts(client: TestClient) -> None:
    response = client.post("/api/runs", json=VALID | {"ticker": "ZZZZ"})
    assert response.status_code == 422
    [detail] = response.json()["details"]
    assert detail["field"] == "ticker"
    assert "not in SEC's company list" in detail["message"]
    assert client.get("/api/runs").json() == {"runs": []}


def test_edgar_unreachable_is_a_503_that_says_so(client: TestClient, filings: FakeFilings) -> None:
    filings.company_error = SourceError("EDGAR could not be reached (ConnectError)")
    response = client.post("/api/runs", json=VALID)
    assert response.status_code == 503
    assert response.json() == {"error": "EDGAR could not be reached (ConnectError)"}


# The run lifecycle


def test_a_run_starts_executes_in_the_background_and_is_listed(client: TestClient) -> None:
    response = client.post("/api/runs", json=VALID)
    assert response.status_code == 202, response.text
    started = response.json()
    assert set(started) == {"id", "status"} and started["status"] == "running"
    record = wait_for(client, started["id"])
    assert record["status"] == RunStatus.partial  # the extractive engine judges no stance
    assert record["company"] == {"cik": 1045810, "ticker": "NVDA", "name": "NVIDIA CORP"}
    assert record["claims"][0]["verdict"] == Verdict.unjudged
    assert [e["excerpt"] for e in record["evidence"]] == [SENTENCE]
    assert record["finished_at"] is not None

    second = client.post("/api/runs", json=VALID).json()["id"]
    wait_for(client, second)
    listing = client.get("/api/runs").json()["runs"]
    assert [run["id"] for run in listing] == [second, started["id"]]
    assert listing[1] == {
        "id": started["id"],
        "status": "partial",
        "ticker": "NVDA",
        "company": "NVIDIA CORP",
        "started_at": record["started_at"],
        "claims": 1,
    }


def test_a_complete_run_with_a_judging_engine(tmp_path: Path) -> None:
    def supports(claim: object, passages: list[Any]) -> Any:
        from app.core.models import Confidence, Stance
        from app.core.ports import ClaimDraft, FindingDraft, Quote

        return ClaimDraft(
            findings=[
                FindingDraft(
                    "Revenue grew.",
                    Stance.supports,
                    [Quote(passages[0].id, SENTENCE)],
                    Confidence.high,
                    "Stated.",
                )
            ]
        )

    app = create_app(
        store=Store(tmp_path / "runs.sqlite"),
        filings=FakeFilings.synthetic(filing_html(SENTENCE)),
        analyst=ScriptedAnalyst(supports),
        fetch_page=FakePages({}),
    )
    with TestClient(app) as client:
        run_id = client.post("/api/runs", json=VALID).json()["id"]
        record = wait_for(client, run_id)
    assert record["status"] == RunStatus.complete, record["coverage_limits"]
    assert record["claims"][0]["verdict"] == Verdict.supported


def test_a_crash_inside_a_run_fails_it_with_a_finish_time(
    client: TestClient, filings: FakeFilings
) -> None:
    def explode(company: object, limit: int) -> list[Any]:
        raise RuntimeError("database password is hunter2")

    filings.periodic_filings = explode  # type: ignore[method-assign]
    run_id = client.post("/api/runs", json=VALID).json()["id"]
    record = wait_for(client, run_id)
    assert record["status"] == RunStatus.failed and record["finished_at"] is not None
    assert record["errors"] == ["The run stopped because of an internal error."]
    assert record["brief"] is None


def test_the_markdown_export_carries_the_record(client: TestClient) -> None:
    run_id = client.post("/api/runs", json=VALID).json()["id"]
    wait_for(client, run_id)
    response = client.get(f"/api/runs/{run_id}/export.md")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.text.startswith("# Evidence Desk brief: NVIDIA CORP (NVDA)")
    assert SENTENCE in response.text and "**Status: PARTIAL.**" in response.text


def test_unknown_runs_are_404(client: TestClient) -> None:
    for path in ("/api/runs/run-nope", "/api/runs/run-nope/export.md"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json() == {"detail": "Run not found"}


# Wording and health


def test_meta_gives_every_view_its_limits_and_wording(client: TestClient) -> None:
    meta = client.get("/api/meta").json()
    public = {name: getattr(limits, name) for name in dir(limits) if name.isupper()}
    assert meta["limits"] == public and "RUN_TIME_LIMIT_SECONDS" in meta["limits"]
    assert meta["status_notes"] == {status.value: note for status, note in STATUS_NOTES.items()}
    assert meta["verdict_labels"] == {v.value: label for v, label in VERDICT_LABELS.items()}
    assert meta["verdict_notes"] == {v.value: note for v, note in VERDICT_NOTES.items()}
    assert meta["provenance_note"] == PROVENANCE_NOTE
    assert meta["figures_note"] == FIGURES_NOTE
    assert meta["version"] == "0.3.0"
    assert meta["engine"] == "extractive"
    assert meta["example"] == EXAMPLE_THESIS.model_dump(mode="json")


def test_health(client: TestClient) -> None:
    assert client.get("/api/health").json() == {
        "status": "ok",
        "version": __version__,
        "engine": "extractive",
        "model": None,
    }
    assert __version__ == "0.3.0"


# Static files


@pytest.mark.parametrize(
    ("path", "media_type", "marker"),
    [
        ("/", "text/html", "Evidence Desk"),
        ("/app.js", "text/javascript", "/api/meta"),
        ("/styles.css", "text/css", "{"),
        ("/sample-run.json", "application/json", '"run"'),
    ],
)
def test_static_files_are_served(
    client: TestClient, path: str, media_type: str, marker: str
) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(media_type)
    assert marker in response.text


# Reported figures without a run


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def nvidia_filings() -> FakeFilings:
    return FakeFilings.nvidia()


@pytest.fixture
def metrics_client(
    tmp_path: Path, nvidia_filings: FakeFilings, clock: Clock
) -> Iterator[TestClient]:
    app = create_app(
        store=Store(tmp_path / "runs.sqlite"),
        filings=nvidia_filings,
        analyst=ExtractiveAnalyst(),
        fetch_page=FakePages({}),
        monotonic=clock,
    )
    with TestClient(app) as test_client:
        yield test_client


def test_metrics_for_a_ticker_without_a_run(metrics_client: TestClient) -> None:
    response = metrics_client.get("/api/companies/nvda/metrics")
    assert response.status_code == 200, response.text
    report = response.json()
    expected = build_report(FactBook(recorded_facts()))
    assert report == expected.model_dump(mode="json")
    assert report["cik"] == 1045810
    assert metrics_client.get("/api/runs").json() == {"runs": []}


def test_metrics_are_cached_for_fifteen_minutes_per_company(
    metrics_client: TestClient, nvidia_filings: FakeFilings, clock: Clock
) -> None:
    for _ in range(3):
        assert metrics_client.get("/api/companies/NVDA/metrics").status_code == 200
    assert nvidia_filings.facts_calls == 1
    clock.now += limits.METRICS_CACHE_SECONDS + 1
    assert metrics_client.get("/api/companies/NVDA/metrics").status_code == 200
    assert nvidia_filings.facts_calls == 2


@pytest.mark.parametrize("ticker", ["nv da$", "TOOLONGTICKER", "ZZZZ"])
def test_metrics_for_a_malformed_or_unknown_ticker_are_refused(
    metrics_client: TestClient, ticker: str
) -> None:
    response = metrics_client.get(f"/api/companies/{ticker}/metrics")
    assert response.status_code == 422
    assert fields(response) == ["ticker"]


def test_metrics_when_edgar_is_down_are_a_503_and_not_cached(
    metrics_client: TestClient, nvidia_filings: FakeFilings
) -> None:
    nvidia_filings.facts_error = SourceError("EDGAR could not be reached (ConnectError)")
    response = metrics_client.get("/api/companies/NVDA/metrics")
    assert response.status_code == 503
    assert response.json() == {"error": "EDGAR could not be reached (ConnectError)"}
    nvidia_filings.facts_error = None
    assert metrics_client.get("/api/companies/NVDA/metrics").status_code == 200


def test_metrics_from_malformed_facts_are_a_503(
    metrics_client: TestClient, nvidia_filings: FakeFilings
) -> None:
    nvidia_filings.facts = {"cik": 1045810, "entityName": "NVIDIA CORP", "facts": []}
    response = metrics_client.get("/api/companies/NVDA/metrics")
    assert response.status_code == 503
    assert "could not be read" in response.json()["error"]


# Sample records


def test_any_named_sample_record_is_served(client: TestClient) -> None:
    sample = WEB_DIR / "sample-zz-api-test.json"
    sample.write_text('{"run": {}}')
    try:
        response = client.get("/sample-zz-api-test.json")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert response.json() == {"run": {}}
    finally:
        sample.unlink()


@pytest.mark.parametrize(
    "path",
    [
        "/sample-missing.json",
        "/sample-..%2F..%2Fdocker%2Fpyproject.json",
        "/sample-../app.json",
        "/sample-%2e%2e.json",
        "/sample-UPPER.json",
        "/sample-" + "a" * 41 + ".json",
    ],
)
def test_unknown_or_unsafe_sample_names_are_404(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404
