"""Record types for which changed filing paragraphs bear on which claim of a run.

Pure data: nothing here touches the network, the file system or a clock.
:func:`app.core.claim_changes.relevant_changes` builds the per-claim records and
:func:`app.services.claim_changes.run_changes` the whole record for one run.
The match is deterministic keyword retrieval (BM25 over shared words); no model
reads these paragraphs, and "bears on" means only "shares words with".
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.core.change_models import ChangeCounts, FilingSide, Paragraph, RewordedParagraph

ChangeKind = Literal["added", "removed", "reworded", "numbers_only"]
CompareForm = Literal["10-K", "10-Q"]

# Kinds that list one paragraph, and kinds that list an earlier and a later paragraph.
SINGLE_KINDS: tuple[ChangeKind, ...] = ("added", "removed")
PAIR_KINDS: tuple[ChangeKind, ...] = ("reworded", "numbers_only")


class RelevantChange(BaseModel):
    """One changed paragraph that shares words with a claim.

    ``paragraph`` is set for an added paragraph (of the later filing) or a removed one
    (of the earlier filing); ``pair`` for a reworded or numbers-only pair, whose later
    paragraph was the text searched. ``item`` is the name of the Item it sits in.
    ``score`` is its BM25 score for the claim, rounded to four places, and
    ``matched_terms`` the distinct content terms of the claim (its text and queries,
    as :func:`app.core.text.tokenize` stems them, figures left out) found in the
    searched text, sorted. ``also_under`` names, in filing order, the other Items where
    the same change appears again in the same comparison (same kind, same text once
    whitespace and case are normalised; for a pair, the same later and earlier text);
    the entry stands for all of those copies and its own ``item`` is not repeated.
    """

    kind: ChangeKind
    form: CompareForm
    item: str
    paragraph: Paragraph | None = None
    pair: RewordedParagraph | None = None
    score: float = Field(ge=0.0)
    matched_terms: list[str]
    also_under: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_shape_per_kind(self) -> RelevantChange:
        if self.kind in SINGLE_KINDS and (self.paragraph is None or self.pair is not None):
            raise ValueError(f"an {self.kind} change carries a paragraph and no pair")
        if self.kind in PAIR_KINDS and (self.pair is None or self.paragraph is not None):
            raise ValueError(f"a {self.kind} change carries a pair and no paragraph")
        return self


class ClaimChanges(BaseModel):
    """The changes listed for one claim, best first, one entry per distinct change.

    All three counts are taken before the list is cut to its cap. ``considered`` counts
    the changed paragraphs searched (every added and removed paragraph and every
    reworded and numbers-only pair of every comparison, each copy of a repeated one
    counted); ``matched`` the paragraphs among them that share enough terms with the
    claim, copies counted; ``distinct_matched`` the distinct changes they make, a
    change repeated under several Items counted once. So
    ``len(changes) <= distinct_matched <= matched <= considered``.
    """

    claim_id: str
    changes: list[RelevantChange] = Field(default_factory=list)
    considered: int = Field(default=0, ge=0)
    matched: int = Field(default=0, ge=0)
    distinct_matched: int = Field(default=0, ge=0)


class ComparedFilings(BaseModel):
    """One comparison that was searched: a filing the run read and the one filed before it."""

    form: CompareForm
    earlier: FilingSide
    later: FilingSide
    totals: ChangeCounts


class RunChanges(BaseModel):
    """For each claim of a run, the changed paragraphs of the filings it read that share its words.

    ``compared`` lists the comparisons made, one per form the run read. ``claims`` holds
    one record per claim of the run, in the run's order, present even when empty.
    ``notes`` say which comparison is missing and why, or why nothing was compared.
    """

    run_id: str
    compared: list[ComparedFilings] = Field(default_factory=list)
    claims: list[ClaimChanges] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
