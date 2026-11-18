"""Split the primary document of an SEC 10-K or 10-Q into its Items.

The document is inline-XBRL HTML whose headings are styled text, not ``<h1>``
tags. Extraction runs in two linear passes:

1. **Lines.** One walk over the parsed tree drops the ``ix:header`` block,
   scripts, styles and anything hidden with ``display:none``, and emits one line
   per paragraph-like block and one per table row (cells joined by single spaces,
   with a lone ``$`` joined to the number after it and a lone ``%`` or ``)`` to
   the number before it). Bare page numbers and the running "Table of Contents"
   links are dropped.
2. **Sections.** ``PART`` and ``Item N.`` headings are recognised from the text
   of a line. Table-of-contents entries (linked, or ending in a page number) are
   not headings. Where the same Part and Item occur more than once, the
   occurrence with the most text under it is kept. A short bold line that starts
   a run of paragraphs opens a sub-section headed ``<item> › <sub-heading>``.

The stored text is ``"\\n\\n".join(heading + "\\n" + section text)``, so every
section is an exact substring of :attr:`Document.text`. Filing text is data,
never instructions.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass

from bs4 import BeautifulSoup, NavigableString, Tag
from bs4.element import PreformattedString

from ed_v2.core.documents import Document, Section

PUBLISHER = "SEC EDGAR"
COVER_HEADING = "Cover page"
FALLBACK_HEADING = "Full document"
SUBHEADING_SEPARATOR = " › "
MAX_SUBHEADING_CHARS = 140
RUNNING_HEADER_REPEATS = 4
MAX_ITEM_LINE_CHARS = 200
MAX_PART_LINE_CHARS = 100
MAX_TITLE_LINE_CHARS = 150
# A heading title may end in a full stop only when it is this short (else it is a sentence).
MAX_DOTTED_TITLE_CHARS = 80

SKIPPED_TAGS = frozenset(
    {"head", "title", "meta", "link", "script", "style", "noscript", "template", "ix:header"}
)
BLOCK_TAGS = frozenset(
    {
        "html",
        "body",
        "div",
        "p",
        "li",
        "ul",
        "ol",
        "dl",
        "dt",
        "dd",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "pre",
        "section",
        "article",
        "center",
        "table",
        "thead",
        "tbody",
        "tfoot",
        "caption",
        "td",
        "th",
        "hr",
        "figure",
        "figcaption",
        "address",
    }
)
CELL_TAGS = ("td", "th")
JOIN_TO_NEXT = frozenset({"$"})
JOIN_TO_PREVIOUS = frozenset({"%", ")", "%)"})

HIDDEN = re.compile(r"display\s*:\s*none", re.IGNORECASE)
FONT_WEIGHT = re.compile(r"font-weight\s*:\s*([a-z]+|\d+)", re.IGNORECASE)
WHITESPACE = re.compile(r"\s+")
INVISIBLE = re.compile("[​‌‍﻿]")
PAGE_NUMBER = re.compile(r"^(?:(?:page\s+)?\d{1,3}|[ivxl]{1,6})$", re.IGNORECASE)
PAGE_NUMBER_SUFFIX = re.compile(r"\s(?:\d{1,3}|[ivxl]{1,6})$")
CONTENTS_LINK = re.compile(r"^(?:(?:return|back) to )?table of contents$", re.IGNORECASE)
PART_LINE = re.compile(r"^part\s+(iv|iii|ii|i)\b\s*[.:,\-–—]?\s*(.*)$", re.IGNORECASE)
ITEM_LINE = re.compile(r"^item\s+(\d{1,2}[a-z]?)\s*[.:]\s*(.*)$", re.IGNORECASE)
LETTER = re.compile(r"[A-Za-z]")


@dataclass(frozen=True, slots=True)
class _Line:
    """One emitted line and the layout facts the section pass needs."""

    text: str
    bold: bool
    row: bool
    linked: bool  # contains an in-document link (#anchor), as table-of-contents entries do

    @property
    def toc_like(self) -> bool:
        return self.linked or (self.row and PAGE_NUMBER_SUFFIX.search(self.text) is not None)


@dataclass(frozen=True, slots=True)
class _Heading:
    """An Item heading found in the line sequence."""

    line: int
    body_start: int
    part: str | None
    number: str
    title: str


def _clean(value: str) -> str:
    """Collapse all whitespace, non-breaking spaces included, and drop zero-width characters."""
    return WHITESPACE.sub(" ", INVISIBLE.sub("", value)).strip()


def _is_bold(tag: Tag, inherited: bool) -> bool:
    if tag.name in ("b", "strong"):
        return True
    style = tag.get("style")
    if isinstance(style, str):
        match = FONT_WEIGHT.search(style)
        if match:
            weight = match.group(1).lower()
            return weight in ("bold", "bolder") or (weight.isdigit() and int(weight) >= 600)
    return inherited


def _is_hidden(tag: Tag) -> bool:
    if tag.name in SKIPPED_TAGS:
        return True
    style = tag.get("style")
    return isinstance(style, str) and HIDDEN.search(style) is not None


def _is_internal_link(tag: Tag) -> bool:
    href = tag.get("href")
    return tag.name == "a" and isinstance(href, str) and href.startswith("#")


def _join_cells(cells: list[str]) -> str:
    """Join row cells with single spaces, re-attaching lone currency and percent signs."""
    joined: list[str] = []
    prefix = ""
    for cell in cells:
        if cell in JOIN_TO_NEXT:
            prefix += cell
        elif cell in JOIN_TO_PREVIOUS and joined and not prefix:
            joined[-1] += cell
        else:
            joined.append(prefix + cell)
            prefix = ""
    if prefix:
        joined.append(prefix)
    return " ".join(joined)


class _LineCollector:
    """Walks the tree once, in document order, and emits :class:`_Line` records."""

    def __init__(self) -> None:
        self.lines: list[_Line] = []
        self._parts: list[tuple[str, bool]] = []
        self._linked = False

    def _emit(self, text: str, *, bold: bool, row: bool, linked: bool) -> None:
        if text and not PAGE_NUMBER.match(text) and not CONTENTS_LINK.match(text):
            self.lines.append(_Line(text=text, bold=bold, row=row, linked=linked))

    def flush(self) -> None:
        """End the current paragraph-like line."""
        if self._parts:
            text = _clean("".join(piece for piece, _ in self._parts))
            bold = all(is_bold for piece, is_bold in self._parts if piece.strip())
            self._emit(text, bold=bold, row=False, linked=self._linked)
        self._parts.clear()
        self._linked = False

    def walk(self, node: Tag, bold: bool) -> None:
        """Collect the visible text under ``node``, breaking lines at block boundaries."""
        for child in node.children:
            if isinstance(child, NavigableString):
                if not isinstance(child, PreformattedString):
                    self._parts.append((str(child), bold))
                continue
            if not isinstance(child, Tag) or _is_hidden(child):
                continue
            if child.name == "tr":
                self.flush()
                self._row(child)
                continue
            if child.name == "br":
                self.flush()
                continue
            if _is_internal_link(child):
                self._linked = True
            block = child.name in BLOCK_TAGS
            if block:
                self.flush()
            self.walk(child, _is_bold(child, bold))
            if block:
                self.flush()

    def _row(self, row: Tag) -> None:
        cells: list[str] = []
        linked = [False]
        for cell in row.children:
            if isinstance(cell, Tag) and cell.name in CELL_TAGS and not _is_hidden(cell):
                pieces: list[str] = []
                self._cell_text(cell, pieces, linked)
                text = _clean("".join(pieces))
                if text:
                    cells.append(text)
        self._emit(_join_cells(cells), bold=False, row=True, linked=linked[0])

    def _cell_text(self, node: Tag, pieces: list[str], linked: list[bool]) -> None:
        for child in node.children:
            if isinstance(child, NavigableString):
                if not isinstance(child, PreformattedString):
                    pieces.append(str(child))
                continue
            if not isinstance(child, Tag) or _is_hidden(child):
                continue
            if _is_internal_link(child):
                linked[0] = True
            separate = child.name in BLOCK_TAGS or child.name in ("br", "tr")
            if separate:
                pieces.append(" ")
            self._cell_text(child, pieces, linked)
            if separate:
                pieces.append(" ")


def _document_type(soup: BeautifulSoup) -> str | None:
    """The ``dei:DocumentType`` tagged in the filing (``10-K``, ``10-Q``), if any."""
    tag = soup.find("ix:nonnumeric", attrs={"name": "dei:DocumentType"})
    return _clean(tag.get_text()) if isinstance(tag, Tag) else None


def _title_like(line: _Line) -> bool:
    """Could ``line`` be the title of an Item whose number stood alone on the line before?"""
    text = line.text
    return (
        len(text) <= MAX_TITLE_LINE_CHARS
        and not text.endswith(".")
        and not line.toc_like
        and LETTER.search(text) is not None
        and not ITEM_LINE.match(text)
        and not PART_LINE.match(text)
    )


def _clean_title(title: str) -> str | None:
    """The title with a trailing full stop removed, or None if it reads like a sentence."""
    title = title.strip()
    if title.endswith("."):
        if len(title) > MAX_DOTTED_TITLE_CHARS:
            return None
        title = title.rstrip(".").rstrip()
    return title


def _find_headings(lines: list[_Line]) -> tuple[list[_Heading], set[int]]:
    """Item headings in order, and the indexes of Part lines (never emitted as text)."""
    headings: list[_Heading] = []
    part_lines: set[int] = set()
    part: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        text = line.text
        part_match = PART_LINE.match(text) if len(text) <= MAX_PART_LINE_CHARS else None
        if part_match:
            rest = part_match.group(2)
            if ITEM_LINE.match(rest):
                part = part_match.group(1).upper()
                text = rest
            elif "item" not in rest.casefold():
                part = part_match.group(1).upper()
                part_lines.add(index)
                index += 1
                continue
        item_match = ITEM_LINE.match(text)
        if item_match and len(text) <= MAX_ITEM_LINE_CHARS and not line.toc_like:
            title = _clean_title(item_match.group(2))
            body_start = index + 1
            if title == "" and body_start < len(lines) and _title_like(lines[body_start]):
                title = _clean_title(lines[body_start].text)
                body_start += 1
            if title is not None:
                number = item_match.group(1).upper()
                headings.append(_Heading(index, body_start, part, number, title))
                index = body_start
                continue
        index += 1
    return headings, part_lines


def _heading_label(heading: _Heading, with_part: bool) -> str:
    item = f"Item {heading.number}." + (f" {heading.title}" if heading.title else "")
    if with_part and heading.part:
        return f"Part {heading.part}, {item}"
    return item


def _short_bold(line: _Line) -> bool:
    """A short bold paragraph line with no closing full stop and not a parenthetical."""
    text = line.text
    return (
        line.bold
        and not line.row
        and len(text) < MAX_SUBHEADING_CHARS
        and not text.endswith(".")
        and not text.startswith("(")
        and LETTER.search(text) is not None
    )


def _subheading_candidates(lines: list[_Line]) -> list[bool]:
    """Which lines may open a sub-section.

    A short bold line repeated :data:`RUNNING_HEADER_REPEATS` times or more is a
    running page header ("Notes to Consolidated Financial Statements"), not a heading.
    """
    counts = Counter(line.text for line in lines if _short_bold(line))
    return [_short_bold(line) and counts[line.text] < RUNNING_HEADER_REPEATS for line in lines]


def _item_sections(
    lines: list[_Line],
    candidates: list[bool],
    label: str,
    span: tuple[int, int],
    part_lines: set[int],
) -> list[Section]:
    """Sections of one Item: a candidate line followed by a non-candidate opens a sub-section."""
    start, end = span
    sections: list[Section] = []
    heading = label
    buffer: list[str] = []
    for index in range(start, end):
        if index in part_lines:
            continue
        if candidates[index] and index + 1 < end and not candidates[index + 1]:
            if buffer:
                sections.append(Section(heading=heading, text="\n".join(buffer)))
            heading = f"{label}{SUBHEADING_SEPARATOR}{lines[index].text}"
            buffer = []
            continue
        buffer.append(lines[index].text)
    if buffer:
        sections.append(Section(heading=heading, text="\n".join(buffer)))
    return sections


def _sections(lines: list[_Line], document_type: str | None) -> list[Section]:
    headings, part_lines = _find_headings(lines)
    if not headings:
        text = "\n".join(line.text for line in lines)
        return [Section(heading=FALLBACK_HEADING, text=text)] if text else []

    with_part = (
        document_type.upper().startswith("10-Q")
        if document_type
        else len({(h.part, h.number) for h in headings}) > len({h.number for h in headings})
    )
    ends = [heading.line for heading in headings[1:]] + [len(lines)]
    spans = list(zip(headings, ends, strict=True))

    # Where the same Part and Item occur more than once, keep the one with the most text.
    best: dict[tuple[str | None, str], tuple[int, int]] = {}
    for position, (heading, end) in enumerate(spans):
        size = sum(
            len(lines[index].text)
            for index in range(heading.body_start, end)
            if index not in part_lines
        )
        key = (heading.part, heading.number)
        if key not in best or size >= best[key][1]:
            best[key] = (position, size)
    kept = {position for position, _ in best.values()}

    sections: list[Section] = []
    cover = [lines[index].text for index in range(headings[0].line) if index not in part_lines]
    if cover:
        sections.append(Section(heading=COVER_HEADING, text="\n".join(cover)))
    candidates = _subheading_candidates(lines)
    for position, (heading, end) in enumerate(spans):
        if position in kept:
            label = _heading_label(heading, with_part)
            span = (heading.body_start, end)
            sections.extend(_item_sections(lines, candidates, label, span, part_lines))
    return sections


def parse_filing(html: str, *, url: str, title: str, published_date: str | None) -> Document:
    """Extract a filing's text and split it into Item sections (with sub-sections).

    Falls back to one section headed "Full document" when no Item heading is found.
    """
    soup = BeautifulSoup(html, "html.parser")
    document_type = _document_type(soup)
    collector = _LineCollector()
    collector.walk(soup, False)
    collector.flush()
    sections = _sections(collector.lines, document_type)
    text = "\n\n".join(f"{section.heading}\n{section.text}" for section in sections)
    return Document(
        url=url,
        title=title,
        publisher=PUBLISHER,
        published_date=published_date,
        text=text,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        sections=sections,
    )
