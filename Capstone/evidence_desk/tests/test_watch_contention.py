"""The watcher does not lock the app out: a run and watcher cycles write one record at once.

Two processes, as in production (the app's container and the watcher's): this one runs
the example thesis on the recorded NVIDIA filings, saving after every stage, source and
claim, while a second process does watcher cycles on the same record and cache files.
Each of its cycles finds a new routine 8-K, so each one writes a seen filing, a job, an
inbox item and a heartbeat. Both must finish without an error, and the file must pass
SQLite's integrity check.
"""

from __future__ import annotations

import multiprocessing
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.models import ThesisCreate, ThesisRequest
from app.core.watch_models import WatchPolicy
from app.engines.extractive import ExtractiveAnalyst
from app.services import theses, thesis_run
from app.services.examples import EXAMPLE_THESIS
from app.store import FilingCache, Store
from app.watch.service import Watcher, WatchSettings, run_executor, start_watching
from app.watch.store import WatchStatus, WatchStore
from tests.fakes import FakeFilings, FakePages, current_report_html, current_report_ref

T0 = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
VOTE = current_report_html(("5.07", "Submission of Matters to a Vote.", ["Votes were cast."]))


def _cycles(record: str, cache: str, started: object, stop: object, out: object) -> None:
    """Do watcher cycles until told to stop; each cycle a new routine 8-K appears."""
    store, files = Store(Path(record)), FilingCache(Path(cache))
    source = FakeFilings.nvidia()
    clock = [T0]
    watcher = Watcher(
        store=store,
        watches=WatchStore(store),
        status=WatchStatus(files),
        filings=source,
        cache=files,
        execute=run_executor(store, source, ExtractiveAnalyst(), files, fetch_page=FakePages({})),
        settings=WatchSettings(interval_seconds=300),
        now=lambda: clock[0],
        worker="contender",
    )
    cycles, done = 0, 0
    try:
        started.set()  # type: ignore[attr-defined]
        while not stop.is_set() or cycles < 3:  # type: ignore[attr-defined]
            cycles += 1
            ref = current_report_ref(1000 + cycles, "2026-11-12", "5.07")
            source.current.append(ref)
            source.documents[ref.url] = VOTE
            clock[0] += timedelta(seconds=300)
            done += watcher.cycle().jobs_done
        out.put(("ok", cycles, done))  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 - reported to the test, which fails on it
        out.put(("error", cycles, f"{type(exc).__name__}: {exc}"))  # type: ignore[attr-defined]


def test_a_run_and_watcher_cycles_writing_one_record_at_once_both_succeed(tmp_path: Path) -> None:
    record, cache = tmp_path / "record.sqlite", tmp_path / "filings.sqlite"
    store, files = Store(record), FilingCache(cache)
    source = FakeFilings.nvidia()
    watched = theses.create_thesis(
        store,
        ThesisCreate(
            name="Watched",
            request=ThesisRequest(
                ticker="NVDA",
                decision="A watched thesis of NVIDIA",
                claims=["Buy because Jane Smith is gone."],
            ),
        ),
    )
    start_watching(store, WatchStore(store), source, watched.id, WatchPolicy.ask, T0)

    context = multiprocessing.get_context("spawn")
    started, stop, out = context.Event(), context.Event(), context.Queue()
    contender = context.Process(target=_cycles, args=(str(record), str(cache), started, stop, out))
    contender.start()
    assert started.wait(timeout=60)
    run = thesis_run.new_run(EXAMPLE_THESIS)
    store.save_run(run)
    finished = thesis_run.execute_run(
        run,
        store,
        filings=source,
        analyst=ExtractiveAnalyst(),
        fetch_page=FakePages({}),
        cache=files,
    )
    stop.set()
    outcome, cycles, detail = out.get(timeout=120)
    contender.join(timeout=60)

    assert outcome == "ok", detail
    assert finished.status.value in ("complete", "partial"), finished.errors
    assert store.get_run(run.id) == finished
    assert cycles >= 3 and detail == cycles  # every cycle's new 8-K was triaged and done
    inbox = WatchStore(store).list_items(limit=1, offset=0)
    assert inbox.total == cycles
    with closing(sqlite3.connect(record)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
