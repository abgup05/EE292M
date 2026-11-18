"""The watcher: a cycle notices new filings, triages them and runs or waits; the inbox says so.

Offline: a fake EDGAR whose index gains filings when a test adds them, a scripted
engine, and a wall clock the test moves. The end-to-end case is
``test_end_to_end_a_new_5_02_8k_runs_the_thesis_and_the_inbox_says_what_moved``.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from app.core import watch_policy as wording
from app.core.documents import Passage
from app.core.models import (
    Claim,
    Confidence,
    Run,
    Stance,
    ThesisCreate,
    ThesisRequest,
    Verdict,
)
from app.core.ports import ClaimDraft, FindingDraft, Quote, SourceError
from app.core.watch_models import InboxKind, JobState, TriageRule, WatchPolicy
from app.services import theses
from app.store import FilingCache, Store
from app.watch.service import (
    Watcher,
    WatchSettings,
    finish_inbox_run,
    run_executor,
    start_waiting_run,
    start_watching,
    stop_watching,
)
from app.watch.store import WatchStatus, WatchStore
from tests.fakes import (
    FakeFilings,
    FakePages,
    FormFakeFilings,
    ScriptedAnalyst,
    WallClock,
    current_report_html,
    current_report_ref,
    filing_html,
    synthetic_ref,
)
from tests.test_events_run import (
    ANNUAL,
    CEO_SENTENCE,
    CLAIM,
    DEPARTURE,
    DEPARTURE_8K,
    QUARTER,
    departure_html,
    filings,
)

T0 = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
GROWTH = "Revenue grew in the quarter as demand for systems rose."


def departure_or_annual(claim: Claim, passages: list[Passage]) -> ClaimDraft:
    """Supports the claim from the 8-K when it is offered, else challenges it from the 10-K."""
    if claim.text != CLAIM:
        return ClaimDraft(rationale="Nothing scripted for this claim.")
    eight_k = next((p for p in passages if DEPARTURE in p.text), None)
    if eight_k is not None:
        statement, stance, passage, text = (
            "The 8-K reports that Jane Smith resigned as chief executive.",
            Stance.supports,
            eight_k,
            DEPARTURE,
        )
    else:
        passage = next(p for p in passages if CEO_SENTENCE in p.text)
        statement, stance, text = (
            "The annual report names Jane Smith as chief executive.",
            Stance.challenges,
            CEO_SENTENCE,
        )
    return ClaimDraft(
        findings=[
            FindingDraft(
                statement=statement,
                stance=stance,
                quotes=[Quote(passage_id=passage.id, text=text)],
                confidence=Confidence.medium,
                rationale="Scripted by the test.",
            )
        ],
        rationale="Scripted by the test.",
    )


@dataclasses.dataclass
class Desk:
    """One record, one cache, one fake EDGAR, a watcher and its clock."""

    store: Store
    watches: WatchStore
    status: WatchStatus
    source: FakeFilings
    clock: WallClock
    watcher: Watcher
    thesis_id: str

    def execute(self, run: Run) -> Run:
        return self.watcher.execute(run)

    def run_thesis(self) -> Run:
        return self.execute(theses.start_thesis_run(self.store, self.thesis_id))


def desk(
    source: FakeFilings | None = None,
    *,
    claims: list[str] | None = None,
    cap: int = wording.DEFAULT_AUTO_RUNS_PER_DAY,
) -> Desk:
    store = Store(":memory:")
    cache = FilingCache()
    source = source or filings()
    clock = WallClock(T0)
    analyst = ScriptedAnalyst(departure_or_annual)
    watches = WatchStore(store)
    status = WatchStatus(cache)
    execute = run_executor(store, source, analyst, cache, fetch_page=FakePages({}))
    watcher = Watcher(
        store=store,
        watches=watches,
        status=status,
        filings=source,
        cache=cache,
        execute=execute,
        settings=WatchSettings(interval_seconds=900, auto_runs_per_day=cap),
        now=clock,
        worker="test-worker",
    )
    thesis = theses.create_thesis(
        store,
        ThesisCreate(
            name="Jane Smith is gone",
            request=ThesisRequest(
                ticker="NVDA",
                decision="Whether to buy the shares after the change at the top",
                claims=claims or [CLAIM, GROWTH],
                filings=2,
            ),
        ),
    )
    return Desk(store, watches, status, source, clock, watcher, thesis.id)


def watch(d: Desk, policy: WatchPolicy) -> None:
    start_watching(d.store, d.watches, d.source, d.thesis_id, policy, d.clock())


def gain(d: Desk, ref: object, html: str) -> None:
    """The fake index lists a new filing (an 8-K, or a periodic report) from now on."""
    if ref.form.startswith("8-K"):  # type: ignore[attr-defined]
        d.source.current.append(ref)  # type: ignore[arg-type]
    else:
        d.source.refs.insert(0, ref)  # type: ignore[arg-type]
    d.source.documents[ref.url] = html  # type: ignore[attr-defined]
    d.clock.advance(900)


def test_end_to_end_a_new_5_02_8k_runs_the_thesis_and_the_inbox_says_what_moved() -> None:
    d = desk()
    before = d.run_thesis()
    assert before.claims[0].verdict == Verdict.challenged
    watch(d, WatchPolicy.auto)
    assert d.watcher.cycle().jobs_queued == 0  # what was there before the watch is not new

    gain(d, DEPARTURE_8K, departure_html())
    report = d.watcher.cycle()

    assert report.jobs_queued == 1 and report.jobs_done == 1
    [item] = d.watches.list_items(limit=10, offset=0).items
    assert item.filing.accession == DEPARTURE_8K.accession
    assert item.filing.label == "8-K of 10 Mar 2026, Items 5.02 and 9.01"
    assert item.filing.url == DEPARTURE_8K.url
    claim_1, claim_2 = item.triage.claims
    assert claim_1.bears and claim_1.categories == ["leadership"]
    assert "Item 5.02" in claim_1.reasons[0] and "leadership" in claim_1.reasons[0]
    assert not claim_2.bears
    assert item.triage.rules == [TriageRule.event_category]
    assert item.kind == InboxKind.moved
    assert item.run is not None and item.run.started_by == "watch"
    after = d.store.get_run(item.run.run_id or "")
    assert after is not None and after.claims[0].verdict == Verdict.supported
    assert item.moved is not None
    assert [(v.claim, v.before, v.after) for v in item.moved.verdicts] == [
        (CLAIM, Verdict.challenged, Verdict.supported)
    ]
    assert [e.accession for e in item.moved.new_events] == [DEPARTURE_8K.accession]
    assert item.moved.line == "1 of 2 verdicts moved; 1 new 8-K on the timeline."
    assert "8-K of 10 Mar 2026" in item.headline and item.moved.line in item.headline
    assert len(d.store.get_thesis(d.thesis_id).run_ids) == 2  # type: ignore[union-attr]

    d.clock.advance(900)
    again = d.watcher.cycle()
    assert again.jobs_queued == 0 and again.jobs_done == 0
    assert len(d.store.get_thesis(d.thesis_id).run_ids) == 2  # type: ignore[union-attr]


def test_a_routine_8k_is_seen_and_skipped_without_a_run() -> None:
    d = desk()
    watch(d, WatchPolicy.auto)
    vote = current_report_ref(3, "2026-03-11", "5.07")
    gain(d, vote, current_report_html(("5.07", "Submission of Matters.", ["Votes."])))

    d.watcher.cycle()

    [item] = d.watches.list_items(limit=10, offset=0).items
    assert item.kind == InboxKind.not_relevant and item.collapsed
    assert item.run is None and item.moved is None
    assert "shareholder vote" in item.triage.summary
    assert d.store.get_thesis(d.thesis_id).run_ids == []  # type: ignore[union-attr]
    assert d.watches.jobs()[0].state == JobState.done


def test_policy_ask_leaves_the_run_waiting_until_the_owner_starts_it() -> None:
    d = desk()
    d.run_thesis()
    watch(d, WatchPolicy.ask)
    gain(d, DEPARTURE_8K, departure_html())

    d.watcher.cycle()

    [item] = d.watches.list_items(limit=10, offset=0).items
    assert item.kind == InboxKind.waiting
    assert item.run is not None and item.run.state == "waiting"
    assert item.run.waiting_reason == wording.WAITING_POLICY
    assert len(d.store.get_thesis(d.thesis_id).run_ids) == 1  # type: ignore[union-attr]

    run = start_waiting_run(d.store, d.watches, item.id, d.clock())
    started = d.watches.get_item(item.id)
    assert started is not None and started.kind == InboxKind.running
    assert started.headline.endswith("A run is under way.")
    with pytest.raises(LookupError):
        start_waiting_run(d.store, d.watches, item.id, d.clock())
    finished = d.execute(run)
    finish_inbox_run(d.store, d.watches, item.id, finished, d.clock())

    done = d.watches.get_item(item.id)
    assert done is not None and done.kind == InboxKind.moved
    assert done.run is not None and done.run.started_by == "owner"
    assert done.moved is not None and done.moved.verdicts[0].after == Verdict.supported


def test_the_daily_cap_turns_further_automatic_runs_into_waiting_ones() -> None:
    d = desk(cap=1)
    watch(d, WatchPolicy.auto)
    gain(d, DEPARTURE_8K, departure_html())
    second = current_report_ref(4, "2026-03-11", "2.02")
    gain(d, second, current_report_html(("2.02", "Results.", ["The company reported."])))

    d.watcher.cycle()

    kinds = {i.filing.accession: i for i in d.watches.list_items(limit=10, offset=0).items}
    ran, waited = kinds[DEPARTURE_8K.accession], kinds[second.accession]
    assert ran.kind in (InboxKind.moved, InboxKind.nothing_moved)
    assert waited.kind == InboxKind.waiting
    assert waited.run is not None
    assert waited.run.waiting_reason == wording.WAITING_CAP.format(cap=1)


def test_a_run_that_fails_is_retried_with_backoff_and_then_reported_failed() -> None:
    d = desk()
    watch(d, WatchPolicy.auto)
    gain(d, DEPARTURE_8K, departure_html())
    real = d.source.periodic_filings
    d.source.periodic_filings = lambda company, limit: (_ for _ in ()).throw(  # type: ignore[method-assign]
        SourceError("EDGAR answered HTTP 503 for the index")
    )

    first = d.watcher.cycle()
    assert first.jobs_retried == 1
    [job] = d.watches.jobs()
    assert job.state == JobState.queued and "HTTP 503" in job.error
    [between] = d.watches.list_items(limit=10, offset=0).items
    assert between.kind == InboxKind.failed and "HTTP 503" in between.error
    assert between.run is not None and (between.run.state, between.run.status) == (
        "failed",
        "failed",
    )
    for wait in wording.BACKOFF_SECONDS:
        d.clock.advance(wait)
        d.watcher.cycle()

    [job] = d.watches.jobs()
    assert job.state == JobState.failed and job.attempts == wording.MAX_ATTEMPTS
    [item] = d.watches.list_items(limit=10, offset=0).items
    assert item.kind == InboxKind.failed
    assert "HTTP 503" in item.error and f"{wording.MAX_ATTEMPTS} attempts" in item.error
    assert item.run is not None and item.run.state == "failed"
    d.source.periodic_filings = real  # type: ignore[method-assign]


def test_an_index_that_cannot_be_read_is_recorded_on_the_check_and_queues_nothing() -> None:
    d = desk()
    watch(d, WatchPolicy.auto)
    d.source.index_error = SourceError("EDGAR could not be reached (ConnectError)")

    report = d.watcher.cycle()

    assert report.index_errors == 1 and report.jobs_queued == 0
    [check] = d.status.checks().values()
    assert check.last_error == "EDGAR could not be reached (ConnectError)"
    assert check.last_check_at == T0
    assert check.next_check_at == T0 + timedelta(seconds=900)
    beat = d.status.newest_beat()
    assert beat is not None and beat.last_cycle["index_errors"] == 1


def test_two_theses_on_one_company_cost_one_index_request_per_cycle() -> None:
    d = desk()
    other = theses.create_thesis(
        d.store,
        ThesisCreate(
            name="Second thesis",
            request=ThesisRequest(
                ticker="NVDA", decision="Another decision on NVIDIA", claims=[GROWTH]
            ),
        ),
    )
    watch(d, WatchPolicy.ask)
    start_watching(d.store, d.watches, d.source, other.id, WatchPolicy.ask, d.clock())
    d.source.index_calls = 0
    gain(d, DEPARTURE_8K, departure_html())

    report = d.watcher.cycle()

    assert d.source.index_calls == 1
    assert report.jobs_queued == 2  # one per thesis
    by_thesis = {i.thesis_id: i.kind for i in d.watches.list_items(limit=10, offset=0).items}
    assert by_thesis == {d.thesis_id: InboxKind.waiting, other.id: InboxKind.not_relevant}


def test_a_new_quarterly_report_bears_on_every_claim_and_names_the_paragraphs() -> None:
    source = FormFakeFilings(refs=[QUARTER, ANNUAL], documents=dict(filings().documents))
    d = desk(source)
    watch(d, WatchPolicy.ask)
    newer = dataclasses.replace(synthetic_ref(3, "10-Q"), filed_date="2026-05-15")
    gain(
        d,
        newer,
        filing_html(
            "Revenue grew in the quarter as demand for systems rose sharply in every region.",
            "Revenue grew in the quarter as demand for systems rose.",
        ),
    )

    d.watcher.cycle()

    [item] = d.watches.list_items(limit=10, offset=0).items
    assert item.kind == InboxKind.waiting
    assert item.triage.rules == [TriageRule.periodic_report]
    leaving, growth = item.triage.claims
    assert leaving.bears and growth.bears
    assert growth.paragraphs and "every region" in growth.paragraphs[0].text
    assert wording.REASON_NO_PARAGRAPHS in leaving.reasons


def test_a_thesis_taken_off_watch_queues_nothing_and_its_queued_jobs_are_skipped() -> None:
    d = desk()
    watch(d, WatchPolicy.auto)
    gain(d, DEPARTURE_8K, departure_html())
    d.watcher.poll()
    assert stop_watching(d.watches, d.thesis_id)

    d.watcher.work()

    [job] = d.watches.jobs()
    assert job.state == JobState.done and job.outcome == wording.NO_LONGER_WATCHED
    assert d.watches.list_items(limit=10, offset=0).total == 0
    gain(d, current_report_ref(5, "2026-03-12", "5.02"), departure_html())
    assert d.watcher.cycle().jobs_queued == 0


def test_watching_again_only_changes_the_policy_and_does_not_rebaseline() -> None:
    d = desk()
    watch(d, WatchPolicy.ask)
    gain(d, DEPARTURE_8K, departure_html())  # listed, but no cycle has seen it yet

    watch(d, WatchPolicy.auto)

    assert d.watches.get_watch(d.thesis_id).policy == WatchPolicy.auto  # type: ignore[union-attr]
    assert d.watcher.cycle().jobs_queued == 1
