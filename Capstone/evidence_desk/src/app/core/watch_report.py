"""What a watch-triggered run moved, against the previous finished run of the same thesis.

Pure: two run records in, a :class:`~app.core.watch_models.WhatMoved` out. The verdicts
are compared by :func:`app.core.compare.compare_runs` (claims matched by their text);
on top of it this names what version 12 added to a run:

- a **caution** is new when the claim has one now that differs from the one it had (a
  caution names the 8-K that predates the evidence, so a new 8-K gives a new caution);
- an **8-K note** is new only when the claim had none: a note names the newest filing
  read, so its date changes with every filing and would otherwise always look new;
- an **8-K** is new when the later run's timeline lists an accession the earlier did not;
- a **computed test** (version 14) changed its outcome when the claim compiled to the same
  canonical test in both runs and the outcome differs: the later run read facts a new
  filing brought. A test read differently, or only in one run, is not a change of outcome.

Something moved when any verdict moved, or any of these is new. Each claim that moved in
any of these ways is counted once in ``claims_moved``.
"""

from __future__ import annotations

from app.core import policy
from app.core import watch_policy as wording
from app.core.compare import claim_key, compare_runs
from app.core.events import day_label
from app.core.models import Run
from app.core.watch_models import ClaimNote, ComputedMove, NewEvent, VerdictMove, WhatMoved


def _count(number: int, one: str, many: str) -> str:
    return f"{number} {one if number == 1 else many}"


def what_moved(earlier: Run | None, later: Run) -> WhatMoved:
    """What moved from ``earlier`` (None for a thesis's first finished run) to ``later``."""
    if earlier is None:
        return WhatMoved(
            later_run_id=later.id, line=wording.FIRST_RUN, claims_total=len(later.claims)
        )
    comparison = compare_runs(earlier, later)
    before = {claim_key(claim.text): claim for claim in earlier.claims}
    cautions: list[ClaimNote] = []
    notes: list[ClaimNote] = []
    computed: list[ComputedMove] = []
    for claim in later.claims:
        old = before.get(claim_key(claim.text))
        was, now = (old.computed if old else None), claim.computed
        if was and now and was.canonical == now.canonical and was.outcome != now.outcome:
            computed.append(
                ComputedMove(
                    claim=claim.text,
                    canonical=now.canonical,
                    before=was.outcome,
                    after=now.outcome,
                    before_label=policy.COMPUTED_LABELS[was.outcome],
                    after_label=policy.COMPUTED_LABELS[now.outcome],
                )
            )
        if claim.caution and (old is None or old.caution != claim.caution):
            cautions.append(ClaimNote(claim=claim.text, text=claim.caution))
        if claim.event_note and (old is None or not old.event_note):
            notes.append(ClaimNote(claim=claim.text, text=claim.event_note))
    known = {event.accession for event in earlier.timeline}
    events = [
        NewEvent(
            accession=event.accession,
            form=event.form,
            filed_date=event.filed_date,
            items=[item.number for item in event.items],
            url=event.url,
            label=f"{event.form} of {day_label(event.filed_date)}",
        )
        for event in later.timeline
        if event.accession not in known
    ]
    verdicts = [
        VerdictMove(claim=change.claim, before=change.before, after=change.after)
        for change in comparison.claims
        if change.moved
    ]
    parts: list[str] = []
    if verdicts:
        parts.append(
            f"{len(verdicts)} of {_count(comparison.claims_total, 'verdict', 'verdicts')} moved"
        )
    if cautions:
        parts.append(_count(len(cautions), "new caution", "new cautions"))
    if notes:
        parts.append(_count(len(notes), "new 8-K note", "new 8-K notes"))
    if events:
        parts.append(_count(len(events), "new 8-K on the timeline", "new 8-Ks on the timeline"))
    if computed:
        parts.append(
            _count(
                len(computed),
                "computed test changed its outcome",
                "computed tests changed their outcome",
            )
        )
    moved_claims = {
        claim_key(text)
        for text in (
            *(move.claim for move in verdicts),
            *(note.claim for note in cautions),
            *(note.claim for note in notes),
            *(move.claim for move in computed),
        )
    }
    total = len(later.claims)
    return WhatMoved(
        earlier_run_id=earlier.id,
        later_run_id=later.id,
        moved=bool(parts),
        verdicts=verdicts,
        new_cautions=cautions,
        new_notes=notes,
        new_events=events,
        sources_added=comparison.sources_added,
        computed=computed,
        line=_sentence(parts) if parts else wording.NOTHING_MOVED,
        claims_moved=len(moved_claims),
        claims_total=total,
        claims_line=wording.CLAIMS_MOVED.format(
            moved=len(moved_claims), total=total, noun="claim" if total == 1 else "claims"
        ),
        claims=comparison.claims,
        comparison_note=comparison.note,
    )


def _sentence(parts: list[str]) -> str:
    """The parts joined with semicolons, as one sentence with a capital letter."""
    text = "; ".join(parts) + "."
    return text[0].upper() + text[1:]
