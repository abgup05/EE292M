"""Triage: whether a new filing bears on any claim of a thesis, decided by rule, no model."""

from __future__ import annotations

from collections.abc import Sequence

from app.core import watch_policy as wording
from app.core.change_models import (
    ChangeCounts,
    FilingChanges,
    FilingSide,
    ItemChanges,
    Paragraph,
)
from app.core.documents import FilingRef
from app.core.models import Claim
from app.core.triage import thesis_claims, triage, watched_filing
from app.core.watch_models import TriageRule, WatchedFiling
from tests.fakes import NVIDIA, current_report_ref, synthetic_ref

LEAVING = "Buy because Jane Smith is gone."
GROWTH = "Data center revenue is still growing year over year."
SUPPLY = "The company depends on a limited number of suppliers."


def claims(*texts: str) -> list[Claim]:
    return thesis_claims(list(texts))


def eight_k(*items: str, form: str = "8-K") -> WatchedFiling:
    return watched_filing(current_report_ref(7, "2026-11-12", *items, form=form))


def test_a_leadership_8k_bears_on_the_claim_about_a_name_leaving_and_says_why() -> None:
    result = triage(claims(LEAVING, GROWTH), eight_k("5.02", "9.01"))

    assert result.bears
    assert result.rules == [TriageRule.event_category]
    first, second = result.claims
    assert first.bears and first.categories == ["leadership"]
    assert "Item 5.02" in first.reasons[0] and "leadership" in first.reasons[0]
    assert not second.bears and second.reasons == []
    assert result.summary == "It bears on 1 of 2 claims."


def test_an_exhibits_only_8k_bears_on_nothing_and_is_called_routine() -> None:
    result = triage(claims(LEAVING, GROWTH), eight_k("9.01"))

    assert not result.bears
    assert result.rules == [TriageRule.routine]
    assert "exhibits only" in result.summary
    assert not any(claim.bears for claim in result.claims)


def test_a_vote_is_routine_even_for_a_claim_about_leadership() -> None:
    result = triage(claims(LEAVING), eight_k("5.07"))

    assert not result.bears
    assert result.rules == [TriageRule.routine]
    assert "shareholder vote" in result.summary


def test_results_announced_bear_on_every_claim_with_the_fixed_reason() -> None:
    result = triage(claims(LEAVING, GROWTH, SUPPLY), eight_k("2.02", "9.01"))

    assert result.bears
    assert result.rules == [TriageRule.results_announced]
    assert all(claim.bears for claim in result.claims)
    assert all(wording.REASON_RESULTS in claim.reasons for claim in result.claims)


def test_a_substantive_8k_on_no_claim_subject_bears_on_nothing_and_names_its_subject() -> None:
    result = triage(claims(LEAVING, GROWTH), eight_k("1.01"))

    assert not result.bears
    assert result.rules == [TriageRule.no_match]
    assert "Item 1.01" in result.summary and "material agreement" in result.summary


def test_an_8k_whose_index_lists_no_items_is_not_ruled_out() -> None:
    result = triage(claims(LEAVING, GROWTH), eight_k())

    assert result.bears
    assert result.rules == [TriageRule.no_items]
    assert all(wording.REASON_NO_ITEMS in claim.reasons for claim in result.claims)


def test_an_amended_8k_is_triaged_like_an_8k() -> None:
    result = triage(claims(LEAVING), eight_k("5.02", form="8-K/A"))

    assert result.bears and result.claims[0].bears


def _comparison(later: FilingRef, *added: str) -> FilingChanges:
    side = {
        "form": later.form,
        "period_end": later.period_end,
        "filed_date": later.filed_date,
        "url": later.url,
        "title": "NVIDIA CORP 10-Q",
        "item_coverage": 1.0,
    }
    item = ItemChanges(
        item="Item 2. Management's Discussion and Analysis",
        present_in="both",
        added=len(added),
        added_paragraphs=[
            Paragraph(text=text, locator="Item 2", start=0, link=f"{later.url}#p{n}")
            for n, text in enumerate(added)
        ],
    )
    return FilingChanges(
        company=NVIDIA,
        earlier=FilingSide(accession="0009999999-26-000001", **side),
        later=FilingSide(accession=later.accession, **side),
        items=[item],
        totals=ChangeCounts(added=len(added)),
    )


def test_a_new_quarterly_report_bears_on_every_claim_and_names_its_paragraphs() -> None:
    ref = synthetic_ref(3, "10-Q")
    comparison = _comparison(
        ref,
        "Data Center revenue was $89.0 billion, up 117% from a year ago, still growing.",
        "We depend on a limited number of suppliers for wafers and memory.",
        "The weather was mild.",
    )

    result = triage(claims(LEAVING, GROWTH, SUPPLY), watched_filing(ref), comparison)

    assert result.bears
    assert result.rules == [TriageRule.periodic_report]
    assert all(claim.bears for claim in result.claims)
    assert all(
        wording.REASON_PERIODIC.format(form="10-Q") in claim.reasons for claim in result.claims
    )
    leaving, growth, supply = result.claims
    assert leaving.paragraphs == []
    assert wording.REASON_NO_PARAGRAPHS in leaving.reasons
    assert [p.text[:20] for p in growth.paragraphs] == ["Data Center revenue "]
    assert growth.paragraphs[0].link == f"{ref.url}#p0"
    assert [p.text[:10] for p in supply.paragraphs] == ["We depend "]
    assert "1 changed paragraph of it shares words with this claim." in supply.reasons


def test_a_new_annual_report_bears_without_a_comparison_and_says_why_none_is_named() -> None:
    ref = synthetic_ref(4, "10-K")

    result = triage(claims(GROWTH), watched_filing(ref), None, notes=["EDGAR answered HTTP 503"])

    assert result.bears and result.claims[0].bears
    assert result.claims[0].paragraphs == []
    assert result.notes == [wording.NOTE_NO_COMPARISON.format(reason="EDGAR answered HTTP 503")]


def test_the_extension_point_adds_a_reason_and_makes_a_routine_filing_bear() -> None:
    def flipped(thesis: Sequence[Claim], filing: WatchedFiling) -> list[tuple[str, str]]:
        return [(thesis[1].id, "A compiled claim's computed outcome flipped.")]

    result = triage(claims(LEAVING, GROWTH), eight_k("9.01"), extra_rules=[flipped])

    assert result.bears
    assert result.rules == [TriageRule.routine, TriageRule.extension]
    assert not result.claims[0].bears
    assert result.claims[1].reasons == ["A compiled claim's computed outcome flipped."]


def test_the_filing_label_names_form_date_and_items() -> None:
    assert eight_k("5.02", "9.01").label == "8-K of 12 Nov 2026, Items 5.02 and 9.01"
    assert watched_filing(synthetic_ref(3, "10-Q")).label == "10-Q of 15 Mar 2026"


def test_claims_take_their_queries_from_the_latest_run_by_text() -> None:
    made = thesis_claims([LEAVING, GROWTH], {GROWTH.casefold(): ["data center growth"]})

    assert [claim.id for claim in made] == ["c1", "c2"]
    assert made[1].queries == ["data center growth"]
    assert made[0].categories == ["leadership"]
