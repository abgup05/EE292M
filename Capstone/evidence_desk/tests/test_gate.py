"""The citation gate: quotes are located in stored text, and only located spans survive."""

import random
import re
import time

import pytest

from app.core import limits
from app.core.documents import Passage
from app.core.gate import GateResult, IdMinter, RunIds, StoredSource, TextIndex, gate_claim, locate
from app.core.metric_models import Metric
from app.core.models import Confidence, Stance
from app.core.ports import ClaimDraft, FindingDraft, Quote

RISK = (
    "Item 1A. Risk Factors\n"
    "Our revenue is concentrated: a limited number of customers account for a significant "
    "share of our revenue, and the loss of any of them could harm our business.\n"
    "The company’s “Data Center” segment depends on a small set of suppliers — chiefly one "
    "foundry — for its wafers.\n"
)
MDNA = (
    "Item 2. Management's Discussion and Analysis\n"
    "Data Center revenue was $41.1 billion, up 56% from a year ago, driven by demand for "
    "accelerated computing platforms.\n"
)
URL_1 = "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm"
URL_2 = "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000052/nvda-20260426.htm"


def _passage(pid: str, source_id: str, text: str, locator: str) -> Passage:
    return Passage(id=pid, source_id=source_id, locator=locator, text=text, start=0)


SOURCES = {"s1": StoredSource(text=RISK, url=URL_1), "s2": StoredSource(text=MDNA, url=URL_2)}
PASSAGES = {
    "p1": _passage("p1", "s1", RISK, "Part II, Item 1A. Risk Factors"),
    "p2": _passage("p2", "s2", MDNA, "Part I, Item 2. Management's Discussion and Analysis"),
}


def _finding(*quotes: tuple[str, str], stance: Stance = Stance.supports) -> FindingDraft:
    return FindingDraft(
        statement="Revenue is concentrated in a few customers.",
        stance=stance,
        quotes=[Quote(passage_id=pid, text=text) for pid, text in quotes],
        confidence=Confidence.high,
        rationale="The filing says so.",
    )


def _gate(*findings: FindingDraft, ids: RunIds | None = None) -> GateResult:
    return gate_claim(
        claim_id="c1",
        draft=ClaimDraft(findings=list(findings)),
        passages=PASSAGES,
        sources=SOURCES,
        ids=ids or RunIds(),
    )


def _normalised(text: str) -> str:
    folded = text.translate(str.maketrans("‘’“”–—−", "''\"\"---")).replace("…", "...")
    return re.sub(r"\s+", " ", folded).strip()


def _assert_identity(result: GateResult) -> None:
    for item in result.evidence:
        stored = SOURCES[item.source_id].text
        assert stored[item.start : item.start + len(item.excerpt)] == item.excerpt


# locate -------------------------------------------------------------------------------------


def test_locate_exact_match() -> None:
    quote = "a limited number of customers account for a significant share"
    start, end = locate(quote, RISK)
    assert RISK[start:end] == quote


def test_locate_ignores_quote_padding() -> None:
    quote = "a limited number of customers"
    start, end = locate(f"  {quote}\n", RISK)
    assert RISK[start:end] == quote


def test_locate_line_breaks_for_spaces_returns_stored_span() -> None:
    quote = "a limited number of customers account for a significant share"
    start, end = locate(quote.replace(" ", "\n"), RISK)
    assert RISK[start:end] == quote


def test_locate_straight_quotes_and_dashes_match_typographic_source() -> None:
    quote = 'The company\'s "Data Center" segment depends on a small set of suppliers - chiefly'
    span = locate(quote, RISK)
    assert span is not None
    assert RISK[span[0] : span[1]] == (
        "The company’s “Data Center” segment depends on a small set of suppliers — chiefly"
    )


def test_locate_folds_typographic_quote_against_plain_source() -> None:
    text = "Management's view is that demand... remains strong."
    span = locate("Management’s view is that demand… remains strong", text)
    assert span is not None
    assert text[span[0] : span[1]] == "Management's view is that demand... remains strong"


def test_locate_collapses_non_breaking_and_repeated_whitespace_in_source() -> None:
    text = "Revenue grew\n\n  56%   from a year ago."
    span = locate("Revenue grew 56% from a year ago.", text)
    assert span == (0, len(text))


def test_locate_with_a_changed_word_is_not_found() -> None:
    assert locate("a limited number of suppliers account for a significant share", RISK) is None


def test_locate_empty_quote_is_not_found() -> None:
    assert locate("   ", RISK) is None


def test_locate_start_prefers_a_later_occurrence() -> None:
    text = "Risk Factors\nsee below\nRisk Factors\nthe body"
    index = TextIndex(text)
    assert index.locate("Risk Factors") == (0, 12)
    assert index.locate("Risk Factors", start=5) == (23, 35)
    assert index.locate("Risk\nFactors the", start=5) == (23, 39)
    assert index.locate("Risk\nFactors see") == (0, len("Risk Factors\nsee"))


def test_locate_does_not_match_inside_a_folded_ellipsis() -> None:
    # ".. here" must not start inside the single character "…" (folded to "...").
    text = "wait… here, then also.. here"
    span = locate("..\nhere", text)
    assert span == (text.index("also") + 4, len(text))


def test_locate_random_substrings_round_trip() -> None:
    rng = random.Random(292)
    alphabet = "abcdefgh  \n\t .,’‘“”—–…-'\""
    for _ in range(300):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(40, 400)))
        index = TextIndex(text)
        length = rng.randint(20, len(text))
        start = rng.randint(0, len(text) - length)
        begin, end = _whole_span(text, start, start + length)
        quote = _perturb(text[begin:end], rng)
        if not quote.strip():
            continue
        span = index.locate(quote)
        assert span is not None, (text, quote)
        assert _normalised(text[span[0] : span[1]]) == _normalised(quote)


def _whole_span(text: str, begin: int, end: int) -> tuple[int, int]:
    """``(begin, end)`` widened until neither end is inside a word: a quote the gate accepts."""
    while begin > 0 and text[begin - 1].isalnum() and text[begin].isalnum():
        begin -= 1
    while end < len(text) and text[end - 1].isalnum() and text[end].isalnum():
        end += 1
    return begin, end


def _perturb(quote: str, rng: random.Random) -> str:
    """Re-space and un-curl a quote the way a model copying it might."""
    plain = {"’": "'", "‘": "'", "“": '"', "”": '"', "—": "-", "–": "-", "…": "..."}
    out = []
    for char in quote:
        if char.isspace():
            out.append(rng.choice([" ", "\n", "  ", " ", "\t "]))
        elif char in plain and rng.random() < 0.7:
            out.append(plain[char])
        else:
            out.append(char)
    return "".join(out)


def _large_text(characters: int, seed: int = 7) -> tuple[str, list[str]]:
    """Filing-like text full of folded characters, and 50 re-spaced quotes (the last absent)."""
    rng = random.Random(seed)
    words = ["revenue", "grew", "customers", "risk", "the", "data", "center", "supply"]
    lines = []
    while sum(len(line) + 1 for line in lines) < characters:
        lines.append(" ".join(rng.choice(words) for _ in range(rng.randint(5, 40))) + " — ’")
    text = "\n".join(lines)[:characters]
    quotes = []
    for _ in range(50):
        begin, end = _whole_span(text, (start := rng.randint(0, len(text) - 200)), start + 120)
        quotes.append(text[begin:end].replace(" ", "\n").replace("’", "'"))
    quotes[-1] = "a quote that is nowhere in the text at all"
    return text, quotes


def _best_seconds(text: str, quotes: list[str], repeats: int = 5) -> float:
    """The fastest of ``repeats`` timings of indexing ``text`` and locating every quote."""
    timings = []
    for _ in range(repeats):
        began = time.perf_counter()
        index = TextIndex(text)
        for quote in quotes:
            index.locate(quote)
        timings.append(time.perf_counter() - began)
    return min(timings)


def test_locate_scales_linearly_with_the_text() -> None:
    # A ratio of two timings on the same machine, not a wall-clock bound: eight times the text
    # costs about eight times as much when indexing and locating are linear, sixty-four times
    # when quadratic. Twenty sits between the two with room for noise; the best of five runs
    # each removes most scheduling noise.
    small_text, small_quotes = _large_text(50_000)
    large_text, large_quotes = _large_text(400_000)
    index = TextIndex(large_text)
    found = [index.locate(quote) for quote in large_quotes]
    assert all(span is not None for span in found[:-1])
    assert found[-1] is None
    small = _best_seconds(small_text, small_quotes)
    large = _best_seconds(large_text, large_quotes)
    assert large < 20 * small, f"8x the text took {large / small:.1f}x as long"


# gate_claim ---------------------------------------------------------------------------------


def test_identity_holds_for_every_evidence_record() -> None:
    result = _gate(
        _finding(("p1", "a limited number of customers account for a significant share")),
        _finding(("p2", "Data Center revenue was $41.1 billion, up 56%")),
        _finding(("p1", 'The company\'s "Data Center" segment depends')),
    )
    assert len(result.evidence) == 3
    _assert_identity(result)


def test_verified_finding_carries_evidence_fields() -> None:
    quote = "Data Center revenue was $41.1 billion, up 56% from a year ago"
    result = _gate(_finding(("p2", quote.replace(" ", "\n"))))
    (finding,) = result.findings
    (item,) = result.evidence
    assert finding.verified and finding.evidence_ids == [item.id]
    assert finding.claim_id == "c1" and finding.filings_cited == 1
    assert finding.stance == Stance.supports and finding.confidence == Confidence.high
    assert item.excerpt == quote
    assert item.source_id == "s2" and item.finding_id == finding.id
    assert item.locator == "Part I, Item 2. Management's Discussion and Analysis"
    assert item.link.startswith(URL_2 + "#:~:text=")
    assert MDNA[: item.start].endswith(item.context_before)
    assert MDNA[item.start + len(item.excerpt) :].startswith(item.context_after)
    assert item.context_after.startswith(", driven by demand")
    assert item.context_before.startswith("Item 2.")
    assert result.quotes_offered == 1 and result.quotes_rejected == 0 and not result.problems


def test_straight_quotes_show_the_stored_curly_span() -> None:
    result = _gate(_finding(("p1", 'The company\'s "Data Center" segment depends')))
    assert result.evidence[0].excerpt == "The company’s “Data Center” segment depends"


def test_one_changed_word_withholds_the_finding() -> None:
    result = _gate(_finding(("p1", "a limited number of suppliers account for a significant")))
    assert result.findings == [] and result.evidence == []
    (withheld,) = result.unsupported
    assert not withheld.verified and withheld.evidence_ids == [] and withheld.claim_id == "c1"
    assert result.quotes_rejected == 1
    assert result.problems == [
        f"{withheld.id}: quote is not in any passage offered for this claim "
        "(it names p1, s1 (Part II, Item 1A. Risk Factors))"
    ]


def test_good_and_bad_quote_keeps_the_good_one() -> None:
    good = "a limited number of customers account for a significant share"
    bad = "a limited number of customers account for an insignificant share"
    result = _gate(_finding(("p1", good), ("p1", bad)))
    (finding,) = result.findings
    assert [item.excerpt for item in result.evidence] == [good]
    assert finding.evidence_ids == [result.evidence[0].id]
    assert result.quotes_offered == 2 and result.quotes_rejected == 1
    assert len(result.problems) == 1
    assert "not in any passage offered" in result.problems[0]


def test_too_short_quote_is_rejected() -> None:
    short = "Data Center revenue"
    assert len(short) < limits.MIN_EXCERPT_CHARS
    result = _gate(_finding(("p2", short)))
    assert result.findings == [] and len(result.unsupported) == 1
    assert "too short" in result.problems[0]


def test_too_long_quote_is_rejected() -> None:
    long_text = "word " * 200
    sources = {"s1": StoredSource(text=long_text, url=URL_1)}
    passages = {"p1": _passage("p1", "s1", long_text, "Full document")}
    quote = long_text[: limits.MAX_EXCERPT_CHARS + 5].strip()
    result = gate_claim(
        claim_id="c1",
        draft=ClaimDraft(findings=[_finding(("p1", quote))]),
        passages=passages,
        sources=sources,
        ids=RunIds(),
    )
    assert result.findings == [] and "too long" in result.problems[0]


def test_quote_at_the_length_limits_is_kept() -> None:
    # Each quote is a whole word of the text: a quote may not begin or end inside one.
    shortest = "y" * limits.MIN_EXCERPT_CHARS
    longest = "z" * limits.MAX_EXCERPT_CHARS
    text = f"{'x' * 10} {shortest} {longest} end"
    sources = {"s1": StoredSource(text=text, url=URL_1)}
    passages = {"p1": _passage("p1", "s1", text, "Full document")}
    result = gate_claim(
        claim_id="c1",
        draft=ClaimDraft(findings=[_finding(("p1", shortest)), _finding(("p1", longest))]),
        passages=passages,
        sources=sources,
        ids=RunIds(),
    )
    assert len(result.findings) == 2 and result.quotes_rejected == 0


def test_quote_from_a_different_source_than_its_passage_is_rejected() -> None:
    # The text is in s2 (MD&A) but the quote names p1, a Risk Factors passage of s1.
    result = _gate(_finding(("p1", "Data Center revenue was $41.1 billion, up 56%")))
    assert result.findings == []
    assert "not in any passage offered for this claim (it names p1, s1" in result.problems[0]


def test_unknown_passage_is_rejected() -> None:
    result = _gate(_finding(("p9", "Data Center revenue was $41.1 billion, up 56%")))
    assert result.findings == []
    assert "unknown passage p9" in result.problems[0]


def test_passage_whose_source_is_not_stored_is_rejected() -> None:
    passages = {**PASSAGES, "p3": _passage("p3", "s9", MDNA, "Full document")}
    result = gate_claim(
        claim_id="c1",
        draft=ClaimDraft(findings=[_finding(("p3", "Data Center revenue was $41.1 billion"))]),
        passages=passages,
        sources=SOURCES,
        ids=RunIds(),
    )
    assert result.findings == [] and "s9" in result.problems[0]


def test_duplicate_spans_in_one_finding_are_kept_once() -> None:
    quote = "a limited number of customers account for a significant share"
    result = _gate(_finding(("p1", quote), ("p1", quote.replace(" ", "\n"))))
    assert len(result.evidence) == 1
    assert result.findings[0].evidence_ids == [result.evidence[0].id]
    assert result.quotes_rejected == 0


def test_filings_cited_counts_distinct_sources() -> None:
    passages = {**PASSAGES, "p3": _passage("p3", "s1", RISK, "Part II, Item 1A. Risk Factors")}
    result = gate_claim(
        claim_id="c1",
        draft=ClaimDraft(
            findings=[
                _finding(
                    ("p1", "a limited number of customers account"),
                    ("p3", "the loss of any of them could harm our business"),
                    ("p2", "Data Center revenue was $41.1 billion"),
                )
            ]
        ),
        passages=passages,
        sources=SOURCES,
        ids=RunIds(),
    )
    assert result.findings[0].filings_cited == 2
    assert len(result.findings[0].evidence_ids) == 3


def test_ids_are_run_wide_and_sequential() -> None:
    ids = RunIds()
    first = _gate(_finding(("p2", "Data Center revenue was $41.1 billion")), ids=ids)
    second = _gate(
        _finding(("p1", "nothing like this appears anywhere")),
        _finding(("p1", "a limited number of customers account")),
        ids=ids,
    )
    assert [f.id for f in first.findings] == ["f1"]
    assert [e.id for e in first.evidence] == ["e1"]
    assert [f.id for f in second.unsupported] == ["f2"]
    assert [f.id for f in second.findings] == ["f3"]
    assert [e.id for e in second.evidence] == ["e2"]


def test_id_minter_counts_from_one() -> None:
    mint = IdMinter("x")
    assert [mint(), mint(), mint()] == ["x1", "x2", "x3"]
    assert mint.issued == 3


def test_quote_repeated_in_the_source_is_located_inside_its_passage() -> None:
    repeated = "Customer concentration could harm our business and results."
    text = f"Table of contents\n{repeated}\nItem 1A. Risk Factors\n{repeated}\nmore text here"
    body_start = text.index("Item 1A.")
    sources = {"s1": StoredSource(text=text, url=URL_1)}
    passage = Passage(
        id="p1", source_id="s1", locator="Item 1A", text=text[body_start:], start=body_start
    )
    result = gate_claim(
        claim_id="c1",
        draft=ClaimDraft(findings=[_finding(("p1", repeated))]),
        passages={"p1": passage},
        sources=sources,
        ids=RunIds(),
    )
    assert result.evidence[0].start > body_start


@pytest.mark.parametrize("named", ["risk", "mdna"])
def test_a_quote_in_two_offered_passages_is_located_in_the_one_the_finding_names(
    named: str,
) -> None:
    # Review 5, finding 10: the same sentence under two Items, both offered to the engine.
    repeated = "Customer concentration could harm our business and results."
    risk_heading, mdna_heading = "Item 1A. Risk Factors", "Item 7. Management's Discussion"
    text = f"{risk_heading}\n{repeated}\nOther risks follow.\n\n{mdna_heading}\n{repeated}\nEnd."
    risk_start = text.index(repeated)
    mdna_start = text.index(repeated, risk_start + 1)
    passages = {
        "risk": Passage(
            id="risk",
            source_id="s1",
            locator=risk_heading,
            text=text[risk_start : text.index("\n\n")],
            start=risk_start,
        ),
        "mdna": Passage(
            id="mdna",
            source_id="s1",
            locator=mdna_heading,
            text=text[mdna_start:],
            start=mdna_start,
        ),
    }
    result = gate_claim(
        claim_id="c1",
        draft=ClaimDraft(findings=[_finding((named, repeated))]),
        passages=passages,
        sources={"s1": StoredSource(text=text, url=URL_1)},
        ids=RunIds(),
    )
    (item,) = result.evidence
    expected = {"risk": (risk_start, risk_heading), "mdna": (mdna_start, mdna_heading)}[named]
    assert (item.start, item.locator) == expected
    assert text[item.start : item.start + len(item.excerpt)] == repeated == item.excerpt


def test_context_is_trimmed_to_whole_words_and_bounded() -> None:
    words = [f"w{i:03d}" for i in range(300)]
    text = " ".join(words)
    quote = " ".join(words[150:160])
    sources = {"s1": StoredSource(text=text, url=URL_1)}
    passages = {"p1": _passage("p1", "s1", text, "Full document")}
    result = gate_claim(
        claim_id="c1",
        draft=ClaimDraft(findings=[_finding(("p1", quote))]),
        passages=passages,
        sources=sources,
        ids=RunIds(),
    )
    (item,) = result.evidence
    assert 0 < len(item.context_before) <= limits.CONTEXT_CHARS
    assert 0 < len(item.context_after) <= limits.CONTEXT_CHARS
    assert text[: item.start].endswith(item.context_before)
    assert text[item.start + len(item.excerpt) :].startswith(item.context_after)
    assert item.context_before.split()[0] in words
    assert item.context_after.split()[-1] in words
    assert not item.context_before[0].isspace() and not item.context_after[-1].isspace()


def test_context_at_text_edges_is_short_and_exact() -> None:
    text = "Revenue grew strongly in every segment this quarter."
    sources = {"s1": StoredSource(text=text, url=URL_1)}
    passages = {"p1": _passage("p1", "s1", text, "Full document")}
    result = gate_claim(
        claim_id="c1",
        draft=ClaimDraft(findings=[_finding(("p1", "Revenue grew strongly in every"))]),
        passages=passages,
        sources=sources,
        ids=RunIds(),
    )
    (item,) = result.evidence
    assert item.context_before == ""
    assert item.context_after == " segment this quarter."


def test_too_many_findings_are_reported_not_silently_dropped() -> None:
    drafts = [_finding(("p2", "Data Center revenue was $41.1 billion"))] * (
        limits.MAX_FINDINGS_PER_CLAIM + 2
    )
    result = _gate(*drafts)
    assert len(result.findings) == limits.MAX_FINDINGS_PER_CLAIM
    assert any("only the first" in problem for problem in result.problems)


@pytest.mark.parametrize("stance", list(Stance))
def test_stance_is_carried_through(stance: Stance) -> None:
    result = _gate(_finding(("p2", "Data Center revenue was $41.1 billion"), stance=stance))
    assert result.findings[0].stance == stance


# numbers and reported figures ---------------------------------------------------------------

GROWTH_QUOTE = "Data Center revenue was $41.1 billion, up 56% from a year ago"
FIGURE = Metric(
    id="revenue_yoy:annual:2026-01-25",
    key="revenue_yoy",
    label="Revenue growth, year over year",
    period="annual",
    period_end="2026-01-25",
    period_label="Fiscal year ended 2026-01-25",
    value=65.4735357900948,
    unit="percent",
    display="+65.5%",
)
FIGURES = {FIGURE.id: FIGURE}


def _stated(statement: str, *quotes: tuple[str, str], metric_ids: list[str] = ()) -> FindingDraft:
    return FindingDraft(
        statement=statement,
        stance=Stance.supports,
        quotes=[Quote(passage_id=pid, text=text) for pid, text in quotes],
        confidence=Confidence.high,
        rationale="Scripted.",
        metric_ids=list(metric_ids),
    )


def _gate_figures(*findings: FindingDraft) -> GateResult:
    return gate_claim(
        claim_id="c1",
        draft=ClaimDraft(findings=list(findings)),
        passages=PASSAGES,
        sources=SOURCES,
        ids=RunIds(),
        figures=FIGURES,
    )


def test_a_number_not_in_the_quote_withholds_the_finding_and_names_the_number() -> None:
    result = _gate_figures(_stated("Data Center revenue grew 65%.", ("p2", GROWTH_QUOTE)))
    assert result.findings == [] and result.evidence == []
    (withheld,) = result.unsupported
    assert not withheld.verified and withheld.evidence_ids == []
    assert withheld.checks.quotes == "passed"
    assert withheld.checks.numbers == "failed"
    assert withheld.checks.numbers_detail == [
        "65% was not found in the quotes or the cited figures"
    ]
    assert withheld.withheld_reason == (
        "a number in the statement is not in its quotes or cited figures: 65%"
    )
    assert result.numbers_checked == 1 and result.numbers_unmatched == 1
    # The quote itself was found word for word, whatever became of its finding.
    assert (result.quotes_offered, result.quotes_found, result.quotes_rejected) == (1, 1, 0)


def test_the_quoted_number_passes_the_numeric_check() -> None:
    result = _gate_figures(_stated("Data Center revenue grew 56%.", ("p2", GROWTH_QUOTE)))
    (finding,) = result.findings
    assert finding.verified and finding.withheld_reason == ""
    assert finding.checks.quotes == "passed" and finding.checks.numbers == "passed"
    assert finding.checks.numbers_detail == ["56% matched 56% in a quote"]
    assert result.numbers_checked == 1 and result.numbers_unmatched == 0
    _assert_identity(result)


def test_a_finding_without_numbers_says_the_check_did_not_apply() -> None:
    result = _gate(_finding(("p1", "a limited number of customers account")))
    (finding,) = result.findings
    assert finding.checks.numbers == "none" and finding.checks.numbers_detail == []
    assert finding.metric_ids == []


def test_a_cited_figure_alone_verifies_a_finding() -> None:
    result = _gate_figures(_stated("Revenue grew 65% in fiscal 2026.", metric_ids=[FIGURE.id]))
    (finding,) = result.findings
    assert finding.verified and finding.metric_ids == [FIGURE.id] and finding.evidence_ids == []
    assert finding.checks.quotes == "none" and finding.checks.numbers == "passed"
    assert finding.filings_cited == 0


def test_an_unknown_figure_is_dropped_reported_and_cannot_verify() -> None:
    result = _gate_figures(
        _stated("Revenue grew 65% in fiscal 2026.", metric_ids=["revenue_yoy:annual:1999-01-31"])
    )
    (withheld,) = result.unsupported
    assert withheld.metric_ids == []
    assert withheld.withheld_reason == "no verified quote or reported figure"
    assert result.problems == [
        f"{withheld.id}: cites figure revenue_yoy:annual:1999-01-31, which was not offered"
    ]


def test_a_number_only_in_an_uncited_figure_fails() -> None:
    result = _gate_figures(_stated("Data Center revenue grew 65%, up 56%.", ("p2", GROWTH_QUOTE)))
    (withheld,) = result.unsupported
    assert withheld.checks.numbers == "failed"


def test_a_finding_with_no_quote_and_no_figure_says_why_it_was_withheld() -> None:
    result = _gate(_finding(("p1", "a limited number of suppliers account for a significant")))
    (withheld,) = result.unsupported
    assert withheld.withheld_reason == "no verified quote or reported figure"
    assert withheld.checks.quotes == "none"


# Quotes come from what the engine was shown (referee 1 of version 4, finding 2) ------------

MDNA_HEADING = "Part I, Item 2. Management's Discussion and Analysis"
RISK_HEADING = "Part II, Item 1A. Risk Factors"
LEGAL_HEADING = "Part II, Item 3. Legal Proceedings"
MDNA_LINE = "Data Center revenue was $41.1 billion, up 56% from a year ago."
RISK_LINE = "A limited number of customers account for a significant share of our revenue."
LEGAL_LINE = "We are subject to legal proceedings in the ordinary course of our business."
# Stored the way the filing parser lays a document out: each heading line, then its text.
FILING = "\n\n".join(
    f"{heading}\n{line}"
    for heading, line in (
        (MDNA_HEADING, MDNA_LINE),
        (RISK_HEADING, RISK_LINE),
        (LEGAL_HEADING, LEGAL_LINE),
    )
)


def _section_passage(pid: str, line: str, heading: str) -> Passage:
    """A passage as the chunker makes it: the text under a heading, never the heading line."""
    return Passage(id=pid, source_id="s1", locator=heading, text=line, start=FILING.index(line))


# X (MD&A) and Y (Risk Factors) were offered for the claim; Legal Proceedings was not.
OFFERED = {
    "x": _section_passage("x", MDNA_LINE, MDNA_HEADING),
    "y": _section_passage("y", RISK_LINE, RISK_HEADING),
}


def _gate_offered(*findings: FindingDraft) -> GateResult:
    return gate_claim(
        claim_id="c1",
        draft=ClaimDraft(findings=list(findings)),
        passages=OFFERED,
        sources={"s1": StoredSource(text=FILING, url=URL_1)},
        ids=RunIds(),
    )


def test_a_quote_from_a_section_that_was_not_offered_is_rejected() -> None:
    # The referee's demonstration: name passage X, quote a sentence of an unoffered section.
    result = _gate_offered(_finding(("x", LEGAL_LINE)))
    assert result.findings == [] and result.evidence == []
    assert result.quotes_rejected == 1 and result.quotes_found == 0
    (withheld,) = result.unsupported
    assert result.problems == [
        f"{withheld.id}: quote is not in any passage offered for this claim "
        f"(it names x, s1 ({MDNA_HEADING}))"
    ]


def test_a_quote_from_another_offered_passage_is_kept_under_that_passages_locator() -> None:
    result = _gate_offered(_finding(("x", RISK_LINE)))
    (finding,) = result.findings
    (item,) = result.evidence
    assert item.excerpt == RISK_LINE and item.start == FILING.index(RISK_LINE)
    assert item.locator == RISK_HEADING, "labelled with the passage that holds the quote"
    assert finding.evidence_ids == [item.id]
    assert result.quotes_found == 1 and result.quotes_rejected == 0


def test_a_quote_inside_the_named_passage_keeps_its_locator() -> None:
    result = _gate_offered(_finding(("x", MDNA_LINE)))
    (item,) = result.evidence
    assert item.locator == MDNA_HEADING and item.start == FILING.index(MDNA_LINE)


def test_a_quote_that_includes_a_heading_line_is_rejected() -> None:
    # The heading is the parser's, not the filing's; no passage contains it.
    quote = f"{MDNA_HEADING}\nData Center revenue was $41.1 billion"
    assert quote in FILING
    result = _gate_offered(_finding(("x", quote)))
    assert result.findings == [] and result.quotes_rejected == 1
    assert "not in any passage offered for this claim" in result.problems[0]


def test_found_and_rejected_quotes_add_up_to_the_quotes_offered() -> None:
    result = _gate_offered(
        _finding(("x", MDNA_LINE), ("x", LEGAL_LINE)),
        _finding(("y", RISK_LINE), ("y", RISK_LINE)),  # one span twice: found twice, kept once
        _finding(("q", MDNA_LINE)),
    )
    assert result.quotes_offered == 5
    assert (result.quotes_found, result.quotes_rejected) == (3, 2)
    assert len(result.evidence) == 2


def test_evidence_says_what_its_link_opens() -> None:
    result = _gate_offered(_finding(("x", MDNA_LINE)))
    assert result.evidence[0].link_kind == "passage"


# The number check reads the reason too (referee 1 of version 4, finding 3) ---------------

REASON_WITHHELD = (
    "[Reason withheld: it cited a number (65%) that is in neither the finding's quotes nor "
    "its cited figures.]"
)


def _reasoned(statement: str, rationale: str) -> FindingDraft:
    return FindingDraft(
        statement=statement,
        stance=Stance.supports,
        quotes=[Quote(passage_id="p2", text=GROWTH_QUOTE)],
        confidence=Confidence.high,
        rationale=rationale,
    )


def test_a_reason_citing_a_number_its_quotes_lack_is_withheld_and_the_finding_kept() -> None:
    # The referee's demonstration: an honest statement and a 56% quote under "grew 65%".
    result = _gate_figures(_reasoned("Data Center revenue grew 56%.", "Revenue grew 65%"))
    (finding,) = result.findings
    assert finding.verified and finding.statement == "Data Center revenue grew 56%."
    assert finding.rationale == REASON_WITHHELD
    assert finding.checks.numbers == "passed"
    assert finding.checks.numbers_detail == [
        "56% matched 56% in a quote",
        "in the reason: 65% was not found in the quotes or the cited figures",
    ]
    assert result.reasons_withheld == 1
    assert result.numbers_checked == 1 and result.numbers_unmatched == 0  # statements only


def test_a_reason_whose_numbers_are_in_the_quotes_is_kept_as_written() -> None:
    reason = "The filing reports 56% growth in Data Center revenue."
    result = _gate_figures(_reasoned("Data Center revenue grew 56%.", reason))
    (finding,) = result.findings
    assert finding.rationale == reason and result.reasons_withheld == 0
    assert finding.checks.numbers_detail == ["56% matched 56% in a quote"]


# A located span must not begin or end inside a number or a word (fourth referee) ---------------

AMOUNT = "Total revenue was $46.78 billion for the quarter; costs were 1,234 million."


@pytest.mark.parametrize(
    "quote",
    [
        "revenue was $46.7",  # ends inside the decimals
        "revenue was $46.",  # ends just after the decimal point
        "revenue was $46",  # ends just before the decimal point
        "78 billion for the quarter",  # begins inside the decimals
        ".78 billion for the quarter",  # begins at the decimal point
        "6.78 billion for the quarter",  # begins inside the whole part
        "costs were 1",  # ends before a thousands separator
        "costs were 1,",  # ends after it
        "234 million",  # begins after it
        ",234 million",  # begins at it
    ],
)
def test_a_quote_that_cuts_a_number_is_not_found(quote: str) -> None:
    assert locate(quote, AMOUNT) is None
    assert locate(quote.replace(" ", "\n"), AMOUNT.replace(" ", "  ")) is None


@pytest.mark.parametrize("quote", ["tal revenue was", "Total revenue wa", "nue was $46.78"])
def test_a_quote_that_cuts_a_word_is_not_found(quote: str) -> None:
    assert locate(quote, AMOUNT) is None
    assert locate(quote.replace(" ", "\n"), AMOUNT.replace(" ", "  ")) is None


def test_a_later_whole_occurrence_is_found_after_one_that_cuts_a_number() -> None:
    text = "In billions, Q1 revenue was $46.78. Q2 revenue was $46.7. Margin rose."
    span = locate("revenue was $46.7", text)
    assert span == (text.index("Q2") + 3, text.index("Q2") + 3 + len("revenue was $46.7"))


def test_an_occurrence_whole_in_its_digits_but_cut_before_its_scale_word_is_not_one() -> None:
    """Until version 14.3 this was the expected result of the test above: "revenue was $46.7"
    found in "Q2 revenue was $46.7 billion", which is the sixth referee's finding 1."""
    text = "Q1 revenue was $46.78 billion. Q2 revenue was $46.7 billion."
    assert locate("revenue was $46.7", text) is None
    whole = "revenue was $46.7 billion"
    assert locate(whole, text) == (text.index("Q2") + 3, text.index("Q2") + 3 + len(whole))


def test_a_later_whole_occurrence_is_found_after_one_inside_a_word() -> None:
    text = "Up front: the margins fell, and the margin on services rose."
    whole = text.index("the margin on")
    assert locate("the margin", text) == (whole, whole + len("the margin"))
    # The same on the normalised path: the stored spaces are non-breaking, the quote's plain.
    stored = text.replace(" ", " ")
    assert locate("the margin", stored) == (whole, whole + len("the margin"))


@pytest.mark.parametrize(
    ("text", "quote"),
    [
        ("Revenue was 46.7. Margin rose.", "Revenue was 46.7"),  # a number ends a sentence
        ("Revenue was 46.7. Margin rose.", "Revenue was 46.7."),
        ("Revenue was 1,234, and margin rose.", "Revenue was 1,234"),  # a comma after a number
        ("Sales in the U.S. rose.", "Sales in the U.S"),  # an abbreviation before a full stop
        ("The company's revenue rose.", "The company"),  # a word before an apostrophe
        ("The company’s revenue rose.", "The company"),
    ],
)
def test_a_whole_number_or_word_before_punctuation_is_still_found(text: str, quote: str) -> None:
    span = locate(quote, text)
    assert span is not None and text[span[0] : span[1]] == quote
    respaced = text.replace(" ", "\n")
    span = locate(quote, respaced)
    assert span is not None and respaced[span[0] : span[1]] == quote.replace(" ", "\n")


def test_a_quote_that_cuts_a_number_withholds_a_finding_that_would_have_shown_the_cut() -> None:
    """Before the fix "revenue was $41" verified, and the excerpt shown carried $41."""
    draft = _stated("Data Center revenue was $41 billion.", ("p2", "Data Center revenue was $41"))
    result = _gate_figures(draft)
    assert result.evidence == [] and result.quotes_rejected == 1
    [withheld] = result.unsupported
    assert withheld.withheld_reason == "no verified quote or reported figure"


# A located span must not end between a number and its scale word or unit, nor begin between a
# sign or currency symbol and its number (sixth referee, finding 1) --------------------------------

UNITS = (
    "Item 2. Results\n"
    "Data Center revenue was $46.7 billion for the quarter, up 56% from a year ago.\n"
    "Gaming revenue changed by -5% from the prior year and inventory was (1,234) million.\n"
    "The notes pay 350 basis points over the benchmark and trade at 30 times earnings.\n"
    "Net revenue $ 46,743 106 % of plan.\n"
)
UNIT_SOURCES = {"s9": StoredSource(text=UNITS, url=URL_1)}
UNIT_PASSAGES = {"p9": _passage("p9", "s9", UNITS, "Part I, Item 2. Results")}


def _gate_units(statement: str, quote: str) -> GateResult:
    return gate_claim(
        claim_id="c1",
        draft=ClaimDraft(findings=[_stated(statement, ("p9", quote))]),
        passages=UNIT_PASSAGES,
        sources=UNIT_SOURCES,
        ids=RunIds(),
    )


def test_a_quote_that_stops_before_the_scale_word_cannot_verify_another_scale() -> None:
    """The referee's input: "$46.7" out of "$46.7 billion" under a statement of $46.7 million."""
    result = _gate_units("Data Center revenue was $46.7 million.", "Data Center revenue was $46.7")
    assert result.findings == [] and result.evidence == [] and result.quotes_rejected == 1
    [withheld] = result.unsupported
    assert withheld.withheld_reason == "no verified quote or reported figure"


def test_a_quote_that_begins_after_the_minus_cannot_verify_growth() -> None:
    """The referee's second input: "5% from the prior year" out of "-5% from the prior year"."""
    result = _gate_units("Gaming revenue grew 5%.", "5% from the prior year and inventory")
    assert result.findings == [] and result.quotes_rejected == 1


@pytest.mark.parametrize(
    "quote",
    [
        "Data Center revenue was $46.7",  # ends before the scale word
        "Data Center revenue was $46.7 ",  # the same: padding is ignored
        "for the quarter, up 56",  # ends before the percent sign
        "5% from the prior year",  # begins after the minus
        "46.7 billion for the quarter",  # begins after the dollar sign
        "inventory was (1,234",  # ends before the closing parenthesis of a negative
        "inventory was (1,234)",  # ends before the scale word of a negative
        "1,234) million.\nThe notes pay",  # begins after the opening parenthesis
        "The notes pay 350",  # ends before "basis points"
        "The notes pay 350 basis",  # ends inside "basis points"
        "over the benchmark and trade at 30",  # ends before "times"
        "46,743 106 % of plan",  # begins after "$ "
        "Net revenue $ 46,743 106",  # ends before " %"
    ],
)
def test_a_quote_cut_beside_a_number_s_sign_scale_or_unit_is_not_found(quote: str) -> None:
    assert locate(quote, UNITS) is None
    # The same on the normalised path: the stored spaces are non-breaking, the quote's plain.
    assert locate(quote, UNITS.replace(" ", "\u00a0")) is None


@pytest.mark.parametrize(
    "quote",
    [
        "Data Center revenue was $46.7 billion",  # the amount with its scale word
        "revenue was $46.7 billion for the quarter, up 56%",  # ends after the percent sign
        "changed by -5% from the prior year",  # begins before the minus
        "inventory was (1,234) million",
        "The notes pay 350 basis points",
        "trade at 30 times earnings",
        "Net revenue $ 46,743",  # a table cell: a number then another number, no unit between
        "$ 46,743 106 % of plan",
    ],
)
def test_a_quote_that_keeps_each_number_whole_with_its_unit_is_still_found(quote: str) -> None:
    span = locate(quote, UNITS)
    assert span is not None and UNITS[span[0] : span[1]] == quote


@pytest.mark.parametrize(
    ("text", "quote"),
    [
        ("Revenue for the year was 46.7. Margin rose.", "Revenue for the year was 46.7"),
        ("Revenue was $1,234 million in 2026. Margin rose.", "Revenue was $1,234 million in 2026"),
        ("The plan covers 2,000 employees.", "The plan covers 2,000"),  # a noun is not a unit
        ("It earned $1.25 per share this year.", "It earned $1.25"),  # nor is "per share"
        ("Growth of 5% (a record) followed.", "Growth of 5% (a record)"),
        ("Sales rose 5%-7% in the period.", "Sales rose 5%"),  # a range's dash is not a sign
        ("Revenue of 46.7 billions of yen.", "Revenue of 46.7"),  # "billions" is no scale word
    ],
)
def test_a_true_quote_ending_in_a_number_is_not_refused_wrongly(text: str, quote: str) -> None:
    span = locate(quote, text)
    assert span is not None and text[span[0] : span[1]] == quote
