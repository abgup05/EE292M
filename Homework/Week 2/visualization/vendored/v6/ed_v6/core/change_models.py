"""Record types for what changed between two filings of one company and form.

Pure data: nothing here touches the network, the file system or a clock.
:func:`app.core.filing_diff.diff_documents` builds the per-Item records and
:func:`app.services.filing_changes.filing_changes` the whole comparison; the
command line (``app.changes``) and, later, an API route render them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ed_v6.core.models import Company

SegmentKind = Literal["same", "added", "removed"]
Presence = Literal["both", "earlier", "later"]


class Paragraph(BaseModel):
    """One paragraph (one line of a section) of a filing.

    ``text`` is an exact span of the filing's stored text: ``stored[start:start + len(text)]``.
    ``locator`` is the heading of the section it sits under; ``link`` opens the
    filing at it (a text-fragment link).
    """

    text: str
    locator: str
    start: int = Field(ge=0)
    link: str


class WordChange(BaseModel):
    """A run of words of a reworded pair: in both, only in the later, or only in the earlier."""

    text: str
    kind: SegmentKind


class RewordedParagraph(BaseModel):
    """An earlier paragraph and the later paragraph that rewords it.

    ``similarity`` is the Jaccard similarity of their word-token sets (0 to 1).
    ``segments`` walk the later paragraph against the earlier one: joining the
    ``same`` and ``removed`` texts gives the earlier words, ``same`` and ``added``
    the later ones.
    """

    before: Paragraph
    after: Paragraph
    similarity: float = Field(ge=0.0, le=1.0)
    segments: list[WordChange]


class TruncatedLists(BaseModel):
    """Which of an Item's lists were cut to their cap (the counts stay true)."""

    added: bool = False
    removed: bool = False
    reworded: bool = False


class ChangeCounts(BaseModel):
    """How the paragraphs of one Item, or of a whole filing pair, compare.

    ``unchanged`` and ``numbers_only`` count every line. ``reworded``, ``added``
    and ``removed`` count paragraphs (lines of at least the minimum length that
    are not table rows); short lines and table rows that are in only one filing
    are counted in ``minor_added`` and ``minor_removed`` and never listed.
    """

    unchanged: int = 0
    numbers_only: int = 0
    reworded: int = 0
    added: int = 0
    removed: int = 0
    minor_added: int = 0
    minor_removed: int = 0


class ItemChanges(ChangeCounts):
    """What changed in one Item (or the cover page, or unnumbered text).

    ``item`` is the Item's heading without any sub-heading, as the later filing
    writes it (the earlier filing's when the Item is only there). The lists hold
    at most :data:`app.core.filing_diff.MAX_LISTED` paragraphs each, in document order.
    """

    item: str
    present_in: Presence
    added_paragraphs: list[Paragraph] = Field(default_factory=list)
    removed_paragraphs: list[Paragraph] = Field(default_factory=list)
    reworded_paragraphs: list[RewordedParagraph] = Field(default_factory=list)
    truncated: TruncatedLists = Field(default_factory=TruncatedLists)


class FilingSide(BaseModel):
    """One of the two filings compared, as the reader is shown it."""

    form: str
    period_end: str
    filed_date: str
    accession: str
    url: str
    title: str
    item_coverage: float = Field(ge=0.0, le=1.0)


class FilingChanges(BaseModel):
    """What changed from the ``earlier`` filing to the ``later`` one, Item by Item.

    ``items`` are in filing order (the later filing's, with Items found only in
    the earlier one placed after the Item that preceded them there).
    """

    company: Company
    earlier: FilingSide
    later: FilingSide
    items: list[ItemChanges]
    totals: ChangeCounts
    notes: list[str] = Field(default_factory=list)
