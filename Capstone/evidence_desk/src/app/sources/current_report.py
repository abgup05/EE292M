"""Split the primary document of an SEC current report (Form 8-K) into its Items.

An 8-K is short: a cover page, one heading per item it reports ("Item 5.02.
Departure of Directors or Certain Officers; ..."), then the signature block and
sometimes an exhibit index. The lines are read exactly as a 10-K's are
(:mod:`app.sources.filing`: the inline-XBRL header cut out, hidden text dropped,
one line per paragraph and per table row); only the sections differ:

- a line that starts "Item N.NN" (or "Items N.NN and M.MM") opens an item
  section, unless it reads as a reference ("Item 2.03 of this report ...");
  a heading whose title stands on the next line takes that line as its title;
- the signature block ("SIGNATURE", "SIGNATURES", or the sentence that opens it)
  and an exhibit index after the last item are not part of that item: they form
  one section of their own, :data:`TRAILER_HEADING`;
- where the same item number heads two sections, the one with more text is kept.

The stored text is ``"\\n\\n".join(heading + "\\n" + section text)``, the layout
:mod:`app.sources.filing` uses, so every section is an exact substring of
:attr:`Document.text` and the chunker and the citation gate treat an 8-K like
any other filing. Filing text is data, never instructions.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import bs4
from bs4 import BeautifulSoup

from app.core.documents import Document, Section
from app.sources import filing

# The line reader of the 10-K parser, reused so that an 8-K's lines are read the same way.
from app.sources.filing import _cut_ix_headers, _Line, _LineCollector

PUBLISHER = "SEC EDGAR"
COVER_HEADING = "Cover page"
TRAILER_HEADING = "Signature and exhibit index"
FALLBACK_HEADING = "Full document"
MAX_HEADING_LINE_CHARS = 300
MAX_TITLE_LINE_CHARS = 200
MAX_TRAILER_LINE_CHARS = 40
# A title on the line after a bare "Item 8.01." ends in a full stop only when it is this short.
MAX_DOTTED_TITLE_CHARS = 60
MAX_TITLE_WORDS = 25

ITEM_NUMBER = r"\d{1,2}\.\d{1,2}"
# "Item 5.02.", "ITEM 5.02 -", "Item 5.02:", "Items 2.02 and 9.01.", "Item 2.02, 7.01 and 9.01".
HEADING_LINE = re.compile(
    rf"^items?\s*({ITEM_NUMBER}(?:\s*(?:,\s*and|,|and|&)\s*{ITEM_NUMBER})*)"
    r"(?:\s*([.:\-–—])\s*|\s+|$)(.*)$",
    re.IGNORECASE,
)
NUMBER = re.compile(ITEM_NUMBER)
# What ends the last item: the signature block, or an exhibit index, as a heading line.
TRAILER_LINE = re.compile(
    r"^(?:signatures?|exhibit index|index to exhibits|exhibits index|list of exhibits)\s*[.:]?$",
    re.IGNORECASE,
)
SIGNATURE_SENTENCE = re.compile(
    r"^pursuant to the requirements of the securities exchange act of 1934", re.IGNORECASE
)


def parser_version() -> str:
    """This splitter's identity: SHA-256 of this file and of the line reader, and bs4's version.

    An edit to either file gives a new version, and an 8-K cached under an older
    one is fetched and split again.
    """
    digest = hashlib.sha256()
    for module_file in (__file__, filing.__file__):
        digest.update(Path(module_file).read_bytes())
    return f"8k-{digest.hexdigest()[:16]}-bs4-{bs4.__version__}"


def normalise_number(number: str) -> str:
    """An item number as EDGAR's index writes it: "5.2" and "5.02" are both "5.02"."""
    major, minor = number.split(".")
    return f"{int(major)}.{int(minor):02d}"


@dataclass(frozen=True, slots=True)
class _Heading:
    line: int
    body_start: int
    numbers: tuple[str, ...]
    title: str


def _clean_title(title: str) -> str:
    """A heading's title without its closing full stop."""
    return title.strip().rstrip(".").rstrip()


def _title_line(line: _Line) -> bool:
    """Could ``line`` be the title of an item whose number stood alone on the line before?

    A short line that is not itself a heading, a sub-item marker such as "(b)" or the
    signature block; one that ends in a full stop only when it is very short, as
    "Other Events." is and an opening sentence is not.
    """
    text = line.text
    return (
        len(text) <= MAX_TITLE_LINE_CHARS
        and HEADING_LINE.match(text) is None
        and TRAILER_LINE.match(text) is None
        and not SIGNATURE_SENTENCE.match(text)
        and any(character.isalpha() for character in text)
        and not text.startswith("(")
        and len(text.split()) <= MAX_TITLE_WORDS
        and (not text.endswith(".") or len(text) <= MAX_DOTTED_TITLE_CHARS)
    )


def _headings(lines: list[_Line]) -> list[_Heading]:
    headings: list[_Heading] = []
    index = 0
    while index < len(lines):
        text = lines[index].text
        match = HEADING_LINE.match(text) if len(text) <= MAX_HEADING_LINE_CHARS else None
        if match is None:
            index += 1
            continue
        title = match.group(3).strip()
        if match.group(2) is None and title and not title[0].isupper():
            index += 1  # "Item 1.01 of this report ...": a reference, not a heading
            continue
        cleaned = _clean_title(title)
        body_start = index + 1
        if not cleaned and body_start < len(lines) and _title_line(lines[body_start]):
            cleaned = _clean_title(lines[body_start].text)
            body_start += 1
        numbers = tuple(dict.fromkeys(normalise_number(n) for n in NUMBER.findall(match.group(1))))
        headings.append(_Heading(index, body_start, numbers, cleaned))
        index = body_start
    return headings


def _trailer_start(lines: list[_Line], after: int) -> int:
    """The first line at or after ``after`` that opens the signature block or exhibit index."""
    for index in range(after, len(lines)):
        text = lines[index].text
        if len(text) <= MAX_TRAILER_LINE_CHARS and TRAILER_LINE.match(text):
            return index
        if SIGNATURE_SENTENCE.match(text):
            return index
    return len(lines)


def heading_label(numbers: tuple[str, ...], title: str) -> str:
    """The section heading written for an item: "Item 5.02. Title" or "Items 2.02 and 9.01."."""
    if len(numbers) == 1:
        label = f"Item {numbers[0]}."
    else:
        label = f"Items {', '.join(numbers[:-1])} and {numbers[-1]}."
    return f"{label} {title}" if title else label


def _sections(lines: list[_Line]) -> list[Section]:
    headings = _headings(lines)
    texts = [line.text for line in lines]
    if not headings:
        return [Section(heading=FALLBACK_HEADING, text="\n".join(texts))] if texts else []
    trailer = _trailer_start(lines, headings[-1].body_start)
    ends = [heading.line for heading in headings[1:]] + [trailer]
    bodies = [
        (heading, "\n".join(texts[heading.body_start : end]))
        for heading, end in zip(headings, ends, strict=True)
    ]
    # Where an item number heads two sections, keep the one with more text (a cover-page list
    # of items, or a repeated heading, is the shorter).
    best: dict[str, int] = {}
    for position, (heading, body) in enumerate(bodies):
        for number in heading.numbers:
            if number not in best or len(body) > len(bodies[best[number]][1]):
                best[number] = position
    kept = set(best.values())
    sections: list[Section] = []
    cover = "\n".join(texts[: headings[0].line])
    if cover:
        sections.append(Section(heading=COVER_HEADING, text=cover))
    for position, (heading, body) in enumerate(bodies):
        if position in kept and body:
            label = heading_label(heading.numbers, heading.title)
            sections.append(Section(heading=label, text=body))
    tail = "\n".join(texts[trailer:])
    if tail:
        sections.append(Section(heading=TRAILER_HEADING, text=tail))
    return sections


def parse_current_report(
    html: str, *, url: str, title: str, published_date: str | None
) -> Document:
    """Extract an 8-K's text and split it into one section per item heading.

    Falls back to one section headed "Full document" when no item heading is found.
    """
    body, _headers = _cut_ix_headers(html)
    soup = BeautifulSoup(body, "html.parser")
    collector = _LineCollector()
    collector.walk(soup, False)
    collector.flush()
    sections = _sections(collector.lines)
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
