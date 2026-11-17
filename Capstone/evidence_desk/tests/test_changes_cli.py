"""The filing-changes command line, driven by fake EDGAR filings (no network)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app import changes
from app.core.change_models import (
    ChangeCounts,
    FilingChanges,
    FilingSide,
    ItemChanges,
    Paragraph,
    RewordedParagraph,
    WordChange,
)
from app.core.ports import SourceError
from app.services.filing_changes import filing_changes
from app.store import FilingCache
from tests.fakes import NVIDIA, synthetic_ref
from tests.test_filing_changes import (
    DROPPED,
    EARLIER,
    LATER,
    PLANTED,
    FormFilings,
    annual_report,
    two_annual_reports,
)
from tests.test_filing_diff import X_AFTER, X_BEFORE, Y_AFTER, Y_BEFORE

NOW = datetime(2026, 11, 17, 12, 30, 5, tzinfo=UTC)
STEM = "changes-NVDA-10-K-20261117T123005Z"


def run(tmp_path: Path, *argv: str, filings: FormFilings | None = None) -> int:
    return changes.main(
        list(argv),
        source=filings or two_annual_reports(),
        cache=FilingCache(),
        now=NOW,
        out_dir=tmp_path,
    )


def test_main_prints_and_writes_the_markdown_and_the_record(tmp_path: Path, capsys) -> None:
    assert run(tmp_path, "nvda", "--form", "10-K") == 0
    markdown = (tmp_path / f"{STEM}.md").read_text()
    record = FilingChanges.model_validate_json((tmp_path / f"{STEM}.json").read_text())
    assert record == filing_changes("NVDA", "10-K", filings=two_annual_reports())
    printed = capsys.readouterr().out
    assert markdown in printed
    assert f"changes: wrote {tmp_path / STEM}.md and .json" in printed


def test_the_form_defaults_to_the_annual_report(tmp_path: Path) -> None:
    assert run(tmp_path, "NVDA") == 0
    assert (tmp_path / f"{STEM}.json").exists()


def test_the_markdown_names_both_filings_counts_each_item_and_quotes_the_changes(
    tmp_path: Path,
) -> None:
    run(tmp_path, "NVDA")
    markdown = (tmp_path / f"{STEM}.md").read_text()
    assert markdown.startswith("# What changed: NVIDIA CORP, 10-K\n")
    assert "| Accession | 0009999999-26-000001 | 0009999999-26-000002 |" in markdown
    assert "| Period end | 2026-01-01 | 2026-02-01 |" in markdown
    assert "| Item 1A. Risk Factors | both | 1 | 0 | 0 | 1 | 1 | 0 / 0 / 0 / 0 |" in markdown
    assert "| Total | | 2 | 0 | 0 | 1 | 1 | 0 / 0 / 0 / 0 |" in markdown
    assert "table rows: unchanged / numbers only / added / removed |" in markdown
    assert f"  > {PLANTED}" in markdown
    assert f"  > {DROPPED}" in markdown
    assert "### Added (1)" in markdown and "### Removed (1)" in markdown


def _reworded_record() -> FilingChanges:
    side = FilingSide(
        form="10-K",
        period_end="2026-01-25",
        filed_date="2026-02-25",
        accession="a-2",
        url="https://www.sec.gov/x/later.htm",
        title="later",
        item_coverage=0.96,
    )

    def paragraph(text: str) -> Paragraph:
        return Paragraph(text=text, locator="Item 1A. Risk Factors", start=0, link="https://l/#t")

    pair = RewordedParagraph(
        before=paragraph("Supply is tight this year."),
        after=paragraph("Supply is ample this year."),
        similarity=0.6,
        segments=[
            WordChange(text="Supply is", kind="same"),
            WordChange(text="tight", kind="removed"),
            WordChange(text="ample", kind="added"),
            WordChange(text="this year.", kind="same"),
        ],
    )
    items = [
        ItemChanges(
            item="Item 1A. Risk Factors",
            present_in="both",
            reworded=1,
            **{"reworded_paragraphs": [pair]},
        ),
        ItemChanges(item="Item 1C. Cybersecurity", present_in="earlier", removed=2),
        ItemChanges(item="Item 9. Stars * and | pipes", present_in="later"),
    ]
    return FilingChanges(
        company=NVIDIA,
        earlier=side.model_copy(update={"accession": "a-1"}),
        later=side,
        items=items,
        totals=ChangeCounts(reworded=1, removed=2),
        notes=["A note for the reader."],
    )


def test_numbers_only_paragraphs_and_changed_sub_headings_are_listed() -> None:
    record = _reworded_record()
    pair = (
        record.items[0]
        .reworded_paragraphs[0]
        .model_copy(
            update={
                "similarity": 1.0,
                "segments": [
                    WordChange(text="Revenue was", kind="same"),
                    WordChange(text="$115.2", kind="removed"),
                    WordChange(text="$193.7", kind="added"),
                    WordChange(text="billion.", kind="same"),
                ],
            }
        )
    )
    record.items[0] = record.items[0].model_copy(
        update={
            "numbers_only": 3,
            "numbers_only_paragraphs": [pair],
            "subheadings_added": ["Risks Related to Our * AI Offerings"],
            "subheadings_removed": ["Risks Related to Supply"],
        }
    )
    markdown = changes.render_markdown(record)
    assert "### Numbers only (3; the first 1 shown)" in markdown
    assert "Before: Revenue was ~~$115.2~~ billion." in markdown
    assert "After: Revenue was **$193.7** billion." in markdown
    later_only = "Sub-headings only in the later filing: Risks Related to Our \\* AI Offerings"
    assert later_only in markdown
    assert "Sub-headings only in the earlier filing: Risks Related to Supply" in markdown


def test_a_reworded_paragraph_marks_removed_words_struck_and_added_words_bold() -> None:
    markdown = changes.render_markdown(_reworded_record())
    assert "Before: Supply is ~~tight~~ this year." in markdown
    assert "After: Supply is **ample** this year." in markdown
    assert "similarity 0.60" in markdown


def test_items_in_one_filing_only_are_listed_as_such_and_cells_are_escaped() -> None:
    markdown = changes.render_markdown(_reworded_record())
    assert "| Item 1C. Cybersecurity | earlier only |" in markdown
    assert "| Item 9. Stars \\* and \\| pipes | later only |" in markdown
    assert "- A note for the reader." in markdown


def test_filing_text_cannot_inject_markdown() -> None:
    assert changes.escape("a *b* _c_ [d](e) <f> | `g` ~h~") == (
        "a \\*b\\* \\_c\\_ \\[d\\](e) \\<f\\> \\| \\`g\\` \\~h\\~"
    )


def test_an_unknown_ticker_exits_2_and_writes_nothing(tmp_path: Path, capsys) -> None:
    assert run(tmp_path, "NOPE") == 2
    assert "ticker: Ticker NOPE is not in SEC's company list" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "filings",
    [
        FormFilings(refs=[synthetic_ref(2, "10-K"), synthetic_ref(1)], documents={}),
        two_annual_reports(SourceError("EDGAR answered HTTP 503 for the document")),
    ],
)
def test_edgar_failures_exit_1_with_the_reason(tmp_path: Path, capsys, filings) -> None:
    assert run(tmp_path, "NVDA", filings=filings) == 1
    error = capsys.readouterr().err
    assert error.startswith("SEC EDGAR: ")
    assert "has 1 10-K filing" in error or "HTTP 503" in error
    assert list(tmp_path.iterdir()) == []


def test_the_record_is_json_an_api_can_return(tmp_path: Path) -> None:
    run(tmp_path, "NVDA", "--form", "10-K")
    payload = json.loads((tmp_path / f"{STEM}.json").read_text())
    assert set(payload) == {"company", "earlier", "later", "items", "totals", "notes"}


def test_timing_compares_the_candidate_index_with_all_pairs_and_saves_it(
    tmp_path: Path, capsys
) -> None:
    assert run(tmp_path, "NVDA", "--time", "3") == 0
    markdown = (tmp_path / f"{STEM}.md").read_text()
    timing = markdown[markdown.index("## Timing") :]
    assert "3 interleaved runs of each, after one discarded run of each" in timing
    assert "| Candidate index |" in timing and "| All pairs |" in timing
    assert "The two give the same record: yes." in timing
    assert timing in capsys.readouterr().out


def test_timing_needs_a_positive_count(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        run(tmp_path, "NVDA", "--time", "0")


# Reviewing the threshold


def near_threshold_reports() -> FormFilings:
    """Two annual reports with one pair of risk factors just above the threshold, one below."""
    return FormFilings(
        refs=[LATER, EARLIER],
        documents={
            LATER.url: annual_report(X_AFTER, Y_AFTER),
            EARLIER.url: annual_report(X_BEFORE, Y_BEFORE),
        },
    )


def test_review_lists_the_pairs_just_above_and_just_below_the_threshold(tmp_path: Path) -> None:
    assert run(tmp_path, "NVDA", "--review", "0.4", filings=near_threshold_reports()) == 0
    markdown = (tmp_path / f"{STEM}.md").read_text()
    review = markdown[markdown.index("## Pairs to read before trusting the threshold") :]
    above, below = review.split("### Not paired, just below it")
    assert "### Paired, just above it (similarity 0.5 to under 0.6): 1" in above
    assert "similarity 0.53" in above and "juliet" in above and "xray" in above
    assert below.startswith(" (similarity 0.4 to under 0.5): 1")
    assert "similarity 0.44" in below and "jasmine" in below and "quince" in below
    assert "juliet" not in below and "jasmine" not in above


def test_review_changes_neither_the_comparison_nor_the_record(tmp_path: Path) -> None:
    plain, reviewed = tmp_path / "plain", tmp_path / "reviewed"
    run(plain, "NVDA", filings=near_threshold_reports())
    run(reviewed, "NVDA", "--review", "0.4", filings=near_threshold_reports())
    assert (plain / f"{STEM}.json").read_text() == (reviewed / f"{STEM}.json").read_text()
    report = (plain / f"{STEM}.md").read_text()
    assert "Pairs to read" not in report
    assert (reviewed / f"{STEM}.md").read_text().startswith(report)


@pytest.mark.parametrize("value", ["0.5", "0.6", "0", "-0.2", "half"])
def test_review_needs_a_similarity_below_the_threshold(tmp_path: Path, value: str) -> None:
    with pytest.raises(SystemExit) as stopped:
        run(tmp_path, "NVDA", "--review", value)
    assert stopped.value.code == 2
