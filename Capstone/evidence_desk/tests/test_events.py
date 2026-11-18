"""The pure rules about current reports (8-K): items, splitting, claims, supersession, wording."""

from __future__ import annotations

from datetime import date

import pytest

from app.core import events, limits
from app.core.event_models import Event, EventCounts, EventItem, EventStatus
from app.core.events import Category
from app.sources.current_report import parse_current_report
from tests.fakes import recorded_html

RESIGNATION = "nvda-8k-0001045810-26-000082.htm.gz"
RETIREMENT = "nvda-8k-0001045810-26-000026.htm.gz"


def event(
    filed: str,
    *numbers: str,
    status: EventStatus = EventStatus.read,
    found: bool = True,
    accession: str | None = None,
) -> Event:
    items = [events.describe_item(number) for number in numbers]
    for item in items:
        item.found = found and status == EventStatus.read
        item.locator = f"Item {item.number}. {item.title}" if item.found else ""
    return Event(
        id=f"ev-{accession or filed}",
        form="8-K",
        accession=accession or f"0001045810-26-{filed.replace('-', '')}",
        filed_date=filed,
        event_date=filed,
        filed_label=events.day_label(filed),
        url=f"https://www.sec.gov/{filed}.htm",
        items=items,
        categories=[category.value for category in events.event_categories(numbers)],
        substantive=events.is_substantive(events.event_categories(numbers)),
        status=status,
    )


# The table of items


def test_the_table_holds_every_item_from_1_01_to_9_01_with_sec_titles() -> None:
    assert events.ITEMS["1.01"] == ("Entry into a Material Definitive Agreement", Category.deal)
    assert events.ITEMS["9.01"] == ("Financial Statements and Exhibits", Category.exhibits)
    assert events.ITEMS["5.02"][0].startswith("Departure of Directors or Certain Officers")
    assert len(events.ITEMS) == 34
    assert min(events.ITEMS) == "1.01"
    assert max(events.ITEMS) == "9.01"


@pytest.mark.parametrize(
    ("category", "numbers"),
    [
        (Category.leadership, {"5.02"}),
        (Category.accounting, {"4.01", "4.02"}),
        (Category.deal, {"1.01", "1.02", "2.01"}),
        (Category.restructuring, {"2.05", "2.06"}),
        (Category.incident, {"1.05"}),
        (Category.financing, {"2.03", "2.04", "3.02"}),
        (Category.control, {"1.03", "5.01"}),
        (Category.listing, {"3.01"}),
        (Category.results, {"2.02"}),
        (Category.governance, {"5.03", "5.05", "5.07", "5.08", "3.03"}),
        (Category.disclosure, {"7.01", "8.01"}),
        (Category.exhibits, {"9.01"}),
    ],
)
def test_each_category_holds_exactly_its_items(category: Category, numbers: set[str]) -> None:
    assert set(events.items_of(category)) == numbers


def test_the_substantive_categories_are_those_with_a_claim_lexicon() -> None:
    assert set(events.SUBSTANTIVE) == {
        Category.leadership,
        Category.accounting,
        Category.deal,
        Category.restructuring,
        Category.incident,
        Category.financing,
        Category.control,
        Category.listing,
    }
    assert set(events.SUBSTANTIVE) == set(events.CLAIM_LEXICON)


def test_an_item_number_not_in_the_table_is_kept_and_labelled_unknown() -> None:
    item = events.describe_item("7.02")
    assert (item.number, item.known, item.category) == ("7.02", False, Category.other.value)
    assert item.title == events.UNKNOWN_ITEM_TITLE


def test_an_events_categories_follow_the_category_order_each_once() -> None:
    assert events.event_categories(["9.01", "5.02", "7.01", "9.01"]) == [
        Category.leadership,
        Category.disclosure,
        Category.exhibits,
    ]


# Splitting a read 8-K into its items


def test_the_sections_of_a_read_8k_are_found_by_item_number() -> None:
    document = parse_current_report(
        recorded_html(RESIGNATION), url="u", title="t", published_date="2026-11-12"
    )
    sections = events.item_sections(document)
    assert sorted(sections) == ["5.02", "9.01"]
    assert sections["5.02"].text.startswith("On November 11, 2026")


def test_a_heading_of_two_items_gives_both_numbers() -> None:
    assert events.section_numbers("Items 2.02 and 7.01. Results; Disclosure") == ("2.02", "7.01")
    assert events.section_numbers("Item 5.02. Departure") == ("5.02",)
    assert events.section_numbers("Cover page") == ()


def test_opening_sentences_are_exact_slices_and_skip_markers_and_subheadings() -> None:
    text = "(b)\nAdoption of a Plan\nOn June 1, the CFO resigned. A successor was named. More."
    opening = events.opening_sentences(text, 2)
    assert opening == ["On June 1, the CFO resigned.", "A successor was named."]
    assert all(sentence in text for sentence in opening)


def test_opening_sentences_are_capped_by_the_limit() -> None:
    text = " ".join(f"Sentence number {n} is here." for n in range(10))
    assert len(events.opening_sentences(text)) == limits.EVENT_OPENING_SENTENCES


def test_the_roles_of_the_resignation_are_named_in_order_and_once() -> None:
    document = parse_current_report(
        recorded_html(RESIGNATION), url="u", title="t", published_date="2026-11-12"
    )
    roles = events.officer_roles(events.item_sections(document)["5.02"].text)
    assert roles == [
        "President",
        "Chief Executive Officer",
        "Director",
        "Executive Vice President",
        "Chief Financial Officer",
        "Chair",
    ]


def test_roles_are_whole_words_and_a_vice_president_is_no_president() -> None:
    assert events.officer_roles("The Vice President of Presidential Affairs left.") == [
        "Vice President"
    ]
    assert events.officer_roles("The Board of Directors met; the directorate grew.") == []
    assert events.officer_roles("Our CFO and the chief operating officer resigned.") == [
        "Chief Financial Officer",
        "Chief Operating Officer",
    ]


# The category of a claim


@pytest.mark.parametrize(
    ("claim", "expected"),
    [
        ("Buy because Jensen is gone.", [Category.leadership]),
        ("Jensen is gone.", [Category.leadership]),
        ("The CEO transition is a risk.", [Category.leadership]),
        ("Margins are gone.", []),
        ("The board game segment is shrinking.", []),
        ("The left-hand column shows falling sales.", []),
        ("Export controls on sales to China are restricting revenue.", []),
        ("Data center revenue is still growing year over year.", []),
        ("The company restated its results and changed its auditor.", [Category.accounting]),
        ("It took on new debt to fund an acquisition.", [Category.deal, Category.financing]),
    ],
)
def test_a_claims_categories_come_from_whole_word_rules(
    claim: str, expected: list[Category]
) -> None:
    assert events.claim_categories(claim) == expected


def test_no_claim_gets_a_category_without_a_lexicon() -> None:
    assert events.claim_categories("Results of operations and other events, exhibits.") == []


# Supersession


def test_an_event_filed_after_every_cited_filing_on_the_claims_subject_predates_it() -> None:
    timeline = [event("2026-11-12", "5.02", "9.01"), event("2026-08-17", "1.01", "2.03")]
    marks = events.predating(["2026-02-25", "2026-08-26"], [Category.leadership], timeline)
    assert [(mark.event_id, mark.items) for mark in marks] == [("ev-2026-11-12", ["5.02"])]
    assert marks[0].label == "Predates the 8-K of 12 Nov 2026, Item 5.02"


def test_an_event_filed_before_one_of_the_cited_filings_does_not_predate_it() -> None:
    timeline = [event("2026-07-02", "5.02")]
    assert events.predating(["2026-02-25", "2026-08-26"], [Category.leadership], timeline) == []


def test_an_event_filed_the_same_day_as_a_cited_filing_is_not_later() -> None:
    timeline = [event("2026-08-26", "5.02")]
    assert events.predating(["2026-08-26"], [Category.leadership], timeline) == []


def test_an_event_of_another_category_does_not_predate() -> None:
    timeline = [event("2026-11-12", "2.02", "9.01")]
    assert events.predating(["2026-02-25"], [Category.leadership], timeline) == []


def test_a_finding_that_cites_no_dated_filing_is_never_marked() -> None:
    assert events.predating([], [Category.leadership], [event("2026-11-12", "5.02")]) == []


def test_an_event_listed_but_not_read_still_predates_by_its_index_items() -> None:
    timeline = [event("2026-11-12", "5.02", status=EventStatus.capped)]
    assert len(events.predating(["2026-02-25"], [Category.leadership], timeline)) == 1


def test_the_caution_names_the_newest_filing_that_postdates_the_evidence() -> None:
    timeline = [event("2026-11-12", "5.02"), event("2026-07-02", "5.02")]
    marks = [events.predating(["2026-02-25"], [Category.leadership], timeline)]
    caution = events.claim_caution(marks, timeline)
    assert caution.startswith("The evidence for this verdict was filed before the 8-K of ")
    assert "12 Nov 2026 (Item 5.02)" in caution
    assert events.claim_caution([[]], timeline) == ""


# The honest negative


def test_no_event_of_the_claims_category_gives_a_note_that_is_not_a_verdict() -> None:
    timeline = [event("2026-08-26", "2.02", "9.01")]
    note = events.events_note(
        [Category.leadership],
        timeline,
        annual_filed="2026-02-25",
        newest_filed="2026-08-26",
        index_error="",
    )
    assert note == (
        "No 8-K filed since 25 Feb 2026 reports a change of directors or officers (Item 5.02). "
        "The newest filing read is dated 26 Aug 2026; anything later is not in the record."
    )


def test_a_claim_with_no_substantive_category_gets_no_note() -> None:
    assert events.events_note([], [], "2026-02-25", "2026-08-26", "") == ""


def test_an_unreadable_index_says_the_answer_is_unknown() -> None:
    note = events.events_note([Category.leadership], [], "2026-02-25", "2026-08-26", "HTTP 503")
    assert "could not be read (HTTP 503)" in note
    assert "not known" in note
    assert not note.startswith("No 8-K")


def test_an_event_of_the_category_that_was_not_read_is_named_in_the_note() -> None:
    timeline = [event("2026-11-12", "5.02", status=EventStatus.failed)]
    timeline[0].reason = "EDGAR answered HTTP 404"
    note = events.events_note([Category.leadership], timeline, "2026-02-25", "2026-08-26", "")
    assert note == (
        "The 8-K of 12 Nov 2026 reports Item 5.02, but its text was not read: "
        "EDGAR answered HTTP 404."
    )


# Choosing which documents to read


def test_8ks_after_the_periodic_report_and_substantive_ones_since_the_annual_are_read() -> None:
    timeline = [
        event("2026-11-12", "5.02", "9.01", status=EventStatus.index_only),
        event("2026-09-03", "8.01", status=EventStatus.index_only),
        event("2026-08-26", "2.02", status=EventStatus.index_only),
        event("2026-08-17", "1.01", status=EventStatus.index_only),
        event("2026-06-30", "5.07", status=EventStatus.index_only),
    ]
    wanted = events.choose_reads(timeline, newest_periodic_filed="2026-08-26", cap=8)
    assert [e.filed_date for e in wanted] == ["2026-11-12", "2026-09-03", "2026-08-17"]
    assert [e.after_periodic for e in timeline] == [True, True, False, False, False]


def test_the_cap_keeps_the_newest_and_marks_the_rest_capped() -> None:
    timeline = [event(f"2026-0{m}-10", "5.02", status=EventStatus.index_only) for m in (9, 8, 7)]
    wanted = events.choose_reads(timeline, newest_periodic_filed="2026-08-26", cap=2)
    assert [e.filed_date for e in wanted] == ["2026-09-10", "2026-08-10"]
    assert [e.status for e in timeline] == [
        EventStatus.index_only,
        EventStatus.index_only,
        EventStatus.capped,
    ]


def test_the_counts_add_up_to_the_listed_events() -> None:
    timeline = [
        event("2026-11-12", "5.02", status=EventStatus.read),
        event("2026-09-03", "8.01", status=EventStatus.failed),
        event("2026-08-17", "1.01", status=EventStatus.capped),
        event("2026-06-30", "5.07", status=EventStatus.index_only),
    ]
    counts = events.count_events(timeline, cap=8, annual_filed="2026-02-25")
    assert counts.model_dump(exclude={"line"}) == {
        "listed": 4,
        "wanted": 3,
        "read": 1,
        "failed": 1,
        "capped": 1,
        "out_of_time": 0,
        "index_only": 1,
        "cap": 8,
    }
    assert counts.line == (
        "4 8-K(s) filed since the annual report of 25 Feb 2026: 1 read, 1 could not be read, "
        "1 not read because of the cap of 8 per run, 1 routine 8-K(s) filed before the newest "
        "periodic report listed from the index only."
    )


def test_offered_sections_are_of_the_claims_categories_newest_first_and_capped() -> None:
    timeline = [
        event("2026-11-12", "5.02", "9.01"),
        event("2026-09-03", "8.01"),
        event("2026-07-02", "5.02"),
        event("2026-05-08", "5.02"),
        event("2026-04-27", "5.02", status=EventStatus.failed),
    ]
    pinned = events.pinned_items([Category.leadership], timeline, limits.EVENT_PASSAGES_PER_CLAIM)
    assert [(e.filed_date, item.number) for e, item in pinned] == [
        ("2026-11-12", "5.02"),
        ("2026-07-02", "5.02"),
    ]
    assert events.pinned_items([], timeline, 2) == []


# Dates and the as-of line


def test_a_day_is_written_day_month_year() -> None:
    assert events.day_label("2026-11-12") == "12 Nov 2026"
    assert events.day_label("") == ""
    assert events.day_label("not a date") == "not a date"


def test_the_as_of_block_names_the_newest_filing_of_any_form() -> None:
    as_of = events.build_as_of(
        filings=[
            ("10-Q", "2026-08-26", "https://q"),
            ("10-K", "2026-02-25", "https://k"),
            ("8-K", "2026-11-12", "https://e"),
        ],
        annual_filed="2026-02-25",
        started=date(2026, 11, 17),
        counts=EventCounts(),
        index_error="",
    )
    assert (as_of.newest_form, as_of.newest_filed, as_of.newest_url) == (
        "8-K",
        "2026-11-12",
        "https://e",
    )
    assert (as_of.periodic_form, as_of.periodic_filed) == ("10-Q", "2026-08-26")
    assert as_of.days_since_newest == 5
    assert as_of.line == (
        "Evidence as of 12 Nov 2026 (8-K), 5 days before this run. "
        "Newest periodic report: 10-Q filed 26 Aug 2026."
    )


def test_with_nothing_read_the_as_of_block_says_so() -> None:
    as_of = events.build_as_of(
        filings=[],
        annual_filed=None,
        started=date(2026, 11, 17),
        counts=EventCounts(),
        index_error="",
    )
    assert as_of.newest_filed is None
    assert as_of.line == "No filing was read, so the evidence has no date."


def test_event_items_are_described_from_the_table() -> None:
    item = events.describe_item("5.02")
    assert isinstance(item, EventItem)
    assert item.category == "leadership"
    assert item.title.startswith("Departure of Directors")


def test_an_opening_sentence_is_not_cut_after_a_title_or_a_company_suffix() -> None:
    """Seen live in NVIDIA's 8-Ks: "Mr. Huang's resignation" split after "Mr."."""
    text = (
        "On November 11, 2026, the Board accepted the resignation of Jen-Hsun Huang. "
        "In connection with Mr. Huang's resignation, the Board appointed Colette M. Kress "
        "as interim Chief Executive Officer. Ms. Kress, age 59, will continue as CFO."
    )
    assert events.opening_sentences(text, 3) == [
        "On November 11, 2026, the Board accepted the resignation of Jen-Hsun Huang.",
        "In connection with Mr. Huang's resignation, the Board appointed Colette M. Kress "
        "as interim Chief Executive Officer.",
        "Ms. Kress, age 59, will continue as CFO.",
    ]
    deal = (
        "On August 17, 2026, NVIDIA announced a partnership with SB Energy Corp. "
        "(collectively with its affiliates, “SB Energy”) to build a campus. "
        "NVIDIA agreed to acquire Hugging Face, Inc. Hugging Face operates a platform."
    )
    sentences = events.opening_sentences(deal, 3)
    assert sentences[0].endswith("to build a campus.")
    assert sentences[1] == "NVIDIA agreed to acquire Hugging Face, Inc."
    assert all(sentence in deal for sentence in sentences)
