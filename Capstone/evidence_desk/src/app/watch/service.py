"""The standing watch: one watcher cycle, one job, and the use cases the API shares.

A **cycle** (:meth:`Watcher.cycle`) has two steps:

1. **Poll.** For each watched company, once however many theses watch it, list the
   10-K, 10-Q, 8-K and 8-K/A filings in EDGAR's index (one request, through the EDGAR
   client and its rate limit). Each filing a watch has not seen gets one job per
   (thesis, filing), unique in the record. A company whose index cannot be read is
   recorded with the error and tried again next cycle.
2. **Work.** Jobs whose lease ran out (a worker that stopped) are queued again or
   failed; then each ready job is claimed and done: :func:`app.core.triage.triage`
   first, with no model. Nothing bears: an inbox item "seen, not relevant", no run. It
   bears: with policy ``auto`` and a slot under the daily cap, the thesis is run through
   :mod:`app.services.theses` and :func:`app.services.thesis_run.execute_run` and compared
   with its previous finished run (:func:`app.core.watch_report.what_moved`); otherwise
   the inbox item says a run is waiting. A job that raises, or whose run fails, is
   retried after a backoff and, after its last attempt, written to the inbox as failed.

The watcher process is :mod:`app.watch.__main__`; the API (:mod:`app.watch.routes`) calls
:func:`start_watching`, :func:`stop_watching`, :func:`start_waiting_run` and
:func:`finish_inbox_run`.
"""

from __future__ import annotations

import logging
import os
import socket
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.core import watch_policy as wording
from app.core.change_models import FilingChanges
from app.core.documents import FetchedFiling, FilingRef
from app.core.models import Company, Run, RunStatus, Thesis
from app.core.ports import (
    Analyst,
    Checker,
    ClaimReaders,
    FilingSource,
    PageFetcher,
    SourceError,
)
from app.core.triage import ExtraRule, thesis_claims, triage, watched_filing
from app.core.watch_models import (
    InboxItem,
    InboxKind,
    InboxRun,
    JobState,
    Triage,
    Watch,
    WatchedFiling,
    WatchJob,
    WatchPolicy,
)
from app.core.watch_report import what_moved
from app.services import theses, thesis_run
from app.services.filing_changes import compare_pair, read_pair
from app.sources.http import fetch_page as default_fetch_page
from app.store import FactStore, FilingCache, Store
from app.watch.store import WatchStatus, WatchStore, item_id, stamp

log = logging.getLogger(__name__)

# EXTENSION POINT: further triage rules, each (claims, filing) -> [(claim id, reason)]. Left
# empty in version 14: a compiled claim's change of outcome needs the facts the new filing
# brings, which come only from EDGAR's company-facts API, a request triage does not make.
# It is reported after the run instead (WhatMoved.computed, app.core.watch_report).
EXTRA_TRIAGE_RULES: tuple[ExtraRule, ...] = ()

# How many of a form's filings are listed to find the one before a new 10-K or 10-Q.
FORM_HISTORY = 12
CRASH_MESSAGE = "The run stopped because of an internal error."

RunExecutor = Callable[[Run], Run]


class WatchedSource(FilingSource, Protocol):
    """What the watch needs of SEC EDGAR besides a run's needs (EdgarClient has all of it)."""

    def recent_filings(self, company: Company, forms: Sequence[str]) -> list[FilingRef]:
        """The filings of ``forms`` in the company's recent index, newest first."""
        ...


class FormLister(Protocol):
    """A source that can list a company's filings of one form (to compare a new 10-K or 10-Q)."""

    def filings_of_form(self, company: Company, form: str, limit: int) -> list[FilingRef]: ...

    def fetch(self, ref: FilingRef) -> FetchedFiling: ...


class UnknownItem(LookupError):
    """No inbox item has the id asked for."""


class NotWaiting(LookupError):
    """The inbox item holds no run waiting to be started (none, or it already started)."""


class JobFailed(Exception):
    """A job could not be completed; the message is safe to show."""


@dataclass(frozen=True)
class WatchSettings:
    """How often a watcher polls and how many runs the watches may start on their own a day."""

    interval_seconds: int = wording.DEFAULT_INTERVAL_SECONDS
    auto_runs_per_day: int = wording.DEFAULT_AUTO_RUNS_PER_DAY
    lease_seconds: int = wording.LEASE_SECONDS


def clamp_interval(seconds: int) -> int:
    """``seconds``, raised to :data:`~app.core.watch_policy.MIN_INTERVAL_SECONDS` if below it."""
    return max(seconds, wording.MIN_INTERVAL_SECONDS)


def default_worker() -> str:
    """This process's name among watchers: host and process id."""
    return f"{socket.gethostname()}:{os.getpid()}"


def run_executor(
    store: Store,
    filings: FilingSource,
    analyst: Analyst,
    cache: FilingCache,
    *,
    checker: Checker | None = None,
    fetch_page: PageFetcher = default_fetch_page,
    facts_store: FactStore | None = None,
    claim_reader: ClaimReaders = None,
) -> RunExecutor:
    """A function that executes a started run to its end, as the API's worker does.

    ``facts_store`` keeps the facts the run reads and ``claim_reader`` is the model
    parser when it is on (version 14), as for a run the app starts. A crash ends the run
    as failed with :data:`CRASH_MESSAGE`; a run never stays running.
    """

    def execute(run: Run) -> Run:
        try:
            return thesis_run.execute_run(
                run,
                store,
                filings=filings,
                analyst=analyst,
                fetch_page=fetch_page,
                cache=cache,
                checker=checker,
                facts_store=facts_store,
                claim_reader=claim_reader,
            )
        except Exception:  # noqa: BLE001 - last resort: a run must never stay "running"
            log.exception("Watch run %s crashed", run.id)
            return thesis_run.fail_run(run, store, CRASH_MESSAGE)

    return execute


# Use cases the API shares


def start_watching(
    store: Store,
    watches: WatchStore,
    filings: WatchedSource,
    thesis_id: str,
    policy: WatchPolicy,
    now: datetime,
) -> tuple[Watch, bool]:
    """Put a thesis on watch with ``policy``, or change the policy of its watch.

    On first watching, every filing EDGAR's index lists now is marked seen without a
    job: a watch reports what is new from then on. Watching again only changes the
    policy. Raises :class:`app.services.theses.UnknownThesis` and
    :class:`~app.core.ports.SourceError` (EDGAR could not be read; nothing is saved).
    Returns the watch and whether it is new.
    """
    thesis = store.get_thesis(thesis_id)
    if thesis is None:
        raise theses.UnknownThesis(thesis_id)
    existing = watches.get_watch(thesis_id)
    if existing is not None:
        changed = existing.model_copy(update={"policy": policy, "updated_at": now})
        watches.put_watch(changed)
        return changed, False
    company = filings.company(thesis.request.ticker)
    listed = [watched_filing(r) for r in filings.recent_filings(company, wording.WATCH_FORMS)]
    watch = Watch(
        thesis_id=thesis_id,
        cik=company.cik,
        ticker=company.ticker,
        company_name=company.name,
        policy=policy,
        created_at=now,
        updated_at=now,
    )
    watches.note_filings(thesis_id, listed, now, baseline=True)
    watches.put_watch(watch)
    return watch, True


def stop_watching(watches: WatchStore, thesis_id: str) -> bool:
    """Take a thesis off watch; False when it was not watched. Its inbox and jobs stay."""
    return watches.remove_watch(thesis_id)


def _headline(item: InboxItem) -> str:
    what = {
        InboxKind.not_relevant: item.triage.summary,
        InboxKind.waiting: f"{item.triage.summary} A run is waiting.",
        InboxKind.running: f"{item.triage.summary} A run is under way.",
        InboxKind.failed: item.error,
    }.get(item.kind) or (item.moved.line if item.moved else "")
    return wording.HEADLINE.format(ticker=item.ticker, filing=item.filing.label, what=what)


def _save(watches: WatchStore, item: InboxItem) -> InboxItem:
    item.collapsed = item.kind in wording.COLLAPSED_KINDS
    item.headline = _headline(item)
    watches.put_item(item)
    return item


def _previous_run(store: Store, run: Run) -> Run | None:
    """The newest finished run of the same thesis that started before ``run``."""
    if run.thesis_id is None:
        return None
    return next(
        (
            other
            for other in store.runs_of_thesis(run.thesis_id)
            if other.id != run.id
            and other.status in theses.FINISHED
            and other.started_at <= run.started_at
        ),
        None,
    )


def _run_failure(run: Run) -> str:
    """Why a run failed: its first two distinct errors (the cause, then the conclusion)."""
    errors = list(dict.fromkeys(error.rstrip(".") for error in run.errors))
    return "; ".join(errors[:2]) or "no reason was recorded"


def _complete(store: Store, item: InboxItem, run: Run, now: datetime) -> InboxItem:
    """Fill ``item`` from its finished (or failed) run."""
    item.updated_at = now
    started_by = item.run.started_by if item.run else "watch"
    waiting = item.run.waiting_reason if item.run else ""
    if run.status == RunStatus.failed:
        reason = _run_failure(run)
        item.kind = InboxKind.failed
        item.error = wording.RUN_FAILED.format(reason=reason)
        item.run = InboxRun(
            state="failed",
            waiting_reason=waiting,
            run_id=run.id,
            status=run.status.value,
            started_by=started_by,
        )
        return item
    item.moved = what_moved(_previous_run(store, run), run)
    item.kind = InboxKind.moved if item.moved.moved else InboxKind.nothing_moved
    item.run = InboxRun(
        state="finished",
        waiting_reason=waiting,
        run_id=run.id,
        status=run.status.value,
        started_by=started_by,
    )
    return item


def start_waiting_run(store: Store, watches: WatchStore, ident: str, now: datetime) -> Run:
    """Start the run an inbox item holds waiting, once; the caller executes it.

    Raises :class:`UnknownItem` and :class:`NotWaiting` (no run waits: it was never
    needed, or it already started), and :class:`app.services.theses.UnknownThesis`.
    """
    item = watches.get_item(ident)
    if item is None:
        raise UnknownItem(ident)
    if item.kind != InboxKind.waiting:
        raise NotWaiting(ident)
    run = theses.start_thesis_run(store, item.thesis_id)
    if not watches.start_waiting(ident, run.id, now):
        thesis_run.fail_run(run, store, "The waiting run was started from another request.")
        raise NotWaiting(ident)
    started = watches.get_item(ident)
    if started is not None and started.kind == InboxKind.running:
        _save(watches, started)  # its headline now says the run is under way
    return run


def finish_inbox_run(
    store: Store, watches: WatchStore, ident: str, run: Run, now: datetime
) -> InboxItem | None:
    """Write what the run an inbox item started moved (or why it failed) into the item."""
    item = watches.get_item(ident)
    if item is None:
        return None
    return _save(watches, _complete(store, item, run, now))


# The watcher


@dataclass
class CycleReport:
    """What one cycle did, counted; kept as the watcher's heartbeat."""

    started_at: str = ""
    finished_at: str = ""
    companies: int = 0
    index_errors: int = 0
    jobs_queued: int = 0
    jobs_done: int = 0
    jobs_retried: int = 0
    jobs_failed: int = 0
    leases_expired: int = 0
    errors: list[str] = field(default_factory=list)


class Watcher:
    """One watcher: polls the watched companies' indexes and works the ready jobs."""

    def __init__(
        self,
        *,
        store: Store,
        watches: WatchStore,
        status: WatchStatus,
        filings: WatchedSource,
        cache: FilingCache,
        execute: RunExecutor,
        settings: WatchSettings,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        worker: str | None = None,
        extra_rules: Sequence[ExtraRule] = EXTRA_TRIAGE_RULES,
    ) -> None:
        """Wire the watcher; ``now`` is its wall clock and ``execute`` runs a started run."""
        self.store = store
        self.watches = watches
        self.status = status
        self.filings = filings
        self.cache = cache
        self.execute = execute
        self.settings = settings
        self.now = now
        self.worker = worker or default_worker()
        self.extra_rules = tuple(extra_rules)
        self.started_at = now()

    # Poll

    def poll(self, report: CycleReport | None = None) -> CycleReport:
        """List each watched company's filings once and queue a job per new (thesis, filing)."""
        report = report or CycleReport()
        companies: dict[int, list[Watch]] = {}
        for watch in self.watches.list_watches():
            companies.setdefault(watch.cik, []).append(watch)
        for cik, group in companies.items():
            first = group[0]
            company = Company(cik=cik, ticker=first.ticker, name=first.company_name)
            now = self.now()
            next_at = now + timedelta(seconds=self.settings.interval_seconds)
            report.companies += 1
            try:
                refs = self.filings.recent_filings(company, wording.WATCH_FORMS)
            except SourceError as exc:
                report.index_errors += 1
                self.status.record_check(cik, now, next_at, str(exc))
                continue
            # Oldest first, so jobs are worked in the order the filings were made.
            listed = [watched_filing(ref) for ref in reversed(refs)]
            for watch in group:
                report.jobs_queued += len(self.watches.note_filings(watch.thesis_id, listed, now))
            self.status.record_check(cik, now, next_at, "")
        return report

    # Work

    def work(self, report: CycleReport | None = None) -> CycleReport:
        """Settle jobs whose lease ran out, then claim and do every ready job."""
        report = report or CycleReport()
        for job, state in self.watches.reap_expired(self.now()):
            report.leases_expired += 1
            if state == JobState.failed:
                report.jobs_failed += 1
                self._write_failed(job, wording.LEASE_EXPIRED)
        while (
            job := self.watches.claim_job(self.worker, self.now(), self.settings.lease_seconds)
        ) is not None:
            try:
                outcome = self.process(job)
            except Exception as exc:  # noqa: BLE001 - a job's failure is recorded, never lost
                reason = (
                    str(exc)
                    if isinstance(exc, JobFailed | SourceError)
                    else (thesis_run.safe_message(exc))
                )
                if not isinstance(exc, JobFailed | SourceError):
                    log.exception("Watch job %s failed", job.id)
                state = self.watches.fail_job(job, reason, self.now())
                if state == JobState.failed:
                    report.jobs_failed += 1
                    self._write_failed(job, reason)
                elif state == JobState.queued:
                    report.jobs_retried += 1
                continue
            if self.watches.finish_job(job, outcome, self.now()):
                report.jobs_done += 1
        return report

    def cycle(self) -> CycleReport:
        """Poll, work, and record the heartbeat with what the cycle did."""
        report = CycleReport(started_at=stamp(self.now()))
        self.poll(report)
        self.work(report)
        report.finished_at = stamp(self.now())
        self.status.beat(
            self.worker, self.started_at, self.now(), self.settings.interval_seconds, asdict(report)
        )
        return report

    # One job

    def _item(self, job: WatchJob, thesis: Thesis | None, result: Triage) -> InboxItem:
        now = self.now()
        return InboxItem(
            id=item_id(job.id),
            thesis_id=job.thesis_id,
            thesis_name=thesis.name if thesis else job.thesis_id,
            ticker=thesis.request.ticker if thesis else "",
            job_id=job.id,
            kind=InboxKind.not_relevant,
            created_at=now,
            updated_at=now,
            filing=job.filing,
            triage=result,
        )

    def _write_failed(self, job: WatchJob, reason: str) -> None:
        thesis = self.store.get_thesis(job.thesis_id)
        existing = self.watches.get_item(item_id(job.id))
        item = existing or self._item(
            job, thesis, Triage(bears=False, summary="The filing was not triaged.")
        )
        item.kind = InboxKind.failed
        item.updated_at = self.now()
        if item.run is not None and item.run.state == "running":  # its worker stopped mid-run
            item.run = item.run.model_copy(update={"state": "failed"})
        item.error = wording.JOB_GAVE_UP.format(attempts=job.attempts, reason=reason.rstrip("."))
        _save(self.watches, item)

    def _comparison(
        self, company: Company, filing: WatchedFiling
    ) -> tuple[FilingChanges | None, list[str]]:
        """The new 10-K or 10-Q compared with the one of its form before it, or why not."""
        lister = self.filings if hasattr(self.filings, "filings_of_form") else None
        if lister is None:
            return None, ["the filing source cannot list a company's filings of one form"]
        source: FormLister = lister  # type: ignore[assignment]
        try:
            refs = source.filings_of_form(company, filing.form, FORM_HISTORY)
            later = next((ref for ref in refs if ref.accession == filing.accession), None)
            if later is None:
                return None, [f"EDGAR does not list {filing.label} among its {filing.form}s yet"]
            before = [
                ref
                for ref in refs
                if (ref.filed_date, ref.accession) < (later.filed_date, later.accession)
            ]
            if not before:
                return None, [f"EDGAR lists no {filing.form} filed before {filing.label}"]
            earlier = max(before, key=lambda ref: (ref.filed_date, ref.accession))
            pair = read_pair(company, earlier, later, filings=source, cache=self.cache)  # type: ignore[arg-type]
            return compare_pair(pair, max_listed=None), []
        except SourceError as exc:
            return None, [str(exc)]
        except Exception as exc:  # noqa: BLE001 - untrusted filings: one bad pair is one note
            log.exception("Comparing %s with the filing before it failed", filing.url)
            return None, [f"the two filings could not be compared ({type(exc).__name__})"]

    def _queries(self, thesis: Thesis) -> dict[str, list[str]]:
        """The search queries the thesis's newest finished run wrote, by claim text."""
        for run in self.store.runs_of_thesis(thesis.id):
            if run.status in theses.FINISHED:
                return {claim.text.casefold(): list(claim.queries) for claim in run.claims}
        return {}

    def process(self, job: WatchJob) -> str:
        """Do one claimed job; return what it did in a few words. Raises to be retried."""
        thesis = self.store.get_thesis(job.thesis_id)
        if thesis is None:
            return wording.THESIS_GONE
        watch = self.watches.get_watch(job.thesis_id)
        if watch is None:
            return wording.NO_LONGER_WATCHED
        company = Company(cik=watch.cik, ticker=watch.ticker, name=watch.company_name)
        claims = thesis_claims(thesis.request.claims, self._queries(thesis))
        comparison, notes = (
            self._comparison(company, job.filing)
            if job.filing.form in wording.PERIODIC_FORMS
            else (None, [])
        )
        result = triage(claims, job.filing, comparison, notes=notes, extra_rules=self.extra_rules)
        item = self._item(job, thesis, result)
        if not result.bears:
            _save(self.watches, item)
            return "seen, not relevant"
        day = self.now().date().isoformat()
        automatic = watch.policy == WatchPolicy.auto and self.watches.take_auto_slot(
            job.id, day, self.settings.auto_runs_per_day
        )
        if not automatic:
            reason = (
                wording.WAITING_POLICY
                if watch.policy == WatchPolicy.ask
                else wording.WAITING_CAP.format(cap=self.settings.auto_runs_per_day)
            )
            item.kind = InboxKind.waiting
            item.run = InboxRun(state="waiting", waiting_reason=reason)
            _save(self.watches, item)
            return "a run is waiting"
        run = theses.start_thesis_run(self.store, thesis.id)
        item.kind = InboxKind.running
        item.run = InboxRun(state="running", run_id=run.id, started_by="watch")
        _save(self.watches, item)
        finished = self.execute(run)
        if finished.status == RunStatus.failed:
            # The item says the run failed now; the job is retried (a new run) or gives up.
            _save(self.watches, _complete(self.store, item, finished, self.now()))
            raise JobFailed(wording.RUN_FAILED.format(reason=_run_failure(finished)))
        _save(self.watches, _complete(self.store, item, finished, self.now()))
        return f"ran {run.id}"
