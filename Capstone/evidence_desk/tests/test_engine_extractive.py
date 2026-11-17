"""The credential-free engine: quotes exact sentences, judges no stance, invents nothing."""

from app.core.documents import Passage
from app.core.models import (
    Claim,
    Company,
    Confidence,
    Finding,
    Stance,
    ThesisRequest,
    Verdict,
)
from app.core.ports import Analyst, Quote
from app.core.text import tokenize
from app.engines.extractive import ExtractiveAnalyst

REQUEST = ThesisRequest(
    ticker="NVDA",
    decision="Keep the position into the next earnings report",
    claims=["Data center revenue is still growing", "A few customers account for most revenue"],
)
COMPANY = Company(cik=1045810, ticker="NVDA", name="NVIDIA CORP")
CLAIM = Claim(id="c-1", text="Data center revenue is still growing")
PASSAGES = [
    Passage(
        id="src-1-p1",
        source_id="src-1",
        locator="Part I, Item 2",
        text=(
            "Revenue overview.\n"
            "Data Center revenue grew 56% from a year ago, led by Blackwell systems.  "
            "Gaming was flat in the quarter compared with the prior year.\n"
            "Data Center compute revenue grew on strong demand from cloud providers."
        ),
        start=100,
    ),
    Passage(
        id="src-2-p4",
        source_id="src-2",
        locator="Part II, Item 1A",
        text=(
            "Our data center business is still growing, but export rules could limit sales. "
            "Short. " + "Revenue " * 80 + "grew."
        ),
        start=0,
    ),
]


def test_satisfies_the_analyst_protocol() -> None:
    engine: Analyst = ExtractiveAnalyst()
    assert engine.name == "extractive"


def test_plan_gives_one_content_query_per_claim() -> None:
    plan = ExtractiveAnalyst().plan(REQUEST, COMPANY)
    assert len(plan) == len(REQUEST.claims)
    assert all(len(queries) == 1 for queries in plan)
    assert plan[0] == ["Data center revenue still growing"]
    for claim, [query] in zip(REQUEST.claims, plan, strict=True):
        assert set(tokenize(query)) == set(tokenize(claim))


def test_assess_quotes_best_matching_exact_sentences_without_a_stance() -> None:
    draft = ExtractiveAnalyst().assess(REQUEST, COMPANY, CLAIM, PASSAGES)
    assert 1 <= len(draft.findings) <= 3
    by_id = {p.id: p for p in PASSAGES}
    for finding in draft.findings:
        assert finding.stance == Stance.context
        assert finding.confidence == Confidence.low
        assert finding.rationale == (
            "Quoted by keyword overlap with the claim; no stance was judged."
        )
        [quote] = finding.quotes
        assert isinstance(quote, Quote)
        assert quote.text in by_id[quote.passage_id].text
        assert 40 <= len(quote.text) <= 400
        assert finding.statement == f"The filing states: {quote.text}"
        overlap = set(tokenize(quote.text)) & set(tokenize(CLAIM.text))
        assert len(overlap) >= 2
    quoted = [f.quotes[0].text for f in draft.findings]
    assert quoted[0] == (
        "Our data center business is still growing, but export rules could limit sales."
    )
    assert "Gaming was flat in the quarter compared with the prior year." not in quoted
    assert all("Revenue Revenue" not in text for text in quoted)  # over 400 characters


def test_statement_is_truncated_but_quote_is_not() -> None:
    sentence = (
        "Data center revenue growth "
        + "continued strongly across regions " * 10
        + "and stayed firm through the year."
    )
    assert 380 < len(sentence) <= 400
    passage = Passage(id="p", source_id="s", locator="L", text=sentence, start=0)
    [finding] = ExtractiveAnalyst().assess(REQUEST, COMPANY, CLAIM, [passage]).findings
    assert finding.quotes[0].text == sentence
    assert len(finding.statement) <= 400
    assert finding.statement.startswith("The filing states: Data center revenue growth")


def test_no_qualifying_sentence_gives_an_empty_draft() -> None:
    passage = Passage(
        id="p",
        source_id="s",
        locator="L",
        text="The company operates a fleet of delivery vehicles in many regions worldwide.",
        start=0,
    )
    draft = ExtractiveAnalyst().assess(REQUEST, COMPANY, CLAIM, [passage])
    assert draft.findings == []
    assert draft.rationale == (
        "No sentence in the retrieved passages shares enough terms with the claim."
    )
    assert ExtractiveAnalyst().assess(REQUEST, COMPANY, CLAIM, []).findings == []


def test_assess_is_deterministic() -> None:
    engine = ExtractiveAnalyst()
    assert engine.assess(REQUEST, COMPANY, CLAIM, PASSAGES) == engine.assess(
        REQUEST, COMPANY, CLAIM, PASSAGES
    )


def test_summary_is_a_template_from_counts() -> None:
    claims = [
        Claim(id="c-1", text="x" * 20, verdict=Verdict.unjudged),
        Claim(id="c-2", text="y" * 20, verdict=Verdict.not_addressed),
        Claim(id="c-3", text="z" * 20, verdict=Verdict.unjudged),
    ]
    findings = [
        Finding(
            id=f"f-{n}",
            claim_id=claim_id,
            statement="The filing states: something",
            stance=Stance.context,
            evidence_ids=["e-1"],
            confidence=Confidence.low,
            rationale="r",
            verified=verified,
        )
        for n, (claim_id, verified) in enumerate(
            [("c-1", True), ("c-1", True), ("c-2", False), ("c-3", True)]
        )
    ]
    summary = ExtractiveAnalyst().summarize(REQUEST, COMPANY, claims, findings)
    assert summary.summary == (
        "Verdicts across 3 claims — Passages found, not judged: 2; Not addressed: 1. "
        "No engine judged the stance of the passages found for 2 claim(s), so read those "
        "excerpts before relying on them."
    )
    assert "something" not in summary.summary
    assert any("model key" in step for step in summary.next_steps)


def test_summary_of_judged_verdicts_does_not_call_them_unjudged() -> None:
    """A model-assessed run whose summary step fell back keeps its judged verdicts."""
    claims = [
        Claim(id="c-1", text="x" * 20, verdict=Verdict.supported),
        Claim(id="c-2", text="y" * 20, verdict=Verdict.challenged),
        Claim(id="c-3", text="z" * 20, verdict=Verdict.supported),
        Claim(id="c-4", text="w" * 20, verdict=None),
    ]
    summary = ExtractiveAnalyst().summarize(REQUEST, COMPANY, claims, [])
    assert summary.summary == (
        "Verdicts across 4 claims — Supported: 2; Challenged: 1; Not assessed: 1."
    )
    assert not any("model key" in step for step in summary.next_steps)
    assert summary.next_steps
