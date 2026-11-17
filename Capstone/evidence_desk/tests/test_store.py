"""Run persistence: records and stored source text survive a round trip."""

import logging
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.models import Claim, Run, RunStatus, ThesisRequest, Verdict
from app.store import Store

REQUEST = ThesisRequest(
    ticker="NVDA",
    decision="Keep the position into the next earnings report",
    claims=["Data-center revenue is still growing", "A few customers account for most revenue"],
)


def _run(run_id: str = "run-1", minutes: int = 0) -> Run:
    return Run(
        id=run_id,
        inputs=REQUEST,
        status=RunStatus.running,
        started_at=datetime(2026, 11, 17, 12, 0, tzinfo=UTC) + timedelta(minutes=minutes),
    )


def test_run_round_trip(tmp_path: Path) -> None:
    store = Store(tmp_path / "runs.sqlite")
    run = _run().model_copy(
        update={"claims": [Claim(id="c1", text=REQUEST.claims[0], verdict=Verdict.supported)]}
    )
    store.save_run(run)
    assert store.get_run("run-1") == run
    assert store.get_run("run-missing") is None


def test_save_run_overwrites_previous_version(tmp_path: Path) -> None:
    store = Store(tmp_path / "runs.sqlite")
    run = _run()
    store.save_run(run)
    store.save_run(run.model_copy(update={"status": RunStatus.partial}))
    loaded = store.get_run("run-1")
    assert loaded is not None and loaded.status == RunStatus.partial
    assert [r.id for r in store.list_runs()] == ["run-1"]


def test_list_runs_newest_first_and_limited(tmp_path: Path) -> None:
    store = Store(tmp_path / "runs.sqlite")
    for minute in range(5):
        store.save_run(_run(f"run-{minute}", minutes=minute))
    assert [r.id for r in store.list_runs()] == ["run-4", "run-3", "run-2", "run-1", "run-0"]
    assert [r.id for r in store.list_runs(limit=2)] == ["run-4", "run-3"]


def test_old_format_record_is_skipped_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "runs.sqlite"
    store = Store(path)
    store.save_run(_run("run-new", minutes=1))
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO runs (id, started_at, record) VALUES (?, ?, ?)",
            ("run-old", "2026-10-21T12:00:00+00:00", '{"id": "run-old", "question": "v1"}'),
        )
    connection.close()
    with caplog.at_level(logging.WARNING, logger="app.store"):
        runs = store.list_runs()
    assert [r.id for r in runs] == ["run-new"]
    assert any("run-old" in record.getMessage() for record in caplog.records)
    with caplog.at_level(logging.WARNING, logger="app.store"):
        assert store.get_run("run-old") is None


def test_source_text_round_trip(tmp_path: Path) -> None:
    store = Store(tmp_path / "runs.sqlite")
    text = "Exact stored text.\nThe company’s “Data Center” revenue grew."
    store.save_source_text("run-1", "s1", text)
    store.save_source_text("run-1", "s2", "Other text.")
    store.save_source_text("run-2", "s1", "Another run.")
    assert store.get_source_texts("run-1") == {"s1": text, "s2": "Other text."}
    assert store.get_source_texts("run-3") == {}


def test_concurrent_writes_are_all_kept(tmp_path: Path) -> None:
    store = Store(tmp_path / "runs.sqlite")

    def write(index: int) -> None:
        store.save_run(_run(f"run-{index}", minutes=index))
        store.save_source_text(f"run-{index}", "s1", f"text {index}")

    threads = [threading.Thread(target=write, args=(index,)) for index in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(store.list_runs()) == 12
    assert store.get_source_texts("run-7") == {"s1": "text 7"}
