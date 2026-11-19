"""What moved between an earlier and a later run of the same thesis.

Pure: compares two run records (and, when given, their reviews) and says, per
claim, how its verdict changed and which verified excerpts are new or gone,
and which filings are new or no longer read. Claims are matched by their text
with whitespace collapsed and case folded, so a claim retyped with different
spacing or capitals is still the same claim.

What is compared:

- **Verdicts**, the engine's, claim by claim. Each claim's ``change`` is one of
  :data:`CHANGES`: "moved" (both runs judged it, differently), "unchanged",
  "new" (the earlier run had no such claim), "dropped" (the later run has
  none), or "not_assessed" (both runs have the claim but one, or both, never
  assessed it, for example because the run hit its time limit). Only "moved"
  sets ``moved`` and counts toward ``verdicts_moved``.
- **Engines.** Both runs' engines are recorded. When they differ, the note
  ends by saying so: a keyless re-run after a model run can move a verdict
  with no change in the filings.
- **Excerpts**: verified excerpts, by filing (accession, or URL) and text.
- **Filings** read, by accession.
- **Reviewed verdicts**, reported beside the engine's when the reviews are given.

What is not compared: findings that cite only reported figures have no
excerpt, so they never show in ``excerpts_added`` or ``excerpts_dropped``;
such a finding appears or disappears only through the verdict it moves.
Statements, rationales, figures and the meaning check are not compared.
"""

from __future__ import annotations

from typing import Final

from ed_v12.core.models import (
    ClaimChange,
    ExtractionStatus,
    Review,
    Run,
    RunComparison,
    Verdict,
)

# An excerpt's identity across runs: (accession, or URL when there is none; excerpt text).
ExcerptKey = tuple[str, str]

MOVED: Final = "moved"
UNCHANGED: Final = "unchanged"
NEW: Final = "new"
DROPPED: Final = "dropped"
NOT_ASSESSED: Final = "not_assessed"
CHANGES: tuple[str, ...] = (MOVED, UNCHANGED, NEW, DROPPED, NOT_ASSESSED)


def claim_key(text: str) -> str:
    """The text a claim is matched by: whitespace collapsed, case folded."""
    return " ".join(text.split()).casefold()


def claim_change(
    in_earlier: bool, in_later: bool, before: Verdict | None, after: Verdict | None
) -> str:
    """How one claim changed: one of :data:`CHANGES`.

    ``in_earlier`` and ``in_later`` say whether each run has the claim at all;
    a verdict of None in a run that has the claim means it was not assessed.
    """
    if not in_earlier:
        return NEW
    if not in_later:
        return DROPPED
    if before is None or after is None:
        return NOT_ASSESSED
    return MOVED if before != after else UNCHANGED


def _excerpts_by_claim(run: Run) -> dict[str, set[ExcerptKey]]:
    """Each claim's verified excerpts, keyed by claim id."""
    sources = {source.id: source for source in run.sources}
    claim_of = {finding.id: finding.claim_id for finding in run.findings if finding.verified}
    out: dict[str, set[ExcerptKey]] = {claim.id: set() for claim in run.claims}
    for item in run.evidence:
        claim_id = claim_of.get(item.finding_id)
        if claim_id is None:
            continue
        source = sources.get(item.source_id)
        where = (source.accession or source.url) if source else item.source_id
        out.setdefault(claim_id, set()).add((where, " ".join(item.excerpt.split())))
    return out


def _filings(run: Run) -> dict[str, str]:
    """The filings the run read, title by accession, in the run's order."""
    return {
        source.accession: source.title
        for source in run.sources
        if source.accession and source.extraction_status == ExtractionStatus.extracted
    }


def _reviewed(review: Review | None) -> dict[str, Verdict | None]:
    return {claim.claim_id: claim.reviewed_verdict for claim in review.claims} if review else {}


def _note(moved: int, total: int, added: list[str], engines: tuple[str, str] | None) -> str:
    """Plain sentences: how many verdicts moved, which filings are new, and any engine change."""
    plural = "" if total == 1 else "s"
    verdicts = f"{moved} of {total} verdict{plural} moved" if moved else "No verdict moved"
    if not added:
        note = f"{verdicts} and no filing is new."
    else:
        filings = "1 filing is new" if len(added) == 1 else f"{len(added)} filings are new"
        note = f"{verdicts}; {filings}: {'; '.join(added)}."
    if engines is not None:
        note += (
            f" The two runs used different engines ({engines[0]}, then {engines[1]}), so a "
            "verdict that moved may reflect the engine and not the filings."
        )
    return note


def compare_runs(
    earlier: Run,
    later: Run,
    earlier_review: Review | None = None,
    later_review: Review | None = None,
) -> RunComparison:
    """Compare ``earlier`` with ``later``, claim by claim.

    Claims appear in the later run's order, then any the earlier run alone had;
    a claim in one run only has None on the other side. ``change`` and
    ``moved`` compare the engine's verdicts (see the module notes); the
    reviewed verdicts are reported beside them when the reviews are given.
    """
    before_claims = {claim_key(claim.text): claim for claim in earlier.claims}
    after_claims = {claim_key(claim.text): claim for claim in later.claims}
    keys = list(after_claims) + [key for key in before_claims if key not in after_claims]
    before_excerpts, after_excerpts = _excerpts_by_claim(earlier), _excerpts_by_claim(later)
    before_reviewed, after_reviewed = _reviewed(earlier_review), _reviewed(later_review)

    changes: list[ClaimChange] = []
    for key in keys:
        old, new = before_claims.get(key), after_claims.get(key)
        old_excerpts = before_excerpts.get(old.id, set()) if old else set()
        new_excerpts = after_excerpts.get(new.id, set()) if new else set()
        before = old.verdict if old else None
        after = new.verdict if new else None
        text = new.text if new else old.text if old else key
        change = claim_change(old is not None, new is not None, before, after)
        changes.append(
            ClaimChange(
                claim=text,
                before=before,
                after=after,
                moved=change == MOVED,
                change=change,
                reviewed_before=before_reviewed.get(old.id) if old else None,
                reviewed_after=after_reviewed.get(new.id) if new else None,
                excerpts_added=len(new_excerpts - old_excerpts),
                excerpts_dropped=len(old_excerpts - new_excerpts),
            )
        )

    old_filings, new_filings = _filings(earlier), _filings(later)
    added = [title for accession, title in new_filings.items() if accession not in old_filings]
    dropped = [title for accession, title in old_filings.items() if accession not in new_filings]
    moved = sum(1 for change in changes if change.moved)
    engines_differ = earlier.engine != later.engine
    return RunComparison(
        thesis_id=later.thesis_id if later.thesis_id == earlier.thesis_id else None,
        earlier_run_id=earlier.id,
        later_run_id=later.id,
        earlier_finished_at=earlier.finished_at,
        later_finished_at=later.finished_at,
        sources_added=added,
        sources_dropped=dropped,
        claims=changes,
        verdicts_moved=moved,
        claims_total=len(changes),
        note=_note(
            moved, len(changes), added, (earlier.engine, later.engine) if engines_differ else None
        ),
        earlier_engine=earlier.engine,
        later_engine=later.engine,
        engines_differ=engines_differ,
    )
