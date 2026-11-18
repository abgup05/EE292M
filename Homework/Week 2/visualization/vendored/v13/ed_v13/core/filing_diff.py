"""What changed between two filings of one company: paragraphs added, removed and reworded.

Pure: two :class:`~app.core.documents.Document` records in, one
:class:`~app.core.change_models.ItemChanges` per Item out; no network, no files.

**Unit.** A paragraph is one line of a section's text (the filing parser emits one
line per paragraph or table row). Sections are grouped by their Item, the heading
before :data:`SUBHEADING_SEPARATOR`, and Items are matched across the two filings
by :func:`item_key` (Part and Item number; case, punctuation and title ignored).
Any other heading ("Cover page", "Unnumbered text", "Full document") is its own group.

**Classification**, within one Item, in three passes:

1. *Unchanged*: identical after collapsing whitespace, folding case and straightening
   typographic quotes. Matching is by text, not position, so a paragraph that only
   moved within its Item is unchanged.
2. *Numbers only*: identical once every number, date and currency amount is also
   replaced by a placeholder ("$46.7 billion, up 56%" against "$96.2 billion, up 106%").
3. *Reworded*: of what is left, paragraphs of at least :data:`MIN_PARAGRAPH_CHARS`
   that are not table rows (:func:`is_table_row`) are paired by the Jaccard similarity
   of their word-token sets (:func:`similarity_tokens`: :func:`app.core.text.tokenize`,
   which stems and drops stop words, less tokens that are only digits, so an updated
   figure never counts against a paragraph that kept its words). Every pair at or
   above :data:`REWORD_THRESHOLD` is a candidate; pairs
   are taken greedily, most similar first, each paragraph at most once. Later
   paragraphs left unpaired are *added*, earlier ones *removed*.

Short lines and table rows left after passes 1 and 2 are counted as ``minor_added``
and ``minor_removed`` and never listed.

**Speed.** Scoring every remaining later paragraph against every remaining earlier one
is quadratic. Instead an inverted index maps each token to the earlier paragraphs that
contain it, and a later paragraph of ``n`` tokens is scored only against the earlier
paragraphs that share one of its ``n - ceil(t * n) + 1`` rarest tokens and whose size
is within the ratio ``t`` of its own. That is prefix filtering, and it is exact: a
pair with Jaccard similarity of at least ``t`` shares at least ``ceil(t * n)`` tokens,
so it must share one of any ``n - ceil(t * n) + 1`` of them. ``exhaustive=True``
scores all pairs instead, for tests and for measuring.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict, deque
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Literal

from ed_v13.core.change_models import (
    ChangeCounts,
    ItemChanges,
    Paragraph,
    RewordedParagraph,
    TruncatedLists,
    WordChange,
)
from ed_v13.core.documents import Document
from ed_v13.core.links import link_kind, passage_link
from ed_v13.core.text import tokenize

# Lines shorter than this are headings, bullets or page furniture: counted, never listed.
MIN_PARAGRAPH_CHARS = 60
# Token-set Jaccard similarity at or above which two paragraphs are one paragraph reworded.
# Set from reading every pair NVIDIA's 10-K and 10-Q pairs form near it: docs/filing-changes.md.
REWORD_THRESHOLD = 0.5
# At most this many paragraphs per list per Item in the record; the counts stay true.
MAX_LISTED = 40
# A line whose letters are fewer than this share of its visible characters is a table row.
TABLE_MAX_LETTER_SHARE = 0.5
# An unpunctuated line whose words start with a capital at least this often is column titles.
TITLE_ROW_CAPITAL_SHARE = 0.8
# The parser's separator between an Item heading and a sub-heading (sources/filing.py).
SUBHEADING_SEPARATOR = " › "

_EPSILON = 1e-9
_QUOTES = str.maketrans({"‘": "'", "’": "'", "′": "'", "“": '"', "”": '"', "″": '"'})
_ITEM = re.compile(r"^\s*(?:part\s+(iv|iii|ii|i)\b\W*)?item\s+(\d{1,2}[a-z]?)\b", re.IGNORECASE)
_NOT_ALNUM = re.compile(r"[^a-z0-9]+")
_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
# A date ("january 25, 2026"), then any number with its currency sign, separators and percent.
_NUMBER = re.compile(
    rf"\b(?:{_MONTHS})\s+\d{{1,2}},?\s+\d{{4}}\b"
    r"|[$€£]?(?<![a-z0-9])\d(?:[\d,.]*\d)?%?"
)
_SENTENCE_END = tuple(".!?:;")


def item_key(heading: str) -> str:
    """The key an Item is matched by across filings.

    A numbered Item is its Part (when the heading names one) and its number, so
    "Item 1A. Risk Factors" and "ITEM 1A—RISK FACTORS" meet. Any other heading is
    its own text with case and punctuation dropped.
    """
    match = _ITEM.match(heading)
    if match:
        part = (match.group(1) or "").lower()
        return f"item:{part}:{match.group(2).lower()}"
    return "heading:" + _NOT_ALNUM.sub(" ", heading.casefold()).strip()


def is_table_row(line: str) -> bool:
    """True for a line that is a row of a table rather than prose.

    Either fewer than half of its visible characters are letters; or the line does
    not close a sentence (``. ! ? : ;``) and either its last word holding a letter
    or digit holds a digit, as "Purchases of property and equipment (3,236) (1,069)"
    and "Debt securities 1,539 399 — —" do, or nearly every word starts with a
    capital, as a row of column titles does.
    """
    visible = [char for char in line if not char.isspace()]
    if not visible:
        return False
    letters = sum(char.isalpha() for char in visible)
    if letters < TABLE_MAX_LETTER_SHARE * len(visible):
        return True
    if line.rstrip().endswith(_SENTENCE_END):
        return False
    firsts = [next(c for c in word if c.isalnum()) for word in line.split() if _has_alnum(word)]
    last = next(word for word in reversed(line.split()) if _has_alnum(word))
    if any(char.isdigit() for char in last):
        return True
    capitals = sum(first.isupper() or first.isdigit() for first in firsts)
    return capitals >= TITLE_ROW_CAPITAL_SHARE * len(firsts)


def _has_alnum(word: str) -> bool:
    return any(char.isalnum() for char in word)


def similarity_tokens(text: str) -> frozenset[str]:
    """The tokens a paragraph's similarity is measured on: its word tokens, figures left out."""
    return frozenset(token for token in tokenize(text) if not token.isdigit())


def _normal(text: str) -> str:
    return " ".join(text.translate(_QUOTES).casefold().split())


def _without_numbers(normal: str) -> str:
    return _NUMBER.sub("#", normal)


def jaccard(first: frozenset[str], second: frozenset[str]) -> float:
    """Jaccard similarity of two token sets (0.0 when either is empty)."""
    if not first or not second:
        return 0.0
    shared = len(first & second)
    return shared / (len(first) + len(second) - shared)


# Pairing reworded paragraphs ------------------------------------------------------------------


def _all_pairs(
    earlier: list[frozenset[str]], later: list[frozenset[str]], threshold: float
) -> Iterator[tuple[float, int, int]]:
    for j, tokens in enumerate(later):
        for i, candidate in enumerate(earlier):
            score = jaccard(candidate, tokens)
            if score >= threshold:
                yield score, i, j


def _indexed_pairs(
    earlier: list[frozenset[str]], later: list[frozenset[str]], threshold: float
) -> Iterator[tuple[float, int, int]]:
    """The pairs :func:`_all_pairs` yields, scoring only candidates from an inverted index."""
    postings: dict[str, list[int]] = defaultdict(list)
    for i, tokens in enumerate(earlier):
        for token in tokens:
            postings[token].append(i)
    for j, tokens in enumerate(later):
        if not tokens:
            continue
        size = len(tokens)
        must_share = math.ceil(threshold * size - _EPSILON)
        rarest = sorted(tokens, key=lambda token: (len(postings.get(token, ())), token))
        candidates: set[int] = set()
        for token in rarest[: size - must_share + 1]:
            candidates.update(postings.get(token, ()))
        low, high = threshold * size - _EPSILON, size / threshold + _EPSILON
        for i in sorted(candidates):
            candidate = earlier[i]
            if low <= len(candidate) <= high:
                score = jaccard(candidate, tokens)
                if score >= threshold:
                    yield score, i, j


def pair_reworded(
    earlier: Sequence[str],
    later: Sequence[str],
    *,
    threshold: float = REWORD_THRESHOLD,
    exhaustive: bool = False,
) -> list[tuple[int, int, float]]:
    """Pairs ``(earlier index, later index, similarity)`` of paragraphs that reword each other.

    Every pair whose token-set Jaccard similarity is at least ``threshold`` is a
    candidate; candidates are taken most similar first, each paragraph at most once
    (ties broken by the two texts, then positions, so swapping the inputs swaps the
    pairs). The result is ordered by the later index. ``exhaustive`` scores every
    pair instead of using the candidate index; the result is the same.
    """
    earlier_tokens = [similarity_tokens(text) for text in earlier]
    later_tokens = [similarity_tokens(text) for text in later]
    finder = _all_pairs if exhaustive else _indexed_pairs
    scored = list(finder(earlier_tokens, later_tokens, threshold))

    def order(entry: tuple[float, int, int]) -> tuple[float, str, str, int, int]:
        score, i, j = entry
        first, second = sorted((earlier[i], later[j]))
        return (-score, first, second, min(i, j), max(i, j))

    scored.sort(key=order)
    used_earlier: set[int] = set()
    used_later: set[int] = set()
    chosen: list[tuple[int, int, float]] = []
    for score, i, j in scored:
        if i not in used_earlier and j not in used_later:
            used_earlier.add(i)
            used_later.add(j)
            chosen.append((i, j, score))
    return sorted(chosen, key=lambda pair: pair[1])


def word_changes(before: str, after: str) -> list[WordChange]:
    """The later paragraph's words against the earlier one's, as same/added/removed runs.

    Computed over the two paragraphs' whitespace-separated words only (a paragraph
    is small, so :class:`difflib.SequenceMatcher` is cheap here). A replaced run
    is given as removed words, then added words.
    """
    old, new = before.split(), after.split()
    segments: list[WordChange] = []

    def add(kind: Literal["same", "added", "removed"], words: list[str]) -> None:
        if not words:
            return
        text = " ".join(words)
        if segments and segments[-1].kind == kind:
            segments[-1] = WordChange(text=f"{segments[-1].text} {text}", kind=kind)
        else:
            segments.append(WordChange(text=text, kind=kind))

    matcher = SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            add("same", new[j1:j2])
        else:
            add("removed", old[i1:i2])
            add("added", new[j1:j2])
    return segments


# Paragraphs and Items -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Line:
    """One line of one section, where it sits in the stored text, and its comparison keys."""

    text: str
    locator: str
    start: int
    exact: str
    numbers: str
    listable: bool


@dataclass
class _Group:
    """The lines of one Item (all its sub-sections), in document order."""

    name: str
    lines: list[_Line] = field(default_factory=list)
    # Sub-headings under the Item, keyed without case, punctuation and figures, in order.
    subheadings: dict[str, str] = field(default_factory=dict)


def _section_starts(document: Document) -> list[int]:
    """Where each section's text starts in the stored text (sections are exact substrings)."""
    starts: list[int] = []
    cursor = 0
    for section in document.sections:
        found = document.text.find(f"{section.heading}\n{section.text}", cursor)
        if found >= 0:
            start = found + len(section.heading) + 1
        else:
            start = document.text.find(section.text, cursor)
            if start < 0:
                raise ValueError(f"Section {section.heading!r} is not a substring of its document")
        starts.append(start)
        cursor = start + len(section.text)
    return starts


def _groups(document: Document) -> dict[str, _Group]:
    """The document's lines grouped by Item key, Items in document order."""
    groups: dict[str, _Group] = {}
    for section, start in zip(document.sections, _section_starts(document), strict=True):
        name, _, below = section.heading.partition(SUBHEADING_SEPARATOR)
        name, below = name.strip(), below.strip()
        group = groups.setdefault(item_key(name), _Group(name=name))
        if below:
            group.subheadings.setdefault(_without_numbers(_normal(below)), below)
        offset = 0
        for text in section.text.split("\n"):
            if text.strip():
                exact = _normal(text)
                group.lines.append(
                    _Line(
                        text=text,
                        locator=section.heading,
                        start=start + offset,
                        exact=exact,
                        numbers=_without_numbers(exact),
                        listable=len(text) >= MIN_PARAGRAPH_CHARS and not is_table_row(text),
                    )
                )
            offset += len(text) + 1
    return groups


def _match_by(
    attribute: str, earlier: list[_Line], later: list[_Line]
) -> tuple[list[tuple[_Line, _Line]], list[_Line], list[_Line]]:
    """Pair lines with equal keys, in order: (the pairs, earlier left, later left)."""
    waiting: dict[str, deque[int]] = defaultdict(deque)
    for index, line in enumerate(earlier):
        waiting[getattr(line, attribute)].append(index)
    taken: set[int] = set()
    pairs: list[tuple[_Line, _Line]] = []
    later_left: list[_Line] = []
    for line in later:
        queue = waiting.get(getattr(line, attribute))
        if queue:
            index = queue.popleft()
            taken.add(index)
            pairs.append((earlier[index], line))
        else:
            later_left.append(line)
    earlier_left = [line for index, line in enumerate(earlier) if index not in taken]
    return pairs, earlier_left, later_left


def _paragraph(line: _Line, url: str) -> Paragraph:
    return Paragraph(
        text=line.text,
        locator=line.locator,
        start=line.start,
        link=passage_link(url, line.text),
        link_kind=link_kind(line.text),
    )


def _changed(
    old: _Line, new: _Line, score: float, earlier_url: str, later_url: str
) -> RewordedParagraph:
    """One earlier line and the later line matched with it, with the words that differ."""
    return RewordedParagraph(
        before=_paragraph(old, earlier_url),
        after=_paragraph(new, later_url),
        similarity=round(score, 3),
        segments=word_changes(old.text, new.text),
    )


def _compare_group(
    name: str,
    present_in: Literal["both", "earlier", "later"],
    earlier: list[_Line],
    later: list[_Line],
    *,
    earlier_url: str,
    later_url: str,
    exhaustive: bool,
    threshold: float,
    max_listed: int | None,
    earlier_headings: dict[str, str],
    later_headings: dict[str, str],
) -> ItemChanges:
    same, earlier, later = _match_by("exact", earlier, later)
    figures, earlier, later = _match_by("numbers", earlier, later)
    # A matched pair is a paragraph or a short line or table row by its later line.
    moved = [(old, new) for old, new in figures if new.listable]
    old = [line for line in earlier if line.listable]
    new = [line for line in later if line.listable]
    pairs = pair_reworded(
        [line.text for line in old],
        [line.text for line in new],
        threshold=threshold,
        exhaustive=exhaustive,
    )
    cut = slice(max_listed)  # slice(None) lists everything
    paired_old = {i for i, _, _ in pairs}
    paired_new = {j for _, j, _ in pairs}
    added = [line for j, line in enumerate(new) if j not in paired_new]
    removed = [line for i, line in enumerate(old) if i not in paired_old]

    def cut_short(count: int) -> bool:
        return max_listed is not None and count > max_listed

    return ItemChanges(
        item=name,
        present_in=present_in,
        unchanged=sum(line.listable for _, line in same),
        numbers_only=len(moved),
        reworded=len(pairs),
        added=len(added),
        removed=len(removed),
        minor_unchanged=sum(not line.listable for _, line in same),
        minor_numbers_only=len(figures) - len(moved),
        minor_added=sum(not line.listable for line in later),
        minor_removed=sum(not line.listable for line in earlier),
        added_paragraphs=[_paragraph(line, later_url) for line in added[cut]],
        removed_paragraphs=[_paragraph(line, earlier_url) for line in removed[cut]],
        reworded_paragraphs=[
            _changed(old[i], new[j], score, earlier_url, later_url) for i, j, score in pairs[cut]
        ],
        numbers_only_paragraphs=[
            _changed(
                before,
                after,
                jaccard(similarity_tokens(before.text), similarity_tokens(after.text)),
                earlier_url,
                later_url,
            )
            for before, after in moved[cut]
        ],
        subheadings_added=[
            text for key, text in later_headings.items() if key not in earlier_headings
        ],
        subheadings_removed=[
            text for key, text in earlier_headings.items() if key not in later_headings
        ],
        truncated=TruncatedLists(
            added=cut_short(len(added)),
            removed=cut_short(len(removed)),
            reworded=cut_short(len(pairs)),
            numbers_only=cut_short(len(moved)),
        ),
    )


def _item_order(earlier: list[str], later: list[str]) -> list[str]:
    """The later filing's Items, each Item only in the earlier one after its predecessor there."""
    order = list(later)
    for index, key in enumerate(earlier):
        if key in order:
            continue
        position = 0
        for previous in reversed(earlier[:index]):
            if previous in order:
                position = order.index(previous) + 1
                break
        order.insert(position, key)
    return order


def diff_documents(
    earlier: Document,
    later: Document,
    *,
    earlier_url: str,
    later_url: str,
    exhaustive: bool = False,
    threshold: float = REWORD_THRESHOLD,
    max_listed: int | None = MAX_LISTED,
) -> list[ItemChanges]:
    """What changed from ``earlier`` to ``later``, one record per Item in filing order.

    ``earlier_url`` and ``later_url`` are the filings' addresses, for each
    paragraph's link. ``exhaustive`` scores every pair of paragraphs instead of
    using the candidate index (same result; for tests and measuring). ``threshold``
    and ``max_listed`` (None lists every paragraph) are the method's two settings;
    they are parameters only so that the threshold can be reviewed
    (:func:`pairs_near_threshold`). Raises ValueError if a section is not a substring
    of its document's text.
    """
    old, new = _groups(earlier), _groups(later)
    items: list[ItemChanges] = []
    for key in _item_order(list(old), list(new)):
        before, after = old.get(key), new.get(key)
        present: Literal["both", "earlier", "later"] = (
            "both" if before and after else "earlier" if before else "later"
        )
        name = after.name if after else before.name if before else key
        items.append(
            _compare_group(
                name,
                present,
                before.lines if before else [],
                after.lines if after else [],
                earlier_url=earlier_url,
                later_url=later_url,
                exhaustive=exhaustive,
                threshold=threshold,
                max_listed=max_listed,
                earlier_headings=before.subheadings if before else {},
                later_headings=after.subheadings if after else {},
            )
        )
    return items


NearPair = tuple[str, RewordedParagraph]


def pairs_near_threshold(
    earlier: Document,
    later: Document,
    *,
    earlier_url: str,
    later_url: str,
    low: float,
    high: float,
) -> tuple[list[NearPair], list[NearPair]]:
    """The pairs to read to judge :data:`REWORD_THRESHOLD`: (just above it, just below it).

    Just above: the pairs the comparison reports as reworded with a similarity under
    ``high``. Just below: the pairs a threshold of ``low`` would add, which the
    comparison reports as one removed and one added paragraph. Each comes with its
    Item's name, in filing order, and neither list is cut. The band must straddle the
    threshold, ``0 < low < REWORD_THRESHOLD < high <= 1``, else ValueError.
    """
    if not 0 < low < REWORD_THRESHOLD < high <= 1:
        raise ValueError(
            f"the band must straddle the threshold: 0 < low < {REWORD_THRESHOLD} < high <= 1"
        )

    def pairs(threshold: float) -> list[NearPair]:
        items = diff_documents(
            earlier,
            later,
            earlier_url=earlier_url,
            later_url=later_url,
            threshold=threshold,
            max_listed=None,
        )
        return [(item.item, pair) for item in items for pair in item.reworded_paragraphs]

    def key(entry: NearPair) -> tuple[str, int, int]:
        name, pair = entry
        return (name, pair.before.start, pair.after.start)

    reported = pairs(REWORD_THRESHOLD)
    paired = {key(entry) for entry in reported}
    above = [entry for entry in reported if entry[1].similarity < high]
    below = [entry for entry in pairs(low) if key(entry) not in paired]
    return above, below


def totals(items: Sequence[ChangeCounts]) -> ChangeCounts:
    """Every count summed over ``items``."""
    return ChangeCounts(
        **{name: sum(getattr(item, name) for item in items) for name in ChangeCounts.model_fields}
    )
