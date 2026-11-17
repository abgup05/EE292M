"""Saved theses: create, run again, compare the two newest finished runs (services/theses.py)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.models import (
    Claim,
    Confidence,
    Decision,
    DecisionValue,
    Finding,
    RunStatus,
    Stance,
    ThesisCreate,
    ThesisRequest,
    Verdict,
)
from app.services import theses
from app.store import Store

CLAIM = "Data-center revenue is still growing"
REQUEST = ThesisRequest(ticker="NVDA", decision="Keep the position into earnings", claims=[CLAIM])
BODY = ThesisCreate(name="  NVIDIA   data center ", request=REQUEST)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[Store]:
    record = Store(tmp_path / "record.sqlite")
    yield record
    record.close()


def test_create_thesis_saves_it_with_an_id_and_utc_time(store: Store) -> None:
    before = datetime.now(UTC)
    thesis = theses.create_thesis(store, BODY)
    assert re.fullmatch(r"th-[0-9a-f]{12}", thesis.id)
    assert thesis.name == "NVIDIA data center"
    assert thesis.request == REQUEST and thesis.run_ids == []
    assert thesis.created_at.tzinfo is not None and thesis.created_at >= before
    assert store.get_thesis(thesis.id) == thesis


def test_each_run_of_a_thesis_is_recorded_newest_first(store: Store) -> None:
    thesis = theses.create_thesis(store, BODY)
    first = theses.start_thesis_run(store, thesis.id)
    second = theses.start_thesis_run(store, thesis.id)
    assert first.thesis_id == second.thesis_id == thesis.id
    assert first.status == RunStatus.running and first.inputs == REQUEST
    saved = store.get_thesis(thesis.id)
    assert saved is not None and saved.run_ids == [second.id, first.id]
    assert store.get_run(first.id) == first


def test_running_an_unknown_thesis_is_refused(store: Store) -> None:
    with pytest.raises(theses.UnknownThesis):
        theses.start_thesis_run(store, "th-000000000000")
    with pytest.raises(theses.UnknownThesis):
        theses.latest_comparison(store, "th-000000000000")


def finish(store: Store, thesis_id: str, verdict: Verdict, status: RunStatus, hours: int) -> str:
    """Start a run of the thesis and record it as finished with one claim's verdict."""
    run = theses.start_thesis_run(store, thesis_id)
    run.started_at = datetime(2026, 11, 1, tzinfo=UTC) + timedelta(hours=hours)
    run.status = status
    run.finished_at = run.started_at + timedelta(minutes=2)
    run.claims = [Claim(id="c1", text=CLAIM, verdict=verdict)]
    store.save_run(run)
    return run.id


def test_changes_compare_the_two_newest_finished_runs(store: Store) -> None:
    thesis = theses.create_thesis(store, BODY)
    oldest = finish(store, thesis.id, Verdict.unjudged, RunStatus.partial, 0)
    earlier = finish(store, thesis.id, Verdict.supported, RunStatus.complete, 1)
    later = finish(store, thesis.id, Verdict.challenged, RunStatus.partial, 2)
    finish(store, thesis.id, Verdict.mixed, RunStatus.failed, 3)  # failed: not compared
    finish(store, thesis.id, Verdict.mixed, RunStatus.running, 4)  # still running
    comparison = theses.latest_comparison(store, thesis.id)
    assert (comparison.earlier_run_id, comparison.later_run_id) == (earlier, later)
    assert oldest not in (comparison.earlier_run_id, comparison.later_run_id)
    assert comparison.thesis_id == thesis.id
    [change] = comparison.claims
    assert (change.before, change.after, change.moved) == (
        Verdict.supported,
        Verdict.challenged,
        True,
    )


def test_changes_carry_each_runs_reviewed_verdicts(store: Store) -> None:
    thesis = theses.create_thesis(store, BODY)
    finish(store, thesis.id, Verdict.supported, RunStatus.complete, 0)
    later_id = finish(store, thesis.id, Verdict.supported, RunStatus.complete, 1)
    later = store.get_run(later_id)
    assert later is not None
    later.findings = [
        Finding(
            id="f1",
            claim_id="c1",
            statement="Revenue grew.",
            stance=Stance.supports,
            evidence_ids=["e1"],
            confidence=Confidence.high,
            rationale="Stated.",
            verified=True,
        )
    ]
    store.save_run(later)
    store.save_decision(
        Decision(
            run_id=later_id,
            finding_id="f1",
            value=DecisionValue.rejected,
            decided_at=datetime.now(UTC),
        )
    )
    [change] = theses.latest_comparison(store, thesis.id).claims
    assert change.reviewed_before is None
    assert change.reviewed_after == Verdict.not_addressed


@pytest.mark.parametrize("finished", [0, 1])
def test_changes_need_two_finished_runs(store: Store, finished: int) -> None:
    thesis = theses.create_thesis(store, BODY)
    for hour in range(finished):
        finish(store, thesis.id, Verdict.supported, RunStatus.complete, hour)
    theses.start_thesis_run(store, thesis.id)  # running: does not count
    with pytest.raises(theses.NotEnoughRuns) as raised:
        theses.latest_comparison(store, thesis.id)
    assert str(raised.value) == "This thesis has fewer than two finished runs to compare."
