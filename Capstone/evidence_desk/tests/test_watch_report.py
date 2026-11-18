"""What a watch-triggered run moved, against the previous finished run of the thesis."""

from __future__ import annotations

from datetime import UTC, datetime

from app.core import watch_policy as wording
from app.core.event_models import Event
from app.core.models import Claim, Run, RunStatus, ThesisRequest, Verdict
from app.core.watch_report import what_moved

REQUEST = ThesisRequest(
    ticker="NVDA",
    decision="Whether to keep the position in NVIDIA",
    claims=["Buy because Jane Smith is gone.", "Data center revenue is still growing."],
)


def run(
    ident: str,
    verdicts: tuple[Verdict | None, Verdict | None],
    *,
    caution: str = "",
    note: str = "",
    events: tuple[str, ...] = (),
) -> Run:
    return Run(
        id=ident,
        inputs=REQUEST,
        status=RunStatus.complete,
        started_at=datetime(2026, 11, 18, tzinfo=UTC),
        claims=[
            Claim(id="c1", text=REQUEST.claims[0], verdict=verdicts[0], caution=caution,
                  event_note=note),
            Claim(id="c2", text=REQUEST.claims[1], verdict=verdicts[1]),
        ],
        timeline=[
            Event(
                id=f"ev-{accession}",
                form="8-K",
                accession=accession,
                filed_date="2026-11-12",
                url=f"https://www.sec.gov/{accession}.htm",
                items=[],
            )
            for accession in events
        ],
    )


def test_a_moved_verdict_a_new_caution_and_a_new_8k_are_each_named() -> None:
    earlier = run("run-1", (Verdict.not_addressed, Verdict.unjudged), events=("a-1",))
    later = run(
        "run-2",
        (Verdict.supported, Verdict.unjudged),
        caution="The evidence for this verdict was filed before the 8-K of 12 Nov 2026.",
        events=("a-1", "a-2"),
    )

    moved = what_moved(earlier, later)

    assert moved.moved
    assert [(v.claim, v.before, v.after) for v in moved.verdicts] == [
        (REQUEST.claims[0], Verdict.not_addressed, Verdict.supported)
    ]
    assert [c.claim for c in moved.new_cautions] == [REQUEST.claims[0]]
    assert [e.accession for e in moved.new_events] == ["a-2"]
    assert moved.line == "1 of 2 verdicts moved; 1 new caution; 1 new 8-K on the timeline."
    assert moved.earlier_run_id == "run-1" and moved.later_run_id == "run-2"


def test_nothing_moved_says_so() -> None:
    earlier = run("run-1", (Verdict.unjudged, Verdict.unjudged), events=("a-1",))
    later = run("run-2", (Verdict.unjudged, Verdict.unjudged), events=("a-1",))

    moved = what_moved(earlier, later)

    assert not moved.moved
    assert moved.line == wording.NOTHING_MOVED
    assert len(moved.claims) == 2


def test_a_note_counts_as_new_only_when_the_claim_had_none() -> None:
    earlier = run("run-1", (Verdict.unjudged, None), note="No 8-K filed ... dated 12 Nov 2026.")
    later = run("run-2", (Verdict.unjudged, None), note="No 8-K filed ... dated 17 Nov 2026.")
    fresh = run("run-3", (Verdict.unjudged, None), note="No 8-K filed since the annual report.")

    assert not what_moved(earlier, later).moved
    assert [n.claim for n in what_moved(run("run-0", (Verdict.unjudged, None)), fresh).new_notes] == [
        REQUEST.claims[0]
    ]


def test_the_first_run_has_nothing_to_compare_with() -> None:
    moved = what_moved(None, run("run-1", (Verdict.supported, None)))

    assert not moved.moved
    assert moved.earlier_run_id is None
    assert moved.line == wording.FIRST_RUN
