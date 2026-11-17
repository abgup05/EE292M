"""Tokenizer and sentence splitter shared by retrieval and the extractive engine."""

import random

import pytest

from app.core.text import STOPWORDS, sentence_spans, sentences, tokenize


def test_tokens_are_lower_case_words_without_stopwords() -> None:
    assert tokenize("The Company AND its Revenue") == ["company", "revenu"]
    assert "the" in STOPWORDS and "and" in STOPWORDS


@pytest.mark.parametrize(
    "family",
    [
        ("customers", "customer", "Customers"),
        ("restricted", "restricting", "restrict", "restricts"),
        ("growing", "grows", "grow"),
        ("companies", "company"),
        ("increase", "increased", "increasing", "increases"),
        ("planned", "planning", "plan", "plans"),
        ("exceeded", "exceed", "exceeds"),
    ],
)
def test_inflections_share_a_token(family: tuple[str, ...]) -> None:
    stems = {tuple(tokenize(word)) for word in family}
    assert len(stems) == 1, stems
    assert len(next(iter(stems))) == 1


def test_numbers_and_alphanumeric_tokens_are_kept() -> None:
    assert tokenize("10 H20 chips in fiscal 2026") == ["10", "h20", "chip", "fiscal", "2026"]


def test_words_that_only_look_plural_are_not_damaged() -> None:
    assert tokenize("status analysis process") == ["status", "analysis", "process"]


def test_empty_and_punctuation_only_text() -> None:
    assert tokenize("") == []
    assert tokenize("... -- !!") == []


def test_sentences_split_on_punctuation_and_line_breaks() -> None:
    text = "Revenue grew 56%. Data Center led!\nCustomers  are concentrated? Yes\n\n  Tail line  "
    assert sentences(text) == [
        "Revenue grew 56%.",
        "Data Center led!",
        "Customers  are concentrated?",
        "Yes",
        "Tail line",
    ]


def test_sentences_keep_decimals_and_closing_quotes_together() -> None:
    text = 'Margins were 1.5 points lower. He said "it ended." Then it resumed.'
    assert sentences(text) == [
        "Margins were 1.5 points lower.",
        'He said "it ended."',
        "Then it resumed.",
    ]


def test_sentences_do_not_split_initialisms() -> None:
    text = "Sales to the U.S. government rose. Exports fell."
    assert sentences(text) == ["Sales to the U.S. government rose.", "Exports fell."]


def test_sentence_spans_are_exact_substrings_in_order_on_random_text() -> None:
    rng = random.Random(7)
    alphabet = ["word", "U.S.", "1.5", ".", "!", "?", " ", "  ", "\n", '"', "end."]
    for _ in range(300):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        spans = sentence_spans(text)
        previous_end = 0
        for start, end in spans:
            assert previous_end <= start < end <= len(text)
            piece = text[start:end]
            assert piece == piece.strip() and piece
            previous_end = end
        assert sentences(text) == [text[s:e] for s, e in spans]
        covered = "".join(text[s:e] for s, e in spans)
        assert "".join(text.split()) == "".join(covered.split())
