"""Links that open a source page scrolled to, and highlighting, one excerpt.

Uses URL Text Fragments (``#:~:text=start,end``; WICG, *Text Fragments*), which
current browsers support. Pure: no network, no I/O.

What a link can and cannot do, by :func:`link_kind`:

- ``"passage"``: a one-line prose excerpt. The fragment names it whole (ten
  words or fewer) or by its first and last five words.
- ``"first-line"``: an excerpt that spans lines. A text fragment does not match
  across block boundaries (paragraphs, list items, table cells), so the link
  names the first non-empty line only and the page opens at the start of the
  excerpt, not over all of it.
- ``"document"``: a table row, or nothing to link by. The stored row is the
  parser's rendering of the table: cells are flattened into one line and a
  lone "$", "%" or ")" is joined to its neighbour, so its text is not the
  page's text and a fragment would not match. The link is the plain URL.

Not handled: a fragment matches the *first* occurrence of its words, and no
prefix or suffix is given, so an excerpt whose opening five words (or whole
text, when short) also appear earlier on the page opens at that earlier spot.
A row that is one label and one figure ("Revenue $46,743") reads as prose and
gets a fragment that may not match. None of this has been checked in a browser.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import quote, urlsplit, urlunsplit

LinkKind = Literal["passage", "first-line", "document"]

FRAGMENT_DIRECTIVE = ":~:text="
# Above this many words the fragment names the first and last few instead of the whole text.
WHOLE_EXCERPT_MAX_WORDS = 10
EDGE_WORDS = 5
# A line is a table row when more than this share of its visible characters are figure
# characters (the same half-way line as app.core.filing_diff.is_table_row's letter share).
TABLE_FIGURE_SHARE = 0.5
FIGURE_CHARACTERS = frozenset("0123456789$%(),.-−–")


def _encode(text: str) -> str:
    """Percent-encode one text-fragment term.

    ``quote`` with no safe characters still leaves ``-`` alone; the Text
    Fragments syntax gives ``-`` (and ``,`` and ``&``) a meaning, so it is
    encoded explicitly.
    """
    return quote(text, safe="").replace("-", "%2D")


def _figure_token(token: str) -> bool:
    """True for a token made only of figure characters: "$41,096", "(3,236)", "34%", "$"."""
    return all(char in FIGURE_CHARACTERS for char in token)


def is_table_row(line: str) -> bool:
    """True for a line that reads as a row of figures rather than prose.

    Either more than half of its visible characters are digits or one of
    ``$ % ( ) , . -``, or two figure tokens stand side by side, as the cells
    of "Purchases of property and equipment (3,236) (1,069)" do. Prose
    separates its numbers with words.
    """
    visible = [char for char in line if not char.isspace()]
    if not visible:
        return False
    figures = sum(char in FIGURE_CHARACTERS for char in visible)
    if figures > TABLE_FIGURE_SHARE * len(visible):
        return True
    tokens = line.split()
    return any(
        _figure_token(left) and _figure_token(right) and any(c.isdigit() for c in left + right)
        for left, right in zip(tokens, tokens[1:], strict=False)
    )


def _first_line(excerpt: str) -> str:
    """The first line of ``excerpt`` that has any text, or "" when none does."""
    return next((line for line in excerpt.splitlines() if line.strip()), "")


def link_kind(excerpt: str) -> LinkKind:
    """What a link built by :func:`passage_link` for ``excerpt`` opens.

    ``"passage"`` for one line of prose, ``"first-line"`` for prose over several
    lines (the link names the first), ``"document"`` for a table row or an
    empty excerpt (the plain URL). A view can say so in words beside the link.
    """
    first = _first_line(excerpt)
    if not first or is_table_row(first):
        return "document"
    lines = [line for line in excerpt.splitlines() if line.strip()]
    return "first-line" if len(lines) > 1 else "passage"


def passage_link(url: str, excerpt: str) -> str:
    """Return ``url`` with a text fragment that opens the page at ``excerpt``.

    The fragment is built from the excerpt's first non-empty line
    (:func:`link_kind`); a line of ten words or fewer is matched whole, a longer
    one by its first and last five words. A table row or an empty excerpt gets
    ``url`` with no fragment. Any existing fragment on ``url`` is replaced, and
    URLs that are not ``http`` or ``https`` are returned unchanged.
    """
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https"):
        return url
    if link_kind(excerpt) == "document":
        return url
    words = _first_line(excerpt).split()
    if len(words) <= WHOLE_EXCERPT_MAX_WORDS:
        directive = _encode(" ".join(words))
    else:
        start = _encode(" ".join(words[:EDGE_WORDS]))
        end = _encode(" ".join(words[-EDGE_WORDS:]))
        directive = f"{start},{end}"
    return urlunsplit(parts._replace(fragment=FRAGMENT_DIRECTIVE + directive))
