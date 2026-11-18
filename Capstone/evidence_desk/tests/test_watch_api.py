"""The watch's HTTP routes: validated like their neighbours, and every result computed here."""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.core.models import ThesisCreate, ThesisRequest
from app.core.ports import SourceError
from app.core.watch_models import InboxKind
from app.services import theses
from app.store import FilingCache, Store
from app.watch.service import Watcher, WatchSettings, run_executor
from app.watch.store import WatchStatus, WatchStore
from tests.fakes import FakeFilings, FakePages, ScriptedAnalyst, WallClock
from tests.test_events_run import CLAIM, DEPARTURE_8K, departure_html, filings
from tests.test_watch_service import GROWTH, T0, departure_or_annual


@dataclass
class Api:
    client: TestClient
    store: Store
    source: FakeFilings
    clock: WallClock
    watcher: Watcher
    thesis_id: str

    def gain_departure(self) -> None:
        self.source.current.append(DEPARTURE_8K)
        self.source.documents[DEPARTURE_8K.url] = departure_html()
        self.clock.advance(900)


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Api]:
    store = Store(tmp_path / "record.sqlite")
    cache = FilingCache()
    source = filings()
    clock = WallClock(T0)
    analyst = ScriptedAnalyst(departure_or_annual)
    app = create_app(
        store=store,
        filings=source,
        analyst=analyst,
        fetch_page=FakePages({}),
        cache=cache,
        wall_clock=clock,
    )
    watcher = Watcher(
        store=store,
        watches=WatchStore(store),
        status=WatchStatus(cache),
        filings=source,
        cache=cache,
        execute=run_executor(store, source, analyst, cache, fetch_page=FakePages({})),
        settings=WatchSettings(interval_seconds=900),
        now=clock,
        worker="test-worker",
    )
    thesis = theses.create_thesis(
        store,
        ThesisCreate(
            name="Jane Smith is gone",
            request=ThesisRequest(
                ticker="NVDA",
                decision="Whether to buy the shares after the change at the top",
                claims=[CLAIM, GROWTH],
                filings=2,
            ),
        ),
    )
    with TestClient(app) as client:
        yield Api(client, store, source, clock, watcher, thesis.id)


def fields(response: Any) -> list[str]:
    return [problem["field"] for problem in response.json()["details"]]


def test_watching_a_thesis_is_201_then_200_when_only_the_policy_changes(api: Api) -> None:
    first = api.client.put(f"/api/theses/{api.thesis_id}/watch", json={})
    second = api.client.put(f"/api/theses/{api.thesis_id}/watch", json={"policy": "auto"})

    assert first.status_code == 201
    assert first.json()["created"] is True
    assert first.json()["watch"]["policy"] == "ask"
    assert second.status_code == 200
    assert second.json()["watch"]["policy"] == "auto"
    assert second.json()["watch"]["policy_label"] == "Run at once"
    [row] = api.client.get("/api/watch").json()["watches"]
    assert row["last_check_at"] is None
    assert row["next_check_note"] == "At the watcher's next cycle."


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"policy": "sometimes"}, "policy"),
        ({"policy": "ask", "notify": True}, "notify"),
    ],
)
def test_a_watch_request_outside_the_schema_is_refused_naming_its_field(
    api: Api, body: dict[str, Any], field: str
) -> None:
    response = api.client.put(f"/api/theses/{api.thesis_id}/watch", json=body)

    assert response.status_code == 422
    assert fields(response) == [field]


def test_a_malformed_or_unknown_thesis_id_is_422_or_404(api: Api) -> None:
    malformed = api.client.put("/api/theses/th%20one!/watch", json={})
    unknown = api.client.put("/api/theses/th-000000000000/watch", json={})

    assert malformed.status_code == 422 and fields(malformed) == ["path.thesis_id"]
    assert unknown.status_code == 404


def test_with_edgar_down_no_watch_is_saved_and_the_answer_is_503(api: Api) -> None:
    api.source.index_error = SourceError("EDGAR could not be reached (ConnectError)")

    response = api.client.put(f"/api/theses/{api.thesis_id}/watch", json={})

    assert response.status_code == 503
    assert api.client.get("/api/watch").json()["watches"] == []


def test_taking_a_thesis_off_watch_then_again_is_409(api: Api) -> None:
    api.client.put(f"/api/theses/{api.thesis_id}/watch", json={})

    first = api.client.delete(f"/api/theses/{api.thesis_id}/watch")
    again = api.client.delete(f"/api/theses/{api.thesis_id}/watch")
    unknown = api.client.delete("/api/theses/th-000000000000/watch")

    assert first.status_code == 200 and first.json() == {
        "thesis_id": api.thesis_id,
        "watching": False,
    }
    assert again.status_code == 409
    assert unknown.status_code == 404


def _wait_until_finished(api: Api, item_id: str) -> dict[str, Any]:
    for _ in range(200):
        item = api.client.get(f"/api/inbox/{item_id}").json()
        if item["kind"] != InboxKind.running:
            return item
        time.sleep(0.02)
    raise AssertionError("the waiting run never finished")


def test_a_waiting_run_is_started_once_and_its_item_then_says_what_moved(api: Api) -> None:
    api.client.post(f"/api/theses/{api.thesis_id}/runs")
    for _ in range(200):
        runs = api.client.get(f"/api/theses/{api.thesis_id}").json()["runs"]
        if runs and runs[0]["status"] != "running":
            break
        time.sleep(0.02)
    api.client.put(f"/api/theses/{api.thesis_id}/watch", json={"policy": "ask"})
    api.gain_departure()
    api.watcher.cycle()

    inbox = api.client.get("/api/inbox").json()
    [item] = inbox["items"]
    assert (inbox["total"], inbox["unread"], inbox["next_offset"]) == (1, 1, None)
    assert item["kind"] == "waiting" and item["run"]["state"] == "waiting"

    started = api.client.post(f"/api/inbox/{item['id']}/run")
    again = api.client.post(f"/api/inbox/{item['id']}/run")

    assert started.status_code == 202 and started.json()["item_id"] == item["id"]
    assert again.status_code == 409
    done = _wait_until_finished(api, item["id"])
    assert done["kind"] == "moved"
    assert done["run"]["run_id"] == started.json()["id"]
    assert done["moved"]["verdicts"] == [
        {"claim": CLAIM, "before": "challenged", "after": "supported"}
    ]


def test_inbox_paging_is_bounded_and_validated(api: Api) -> None:
    for query, field in (("limit=0", "limit"), ("limit=101", "limit"), ("offset=-1", "offset")):
        response = api.client.get(f"/api/inbox?{query}")
        assert response.status_code == 422 and fields(response) == [f"query.{field}"]
    assert api.client.get("/api/inbox?thesis_id=bad%20id").status_code == 422
    assert api.client.get("/api/inbox/not-an-item").status_code == 422
    assert api.client.get("/api/inbox/ib-nothing").status_code == 404


def test_marking_items_read_lists_unknown_ids_and_counts_what_is_left(api: Api) -> None:
    api.client.put(f"/api/theses/{api.thesis_id}/watch", json={"policy": "ask"})
    api.gain_departure()
    api.watcher.cycle()
    [item] = api.client.get("/api/inbox").json()["items"]

    marked = api.client.post("/api/inbox/read", json={"ids": [item["id"], "ib-gone"]})
    unread = api.client.post("/api/inbox/read", json={"ids": [item["id"]], "read": False})

    assert marked.json() == {"marked": [item["id"]], "unknown": ["ib-gone"], "unread": 0}
    assert unread.json()["unread"] == 1
    for body in ({"ids": []}, {"ids": ["not an id"]}, {"ids": [item["id"]], "read": "yes"}):
        assert api.client.post("/api/inbox/read", json=body).status_code == 422


def test_health_says_no_watcher_until_a_cycle_and_then_alive_with_the_queue(api: Api) -> None:
    before = api.client.get("/api/watch/health").json()
    api.client.put(f"/api/theses/{api.thesis_id}/watch", json={})
    api.watcher.cycle()
    after = api.client.get("/api/watch/health").json()

    assert before["alive"] is False and before["worker"] is None
    assert after["alive"] is True and after["worker"] == "test-worker"
    assert after["stale_after_seconds"] == 1860
    assert after["queue_depth"] == 0 and after["watches"] == 1


def test_meta_labels_every_inbox_kind_policy_and_rule(api: Api) -> None:
    meta = api.client.get("/api/watch/meta").json()

    assert set(meta["kind_labels"]) == {kind.value for kind in InboxKind}
    assert meta["collapsed_kinds"] == ["not_relevant"]
    assert meta["policy_labels"] == {"auto": "Run at once", "ask": "Ask before running"}
    assert meta["limits"]["min_interval_seconds"] == 300
