"""What changed between two filings: the pure paragraph comparison (no network, no files)."""

from __future__ import annotations

import hashlib
import random
import time

import pytest

from app.core.change_models import ItemChanges, WordChange
from app.core.documents import Document, Section
from app.core.filing_diff import (
    MAX_LISTED,
    MIN_PARAGRAPH_CHARS,
    REWORD_THRESHOLD,
    diff_documents,
    is_table_row,
    item_key,
    pair_reworded,
    pairs_near_threshold,
    totals,
    word_changes,
)
from app.core.links import passage_link
from app.sources.filing import parse_filing
from tests.fakes import FY_2026, RECORDED, recorded_html

EARLIER_URL = "https://www.sec.gov/Archives/edgar/data/1/000000000125000001/old.htm"
LATER_URL = "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/new.htm"
RISK = "Item 1A. Risk Factors"
BUSINESS = "Item 1. Business"

# Risk-factor paragraphs with distinct vocabularies, each well over the minimum length.
P = [
    "We depend on third-party foundries to manufacture our semiconductor wafers, and any "
    "disruption in their capacity could delay our product shipments to customers.",
    "Competition in the accelerated computing market is intense, and rivals may introduce "
    "products with better performance or lower prices than ours.",
    "Our operations could be harmed by natural disasters, pandemics, or geopolitical conflict "
    "in regions where our suppliers and offices are located.",
    "Export controls imposed by the United States government restrict sales of certain "
    "data center products to customers in China and other countries.",
    "A significant portion of our revenue comes from a limited number of hyperscale "
    "customers, and the loss of any one could reduce our earnings materially.",
    "Security breaches of our information technology systems could expose confidential data "
    "and lead to litigation, regulatory penalties and reputational damage.",
]
NEW = (
    "Climate disclosure rules adopted by European regulators will require additional "
    "reporting about greenhouse emissions throughout our supply chain."
)


def document(*sections: tuple[str, list[str]], url: str = EARLIER_URL) -> Document:
    """A document laid out exactly as the filing parser stores one."""
    parts = [Section(heading=heading, text="\n".join(lines)) for heading, lines in sections]
    text = "\n\n".join(f"{section.heading}\n{section.text}" for section in parts)
    return Document(
        url=url,
        title="synthetic",
        publisher="SEC EDGAR",
        published_date=None,
        text=text,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        sections=parts,
    )


def diff(earlier: Document, later: Document, **kwargs) -> list[ItemChanges]:
    return diff_documents(earlier, later, earlier_url=EARLIER_URL, later_url=LATER_URL, **kwargs)


def only(items: list[ItemChanges], name: str = RISK) -> ItemChanges:
    (found,) = [item for item in items if item.item == name]
    return found


def nothing_changed(item: ItemChanges) -> bool:
    return (
        item.numbers_only
        == item.reworded
        == item.added
        == item.removed
        == item.minor_added
        == item.minor_removed
        == 0
    )


# The plan's exit check --------------------------------------------------------------------


def test_a_planted_paragraph_change_is_reported_as_added_and_removed() -> None:
    earlier = document((RISK, P))
    later = document((RISK, [P[0], P[1], P[2], NEW, P[4], P[5]]))
    item = only(diff(earlier, later))
    assert [p.text for p in item.added_paragraphs] == [NEW]
    assert [p.text for p in item.removed_paragraphs] == [P[3]]
    assert (item.added, item.removed, item.unchanged) == (1, 1, 5)
    assert (item.reworded, item.numbers_only, item.minor_added, item.minor_removed) == (0, 0, 0, 0)
    added, removed = item.added_paragraphs[0], item.removed_paragraphs[0]
    assert added.locator == removed.locator == RISK
    assert later.text[added.start : added.start + len(NEW)] == NEW
    assert earlier.text[removed.start : removed.start + len(P[3])] == P[3]
    assert added.link == passage_link(LATER_URL, NEW)
    assert removed.link == passage_link(EARLIER_URL, P[3])


# Identity and symmetry ----------------------------------------------------------------------


def test_a_document_compared_with_itself_has_nothing_changed() -> None:
    synthetic = document((BUSINESS, P[:2]), (RISK, P[2:]))
    assert all(nothing_changed(item) for item in diff(synthetic, synthetic))


def test_the_recorded_annual_report_compared_with_itself_has_nothing_changed() -> None:
    html = recorded_html(RECORDED[FY_2026.url])
    real = parse_filing(html, url=FY_2026.url, title="10-K", published_date=None)
    items = diff(real, real)
    assert len(items) > 10
    assert all(item.present_in == "both" and nothing_changed(item) for item in items)
    lines = sum(1 for section in real.sections for line in section.text.split("\n") if line)
    assert totals(items).unchanged == lines


def _rich_pair() -> tuple[Document, Document]:
    """Two documents with every kind of change: added, removed, reworded, numbers, minor."""
    reworded_before = P[1]
    reworded_after = P[1].replace("intense", "intense and increasing") + (
        " New entrants with custom silicon add to this pressure."
    )
    earlier = document(
        (BUSINESS, [P[0], "Revenue was $46.7 billion, up 56%", "Short heading"]),
        (RISK, [reworded_before, P[2], P[3], P[5]]),
        ("Item 1C. Cybersecurity", [P[4]]),
    )
    later = document(
        (BUSINESS, [P[0], "Revenue was $96.2 billion, up 106%", "Another short line"]),
        (RISK, [P[3], reworded_after, NEW, P[2]]),
        ("Item 7. Management's Discussion and Analysis", [P[5]]),
    )
    return earlier, later


def test_swapping_the_filings_swaps_added_with_removed_and_keeps_the_reworded_pairs() -> None:
    earlier, later = _rich_pair()
    forward = {item.item: item for item in diff(earlier, later)}
    backward = {
        item.item: item
        for item in diff_documents(later, earlier, earlier_url=LATER_URL, later_url=EARLIER_URL)
    }
    assert forward.keys() == backward.keys()
    flipped = {"both": "both", "earlier": "later", "later": "earlier"}
    for name, there in forward.items():
        back = backward[name]
        assert back.present_in == flipped[there.present_in]
        assert (back.added, back.removed) == (there.removed, there.added)
        assert (back.minor_added, back.minor_removed) == (there.minor_removed, there.minor_added)
        assert (back.unchanged, back.numbers_only, back.reworded) == (
            there.unchanged,
            there.numbers_only,
            there.reworded,
        )
        assert back.added_paragraphs == there.removed_paragraphs
        assert back.removed_paragraphs == there.added_paragraphs
        assert [(r.after, r.before, r.similarity) for r in back.reworded_paragraphs] == [
            (r.before, r.after, r.similarity) for r in there.reworded_paragraphs
        ]
    risk = forward[RISK]
    assert (risk.reworded, risk.added, risk.removed) == (1, 1, 1)


# Numbers, rewording and moves ---------------------------------------------------------------


def test_a_paragraph_whose_numbers_alone_changed_is_numbers_only() -> None:
    long_before = (
        "Revenue for fiscal year 2025 was $130.5 billion, up 114% from a year ago, as of "
        "January 26, 2025, driven by Data Center."
    )
    long_after = (
        "Revenue for fiscal year 2026 was $215.9 billion, up 65% from a year ago, as of "
        "January 25, 2026, driven by Data Center."
    )
    earlier = document((RISK, ["Revenue was $46.7 billion, up 56%", long_before]))
    later = document((RISK, ["Revenue was $96.2 billion, up 106%", long_after]))
    item = only(diff(earlier, later))
    assert item.numbers_only == 2
    assert (item.reworded, item.added, item.removed, item.minor_added, item.minor_removed) == (
        0,
        0,
        0,
        0,
        0,
    )


def test_a_sentence_appended_to_a_paragraph_is_reworded_and_only_its_words_are_marked() -> None:
    appended = "Shortages of advanced packaging capacity may also limit our supply next year."
    earlier = document((RISK, [P[0], P[2]]))
    later = document((RISK, [P[0] + " " + appended, P[2]]))
    item = only(diff(earlier, later))
    assert (item.reworded, item.added, item.removed, item.unchanged) == (1, 0, 0, 1)
    (pair,) = item.reworded_paragraphs
    assert pair.before.text == P[0]
    assert pair.after.text == P[0] + " " + appended
    assert REWORD_THRESHOLD <= pair.similarity < 1.0
    assert pair.segments == [
        WordChange(text=P[0], kind="same"),
        WordChange(text=appended, kind="added"),
    ]


def test_new_figures_do_not_count_against_a_reworded_paragraph() -> None:
    # Words: 9 of 10 distinct stems shared. Counting the five changed figures as words too
    # would give 9 of 20, below the threshold, and report one paragraph added and one removed.
    before = (
        "In fiscal year 2025 we repurchased 310 million shares for $33.7 billion and paid "
        "$834 million in dividends to shareholders."
    )
    after = (
        "In fiscal year 2026 we repurchased 282 million shares for $40.1 billion and paid "
        "$974 million in cash dividends to our shareholders."
    )
    item = only(diff(document((RISK, [before])), document((RISK, [after]))))
    assert (item.reworded, item.added, item.removed, item.numbers_only) == (1, 0, 0, 0)
    assert item.reworded_paragraphs[0].similarity == 0.9


def test_paragraphs_sharing_half_their_words_are_reworded_and_fewer_are_not() -> None:
    assert REWORD_THRESHOLD == 0.5
    base = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike"
    half = "alpha bravo charlie delta echo foxtrot golf hotel india xray yankee zulu oscar"
    less = "alpha bravo charlie delta echo foxtrot golf hotel xray yankee zulu oscar papa"
    assert [score for _, _, score in pair_reworded([base], [half])] == [9 / 17]
    assert pair_reworded([base], [less]) == []


# Reviewing the threshold: the pairs a person should read ----------------------------------

# Three pairs of paragraphs with vocabularies of their own: X shares 9 of 17 words (0.529,
# just above the threshold), Y 8 of 18 (0.444, just below), Z 12 of 14 (0.857, far above).
X_BEFORE = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike"
X_AFTER = "alpha bravo charlie delta echo foxtrot golf hotel india xray yankee zulu oscar"
Y_BEFORE = "amber birch cedar daisy elder fern grape hazel iris jasmine kale lilac maple"
Y_AFTER = "amber birch cedar daisy elder fern grape hazel onion pansy quince rose sage"
Z_BEFORE = "anchor barge canoe dinghy ferry galley harbor jetty keel lagoon mast nautical oar"
Z_AFTER = "anchor barge canoe dinghy ferry galley harbor jetty keel lagoon mast nautical paddle"


def test_a_lower_threshold_pairs_what_the_default_reports_as_removed_and_added() -> None:
    earlier, later = document((RISK, [Y_BEFORE])), document((RISK, [Y_AFTER]))
    default = only(diff(earlier, later))
    assert (default.reworded, default.added, default.removed) == (0, 1, 1)
    lower = only(diff(earlier, later, threshold=0.4))
    assert (lower.reworded, lower.added, lower.removed) == (1, 0, 0)
    assert lower.reworded_paragraphs[0].similarity == round(8 / 18, 3)


def test_every_paragraph_is_listed_when_the_cap_is_lifted() -> None:
    fresh = [f"{NEW} Paragraph {chr(65 + n % 26)}{chr(97 + n // 26)} of many." for n in range(45)]
    later = document((RISK, [P[0], *fresh]))
    item = only(diff(document((RISK, [P[0]])), later, max_listed=None))
    assert item.added == len(item.added_paragraphs) == 45
    assert not item.truncated.added


def near(earlier: Document, later: Document, low: float, high: float):
    return pairs_near_threshold(
        earlier, later, earlier_url=EARLIER_URL, later_url=LATER_URL, low=low, high=high
    )


def test_the_pairs_to_read_are_those_just_above_the_threshold_and_those_just_below() -> None:
    earlier = document((RISK, [X_BEFORE, Y_BEFORE, Z_BEFORE, P[0]]))
    later = document((RISK, [X_AFTER, Y_AFTER, Z_AFTER, P[1]]))
    above, below = near(earlier, later, 0.4, 0.6)
    assert [(name, p.before.text, p.after.text, p.similarity) for name, p in above] == [
        (RISK, X_BEFORE, X_AFTER, round(9 / 17, 3))
    ]
    assert [(name, p.before.text, p.after.text, p.similarity) for name, p in below] == [
        (RISK, Y_BEFORE, Y_AFTER, round(8 / 18, 3))
    ]
    # The comparison itself is untouched: Y is still one removed and one added paragraph.
    item = only(diff(earlier, later))
    assert (item.reworded, item.added, item.removed) == (2, 2, 2)


def test_the_pairs_to_read_are_not_cut_at_the_list_cap() -> None:
    count = MAX_LISTED + 5
    stems = [f"{chr(97 + n // 26)}{chr(97 + n % 26)}" for n in range(count)]
    before = [" ".join(f"{stem}{word}" for word in X_BEFORE.split()) for stem in stems]
    after = [" ".join(f"{stem}{word}" for word in X_AFTER.split()) for stem in stems]
    above, below = near(document((RISK, before)), document((RISK, after)), 0.4, 0.6)
    assert len(above) == count and below == []


@pytest.mark.parametrize(
    ("low", "high"), [(0.5, 0.6), (0.0, 0.6), (-0.1, 0.6), (0.4, 0.5), (0.6, 0.7), (0.4, 1.01)]
)
def test_the_band_must_straddle_the_threshold(low: float, high: float) -> None:
    filing = document((RISK, [P[0]]))
    with pytest.raises(ValueError, match="threshold"):
        near(filing, filing, low, high)


def test_word_changes_mark_a_replaced_word_as_removed_then_added() -> None:
    assert word_changes("supply is tight this year", "supply is ample this year") == [
        WordChange(text="supply is", kind="same"),
        WordChange(text="tight", kind="removed"),
        WordChange(text="ample", kind="added"),
        WordChange(text="this year", kind="same"),
    ]


def test_reordering_paragraphs_inside_an_item_changes_nothing() -> None:
    earlier = document((RISK, P))
    later = document((RISK, list(reversed(P))))
    item = only(diff(earlier, later))
    assert item.unchanged == len(P)
    assert nothing_changed(item)


def test_moving_a_paragraph_between_sub_headings_of_one_item_changes_nothing() -> None:
    first, second = f"{RISK} › Risks Related to Supply", f"{RISK} › Risks Related to Regulation"
    earlier = document((first, P[:3]), (second, P[3:]))
    later = document((first, P[:2]), (second, [P[2], *P[3:]]))
    (item,) = diff(earlier, later)
    assert item.item == RISK
    assert item.unchanged == len(P) and nothing_changed(item)


def test_a_duplicated_paragraph_dropped_once_is_one_removal() -> None:
    earlier = document((RISK, [P[0], P[0], P[1]]))
    later = document((RISK, [P[0], P[1]]))
    item = only(diff(earlier, later))
    assert (item.unchanged, item.removed, item.added) == (2, 1, 0)


# Items ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Item 1A. Risk Factors", "ITEM 1A—RISK FACTORS"),
        ("Item 1A. Risk Factors", "Item 1A: Risk factors (continued)"),
        ("Part II, Item 1A. Risk Factors", "PART II — ITEM 1A. RISK FACTORS"),
        ("Cover page", "COVER PAGE"),
    ],
)
def test_item_keys_ignore_case_punctuation_and_title(first: str, second: str) -> None:
    assert item_key(first) == item_key(second)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Item 1A. Risk Factors", "Item 1B. Unresolved Staff Comments"),
        ("Part I, Item 1A. Risk Factors", "Part II, Item 1A. Risk Factors"),
        ("Item 1. Business", "Item 10. Directors"),
        ("Cover page", "Unnumbered text"),
    ],
)
def test_different_items_have_different_keys(first: str, second: str) -> None:
    assert item_key(first) != item_key(second)


def test_items_are_matched_across_heading_styles() -> None:
    earlier = document(("Item 1A. Risk Factors", P))
    later = document(("ITEM 1A—RISK FACTORS", P))
    (item,) = diff(earlier, later)
    assert (item.item, item.present_in, item.unchanged) == ("ITEM 1A—RISK FACTORS", "both", 6)


def test_an_item_in_one_filing_only_is_all_added_or_all_removed_and_keeps_filing_order() -> None:
    earlier, later = _rich_pair()
    items = diff(earlier, later)
    assert [(item.item, item.present_in) for item in items] == [
        (BUSINESS, "both"),
        (RISK, "both"),
        ("Item 1C. Cybersecurity", "earlier"),  # after the Item that preceded it there
        ("Item 7. Management's Discussion and Analysis", "later"),
    ]
    gone = only(items, "Item 1C. Cybersecurity")
    assert ([p.text for p in gone.removed_paragraphs], gone.added, gone.unchanged) == ([P[4]], 0, 0)
    new = only(items, "Item 7. Management's Discussion and Analysis")
    assert ([p.text for p in new.added_paragraphs], new.removed) == ([P[5]], 0)


def test_cover_page_and_unnumbered_text_are_compared_as_their_own_groups() -> None:
    earlier = document(("Cover page", [P[0]]), ("Unnumbered text", [P[1]]), (RISK, [P[2]]))
    later = document(("Cover page", [P[0]]), ("Unnumbered text", [NEW]), (RISK, [P[2]]))
    items = diff(earlier, later)
    assert [item.item for item in items] == ["Cover page", "Unnumbered text", RISK]
    unnumbered = only(items, "Unnumbered text")
    assert (unnumbered.added, unnumbered.removed) == (1, 1)
    assert nothing_changed(only(items, "Cover page")) and nothing_changed(only(items, RISK))


# What is listed ------------------------------------------------------------------------------


def test_every_listed_paragraph_is_an_exact_span_of_its_filing() -> None:
    earlier, later = _rich_pair()
    for item in diff(earlier, later):
        listed = [(later, p) for p in item.added_paragraphs]
        listed += [(earlier, p) for p in item.removed_paragraphs]
        for pair in item.reworded_paragraphs:
            listed += [(earlier, pair.before), (later, pair.after)]
        for source, paragraph in listed:
            assert source.text[paragraph.start : paragraph.start + len(paragraph.text)] == (
                paragraph.text
            )
            assert paragraph.locator in source.text[: paragraph.start]


@pytest.mark.parametrize(
    "line",
    [
        "Revenue $ 130,497 $ 60,922 114%",
        "Purchases related to property and equipment and intangible assets (3,236) (1,069) (815)",
        "Total 2,345 1,234 987 654 321 100",
        # From NVIDIA's 10-Q: a row whose last cells are dashes, and a row of column titles.
        "Debt securities issued by U.S. government agencies 1,539 399 1,140 — —",
        "Common Stock Outstanding Additional Paid-in Capital Accumulated Other Comprehensive "
        "Income (Loss) Retained Earnings Total Shareholders’ Equity",
    ],
)
def test_rows_of_figures_are_table_rows(line: str) -> None:
    assert is_table_row(line)


@pytest.mark.parametrize(
    "line",
    [
        P[0],
        "Revenue was $96.2 billion, up 106% from a year ago.",
        "•our customers’ and partners’ ability to secure capital and energy and to build complex "
        "datacenter infrastructure timely; and",
    ],
)
def test_prose_is_not_a_table_row(line: str) -> None:
    assert not is_table_row(line)


def test_short_lines_and_table_rows_are_counted_but_never_listed() -> None:
    long_row = (
        "Purchases related to property and equipment and intangible assets (3,236) (1,069) (815)"
    )
    assert len(long_row) >= MIN_PARAGRAPH_CHARS
    earlier = document((RISK, [P[0], "Old short heading", "Gross margin 75.0% 72.7% 56.9%"]))
    later = document((RISK, [P[0], "New short heading", long_row, "Totals 1 2 3 4 5 6 7"]))
    item = only(diff(earlier, later))
    assert (item.minor_added, item.minor_removed) == (3, 2)
    assert (item.added, item.removed, item.reworded) == (0, 0, 0)
    assert item.added_paragraphs == item.removed_paragraphs == item.reworded_paragraphs == []


def test_lists_are_capped_with_true_counts_and_a_flag() -> None:
    # Distinct paragraphs in the later filing only, so only the cap limits the list.
    fresh = [f"{NEW} Paragraph {chr(65 + n % 26)}{chr(97 + n // 26)} of many." for n in range(45)]
    item = only(diff(document((RISK, [P[0]])), document((RISK, [P[0], *fresh]))))
    assert item.added == 45
    assert len(item.added_paragraphs) == MAX_LISTED == 40
    assert [p.text for p in item.added_paragraphs] == fresh[:40]
    assert item.truncated.added and not item.truncated.removed and not item.truncated.reworded


def test_totals_add_up_every_item() -> None:
    earlier, later = _rich_pair()
    items = diff(earlier, later)
    total = totals(items)
    assert total.added == sum(item.added for item in items)
    assert total.unchanged == sum(item.unchanged for item in items)
    assert total.minor_removed == sum(item.minor_removed for item in items)


# Speed: the candidate index gives the all-pairs result, in linear time -----------------------

SYLLABLES = [c + v for c in "bdfgklmnprstvz" for v in "aeiou"]


def _words(rng: random.Random, count: int) -> list[str]:
    """``count`` distinct made-up alphabetic words (no digits, so no number placeholders)."""
    seen: dict[str, None] = {}
    while len(seen) < count:
        seen["".join(rng.choice(SYLLABLES) for _ in range(rng.randint(2, 4)))] = None
    return list(seen)


def _mutate(rng: random.Random, words: list[str], vocabulary: list[str], share: float) -> list[str]:
    out = [rng.choice(vocabulary) if rng.random() < share else word for word in words]
    if rng.random() < 0.5:
        out += [rng.choice(vocabulary) for _ in range(rng.randint(1, 6))]
    return out


def _synthetic_pair(paragraphs: int, seed: int) -> tuple[Document, Document]:
    """Two related documents whose paragraphs sit near the rewording threshold.

    Families of near-duplicate paragraphs compete for the same partner, so the
    order in which pairs are taken matters; the vocabulary grows with the document,
    as a real filing's does.
    """
    rng = random.Random(seed)
    vocabulary = _words(rng, 12 * paragraphs)
    common = vocabulary[:60]
    earlier_lines: list[str] = []
    later_lines: list[str] = []
    for _ in range(paragraphs // 3):
        base = [rng.choice(vocabulary if rng.random() < 0.7 else common) for _ in range(30)]
        family = [base, _mutate(rng, base, vocabulary, 0.15), _mutate(rng, base, vocabulary, 0.3)]
        for words in family:
            if rng.random() < 0.9:
                earlier_lines.append(" ".join(words) + ".")
            if rng.random() < 0.9:
                share = rng.choice((0.0, 0.1, 0.2, 0.3, 0.45, 0.7))
                later_lines.append(" ".join(_mutate(rng, words, vocabulary, share)) + ".")
    rng.shuffle(later_lines)
    return document((RISK, earlier_lines)), document((RISK, later_lines), url=LATER_URL)


def test_the_candidate_index_finds_exactly_the_all_pairs_result() -> None:
    earlier, later = _synthetic_pair(300, seed=7)
    indexed = diff(earlier, later)
    exhaustive = diff(earlier, later, exhaustive=True)
    assert indexed == exhaustive
    item = only(indexed)
    assert item.reworded > 30 and item.added > 10 and item.removed > 10
    earlier_texts = earlier.sections[0].text.split("\n")
    later_texts = later.sections[0].text.split("\n")
    assert pair_reworded(earlier_texts, later_texts) == pair_reworded(
        earlier_texts, later_texts, exhaustive=True
    )


def _best_seconds(earlier: Document, later: Document, repeats: int = 5) -> float:
    timings = []
    for _ in range(repeats):
        began = time.perf_counter()
        diff(earlier, later)
        timings.append(time.perf_counter() - began)
    return min(timings)


def test_the_comparison_scales_linearly_with_the_document() -> None:
    # A ratio of two timings on the same machine, not a wall-clock bound: twice the paragraphs
    # cost about twice as much when matching is linear, four times when it is all-pairs. Three
    # sits between the two; the best of five runs each removes most scheduling noise.
    small = _best_seconds(*_synthetic_pair(900, seed=1))
    large = _best_seconds(*_synthetic_pair(1800, seed=1))
    assert large < 3 * small, f"twice the paragraphs took {large / small:.1f}x as long"
