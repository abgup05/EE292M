"""HTTP boundary: validation errors are clear, runs are retrievable, export is Markdown."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.store import Store
from app.synthesize import ExtractiveSynthesizer
from tests.test_pipeline import DECISION, QUESTION, fake_fetcher


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    app = create_app(
        store=Store(tmp_path / "runs.sqlite"),
        fetcher=fake_fetcher,
        synthesizer=ExtractiveSynthesizer(),
    )
    with TestClient(app) as test_client:
        yield test_client


def wait_for_run(client: TestClient, run_id: str) -> dict:
    for _ in range(100):
        record = client.get(f"/api/research/{run_id}").json()
        if record["status"] != "running":
            return record
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_start_and_fetch_run(client: TestClient) -> None:
    response = client.post(
        "/api/research",
        json={
            "question": QUESTION,
            "decision": DECISION,
            "seed_urls": ["https://www.nist.gov/rmf", "https://www.gao.gov/gen-ai"],
        },
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    record = wait_for_run(client, run_id)
    assert record["status"] == "partial"
    assert record["inputs"]["source_budget"] == 10
    assert len([s for s in record["sources"] if s["extraction_status"] == "extracted"]) == 2
    assert record["brief"]["findings"]
    assert all(f["verified"] for f in record["brief"]["findings"])
    listing = client.get("/api/research").json()
    assert [r["id"] for r in listing["runs"]] == [run_id]


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"question": "short", "decision": DECISION}, "question"),
        ({"question": QUESTION, "decision": ""}, "decision"),
        ({"question": QUESTION, "decision": DECISION, "source_budget": 5}, "source_budget"),
        ({"question": QUESTION, "decision": DECISION, "source_budget": 16}, "source_budget"),
        ({"question": QUESTION, "decision": DECISION, "seed_urls": ["nope"]}, "seed_urls"),
        (
            {"question": QUESTION, "decision": DECISION, "seed_urls": ["http://127.0.0.1/"]},
            "seed_urls",
        ),
        ({"question": QUESTION, "decision": DECISION, "scope_notes": "x" * 5001}, "scope_notes"),
    ],
)
def test_invalid_requests_are_rejected_clearly(client: TestClient, body: dict, field: str) -> None:
    response = client.post("/api/research", json=body)
    assert response.status_code == 422
    payload = response.json()
    assert payload["error"]
    assert any(detail["field"] == field for detail in payload["details"]), payload


def test_malformed_json_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/research", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["error"]


def test_unknown_run_is_404(client: TestClient) -> None:
    assert client.get("/api/research/run-nope").status_code == 404
    assert client.get("/api/research/run-nope/export.md").status_code == 404


def test_markdown_export(client: TestClient) -> None:
    run_id = client.post(
        "/api/research",
        json={
            "question": QUESTION,
            "decision": DECISION,
            "seed_urls": ["https://www.nist.gov/rmf"],
        },
    ).json()["id"]
    wait_for_run(client, run_id)
    response = client.get(f"/api/research/{run_id}/export.md")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "PARTIAL" in response.text
    assert "https://www.nist.gov/rmf" in response.text


def test_static_page_is_served(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Evidence Desk" in response.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/styles.css").status_code == 200
