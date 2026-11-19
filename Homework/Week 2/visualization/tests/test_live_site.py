"""The guard, the held run start and /live/status of the live versions (src/live)."""

from __future__ import annotations

import asyncio
import json
from datetime import date

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from test_snapshots import call

import live.site as site_module
from app.api import LIVE
from live.guard import (
    Caps,
    Guard,
    Refusal,
    check_body,
    check_request,
    client_of,
    costly_read,
)
from live.seed import Seed
from live.site import LiveVersionApp
from live.versions import VENDOR_DIR, build


def test_shim_carries_this_versions_settings():
    status, headers, body = call("/v14/live-shim.js")
    assert status == 200
    assert headers["content-type"].startswith("text/javascript")
    text = body.decode()
    assert "/*LIVE*/null" not in text
    assert '"base": "/v14/"' in text
    assert '"ref": "capstone-v14"' in text


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("DELETE", "/v14/api/theses/t1"),
        ("DELETE", "/v4/api/runs/r1"),
        ("POST", "/v14/api/backup"),
        ("PUT", "/v14/api/runs/r1"),
        ("PATCH", "/v2/api/runs"),
        ("POST", "/v1/api/runs"),
    ],
)
def test_writes_the_page_does_not_make_are_refused(method, path):
    status, _, body = call(path, method)
    assert status == 405
    assert "turned off on the public server" in json.loads(body)["error"]


def test_visitor_supplied_urls_are_refused_before_the_version_sees_them():
    request = {
        "ticker": "NVDA",
        "decision": "x" * 20,
        "claims": ["a claim"],
        "extra_urls": ["http://169.254.169.254/"],
    }
    status, _, body = call("/v14/api/runs", "POST", json.dumps(request).encode())
    assert status == 422
    payload = json.loads(body)
    assert payload["details"][0]["field"] == "extra_urls.0"
    thesis = {"name": "n", "request": request}
    status, _, body = call("/v9/api/theses", "POST", json.dumps(thesis).encode())
    assert status == 422
    assert json.loads(body)["details"][0]["field"] == "request.extra_urls.0"


def test_version_1_reads_only_its_examples_pages():
    request = {
        "question": "q" * 30,
        "decision": "d" * 20,
        "seed_urls": ["http://127.0.0.1:8000/"],
    }
    status, _, body = call("/v1/api/research", "POST", json.dumps(request).encode())
    assert status == 422
    assert "two pages of its own example" in json.loads(body)["details"][0]["message"]
    assert (
        check_body(
            "research",
            "POST",
            "/api/research",
            json.dumps(
                {"seed_urls": ["https://www.gao.gov/products/gao-24-106946"]}
            ).encode(),
        )
        is None
    )


def test_a_long_body_and_a_long_query_are_refused():
    status, _, _ = call(
        "/v14/api/runs",
        "POST",
        b"{" + b" " * (LIVE.caps.LIVE_MAX_BODY_BYTES + 1) + b"}",
    )
    assert status == 413
    assert (
        check_request(
            "thesis", "GET", "/api/meta", b"q=" + b"x" * 3000, LIVE.caps
        ).status
        == 414
    )


def test_caps_come_from_the_environment_and_bad_values_are_named():
    caps, invalid = Caps.from_env(
        {
            "LIVE_MODEL_RUNS_PER_DAY": "5",
            "LIVE_RUNS_AT_ONCE": "two",
            "LIVE_HOLD_SECONDS": "100000",
        }
    )
    assert caps.LIVE_MODEL_RUNS_PER_DAY == 5
    assert caps.LIVE_RUNS_AT_ONCE == Caps().LIVE_RUNS_AT_ONCE
    assert caps.LIVE_HOLD_SECONDS == 790
    assert invalid == ["LIVE_RUNS_AT_ONCE"]


def test_one_model_run_at_a_time_and_a_daily_cap_per_client():
    day = [date(2026, 11, 18)]
    guard = Guard(
        Caps(LIVE_MODEL_RUNS_PER_CLIENT_PER_DAY=2),
        today=lambda: day[0],
        environ={"ANTHROPIC_API_KEY": "configured"},
    )
    first = guard.admit_run("a")
    assert not isinstance(first, Refusal)
    first.accept()
    busy = guard.admit_run("b")
    assert (
        isinstance(busy, Refusal)
        and busy.status == 429
        and "one at a time" in busy.message
    )
    first.release()
    second = guard.admit_run("a")
    second.accept()
    second.release()
    over = guard.admit_run("a")
    assert isinstance(over, Refusal) and "per visitor" in over.message
    assert not isinstance(guard.admit_run("b"), Refusal)
    day[0] = date(2026, 11, 19)
    assert guard.counts()["model_runs_today"] == 0


def test_without_a_key_runs_are_not_model_runs_and_have_their_own_cap():
    guard = Guard(Caps(LIVE_RUNS_PER_CLIENT_PER_DAY=1, LIVE_RUNS_AT_ONCE=5), environ={})
    first = guard.admit_run("a")
    assert not isinstance(first, Refusal) and not first.model
    first.accept()
    other = guard.admit_run("b")  # a second run at once is fine without a model
    assert not isinstance(other, Refusal)
    first.release()
    other.release()
    assert isinstance(guard.admit_run("a"), Refusal)


def test_the_client_is_the_address_vercel_reports_and_only_on_vercel():
    vercel = {"VERCEL": "1"}
    headers = {"x-vercel-forwarded-for": "203.0.113.9", "x-forwarded-for": "1.2.3.4"}
    assert client_of(headers, "c", vercel) == "203.0.113.9"
    assert (
        client_of({"x-forwarded-for": "198.51.100.7, 10.0.0.1"}, "c", vercel)
        == "198.51.100.7"
    )
    assert client_of({}, "fallback", vercel) == "fallback"
    # Off Vercel nothing stands in front of the process: a header is the visitor's own word.
    assert client_of(headers, "192.0.2.5", {}) == "192.0.2.5"


def test_a_spoofed_forwarding_header_does_not_buy_more_runs(held, monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setattr(LIVE.guard, "caps", Caps(LIVE_RUNS_PER_CLIENT_PER_DAY=1))
    monkeypatch.setattr(LIVE.guard, "_client_runs", {})
    first = asgi(
        held, "/v2/api/runs", "POST", b"{}", [(b"x-forwarded-for", b"198.51.100.1")]
    )
    again = asgi(
        held, "/v2/api/runs", "POST", b"{}", [(b"x-forwarded-for", b"198.51.100.2")]
    )
    assert first[0] == 202
    assert again[0] == 429 and "per visitor" in json.loads(again[2])["error"]


def test_every_run_start_address_passes_the_guard_whoever_calls_it(held, monkeypatch):
    """Without the shim's header and whatever the address, a run start is counted."""
    monkeypatch.setattr(LIVE.guard, "caps", Caps(LIVE_RUNS_PER_DAY=0))
    for path in ("/v2/api/runs", "/v2/api/theses/t1/runs", "/v2/api/inbox/i1/run"):
        status, _, body = asgi(held, path, "POST", b"{}", [])
        assert status == 429, path
        assert "runs for today" in json.loads(body)["error"]


def test_removing_a_watch_is_let_through_and_nothing_else_is_deleted():
    assert (
        check_request("thesis", "DELETE", "/api/theses/t1/watch", b"", LIVE.caps)
        is None
    )
    for path in (
        "/api/theses/t1",
        "/api/runs/r1",
        "/api/inbox/i1",
        "/api/theses/t1/watch/",
    ):
        assert check_request("thesis", "DELETE", path, b"", LIVE.caps).status == 405, (
            path
        )


def test_a_brief_with_its_changes_counts_as_a_costly_read():
    assert costly_read("GET", "/api/companies/NVDA/metrics", b"")
    assert costly_read("GET", "/api/runs/r1/export.md", b"reviewed=true&changes=true")
    assert not costly_read("GET", "/api/runs/r1/export.md", b"reviewed=true")
    assert not costly_read("GET", "/api/runs/r1", b"")


def test_a_version_that_cannot_be_built_is_answered_by_its_recording(monkeypatch):
    version = LIVE.versions[14]
    monkeypatch.setattr(version, "app", None)
    monkeypatch.setattr(version, "error", "ImportError")
    status, _, body = call("/v14/")
    assert status == 200
    page = body.decode()
    assert 'data-snapshot-version="14"' in page and "data-live-version" not in page
    assert call("/v14/snapshot.js")[0] == 200
    assert call("/v14/api/runs", "POST", b"{}")[0] == 405
    report = json.loads(call("/live/status")[2])
    assert report["versions"]["14"]["serving"] == "recorded"
    assert report["versions"]["14"]["import_error"] == "ImportError"


def test_status_reports_booleans_and_counts_never_the_values(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key-0123456789")
    monkeypatch.setenv("SEC_USER_AGENT", "Placeholder Contact placeholder-contact")
    status, _, body = call("/live/status")
    assert status == 200
    assert b"not-a-real-key" not in body and b"Placeholder" not in body
    report = json.loads(body)
    assert report["key_present"] is True
    assert report["sec_user_agent_present"] is True
    assert report["model_engine"] == "on"
    assert set(report["versions"]) == {str(n) for n in LIVE.versions}
    assert "per server instance" in report["caps_scope"]
    page = call("/v14/")[2].decode()
    assert "model engine on" in page and "not hard totals" in page
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert "The model engine is off on this server" in call("/v14/")[2].decode()


def test_versions_13_and_later_say_no_watcher_runs_online():
    assert "no watcher runs online" in call("/v13/")[2].decode()
    assert "no watcher runs online" not in call("/v12/")[2].decode()


# -- the held run start, against a stand-in for a version's app


def stand_in() -> FastAPI:
    """A version-shaped app whose run is running for two reads, then complete."""
    app = FastAPI()
    reads = {"r1": 0}

    @app.post("/api/runs", status_code=202)
    async def start(request: Request) -> dict:
        await request.body()
        return {"id": "r1", "status": "running"}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        reads[run_id] += 1
        status = "running" if reads[run_id] <= 2 else "complete"
        return {"id": run_id, "status": status, "findings": [reads[run_id]]}

    @app.get("/api/runs/{run_id}/review")
    def review(run_id: str) -> dict:
        return {"run_id": run_id, "decisions": []}

    @app.get("/api/runs/{run_id}/export.md")
    def brief(run_id: str) -> PlainTextResponse:
        return PlainTextResponse(f"# {run_id}", media_type="text/markdown")

    return app


@pytest.fixture
def held(monkeypatch):
    monkeypatch.setattr(site_module, "POLL_SECONDS", 0.01)
    monkeypatch.setattr(site_module, "PROGRESS_SECONDS", 0.0)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    version = LIVE.versions[2]
    saved = version.app
    version.app = stand_in()
    yield LiveVersionApp(LIVE, 2)
    version.app = saved


def asgi(
    app, path: str, method: str, body: bytes, headers: list
) -> tuple[int, dict, bytes]:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"t"), *headers],
        "client": ("192.0.2.1", 1),
        "server": ("t", 80),
    }
    messages: list[dict] = []
    sent = False

    async def receive() -> dict:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    return (
        start["status"],
        {k.decode(): v.decode() for k, v in start["headers"]},
        b"".join(
            m.get("body", b"") for m in messages if m["type"] == "http.response.body"
        ),
    )


def test_a_run_start_is_held_until_the_run_has_finished(held):
    status, headers, body = asgi(
        held, "/v2/api/runs", "POST", b"{}", [(b"x-live-hold", b"ndjson")]
    )
    assert status == 200
    assert headers["content-type"] == "application/x-ndjson"
    lines = [json.loads(line) for line in body.decode().splitlines()]
    assert lines[0]["kind"] == "started"
    assert lines[0]["status"] == 202 and lines[0]["body"] == {
        "id": "r1",
        "status": "running",
    }
    assert lines[0]["run"]["status"] == "running"
    assert lines[-1]["kind"] == "finished"
    assert lines[-1]["run"]["status"] == "complete"
    assert (
        json.loads(lines[-1]["extras"]["/api/runs/r1/review"]["body"])["run_id"] == "r1"
    )
    assert lines[-1]["extras"]["/api/runs/r1/export.md"]["body"] == "# r1"
    assert LIVE.guard.counts()["runs_in_progress"] == 0


def test_without_the_shim_the_answer_is_the_versions_own_once_the_run_has_finished(
    held,
):
    status, headers, body = asgi(held, "/v2/api/runs", "POST", b"{}", [])
    assert status == 202
    assert headers["content-type"] == "application/json"
    assert json.loads(body) == {"id": "r1", "status": "running"}


def test_the_owner_can_switch_every_version_to_its_recording(monkeypatch):
    monkeypatch.setenv("LIVE_VERSIONS", "off")
    page = call("/v3/")[2].decode()
    assert 'data-snapshot-version="3"' in page and "data-live-version" not in page
    assert call("/v3/api/runs", "POST", b"{}")[0] == 405
    report = json.loads(call("/live/status?imports=true")[2])
    assert report["live_versions"].startswith("off")
    assert {state["serving"] for state in report["versions"].values()} == {"recorded"}
    monkeypatch.delenv("LIVE_VERSIONS")
    assert 'data-live-version="3"' in call("/v3/")[2].decode()


# -- EDGAR refusing the server, as it does on Vercel without a contact string


class Refusing(httpx.BaseTransport):
    """EDGAR as it answered the deployed site: 403 from www.sec.gov, nothing else reachable."""

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.sec.gov":
            return httpx.Response(403, request=request)
        raise httpx.ConnectError("unreachable", request=request)


def version_behind(
    network: httpx.BaseTransport, tmp_path, monkeypatch, number: int = 14
):
    monkeypatch.setenv("LIVE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    seed = Seed(VENDOR_DIR / "seed")
    return build(LIVE.versions[number].info, seed, network), seed


@pytest.mark.parametrize("number", [2, 14])
def test_a_company_outside_the_recorded_list_is_not_called_unknown_to_sec(
    number, tmp_path, monkeypatch
):
    """The seed's list holds five tickers; "not in SEC's company list" would be false."""
    app, seed = version_behind(Refusing(), tmp_path, monkeypatch, number)
    request = {
        "ticker": "COST",
        "decision": "d" * 20,
        "claims": ["Revenue is growing."],
    }
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "scheme": "http",
        "root_path": "",
        "query_string": b"",
        "client": ("192.0.2.1", 1),
        "server": ("t", 80),
        "headers": [(b"host", b"t"), (b"content-type", b"application/json")],
    }
    status, _, body = asyncio.run(
        site_module.call(app, scope, "POST", "/api/runs", json.dumps(request).encode())
    )
    message = json.loads(body)["error"]
    assert status == 503, body
    assert "not in SEC's company list" not in message
    assert "COST could not be looked up" in message and "HTTP 403" in message
    assert "holds only AAPL, NVDA, MSFT, BRK-B, KO" in message
    assert "no SEC contact string set" in message
    assert seed.edgar()["www.sec.gov"] == {"HTTP 403": 1}
    # A company the recording does hold is still found (saving a thesis looks it up).
    if number >= 4:
        request["ticker"] = "NVDA"
        thesis = json.dumps({"name": "n", "request": request}).encode()
        status, _, body = asyncio.run(
            site_module.call(app, scope, "POST", "/api/theses", thesis)
        )
        assert status == 201, body


def test_a_ticker_sec_really_does_not_list_is_still_called_unknown(
    tmp_path, monkeypatch
):
    listing = b'{"0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"}}'

    class Answering(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=listing,
                request=request,
                headers={"content-type": "application/json"},
            )

    app, seed = version_behind(Answering(), tmp_path, monkeypatch)
    request = {
        "ticker": "ZZZZ",
        "decision": "d" * 20,
        "claims": ["Revenue is growing."],
    }
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "scheme": "http",
        "root_path": "",
        "query_string": b"",
        "client": ("192.0.2.1", 1),
        "server": ("t", 80),
        "headers": [(b"host", b"t"), (b"content-type", b"application/json")],
    }
    status, _, body = asyncio.run(
        site_module.call(app, scope, "POST", "/api/runs", json.dumps(request).encode())
    )
    assert status == 422
    assert "not in SEC's company list" in json.loads(body)["details"][0]["message"]
    assert seed.edgar()["www.sec.gov"] == {"HTTP 200": 1}


def test_status_says_how_edgar_answered_in_counts_only():
    report = json.loads(call("/live/status")[2])
    assert isinstance(report["edgar"], dict)
    for outcomes in report["edgar"].values():
        assert all(isinstance(count, int) for count in outcomes.values())
