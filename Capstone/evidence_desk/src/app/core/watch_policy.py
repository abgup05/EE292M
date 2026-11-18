"""Every number and every sentence of the standing watch (version 14), in one place.

Kept apart from :mod:`app.core.limits` and :mod:`app.core.policy` so the watch can be
merged without touching their contract tests; the page reads all of it from
``GET /api/watch/meta``. Imports nothing from the application but the watch's enums.
"""

from __future__ import annotations

from app.core.watch_models import InboxKind, JobState, TriageRule, WatchPolicy

# Polling. EDGAR's fair-use policy allows 10 requests a second; a watch cycle makes one
# request per watched company. The floor keeps a cycle at most every five minutes: EDGAR's
# index updates within minutes of acceptance and a company has four business days to file
# an 8-K, so polling faster buys nothing a reader can act on.
DEFAULT_INTERVAL_SECONDS = 900
MIN_INTERVAL_SECONDS = 300
# A watcher whose last cycle is older than this many intervals (plus a minute) is not alive.
ALIVE_INTERVALS = 2
ALIVE_GRACE_SECONDS = 60

# Automatic runs started by all watches together in one UTC day; further jobs wait as "ask".
DEFAULT_AUTO_RUNS_PER_DAY = 5
DEFAULT_POLICY = WatchPolicy.ask

# Jobs. A claimed job is leased for longer than a run may take (300 s) plus its triage; a job
# still "running" after its lease belongs to a worker that stopped, and is taken up again.
LEASE_SECONDS = 900
MAX_ATTEMPTS = 4
# The wait before attempt 2, 3 and 4. A watcher works ready jobs once per cycle, so a retry
# runs at the first cycle after its wait.
BACKOFF_SECONDS = (60, 300, 1800)

# The forms a watch notices. 10-K/A and 10-Q/A are not: a run never reads them.
WATCH_FORMS = ("10-K", "10-Q", "8-K", "8-K/A")
PERIODIC_FORMS = ("10-K", "10-Q")
RESULTS_ITEM = "2.02"
# Changed paragraphs named under one claim for a new 10-K or 10-Q.
PARAGRAPHS_PER_CLAIM = 3
# Inbox paging.
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
MAX_MARK_READ = 100

# Triage wording. {n} is a claim's number, {items} "Item 5.02" or "Items 1.01 and 2.03".
REASON_PERIODIC = "A new {form} carries new reported figures, so every claim is tested again."
REASON_PARAGRAPHS = "{count} changed paragraph{plural} of it share{verb} words with this claim."
REASON_NO_PARAGRAPHS = "No changed paragraph of it shares two words with this claim."
REASON_RESULTS = "New results announced (Item 2.02); the figures arrive with the quarterly report."
REASON_CATEGORY = "{items} reports {words}, a subject of this claim ({categories})."
REASON_NO_ITEMS = (
    "EDGAR's index lists no items for this 8-K, so triage cannot rule it out for any claim."
)
SUMMARY_PERIODIC = "A new {form}: it bears on every claim ({claims} of {claims})."
SUMMARY_BEARS = "It bears on {count} of {claims} claims."
SUMMARY_ROUTINE = "A routine 8-K ({items}: {words}); it bears on no claim and no run is needed."
SUMMARY_NO_MATCH = (
    "{items} reports {words}; no claim of this thesis is about that, so no run is needed."
)
ROUTINE_WORDS = {
    "results": "results of operations",
    "governance": "a governance matter such as a shareholder vote or a bylaw change",
    "disclosure": "a Regulation FD or other voluntary disclosure",
    "exhibits": "exhibits only",
    "other": "an item outside the categories the claims are matched on",
}
NOTE_NO_COMPARISON = "The changed paragraphs could not be named: {reason}"

# Inbox wording.
KIND_LABELS = {
    InboxKind.not_relevant: "Seen, not relevant",
    InboxKind.waiting: "Run waiting",
    InboxKind.running: "Running",
    InboxKind.moved: "Something moved",
    InboxKind.nothing_moved: "Nothing moved",
    InboxKind.failed: "Could not be completed",
}
COLLAPSED_KINDS = (InboxKind.not_relevant,)
POLICY_LABELS = {
    WatchPolicy.auto: "Run at once",
    WatchPolicy.ask: "Ask before running",
}
JOB_STATE_LABELS = {
    JobState.queued: "Queued",
    JobState.running: "Running",
    JobState.done: "Done",
    JobState.failed: "Failed",
}
RULE_LABELS = {
    TriageRule.periodic_report: "New annual or quarterly report",
    TriageRule.results_announced: "Results announced",
    TriageRule.event_category: "8-K item on a claim's subject",
    TriageRule.no_items: "8-K with no items listed",
    TriageRule.routine: "Routine 8-K",
    TriageRule.no_match: "8-K on no claim's subject",
    TriageRule.extension: "Added rule",
}
HEADLINE = "{ticker}: {filing}. {what}"
WAITING_POLICY = "The watch asks before running; start the run when you want it."
WAITING_CAP = (
    "The daily cap of {cap} automatic runs across all watches was reached; start the run when "
    "you want it."
)
NOTHING_MOVED = "Nothing moved."
FIRST_RUN = "This is the thesis's first finished run, so there is nothing to compare it with."
RUN_FAILED = "The run failed: {reason}"
JOB_GAVE_UP = "Gave up after {attempts} attempts: {reason}"
LEASE_EXPIRED = "the worker stopped while the job was running (its lease ran out)"
NO_LONGER_WATCHED = "The thesis is no longer watched; the filing was not triaged."
THESIS_GONE = "The thesis no longer exists; the filing was not triaged."
NEXT_CHECK_UNKNOWN = "At the watcher's next cycle."
