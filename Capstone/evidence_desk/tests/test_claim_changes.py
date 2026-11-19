"""Which changed filing paragraphs bear on which claim of a run (keyword retrieval, no model).

The first half tests the pure ranking (:mod:`app.core.claim_changes`) on hand-built
comparisons; the second the use case (:mod:`app.services.claim_changes`) on small
synthetic filings read through the cache, as a run reads them.
"""

from __future__ import annotations

import pytest

from app.core.change_models import (
    ChangeCounts,
    FilingChanges,
    FilingSide,
    ItemChanges,
    Paragraph,
    RewordedParagraph,
    TruncatedLists,
)
from app.core.claim_change_models import ClaimChanges, RelevantChange, RunChanges
from app.core.claim_changes import MAX_CHANGES_PER_CLAIM, MIN_SHARED_TERMS, relevant_changes
from app.core.documents import FilingRef, FormListing
from app.core.models import Claim, Company, Run, RunStatus, Source, ThesisRequest
from app.core.ports import SourceError
from app.services.claim_changes import run_changes
from app.services.ingest import PARSER_VERSION, _read_filing
from app.store import FilingCache
from tests.fakes import (
    NVIDIA,
    RETRIEVED_AT,
    FakeFilings,
    FormFakeFilings,
    filing_html,
    synthetic_ref,
)

LATER_URL = "https://www.sec.gov/Archives/edgar/data/1045810/later.htm"
EARLIER_URL = "https://www.sec.gov/Archives/edgar/data/1045810/earlier.htm"

CHINA = Claim(
    id="china",
    text="Export controls on data center sales to China will not hurt revenue growth.",
    queries=["export controls China data center sales"],
)
MARGIN = Claim(
    id="margin",
    text="Gross margin will stay above seventy percent as component costs fall.",
    queries=["gross margin component costs"],
)


# Building comparisons by hand -----------------------------------------------------------------


def _paragraph(text: str, url: str = LATER_URL, start: int = 0) -> Paragraph:
    return Paragraph(
        text=text, locator="Item", start=start, link=f"{url}#:~:text=x", link_kind="passage"
    )


def _pair(before: str, after: str) -> RewordedParagraph:
    return RewordedParagraph(
        before=_paragraph(before, EARLIER_URL),
        after=_paragraph(after),
        similarity=0.8,
        segments=[],
    )


def _item(
    name: str,
    *,
    added: tuple[str, ...] = (),
    removed: tuple[str, ...] = (),
    reworded: tuple[tuple[str, str], ...] = (),
    numbers_only: tuple[tuple[str, str], ...] = (),
) -> ItemChanges:
    return ItemChanges(
        item=name,
        present_in="both",
        added_paragraphs=[_paragraph(text, start=n) for n, text in enumerate(added)],
        removed_paragraphs=[_paragraph(text, EARLIER_URL, n) for n, text in enumerate(removed)],
        reworded_paragraphs=[_pair(before, after) for before, after in reworded],
        numbers_only_paragraphs=[_pair(before, after) for before, after in numbers_only],
    )


def _side(form: str, url: str) -> FilingSide:
    return FilingSide(
        form=form,
        period_end="2026-01-25",
        filed_date="2026-02-25",
        accession=url,
        url=url,
        title=f"NVIDIA CORP {form}",
        item_coverage=1.0,
    )


def _comparison(form: str, *items: ItemChanges) -> FilingChanges:
    return FilingChanges(
        company=NVIDIA,
        earlier=_side(form, EARLIER_URL),
        later=_side(form, LATER_URL),
        items=list(items),
        totals=ChangeCounts(),
    )


def _searched(change: RelevantChange) -> str:
    """The text that was searched: the paragraph, or the later paragraph of a pair."""
    if change.paragraph is not None:
        return change.paragraph.text
    assert change.pair is not None
    return change.pair.after.text


def _texts(result: ClaimChanges) -> list[str]:
    return [_searched(change) for change in result.changes]


# The pure ranking -----------------------------------------------------------------------------

ONE_TERM = "Our gross profit was affected by inventory provisions and warranty charges this year."
ONE_TERM_AND_A_YEAR = (
    "In fiscal year 2026 the margin on legacy products reflected inventory provisions."
)
TWO_TERMS = "Gross margin was affected by inventory provisions and warranty charges this year."


def test_the_rule_and_cap_are_the_documented_constants() -> None:
    assert (MIN_SHARED_TERMS, MAX_CHANGES_PER_CLAIM) == (2, 5)


def test_a_paragraph_sharing_fewer_than_two_content_terms_is_not_listed() -> None:
    claim = Claim(id="m", text="Gross margin will stay above seventy percent in 2026.")
    item = _item("Item 7", added=(ONE_TERM, ONE_TERM_AND_A_YEAR, TWO_TERMS))
    comparison = _comparison("10-K", item)
    [result] = relevant_changes([claim], [comparison])
    assert _texts(result) == [TWO_TERMS]
    assert result.changes[0].matched_terms == ["gross", "margin"]
    assert (result.considered, result.matched) == (3, 1)


CAP_TERMS = "data center revenue depends demand accelerated computing platforms".split()
FILLER = "quarterly filings describe several matters relating ordinary course".split()


def _sharing(count: int) -> str:
    """A ten-word paragraph holding the first ``count`` claim words, the rest filler."""
    return " ".join(CAP_TERMS[:count] + FILLER[: 10 - count]).capitalize() + "."


def test_at_most_five_are_listed_best_first() -> None:
    claim = Claim(
        id="dc", text="Data center revenue depends on demand for accelerated computing platforms."
    )
    order = (2, 5, 8, 1, 3, 6, 4, 7)
    comparison = _comparison("10-Q", _item("Item 2", added=tuple(_sharing(k) for k in order)))
    [result] = relevant_changes([claim], [comparison])
    assert _texts(result) == [_sharing(k) for k in (8, 7, 6, 5, 4)]
    scores = [change.score for change in result.changes]
    assert scores == sorted(scores, reverse=True) and len(set(scores)) == 5
    assert (result.considered, result.matched) == (8, 7)


def test_equal_scores_keep_filing_order_and_the_result_is_deterministic() -> None:
    claim = Claim(id="m", text="Gross margin will stay above seventy percent.")
    comparisons = [
        _comparison("10-K", _item("Item 1", added=(TWO_TERMS,))),
        _comparison("10-Q", _item("Item 2", added=(TWO_TERMS,), removed=(TWO_TERMS,))),
    ]
    [result] = relevant_changes([claim], comparisons)
    assert [(c.form, c.item, c.kind) for c in result.changes] == [
        ("10-K", "Item 1", "added"),
        ("10-Q", "Item 2", "added"),
        ("10-Q", "Item 2", "removed"),
    ]
    assert len({change.score for change in result.changes}) == 1
    assert relevant_changes([claim], comparisons) == [result]


def test_considered_and_matched_count_every_changed_paragraph_searched() -> None:
    comparisons = [
        _comparison(
            "10-K",
            _item(
                "Item 7",
                added=(TWO_TERMS, ONE_TERM),
                removed=("Gross margin declined in the year because component costs rose.",),
            ),
        ),
        _comparison(
            "10-Q",
            _item(
                "Item 2",
                reworded=(
                    (
                        "Component costs supported margin in the quarter.",
                        "Lower component costs supported margin expansion in the quarter.",
                    ),
                ),
                numbers_only=(
                    (
                        "Inventory provisions were $1.1 billion in the quarter.",
                        "Inventory provisions were $1.2 billion in the quarter.",
                    ),
                ),
            ),
        ),
    ]
    [result] = relevant_changes([MARGIN], comparisons)
    assert (result.considered, result.matched) == (5, 3)
    assert sorted((c.form, c.kind) for c in result.changes) == [
        ("10-K", "added"),
        ("10-K", "removed"),
        ("10-Q", "reworded"),
    ]
    reworded = next(c for c in result.changes if c.kind == "reworded")
    assert reworded.paragraph is None and reworded.pair is not None
    assert reworded.matched_terms == ["component", "cost", "margin"]


def test_swapping_two_claims_swaps_their_lists() -> None:
    comparison = _comparison(
        "10-K",
        _item(
            "Item 1A",
            added=(
                "The government expanded export controls on data center sales to China.",
                TWO_TERMS,
            ),
            removed=("Gross margin declined in the year because component costs rose.",),
        ),
    )
    forward = relevant_changes([CHINA, MARGIN], [comparison])
    backward = relevant_changes([MARGIN, CHINA], [comparison])
    assert [r.claim_id for r in forward] == ["china", "margin"]
    assert [r.claim_id for r in backward] == ["margin", "china"]
    assert forward == list(reversed(backward))
    assert _texts(forward[0]) != _texts(forward[1])
    assert forward[0].changes and forward[1].changes


def test_a_comparison_whose_lists_were_cut_is_refused() -> None:
    cut = _item("Item 1A", added=(TWO_TERMS,))
    cut.truncated = TruncatedLists(added=True)
    with pytest.raises(ValueError, match="every changed paragraph"):
        relevant_changes([MARGIN], [_comparison("10-K", cut)])


def test_a_pair_repeated_under_two_items_is_listed_once_and_near_twins_are_kept_apart() -> None:
    before = "Component costs supported margin in the quarter."
    after = "Lower component costs supported margin expansion in the quarter."
    comparisons = [
        _comparison(
            "10-K",
            _item("Item 1", reworded=((before, after),), added=(TWO_TERMS, TWO_TERMS)),
            _item(
                "Item 7",
                reworded=(
                    (" ".join(before.upper().split()), after.lower()),
                    ("Component costs and margin were stable in the quarter.", after),
                ),
                removed=(TWO_TERMS,),
            ),
        ),
        _comparison("10-Q", _item("Item 2", added=(TWO_TERMS,))),
    ]
    [result] = relevant_changes([MARGIN], comparisons)
    listed = [(c.form, c.item, c.kind, c.also_under) for c in result.changes]
    # The same pair under Item 7 joins Item 1's entry; a pair with another earlier text, the
    # same text removed rather than added, and the same text in the 10-Q stay separate.
    assert sorted(listed) == [
        ("10-K", "Item 1", "added", []),
        ("10-K", "Item 1", "reworded", ["Item 7"]),
        ("10-K", "Item 7", "removed", []),
        ("10-K", "Item 7", "reworded", []),
        ("10-Q", "Item 2", "added", []),
    ]
    assert (result.considered, result.matched, result.distinct_matched) == (7, 7, 5)


DUPLICATED = _sharing(8)


def test_a_paragraph_added_under_two_items_takes_one_place_and_frees_the_other() -> None:
    claim = Claim(
        id="dc", text="Data center revenue depends on demand for accelerated computing platforms."
    )
    others = [_sharing(k) for k in (3, 7, 4, 6, 5)]
    filings = FormFakeFilings(
        refs=[K_RUN, K_EARLIER],
        documents={
            K_EARLIER.url: annual([KEEP], [FIGURES_BEFORE]),
            K_RUN.url: annual(
                [KEEP, DUPLICATED, *others[:2]],
                [FIGURES_BEFORE, *others[2:], DUPLICATED.upper()],
            ),
        },
    )
    cache = FilingCache()
    run = finished_run(filings, cache, read=(K_RUN,), claims=(claim,))
    [result] = run_changes(run, filings=filings, cache=cache).claims
    assert _texts(result) == [DUPLICATED, *(_sharing(k) for k in (7, 6, 5, 4))]
    first = result.changes[0]
    assert (first.item, first.also_under) == (
        "Item 1A. Risk Factors",
        ["Item 7. Management's Discussion and Analysis"],
    )
    assert [change.also_under for change in result.changes[1:]] == [[]] * 4
    assert (result.considered, result.matched, result.distinct_matched) == (7, 7, 6)


# The use case on synthetic filings ------------------------------------------------------------

KEEP = (
    "We depend on third-party foundries to manufacture our semiconductor wafers, and any "
    "disruption in their capacity could delay our product shipments to customers."
)
CHINA_ADDED = (
    "In the fourth quarter the United States government expanded export controls on sales "
    "of our data center products to customers in China."
)
MARGIN_REMOVED = (
    "Our gross margin benefited from lower component costs and a favorable mix of products "
    "sold during the year."
)
FIGURES_BEFORE = (
    "Gross margin was 75.0% of revenue in fiscal year 2025 compared with 72.7% in fiscal year 2024."
)
FIGURES_AFTER = (
    "Gross margin was 71.1% of revenue in fiscal year 2026 compared with 75.0% in fiscal year 2025."
)
LICENSE_BEFORE = (
    "Sales of our data center products to customers in China require a license under "
    "United States export controls."
)
LICENSE_AFTER = (
    "Sales of our data center products to customers in China now require a license under "
    "new United States export controls and may decline."
)
NEWER_ONLY = (
    "Export controls on data center sales to China were lifted in full by the government "
    "this quarter, and revenue growth resumed."
)

K_EARLIER, K_RUN = synthetic_ref(1, "10-K"), synthetic_ref(2, "10-K")
Q_OLDEST, Q_EARLIER, Q_RUN = synthetic_ref(3), synthetic_ref(4), synthetic_ref(5)
K_NEWER, Q_NEWER = synthetic_ref(6, "10-K"), synthetic_ref(7)
K_NEWEST = synthetic_ref(8, "10-K")


def annual(risks: list[str], results: list[str]) -> str:
    """A minimal 10-K primary document with Items 1A and 7."""

    def body(texts: list[str]) -> str:
        return "".join(f"<p>{text}</p>" for text in texts)

    return (
        "<html><body><p>PART I</p><p><b>Item 1A. Risk Factors</b></p>"
        f"{body(risks)}<p>PART II</p><p><b>Item 7. Management's Discussion and Analysis</b></p>"
        f"{body(results)}</body></html>"
    )


def filings_of_a_year(*extra: FilingRef) -> FormFakeFilings:
    """A 10-K and a 10-Q the run read, each with the filing of its form before it."""
    documents: dict[str, str | SourceError] = {
        K_EARLIER.url: annual([KEEP, MARGIN_REMOVED], [FIGURES_BEFORE]),
        K_RUN.url: annual([KEEP, CHINA_ADDED], [FIGURES_AFTER]),
        Q_OLDEST.url: filing_html(KEEP),
        Q_EARLIER.url: filing_html(LICENSE_BEFORE),
        Q_RUN.url: filing_html(LICENSE_AFTER),
        K_NEWER.url: annual([KEEP, NEWER_ONLY], [FIGURES_AFTER]),
        Q_NEWER.url: filing_html(NEWER_ONLY),
    }
    return FormFakeFilings(refs=[Q_RUN, Q_EARLIER, K_RUN, K_EARLIER, *extra], documents=documents)


def finished_run(
    filings: FakeFilings,
    cache: FilingCache,
    read: tuple[FilingRef, ...] = (Q_RUN, K_RUN),
    claims: tuple[Claim, ...] = (CHINA, MARGIN),
) -> Run:
    """A finished run that read ``read`` through ``cache``, as ingest records them."""
    sources: list[Source] = []
    for number, ref in enumerate(read, start=1):
        source, document, _ = _read_filing(f"S{number}", ref, NVIDIA, filings, cache)
        assert document is not None
        cache.put_text(document.content_hash, document.text)
        sources.append(source)
    return Run(
        id="run-1",
        inputs=ThesisRequest(
            ticker="NVDA", decision="Hold NVIDIA through 2027.", claims=[c.text for c in claims]
        ),
        status=RunStatus.complete,
        started_at=RETRIEVED_AT,
        finished_at=RETRIEVED_AT,
        company=NVIDIA,
        claims=list(claims),
        sources=sources,
    )


def _by_claim(result: RunChanges) -> dict[str, ClaimChanges]:
    return {claims.claim_id: claims for claims in result.claims}


def _listed(claims: ClaimChanges) -> set[tuple[str, str, str]]:
    return {(change.kind, change.form, _searched(change)) for change in claims.changes}


def test_exit_check_a_planted_china_paragraph_reaches_the_china_claim_only() -> None:
    cache = FilingCache()
    filings = filings_of_a_year()
    result = run_changes(finished_run(filings, cache), filings=filings, cache=cache)
    claims = _by_claim(result)
    china = [c for c in claims["china"].changes if c.paragraph and c.paragraph.text == CHINA_ADDED]
    assert len(china) == 1
    assert china[0].kind == "added" and china[0].form == "10-K"
    assert china[0].item == "Item 1A. Risk Factors"
    assert {"china", "control", "export"} <= set(china[0].matched_terms)
    assert CHINA_ADDED not in _texts(claims["margin"])
    assert result.notes == []


def test_each_kind_reaches_the_right_claim_with_its_own_filing_link() -> None:
    cache = FilingCache()
    filings = filings_of_a_year()
    result = run_changes(finished_run(filings, cache), filings=filings, cache=cache)
    assert result.run_id == "run-1"
    assert [(c.form, c.earlier.accession, c.later.accession) for c in result.compared] == [
        ("10-K", K_EARLIER.accession, K_RUN.accession),
        ("10-Q", Q_EARLIER.accession, Q_RUN.accession),
    ]
    claims = _by_claim(result)
    assert [c.claim_id for c in result.claims] == ["china", "margin"]
    assert _listed(claims["china"]) == {
        ("added", "10-K", CHINA_ADDED),
        ("reworded", "10-Q", LICENSE_AFTER),
    }
    assert _listed(claims["margin"]) == {
        ("removed", "10-K", MARGIN_REMOVED),
        ("numbers_only", "10-K", FIGURES_AFTER),
    }
    for change in claims["china"].changes + claims["margin"].changes:
        if change.paragraph is not None:
            filing = K_RUN if change.kind == "added" else K_EARLIER
            assert change.paragraph.link.startswith(filing.url + "#")
        else:
            assert change.pair is not None
            earlier, later = (K_EARLIER, K_RUN) if change.form == "10-K" else (Q_EARLIER, Q_RUN)
            assert change.pair.before.text in (LICENSE_BEFORE, FIGURES_BEFORE)
            assert change.pair.before.link.startswith(earlier.url + "#")
            assert change.pair.after.link.startswith(later.url + "#")


def test_every_listed_paragraph_is_an_exact_span_of_its_filing() -> None:
    cache = FilingCache()
    filings = filings_of_a_year()
    result = run_changes(finished_run(filings, cache), filings=filings, cache=cache)

    def stored(url: str) -> str:
        ref = next(ref for ref in filings.refs if ref.url == url)
        cached = cache.lookup_filing(ref.accession, PARSER_VERSION)
        assert cached is not None
        text = cache.get_text(cached.content_hash)
        assert text is not None
        return text

    def check(paragraph: Paragraph) -> None:
        url = paragraph.link.split("#", 1)[0]
        text = stored(url)
        assert text[paragraph.start : paragraph.start + len(paragraph.text)] == paragraph.text

    listed = [change for claims in result.claims for change in claims.changes]
    assert len(listed) == 4
    for change in listed:
        if change.paragraph is not None:
            check(change.paragraph)
        else:
            assert change.pair is not None
            check(change.pair.before)
            check(change.pair.after)


def test_the_run_filing_is_compared_with_the_one_before_it_not_with_the_newest() -> None:
    cache = FilingCache()
    filings = filings_of_a_year(K_NEWER, Q_NEWER, Q_OLDEST)
    run = finished_run(filings, cache)
    result = run_changes(run, filings=filings, cache=cache)
    assert [(c.form, c.earlier.accession, c.later.accession) for c in result.compared] == [
        ("10-K", K_EARLIER.accession, K_RUN.accession),
        ("10-Q", Q_EARLIER.accession, Q_RUN.accession),
    ]
    assert K_NEWER.url not in filings.fetched and Q_NEWER.url not in filings.fetched
    assert Q_OLDEST.url not in filings.fetched
    for claims in result.claims:
        assert NEWER_ONLY not in {text for _, _, text in _listed(claims)}
    assert result.notes == []


def test_the_newest_filing_of_a_form_the_run_read_is_the_later_one() -> None:
    cache = FilingCache()
    filings = filings_of_a_year(Q_OLDEST)
    run = finished_run(filings, cache, read=(Q_EARLIER, Q_RUN, K_RUN))
    result = run_changes(run, filings=filings, cache=cache)
    assert [(c.form, c.later.accession) for c in result.compared] == [
        ("10-K", K_RUN.accession),
        ("10-Q", Q_RUN.accession),
    ]


def test_no_earlier_filing_of_a_form_gives_a_note_and_the_other_form_is_still_compared() -> None:
    cache = FilingCache()
    filings = filings_of_a_year(Q_NEWER)
    filings.refs.remove(Q_EARLIER)
    result = run_changes(finished_run(filings, cache), filings=filings, cache=cache)
    assert [c.form for c in result.compared] == ["10-K"]
    assert len(result.notes) == 1
    note = result.notes[0]
    assert "10-Q" in note and "NVIDIA CORP 10-Q, period ended 2026-05-01" in note
    assert "before" in note
    assert ("added", "10-K", CHINA_ADDED) in _listed(_by_claim(result)["china"])


def test_a_run_filing_no_longer_listed_gives_a_note() -> None:
    cache = FilingCache()
    filings = filings_of_a_year(Q_NEWER, Q_OLDEST)
    run = finished_run(filings, cache)
    filings.refs.remove(Q_RUN)
    result = run_changes(run, filings=filings, cache=cache)
    assert [c.form for c in result.compared] == ["10-K"]
    assert len(result.notes) == 1 and "is not among" in result.notes[0]
    assert "NVIDIA CORP 10-Q, period ended 2026-05-01" in result.notes[0]


def test_a_source_that_cannot_list_filings_of_a_form_gives_a_note_per_form() -> None:
    cache = FilingCache()
    listing = filings_of_a_year()
    plain = FakeFilings(refs=listing.refs, documents=listing.documents)
    result = run_changes(finished_run(plain, cache), filings=plain, cache=cache)
    assert result.compared == []
    assert [(c.claim_id, c.changes, c.considered) for c in result.claims] == [
        ("china", [], 0),
        ("margin", [], 0),
    ]
    assert len(result.notes) == 2
    assert all("cannot list" in note for note in result.notes)
    assert "10-K" in result.notes[0] and "10-Q" in result.notes[1]


def test_an_edgar_failure_gives_a_note_and_no_exception() -> None:
    cache = FilingCache()
    filings = filings_of_a_year()
    run = finished_run(filings, cache)
    filings.index_error = SourceError("EDGAR answered HTTP 503 for the filing index")
    result = run_changes(run, filings=filings, cache=cache)
    assert result.compared == []
    assert len(result.notes) == 2 and all("HTTP 503" in note for note in result.notes)
    assert [c.claim_id for c in result.claims] == ["china", "margin"]


def test_an_earlier_filing_that_cannot_be_fetched_costs_only_its_own_comparison() -> None:
    cache = FilingCache()
    filings = filings_of_a_year()
    filings.documents[K_EARLIER.url] = SourceError("EDGAR answered HTTP 503 for the document")
    result = run_changes(finished_run(filings, cache), filings=filings, cache=cache)
    assert [c.form for c in result.compared] == ["10-Q"]
    assert len(result.notes) == 1
    assert "10-K" in result.notes[0] and "HTTP 503" in result.notes[0]
    assert _listed(_by_claim(result)["china"]) == {("reworded", "10-Q", LICENSE_AFTER)}


def test_a_comparison_that_breaks_costs_only_its_own_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """The third referee, finding 4: "never raises" was promised for EDGAR failures only.

    The comparison raises ValueError when a section is not a span of its document. That
    must be a note on that form, with the other form still compared, not an error for
    the whole request.
    """
    from app.services import claim_changes as service

    real = service.compare_pair

    def breaking(pair, **kwargs):  # type: ignore[no-untyped-def]
        if pair.later_ref.form == "10-K":
            raise ValueError("Section 'Item 1A' is not a substring of its document")
        return real(pair, **kwargs)

    monkeypatch.setattr(service, "compare_pair", breaking)
    cache = FilingCache()
    filings = filings_of_a_year()
    result = run_changes(finished_run(filings, cache), filings=filings, cache=cache)
    assert [c.form for c in result.compared] == ["10-Q"]
    assert len(result.notes) == 1
    assert "10-K" in result.notes[0] and "ValueError" in result.notes[0]
    assert "Item 1A" not in result.notes[0]  # the type is enough; internals stay in the log
    assert _listed(_by_claim(result)["china"]) == {("reworded", "10-Q", LICENSE_AFTER)}


def test_an_unfinished_run_gets_empty_lists_and_a_note() -> None:
    cache = FilingCache()
    filings = filings_of_a_year()
    run = finished_run(filings, cache).model_copy(update={"status": RunStatus.running})
    result = run_changes(run, filings=filings, cache=cache)
    assert result.compared == []
    assert [(c.claim_id, c.changes) for c in result.claims] == [("china", []), ("margin", [])]
    assert len(result.notes) == 1 and "running" in result.notes[0]
    assert filings.form_calls == []


def test_a_run_that_read_no_filing_gets_empty_lists_and_a_note() -> None:
    cache = FilingCache()
    filings = filings_of_a_year()
    run = finished_run(filings, cache, read=()).model_copy(update={"status": RunStatus.failed})
    result = run_changes(run, filings=filings, cache=cache)
    assert result.compared == []
    assert [(c.claim_id, c.changes) for c in result.claims] == [("china", []), ("margin", [])]
    assert len(result.notes) == 1 and "no 10-K or 10-Q" in result.notes[0]
    assert filings.form_calls == []


def test_a_filing_read_differently_from_the_run_gets_a_note() -> None:
    cache = FilingCache()
    filings = filings_of_a_year()
    run = finished_run(filings, cache)
    run.sources[1] = run.sources[1].model_copy(update={"content_hash": "0" * 64})
    result = run_changes(run, filings=filings, cache=cache)
    assert len(result.compared) == 2
    assert result.notes == [
        "NVIDIA CORP 10-K, period ended 2026-02-01 reads differently now than when the run "
        "read it (the parser has changed); its paragraphs are from today's reading."
    ]


def test_without_a_cache_one_in_memory_serves_the_call() -> None:
    cache = FilingCache()
    filings = filings_of_a_year()
    run = finished_run(filings, cache)
    fetched = len(filings.fetched)
    result = run_changes(run, filings=filings)
    assert len(result.compared) == 2
    assert len(filings.fetched) == fetched + 4


# EDGAR's recent index holds two filings of the form and the run read the older (sixth referee,
# finding 4) -----------------------------------------------------------------------------------


class RecentIndexFilings(FormFakeFilings):
    """A source that lists as EDGAR does: ``filings_of_form`` reads the recent index only
    while it holds two filings of the form, whatever ``limit`` asks for. ``recent`` are the
    accessions in the recent index; the other refs are on an older page of the index."""

    recent: frozenset[str] = frozenset()

    def filings_of_form(self, company: Company, form: str, limit: int) -> list[FilingRef]:
        listed = super().filings_of_form(company, form, limit)
        recent = [ref for ref in listed if ref.accession in self.recent]
        return recent[:limit] if len(recent) >= 2 else listed


def recent_index(*recent: FilingRef) -> RecentIndexFilings:
    """The filings of a year plus a newer 10-K; ``recent`` are in the recent index."""
    base = filings_of_a_year(K_NEWER)
    filings = RecentIndexFilings(refs=base.refs, documents=base.documents)
    filings.recent = frozenset(ref.accession for ref in recent)
    return filings


def test_a_source_that_lists_two_newer_filings_does_not_make_edgar_list_no_earlier_one() -> None:
    """The referee's case: the index's recent page holds two 10-Ks, the run read the older,
    and the 10-K before it is on an older page. Until version 14.3 the note said "EDGAR
    lists no 10-K filed before ...", which EDGAR does."""
    cache = FilingCache()
    filings = recent_index(K_NEWER, K_RUN, Q_RUN, Q_EARLIER)
    run = finished_run(filings, cache)
    assert [ref.accession for ref in filings.filings_of_form(NVIDIA, "10-K", 12)] == [
        K_NEWER.accession,
        K_RUN.accession,
    ]
    result = run_changes(run, filings=filings, cache=cache)
    assert [c.form for c in result.compared] == ["10-Q"]
    [note] = result.notes
    assert "EDGAR lists no" not in note
    assert "none of the 2 latest 10-K filings listed was filed before" in note


class DeepIndexFilings(RecentIndexFilings):
    """The same source, able to read the older pages as EdgarClient.filings_back_to does."""

    back_to_calls: list[tuple[str, str]]
    pages_left_unread: bool = False

    def filings_back_to(self, company: Company, form: str, accession: str) -> FormListing:
        self.back_to_calls.append((form, accession))
        refs = FormFakeFilings.filings_of_form(self, company, form, 1000)
        if self.pages_left_unread:
            refs = [ref for ref in refs if ref.accession in self.recent]
        where = "EDGAR's recent index and the 1 newest of its 1 older index pages"
        if self.pages_left_unread:
            where = "EDGAR's recent index and the 12 newest of its 14 older index pages"
        return FormListing(refs=refs, where=where, complete=not self.pages_left_unread)


def deep_index(*recent: FilingRef, drop: tuple[FilingRef, ...] = ()) -> DeepIndexFilings:
    base = filings_of_a_year(K_NEWER)
    refs = [ref for ref in base.refs if ref not in drop]
    filings = DeepIndexFilings(refs=refs, documents=base.documents)
    filings.recent = frozenset(ref.accession for ref in recent)
    filings.back_to_calls = []
    return filings


def test_the_earlier_filing_is_sought_on_older_pages_when_the_listing_ends_at_the_runs() -> None:
    cache = FilingCache()
    filings = deep_index(K_NEWER, K_RUN, Q_RUN, Q_EARLIER)
    run = finished_run(filings, cache)
    result = run_changes(run, filings=filings, cache=cache)
    assert [(c.form, c.earlier.accession, c.later.accession) for c in result.compared] == [
        ("10-K", K_EARLIER.accession, K_RUN.accession),
        ("10-Q", Q_EARLIER.accession, Q_RUN.accession),
    ]
    assert result.notes == []
    # Only the form whose listing ended at the run's filing cost the deeper search.
    assert filings.back_to_calls == [("10-K", K_RUN.accession)]


def test_edgar_lists_no_earlier_filing_is_said_only_after_the_whole_index_was_read() -> None:
    cache = FilingCache()
    whole = deep_index(K_NEWER, K_RUN, Q_RUN, Q_EARLIER, drop=(K_EARLIER,))
    run = finished_run(whole, cache)
    [note] = run_changes(run, filings=whole, cache=cache).notes
    assert note.startswith("No 10-K comparison: EDGAR lists no 10-K filed before NVIDIA CORP 10-K")
    capped = deep_index(K_NEWER, K_RUN, Q_RUN, Q_EARLIER)
    capped.pages_left_unread = True
    [note] = run_changes(finished_run(capped, cache), filings=capped, cache=cache).notes
    assert "EDGAR lists no" not in note
    assert "no 10-K filed before" in note
    assert "EDGAR's recent index and the 12 newest of its 14 older index pages" in note


def test_a_run_filing_older_than_the_listing_is_sought_on_the_older_pages() -> None:
    """An as-of run on an older 10-K: the recent index holds two newer ones."""
    cache = FilingCache()
    filings = deep_index(K_NEWER, K_RUN, Q_RUN, Q_EARLIER)
    filings.refs.append(K_NEWEST)
    filings.documents[K_NEWEST.url] = annual([KEEP, NEWER_ONLY], [FIGURES_AFTER])
    recent = (K_NEWEST, K_NEWER, Q_RUN, Q_EARLIER)
    filings.recent = frozenset(ref.accession for ref in recent)
    run = finished_run(filings, cache)
    result = run_changes(run, filings=filings, cache=cache)
    assert ("10-K", K_EARLIER.accession, K_RUN.accession) in [
        (c.form, c.earlier.accession, c.later.accession) for c in result.compared
    ]
    assert result.notes == []
