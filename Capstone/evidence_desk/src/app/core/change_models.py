"""Record types for what changed between two filings of one company and form.

Pure data: nothing here touches the network, the file system or a clock.
:func:`app.core.filing_diff.diff_documents` builds the per-Item records and
:func:`app.services.filing_changes.filing_changes` the whole comparison; the
command line (``app.changes``) and, later, an API route render them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.models import Company

SegmentKind = Literal["same", "added", "removed"]
Presence = Literal["both", "earlier", "later"]


class Paragraph(BaseModel):
    """One paragraph (one line of a section) of a filing.

    ``text`` is an exact span of the filing's stored text: ``stored[start:start + len(text)]``.
    ``locator`` is the heading of the section it sits under. ``link`` opens the filing,
    and ``link_kind`` says where (:func:`app.core.links.link_kind`): at the "passage",
    at its "first-line", or only the "document" when the text cannot be located.
    """

    text: str
    locator: str
    start: int = Field(ge=0)
    link: str
    link_kind: str = ""


class WordChange(BaseModel):
    """A run of words of a reworded pair: in both, only in the later, or only in the earlier."""

    text: str
    kind: SegmentKind


class RewordedParagraph(BaseModel):
    """An earlier paragraph and the later paragraph that rewords it, or differs in numbers only.

    ``similarity`` is the Jaccard similarity of their word-token sets (0 to 1); common
    words and figures are left out of it, so 1 does not mean the two are identical.
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
    numbers_only: bool = False


class ChangeCounts(BaseModel):
    """How the lines of one Item, or of a whole filing pair, compare.

    The first five count paragraphs: lines of at least the minimum length that are not
    table rows. The four ``minor_`` counts are the same classes for short lines and table
    rows, which are never listed and never paired as reworded. A line matched with one
    in the other filing (unchanged, numbers only, reworded) is counted once, by its line
    in the later filing. So for each filing every line is in exactly one count: the later
    filing's lines are the matched ones plus ``added`` and ``minor_added``, the earlier
    filing's the matched ones plus ``removed`` and ``minor_removed``.
    """

    unchanged: int = 0
    numbers_only: int = 0
    reworded: int = 0
    added: int = 0
    removed: int = 0
    minor_unchanged: int = 0
    minor_numbers_only: int = 0
    minor_added: int = 0
    minor_removed: int = 0


class ItemChanges(ChangeCounts):
    """What changed in one Item (or the cover page, or unnumbered text).

    ``item`` is the Item's heading without any sub-heading, as the later filing
    writes it (the earlier filing's when the Item is only there). The lists hold
    at most :data:`app.core.filing_diff.MAX_LISTED` paragraphs each, in document order.
    ``numbers_only_paragraphs`` are pairs whose words are the same and whose figures
    differ, with the figures that changed as their ``segments``. ``subheadings_added``
    and ``subheadings_removed`` are the sub-headings found under the Item in only one
    filing, compared without case, punctuation and figures; the parser keeps a
    sub-heading apart from the text, so no paragraph count can show one changing.
    """

    item: str
    present_in: Presence
    added_paragraphs: list[Paragraph] = Field(default_factory=list)
    removed_paragraphs: list[Paragraph] = Field(default_factory=list)
    reworded_paragraphs: list[RewordedParagraph] = Field(default_factory=list)
    numbers_only_paragraphs: list[RewordedParagraph] = Field(default_factory=list)
    subheadings_added: list[str] = Field(default_factory=list)
    subheadings_removed: list[str] = Field(default_factory=list)
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
