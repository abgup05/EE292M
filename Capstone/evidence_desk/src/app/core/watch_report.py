"""What a watch-triggered run moved, against the previous finished run of the same thesis.

Pure: two run records in, a :class:`~app.core.watch_models.WhatMoved` out. The verdicts
are compared by :func:`app.core.compare.compare_runs` (claims matched by their text);
on top of it this names what version 12 added to a run:

- a **caution** is new when the claim has one now that differs from the one it had (a
  caution names the 8-K that predates the evidence, so a new 8-K gives a new caution);
- an **8-K note** is new only when the claim had none: a note names the newest filing
  read, so its date changes with every filing and would otherwise always look new;
- an **8-K** is new when the later run's timeline lists an accession the earlier did not.

Something moved when any verdict moved, or any of these is new.
"""

from __future__ import annotations

from app.core import watch_policy as wording
from app.core.compare import claim_key, compare_runs
from app.core.events import day_label
from app.core.models import Run
from app.core.watch_models import ClaimNote, NewEvent, VerdictMove, WhatMoved


def _count(number: int, one: str, many: str) -> str:
    return f"{number} {one if number == 1 else many}"


def what_moved(earlier: Run | None, later: Run) -> WhatMoved:
    """What moved from ``earlier`` (None for a thesis's first finished run) to ``later``."""
    if earlier is None:
        return WhatMoved(later_run_id=later.id, line=wording.FIRST_RUN)
    comparison = compare_runs(earlier, later)
    before = {claim_key(claim.text): claim for claim in earlier.claims}
    cautions: list[ClaimNote] = []
    notes: list[ClaimNote] = []
    for claim in later.claims:
        old = before.get(claim_key(claim.text))
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
    return WhatMoved(
        earlier_run_id=earlier.id,
        later_run_id=later.id,
        moved=bool(parts),
        verdicts=verdicts,
        new_cautions=cautions,
        new_notes=notes,
        new_events=events,
        sources_added=comparison.sources_added,
        line="; ".join(parts) + "." if parts else wording.NOTHING_MOVED,
        claims=comparison.claims,
        comparison_note=comparison.note,
    )
