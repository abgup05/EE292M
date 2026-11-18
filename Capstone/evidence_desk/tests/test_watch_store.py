"""The watch's record: seen filings, one job per (thesis, filing), claims, retries, the inbox.

Two processes race for jobs in ``test_two_processes_*``: each opens the same record
file through its own connection, as the app and the watcher container do.
"""

from __future__ import annotations

import multiprocessing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core import watch_policy as wording
from app.core.models import Thesis
from app.core.triage import watched_filing
from app.core.watch_models import (
    InboxItem,
    InboxKind,
    JobState,
    Triage,
    Watch,
    WatchedFiling,
    WatchPolicy,
)
from app.store import Store
from app.watch.store import WatchStore
from tests.fakes import NVIDIA, current_report_ref
from tests.test_backup import REQUEST, _run

T0 = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
LEASE = wording.LEASE_SECONDS


def filing(number: int, *items: str) -> WatchedFiling:
    return watched_filing(current_report_ref(number, "2026-11-12", *items or ("5.02",)))


def watch(thesis_id: str = "th-1", policy: WatchPolicy = WatchPolicy.ask) -> Watch:
    return Watch(
        thesis_id=thesis_id,
        cik=NVIDIA.cik,
        ticker=NVIDIA.ticker,
        company_name=NVIDIA.name,
        policy=policy,
        created_at=T0,
        updated_at=T0,
    )


@pytest.fixture
def watches(tmp_path: Path) -> WatchStore:
    store = WatchStore(Store(tmp_path / "record.sqlite"))
    store.put_watch(watch())
    return store


def test_each_new_filing_queues_one_job_and_seeing_it_again_queues_none(
    watches: WatchStore,
) -> None:
    first = watches.note_filings("th-1", [filing(1), filing(2)], T0)
    again = watches.note_filings("th-1", [filing(1), filing(2), filing(3)], T0)

    assert [f.accession for f in first] == [filing(1).accession, filing(2).accession]
    assert [f.accession for f in again] == [filing(3).accession]
    assert watches.job_counts()[JobState.queued] == 3


def test_a_baseline_marks_filings_seen_without_a_job(watches: WatchStore) -> None:
    queued = watches.note_filings("th-1", [filing(1)], T0, baseline=True)

    assert queued == []
    assert watches.seen("th-1") == {filing(1).accession}
    assert watches.note_filings("th-1", [filing(1)], T0) == []
    assert sum(watches.job_counts().values()) == 0


def test_one_job_per_thesis_and_filing_even_if_the_seen_mark_is_lost(
    watches: WatchStore,
) -> None:
    watches.note_filings("th-1", [filing(1)], T0)
    # As if a second watcher had never seen the mark: only the job's own key is left.
    with watches._db.transaction() as connection:
        connection.execute("DELETE FROM watch_seen")

    assert watches.note_filings("th-1", [filing(1)], T0) == []
    assert len(watches.jobs()) == 1


def test_a_claim_takes_one_ready_job_and_leases_it(watches: WatchStore) -> None:
    watches.note_filings("th-1", [filing(1)], T0)

    job = watches.claim_job("worker-a", T0, LEASE)
    second = watches.claim_job("worker-b", T0, LEASE)

    assert job is not None and job.state == JobState.running
    assert job.attempts == 1 and job.worker == "worker-a"
    assert job.lease_until == T0 + timedelta(seconds=LEASE)
    assert second is None


def test_a_failed_job_waits_its_backoff_then_is_retried_until_the_cap(
    watches: WatchStore,
) -> None:
    watches.note_filings("th-1", [filing(1)], T0)
    now = T0
    for attempt in range(1, wording.MAX_ATTEMPTS):
        job = watches.claim_job("w", now, LEASE)
        assert job is not None and job.attempts == attempt
        state = watches.fail_job(job, "EDGAR answered HTTP 503", now)
        assert state == JobState.queued
        wait = wording.BACKOFF_SECONDS[attempt - 1]
        assert watches.claim_job("w", now + timedelta(seconds=wait - 1), LEASE) is None
        now += timedelta(seconds=wait)

    last = watches.claim_job("w", now, LEASE)
    assert last is not None and last.attempts == wording.MAX_ATTEMPTS
    assert watches.fail_job(last, "EDGAR answered HTTP 503", now) == JobState.failed
    stored = watches.jobs()[0]
    assert stored.state == JobState.failed
    assert stored.error == "EDGAR answered HTTP 503"
    assert watches.claim_job("w", now + timedelta(days=1), LEASE) is None


def test_a_job_left_running_by_a_crash_is_taken_up_after_its_lease(
    watches: WatchStore,
) -> None:
    watches.note_filings("th-1", [filing(1)], T0)
    crashed = watches.claim_job("crashed", T0, LEASE)
    assert crashed is not None

    early = T0 + timedelta(seconds=LEASE - 1)
    assert watches.reap_expired(early) == []
    assert watches.claim_job("other", early, LEASE) is None

    late = T0 + timedelta(seconds=LEASE)
    assert [state for _, state in watches.reap_expired(late)] == [JobState.queued]
    taken = watches.claim_job("other", late + timedelta(seconds=wording.BACKOFF_SECONDS[0]), LEASE)
    assert taken is not None and taken.attempts == 2 and taken.worker == "other"
    assert taken.error == wording.LEASE_EXPIRED
    # The crashed worker, were it to come back, can no longer finish what it lost.
    assert not watches.finish_job(crashed, "late", late)
    assert watches.finish_job(taken, "triaged", late)
    assert watches.jobs()[0].state == JobState.done


def test_a_job_whose_lease_runs_out_on_its_last_attempt_stays_failed(
    watches: WatchStore,
) -> None:
    watches.note_filings("th-1", [filing(1)], T0)
    now = T0
    for _ in range(wording.MAX_ATTEMPTS):
        job = watches.claim_job("w", now, LEASE)
        assert job is not None
        now += timedelta(seconds=LEASE)
        watches.reap_expired(now)
        now += timedelta(seconds=max(wording.BACKOFF_SECONDS))

    stored = watches.jobs()[0]
    assert stored.state == JobState.failed
    assert stored.error == wording.LEASE_EXPIRED


def test_the_daily_cap_on_automatic_runs_counts_jobs_once(watches: WatchStore) -> None:
    watches.note_filings("th-1", [filing(1), filing(2), filing(3)], T0)
    jobs = watches.jobs()
    day = "2026-11-18"

    assert watches.take_auto_slot(jobs[0].id, day, cap=2)
    assert watches.take_auto_slot(jobs[0].id, day, cap=2)  # a retry of the same job
    assert watches.take_auto_slot(jobs[1].id, day, cap=2)
    assert not watches.take_auto_slot(jobs[2].id, day, cap=2)
    assert watches.take_auto_slot(jobs[2].id, "2026-11-19", cap=2)


def _claim_all(path: str, worker: str, start: object, out: object) -> None:
    """Claim jobs until none is left; put each claimed job id on ``out``."""
    store = WatchStore(Store(Path(path)))
    start.wait()  # type: ignore[attr-defined]
    while (job := store.claim_job(worker, T0, LEASE)) is not None:
        out.put((worker, job.id))  # type: ignore[attr-defined]
    out.put((worker, None))  # type: ignore[attr-defined]


def _race(path: Path) -> list[tuple[str, str]]:
    context = multiprocessing.get_context("spawn")
    start = context.Barrier(2)
    out = context.Queue()
    workers = [
        context.Process(target=_claim_all, args=(str(path), name, start, out))
        for name in ("worker-a", "worker-b")
    ]
    for process in workers:
        process.start()
    claimed: list[tuple[str, str]] = []
    finished = 0
    while finished < 2:
        worker, job_id = out.get(timeout=60)
        if job_id is None:
            finished += 1
        else:
            claimed.append((worker, job_id))
    for process in workers:
        process.join(timeout=60)
        assert process.exitcode == 0
    return claimed


def test_two_processes_racing_for_one_job_one_gets_it(watches: WatchStore) -> None:
    watches.note_filings("th-1", [filing(1)], T0)

    claimed = _race(Path(str(watches.path)))

    assert len(claimed) == 1
    assert watches.jobs()[0].attempts == 1


def test_two_processes_draining_many_jobs_claim_each_exactly_once(
    watches: WatchStore,
) -> None:
    watches.note_filings("th-1", [filing(n) for n in range(1, 61)], T0)

    claimed = _race(Path(str(watches.path)))

    ids = [job_id for _, job_id in claimed]
    assert len(ids) == 60 and len(set(ids)) == 60
    assert all(job.attempts == 1 for job in watches.jobs())


def item(number: int, minutes: int, kind: InboxKind = InboxKind.moved) -> InboxItem:
    when = T0 + timedelta(minutes=minutes)
    return InboxItem(
        id=f"ib-{number}",
        thesis_id="th-1",
        thesis_name="NVIDIA leadership",
        ticker="NVDA",
        job_id=f"wj-{number}",
        kind=kind,
        created_at=when,
        updated_at=when,
        filing=filing(number),
        triage=Triage(bears=kind != InboxKind.not_relevant, summary="s"),
    )


def test_the_inbox_lists_unread_first_then_newest_first_with_paging(
    watches: WatchStore,
) -> None:
    for number, minutes in ((1, 1), (2, 2), (3, 3), (4, 4)):
        watches.put_item(item(number, minutes))
    watches.mark_read(["ib-4"], T0, read=True)

    page = watches.list_items(limit=2, offset=0)
    rest = watches.list_items(limit=2, offset=2)

    assert [i.id for i in page.items] == ["ib-3", "ib-2"]
    assert [i.id for i in rest.items] == ["ib-1", "ib-4"]
    assert (page.total, page.unread) == (4, 3)
    assert rest.items[1].read_at == T0


def test_a_waiting_item_can_be_started_once(watches: WatchStore) -> None:
    watches.put_item(item(1, 1, InboxKind.waiting))

    assert watches.start_waiting("ib-1", "run-1", T0)
    assert not watches.start_waiting("ib-1", "run-2", T0)
    stored = watches.get_item("ib-1")
    assert stored is not None and stored.kind == InboxKind.running
    assert stored.run is not None and stored.run.run_id == "run-1"


def test_a_record_written_before_version_14_still_loads_and_gains_the_tables(
    tmp_path: Path,
) -> None:
    path = tmp_path / "record.sqlite"
    old = Store(path)
    old.save_run(_run("run-old"))
    old.save_thesis(
        Thesis(id="th-old", name="Old thesis", request=REQUEST, created_at=T0, run_ids=["run-old"])
    )
    old.close()

    reopened = Store(path)
    WatchStore(reopened)

    assert reopened.get_run("run-old") is not None
    assert reopened.get_thesis("th-old") is not None
    assert reopened.raw_rows("inbox") == {}
    assert reopened.unreadable() == []
