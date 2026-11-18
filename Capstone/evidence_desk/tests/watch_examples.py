"""The watch's API payloads for the page builder: ``python -m tests.watch_examples``.

``make watch-examples`` plays an offline scenario and writes what each route answers to
``docs/examples/v14/``. Nothing is live: the EDGAR index is :class:`tests.fakes.FakeFilings`
(made-up NVIDIA filings), the clock is a :class:`tests.fakes.WallClock` from 18 Nov 2026
09:00 UTC, and the engine is the service tests' scripted one (``departure_or_annual``: no
model, no cassette). Ids, and the times a run stamps itself, change on every regeneration.

The scenario, in order: a thesis with two claims is run once and put on watch (``auto``);
a 5.02 8-K naming the chief executive's departure arrives and is run (``moved``); a
quarterly report arrives and is run (``nothing_moved``); a shareholder-vote 8-K arrives
(``not_relevant``); a results 8-K arrives while EDGAR fails every run, and gives up after
its retries (``failed``); the policy turns to ``ask`` and two more 8-Ks arrive and wait;
the owner starts one outside the API, which is left mid-run (``running``). The inbox is
written then, one item of each kind. Last, the other waiting run is started through the
API, and the item is written again once its run has ended.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.api import create_app
from app.core import watch_policy as wording
from app.core.models import ThesisCreate, ThesisRequest
from app.core.ports import SourceError
from app.core.watch_models import InboxKind
from app.services import theses
from app.store import FilingCache, Store
from app.watch.service import Watcher, WatchSettings, run_executor, start_waiting_run
from app.watch.store import WatchStatus, WatchStore
from tests.fakes import (
    FakePages,
    FormFakeFilings,
    ScriptedAnalyst,
    WallClock,
    current_report_html,
    current_report_ref,
    filing_html,
    synthetic_ref,
)
from tests.test_events_run import (
    ANNUAL,
    CLAIM,
    DEPARTURE_8K,
    QUARTER,
    departure_html,
    filings,
)
from tests.test_watch_service import GROWTH, T0, departure_or_annual

OUT = Path("docs/examples/v14")
INTERVAL = 900


def _write(name: str, payload: Any) -> None:
    (OUT / name).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {OUT / name}")


def _ok(response: Any, status: int = 200) -> Any:
    if response.status_code != status:
        raise SystemExit(f"FAIL: {response.request.url} answered {response.status_code}")
    return response.json()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    store, cache = Store(":memory:"), FilingCache()
    source = FormFakeFilings(refs=[QUARTER, ANNUAL], documents=dict(filings().documents))
    clock = WallClock(T0)
    analyst = ScriptedAnalyst(departure_or_annual)
    settings = WatchSettings(interval_seconds=INTERVAL, auto_runs_per_day=5)
    app = create_app(
        store=store,
        filings=source,
        analyst=analyst,
        fetch_page=FakePages({}),
        cache=cache,
        wall_clock=clock,
    )
    watches = WatchStore(store)
    execute = run_executor(store, source, analyst, cache, fetch_page=FakePages({}))
    watcher = Watcher(
        store=store,
        watches=watches,
        status=WatchStatus(cache),
        filings=source,
        cache=cache,
        execute=execute,
        settings=settings,
        now=clock,
        worker="watch-7f3a",
    )
    thesis = theses.create_thesis(
        store,
        ThesisCreate(
            name="Jane Smith is gone",
            request=ThesisRequest(
                ticker="NVDA",
                decision="Whether to buy the shares after the change at the top",
                claims=[CLAIM, GROWTH],
                filings=3,
            ),
        ),
    )
    execute(theses.start_thesis_run(store, thesis.id))

    def arrive(ref: Any, html: str) -> None:
        if ref.form.startswith("8-K"):
            source.current.append(ref)
        else:
            source.refs.insert(0, ref)
        source.documents[ref.url] = html
        clock.advance(INTERVAL)
        watcher.cycle()

    with TestClient(app) as client:
        _write("health-not-running.json", _ok(client.get("/api/watch/health")))
        _write(
            "watch-put.json",
            _ok(client.put(f"/api/theses/{thesis.id}/watch", json={"policy": "auto"}), 201),
        )
        _write(
            "error-422.json",
            _ok(client.put(f"/api/theses/{thesis.id}/watch", json={"policy": "often"}), 422),
        )
        watcher.cycle()

        quarter = dataclasses.replace(synthetic_ref(3, "10-Q"), filed_date="2026-03-02")
        arrive(
            quarter,
            filing_html(
                "Revenue grew in the quarter as demand for systems rose sharply in every region."
            ),
        )
        arrive(DEPARTURE_8K, departure_html())
        arrive(
            current_report_ref(6, "2026-06-30", "5.07"),
            current_report_html(("5.07", "Submission of Matters to a Vote.", ["Votes."])),
        )

        working = source.periodic_filings
        source.periodic_filings = lambda company, limit: (_ for _ in ()).throw(  # type: ignore[method-assign]
            SourceError("EDGAR answered HTTP 503 for the filing index")
        )
        arrive(
            current_report_ref(7, "2026-08-26", "2.02", "9.01"),
            current_report_html(("2.02", "Results of Operations.", ["Results announced."])),
        )
        for wait in wording.BACKOFF_SECONDS:
            clock.advance(wait)
            watcher.cycle()
        source.periodic_filings = working  # type: ignore[method-assign]

        _ok(client.put(f"/api/theses/{thesis.id}/watch", json={"policy": "ask"}))
        arrive(
            current_report_ref(8, "2026-09-03", "5.02"),
            current_report_html(
                ("5.02", "Departure of Directors.", ["A director resigned from the board."])
            ),
        )
        arrive(
            current_report_ref(9, "2026-11-17", "2.02", "9.01"),
            current_report_html(("2.02", "Results of Operations.", ["Results announced."])),
        )
        items = _ok(client.get("/api/inbox"))["items"]
        waiting = [item for item in items if item["kind"] == InboxKind.waiting]
        later, sooner = waiting[0], waiting[1]  # newest first
        start_waiting_run(store, watches, sooner["id"], clock())  # left running on purpose

        inbox = _ok(client.get("/api/inbox"))
        kinds = sorted(item["kind"] for item in inbox["items"])
        if kinds != sorted(kind.value for kind in InboxKind):
            headlines = "\n".join(f"{i['kind']}: {i['headline']}" for i in inbox["items"])
            raise SystemExit(f"FAIL: the inbox should hold one item of each kind:\n{headlines}")
        _write("inbox.json", inbox)
        _write("inbox-page-2.json", _ok(client.get("/api/inbox?limit=4&offset=4")))
        _write("watches.json", _ok(client.get("/api/watch")))
        _write("health.json", _ok(client.get("/api/watch/health")))
        _write("meta.json", _ok(client.get("/api/watch/meta")))

        started = _ok(client.post(f"/api/inbox/{later['id']}/run"), 202)
        _write("waiting-run-started.json", started)
        for _ in range(500):
            item = _ok(client.get(f"/api/inbox/{later['id']}"))
            if item["kind"] != InboxKind.running:
                break
            time.sleep(0.02)
        else:
            raise SystemExit("FAIL: the started run never ended")
        _write("inbox-item-after-run.json", item)
        _write(
            "mark-read.json",
            _ok(client.post("/api/inbox/read", json={"ids": [later["id"], "ib-gone"]})),
        )
        _write("unwatch.json", _ok(client.delete(f"/api/theses/{thesis.id}/watch")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
