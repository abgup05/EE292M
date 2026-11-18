"""The watch's state in SQLite: what cannot be rebuilt in the record, the rest in the cache.

:class:`WatchStore` adds four tables to **the record** (``record.sqlite``, through
:meth:`app.store.Store.extend`), because nothing can rebuild them: ``watches`` (which
theses are watched and with what policy), ``watch_seen`` (which filings each watch has
seen), ``watch_jobs`` (one job per thesis and filing, unique, so a filing triggers a
thesis once however many watchers run) and ``inbox`` (what came of each, and what was
read). They are backed up and compared by ``make restore-check`` with the rest.

:class:`WatchStatus` adds two tables to **the cache** (``filings.sqlite``, through
:meth:`app.store.FilingCache.extend`): the watcher's heartbeat and the time of each
company's last check. They change every cycle, so keeping them out of the record keeps
``make restore-check`` meaningful while a watcher runs; losing them loses nothing.

Every write that must not be done twice is one statement or one transaction that
re-checks its condition: a claim is one ``UPDATE ... RETURNING``; the daily cap one
conditional ``UPDATE``. Times are stored as fixed-width UTC text, so they sort.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from pydantic import BaseModel, ValidationError

from app.core import watch_policy as wording
from app.core.watch_models import (
    InboxItem,
    InboxKind,
    InboxRun,
    JobState,
    Watch,
    WatchedFiling,
    WatchJob,
    WatchPolicy,
)
from app.store import FilingCache, Store

WATCH_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS watches (
    thesis_id TEXT PRIMARY KEY,
    cik INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    company_name TEXT NOT NULL,
    policy TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS watch_seen (
    thesis_id TEXT NOT NULL,
    accession TEXT NOT NULL,
    form TEXT NOT NULL,
    filed_date TEXT NOT NULL,
    seen_at TEXT NOT NULL,
    baseline INTEGER NOT NULL,
    PRIMARY KEY (thesis_id, accession)
);
CREATE TABLE IF NOT EXISTS watch_jobs (
    id TEXT PRIMARY KEY,
    thesis_id TEXT NOT NULL,
    accession TEXT NOT NULL,
    state TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    not_before TEXT NOT NULL,
    lease_until TEXT,
    worker TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL DEFAULT '',
    auto_run_day TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    filing TEXT NOT NULL,
    UNIQUE (thesis_id, accession)
);
CREATE INDEX IF NOT EXISTS watch_jobs_ready ON watch_jobs (state, not_before);
CREATE TABLE IF NOT EXISTS inbox (
    id TEXT PRIMARY KEY,
    thesis_id TEXT NOT NULL,
    job_id TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read_at TEXT,
    record TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS inbox_by_time ON inbox (created_at);
"""

STATUS_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS watcher_beats (
    worker TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    last_cycle_at TEXT NOT NULL,
    interval_seconds INTEGER NOT NULL,
    last_cycle TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS watch_checks (
    cik INTEGER PRIMARY KEY,
    last_check_at TEXT NOT NULL,
    next_check_at TEXT NOT NULL,
    last_error TEXT NOT NULL
);
"""

# The watch tables of the record and what one row of each is called, for the backup.
WATCH_KINDS: Final = (
    ("watches", "watch"),
    ("watch_seen", "the seen filing"),
    ("watch_jobs", "watch job"),
    ("inbox", "inbox item"),
)
_STAMP = "%Y-%m-%dT%H:%M:%S.%fZ"


def stamp(when: datetime) -> str:
    """``when`` as fixed-width UTC text, which sorts as the times do."""
    return when.astimezone(UTC).strftime(_STAMP)


def unstamp(text: str | None) -> datetime | None:
    """The time :func:`stamp` wrote, or None."""
    return datetime.strptime(text, _STAMP).replace(tzinfo=UTC) if text else None


def job_id(thesis_id: str, accession: str) -> str:
    """The id of the one job a filing can make for a thesis."""
    return f"wj-{thesis_id}-{accession}"


def item_id(job: str) -> str:
    """The id of a job's inbox item: one per job."""
    return f"ib-{job.removeprefix('wj-')}"


@dataclass(frozen=True)
class InboxPage:
    """One page of the inbox and the counts over all of it."""

    items: list[InboxItem]
    total: int
    unread: int


_JOB_COLUMNS = (
    "id, thesis_id, accession, state, attempts, not_before, lease_until, worker, error, "
    "outcome, auto_run_day, created_at, updated_at, filing"
)


def _job(row: Sequence[object]) -> WatchJob:
    (ident, thesis, accession, state, attempts, not_before, lease, worker, error) = row[:9]
    outcome, day, created, updated, filing = row[9:]
    return WatchJob(
        id=str(ident),
        thesis_id=str(thesis),
        accession=str(accession),
        state=JobState(str(state)),
        attempts=int(str(attempts)),
        not_before=unstamp(str(not_before)),  # type: ignore[arg-type]
        lease_until=unstamp(lease if isinstance(lease, str) else None),
        worker=str(worker),
        error=str(error),
        outcome=str(outcome),
        auto_run_day=day if isinstance(day, str) else None,
        created_at=unstamp(str(created)),  # type: ignore[arg-type]
        updated_at=unstamp(str(updated)),  # type: ignore[arg-type]
        filing=WatchedFiling.model_validate_json(str(filing)),
    )


def _parses(model: type[BaseModel], text: str) -> bool:
    try:
        model.model_validate_json(text)
    except ValidationError:
        return False
    return True


class WatchStore:
    """The watch's tables in the record. Thread-safe: it shares the record's connection."""

    def __init__(self, store: Store) -> None:
        """Create the watch tables in ``store``'s file if they are missing, and use them."""
        self._db = store.extend(WATCH_SCHEMA)
        self.path = store.path

    # Watches

    def put_watch(self, watch: Watch) -> bool:
        """Watch a thesis, or change its policy; True when it was not watched before."""
        with self._db.transaction() as connection:
            existing = connection.execute(
                "SELECT 1 FROM watches WHERE thesis_id = ?", (watch.thesis_id,)
            ).fetchone()
            if existing:
                connection.execute(
                    "UPDATE watches SET policy = ?, updated_at = ? WHERE thesis_id = ?",
                    (watch.policy.value, stamp(watch.updated_at), watch.thesis_id),
                )
                return False
            connection.execute(
                "INSERT INTO watches (thesis_id, cik, ticker, company_name, policy, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    watch.thesis_id,
                    watch.cik,
                    watch.ticker,
                    watch.company_name,
                    watch.policy.value,
                    stamp(watch.created_at),
                    stamp(watch.updated_at),
                ),
            )
            return True

    def remove_watch(self, thesis_id: str) -> bool:
        """Take a thesis off watch; True when it was watched. Its jobs and inbox stay."""
        with self._db.transaction() as connection:
            removed = connection.execute("DELETE FROM watches WHERE thesis_id = ?", (thesis_id,))
            return removed.rowcount > 0

    def get_watch(self, thesis_id: str) -> Watch | None:
        """The watch on ``thesis_id``, if it is watched."""
        found = [w for w in self.list_watches() if w.thesis_id == thesis_id]
        return found[0] if found else None

    def list_watches(self) -> list[Watch]:
        """Every watch, oldest first."""
        rows = self._db.query(
            "SELECT thesis_id, cik, ticker, company_name, policy, created_at, updated_at "
            "FROM watches ORDER BY created_at, thesis_id"
        )
        return [
            Watch(
                thesis_id=thesis,
                cik=cik,
                ticker=ticker,
                company_name=name,
                policy=WatchPolicy(policy),
                created_at=unstamp(created),  # type: ignore[arg-type]
                updated_at=unstamp(updated),  # type: ignore[arg-type]
            )
            for thesis, cik, ticker, name, policy, created, updated in rows
        ]

    # Seen filings and jobs

    def seen(self, thesis_id: str) -> set[str]:
        """The accessions the watch on ``thesis_id`` has seen."""
        rows = self._db.query("SELECT accession FROM watch_seen WHERE thesis_id = ?", (thesis_id,))
        return {row[0] for row in rows}

    def note_filings(
        self,
        thesis_id: str,
        filings: Iterable[WatchedFiling],
        now: datetime,
        *,
        baseline: bool = False,
    ) -> list[WatchedFiling]:
        """Mark ``filings`` seen by the watch on ``thesis_id``; queue a job for each new one.

        With ``baseline`` (a thesis just put on watch) nothing is queued: a watch reports
        what is new from then on. Returns the filings a job was queued for. One
        transaction: a filing seen here gets its job, and the job's key is unique, so a
        second watcher noting the same filing queues nothing.
        """
        queued: list[WatchedFiling] = []
        when = stamp(now)
        with self._db.transaction() as connection:
            for filing in filings:
                fresh = connection.execute(
                    "INSERT OR IGNORE INTO watch_seen (thesis_id, accession, form, filed_date, "
                    "seen_at, baseline) VALUES (?, ?, ?, ?, ?, ?)",
                    (thesis_id, filing.accession, filing.form, filing.filed_date, when, baseline),
                ).rowcount
                if not fresh or baseline:
                    continue
                inserted = connection.execute(
                    "INSERT OR IGNORE INTO watch_jobs (id, thesis_id, accession, state, "
                    "not_before, created_at, updated_at, filing) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        job_id(thesis_id, filing.accession),
                        thesis_id,
                        filing.accession,
                        JobState.queued.value,
                        when,
                        when,
                        when,
                        filing.model_dump_json(),
                    ),
                ).rowcount
                if inserted:
                    queued.append(filing)
        return queued

    def jobs(self, thesis_id: str | None = None) -> list[WatchJob]:
        """Every job (of one thesis, when given), oldest first."""
        where, parameters = ("WHERE thesis_id = ?", (thesis_id,)) if thesis_id else ("", ())
        rows = self._db.query(
            f"SELECT {_JOB_COLUMNS} FROM watch_jobs {where} ORDER BY created_at, id", parameters
        )
        return [_job(row) for row in rows]

    def get_job(self, ident: str) -> WatchJob | None:
        """The job ``ident``, if there is one."""
        rows = self._db.query(f"SELECT {_JOB_COLUMNS} FROM watch_jobs WHERE id = ?", (ident,))
        return _job(rows[0]) if rows else None

    def job_counts(self, thesis_id: str | None = None) -> dict[JobState, int]:
        """How many jobs (of one thesis, when given) are in each state."""
        where, parameters = ("WHERE thesis_id = ?", (thesis_id,)) if thesis_id else ("", ())
        counts = dict.fromkeys(JobState, 0)
        for state, count in self._db.query(
            f"SELECT state, COUNT(*) FROM watch_jobs {where} GROUP BY state", parameters
        ):
            counts[JobState(state)] = count
        return counts

    def last_job_error(self, thesis_id: str) -> str:
        """The error of the newest failed job of ``thesis_id``, or ""."""
        rows = self._db.query(
            "SELECT error FROM watch_jobs WHERE thesis_id = ? AND state = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (thesis_id, JobState.failed.value),
        )
        return rows[0][0] if rows else ""

    def inbox_counts(self, thesis_id: str) -> tuple[int, int]:
        """(unread items, runs waiting) of ``thesis_id``'s inbox."""
        unread, waiting = self._db.query(
            "SELECT COUNT(*) - COUNT(read_at), SUM(kind = ?) FROM inbox WHERE thesis_id = ?",
            (InboxKind.waiting.value, thesis_id),
        )[0]
        return int(unread or 0), int(waiting or 0)  # SUM of no rows is NULL

    def claim_job(self, worker: str, now: datetime, lease_seconds: int) -> WatchJob | None:
        """Claim the oldest ready job for ``worker`` and lease it; None when none is ready.

        One ``UPDATE ... RETURNING`` statement: SQLite runs it under its write lock, so two
        workers (two processes) can never claim the same job.
        """
        when = stamp(now)
        with self._db.transaction() as connection:
            rows = connection.execute(
                "UPDATE watch_jobs SET state = ?, worker = ?, lease_until = ?, "
                "attempts = attempts + 1, updated_at = ? "
                "WHERE id = (SELECT id FROM watch_jobs WHERE state = ? AND not_before <= ? "
                "ORDER BY not_before, created_at, rowid LIMIT 1) AND state = ? "
                f"RETURNING {_JOB_COLUMNS}",
                (
                    JobState.running.value,
                    worker,
                    stamp(now + timedelta(seconds=lease_seconds)),
                    when,
                    JobState.queued.value,
                    when,
                    JobState.queued.value,
                ),
            ).fetchall()
        return _job(rows[0]) if rows else None

    def _settle(
        self, job: WatchJob, reason: str, now: datetime, *, expired: bool
    ) -> JobState | None:
        """Queue ``job`` again after its backoff, or fail it on its last attempt."""
        last = job.attempts >= wording.MAX_ATTEMPTS
        state = JobState.failed if last else JobState.queued
        wait = wording.BACKOFF_SECONDS[min(job.attempts, len(wording.BACKOFF_SECONDS)) - 1]
        owned = "lease_until <= ?" if expired else "worker = ?"
        with self._db.transaction() as connection:
            changed = connection.execute(
                "UPDATE watch_jobs SET state = ?, not_before = ?, lease_until = NULL, "
                f"error = ?, updated_at = ? WHERE id = ? AND state = ? AND {owned}",
                (
                    state.value,
                    stamp(now + timedelta(seconds=wait)),
                    reason,
                    stamp(now),
                    job.id,
                    JobState.running.value,
                    stamp(now) if expired else job.worker,
                ),
            ).rowcount
        return state if changed else None

    def fail_job(self, job: WatchJob, reason: str, now: datetime) -> JobState | None:
        """Record that ``job`` failed: retried after its backoff, or failed for good.

        Returns the new state, or None when the job is no longer this worker's (its
        lease ran out and another worker took it up).
        """
        return self._settle(job, reason, now, expired=False)

    def reap_expired(self, now: datetime) -> list[tuple[WatchJob, JobState]]:
        """Treat every job whose lease ran out as failed by a stopped worker.

        Returns each job settled here and its new state: queued again, or failed when that
        was its last attempt (the caller then writes its inbox item).
        """
        rows = self._db.query(
            f"SELECT {_JOB_COLUMNS} FROM watch_jobs WHERE state = ? AND lease_until <= ?",
            (JobState.running.value, stamp(now)),
        )
        settled: list[tuple[WatchJob, JobState]] = []
        for row in rows:
            job = _job(row)
            state = self._settle(job, wording.LEASE_EXPIRED, now, expired=True)
            if state is not None:
                settled.append((job, state))
        return settled

    def finish_job(self, job: WatchJob, outcome: str, now: datetime) -> bool:
        """Mark ``job`` done with what it did; False when it is no longer this worker's."""
        with self._db.transaction() as connection:
            changed = connection.execute(
                "UPDATE watch_jobs SET state = ?, outcome = ?, lease_until = NULL, updated_at = ? "
                "WHERE id = ? AND state = ? AND worker = ?",
                (
                    JobState.done.value,
                    outcome,
                    stamp(now),
                    job.id,
                    JobState.running.value,
                    job.worker,
                ),
            ).rowcount
        return changed > 0

    def take_auto_slot(self, ident: str, day: str, cap: int) -> bool:
        """Count job ``ident`` among the automatic runs of ``day`` if the cap allows.

        One conditional statement, so two watchers cannot both take the last slot. A job
        that already holds a slot of ``day`` (a retry) keeps it.
        """
        with self._db.transaction() as connection:
            changed = connection.execute(
                "UPDATE watch_jobs SET auto_run_day = ? WHERE id = ? AND (auto_run_day = ? OR "
                "(SELECT COUNT(*) FROM watch_jobs WHERE auto_run_day = ?) < ?)",
                (day, ident, day, day, cap),
            ).rowcount
        return changed > 0

    def auto_runs(self, day: str) -> int:
        """How many jobs ran their thesis automatically on ``day``."""
        return self._db.query("SELECT COUNT(*) FROM watch_jobs WHERE auto_run_day = ?", (day,))[0][
            0
        ]

    # The inbox

    def put_item(self, item: InboxItem) -> None:
        """Write ``item`` (one per job: a job tried again replaces its item); keeps read_at."""
        with self._db.transaction() as connection:
            connection.execute(
                "INSERT INTO inbox (id, thesis_id, job_id, kind, created_at, read_at, record) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (id) DO UPDATE SET kind = excluded.kind, "
                "record = excluded.record",
                (
                    item.id,
                    item.thesis_id,
                    item.job_id,
                    item.kind.value,
                    stamp(item.created_at),
                    stamp(item.read_at) if item.read_at else None,
                    item.model_dump_json(exclude={"read_at"}),
                ),
            )

    def _item(self, record: str, read_at: str | None) -> InboxItem:
        item = InboxItem.model_validate_json(record)
        item.read_at = unstamp(read_at)
        return item

    def get_item(self, ident: str) -> InboxItem | None:
        """The inbox item ``ident``, if there is one."""
        rows = self._db.query("SELECT record, read_at FROM inbox WHERE id = ?", (ident,))
        return self._item(*rows[0]) if rows else None

    def list_items(self, *, limit: int, offset: int, thesis_id: str | None = None) -> InboxPage:
        """One page of the inbox: unread first, then newest first; with the totals."""
        where, parameters = ("WHERE thesis_id = ?", (thesis_id,)) if thesis_id else ("", ())
        rows = self._db.query(
            f"SELECT record, read_at FROM inbox {where} "
            "ORDER BY read_at IS NOT NULL, created_at DESC, id DESC LIMIT ? OFFSET ?",
            (*parameters, limit, offset),
        )
        total, unread = self._db.query(
            f"SELECT COUNT(*), COUNT(*) - COUNT(read_at) FROM inbox {where}", parameters
        )[0]
        return InboxPage([self._item(*row) for row in rows], total, unread)

    def mark_read(self, ids: Sequence[str], now: datetime, *, read: bool) -> list[str]:
        """Mark the items ``ids`` read (or unread); the ids that exist."""
        if not ids:
            return []
        marks = ", ".join("?" for _ in ids)
        with self._db.transaction() as connection:
            connection.execute(
                f"UPDATE inbox SET read_at = ? WHERE id IN ({marks})",
                (stamp(now) if read else None, *ids),
            )
            found = connection.execute(
                f"SELECT id FROM inbox WHERE id IN ({marks})", tuple(ids)
            ).fetchall()
        return sorted(row[0] for row in found)

    def start_waiting(self, ident: str, run_id: str, now: datetime) -> bool:
        """Move a waiting item to running with ``run_id``; False unless it was waiting.

        The kind is checked and changed in one transaction under the write lock, so a run
        waiting in the inbox starts once however often it is asked for.
        """
        with self._db.transaction() as connection:
            changed = connection.execute(
                "UPDATE inbox SET kind = ? WHERE id = ? AND kind = ?",
                (InboxKind.running.value, ident, InboxKind.waiting.value),
            ).rowcount
            if not changed:
                return False
            record, read_at = connection.execute(
                "SELECT record, read_at FROM inbox WHERE id = ?", (ident,)
            ).fetchone()
            item = self._item(record, read_at)
            item.kind = InboxKind.running
            item.updated_at = now
            waiting = item.run.waiting_reason if item.run else ""
            item.run = InboxRun(
                state="running", waiting_reason=waiting, run_id=run_id, started_by="owner"
            )
            connection.execute(
                "UPDATE inbox SET record = ? WHERE id = ?",
                (item.model_dump_json(exclude={"read_at"}), ident),
            )
        return True

    def waiting_runs(self) -> int:
        """How many inbox items hold a run waiting for its owner."""
        return self._db.query(
            "SELECT COUNT(*) FROM inbox WHERE kind = ?", (InboxKind.waiting.value,)
        )[0][0]

    # Backup

    def unreadable(self) -> list[str]:
        """Stored watch records that no longer validate against the current models, named."""
        named: list[str] = []
        for ident, filing in self._db.query("SELECT id, filing FROM watch_jobs ORDER BY id"):
            if not _parses(WatchedFiling, filing):
                named.append(f"watch job {ident}")
        for ident, record in self._db.query("SELECT id, record FROM inbox ORDER BY id"):
            if not _parses(InboxItem, record):
                named.append(f"inbox item {ident}")
        return named

    def counts(self) -> dict[str, int]:
        """Rows in each watch table of the record."""
        return {
            table: self._db.query(f"SELECT COUNT(*) FROM {table}")[0][0] for table, _ in WATCH_KINDS
        }


@dataclass(frozen=True)
class Beat:
    """The newest heartbeat of a watcher."""

    worker: str
    started_at: datetime
    last_cycle_at: datetime
    interval_seconds: int
    last_cycle: dict[str, object]


@dataclass(frozen=True)
class Check:
    """When a company's filing index was last read by a watcher, the next time, and any error."""

    cik: int
    last_check_at: datetime
    next_check_at: datetime
    last_error: str


class WatchStatus:
    """The watcher's disposable status, in the filing cache: heartbeats and company checks."""

    def __init__(self, cache: FilingCache) -> None:
        """Create the status tables in ``cache``'s file if they are missing, and use them."""
        self._db = cache.extend(STATUS_SCHEMA)

    def beat(
        self,
        worker: str,
        started_at: datetime,
        now: datetime,
        interval_seconds: int,
        summary: dict[str, object],
    ) -> None:
        """Record that ``worker`` finished a cycle at ``now``, and what it did."""
        with self._db.transaction(durable=False) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO watcher_beats (worker, started_at, last_cycle_at, "
                "interval_seconds, last_cycle) VALUES (?, ?, ?, ?, ?)",
                (worker, stamp(started_at), stamp(now), interval_seconds, json.dumps(summary)),
            )

    def newest_beat(self) -> Beat | None:
        """The heartbeat of the watcher that finished a cycle last, if any did."""
        rows = self._db.query(
            "SELECT worker, started_at, last_cycle_at, interval_seconds, last_cycle "
            "FROM watcher_beats ORDER BY last_cycle_at DESC LIMIT 1"
        )
        if not rows:
            return None
        worker, started, last, interval, summary = rows[0]
        started_at, last_at = unstamp(started), unstamp(last)
        assert started_at is not None and last_at is not None  # NOT NULL columns
        return Beat(worker, started_at, last_at, interval, json.loads(summary))

    def record_check(self, cik: int, now: datetime, next_at: datetime, error: str) -> None:
        """Record a read of company ``cik``'s index (``error`` empty when it succeeded)."""
        with self._db.transaction(durable=False) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO watch_checks (cik, last_check_at, next_check_at, "
                "last_error) VALUES (?, ?, ?, ?)",
                (cik, stamp(now), stamp(next_at), error),
            )

    def checks(self) -> dict[int, Check]:
        """The last check of each company, by CIK."""
        rows = self._db.query(
            "SELECT cik, last_check_at, next_check_at, last_error FROM watch_checks"
        )
        return {
            cik: Check(cik, unstamp(last), unstamp(nxt), error)  # type: ignore[arg-type]
            for cik, last, nxt, error in rows
        }
