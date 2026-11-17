"""The reading sheet of the golden set: one block per case, and the committed sheet is current."""

from __future__ import annotations

from app.evaluation.corpus import PinnedFiling, load_pins
from app.evaluation.golden import GOLDEN_PATH, GoldenCase, read_golden
from app.evaluation.reading_sheet import (
    DEFAULT_OUT,
    newest_results,
    outcomes,
    render_case,
    render_sheet,
)

ACCESSION = "0001045810-26-000075"
URL = "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm"
PIN = PinnedFiling(
    ticker="NVDA",
    accession=ACCESSION,
    form="10-Q",
    period_end="2026-07-26",
    filed_date="2026-08-26",
    url=URL,
    sha256="0" * 64,
    cik=1045810,
    name="NVIDIA CORP",
)
EXCERPT = "Data Center revenue was $89.0 billion, up 117% from a year ago and up 18% sequentially."
ANSWERABLE = GoldenCase(
    id="nvda-data-center",
    ticker="NVDA",
    filings=[ACCESSION],
    claim="Sales of AI server hardware are still the main engine of growth.",
    kind="answerable",
    expected="supports",
    must_retrieve=[{"accession": ACCESSION, "section": "Part I, Item 2", "text": EXCERPT}],
    why="The quarterly report attributes revenue growth to data center products.",
)
UNANSWERABLE = GoldenCase(
    id="nvda-no-such-topic",
    ticker="NVDA",
    filings=[ACCESSION],
    claim="The company plans to open retail stores in South America.",
    kind="unanswerable",
    expected="none",
    why="Nothing in the filing mentions retail stores or South America.",
)


def block(case: GoldenCase, outcome: dict | None) -> str:
    return "\n".join(render_case(1, case, {ACCESSION: PIN}, outcome))


def test_an_answerable_case_shows_its_claim_stance_reason_and_linked_excerpts() -> None:
    text = block(ANSWERABLE, {"verdict": "supported", "agrees": True, "retrieval_hit": False})
    assert text.startswith("## 1. nvda-data-center (NVIDIA CORP)")
    assert f"**Claim:** {ANSWERABLE.claim}" in text
    assert "the filings SUPPORT the claim" in text and ANSWERABLE.why in text
    assert "1. 10-Q for the period ended 2026-07-26, Part I, Item 2:" in text
    assert f"[open in the filing]({URL}#:~:text=" in text and f"   > {EXCERPT}" in text
    assert "verdict 'supported', which agrees with the expected stance" in text
    assert "none of these excerpts was among the passages the engine was shown" in text
    assert "- [ ] The expected stance is right" in text


def test_a_disagreement_is_said_in_capitals_so_it_is_not_read_past() -> None:
    text = block(ANSWERABLE, {"verdict": "mixed", "agrees": False, "retrieval_hit": True})
    assert "verdict 'mixed', which DISAGREES with the expected stance" in text
    assert "one of these excerpts was among the passages the engine was shown" in text


def test_an_unanswerable_case_has_no_excerpt_and_says_whether_the_tool_refused() -> None:
    refused = block(UNANSWERABLE, {"verdict": "not_addressed", "refused": True})
    assert "the filings DO NOT ADDRESS the claim" in refused
    assert "**No excerpt:**" in refused and "10-Q 2026-07-26" in refused
    assert "refused to judge it, as expected" in refused
    judged = block(UNANSWERABLE, {"verdict": "supported", "refused": False})
    assert "judged it (supported)" in judged


def test_a_case_no_evaluation_covers_says_so() -> None:
    assert "no recorded evaluation covers this case" in block(ANSWERABLE, None)


def test_the_sheet_counts_its_cases_and_names_its_sources() -> None:
    sheet = render_sheet([ANSWERABLE, UNANSWERABLE], {ACCESSION: PIN}, {}, "generation-x.json")
    assert "2 cases over 1 companies; 1 of them are claims the filings do not" in sheet
    assert "`eval/results/generation-x.json`" in sheet and "**No person has read them.**" in sheet
    assert sheet.index("## 1. nvda-data-center") < sheet.index("## 2. nvda-no-such-topic")


def test_the_cases_where_tool_and_drafter_part_ways_are_named_first() -> None:
    recorded = {
        ANSWERABLE.id: {"verdict": "mixed", "agrees": False, "retrieval_hit": True},
        UNANSWERABLE.id: {"verdict": "not_addressed", "refused": True},
    }
    sheet = render_sheet([ANSWERABLE, UNANSWERABLE], {ACCESSION: PIN}, recorded, "g.json")
    assert "**Start with these**" in sheet and "1 (nvda-data-center)." in sheet
    assert "2 (nvda-no-such-topic)" not in sheet.split("## 1.")[0]
    agreed = {ANSWERABLE.id: {"verdict": "supported", "agrees": True}}
    assert "**Start with these**" not in render_sheet([ANSWERABLE], {ACCESSION: PIN}, agreed, "")


def test_the_committed_sheet_is_what_the_golden_file_gives_now() -> None:
    raw, _ = read_golden(GOLDEN_PATH)
    cases = [GoldenCase.model_validate(item) for item in raw["cases"]]
    results = newest_results()
    current = render_sheet(cases, load_pins(), outcomes(results), results.name if results else "")
    assert DEFAULT_OUT.read_text(encoding="utf-8") == current, (
        "eval/golden-reading.md is out of date with eval/golden.json or the newest results: "
        "run `make golden-sheet` and commit it"
    )
