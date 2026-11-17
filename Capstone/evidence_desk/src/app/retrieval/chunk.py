"""Split a stored document into retrievable passages that are exact slices of its text.

Each section's lines are packed, in order, into passages of about
``limits.PASSAGE_TARGET_CHARS`` and never more than ``limits.PASSAGE_MAX_CHARS``.
A line longer than the maximum is cut at sentence boundaries, and a sentence
still too long is cut at the last whitespace before the maximum. Every passage
records its offset, so ``document.text[p.start : p.start + len(p.text)] == p.text``.
"""

from __future__ import annotations

from app.core import limits
from app.core.documents import Document, Passage, Section
from app.core.text import sentence_spans

FULL_DOCUMENT = "Full document"


def _locate(document: Document, section: Section, cursor: int) -> int:
    """Offset of ``section.text`` in the document text, preferring the copy after ``cursor``.

    Extractors lay a section out as its heading line followed by its text, so
    that layout is tried first; it keeps a short section text from matching
    inside its own heading.
    """
    heading = section.heading.strip()
    if heading:
        laid_out = document.text.find(f"{heading}\n{section.text}", cursor)
        if laid_out >= 0:
            return laid_out + len(heading) + 1
    for start in (cursor, 0):
        found = document.text.find(section.text, start)
        if found >= 0:
            return found
    raise ValueError(f"section {section.heading!r} is not part of the document text")


def _strip_span(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _cut_at_whitespace(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Cut one over-long sentence at the last whitespace before the maximum (or at it)."""
    pieces: list[tuple[int, int]] = []
    maximum = limits.PASSAGE_MAX_CHARS
    while end - start > maximum:
        limit = start + maximum
        cut = max(text.rfind(" ", start + 1, limit + 1), text.rfind("\t", start + 1, limit + 1))
        cut = cut if cut > start else limit
        piece_start, piece_end = _strip_span(text, start, cut)
        if piece_start < piece_end:
            pieces.append((piece_start, piece_end))
        start, end = _strip_span(text, cut, end)
    if start < end:
        pieces.append((start, end))
    return pieces


def _units(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """A line as one unit, or, when it is too long, its sentences (cut further if needed)."""
    if end - start <= limits.PASSAGE_MAX_CHARS:
        return [(start, end)]
    units: list[tuple[int, int]] = []
    for sentence_start, sentence_end in sentence_spans(text[start:end]):
        units.extend(_cut_at_whitespace(text, start + sentence_start, start + sentence_end))
    return units


def _section_spans(document: Document, section: Section, base: int) -> list[tuple[int, int]]:
    """Passage spans for one section, as absolute offsets in the document text."""
    text = document.text
    heading = section.heading.strip()
    spans: list[tuple[int, int]] = []
    current: tuple[int, int] | None = None
    position = base
    for line in section.text.split("\n"):
        line_start, line_end = _strip_span(text, position, position + len(line))
        position += len(line) + 1
        if line_start == line_end:
            continue
        if heading and text[line_start:line_end] == heading:
            if current is not None:
                spans.append(current)
                current = None
            continue
        for unit_start, unit_end in _units(text, line_start, line_end):
            if current is not None and (
                current[1] - current[0] >= limits.PASSAGE_TARGET_CHARS
                or unit_end - current[0] > limits.PASSAGE_MAX_CHARS
            ):
                spans.append(current)
                current = None
            current = (unit_start, unit_end) if current is None else (current[0], unit_end)
    if current is not None:
        spans.append(current)
    return spans


def chunk_document(source_id: str, document: Document) -> list[Passage]:
    """All passages of ``document`` in document order, numbered ``{source_id}-p1`` onwards.

    Raises :class:`ValueError` if a section's text is not found in the document
    text, which would break the exact-substring contract of
    :class:`~app.core.documents.Document`.
    """
    located: list[tuple[int, int, str]] = []
    cursor = 0
    for section in document.sections:
        base = _locate(document, section, cursor)
        cursor = max(cursor, base + len(section.text))
        locator = section.heading.strip() or FULL_DOCUMENT
        spans = _section_spans(document, section, base)
        located.extend((start, end, locator) for start, end in spans)
    located.sort(key=lambda span: span[0])
    passages: list[Passage] = []
    previous_end = 0
    for start, end, locator in located:
        if start < previous_end:
            continue  # a section repeated in the document's section list; already covered
        passages.append(
            Passage(
                id=f"{source_id}-p{len(passages) + 1}",
                source_id=source_id,
                locator=locator,
                text=document.text[start:end],
                start=start,
            )
        )
        previous_end = end
    return passages
