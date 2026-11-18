"""The Markdown brief: same record and same wording as the API and the page."""

import re
from datetime import UTC, datetime, timedelta

import pytest

from app.core.change_models import (
    ChangeCounts,
    FilingSide,
    Paragraph,
    RewordedParagraph,
    WordChange,
)
from app.core.claim_change_models import (
    ClaimChanges,
    ComparedFilings,
    RelevantChange,
    RunChanges,
)
from app.core.metric_models import Metric
from app.core.models import (
    Brief,
    Claim,
    Company,
    Confidence,
    Decision,
    DecisionValue,
    Evidence,
    ExtractionStatus,
    Finding,
    FindingChecks,
    Review,
    Run,
    RunStatus,
    Source,
    SourceKind,
    Stance,
    ThesisRequest,
    UnplacedPeriod,
    Verdict,
)
from app.core.policy import (
    DECISION_LABELS,
    FIGURES_NOTE,
    PROVENANCE_NOTE,
    REVIEW_NOTE,
    STATUS_NOTES,
    UNDECIDED,
    VERDICT_LABELS,
    VERDICT_NOTES,
)
from app.core.review import build_review
from app.services.export import READING_LIST_HEADING, READING_LIST_NOTE, render_markdown

URL = "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000075/nvda-20260726.htm"
CLAIMS = [
    "Data-center revenue is still growing",
    "A few customers account for most revenue",
    "The company operates grocery stores in Norway",
]
REQUEST = ThesisRequest(
    ticker="NVDA", decision="Keep the position into the next earnings report", claims=CLAIMS
)
STARTED = datetime(2026, 11, 17, 14, 0, tzinfo=UTC)


def _source(**overrides: object) -> Source:
    values: dict = {
        "id": "s1",
        "kind": SourceKind.sec_filing,
        "title": "NVIDIA 10-Q for the period ended 2026-07-26",
        "publisher": "SEC EDGAR",
        "url": URL,
        "form": "10-Q",
        "accession": "0001045810-26-000075",
        "period_end": "2026-07-26",
        "published_date": "2026-08-26",
        "retrieved_at": datetime(2026, 11, 17, 14, 3, 9, tzinfo=UTC),
        "content_hash": "ab" * 32,
        "extraction_status": ExtractionStatus.extracted,
    }
    return Source(**{**values, **overrides})


def _finding(fid: str, claim_id: str, stance: Stance, evidence_ids: list[str]) -> Finding:
    return Finding(
        id=fid,
        claim_id=claim_id,
        statement=f"Statement {fid}.",
        stance=stance,
        evidence_ids=evidence_ids,
        confidence=Confidence.high,
        rationale=f"Rationale {fid}.",
        verified=bool(evidence_ids),
        filings_cited=1 if evidence_ids else 0,
    )


def _complete_run(status: RunStatus = RunStatus.partial) -> Run:
    excerpt = "Data Center revenue was $41.1 billion, up 56% from a year ago"
    return Run(
        id="run-42",
        inputs=REQUEST,
        status=status,
        stage="done",
        started_at=STARTED,
        finished_at=datetime(2026, 11, 17, 14, 4, tzinfo=UTC),
        company=Company(cik=1045810, ticker="NVDA", name="NVIDIA CORP"),
        engine="anthropic:claude",
        claims=[
            Claim(id="c1", text=CLAIMS[0], verdict=Verdict.mixed, finding_ids=["f1", "f2", "f3"]),
            Claim(id="c2", text=CLAIMS[1], verdict=Verdict.unjudged, finding_ids=["f4"]),
            Claim(id="c3", text=CLAIMS[2], verdict=Verdict.not_addressed),
        ],
        sources=[
            _source(),
            _source(
                id="s2",
                kind=SourceKind.public_html,
                title="Investor page",
                publisher="example.com",
                url="https://investor.example.com/x",
                form=None,
                accession=None,
                period_end=None,
                published_date=None,
                extraction_status=ExtractionStatus.failed,
                error="HTTP 404 Not Found",
            ),
        ],
        evidence=[
            Evidence(
                id="e1",
                source_id="s1",
                finding_id="f1",
                excerpt=excerpt,
                locator="Part I, Item 2. Management's Discussion and Analysis",
                start=1200,
                link=URL + "#:~:text=Data%20Center",
            ),
            Evidence(
                id="e2",
                source_id="s1",
                finding_id="f2",
                excerpt="Sales to one customer represented 16% of revenue | line\nsecond line",
                locator="Part II, Item 1A. Risk Factors",
                start=9000,
                link=URL + "#:~:text=Sales",
            ),
            Evidence(
                id="e3",
                source_id="s1",
                finding_id="f3",
                excerpt="Context excerpt about supply constraints in the quarter",
                locator="Part I, Item 2",
                start=50,
            ),
            Evidence(
                id="e4",
                source_id="s1",
                finding_id="f4",
                excerpt="Direct customer A represented 12% of total revenue",
                locator="Part I, Item 1. Financial Statements",
                start=70,
            ),
        ],
        findings=[
            _finding("f1", "c1", Stance.supports, ["e1"]),
            _finding("f2", "c1", Stance.challenges, ["e2"]),
            _finding("f3", "c1", Stance.context, ["e3"]),
            _finding("f4", "c2", Stance.context, ["e4"]),
        ],
        unsupported_findings=[_finding("f5", "c2", Stance.supports, [])],
        coverage_limits=["1 of 2 source(s) could not be read."],
        errors=["s2: HTTP 404 Not Found"],
        brief=Brief(
            summary="Growth continues; concentration is disclosed.",
            summary_origin="anthropic:claude",
            unknowns=["Whether growth persists next quarter."],
            next_steps=["Read the next 10-Q."],
            coverage_status=status,
            status_note=STATUS_NOTES[status],
        ),
    )


def _between(markdown: str, start: str, end: str) -> str:
    return markdown.split(start, 1)[1].split(end, 1)[0]


def test_title_status_and_decision() -> None:
    markdown = render_markdown(_complete_run())
    assert markdown.startswith("# ")
    title = markdown.splitlines()[0]
    assert "NVIDIA CORP" in title and "NVDA" in title
    assert "PARTIAL" in markdown and STATUS_NOTES[RunStatus.partial] in markdown
    assert REQUEST.decision in markdown


def test_sections_are_in_order() -> None:
    markdown = render_markdown(_complete_run())
    order = [
        STATUS_NOTES[RunStatus.partial],
        "## Decision",
        "## Verdicts",
        "## Summary",
        "## Claims",
        "## Unknowns",
        "## Next steps",
        "## Sources",
        "## Coverage limits",
        "## Errors",
        "## Provenance",
        "## Withheld findings",
    ]
    positions = [markdown.index(marker) for marker in order]
    assert positions == sorted(positions)


def test_verdict_table_uses_policy_labels_and_counts_verified_findings() -> None:
    table = _between(render_markdown(_complete_run()), "## Verdicts", "## Summary")
    rows = [line for line in table.splitlines() if line.startswith("|")]
    assert rows[0].replace(" ", "") == (
        "|Claim|Verdict|Computed|Supporting|Challenging|Context|Filingsquoted|"
    )
    assert rows[2].replace(" ", "") == (
        f"|{CLAIMS[0]}|{VERDICT_LABELS[Verdict.mixed]}|Notest|1|1|1|1|".replace(" ", "")
    )
    # f5 supports c2 but was withheld: it is not counted.
    assert rows[3].replace(" ", "") == (
        f"|{CLAIMS[1]}|{VERDICT_LABELS[Verdict.unjudged]}|Notest|0|0|1|1|".replace(" ", "")
    )
    assert VERDICT_LABELS[Verdict.not_addressed] in rows[4]
    assert rows[4].replace(" ", "").endswith("|0|0|0|0|")


def _table_rows(markdown: str) -> dict[str, list[str]]:
    """The verdict table's rows by claim text, each as its stripped cells."""
    table = _between(markdown, "## Verdicts", "## Summary")
    rows = [line for line in table.splitlines() if line.startswith("|")]
    cells = [[cell.strip() for cell in row.strip("|").split("|")] for row in rows]
    return {row[0]: row for row in [cells[0], *cells[2:]]}


def test_the_verdict_table_counts_the_distinct_filings_each_claims_verified_findings_quote() -> (
    None
):
    """One quote from one filing must not look like quotes from several (thin evidence).

    Counted from the run record, evidence to source: distinct SEC filings only, from verified
    findings only. A page the user added is not a filing; a withheld finding's quote is not
    counted, and two quotes from one filing count once.
    """
    run = _complete_run()
    annual = _source(
        id="s4",
        title="NVIDIA 10-K for the period ended 2026-01-25",
        form="10-K",
        accession="0001045810-26-000021",
        period_end="2026-01-25",
        published_date="2026-02-25",
    )
    page = _source(
        id="s5",
        kind=SourceKind.public_html,
        title="Investor page",
        url="https://investor.example.com/q",
        form=None,
        accession=None,
    )
    run.sources += [annual, page]

    def quote(evidence_id: str, source_id: str, finding_id: str) -> Evidence:
        return Evidence(
            id=evidence_id,
            source_id=source_id,
            finding_id=finding_id,
            excerpt=f"Quote {evidence_id}",
            locator="Item 7",
            start=0,
        )

    run.evidence += [
        quote("e5", "s4", "f3"),
        quote("e6", "s5", "f4"),
        quote("e7", "s4", "f5"),
        quote("e8", "s1", "f1"),
    ]
    by_id = {finding.id: finding for finding in run.findings}
    by_id["f3"].evidence_ids.append("e5")
    by_id["f4"].evidence_ids.append("e6")
    by_id["f1"].evidence_ids.append("e8")
    run.unsupported_findings[0].evidence_ids = ["e7"]  # f5, c2: withheld
    rows = _table_rows(render_markdown(run))
    column = rows["Claim"].index("Filings quoted")
    assert rows[CLAIMS[0]][column] == "2"  # s1 (twice) and s4
    assert rows[CLAIMS[1]][column] == "1"  # s1; the page and the withheld quote do not count
    assert rows[CLAIMS[2]][column] == "0"


def test_summary_names_who_wrote_it() -> None:
    summary = _between(render_markdown(_complete_run()), "## Summary", "## Claims")
    assert "Growth continues; concentration is disclosed." in summary
    assert "anthropic:claude" in summary


def test_findings_show_stance_confidence_rationale_and_quoted_excerpt() -> None:
    claims = _between(render_markdown(_complete_run()), "## Claims", "## Unknowns")
    assert "Statement f1." in claims and "Rationale f1." in claims
    assert "supports" in claims and "challenges" in claims and "high" in claims
    assert "> Data Center revenue was $41.1 billion, up 56% from a year ago" in claims
    assert "Part I, Item 2. Management's Discussion and Analysis" in claims
    assert "NVIDIA 10-Q for the period ended 2026-07-26" in claims
    assert URL + "#:~:text=Data%20Center" in claims
    # A multi-line excerpt stays inside the blockquote.
    assert "> second line" in claims
    assert VERDICT_NOTES[Verdict.mixed] in claims


def test_claim_without_findings_says_so_with_the_verdict_note() -> None:
    claims = _between(render_markdown(_complete_run()), "## Claims", "## Unknowns")
    norway = claims.split(CLAIMS[2], 1)[1]
    assert VERDICT_NOTES[Verdict.not_addressed] in norway


def test_sources_table_separates_filing_date_and_retrieval_time() -> None:
    table = _between(render_markdown(_complete_run()), "## Sources", "## Coverage limits")
    rows = [line for line in table.splitlines() if line.startswith("|")]
    header = [cell.strip() for cell in rows[0].strip("|").split("|")]
    for column in ["ID", "Form", "Period end", "Filed", "Retrieved (UTC)", "Status"]:
        assert column in header
    filing = [cell.strip() for cell in rows[2].strip("|").split("|")]
    assert filing[header.index("Filed")] == "2026-08-26"
    assert filing[header.index("Retrieved (UTC)")] == "2026-11-17 14:03:09 UTC"
    assert filing[header.index("Period end")] == "2026-07-26"
    failed = [cell.strip() for cell in rows[3].strip("|").split("|")]
    assert "HTTP 404 Not Found" in failed[header.index("Status")]


def test_limits_errors_provenance_and_withheld_findings() -> None:
    markdown = render_markdown(_complete_run())
    assert "1 of 2 source(s) could not be read." in _between(
        markdown, "## Coverage limits", "## Errors"
    )
    assert "s2: HTTP 404 Not Found" in _between(markdown, "## Errors", "## Provenance")
    assert PROVENANCE_NOTE in markdown
    withheld = markdown.split("## Withheld findings", 1)[1]
    assert "Statement f5." in withheld and "verif" in withheld


def test_table_cells_escape_pipes() -> None:
    run = _complete_run()
    run.claims[0].text = "Revenue | growth is still positive"
    table = _between(render_markdown(run), "## Verdicts", "## Summary")
    assert "Revenue \\| growth" in table


@pytest.mark.parametrize("status", [RunStatus.failed, RunStatus.running])
def test_failed_or_running_run_renders_without_a_verdict_table(status: RunStatus) -> None:
    run = Run(
        id="run-9",
        inputs=REQUEST,
        status=status,
        stage="retrieving",
        started_at=STARTED,
        sources=[
            _source(extraction_status=ExtractionStatus.failed, error="EDGAR could not be reached")
        ],
        errors=["EDGAR could not be reached"],
    )
    markdown = render_markdown(run)
    assert STATUS_NOTES[status] in markdown
    assert "## Verdicts" not in markdown
    assert "NVDA" in markdown.splitlines()[0]
    assert "EDGAR could not be reached" in markdown
    for claim in CLAIMS:
        assert claim in markdown


# Reported figures and checks

QUARTER_REVENUE = Metric(
    id="revenue:quarter:2026-07-26",
    key="revenue",
    label="Revenue",
    period="quarter",
    period_end="2026-07-26",
    period_label="Quarter ended 2026-07-26",
    value=96_221_000_000,
    unit="USD",
    display="$96.22B",
)
QUARTER_MARGIN = Metric(
    id="gross_margin:quarter:2026-07-26",
    key="gross_margin",
    label="Gross margin",
    period="quarter",
    period_end="2026-07-26",
    period_label="Quarter ended 2026-07-26",
    value=74.97531723844068,
    unit="percent",
    display="75.0%",
    formula="72,142 ÷ 96,221; USD millions",
)
OLDER_QUARTER = QUARTER_REVENUE.model_copy(
    update={
        "id": "revenue:quarter:2026-04-26",
        "period_end": "2026-04-26",
        "period_label": "Quarter ended 2026-04-26",
        "display": "$81.62B",
    }
)
YEAR_REVENUE = QUARTER_REVENUE.model_copy(
    update={
        "id": "revenue:annual:2026-01-25",
        "period": "annual",
        "period_end": "2026-01-25",
        "period_label": "Fiscal year ended 2026-01-25",
        "display": "$215.94B",
    }
)


def _run_with_figures() -> Run:
    run = _complete_run()
    run.metrics = [QUARTER_REVENUE, OLDER_QUARTER, QUARTER_MARGIN, YEAR_REVENUE]
    run.metrics_notes = ["Skipped 1 malformed fact(s) of Revenues (USD): fact has no 'end' date"]
    run.sources.append(
        _source(
            id="s3",
            kind=SourceKind.sec_xbrl,
            title="NVIDIA CORP XBRL company facts",
            publisher="SEC EDGAR (XBRL API)",
            url="https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json",
            form=None,
            accession=None,
            period_end=None,
            published_date=None,
        )
    )
    f1 = run.findings[0]
    f1.metric_ids = [QUARTER_MARGIN.id]
    f1.checks = FindingChecks(
        quotes="passed",
        numbers="passed",
        numbers_detail=["56% matched 56% in a quote", "75% matched 75.0% in a cited figure"],
    )
    run.unsupported_findings[
        0
    ].withheld_reason = "a number in the statement is not in its quotes or cited figures: 65%"
    run.coverage.claims_with_evidence = 2
    run.coverage.claims_total = 3
    return run


def test_reported_figures_show_the_newest_quarter_and_fiscal_year() -> None:
    markdown = render_markdown(_run_with_figures())
    section = _between(markdown, "## Reported figures", "## Claims")
    assert "Quarter ended 2026-07-26" in section and "Fiscal year ended 2026-01-25" in section
    assert "$96.22B" in section and "$215.94B" in section and "75.0%" in section
    assert "72,142 ÷ 96,221; USD millions" in section
    assert "$81.62B" not in section  # not the newest quarter
    assert "Skipped 1 malformed fact(s)" in section
    assert FIGURES_NOTE in section


def test_no_reported_figures_section_without_metrics() -> None:
    assert "## Reported figures" not in render_markdown(_complete_run())


def test_each_finding_shows_its_cited_figures_and_its_checks() -> None:
    claims = _between(render_markdown(_run_with_figures()), "## Claims", "## Unknowns")
    f1 = _between(claims, "Statement f1.", "Statement f2.")
    assert "Gross margin, Quarter ended 2026-07-26: 75.0% (72,142 ÷ 96,221; USD millions)" in f1
    assert "Checks: quote: found in the filing; numbers: 2 of 2 matched" in f1
    f4 = claims.split("Statement f4.", 1)[1]
    assert "Checks: quote: found in the filing; numbers: none to check" in f4


def test_the_xbrl_source_is_a_row_of_the_sources_table() -> None:
    table = _between(render_markdown(_run_with_figures()), "## Sources", "## Coverage limits")
    [row] = [line for line in table.splitlines() if line.startswith("| s3 ")]
    assert "NVIDIA CORP XBRL company facts" in row and "| XBRL company facts |" in row
    assert "data.sec.gov/api/xbrl/companyfacts" in row


def test_withheld_findings_carry_their_own_reason() -> None:
    withheld = render_markdown(_run_with_figures()).split("## Withheld findings", 1)[1]
    assert "a number in the statement is not in its quotes or cited figures: 65%" in withheld


def _checked_run() -> Run:
    """The complete run after a meaning check: f1 supported, f2 partly, f3 unchecked; f5 failed."""
    run = _complete_run()
    run.checker = "claude"
    run.checker_detail = "claude-haiku-5-5 via the Anthropic API"
    by_id = {finding.id: finding for finding in run.findings}
    by_id["f1"].checks = FindingChecks(
        quotes="passed", support="passed", support_detail="The excerpt states 56% growth."
    )
    by_id["f2"].checks = FindingChecks(
        quotes="passed", support="partly", support_detail="It names one customer, not most."
    )
    failed = run.unsupported_findings[0]
    failed.checks = FindingChecks(quotes="passed", support="failed", support_detail="Off topic.")
    failed.withheld_reason = (
        "a second model judged that its evidence does not support the statement: Off topic"
    )
    return run


def test_each_finding_says_what_the_meaning_check_found() -> None:
    claims = _between(render_markdown(_checked_run()), "## Claims", "## Unknowns")
    f1 = _between(claims, "Statement f1.", "Statement f2.")
    f2 = _between(claims, "Statement f2.", "Statement f3.")
    f3 = _between(claims, "Statement f3.", "Statement f4.")
    assert "- Meaning: supported: The excerpt states 56% growth." in f1
    assert "- Meaning: partly supported: It names one customer, not most." in f2
    assert "- Meaning: not checked" in f3


def test_the_header_names_the_checker_or_says_none_checked() -> None:
    header = render_markdown(_checked_run()).split("## Decision", 1)[0]
    assert "- Meaning check: claude (claude-haiku-5-5 via the Anthropic API)" in header
    unchecked = render_markdown(_complete_run()).split("## Decision", 1)[0]
    assert "- Meaning check: none. No second model checked the findings' meaning." in unchecked


def test_a_finding_withheld_by_the_meaning_check_gives_its_reason() -> None:
    withheld = render_markdown(_checked_run()).split("## Withheld findings", 1)[1]
    assert (
        "- f5 (c2): Statement f5. Withheld: a second model judged that its evidence does not "
        "support the statement: Off topic."
    ) in withheld


def test_coverage_counts_claims_with_verified_excerpts_or_figures() -> None:
    markdown = render_markdown(_run_with_figures())
    assert "Claims with verified excerpts or figures: 2 of 3" in markdown
    assert "verified evidence:" not in markdown


# The reviewed brief

DECIDED = datetime(2026, 11, 17, 16, 30, tzinfo=UTC)


def _review_of(run: Run) -> Review:
    """f1 accepted with a note, f2 rejected with a note; f3 and f4 undecided."""
    decisions = [
        Decision(
            run_id=run.id,
            finding_id="f1",
            value=DecisionValue.accepted,
            note="Matches the segment table.",
            decided_at=DECIDED - timedelta(minutes=5),
        ),
        Decision(
            run_id=run.id,
            finding_id="f2",
            value=DecisionValue.rejected,
            note="This is about customers, not growth.",
            decided_at=DECIDED,
        ),
    ]
    return build_review(run, decisions)


def test_without_a_review_the_brief_is_unchanged() -> None:
    run = _complete_run()
    assert render_markdown(run, None) == render_markdown(run)
    assert "## Your review" not in render_markdown(run)
    assert "After your review" not in render_markdown(run)


def test_your_review_comes_first_after_the_status() -> None:
    run = _complete_run()
    markdown = render_markdown(run, _review_of(run))
    order = [STATUS_NOTES[RunStatus.partial], "## Your review", "- Run: run-42", "## Decision"]
    positions = [markdown.index(marker) for marker in order]
    assert positions == sorted(positions)
    section = _between(markdown, "## Your review", "- Run: run-42")
    assert "You decided 2 of 4 findings." in section
    assert REVIEW_NOTE in section


def test_the_verdict_table_gains_the_reviewed_verdict() -> None:
    run = _complete_run()
    table = _between(render_markdown(run, _review_of(run)), "## Verdicts", "## Summary")
    rows = [line for line in table.splitlines() if line.startswith("|")]
    assert rows[0].replace(" ", "") == (
        "|Claim|Verdict|Afteryourreview|Computed|Supporting|Challenging|Context|Filingsquoted|"
    )
    # c1: f1 (supports) accepted and f2 (challenges) rejected, so supported.
    assert rows[2].replace(" ", "") == (
        f"|{CLAIMS[0]}|{VERDICT_LABELS[Verdict.mixed]}|{VERDICT_LABELS[Verdict.supported]}|Notest|1|1|1|1|"
    ).replace(" ", "")
    # c2 has no decision yet.
    assert f"| {DECISION_LABELS[UNDECIDED]} |" in rows[3]


def test_each_finding_carries_its_decision_and_rejected_ones_are_struck_and_last() -> None:
    run = _complete_run()
    claims = _between(render_markdown(run, _review_of(run)), "## Claims", "## Unknowns")
    c1 = _between(claims, CLAIMS[0], CLAIMS[1])
    assert c1.index("Statement f1.") < c1.index("Statement f3.") < c1.index("Statement f2.")
    assert "#### ~~f2. Statement f2.~~" in c1
    assert "- Your decision: Accepted. Matches the segment table." in c1
    assert "- Your decision: Rejected. This is about customers, not growth." in c1
    f3 = _between(c1, "Statement f3.", "Statement f2.")
    assert "- Your decision: Undecided" in f3
    assert "~~" not in _between(c1, "Statement f1.", "Statement f3.")


def test_the_footer_dates_the_decisions() -> None:
    run = _complete_run()
    markdown = render_markdown(run, _review_of(run))
    assert markdown.rstrip().endswith(
        "This brief includes the reviewer's decisions as of 2026-11-17 16:30:00 UTC."
    )


def test_a_review_without_decisions_says_none_were_made() -> None:
    run = _complete_run()
    markdown = render_markdown(run, build_review(run, []))
    assert "You decided 0 of 4 findings." in markdown
    assert markdown.rstrip().endswith("This brief includes no reviewer decision yet.")


# Findings counted as context (referee 1 of version 4, finding 1)

FIGURE_ONLY_NOTE = (
    "backed by reported figures only and not confirmed by the meaning check: counted as context"
)


def test_the_export_says_which_findings_were_counted_as_context() -> None:
    run = _run_with_figures()
    f2 = run.findings[1]  # challenges c1, now on a figure alone and not confirmed by a check
    f2.evidence_ids = []
    f2.metric_ids = [QUARTER_REVENUE.id]
    f2.counted_as = Stance.context
    f2.count_note = FIGURE_ONLY_NOTE
    for finding in (run.findings[0], run.findings[2], run.findings[3]):
        finding.counted_as = finding.stance
    run.evidence = [item for item in run.evidence if item.finding_id != "f2"]
    markdown = render_markdown(run)
    claims = _between(markdown, "## Claims", "## Unknowns")
    f2_block = _between(claims, "Statement f2.", "Statement f3.")
    assert f"- Counted as: context ({FIGURE_ONLY_NOTE})" in f2_block
    assert "Counted as" not in _between(claims, "Statement f1.", "Statement f2.")
    # The table counts each finding as the verdict rule counted it.
    table = _between(markdown, "## Verdicts", "## Summary")
    row = [line for line in table.splitlines() if line.startswith(f"| {CLAIMS[0]}")][0]
    assert row.replace(" ", "").endswith("|1|0|2|1|")


def test_the_export_uses_the_runs_own_provenance_note() -> None:
    run = _complete_run()
    assert run.brief is not None
    run.brief.provenance_note = (
        "Evidence comes from the company's SEC filings and from 1 page you added; each excerpt "
        "names its source. A page you added is not a filing."
    )
    provenance = _between(render_markdown(run), "## Provenance", "## Withheld findings")
    assert run.brief.provenance_note in provenance and PROVENANCE_NOTE not in provenance


def test_a_withheld_reason_is_not_counted_among_the_statements_numbers() -> None:
    run = _run_with_figures()
    f1 = run.findings[0]
    f1.rationale = (
        "[Reason withheld: it cited a number (65%) that is in neither the finding's quotes nor "
        "its cited figures.]"
    )
    f1.checks.numbers_detail.append(
        "in the reason: 65% was not found in the quotes or the cited figures"
    )
    claims = _between(render_markdown(run), "## Claims", "## Unknowns")
    f1_block = _between(claims, "Statement f1.", "Statement f2.")
    assert "numbers: 2 of 2 matched; reason: withheld (65%)" in f1_block
    # The rationale is untrusted text, escaped; a viewer shows "[Reason withheld".
    assert "Rationale: \\[Reason withheld" in f1_block


# The reading list of changed paragraphs under each claim (docs/claim-changes.md)

LATER_FILING = "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000021/later.htm"
EARLIER_FILING = "https://www.sec.gov/Archives/edgar/data/1045810/000104581025000023/earlier.htm"


def _paragraph(text: str, url: str) -> Paragraph:
    return Paragraph(
        text=text,
        locator="Item 1A. Risk Factors",
        start=10,
        link=f"{url}#:~:text=x",
        link_kind="passage",
    )


def _run_changes() -> RunChanges:
    later = FilingSide(
        form="10-K",
        period_end="2026-01-25",
        filed_date="2026-02-25",
        accession="0001045810-26-000021",
        url=LATER_FILING,
        title="later",
        item_coverage=0.97,
    )
    earlier = later.model_copy(update={"period_end": "2025-01-26", "url": EARLIER_FILING})
    added = RelevantChange(
        kind="added",
        form="10-K",
        item="Item 1A. Risk Factors",
        paragraph=_paragraph(
            "A licence is now required for <b>H20</b> sales to China.", LATER_FILING
        ),
        score=12.5,
        matched_terms=["china", "export", "licens"],
        also_under=["Item 7. Management's Discussion"],
    )
    reworded = RelevantChange(
        kind="reworded",
        form="10-K",
        item="Item 7. Management's Discussion",
        pair=RewordedParagraph(
            before=_paragraph("Data Center revenue grew on strong demand.", EARLIER_FILING),
            after=_paragraph("Data Center revenue grew on demand for Blackwell.", LATER_FILING),
            similarity=0.7,
            segments=[WordChange(text="Data Center revenue grew on", kind="same")],
        ),
        score=9.0,
        matched_terms=["center", "data", "revenu"],
    )
    return RunChanges(
        run_id="run-42",
        compared=[
            ComparedFilings(
                form="10-K", earlier=earlier, later=later, totals=ChangeCounts(added=3, removed=2)
            )
        ],
        claims=[
            ClaimChanges(
                claim_id="c1",
                changes=[added, reworded],
                considered=6,
                matched=4,
                distinct_matched=3,
            ),
            ClaimChanges(claim_id="c2", considered=6),
            ClaimChanges(claim_id="c3", considered=6),
        ],
        notes=["No earlier 10-Q was found to compare with."],
    )


def test_the_brief_has_no_reading_list_unless_the_changes_are_given() -> None:
    assert READING_LIST_HEADING not in render_markdown(_complete_run())


def test_the_reading_list_sits_after_the_claims_and_says_what_it_is() -> None:
    markdown = render_markdown(_complete_run(), changes=_run_changes())
    section = _between(markdown, f"## {READING_LIST_HEADING}", "## Unknowns")
    assert markdown.index("## Claims") < markdown.index(f"## {READING_LIST_HEADING}")
    assert READING_LIST_NOTE in section
    assert "may be one the run did not read" in section
    assert "the claim or with the search queries the run wrote for it" in section
    assert "A reading list, not findings" in section
    assert "No model chose or judged" in section and "counts toward a verdict" in section
    assert (
        f"- [10-K for the period ended 2026-01-25]({LATER_FILING}) against "
        f"[the one for 2025-01-26]({EARLIER_FILING})"
    ) in section
    assert "- No earlier 10-Q was found to compare with." in section


def test_the_reading_list_says_which_filings_are_compared_and_no_more() -> None:
    """``filings_read`` keeps the newest 10-K and the newest 10-Q a run read, and no other.

    A default run reads one 10-K and two 10-Qs, so the older 10-Q is never compared with the
    one before it; the heading and the note said every filing the run read was.
    """
    assert READING_LIST_HEADING == "Changed since the previous annual and quarterly report"
    assert "newest annual report" in READING_LIST_NOTE
    assert "newest quarterly report" in READING_LIST_NOTE
    assert "filed before" in READING_LIST_NOTE
    assert "An older quarterly report the run read is not compared" in READING_LIST_NOTE
    assert "each one" not in READING_LIST_NOTE and "each filing" not in READING_LIST_NOTE


def test_each_claim_lists_its_changed_paragraphs_with_kind_place_words_and_links() -> None:
    markdown = render_markdown(_complete_run(), changes=_run_changes())
    first = _between(markdown, f"### c1: {CLAIMS[0]}", "### c2:")
    assert (
        "2 listed of 3 that share at least two words with the claim or its search queries, "
        "among 6 changed paragraphs."
    ) in first
    assert (
        "1. **Added** in the 10-K, Item 1A. Risk Factors. Shares: china, export, licens. "
        "Also under Item 7. Management's Discussion."
    ) in first
    assert "> A licence is now required for \\<b>H20\\</b> sales to China." in first
    assert f"[Open in the later filing]({LATER_FILING}#:~:text=x)" in first
    assert "2. **Reworded** in the 10-K, Item 7. Management's Discussion." in first
    assert "> Data Center revenue grew on demand for Blackwell." in first
    assert f"[earlier paragraph]({EARLIER_FILING}#:~:text=x)" in first


def test_a_claim_with_no_changed_paragraph_says_so() -> None:
    markdown = render_markdown(_complete_run(), changes=_run_changes())
    second = _between(markdown, f"### c2: {CLAIMS[1]}", "### c3:")
    assert (
        "No changed paragraph shares two words with this claim or its search queries (6 searched)."
    ) in second


# The period check


def test_a_finding_whose_period_is_not_in_its_evidence_says_so_and_a_passed_one_says_nothing() -> (
    None
):
    run = _complete_run()
    by_id = {finding.id: finding for finding in run.findings}
    by_id["f1"].checks = FindingChecks(
        quotes="passed",
        periods="unverified",
        periods_detail=[
            "fiscal 2026 is the fiscal year of a filing quoted (period ended 2026-01-25)",
            "fiscal 2023 is not in the quotes, the cited figures or the period of a filing quoted",
        ],
        periods_unverified=[
            UnplacedPeriod(
                mention="fiscal 2023",
                detail=(
                    "fiscal 2023 is not in the quotes, the cited figures or the period of a "
                    "filing quoted"
                ),
            )
        ],
    )
    by_id["f2"].checks = FindingChecks(
        quotes="passed",
        periods="passed",
        periods_detail=["fiscal 2026 is in a quote"],
    )
    claims = _between(render_markdown(run), "## Claims", "## Unknowns")
    f1 = _between(claims, "Statement f1.", "Statement f2.")
    f2 = _between(claims, "Statement f2.", "Statement f3.")
    assert (
        "- Period not found in its evidence: fiscal 2023 is not in the quotes, the cited "
        "figures or the period of a filing quoted.\n"
    ) in f1
    assert "fiscal 2026" not in f1
    assert "Period" not in f2 and "fiscal" not in f2


# Untrusted text renders literally (an excerpt is quoted from a filing or from a page the user
# added; a Markdown viewer must not turn it into an image, a link, emphasis or a heading)

HOSTILE_EXCERPT = "\n".join(
    [
        "# Not a heading",
        "See ![x](http://host/p.png) and [x](http://host), *bold*, _x_ and `code` \\ here.",
        "> not a quote",
        "- not an item",
        "+ not an item",
        "1. not a list",
        "&amp; <b>raw</b> ~~struck~~ a | b",
    ]
)
ORDINARY_EXCERPT = "Data Center revenue was $41.1 billion, up 56% (from $26.3 billion) in Q2, 2026."
# CommonMark: a backslash before any ASCII punctuation character stands for that character.
_ESCAPED = re.compile(r"\\([!-/:-@\[-`{-~])")


def _unescape(markdown: str) -> str:
    """Undo the export's backslash escapes: what a CommonMark viewer shows as text."""
    return _ESCAPED.sub(r"\1", markdown)


def _quoted(markdown: str, after: str) -> list[str]:
    """The lines of the first blockquote after ``after``, without their "> " marker."""
    lines = markdown.split(after, 1)[1].splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(">"))
    quote = []
    for line in lines[start:]:
        if not line.startswith(">"):
            break
        quote.append(line.removeprefix(">").removeprefix(" "))
    return quote


def _run_quoting(excerpt: str) -> Run:
    run = _complete_run()
    run.evidence[0].excerpt = excerpt  # e1, quoted under f1
    return run


def test_an_excerpt_cannot_become_an_image_a_link_emphasis_code_or_a_heading() -> None:
    quote = _quoted(render_markdown(_run_quoting(HOSTILE_EXCERPT)), "#### f1.")
    assert quote[0] == "\\# Not a heading"
    assert "See !\\[x\\](http://host/p.png) and \\[x\\](http://host)," in quote[1]
    assert "![x](" not in quote[1] and "[x](http://host)" not in quote[1]
    assert "\\*bold\\*" in quote[1] and "\\_x\\_" in quote[1] and "\\`code\\`" in quote[1]
    assert "\\\\ here" in quote[1]
    assert quote[2] == "\\> not a quote"
    assert quote[3] == "\\- not an item" and quote[4] == "\\+ not an item"
    assert quote[5] == "1\\. not a list"
    assert "\\&amp;" in quote[6] and "\\<b>" in quote[6] and "\\~\\~struck" in quote[6]


def test_undoing_the_escapes_gives_back_the_exact_stored_excerpt() -> None:
    quote = _quoted(render_markdown(_run_quoting(HOSTILE_EXCERPT)), "#### f1.")
    assert _unescape("\n".join(quote)) == HOSTILE_EXCERPT


def test_an_ordinary_excerpt_is_written_unchanged() -> None:
    quote = _quoted(render_markdown(_run_quoting(ORDINARY_EXCERPT)), "#### f1.")
    assert quote == [ORDINARY_EXCERPT]


def test_every_piece_of_untrusted_text_is_escaped_not_only_excerpts() -> None:
    """Statements, reasons, titles, company names, notes: anything the export did not write."""
    run = _complete_run()
    assert run.company is not None and run.brief is not None
    run.company.name = "*NVIDIA*"
    run.claims[0].text = "Revenue is [growing](http://host)"
    run.claims[0].rationale = "_Because_ `it` is"
    finding = run.findings[0]
    finding.statement = "![s](http://host/s.png)"
    finding.rationale = "see [x](http://host)\n# second line"
    run.brief.summary = "Fine.\n# Injected heading\n- injected item"
    run.sources[0].title = "Title ](http://host) [x"
    run.errors = ["1. not a list"]
    markdown = render_markdown(run)
    assert markdown.splitlines()[0] == "# Evidence Desk brief: \\*NVIDIA\\* (NVDA)"
    assert "Revenue is \\[growing\\](http://host)" in markdown
    assert "[growing](" not in markdown and "![s](" not in markdown
    assert "\\_Because\\_ \\`it\\` is" in markdown
    assert "- Rationale: see \\[x\\](http://host)\n\\# second line" in markdown
    summary = _between(markdown, "## Summary", "_Summary written by")
    assert "\n\\# Injected heading\n\\- injected item" in summary
    assert "Title \\](http://host) \\[x" in markdown
    assert "- 1\\. not a list" in markdown


def test_the_links_the_export_writes_still_work_and_a_url_cannot_close_one_early() -> None:
    run = _complete_run()
    run.sources[1].url = "https://investor.example.com/a b(c)\\"
    table = _between(render_markdown(run), "## Sources", "## Coverage limits")
    assert "[Investor page](https://investor.example.com/a%20b%28c%29%5C)" in table
    claims = _between(render_markdown(run), "## Claims", "## Unknowns")
    assert f"[NVIDIA 10-Q for the period ended 2026-07-26]({URL}#:~:text=Data%20Center)" in claims
