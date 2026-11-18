"""Split the primary document of an SEC 10-K or 10-Q into its Items.

The document is inline-XBRL HTML whose headings are styled text, not ``<h1>``
tags. Extraction runs in two linear passes:

1. **Lines.** The ``ix:header`` block (inline-XBRL metadata, never report text)
   is cut out before the HTML is parsed, so the parser never builds the subtree
   the walk would only discard. One walk over the parsed tree drops scripts,
   styles and anything hidden with ``display:none``, and emits one line
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

from ed_v4.core.documents import Document, Section

PUBLISHER = "SEC EDGAR"
COVER_HEADING = "Cover page"
UNNUMBERED_HEADING = "Unnumbered text"
# Text before the first Item is a cover page only up to this size. A real cover page
# with its table of contents and forward-looking-statements notice is far shorter (10,191
# characters in NVIDIA's 10-K, 5,079 in its 10-Q); a filing that cross-references Items
# to pages instead puts hundreds of thousands of characters there (618,101 in JPMorgan's
# 10-Q). 20,000 leaves twice the largest real cover page measured before mislabelling.
COVER_MAX_CHARS = 20_000
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

# The inline-XBRL header: contexts, units and hidden facts. 14-17% of the tags of NVIDIA's
# filings sit inside it, and parsing tags is most of the cost of reading a filing.
IX_HEADER = re.compile(r"<ix:header\b.*?</ix:header\s*>", re.IGNORECASE | re.DOTALL)
HIDDEN = re.compile(r"display\s*:\s*none", re.IGNORECASE)
FONT_WEIGHT = re.compile(r"font-weight\s*:\s*([a-z]+|\d+)", re.IGNORECASE)
WHITESPACE = re.compile(r"\s+")
INVISIBLE = re.compile(r"[​‌‍﻿]")  # zero-width spaces and joiners
PAGE_NUMBER = re.compile(r"^(?:(?:page\s+)?\d{1,3}|[ivxl]{1,6})$", re.IGNORECASE)
PAGE_NUMBER_SUFFIX = re.compile(r"\s(?:\d{1,3}|[ivxl]{1,6})$")
CONTENTS_LINK = re.compile(r"^(?:(?:return|back) to )?table of contents$", re.IGNORECASE)
PART_LINE = re.compile(r"^part\s+(iv|iii|ii|i)\b\s*[.:,\-–—]?\s*(.*)$", re.IGNORECASE)
# "Item 1A. Risk Factors", "Item 1A—Risk Factors", "Item 1A: ...", "Item 1A - ...", "Item 1A Risk".
ITEM_LINE = re.compile(r"^item\s+(\d{1,2}[a-z]?)(?:\s*([.:\-–—])\s*|\s+|$)(.*)$", re.IGNORECASE)
# A section heading produced for a numbered Item (see _heading_label).
ITEM_SECTION = re.compile(r"^(?:Part (?:IV|III|II|I), )?Item \d{1,2}[A-Z]?\.")
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
    body_start: int  # after the title line, when the title stood on the next line
    part: str | None
    number: str
    title: str

    @property
    def key(self) -> tuple[str | None, str]:
        return (self.part, self.number)

    @property
    def own_title(self) -> bool:
        """The title was on the heading line itself (not borrowed from the next line)."""
        return bool(self.title) and self.body_start == self.line + 1


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


def _cut_ix_headers(html: str) -> tuple[str, str]:
    """``html`` without its ``ix:header`` blocks, and those blocks joined.

    The header is never report text, and the line walk skips it anyway; cutting
    it before parsing saves building its subtree. The blocks are kept only so
    the document type can still be read from them when the body does not tag it.
    """
    headers = [match.group() for match in IX_HEADER.finditer(html)]
    return (IX_HEADER.sub("", html), "".join(headers)) if headers else (html, "")


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


def _standalone_part(text: str) -> str | None:
    """The Part numeral of a line such as "PART II — OTHER INFORMATION", else None."""
    match = PART_LINE.match(text) if len(text) <= MAX_PART_LINE_CHARS else None
    if match is None or "item" in match.group(2).casefold():
        return None
    return match.group(1).upper()


def _part_headings(lines: list[_Line]) -> set[int]:
    """Indexes of the Part lines that set the current Part: each Part's own headings.

    A Part line in a table row or a link is an index entry. It counts only when the
    Part has no heading of its own in the body, and then only its last mention does,
    so an index at the front never labels Items that precede the Part's real heading.
    """
    mentions: dict[str, list[tuple[int, bool]]] = {}
    for index, line in enumerate(lines):
        part = _standalone_part(line.text)
        if part is not None:
            mentions.setdefault(part, []).append((index, line.row or line.linked))
    setters: set[int] = set()
    for found in mentions.values():
        own = [index for index, is_index_entry in found if not is_index_entry]
        setters.update(own or [found[-1][0]])
    return setters


def _find_headings(lines: list[_Line]) -> tuple[list[_Heading], set[int]]:
    """Item headings in order, and the indexes of Part lines (never emitted as text)."""
    headings: list[_Heading] = []
    part_lines: set[int] = set()
    setters = _part_headings(lines)
    part: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        text = line.text
        standalone = _standalone_part(text)
        if standalone is not None:
            if index in setters:
                part = standalone
            part_lines.add(index)
            index += 1
            continue
        part_match = PART_LINE.match(text) if len(text) <= MAX_PART_LINE_CHARS else None
        if part_match and ITEM_LINE.match(part_match.group(2)):
            # "PART II Item 7" (often a running page header) names its Part itself.
            part = part_match.group(1).upper()
            text = part_match.group(2)
        item_match = ITEM_LINE.match(text)
        if item_match and len(text) <= MAX_ITEM_LINE_CHARS and not line.toc_like:
            title = _clean_title(item_match.group(3))
            if item_match.group(2) is None and title and not title[0].isupper():
                title = None  # "Item 7 of our report ...": a reference, not a heading
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
    spans: list[tuple[int, int]],
    part_lines: set[int],
) -> list[Section]:
    """Sections of one Item, whose lines lie in ``spans`` (line ranges, in order).

    A candidate line followed by a non-candidate opens a sub-section.
    """
    sections: list[Section] = []
    heading = label
    buffer: list[str] = []
    for start, end in spans:
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


def _occurrences(
    headings: list[_Heading], line_count: int
) -> list[tuple[_Heading, list[tuple[int, int]]]]:
    """Each occurrence of an Item: the heading that names it and the line ranges under it.

    Consecutive headings of the same Part and Item (a running page header such as
    "PART II Item 7" repeated on every page) are one occurrence. It is named by the
    first heading whose title stood on its own line; the others contribute only the
    lines after them, so a body line is never swallowed as a repeated header's title.
    """
    ends = [heading.line for heading in headings[1:]] + [line_count]
    runs: list[list[tuple[_Heading, int]]] = []
    for heading, end in zip(headings, ends, strict=True):
        if runs and runs[-1][0][0].key == heading.key:
            runs[-1].append((heading, end))
        else:
            runs.append([(heading, end)])
    occurrences: list[tuple[_Heading, list[tuple[int, int]]]] = []
    for run in runs:
        named = next((h for h, _ in run if h.own_title), None) or next(
            (h for h, _ in run if h.title), run[0][0]
        )
        spans = [(h.body_start if h is named else h.line + 1, end) for h, end in run]
        occurrences.append((named, spans))
    return occurrences


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
    groups = _occurrences(headings, len(lines))

    # Where the same Part and Item occur more than once, keep the one with the most text.
    best: dict[tuple[str | None, str], tuple[int, int]] = {}
    for position, (heading, spans) in enumerate(groups):
        size = sum(
            len(lines[index].text)
            for start, end in spans
            for index in range(start, end)
            if index not in part_lines
        )
        if heading.key not in best or size >= best[heading.key][1]:
            best[heading.key] = (position, size)
    kept = {position for position, _ in best.values()}

    candidates = _subheading_candidates(lines)
    sections: list[Section] = []
    first = headings[0].line
    before = sum(len(lines[index].text) for index in range(first) if index not in part_lines)
    if before <= COVER_MAX_CHARS:
        cover = [lines[index].text for index in range(first) if index not in part_lines]
        if cover:
            sections.append(Section(heading=COVER_HEADING, text="\n".join(cover)))
    else:
        # A filing that cross-references Items to pages: most of its text precedes any
        # numbered Item, so it is not a cover page. Bold sub-headings still split it.
        unnumbered = (UNNUMBERED_HEADING, [(0, first)])
        sections.extend(_item_sections(lines, candidates, *unnumbered, part_lines))
    for position, (heading, spans) in enumerate(groups):
        if position in kept:
            label = _heading_label(heading, with_part)
            sections.extend(_item_sections(lines, candidates, label, spans, part_lines))
    return sections


def parse_filing(html: str, *, url: str, title: str, published_date: str | None) -> Document:
    """Extract a filing's text and split it into Item sections (with sub-sections).

    Falls back to one section headed "Full document" when no Item heading is found.
    """
    body, headers = _cut_ix_headers(html)
    soup = BeautifulSoup(body, "html.parser")
    document_type = _document_type(soup)
    if document_type is None and headers:
        document_type = _document_type(BeautifulSoup(headers, "html.parser"))
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


def _is_item_section(section: Section) -> bool:
    return ITEM_SECTION.match(section.heading) is not None


def item_labels(document: Document) -> list[str]:
    """The distinct numbered Items found, in document order (sub-headings folded in)."""
    labels = (
        section.heading.split(SUBHEADING_SEPARATOR)[0]
        for section in document.sections
        if _is_item_section(section)
    )
    return list(dict.fromkeys(labels))


def item_coverage(document: Document) -> float:
    """Share of the document's section text (0.0 to 1.0) that sits under numbered Items.

    Cover page, unnumbered text and the "Full document" fallback count against it.
    """
    total = sum(len(section.text) for section in document.sections)
    if total == 0:
        return 0.0
    under_items = sum(len(s.text) for s in document.sections if _is_item_section(s))
    return under_items / total
