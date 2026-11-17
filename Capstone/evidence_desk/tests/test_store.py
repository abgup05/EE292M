"""The record store: runs, decisions and saved theses survive a round trip, in order."""

import logging
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.models import (
    Claim,
    Decision,
    DecisionValue,
    Run,
    RunStatus,
    Thesis,
    ThesisRequest,
    Verdict,
)
from app.store import Store

REQUEST = ThesisRequest(
    ticker="NVDA",
    decision="Keep the position into the next earnings report",
    claims=["Data-center revenue is still growing", "A few customers account for most revenue"],
)
NOON = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


def _run(run_id: str = "run-1", minutes: int = 0, thesis_id: str | None = None) -> Run:
    return Run(
        id=run_id,
        inputs=REQUEST,
        thesis_id=thesis_id,
        status=RunStatus.running,
        started_at=NOON + timedelta(minutes=minutes),
    )


def _decision(
    finding_id: str,
    value: DecisionValue = DecisionValue.accepted,
    minutes: int = 0,
    run_id: str = "run-1",
    note: str = "",
) -> Decision:
    return Decision(
        run_id=run_id,
        finding_id=finding_id,
        value=value,
        note=note,
        decided_at=NOON + timedelta(minutes=minutes),
    )


def _thesis(thesis_id: str, minutes: int = 0) -> Thesis:
    return Thesis(
        id=thesis_id,
        name=f"NVIDIA {thesis_id}",
        request=REQUEST,
        created_at=NOON + timedelta(minutes=minutes),
    )


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "record.sqlite")


# Runs


def test_run_round_trip(store: Store) -> None:
    run = _run().model_copy(
        update={"claims": [Claim(id="c1", text=REQUEST.claims[0], verdict=Verdict.supported)]}
    )
    store.save_run(run)
    assert store.get_run("run-1") == run
    assert store.get_run("run-missing") is None


def test_save_run_overwrites_previous_version(store: Store) -> None:
    run = _run()
    store.save_run(run)
    store.save_run(run.model_copy(update={"status": RunStatus.partial}))
    loaded = store.get_run("run-1")
    assert loaded is not None and loaded.status == RunStatus.partial
    assert [r.id for r in store.list_runs()] == ["run-1"]


def test_list_runs_newest_first_and_limited(store: Store) -> None:
    for minute in range(5):
        store.save_run(_run(f"run-{minute}", minutes=minute))
    assert [r.id for r in store.list_runs()] == ["run-4", "run-3", "run-2", "run-1", "run-0"]
    assert [r.id for r in store.list_runs(limit=2)] == ["run-4", "run-3"]


def test_runs_of_a_thesis_are_found_by_its_indexed_column_newest_first(
    store: Store, tmp_path: Path
) -> None:
    store.save_run(_run("run-a", minutes=0, thesis_id="th-1"))
    store.save_run(_run("run-b", minutes=1, thesis_id="th-2"))
    store.save_run(_run("run-c", minutes=2, thesis_id="th-1"))
    store.save_run(_run("run-d", minutes=3))
    assert [r.id for r in store.runs_of_thesis("th-1")] == ["run-c", "run-a"]
    assert store.runs_of_thesis("th-none") == []
    with sqlite3.connect(tmp_path / "record.sqlite") as connection:
        column = dict(connection.execute("SELECT id, thesis_id FROM runs").fetchall())
        plan = " ".join(
            str(row)
            for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM runs WHERE thesis_id = ?", ("th-1",)
            )
        )
    connection.close()
    assert column == {"run-a": "th-1", "run-b": "th-2", "run-c": "th-1", "run-d": None}
    assert "runs_by_thesis" in plan


def test_old_format_record_is_skipped_with_a_warning(
    store: Store, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store.save_run(_run("run-new", minutes=1))
    with sqlite3.connect(tmp_path / "record.sqlite") as connection:
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


def test_concurrent_writes_are_all_kept(store: Store) -> None:
    def write(index: int) -> None:
        store.save_run(_run(f"run-{index}", minutes=index))
        store.save_decision(_decision(f"f{index}", run_id=f"run-{index}"))

    threads = [threading.Thread(target=write, args=(index,)) for index in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(store.list_runs()) == 12
    assert store.list_decisions("run-7") == [_decision("f7", run_id="run-7")]


def test_the_record_survives_reopening(tmp_path: Path) -> None:
    path = tmp_path / "record" / "record.sqlite"
    first = Store(path)
    first.save_run(_run())
    first.save_decision(_decision("f1", note="Read the 10-Q myself."))
    first.save_thesis(_thesis("th-1"))
    first.close()
    second = Store(path)
    assert second.get_run("run-1") == _run()
    assert second.list_decisions("run-1") == [_decision("f1", note="Read the 10-Q myself.")]
    assert second.get_thesis("th-1") == _thesis("th-1")


# Decisions


def test_decisions_come_back_in_the_order_decided(store: Store) -> None:
    store.save_decision(_decision("f3", minutes=0))
    store.save_decision(_decision("f1", DecisionValue.rejected, minutes=1))
    store.save_decision(_decision("f2", minutes=2))
    store.save_decision(_decision("f9", minutes=0, run_id="run-2"))
    assert [d.finding_id for d in store.list_decisions("run-1")] == ["f3", "f1", "f2"]
    assert [d.finding_id for d in store.list_decisions("run-2")] == ["f9"]
    assert store.list_decisions("run-none") == []


def test_saving_a_decision_again_replaces_it(store: Store) -> None:
    store.save_decision(_decision("f1", minutes=0))
    store.save_decision(_decision("f2", minutes=1))
    changed = _decision("f1", DecisionValue.rejected, minutes=2, note="The quote is about 2025.")
    store.save_decision(changed)
    assert store.list_decisions("run-1") == [_decision("f2", minutes=1), changed]


def test_a_cleared_decision_is_gone_and_clearing_twice_is_harmless(store: Store) -> None:
    store.save_decision(_decision("f1"))
    store.save_decision(_decision("f2", minutes=1))
    store.clear_decision("run-1", "f1")
    store.clear_decision("run-1", "f1")
    store.clear_decision("run-none", "f1")
    assert [d.finding_id for d in store.list_decisions("run-1")] == ["f2"]


def test_decisions_keep_every_field_including_the_note(store: Store) -> None:
    decision = _decision("f4", DecisionValue.rejected, note="Excerpt is from a footnote, “2025”.")
    store.save_decision(decision)
    [loaded] = store.list_decisions("run-1")
    assert loaded == decision and loaded.decided_at.tzinfo is not None


# Saved theses


def test_theses_round_trip_newest_first(store: Store) -> None:
    for minute, thesis_id in enumerate(["th-a", "th-b", "th-c"]):
        store.save_thesis(_thesis(thesis_id, minutes=minute))
    assert [t.id for t in store.list_theses()] == ["th-c", "th-b", "th-a"]
    assert store.get_thesis("th-b") == _thesis("th-b", minutes=1)
    assert store.get_thesis("th-none") is None


def test_saving_a_thesis_again_replaces_it(store: Store) -> None:
    thesis = _thesis("th-a")
    store.save_thesis(thesis)
    store.save_thesis(thesis.model_copy(update={"run_ids": ["run-1", "run-2"]}))
    loaded = store.get_thesis("th-a")
    assert loaded is not None and loaded.run_ids == ["run-1", "run-2"]
    assert len(store.list_theses()) == 1


def test_counts_cover_the_three_tables(store: Store) -> None:
    store.save_run(_run())
    store.save_decision(_decision("f1"))
    store.save_decision(_decision("f2"))
    store.save_thesis(_thesis("th-a"))
    assert store.counts() == {"runs": 1, "decisions": 2, "theses": 1}
