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
from app.core.models import Confidence, RunStatus, Stance, ThesisRequest, Verdict
from app.core.policy import (
    DECISION_LABELS,
    FIGURES_NOTE,
    NO_CHECKER_NOTE,
    PROVENANCE_NOTE,
    REVIEW_NOTE,
    STATUS_NOTES,
    SUPPORT_LABELS,
    VERDICT_LABELS,
    VERDICT_NOTES,
)
from app.core.ports import ClaimDraft, FindingDraft, Quote, SourceError
from app.engines.extractive import ExtractiveAnalyst
from app.services.examples import EXAMPLE_THESIS
from app.services.export import READING_LIST_HEADING
from app.services.thesis_run import new_run
from app.store import Store
from tests.fakes import (
    FakeFilings,
    FakePages,
    ScriptedAnalyst,
    ScriptedChecker,
    filing_html,
    recorded_facts,
    synthetic_ref,
)

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


def test_the_tagged_figures_option_is_accepted_and_recorded(client: TestClient) -> None:
    response = client.post("/api/runs", json=VALID | {"tagged_figures": True})
    assert response.status_code == 202, response.text
    record = wait_for(client, response.json()["id"])
    assert record["inputs"]["tagged_figures"] is True
    assert "tagged_figures_offered" in record["coverage"]


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"tagged_figures": "yes"}, "tagged_figures"),
        ({"tagged_figures": 1}, "tagged_figures"),
        ({"tagged_figure": True}, "tagged_figure"),
        ({"question": "Is it growing?"}, "question"),
    ],
)
def test_a_malformed_option_or_an_unknown_field_is_refused_naming_it(
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


def test_a_second_run_through_the_api_reads_its_filings_from_the_cache(
    client: TestClient, filings: FakeFilings
) -> None:
    """The API hands every run the same filing cache, so a filing is fetched once."""
    first = wait_for(client, client.post("/api/runs", json=VALID).json()["id"])
    second = wait_for(client, client.post("/api/runs", json=VALID).json()["id"])
    assert first["status"] != "failed" and second["status"] != "failed"
    assert len(filings.fetched) == 1
    assert any("local cache" in limit for limit in second["coverage_limits"])


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
        "thesis_id": None,
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
    assert meta["decision_labels"] == DECISION_LABELS
    assert meta["review_note"] == REVIEW_NOTE
    assert meta["version"] == "0.11.1"
    assert meta["engine"] == "extractive"
    assert meta["checker"] == {"name": "none", "detail": ""}
    assert meta["support_labels"] == SUPPORT_LABELS
    assert meta["no_checker_note"] == NO_CHECKER_NOTE
    assert meta["example"] == EXAMPLE_THESIS.model_dump(mode="json")


def test_meta_names_the_checker_and_every_run_is_checked(tmp_path: Path) -> None:
    def supports(claim: object, passages: list[Any]) -> Any:
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

    checker = ScriptedChecker()
    app = create_app(
        store=Store(tmp_path / "runs.sqlite"),
        filings=FakeFilings.synthetic(filing_html(SENTENCE)),
        analyst=ScriptedAnalyst(supports),
        fetch_page=FakePages({}),
        checker=checker,
    )
    with TestClient(app) as client:
        meta = client.get("/api/meta").json()
        record = wait_for(client, client.post("/api/runs", json=VALID).json()["id"])
    assert meta["checker"] == {"name": "scripted-check", "detail": "scripted test checker"}
    assert record["checker"] == "scripted-check"
    assert record["findings"][0]["checks"]["support"] == "passed"
    assert record["coverage"]["findings_checked"] == 1
    assert list(checker.seen) == [CLAIM]


def test_an_injected_engine_without_a_checker_gets_no_checker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key in the environment does not attach the API checker to an engine a test injected."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    app = create_app(
        store=Store(tmp_path / "runs.sqlite"),
        filings=FakeFilings.synthetic(filing_html(SENTENCE)),
        analyst=ExtractiveAnalyst(),
        fetch_page=FakePages({}),
    )
    with TestClient(app) as client:
        assert client.get("/api/meta").json()["checker"]["name"] == "none"


def test_health(client: TestClient) -> None:
    assert client.get("/api/health").json() == {
        "status": "ok",
        "version": __version__,
        "engine": "extractive",
        "model": None,
    }
    assert __version__ == "0.11.1"


# Static files


@pytest.mark.parametrize(
    ("path", "media_type", "marker"),
    [
        ("/", "text/html", "Evidence Desk"),
        ("/app.js", "text/javascript", "/api/meta"),
        ("/styles.css", "text/css", "{"),
        ("/sample-run.json", "application/json", '"run"'),
        ("/sample-changes.json", "application/json", '"changes"'),
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


# Reviewer decisions

GROWTH = "Data Center revenue grew from a year ago, driven by demand for Blackwell."
SLOWING = "Data Center revenue growth slowed sequentially as supply tightened."
GAMING_CLAIM = "Gaming revenue is still growing year over year."
GAMING = "Gaming revenue grew from a year ago on demand for new graphics cards."
NOT_IN_FILING = "Data Center revenue tripled, a sentence that is not in the filing."


def draft(statement: str, stance: Stance, passage: Any, text: str) -> FindingDraft:
    return FindingDraft(statement, stance, [Quote(passage.id, text)], Confidence.high, "Stated.")


def mixed_assessment(claim: Any, passages: list[Any]) -> ClaimDraft:
    """A supporting and a challenging finding, and one whose quote is not in the filing."""
    passage = passages[0]
    return ClaimDraft(
        findings=[
            draft("Revenue grew.", Stance.supports, passage, GROWTH),
            draft("Growth slowed.", Stance.challenges, passage, SLOWING),
            draft("Revenue tripled.", Stance.supports, passage, NOT_IN_FILING),
        ]
    )


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    record = Store(tmp_path / "record.sqlite")
    yield record
    record.close()


@pytest.fixture
def review_client(store: Store) -> Iterator[TestClient]:
    app = create_app(
        store=store,
        filings=FakeFilings.synthetic(filing_html(GROWTH, SLOWING)),
        analyst=ScriptedAnalyst(mixed_assessment),
        fetch_page=FakePages({}),
    )
    with TestClient(app) as test_client:
        yield test_client


def decide(client: TestClient, run_id: str, finding_id: str, body: dict[str, Any]) -> Any:
    return client.put(f"/api/runs/{run_id}/findings/{finding_id}/decision", json=body)


def test_the_review_flow_recomputes_the_verdict_after_each_decision(
    review_client: TestClient,
) -> None:
    client = review_client
    run_id = client.post("/api/runs", json=VALID).json()["id"]
    record = wait_for(client, run_id)
    assert record["claims"][0]["verdict"] == Verdict.mixed
    support, challenge = (f["id"] for f in record["findings"])
    [withheld] = (f["id"] for f in record["unsupported_findings"])

    review = client.get(f"/api/runs/{run_id}/review").json()
    assert review["run_id"] == run_id and review["decisions"] == []
    assert (review["findings_total"], review["decided"], review["complete"]) == (2, 0, False)
    assert review["claims"] == [
        {
            "claim_id": "c1",
            "engine_verdict": "mixed",
            "reviewed_verdict": None,
            "accepted": 0,
            "rejected": 0,
            "undecided": 2,
        }
    ]

    def reviewed(response: Any) -> tuple[str | None, int, bool]:
        assert response.status_code == 200, response.text
        body = response.json()
        claim = body["claims"][0]
        assert claim["engine_verdict"] == "mixed"
        assert body == client.get(f"/api/runs/{run_id}/review").json()
        return claim["reviewed_verdict"], body["decided"], body["complete"]

    accepted = decide(client, run_id, support, {"value": "accepted", "note": "  Matches.  "})
    assert reviewed(accepted) == ("supported", 1, False)
    [decision] = accepted.json()["decisions"]
    assert decision["finding_id"] == support and decision["note"] == "Matches."
    assert decision["value"] == "accepted" and decision["decided_at"]

    rejected = decide(client, run_id, challenge, {"value": "rejected"})
    assert reviewed(rejected) == ("supported", 2, True)

    cleared = decide(client, run_id, support, {"value": None})
    assert reviewed(cleared) == ("not_addressed", 1, False)

    replaced = decide(client, run_id, challenge, {"value": "accepted", "note": "On reflection."})
    assert reviewed(replaced) == ("challenged", 1, False)
    [decision] = replaced.json()["decisions"]
    assert (decision["value"], decision["note"]) == ("accepted", "On reflection.")

    refused = decide(client, run_id, withheld, {"value": "accepted"})
    assert refused.status_code == 422 and fields(refused) == ["finding_id"]

    unknown = decide(client, run_id, "f99", {"value": "accepted"})
    assert unknown.status_code == 404 and unknown.json() == {"detail": "Finding not found"}

    long_note = {"value": "rejected", "note": "x" * (limits.MAX_NOTE_CHARS + 1)}
    too_long = decide(client, run_id, support, long_note)
    assert too_long.status_code == 422 and fields(too_long) == ["note"]

    bad_value = decide(client, run_id, support, {"value": "maybe"})
    assert bad_value.status_code == 422 and fields(bad_value) == ["value"]

    # Nothing refused was kept.
    assert client.get(f"/api/runs/{run_id}/review").json()["decided"] == 1


def test_a_running_run_cannot_be_decided(review_client: TestClient, store: Store) -> None:
    run = new_run(ThesisRequest.model_validate(VALID))
    store.save_run(run)
    response = decide(review_client, run.id, "f1", {"value": "accepted"})
    assert response.status_code == 409
    assert set(response.json()) == {"error"} and "running" in response.json()["error"]


def test_the_reviewed_export_carries_the_decisions(review_client: TestClient) -> None:
    client = review_client
    run_id = client.post("/api/runs", json=VALID).json()["id"]
    record = wait_for(client, run_id)
    support, challenge = (f["id"] for f in record["findings"])
    decide(client, run_id, support, {"value": "accepted", "note": "Matches the table."})
    decide(client, run_id, challenge, {"value": "rejected"})

    plain = client.get(f"/api/runs/{run_id}/export.md").text
    assert "## Your review" not in plain and DECISION_LABELS["accepted"] not in plain
    response = client.get(f"/api/runs/{run_id}/export.md", params={"reviewed": "true"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    reviewed = response.text
    assert "## Your review" in reviewed and REVIEW_NOTE in reviewed
    assert "- Your decision: Accepted. Matches the table." in reviewed
    assert "- Your decision: Rejected." in reviewed
    assert "After your review" in reviewed
    assert "This brief includes the reviewer's decisions as of" in reviewed


# Saved theses


class TwoAnswers:
    """Supports the data-center claim on its first assessment and challenges it after."""

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}

    def __call__(self, claim: Any, passages: list[Any]) -> ClaimDraft:
        count = self.calls[claim.text] = self.calls.get(claim.text, 0) + 1
        passage = passages[0]
        if claim.text == GAMING_CLAIM:
            return ClaimDraft(findings=[draft("Gaming grew.", Stance.supports, passage, GAMING)])
        if count == 1:
            return ClaimDraft(findings=[draft("Revenue grew.", Stance.supports, passage, GROWTH)])
        return ClaimDraft(findings=[draft("Growth slowed.", Stance.challenges, passage, SLOWING)])


THESIS = {
    "name": "NVIDIA after earnings",
    "request": VALID | {"claims": [CLAIM, GAMING_CLAIM]},
}


@pytest.fixture
def thesis_filings() -> FakeFilings:
    return FakeFilings.synthetic(filing_html(GROWTH, SLOWING, GAMING))


@pytest.fixture
def thesis_client(store: Store, thesis_filings: FakeFilings) -> Iterator[TestClient]:
    app = create_app(
        store=store,
        filings=thesis_filings,
        analyst=ScriptedAnalyst(TwoAnswers()),
        fetch_page=FakePages({}),
    )
    with TestClient(app) as test_client:
        yield test_client


def run_thesis(client: TestClient, thesis_id: str) -> dict[str, Any]:
    response = client.post(f"/api/theses/{thesis_id}/runs")
    assert response.status_code == 202, response.text
    started = response.json()
    assert set(started) == {"id", "status"} and started["status"] == "running"
    return wait_for(client, started["id"])


def test_a_saved_thesis_runs_twice_and_says_what_moved(
    thesis_client: TestClient, thesis_filings: FakeFilings
) -> None:
    client = thesis_client
    created = client.post("/api/theses", json=THESIS)
    assert created.status_code == 201, created.text
    thesis = created.json()
    assert thesis["id"].startswith("th-") and thesis["name"] == "NVIDIA after earnings"
    assert thesis["request"]["claims"] == [CLAIM, GAMING_CLAIM] and thesis["run_ids"] == []

    listing = client.get("/api/theses").json()
    assert listing == {
        "theses": [
            {
                "id": thesis["id"],
                "name": "NVIDIA after earnings",
                "ticker": "NVDA",
                "claims": 2,
                "created_at": thesis["created_at"],
                "runs": 0,
                "last_run_id": None,
                "last_status": None,
            }
        ]
    }

    first = run_thesis(client, thesis["id"])
    assert first["thesis_id"] == thesis["id"]
    assert [c["verdict"] for c in first["claims"]] == ["supported", "supported"]
    changes = client.get(f"/api/theses/{thesis['id']}/changes")
    assert changes.status_code == 409
    assert changes.json() == {"error": "This thesis has fewer than two finished runs to compare."}

    # A new 10-Q arrives: it is now the one filing read.
    newer = synthetic_ref(2)
    thesis_filings.refs.insert(0, newer)
    thesis_filings.documents[newer.url] = filing_html(GROWTH, SLOWING, GAMING)
    second = run_thesis(client, thesis["id"])
    assert [c["verdict"] for c in second["claims"]] == ["challenged", "supported"]

    detail = client.get(f"/api/theses/{thesis['id']}").json()
    assert detail["thesis"]["run_ids"] == [second["id"], first["id"]]
    assert detail["runs"] == [
        {
            "id": run["id"],
            "status": run["status"],
            "started_at": run["started_at"],
            "finished_at": run["finished_at"],
        }
        for run in (second, first)
    ]
    [summary] = client.get("/api/theses").json()["theses"]
    assert (summary["runs"], summary["last_run_id"], summary["last_status"]) == (
        2,
        second["id"],
        "complete",
    )
    runs = {run["id"]: run["thesis_id"] for run in client.get("/api/runs").json()["runs"]}
    assert runs == {first["id"]: thesis["id"], second["id"]: thesis["id"]}

    comparison = client.get(f"/api/theses/{thesis['id']}/changes").json()
    assert comparison["thesis_id"] == thesis["id"]
    assert (comparison["earlier_run_id"], comparison["later_run_id"]) == (first["id"], second["id"])
    assert [(c["claim"], c["before"], c["after"], c["moved"]) for c in comparison["claims"]] == [
        (CLAIM, "supported", "challenged", True),
        (GAMING_CLAIM, "supported", "supported", False),
    ]
    assert (comparison["verdicts_moved"], comparison["claims_total"]) == (1, 2)
    assert len(comparison["sources_added"]) == 1 and len(comparison["sources_dropped"]) == 1
    # The gaming excerpt is the same text, but in a different filing: one in, one out.
    gaming = comparison["claims"][1]
    assert (gaming["excerpts_added"], gaming["excerpts_dropped"]) == (1, 1)
    assert comparison["note"].startswith("1 of 2 verdicts moved; 1 filing is new: ")


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"name": " "}, "name"),
        ({"name": "x" * (limits.MAX_THESIS_NAME_CHARS + 1)}, "name"),
        ({"request": VALID | {"ticker": "ZZZZ"}}, "request.ticker"),
        ({"request": VALID | {"claims": []}}, "request.claims"),
        ({"request": VALID | {"extra_urls": ["http://10.0.0.1/"]}}, "request.extra_urls.0"),
    ],
)
def test_an_invalid_thesis_is_refused_naming_its_field(
    thesis_client: TestClient, change: dict[str, Any], field: str
) -> None:
    response = thesis_client.post("/api/theses", json=THESIS | change)
    assert response.status_code == 422, response.text
    assert fields(response) == [field]
    assert thesis_client.get("/api/theses").json() == {"theses": []}


def test_unknown_theses_and_review_routes_are_404(thesis_client: TestClient) -> None:
    client = thesis_client
    for method, path, detail in [
        ("GET", "/api/theses/th-000000000000", "Thesis not found"),
        ("POST", "/api/theses/th-000000000000/runs", "Thesis not found"),
        ("GET", "/api/theses/th-000000000000/changes", "Thesis not found"),
        ("GET", "/api/runs/run-nope/review", "Run not found"),
        ("GET", "/api/runs/run-nope/export.md?reviewed=true", "Run not found"),
    ]:
        response = client.request(method, path)
        assert response.status_code == 404, path
        assert response.json() == {"detail": detail}
    response = decide(client, "run-nope", "f1", {"value": "accepted"})
    assert response.status_code == 404 and response.json() == {"detail": "Run not found"}


# What changed between a company's two latest filings of one form


@pytest.fixture
def changes_client(tmp_path: Path) -> Iterator[TestClient]:
    from tests.test_filing_changes import two_annual_reports

    app = create_app(
        store=Store(tmp_path / "runs.sqlite"),
        filings=two_annual_reports(),
        analyst=ExtractiveAnalyst(),
        fetch_page=FakePages({}),
    )
    with TestClient(app) as test_client:
        yield test_client


def test_filing_changes_for_a_ticker(changes_client: TestClient) -> None:
    response = changes_client.get("/api/companies/NVDA/changes?form=10-K")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["earlier"]["form"] == body["later"]["form"] == "10-K"
    risk = next(item for item in body["items"] if item["item"].startswith("Item 1A"))
    assert risk["added"] == 1 and risk["removed"] == 1
    assert len(risk["added_paragraphs"]) == 1 and len(risk["removed_paragraphs"]) == 1
    assert risk["added_paragraphs"][0]["link"].startswith("https://www.sec.gov/")


def test_filing_changes_default_to_the_annual_report(changes_client: TestClient) -> None:
    assert changes_client.get("/api/companies/NVDA/changes").json()["later"]["form"] == "10-K"


def test_filing_changes_refuse_another_form_and_an_unknown_ticker(
    changes_client: TestClient,
) -> None:
    refused = changes_client.get("/api/companies/NVDA/changes?form=8-K")
    assert refused.status_code == 422 and fields(refused) == ["form"]
    unknown = changes_client.get("/api/companies/ZZZZ/changes")
    assert unknown.status_code == 422 and fields(unknown) == ["ticker"]


def test_filing_changes_with_one_filing_of_the_form_are_a_503_that_says_so(
    changes_client: TestClient,
) -> None:
    response = changes_client.get("/api/companies/NVDA/changes?form=10-Q")
    assert response.status_code == 503 and "10-Q" in response.json()["error"]


# What changed in the filings a run read, under each claim


@pytest.fixture
def run_changes_client(tmp_path: Path) -> Iterator[tuple[TestClient, str, Any]]:
    """A client over a stored, finished run whose two filings each have an earlier one."""
    from app.store import FilingCache
    from tests.test_claim_changes import filings_of_a_year, finished_run

    filings = filings_of_a_year()
    cache = FilingCache()
    store = Store(tmp_path / "runs.sqlite")
    run = finished_run(filings, cache)
    store.save_run(run)
    app = create_app(
        store=store,
        filings=filings,
        analyst=ExtractiveAnalyst(),
        fetch_page=FakePages({}),
        cache=cache,
    )
    with TestClient(app) as test_client:
        yield test_client, run.id, filings


def test_the_changes_of_a_run_are_listed_under_each_of_its_claims(run_changes_client) -> None:
    client, run_id, _ = run_changes_client
    response = client.get(f"/api/runs/{run_id}/changes")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run_id"] == run_id and body["notes"] == []
    assert [claim["claim_id"] for claim in body["claims"]] == ["china", "margin"]
    assert {pair["form"] for pair in body["compared"]} == {"10-K", "10-Q"}
    china = body["claims"][0]
    added = [change for change in china["changes"] if change["kind"] == "added"]
    assert added and added[0]["form"] == "10-K"
    assert added[0]["paragraph"]["link"].startswith("https://www.sec.gov/")
    assert {"china", "export"} <= set(added[0]["matched_terms"])
    assert china["matched"] <= china["considered"]


def test_the_changes_of_a_finished_run_are_computed_once(run_changes_client) -> None:
    client, run_id, filings = run_changes_client
    first = client.get(f"/api/runs/{run_id}/changes").json()
    asked = len(filings.form_calls)
    assert asked > 0
    assert client.get(f"/api/runs/{run_id}/changes").json() == first
    assert len(filings.form_calls) == asked, "the second answer came from the cache"


def test_the_brief_carries_the_reading_list_only_when_asked(run_changes_client) -> None:
    client, run_id, _ = run_changes_client
    plain = client.get(f"/api/runs/{run_id}/export.md")
    assert plain.status_code == 200 and READING_LIST_HEADING not in plain.text
    listed = client.get(f"/api/runs/{run_id}/export.md?changes=true")
    assert listed.status_code == 200 and listed.headers["content-type"].startswith("text/markdown")
    assert f"## {READING_LIST_HEADING}" in listed.text
    assert "A reading list, not findings" in listed.text and "### china:" in listed.text


def test_the_changes_of_an_unknown_run_are_a_404(run_changes_client) -> None:
    client, _, _ = run_changes_client
    response = client.get("/api/runs/run-does-not-exist/changes")
    assert response.status_code == 404 and response.json() == {"detail": "Run not found"}


def test_a_source_that_cannot_list_a_form_gives_a_note_and_not_an_error(
    tmp_path: Path,
) -> None:
    from app.store import FilingCache
    from tests.test_claim_changes import filings_of_a_year, finished_run

    listing, cache = filings_of_a_year(), FilingCache()
    store = Store(tmp_path / "runs.sqlite")
    run = finished_run(listing, cache)
    store.save_run(run)
    plain = FakeFilings(refs=listing.refs, documents=listing.documents)  # no filings_of_form
    app = create_app(
        store=store,
        filings=plain,
        analyst=ExtractiveAnalyst(),
        fetch_page=FakePages({}),
        cache=cache,
    )
    with TestClient(app) as test_client:
        body = test_client.get(f"/api/runs/{run.id}/changes").json()
    assert body["compared"] == [] and len(body["notes"]) >= 1
    assert [claim["changes"] for claim in body["claims"]] == [[], []]


# Segments, geographies and customers from a filing's tagged facts


@pytest.fixture
def breakdowns_client(tmp_path: Path) -> Iterator[TestClient]:
    """A client whose filings are the recorded NVIDIA annual and quarterly reports."""
    from tests.test_breakdowns import nvidia

    app = create_app(
        store=Store(tmp_path / "runs.sqlite"),
        filings=nvidia(),
        analyst=ExtractiveAnalyst(),
        fetch_page=FakePages({}),
    )
    with TestClient(app) as test_client:
        yield test_client


def test_breakdowns_of_the_latest_annual_report(breakdowns_client: TestClient) -> None:
    response = breakdowns_client.get("/api/companies/NVDA/breakdowns?form=10-K")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["filing"]["form"] == "10-K" and body["company"]["ticker"] == "NVDA"
    assert body["filing"]["url"].startswith("https://www.sec.gov/")
    found = {item["id"] for item in body["breakdowns"]}
    assert {"revenue_by_segment", "revenue_by_product", "revenue_by_geography"} <= found
    assert body["facts_read"] > 500 and body["facts_unparsed"] == 0


def test_breakdowns_default_to_the_annual_report_and_take_the_quarterly(
    breakdowns_client: TestClient,
) -> None:
    default = breakdowns_client.get("/api/companies/NVDA/breakdowns")
    assert default.json()["filing"]["form"] == "10-K"
    quarterly = breakdowns_client.get("/api/companies/NVDA/breakdowns?form=10-Q")
    assert quarterly.status_code == 200 and quarterly.json()["filing"]["form"] == "10-Q"


def test_breakdowns_refuse_another_form_and_an_unknown_ticker(
    breakdowns_client: TestClient,
) -> None:
    refused = breakdowns_client.get("/api/companies/NVDA/breakdowns?form=8-K")
    assert refused.status_code == 422 and fields(refused) == ["form"]
    unknown = breakdowns_client.get("/api/companies/ZZZZ/breakdowns")
    assert unknown.status_code == 422 and fields(unknown) == ["ticker"]


def test_breakdowns_when_edgar_cannot_list_the_filing_are_a_503(tmp_path: Path) -> None:
    from tests.test_breakdowns import nvidia

    source = nvidia()
    source.index_error = SourceError("the filing index of NVIDIA CORP is unavailable")
    app = create_app(
        store=Store(tmp_path / "runs.sqlite"),
        filings=source,
        analyst=ExtractiveAnalyst(),
        fetch_page=FakePages({}),
    )
    with TestClient(app) as test_client:
        response = test_client.get("/api/companies/NVDA/breakdowns")
    assert response.status_code == 503 and "unavailable" in response.json()["error"]
