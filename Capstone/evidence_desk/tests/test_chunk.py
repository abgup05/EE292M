"""Passages are exact, ordered, bounded slices of the stored document text."""

import random

from app.core import limits
from app.core.documents import Document, Passage, Section
from app.retrieval.chunk import chunk_document

WORDS = ["revenue", "grew", "Data", "Center", "customers", "H20", "export", "10%", "U.S.", "risk"]


def make_document(sections: list[tuple[str, str]], separator: str = "\n\n") -> Document:
    """Lay sections out the way the extractors do: heading line, then the section text."""
    text = separator.join(f"{heading}\n{body}" if heading else body for heading, body in sections)
    return Document(
        url="https://example.org/doc",
        title="Doc",
        publisher="Example",
        published_date=None,
        text=text,
        content_hash="x",
        sections=[Section(heading=heading, text=body) for heading, body in sections],
    )


def _line_spans(document: Document) -> list[tuple[str, int, int]]:
    """(heading, start, end) of every non-blank, non-heading line, located in document order."""
    out = []
    cursor = 0
    for section in document.sections:
        base = document.text.index(section.text, cursor)
        cursor = base + len(section.text)
        position = base
        for line in section.text.split("\n"):
            stripped = line.strip()
            if stripped and stripped != section.heading.strip():
                left = position + (len(line) - len(line.lstrip()))
                out.append((section.heading, left, left + len(stripped)))
            position += len(line) + 1
    return out


def assert_invariants(document: Document, passages: list[Passage]) -> None:
    previous_end = 0
    for number, passage in enumerate(passages, start=1):
        assert passage.id == f"src-1-p{number}"
        assert passage.source_id == "src-1"
        assert document.text[passage.start : passage.start + len(passage.text)] == passage.text
        assert passage.start >= previous_end, "passages overlap or are out of order"
        assert 0 < len(passage.text) <= limits.PASSAGE_MAX_CHARS
        assert passage.text == passage.text.strip()
        previous_end = passage.start + len(passage.text)
    for section in document.sections:
        heading = section.heading.strip()
        if heading:
            for passage in passages:
                assert heading not in passage.text.split("\n")
    spans = [(p.start, p.start + len(p.text), p.locator) for p in passages]
    for heading, start, end in _line_spans(document):
        for index in range(start, end):
            if document.text[index].isspace():
                continue
            owners = [locator for s, e, locator in spans if s <= index < e]
            assert owners, f"character {index} of a line under {heading!r} is not covered"
            assert owners == [heading or "Full document"]


def test_short_lines_pack_into_passages_near_the_target() -> None:
    line = "Data Center revenue grew because customers bought more systems this quarter."
    body = "\n".join(f"{line} ({n})" for n in range(60))
    document = make_document([("Part I, Item 2. MD&A", body), ("Part II, Item 1A. Risk", body)])
    passages = chunk_document("src-1", document)
    assert_invariants(document, passages)
    assert {p.locator for p in passages} == {"Part I, Item 2. MD&A", "Part II, Item 1A. Risk"}
    full = [p for p in passages[:-1] if p.locator == passages[passages.index(p) + 1].locator]
    assert full and all(len(p.text) >= limits.PASSAGE_TARGET_CHARS for p in full)


def test_empty_heading_reads_full_document() -> None:
    document = make_document([("", "Only text here, with no heading at all.")])
    [passage] = chunk_document("src-1", document)
    assert passage.locator == "Full document"
    assert passage.text == "Only text here, with no heading at all."
    assert passage.start == 0


def test_long_line_splits_at_sentences_then_whitespace() -> None:
    sentence = "Export rules restrict sales of H20 products to China and other regions. "
    long_line = sentence * 60  # one line, far above the maximum
    unbroken = "word " * 600  # one sentence, no terminal punctuation
    solid = "x" * (limits.PASSAGE_MAX_CHARS * 2 + 7)  # no whitespace at all
    document = make_document([("Item 1A. Risk Factors", f"{long_line}\n{unbroken}\n{solid}")])
    passages = chunk_document("src-1", document)
    assert_invariants(document, passages)
    sentence_passages = [p for p in passages if "Export" in p.text]
    assert all(p.text.endswith("regions.") for p in sentence_passages)
    assert all(not p.text.endswith("wor") for p in passages)


def test_heading_line_inside_section_text_is_never_quoted() -> None:
    heading = "Item 2. Properties"
    document = make_document([(heading, f"{heading}\nWe lease our headquarters.")], "\n")
    passages = chunk_document("src-1", document)
    assert [p.text for p in passages] == ["We lease our headquarters."]
    assert_invariants(document, passages)


def test_ids_count_across_the_whole_document() -> None:
    document = make_document([("A", "First section text."), ("B", "Second section text.")])
    passages = chunk_document("src-1", document)
    assert [p.id for p in passages] == ["src-1-p1", "src-1-p2"]
    assert [p.locator for p in passages] == ["A", "B"]


def test_document_without_sections_gives_no_passages() -> None:
    assert chunk_document("src-1", make_document([])) == []


def _random_body(rng: random.Random) -> str:
    lines = []
    for _ in range(rng.randint(0, 25)):
        kind = rng.random()
        if kind < 0.1:
            lines.append(rng.choice(["", "   "]))
        elif kind < 0.2:
            lines.append(" ".join(rng.choice(WORDS) for _ in range(rng.randint(300, 700))))
        elif kind < 0.25:
            lines.append("y" * rng.randint(1, 4000))
        else:
            words = (rng.choice(WORDS) for _ in range(rng.randint(1, 40)))
            lines.append("  " + " ".join(words) + rng.choice([".", "", "!", ". "]))
    return "\n".join(lines)


def test_invariants_hold_on_random_documents() -> None:
    rng = random.Random(20261117)
    for _ in range(200):
        sections = [
            (rng.choice(["", "Item 1. Business", "Item 7. MD&A › Revenue", "Part II"]), body)
            for body in (_random_body(rng) for _ in range(rng.randint(0, 5)))
            if body.strip()
        ]
        document = make_document(sections, rng.choice(["\n", "\n\n", "\n \n"]))
        assert_invariants(document, chunk_document("src-1", document))
