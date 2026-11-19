"""Record types for the standing watch (version 13): watches, triage, jobs and the inbox.

Pure data: nothing here touches the network, the file system or a clock. The values
are computed by :mod:`app.core.triage`, :mod:`app.core.watch_report` and
:mod:`app.watch.service`, kept in the record by :mod:`app.watch.store` and returned by
the API (:mod:`app.watch.routes`); a view only draws them.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ed_v13.core.models import ClaimChange, Verdict


class WatchPolicy(StrEnum):
    """What a watch does when triage says a new filing bears on a claim.

    ``auto`` runs the thesis at once (within the daily cap on automatic runs);
    ``ask`` leaves the run waiting in the inbox until the owner starts it.
    """

    auto = "auto"
    ask = "ask"


class JobState(StrEnum):
    """Where one (thesis, filing) job is.

    ``queued``: waiting to be claimed (a retry waits until ``not_before``).
    ``running``: claimed by a worker until its lease ends. ``done``: triaged, and its
    inbox item written. ``failed``: gave up after the last attempt; ``error`` says why.
    """

    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class InboxKind(StrEnum):
    """What one inbox item says about one new filing of a watched thesis.

    ``not_relevant``: triage found nothing it bears on; no run (collapsed in a listing).
    ``waiting``: it bears on a claim and a run waits for the owner (policy ``ask``, or
    the daily cap on automatic runs was reached). ``running``: a run started and has not
    finished. ``moved`` / ``nothing_moved``: the run finished and was compared with the
    previous one. ``failed``: the job or the run could not be completed; ``error`` says why.
    """

    not_relevant = "not_relevant"
    waiting = "waiting"
    running = "running"
    moved = "moved"
    nothing_moved = "nothing_moved"
    failed = "failed"


class FilingItem(BaseModel):
    """One 8-K item as EDGAR's index lists it, with SEC's title and its category."""

    number: str
    title: str
    category: str


class WatchedFiling(BaseModel):
    """One filing the watch noticed: what EDGAR's index says about it.

    ``report_date`` is the index's report date (a period end, or an 8-K's event date);
    ``items`` are an 8-K's items (empty for a 10-K or 10-Q); ``label`` is the line a
    page shows ("8-K of 12 Nov 2026, Items 5.02 and 9.01").
    """

    accession: str
    form: str
    filed_date: str
    report_date: str = ""
    url: str
    items: list[FilingItem] = Field(default_factory=list)
    label: str = ""


class NamedParagraph(BaseModel):
    """A changed paragraph of a new 10-K or 10-Q that shares words with one claim.

    Chosen by the rule of :mod:`app.core.claim_changes` (two shared content terms,
    ranked by BM25). ``kind`` is added, removed, reworded or numbers_only; ``text`` is
    the paragraph (the later one of a pair), verbatim; ``link`` opens it in the filing.
    """

    kind: str
    item: str
    text: str
    link: str = ""
    matched_terms: list[str] = Field(default_factory=list)


class ClaimTriage(BaseModel):
    """What triage decided for one claim: whether the filing bears on it, and why."""

    claim_id: str
    claim: str
    categories: list[str] = Field(default_factory=list)
    bears: bool = False
    reasons: list[str] = Field(default_factory=list)
    paragraphs: list[NamedParagraph] = Field(default_factory=list)


class TriageRule(StrEnum):
    """The rule that decided a filing's triage, for counting and for the page's label."""

    periodic_report = "periodic_report"
    results_announced = "results_announced"
    event_category = "event_category"
    no_items = "no_items"
    routine = "routine"
    no_match = "no_match"
    extension = "extension"


class Triage(BaseModel):
    """The deterministic decision on one new filing for one thesis. No model is involved.

    ``bears`` is True when it bears on at least one claim; ``rules`` are the rules that
    fired, in the order applied; ``summary`` is one sentence; ``notes`` say what could
    not be done (a comparison that could not be made), never an error.
    """

    bears: bool
    rules: list[TriageRule] = Field(default_factory=list)
    summary: str
    claims: list[ClaimTriage] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ClaimNote(BaseModel):
    """A caution or an 8-K note that a claim has now and did not have in the previous run."""

    claim: str
    text: str


class NewEvent(BaseModel):
    """An 8-K on the new run's timeline that the previous run's timeline did not list."""

    accession: str
    form: str
    filed_date: str
    items: list[str] = Field(default_factory=list)
    url: str
    label: str = ""


class VerdictMove(BaseModel):
    """One claim whose verdict differs between the previous run and the new one."""

    claim: str
    before: Verdict | None
    after: Verdict | None


class WhatMoved(BaseModel):
    """What a watch-triggered run changed, against the previous finished run of the thesis.

    ``moved`` is True when a verdict moved, a caution or an 8-K note is new, or an 8-K
    is new on the timeline. ``line`` says it in one sentence ("Nothing moved." when
    nothing did). ``comparison`` is the full claim-by-claim comparison, None when the
    thesis had no earlier finished run.
    """

    earlier_run_id: str | None = None
    later_run_id: str
    moved: bool = False
    verdicts: list[VerdictMove] = Field(default_factory=list)
    new_cautions: list[ClaimNote] = Field(default_factory=list)
    new_notes: list[ClaimNote] = Field(default_factory=list)
    new_events: list[NewEvent] = Field(default_factory=list)
    sources_added: list[str] = Field(default_factory=list)
    line: str = ""
    claims: list[ClaimChange] = Field(default_factory=list)
    comparison_note: str = ""


class InboxRun(BaseModel):
    """The run an inbox item started or waits for.

    ``state`` is "waiting", "running", "finished" or "failed"; ``waiting_reason`` says
    why a run waits (the policy, or the daily cap); ``run_id`` is set once it started.
    """

    state: str
    waiting_reason: str = ""
    run_id: str | None = None
    status: str | None = None
    started_by: str = ""


class InboxItem(BaseModel):
    """One inbox item: a new filing of a watched thesis's company and what came of it.

    ``read_at`` is None while unread. ``collapsed`` is True for a kind a listing folds
    away by default (``not_relevant``). ``headline`` is the one line a listing shows.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    thesis_id: str
    thesis_name: str
    ticker: str
    job_id: str
    kind: InboxKind
    created_at: datetime
    updated_at: datetime
    read_at: datetime | None = None
    collapsed: bool = False
    headline: str = ""
    filing: WatchedFiling
    triage: Triage
    run: InboxRun | None = None
    moved: WhatMoved | None = None
    error: str = ""


class Watch(BaseModel):
    """A saved thesis on watch, as the record keeps it."""

    thesis_id: str
    cik: int
    ticker: str
    company_name: str
    policy: WatchPolicy
    created_at: datetime
    updated_at: datetime


class WatchJob(BaseModel):
    """One (thesis, filing) job, as the record keeps it."""

    id: str
    thesis_id: str
    accession: str
    state: JobState
    attempts: int = 0
    not_before: datetime
    lease_until: datetime | None = None
    worker: str = ""
    error: str = ""
    outcome: str = ""
    auto_run_day: str | None = None
    created_at: datetime
    updated_at: datetime
    filing: WatchedFiling
