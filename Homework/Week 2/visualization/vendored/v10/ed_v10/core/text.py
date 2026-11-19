"""Word tokens and sentence spans, shared by passage retrieval and the extractive engine.

Pure functions, no state. :func:`tokenize` lower-cases, drops stop words and
strips plural and common verb endings so "customers" and "customer", or
"restricted" and "restrict", match. :func:`sentence_spans` never rewrites the
text: every span it returns is an exact slice of its input, which is what lets
a quoted sentence be verified against the stored filing.
"""

from __future__ import annotations

import re

STOPWORDS: frozenset[str] = frozenset(
    """
    a about above after again against all also am an and any are as at be because been
    before being below between both but by can could did do does doing down during each
    few for from further had has have having he her here hers herself him himself his how
    i if in into is it its itself just may me might more most must my myself no nor not
    now of off on once only or other our ours ourselves out over own same shall she should
    so some such than that the their theirs them themselves then there these they this
    those through to too under until up upon very was we were what when where whether which
    while who whom why will with within without would you your yours yourself yourselves
    """.split()
)

_WORD = re.compile(r"[a-z0-9]+")
_LINE = re.compile(r"[^\n]+")
# Sentence-ending punctuation, any closing quotes or brackets, then whitespace or line end.
_BOUNDARY = re.compile(r"[.!?]+[\"'”’)\]]*(?=\s|$)")
# "U.S", "F", "U.K": single letters joined by periods, the word before an initialism's dot.
_INITIALISM = re.compile(r"(?:[A-Za-z]\.)*[A-Za-z]")
_NO_UNDOUBLE = frozenset("aeiouslz")


def _undouble(word: str) -> str:
    """'plann' -> 'plan', 'stopp' -> 'stop'; 'sell' and 'pass' keep their double letter."""
    if len(word) >= 4 and word[-1] == word[-2] and word[-1] not in _NO_UNDOUBLE:
        return word[:-1]
    return word


def _stem(word: str) -> str:
    """Strip a plural, then a verb ending, then a final 'e', from an alphabetic word.

    Deliberately light (not Porter): it only has to make the common inflections
    of a filing's vocabulary meet. Words of three letters or fewer and words
    containing digits are returned unchanged.
    """
    if len(word) <= 3 or not word.isalpha():
        return word
    if word.endswith("ies") and len(word) > 4:
        word = word[:-3] + "y"
    elif word.endswith("sses"):
        word = word[:-2]
    elif word.endswith("s") and not word.endswith(("ss", "us", "is")):
        word = word[:-1]
    if word.endswith("ied") and len(word) > 4:
        word = word[:-3] + "y"
    elif word.endswith("ing") and len(word) >= 6:
        word = _undouble(word[:-3])
    elif word.endswith("ed") and not word.endswith("eed") and len(word) >= 5:
        word = _undouble(word[:-2])
    if word.endswith("e") and len(word) >= 4:
        word = word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    """Lower-cased, stemmed word tokens of ``text`` in order, stop words removed.

    A token is a run of ASCII letters and digits, so "10" and "H20" survive as
    "10" and "h20". Single letters are dropped with the stop words.
    """
    tokens: list[str] = []
    for word in _WORD.findall(text.lower()):
        if word in STOPWORDS or (len(word) == 1 and word.isalpha()):
            continue
        tokens.append(_stem(word))
    return tokens


def _is_initialism(line: str, match: re.Match[str]) -> bool:
    """True when a bare period ends an initialism such as "U.S." rather than a sentence."""
    if match.group() != ".":
        return False
    word_start = max(line.rfind(" ", 0, match.start()), line.rfind("\t", 0, match.start())) + 1
    return _INITIALISM.fullmatch(line, word_start, match.start()) is not None


def _append_stripped(spans: list[tuple[int, int]], text: str, start: int, end: int) -> None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start < end:
        spans.append((start, end))


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """``(start, end)`` offsets of each sentence of ``text``, in order.

    A sentence ends at ``.``, ``!`` or ``?`` (plus any closing quotes) followed by
    whitespace, and at every line break. Spans exclude surrounding whitespace and
    never overlap; together they cover every non-whitespace character.
    """
    spans: list[tuple[int, int]] = []
    for line_match in _LINE.finditer(text):
        offset = line_match.start()
        line = line_match.group()
        segment_start = 0
        for boundary in _BOUNDARY.finditer(line):
            if _is_initialism(line, boundary):
                continue
            _append_stripped(spans, text, offset + segment_start, offset + boundary.end())
            segment_start = boundary.end()
        _append_stripped(spans, text, offset + segment_start, offset + len(line))
    return spans


def sentences(text: str) -> list[str]:
    """The sentences of ``text`` as exact substrings; see :func:`sentence_spans`."""
    return [text[start:end] for start, end in sentence_spans(text)]
