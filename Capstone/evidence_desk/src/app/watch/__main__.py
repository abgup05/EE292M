"""The watcher process: ``python -m app.watch [run | once | status]``.

``run`` (the default, the ``watch`` service of ``docker/compose.yaml``) does a cycle
every ``EVIDENCE_DESK_WATCH_INTERVAL_SECONDS`` until stopped (SIGTERM or SIGINT end it
between cycles, or while it waits). ``once`` (``make watch-once``) does one cycle, prints
what it did and exits. ``status`` (``make watch-status``) prints each watch, the
watcher's heartbeat and the queue, and exits. Every collaborator comes from
:mod:`app.wiring`: the record, the cache, EDGAR and the configured engine.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from types import FrameType

from app import wiring
from app.store import Store
from app.watch.service import Watcher, WatchSettings, run_executor
from app.watch.store import WatchStatus, WatchStore
from app.watch.views import health, watch_list

log = logging.getLogger("app.watch")


def build_watcher(settings: WatchSettings | None = None) -> Watcher:
    """A watcher over the configured record, cache, EDGAR client and engine."""
    store = wiring.store_from_env()
    cache = wiring.cache_from_env()
    filings = wiring.filings_from_env()
    analyst = wiring.analyst_from_env()
    checker = wiring.checker_from_env(analyst)
    return Watcher(
        store=store,
        watches=WatchStore(store),
        status=WatchStatus(cache),
        filings=filings,
        cache=cache,
        execute=run_executor(
            store,
            filings,
            analyst,
            cache,
            checker=checker,
            facts_store=wiring.facts_from_env(),
            claim_reader=wiring.claim_reader_from_env(analyst),
        ),
        settings=settings or wiring.watch_settings_from_env(),
    )


def summary_line(report: dict[str, object]) -> str:
    """One cycle's counts as one line."""
    return (
        "watch cycle: {companies} companies checked, {index_errors} index errors, "
        "{jobs_queued} jobs queued, {jobs_done} done, {jobs_retried} to retry, "
        "{jobs_failed} failed, {leases_expired} leases expired".format(**report)
    )


def status_lines(
    store: Store, watches: WatchStore, status: WatchStatus, now: datetime, interval: int
) -> list[str]:
    """What ``make watch-status`` prints: the watcher's health, then each watch."""
    state = health(watches, status, now, interval)
    lines = [
        f"watcher: {'alive' if state.alive else 'not running'}. {state.note}",
        f"queue: {state.jobs.queued} queued, {state.jobs.running} running, "
        f"{state.jobs.done} done, {state.jobs.failed} failed; "
        f"{state.waiting_runs} runs waiting for their owner",
    ]
    listed = watch_list(store, watches, status, interval).watches
    if not listed:
        lines.append("no thesis is watched")
    for row in listed:
        checked = row.last_check_at.isoformat() if row.last_check_at else "never"
        upcoming = row.next_check_at.isoformat() if row.next_check_at else row.next_check_note
        lines.append(
            f"{row.thesis_id} {row.ticker} '{row.thesis_name}' ({row.policy.value}): last check "
            f"{checked}, next {upcoming}; {row.unread} unread, {row.waiting_runs} waiting"
            + (f"; last error: {row.last_error}" if row.last_error else "")
            + (f"; last job error: {row.last_job_error}" if row.last_job_error else "")
        )
    return lines


def serve(watcher: Watcher, stop: threading.Event) -> None:
    """Cycle until ``stop`` is set; a cycle that raises is logged and the next one runs."""
    while not stop.is_set():
        try:
            log.info(summary_line(asdict(watcher.cycle())))
        except Exception:  # noqa: BLE001 - the daemon must outlive one bad cycle; logged in full
            log.exception("A watch cycle failed")
        stop.wait(watcher.settings.interval_seconds)


def main(argv: list[str] | None = None, *, make: Callable[[], Watcher] = build_watcher) -> int:
    """Run the watcher, one cycle, or print the status; returns the exit code."""
    parser = argparse.ArgumentParser(prog="python -m app.watch", description=__doc__.split("\n")[0])
    parser.add_argument("command", nargs="?", default="run", choices=("run", "once", "status"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    watcher = make()
    if args.command == "status":
        for line in status_lines(
            watcher.store,
            watcher.watches,
            watcher.status,
            datetime.now(UTC),
            watcher.settings.interval_seconds,
        ):
            print(line)
        return 0
    if args.command == "once":
        print(summary_line(asdict(watcher.cycle())))
        return 0
    stop = threading.Event()

    def on_signal(signum: int, frame: FrameType | None) -> None:
        log.info("signal %d: stopping after this cycle", signum)
        stop.set()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    log.info("watching every %d seconds as %s", watcher.settings.interval_seconds, watcher.worker)
    serve(watcher, stop)
    return 0


if __name__ == "__main__":
    sys.exit(main())
