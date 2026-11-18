"""Links that open a source page scrolled to, and highlighting, one excerpt.

Uses URL Text Fragments (``#:~:text=start,end``; WICG, *Text Fragments*), which
current browsers support. Pure: no network, no I/O.
"""

from __future__ import annotations

from urllib.parse import quote, urlsplit, urlunsplit

FRAGMENT_DIRECTIVE = ":~:text="
# Above this many words the fragment names the first and last few instead of the whole text.
WHOLE_EXCERPT_MAX_WORDS = 10
EDGE_WORDS = 5


def _encode(text: str) -> str:
    """Percent-encode one text-fragment term.

    ``quote`` with no safe characters still leaves ``-`` alone; the Text
    Fragments syntax gives ``-`` (and ``,`` and ``&``) a meaning, so it is
    encoded explicitly.
    """
    return quote(text, safe="").replace("-", "%2D")


def passage_link(url: str, excerpt: str) -> str:
    """Return ``url`` with a text fragment that opens the page at ``excerpt``.

    Excerpts of ten words or fewer are matched whole; longer ones by their
    first and last five words. Any existing fragment on ``url`` is replaced.
    URLs that are not ``http`` or ``https``, and empty excerpts, return ``url``
    unchanged.
    """
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https"):
        return url
    words = excerpt.split()
    if not words:
        return url
    if len(words) <= WHOLE_EXCERPT_MAX_WORDS:
        directive = _encode(" ".join(words))
    else:
        start = _encode(" ".join(words[:EDGE_WORDS]))
        end = _encode(" ".join(words[-EDGE_WORDS:]))
        directive = f"{start},{end}"
    return urlunsplit(parts._replace(fragment=FRAGMENT_DIRECTIVE + directive))
