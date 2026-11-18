"""What the API and ``make watch-status`` show of the watch: each watch, and the watcher's health.

Read only: built from the record (:class:`~app.watch.store.WatchStore`), the disposable
status (:class:`~app.watch.store.WatchStatus`) and a wall-clock time. Every count and
every label is computed here, so a page only draws it.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from app.core import watch_policy as wording
from app.core.watch_models import JobState, WatchPolicy
from app.store import Store
from app.watch.store import WatchStatus, WatchStore


class JobCounts(BaseModel):
    """Jobs in each state."""

    queued: int = 0
    running: int = 0
    done: int = 0
    failed: int = 0


def _counts(counts: dict[JobState, int]) -> JobCounts:
    return JobCounts(**{state.value: count for state, count in counts.items()})


class WatchSummary(BaseModel):
    """One watched thesis: its policy, its company's last and next check, its jobs and inbox.

    ``last_check_at`` and ``next_check_at`` are None before the first cycle that read the
    company's index; ``next_check_note`` then says when it will be. ``last_error`` is the
    error of the last check ("" when it succeeded); ``last_job_error`` that of the newest
    job that gave up.
    """

    thesis_id: str
    thesis_name: str
    ticker: str
    company_name: str
    policy: WatchPolicy
    policy_label: str
    watching_since: datetime
    last_check_at: datetime | None = None
    next_check_at: datetime | None = None
    next_check_note: str = ""
    last_error: str = ""
    last_job_error: str = ""
    jobs: JobCounts = Field(default_factory=JobCounts)
    unread: int = 0
    waiting_runs: int = 0


class WatchList(BaseModel):
    """Every watch, oldest first, and the watcher's polling interval."""

    watches: list[WatchSummary]
    interval_seconds: int


class WatcherHealth(BaseModel):
    """Whether a watcher is running, when it last finished a cycle, and the queue.

    ``alive`` is True when the newest heartbeat is at most ``stale_after_seconds`` old
    (two intervals and a minute); ``note`` says it in words. ``last_cycle`` is what that
    cycle counted (companies, index errors, jobs queued, done, retried and failed).
    ``queue_depth`` is the jobs queued or running.
    """

    alive: bool
    note: str
    worker: str | None = None
    started_at: datetime | None = None
    last_cycle_at: datetime | None = None
    interval_seconds: int
    stale_after_seconds: int
    last_cycle: dict[str, object] = Field(default_factory=dict)
    jobs: JobCounts = Field(default_factory=JobCounts)
    queue_depth: int = 0
    waiting_runs: int = 0
    watches: int = 0


NOT_RUNNING = "No watcher has finished a cycle: start it with `make up` or run `make watch-once`."
STALE = (
    "The watcher's last cycle finished {age} seconds ago, longer than {limit}: it is not running."
)
ALIVE = "The watcher finished a cycle {age} seconds ago."


def watch_list(
    store: Store, watches: WatchStore, status: WatchStatus, interval_seconds: int
) -> WatchList:
    """Every watch with its last and next check, its last error, its jobs and its inbox."""
    checks = status.checks()
    rows: list[WatchSummary] = []
    for watch in watches.list_watches():
        thesis = store.get_thesis(watch.thesis_id)
        check = checks.get(watch.cik)
        unread, waiting = watches.inbox_counts(watch.thesis_id)
        rows.append(
            WatchSummary(
                thesis_id=watch.thesis_id,
                thesis_name=thesis.name if thesis else watch.thesis_id,
                ticker=watch.ticker,
                company_name=watch.company_name,
                policy=watch.policy,
                policy_label=wording.POLICY_LABELS[watch.policy],
                watching_since=watch.created_at,
                last_check_at=check.last_check_at if check else None,
                next_check_at=check.next_check_at if check else None,
                next_check_note="" if check else wording.NEXT_CHECK_UNKNOWN,
                last_error=check.last_error if check else "",
                last_job_error=watches.last_job_error(watch.thesis_id),
                jobs=_counts(watches.job_counts(watch.thesis_id)),
                unread=unread,
                waiting_runs=waiting,
            )
        )
    return WatchList(watches=rows, interval_seconds=interval_seconds)


def health(
    watches: WatchStore, status: WatchStatus, now: datetime, interval_seconds: int
) -> WatcherHealth:
    """Whether a watcher is alive at ``now``, from its heartbeat, and the state of the queue.

    The interval is the one the watcher reported in its heartbeat (``interval_seconds``,
    this process's setting, only before any heartbeat).
    """
    beat = status.newest_beat()
    if beat is not None:
        interval_seconds = beat.interval_seconds
    limit = interval_seconds * wording.ALIVE_INTERVALS + wording.ALIVE_GRACE_SECONDS
    counts = _counts(watches.job_counts())
    common = {
        "interval_seconds": interval_seconds,
        "stale_after_seconds": limit,
        "jobs": counts,
        "queue_depth": counts.queued + counts.running,
        "waiting_runs": watches.waiting_runs(),
        "watches": len(watches.list_watches()),
    }
    if beat is None:
        return WatcherHealth(alive=False, note=NOT_RUNNING, **common)
    age = max(0, int((now - beat.last_cycle_at).total_seconds()))
    alive = now - beat.last_cycle_at <= timedelta(seconds=limit)
    return WatcherHealth(
        alive=alive,
        note=ALIVE.format(age=age) if alive else STALE.format(age=age, limit=limit),
        worker=beat.worker,
        started_at=beat.started_at,
        last_cycle_at=beat.last_cycle_at,
        last_cycle=beat.last_cycle,
        **common,
    )
