"""Breakdowns from one filing's tagged facts: segments, products, geographies, customers.

The answer key for the recorded NVIDIA 10-K comes from the filing's own text as
the project's parser reads it, never from the extraction under test.
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from app.core.breakdown_models import Breakdown, BreakdownReport, FilingInfo
from app.core.breakdowns import MAX_ROWS, build_report, member_label
from app.core.documents import FilingRef
from app.core.models import Company
from app.core.ports import SourceError, UnknownTicker
from app.services.breakdowns import filing_breakdowns
from app.sources.filing import parse_filing
from app.sources.ixbrl import read_tagged_facts
from tests.fakes import FY_2026, NVIDIA, Q2_2027, FakeFilings, recorded_html, synthetic_ref
from tests.test_ixbrl import FY, context, document, fact

PRODUCT = "srt:ProductOrServiceAxis"
SEGMENT = "us-gaap:StatementBusinessSegmentsAxis"
GEOGRAPHY = "srt:StatementGeographicalAxis"
CONSOLIDATION = "srt:ConsolidationItemsAxis"
OPERATING = "us-gaap:OperatingSegmentsMember"


class FormFilings(FakeFilings):
    """FakeFilings that selects filings of one form as EDGAR's client does.

    ``filings_of_form`` refuses fewer than two, as EdgarClient does; ``latest_of_form``
    needs only one. Both honour ``index_error``.
    """

    def _of_form(self, form: str) -> list[FilingRef]:
        if self.index_error is not None:
            raise self.index_error
        return [ref for ref in self.refs if ref.form == form]

    def filings_of_form(self, company: Company, form: str, limit: int) -> list[FilingRef]:
        """The configured refs of ``form``, newest first as given; fewer than two fails."""
        refs = self._of_form(form)
        if len(refs) < 2:
            raise SourceError(f"{company.name} has {len(refs)} {form} filing(s); two are needed")
        return refs[:limit]

    def latest_of_form(self, company: Company, form: str) -> FilingRef:
        """The first configured ref of ``form``; none is a SourceError."""
        refs = self._of_form(form)
        if not refs:
            raise SourceError(f"{company.name} has no {form} filing in the fake index")
        return refs[0]


def nvidia(*refs: FilingRef) -> FormFilings:
    base = FakeFilings.nvidia(*(refs or (Q2_2027, FY_2026)))
    return FormFilings(refs=base.refs, documents=base.documents, companies=base.companies)


def info(ref: FilingRef) -> FilingInfo:
    return FilingInfo(
        form=ref.form,
        period_end=ref.period_end,
        filed_date=ref.filed_date,
        accession=ref.accession,
        url=ref.url,
    )


def report_of(html: str, form: str = "10-K") -> BreakdownReport:
    filing = info(synthetic_ref(1, form))
    return build_report(read_tagged_facts(html), company=NVIDIA, filing=filing)


def breakdown(report: BreakdownReport, breakdown_id: str) -> Breakdown:
    found = [b for b in report.breakdowns if b.id == breakdown_id]
    assert found, f"no {breakdown_id} in {[b.id for b in report.breakdowns]}"
    return found[0]


def row_values(item: Breakdown, member: str) -> dict[str, float]:
    row = next(r for r in item.rows if r.member == member)
    return {v.period_end: v.value for v in row.values}


@pytest.fixture(scope="module")
def annual() -> BreakdownReport:
    return filing_breakdowns("NVDA", "10-K", filings=nvidia())


@pytest.fixture(scope="module")
def quarterly() -> BreakdownReport:
    return filing_breakdowns("NVDA", "10-Q", filings=nvidia())


@pytest.fixture(scope="module")
def annual_text() -> str:
    html = recorded_html("nvda-10k-20260125.htm.gz")
    return parse_filing(html, url=FY_2026.url, title="NVIDIA 10-K", published_date=None).text


# (a) The answer key: the filing's own text


def _millions(text: str) -> float:
    return float(text.replace(",", "")) * 1e6


def test_data_center_revenue_and_its_growth_match_the_filing_text(
    annual: BreakdownReport, annual_text: str
) -> None:
    # Note 17's table, "Revenue by End Market: (In millions)", as the parser writes the row.
    row = re.search(r"^Data Center \$([\d,]+) \$([\d,]+) \$([\d,]+)$", annual_text, re.M)
    assert row is not None
    # Item 7, Fiscal Year 2026 Summary.
    sentence = "Data Center revenue for fiscal year 2026 was up 68% from a year ago."
    assert sentence in annual_text

    products = breakdown(annual, "revenue_by_product")
    data_center = next(r for r in products.rows if r.member == "nvda:DataCenterMember")
    newest, year_before = data_center.values[0], data_center.values[1]
    assert (newest.period_start, newest.period_end) == ("2025-01-27", "2026-01-25")
    assert newest.value == _millions(row.group(1))
    assert year_before.value == _millions(row.group(2))
    assert newest.shown == row.group(1)
    assert newest.change is not None and round(newest.change) == 68


def test_segment_revenue_and_its_growth_match_the_segment_table(
    annual: BreakdownReport, annual_text: str
) -> None:
    # Item 7, "Revenue by Reportable Segments": the amounts, the $ change and the % change.
    row = re.search(
        r"^Compute & Networking \$([\d,]+) \$([\d,]+) \$([\d,]+) (\d+)%$", annual_text, re.M
    )
    assert row is not None, "the segment table row was not found in the parsed text"
    segments = breakdown(annual, "revenue_by_segment")
    compute = next(r for r in segments.rows if r.member == "nvda:ComputeAndNetworkingSegmentMember")
    assert compute.values[0].value == _millions(row.group(1))
    assert compute.values[1].value == _millions(row.group(2))
    assert compute.values[0].change is not None
    assert round(compute.values[0].change) == int(row.group(4))
    assert compute.values[0].change_formula.startswith("(193,479 − 116,193) ÷ 116,193")


def test_customer_concentration_matches_the_sentence(
    annual: BreakdownReport, annual_text: str
) -> None:
    sentence = (
        "For fiscal year 2026, sales to one direct customer represented 22% of total revenue "
        "and sales to another direct customer represented 14% of total revenue"
    )
    assert sentence in annual_text
    customers = breakdown(annual, "revenue_concentration_by_customer")
    newest = {
        r.member: r.values[0] for r in customers.rows if r.values[0].period_end == "2026-01-25"
    }
    assert newest["nvda:CustomerOneMember"].value == pytest.approx(0.22)
    assert newest["nvda:CustomerTwoMember"].value == pytest.approx(0.14)
    assert all(v.change is None and v.change_formula for v in newest.values())
    assert customers.concept == "us-gaap:ConcentrationRiskPercentage1"
    assert any("us-gaap:SalesRevenueNetMember" in note for note in customers.notes)


def test_receivables_concentration_is_a_separate_breakdown(annual: BreakdownReport) -> None:
    receivables = breakdown(annual, "receivables_concentration_by_customer")
    assert receivables.rows
    revenue = breakdown(annual, "revenue_concentration_by_customer")
    assert {v.value for r in revenue.rows for v in r.values}.isdisjoint({0.25, 0.18})


# (b) Members add up to the tagged total


def test_segments_add_up_to_total_revenue(annual: BreakdownReport) -> None:
    segments = breakdown(annual, "revenue_by_segment")
    assert segments.concept == "us-gaap:Revenues"
    assert [v.value for v in segments.total][0] == 215_938e6
    for column, total in enumerate(segments.total):
        assert sum(row.values[column].value for row in segments.rows) == total.value
    assert segments.adds_up is True


def test_products_add_up_once_the_nested_member_is_counted_once(annual: BreakdownReport) -> None:
    products = breakdown(annual, "revenue_by_product")
    assert products.adds_up is True
    nested = [note for note in products.notes if "counted once" in note]
    assert nested and "Data Center" in nested[0]
    assert "Compute" in nested[0] and "Networking" in nested[0]
    # Summed as tagged, they do not: the plain "they add up" sentence must not appear.
    assert not any(note.startswith("The members add up") for note in products.notes)


def test_a_customer_share_qualified_by_geography_is_not_a_share_of_revenue(
    annual: BreakdownReport, annual_text: str
) -> None:
    # Tagged with country:TW: a share of Data Center revenue from Taiwan-headquartered
    # customers, not of total revenue.
    assert (
        "we estimate 76% of Data Center revenue from Taiwan-headquartered customers was "
        "attributed to end customers based in the United States and Europe"
    ) in annual_text
    customers = breakdown(annual, "revenue_concentration_by_customer")
    assert all(v.value != pytest.approx(0.76) for r in customers.rows for v in r.values)
    assert {r.label for r in customers.rows} == {
        "Customer One · Compute and Networking Segment",
        "Customer Two · Compute and Networking Segment",
    }
    assert any("segment's revenue" in note for note in customers.notes)


# Microsoft's 10-K for fiscal 2026 tags two splits of revenue on the product axis: products
# against services, and its product lines. The values as shown, from the live run's record
# (no Microsoft filing is recorded); each on a context with that one dimension.
MSFT_PRODUCTS_FY2026 = {
    "us-gaap:ServiceOtherMember": "267,143",
    "us-gaap:ProductMember": "64,696",
    "msft:ServerProductsAndCloudServicesMember": "129,425",
    "msft:MicrosoftThreeSixFiveCommercialProductsAndCloudServicesMember": "101,997",
    "msft:XBOXMember": "21,790",
    "msft:LinkedInCorporationMember": "19,817",
    "msft:WindowsAndDevicesMember": "17,084",
    "msft:SearchAdvertisingMember": "15,176",
    "msft:MicrosoftThreeSixFiveConsumerProductsAndCloudServicesMember": "9,175",
    "msft:DynamicsProductsAndCloudServicesMember": "9,006",
    "msft:EnterpriseAndPartnerServicesMember": "8,260",
    "msft:OtherProductsAndServicesMember": "109",
}


def test_two_splits_of_the_total_on_one_axis_are_recognised() -> None:
    year = {"start": "2025-07-01", "end": "2026-06-30"}
    contexts = context("t", **year) + "".join(
        context(f"m{n}", **year, dims={PRODUCT: member})
        for n, member in enumerate(MSFT_PRODUCTS_FY2026)
    )
    facts = [fact("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", "t", "331,839")]
    facts += [
        fact("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", f"m{n}", shown)
        for n, shown in enumerate(MSFT_PRODUCTS_FY2026.values())
    ]
    products = breakdown(report_of(document(contexts, *facts)), "revenue_by_product")
    assert products.adds_up is True
    splits = [note for note in products.notes if "two splits" in note]
    assert splits and "Service Other plus Product" in splits[0]
    assert not any("do not add up" in note for note in products.notes)


# Tesla's 10-K for fiscal 2025 tags subtotals and their parts on the product axis, several
# levels deep (values as shown, from the live run's record; no Tesla filing is recorded).
TSLA_PRODUCTS_FY2025 = {
    "tsla:SalesAndServicesMember": "92,614",
    "tsla:AutomotiveRevenuesMember": "69,526",
    "tsla:AutomotiveSalesMember": "65,821",
    "tsla:EnergyGenerationAndStorageMember": "12,771",
    "tsla:ServicesAndOtherMember": "12,530",
    "tsla:EnergyGenerationAndStorageSalesMember": "12,270",
    "tsla:AutomotiveRegulatoryCreditsMember": "1,993",
    "tsla:AutomotiveLeasingMember": "1,712",
    "tsla:EnergyGenerationAndStorageLeasingMember": "501",
}


def test_several_members_made_of_others_are_each_counted_once() -> None:
    year = {"start": "2025-01-01", "end": "2025-12-31"}
    concept = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    contexts = context("t", **year) + "".join(
        context(f"m{n}", **year, dims={PRODUCT: member})
        for n, member in enumerate(TSLA_PRODUCTS_FY2025)
    )
    facts = [fact(concept, "t", "94,827")] + [
        fact(concept, f"m{n}", shown) for n, shown in enumerate(TSLA_PRODUCTS_FY2025.values())
    ]
    products = breakdown(report_of(document(contexts, *facts)), "revenue_by_product")
    assert products.adds_up is True
    made_of = " ".join(products.notes)
    assert "Sales and Services equals" in made_of
    assert "Automotive Revenues equals Automotive Sales plus" in made_of
    energy = "Energy Generation and Storage equals Energy Generation and Storage Sales plus"
    assert energy in made_of
    assert "do not add up" not in made_of


def _segments_with_reconciling_items(corporate: str) -> str:
    """Two segments whose revenue includes sales to each other, as the standard tagging has it.

    The eliminations and corporate revenue carry only srt:ConsolidationItemsAxis.
    """
    year = {"start": "2025-01-01", "end": "2025-12-31"}
    contexts = (
        context("t", **year)
        + context("a", **year, dims={SEGMENT: "x:NorthMember", CONSOLIDATION: OPERATING})
        + context("b", **year, dims={SEGMENT: "x:SouthMember", CONSOLIDATION: OPERATING})
        + context("e", **year, dims={CONSOLIDATION: "us-gaap:IntersegmentEliminationMember"})
        + context("c", **year, dims={CONSOLIDATION: "us-gaap:CorporateNonSegmentMember"})
    )
    return document(
        contexts,
        fact("us-gaap:Revenues", "t", "100"),
        fact("us-gaap:Revenues", "a", "60"),
        fact("us-gaap:Revenues", "b", "50"),
        fact("us-gaap:Revenues", "e", "15", sign="-"),
        fact("us-gaap:Revenues", "c", corporate),
    )


def test_segments_reconcile_through_the_reconciling_items_the_filing_tags() -> None:
    segments = breakdown(report_of(_segments_with_reconciling_items("5")), "revenue_by_segment")
    assert segments.adds_up is True
    assert [r.label for r in segments.rows] == ["North", "South"]
    note = next(note for note in segments.notes if "reconciling items" in note)
    assert "Intersegment Elimination (-15)" in note and "Corporate Non Segment (5)" in note


def test_reconciling_items_that_do_not_close_the_gap_are_named() -> None:
    segments = breakdown(report_of(_segments_with_reconciling_items("9")), "revenue_by_segment")
    assert segments.adds_up is False
    failure = next(note for note in segments.notes if "do not add up" in note)
    assert "Intersegment Elimination (-15)" in failure and "Corporate Non Segment (9)" in failure


# Coca-Cola's 10-K for 2025 (values as shown, from the live run's notes; no Coca-Cola filing
# is recorded): segment revenue includes intersegment sales; on srt:ConsolidationItemsAxis
# alone it tags corporate revenue, the eliminations, and the segments' own subtotal.
KO_SEGMENTS_2025 = {
    "ko:NorthAmericaSegmentMember": "19,586",
    "ko:EuropeMiddleEastAfricaMember": "11,513",
    "ko:LatinAmericaSegmentMember": "6,334",
    "ko:BottlingInvestmentsMember": "5,735",
    "ko:APacificMember": "5,638",
}
KO_RECONCILING_2025 = {
    "us-gaap:MaterialReconcilingItemsMember": ("48,806", None),
    "us-gaap:CorporateNonSegmentMember": ("144", None),
    "us-gaap:ConsolidationEliminationsMember": ("1,009", "-"),
}


def test_a_reconciling_item_that_is_the_segments_own_subtotal_is_not_added() -> None:
    year = {"start": "2025-01-01", "end": "2025-12-31"}
    contexts = context("t", **year)
    facts = [fact("us-gaap:Revenues", "t", "47,941")]
    for n, (member, shown) in enumerate(KO_SEGMENTS_2025.items()):
        contexts += context(f"s{n}", **year, dims={SEGMENT: member, CONSOLIDATION: OPERATING})
        facts.append(fact("us-gaap:Revenues", f"s{n}", shown))
    for n, (member, (shown, sign)) in enumerate(KO_RECONCILING_2025.items()):
        contexts += context(f"r{n}", **year, dims={CONSOLIDATION: member})
        facts.append(fact("us-gaap:Revenues", f"r{n}", shown, sign=sign))
    segments = breakdown(report_of(document(contexts, *facts)), "revenue_by_segment")
    assert segments.adds_up is True
    note = next(note for note in segments.notes if "reconciling items" in note)
    assert "Corporate Non Segment (144), Consolidation Eliminations (-1,009)" in note
    assert "Material Reconciling Items (48,806) equals the members' own sum" in note


def test_members_that_do_not_add_up_are_reported() -> None:
    contexts = (
        FY
        + context("a", start="2025-01-27", end="2026-01-25", dims={PRODUCT: "x:AlphaMember"})
        + context("b", start="2025-01-27", end="2026-01-25", dims={PRODUCT: "x:BetaMember"})
    )
    html = document(
        contexts,
        fact("us-gaap:Revenues", "c-1", "100"),
        fact("us-gaap:Revenues", "a", "60"),
        fact("us-gaap:Revenues", "b", "30"),
    )
    products = breakdown(report_of(html), "revenue_by_product")
    assert products.adds_up is False
    failure = next(note for note in products.notes if "do not add up" in note)
    assert "the members add up to 90, not the tagged total of 100" in failure


def test_rounding_within_the_tagged_decimals_still_adds_up() -> None:
    contexts = (
        FY
        + context("a", start="2025-01-27", end="2026-01-25", dims={PRODUCT: "x:AlphaMember"})
        + context("b", start="2025-01-27", end="2026-01-25", dims={PRODUCT: "x:BetaMember"})
    )
    html = document(
        contexts,
        fact("us-gaap:Revenues", "c-1", "101"),
        fact("us-gaap:Revenues", "a", "50"),
        fact("us-gaap:Revenues", "b", "50"),
    )
    assert breakdown(report_of(html), "revenue_by_product").adds_up is True


def test_two_tagged_totals_for_one_period_are_noted_not_silently_resolved() -> None:
    """The third referee, finding 6: the first total found was taken with no word of another."""
    contexts = (
        FY
        + context("a", start="2025-01-27", end="2026-01-25", dims={PRODUCT: "x:AlphaMember"})
        + context("b", start="2025-01-27", end="2026-01-25", dims={PRODUCT: "x:BetaMember"})
    )
    html = document(
        contexts,
        fact("us-gaap:Revenues", "c-1", "100"),
        fact("us-gaap:Revenues", "c-1", "90"),
        fact("us-gaap:Revenues", "a", "60"),
        fact("us-gaap:Revenues", "b", "40"),
    )
    products = breakdown(report_of(html), "revenue_by_product")
    conflict = next(note for note in products.notes if "more than one value" in note)
    assert "The total for 2026-01-25" in conflict and "100" in conflict and "90" in conflict


def test_the_same_total_tagged_twice_is_not_a_conflict() -> None:
    contexts = (
        FY
        + context("a", start="2025-01-27", end="2026-01-25", dims={PRODUCT: "x:AlphaMember"})
        + context("b", start="2025-01-27", end="2026-01-25", dims={PRODUCT: "x:BetaMember"})
    )
    html = document(
        contexts,
        fact("us-gaap:Revenues", "c-1", "100"),
        fact("us-gaap:Revenues", "c-1", "100"),
        fact("us-gaap:Revenues", "a", "60"),
        fact("us-gaap:Revenues", "b", "40"),
    )
    products = breakdown(report_of(html), "revenue_by_product")
    assert products.adds_up is True
    assert not any("more than one value" in note for note in products.notes)


def test_annual_values_in_the_rarer_unit_do_not_stop_the_report() -> None:
    """The third referee, finding 6: an assertion stood where a filing could reach it.

    An annual report whose members are tagged for the year in one unit and, more often,
    for a quarter in another: the commoner unit was chosen first, no annual value was
    left, and the reader stopped on an ``assert``. The period is chosen first now, then
    the unit among the values of that period.
    """
    year = {"start": "2025-01-27", "end": "2026-01-25"}
    quarter = {"start": "2025-10-27", "end": "2026-01-25"}
    contexts = (
        FY
        + context("a", **year, dims={PRODUCT: "x:AlphaMember"})
        + context("b", **year, dims={PRODUCT: "x:BetaMember"})
        + context("aq", **quarter, dims={PRODUCT: "x:AlphaMember"})
        + context("bq", **quarter, dims={PRODUCT: "x:BetaMember"})
        + context("aq2", start="2025-07-28", end="2025-10-26", dims={PRODUCT: "x:AlphaMember"})
    )
    html = document(
        contexts,
        fact("us-gaap:Revenues", "c-1", "100"),
        fact("us-gaap:Revenues", "a", "60"),
        fact("us-gaap:Revenues", "b", "40"),
        fact("us-gaap:Revenues", "aq", "15", unit="number"),
        fact("us-gaap:Revenues", "bq", "10", unit="number"),
        fact("us-gaap:Revenues", "aq2", "14", unit="number"),
    )
    products = breakdown(report_of(html), "revenue_by_product")
    assert row_values(products, "x:AlphaMember") == {"2026-01-25": 60e6}
    assert products.adds_up is True


# (e) Contexts with two dimensions are not one-dimension breakdowns


def test_a_two_dimension_context_is_not_taken_for_a_one_dimension_breakdown() -> None:
    year = {"start": "2025-01-27", "end": "2026-01-25"}
    contexts = (
        FY
        + context("p", **year, dims={PRODUCT: "x:GamingMember"})
        + context("ps", **year, dims={PRODUCT: "x:GamingMember", SEGMENT: "x:GraphicsMember"})
        + context("pc", **year, dims={PRODUCT: "x:GamingMember", CONSOLIDATION: OPERATING})
        + context("s", **year, dims={SEGMENT: "x:GraphicsMember", CONSOLIDATION: OPERATING})
        + context("t", **year, dims={GEOGRAPHY: "country:US"}, typed="x:LoanAxis")
    )
    html = document(
        contexts,
        fact("us-gaap:Revenues", "c-1", "100"),
        fact("us-gaap:Revenues", "p", "40"),
        fact("us-gaap:Revenues", "ps", "7"),
        fact("us-gaap:Revenues", "pc", "8"),
        fact("us-gaap:Revenues", "s", "100"),
        fact("us-gaap:Revenues", "t", "9"),
    )
    report = report_of(html)
    products = breakdown(report, "revenue_by_product")
    assert [(r.member, [v.value for v in r.values]) for r in products.rows] == [
        ("x:GamingMember", [40e6])
    ]
    # The segment axis qualified only by "operating segments" is the segment breakdown.
    segments = breakdown(report, "revenue_by_segment")
    assert [(r.member, [v.value for v in r.values]) for r in segments.rows] == [
        ("x:GraphicsMember", [100e6])
    ]
    assert segments.adds_up is True
    assert "revenue_by_geography" not in [b.id for b in report.breakdowns]


# (f) Periods placed by their dates


def test_an_annual_report_gives_three_fiscal_years_newest_first(annual: BreakdownReport) -> None:
    products = breakdown(annual, "revenue_by_product")
    assert products.period_kind == "fiscal year"
    ends = [v.period_end for v in products.total]
    assert ends == ["2026-01-25", "2025-01-26", "2024-01-28"]
    for row in products.rows:
        assert [v.period_end for v in row.values] == ends
        assert row.values[-1].change is None


def test_a_quarterly_report_gives_quarters_and_never_year_to_date(
    quarterly: BreakdownReport,
) -> None:
    products = breakdown(quarterly, "revenue_by_product")
    assert products.period_kind == "quarter"
    for value in [v for r in products.rows for v in r.values] + products.total:
        assert value.period_start is not None
        length = date.fromisoformat(value.period_end) - date.fromisoformat(value.period_start)
        assert 80 <= length.days <= 100
    assert products.total[0].period_end == "2026-07-26"
    assert any("Year-to-date values are also tagged" in note for note in products.notes)


def test_a_quarterly_report_with_only_year_to_date_values_says_so() -> None:
    contexts = context("h", start="2026-01-26", end="2026-07-26", dims={PRODUCT: "x:GamingMember"})
    html = document(contexts, fact("us-gaap:Revenues", "h", "5"))
    products = breakdown(report_of(html, "10-Q"), "revenue_by_product")
    assert products.period_kind == "year to date"
    assert products.periods[0].label == "Year to date, 2026-01-26 to 2026-07-26"
    assert any("Only year-to-date" in note for note in products.notes)


def test_a_retailers_36_week_year_to_date_is_recognised_and_not_mixed_in() -> None:
    # Costco's fiscal calendar, from the live run of its 10-Q for the quarter ended 2026-05-10:
    # 12-week quarters and a 36-week year to date (252 days), which no "nine months" band holds.
    # The quarter values are Costco's United States segment as shown; the year-to-date value
    # is made up (it was not shown, because it was dropped).
    us = {SEGMENT: "cost:UnitedStatesMember"}
    contexts = (
        context("q", start="2026-02-16", end="2026-05-10", dims=us)
        + context("qb", start="2025-02-17", end="2025-05-11", dims=us)
        + context("ytd", start="2025-09-01", end="2026-05-10", dims=us)
    )
    concept = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    html = document(
        contexts,
        fact(concept, "q", "51,434"),
        fact(concept, "qb", "46,318"),
        fact(concept, "ytd", "150,000"),
    )
    segments = breakdown(report_of(html, "10-Q"), "revenue_by_segment")
    assert segments.period_kind == "quarter"
    assert [p.label for p in segments.periods] == [
        "Quarter ended 2026-05-10",
        "Quarter ended 2025-05-11",
    ]
    assert segments.rows[0].values[0].change_display == "+11.0%"
    assert any("Year-to-date values are also tagged" in note for note in segments.notes)


def test_a_sixteen_week_quarter_is_a_quarter() -> None:
    # A 16-week first quarter (112 days), as some retailers report.
    contexts = context(
        "q1", start="2026-02-01", end="2026-05-23", dims={PRODUCT: "x:GroceryMember"}
    ) + context("q1b", start="2025-02-02", end="2025-05-24", dims={PRODUCT: "x:GroceryMember"})
    html = document(
        contexts, fact("us-gaap:Revenues", "q1", "110"), fact("us-gaap:Revenues", "q1b", "100")
    )
    products = breakdown(report_of(html, "10-Q"), "revenue_by_product")
    assert products.period_kind == "quarter"
    assert [v.display for v in products.rows[0].values] == ["110", "100"]


def test_the_change_is_from_the_same_period_a_year_earlier() -> None:
    contexts = (
        context("q2", start="2026-04-27", end="2026-07-26", dims={PRODUCT: "x:GamingMember"})
        + context("q1", start="2026-01-26", end="2026-04-26", dims={PRODUCT: "x:GamingMember"})
        + context("q2b", start="2025-04-28", end="2025-07-27", dims={PRODUCT: "x:GamingMember"})
    )
    html = document(
        contexts,
        fact("us-gaap:Revenues", "q2", "150"),
        fact("us-gaap:Revenues", "q1", "140"),
        fact("us-gaap:Revenues", "q2b", "100"),
    )
    row = breakdown(report_of(html, "10-Q"), "revenue_by_product").rows[0]
    assert [v.period_end for v in row.values] == ["2026-07-26", "2026-04-26", "2025-07-27"]
    assert row.values[0].change == pytest.approx(50.0)
    assert row.values[0].change_formula == (
        "(150 − 100) ÷ 100 = +50.0%: the change from the quarter ended 2025-07-27, in USD millions"
    )
    assert row.values[1].change is None


# Revenue concepts differ by company


def test_the_revenue_concept_used_is_recorded() -> None:
    year = {"start": "2025-01-27", "end": "2026-01-25"}
    contexts = FY + context("g", **year, dims={GEOGRAPHY: "country:US"})
    concept = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    html = document(contexts, fact(concept, "c-1", "10"), fact(concept, "g", "10"))
    geography = breakdown(report_of(html), "revenue_by_geography")
    assert geography.concept == concept
    assert geography.rows[0].label == "US"
    assert geography.adds_up is True


def test_a_long_list_is_cut_and_says_so() -> None:
    year = {"start": "2025-01-27", "end": "2026-01-25"}
    count = MAX_ROWS + 3
    contexts = "".join(
        context(f"m{n}", **year, dims={PRODUCT: f"x:Product{n}Member"}) for n in range(count)
    )
    facts = [fact("us-gaap:Revenues", f"m{n}", str(n + 1)) for n in range(count)]
    products = breakdown(report_of(document(contexts, *facts)), "revenue_by_product")
    assert len(products.rows) == MAX_ROWS
    assert products.rows[0].values[0].value == count * 1e6  # the largest first
    assert any(f"{count} members" in note for note in products.notes)


def test_a_filing_without_inline_xbrl_has_no_breakdowns_and_says_why() -> None:
    report = report_of("<html><body><p>No tags here.</p></body></html>")
    assert report.breakdowns == [] and report.facts_read == 0
    assert any("no inline XBRL" in note for note in report.notes)


def test_unread_facts_are_counted_with_their_reasons() -> None:
    html = document(FY, fact("us-gaap:Revenues", "c-1", "n/a"), fact("x:Y", "c-1", "1"))
    report = report_of(html)
    assert (report.facts_read, report.facts_unparsed) == (2, 1)
    assert any("1 of 2" in note and "not a number" in note for note in report.notes)


# What the page draws: every display string is in the record


def test_values_carry_their_display_in_the_breakdowns_unit(annual: BreakdownReport) -> None:
    products = breakdown(annual, "revenue_by_product")
    assert products.unit_label == "USD millions"
    assert [(p.period_start, p.period_end, p.label) for p in products.periods] == [
        ("2025-01-27", "2026-01-25", "Fiscal year ended 2026-01-25"),
        ("2024-01-29", "2025-01-26", "Fiscal year ended 2025-01-26"),
        ("2023-01-30", "2024-01-28", "Fiscal year ended 2024-01-28"),
    ]
    data_center = next(r for r in products.rows if r.member == "nvda:DataCenterMember")
    assert [(v.display, v.change_display) for v in data_center.values] == [
        ("193,737", "+68.2%"),
        ("115,186", "+142.4%"),
        ("47,525", ""),
    ]
    assert (products.total[0].display, products.total[0].change_display) == ("215,938", "+65.5%")
    customers = breakdown(annual, "revenue_concentration_by_customer")
    assert customers.unit_label == "percent of revenue"
    assert {v.display for r in customers.rows for v in r.values} >= {"22.0%", "14.0%"}
    assert all(v.change_display == "" for r in customers.rows for v in r.values)
    receivables = breakdown(annual, "receivables_concentration_by_customer")
    assert receivables.unit_label == "percent of accounts receivable"


def test_a_value_tagged_in_another_scale_displays_in_the_breakdowns_one_unit() -> None:
    contexts = (
        FY
        + context("a", start="2025-01-27", end="2026-01-25", dims={PRODUCT: "x:AlphaMember"})
        + context("b", start="2025-01-27", end="2026-01-25", dims={PRODUCT: "x:BetaMember"})
    )
    html = document(
        contexts,
        fact("us-gaap:Revenues", "c-1", "100"),
        fact("us-gaap:Revenues", "a", "60"),
        # In thousands, beside neighbours in millions: still 40 in the breakdown's unit.
        fact("us-gaap:Revenues", "b", "40,000", scale="3", decimals="-3"),
    )
    products = breakdown(report_of(html), "revenue_by_product")
    assert products.unit_label == "USD millions"
    beta = next(r for r in products.rows if r.member == "x:BetaMember").values[0]
    assert (beta.shown, beta.value, beta.display) == ("40,000", 40e6, "40")
    assert products.adds_up is True


def test_a_quarterly_breakdowns_periods_are_labelled_as_quarters(
    quarterly: BreakdownReport,
) -> None:
    products = breakdown(quarterly, "revenue_by_product")
    assert [p.label for p in products.periods] == [
        "Quarter ended 2026-07-26",
        "Quarter ended 2025-07-27",
    ]


# (g) Labels


@pytest.mark.parametrize(
    ("member", "label"),
    [
        ("nvda:ComputeAndNetworkingSegmentMember", "Compute and Networking Segment"),
        ("nvda:OEMAndOtherMember", "OEM and Other"),
        ("nvda:ChinaIncludingHongKongMember", "China Including Hong Kong"),
        ("aapl:IPhoneMember", "IPhone"),
        ("nvda:A2060NotesMember", "A2060 Notes"),
        ("country:US", "US"),
        ("us-gaap:NonUsMember", "Non Us"),
        ("amzn:AWSSegmentMember", "AWS Segment"),
        ("msft:LinkedInCorporationMember", "Linked In Corporation"),
    ],
)
def test_labels_are_derived_from_the_tag_name(member: str, label: str) -> None:
    assert member_label(member) == label


def test_every_breakdown_says_its_labels_are_derived(annual: BreakdownReport) -> None:
    assert annual.breakdowns
    for item in annual.breakdowns:
        assert any("not the company's own labels" in note for note in item.notes)


# The service


def test_the_service_reads_the_latest_filing_of_the_form(annual: BreakdownReport) -> None:
    assert annual.company == NVIDIA
    assert annual.filing == info(FY_2026)
    assert {b.id for b in annual.breakdowns} >= {
        "revenue_by_segment",
        "revenue_by_product",
        "revenue_by_geography",
        "revenue_concentration_by_customer",
    }


def test_a_companys_only_annual_report_is_read() -> None:
    # One 10-K and nothing to compare it with: EDGAR's pair listing would refuse this.
    report = filing_breakdowns("NVDA", "10-K", filings=nvidia(FY_2026))
    assert report.filing.accession == FY_2026.accession
    assert breakdown(report, "revenue_by_product").rows


def test_a_company_with_no_filing_of_the_form_is_a_source_error() -> None:
    with pytest.raises(SourceError, match="has no 10-Q filing"):
        filing_breakdowns("NVDA", "10-Q", filings=nvidia(FY_2026))


def test_the_service_refuses_other_forms() -> None:
    with pytest.raises(ValueError, match="10-K or 10-Q"):
        filing_breakdowns("NVDA", "8-K", filings=nvidia())


def test_the_service_lets_edgar_failures_and_unknown_tickers_through() -> None:
    with pytest.raises(UnknownTicker):
        filing_breakdowns("NOPE", "10-K", filings=nvidia())
    failing = nvidia()
    failing.index_error = SourceError("EDGAR answered HTTP 503")
    with pytest.raises(SourceError):
        filing_breakdowns("NVDA", "10-K", filings=failing)
    missing = nvidia(FY_2026)
    missing.documents = {}
    with pytest.raises(SourceError, match="404"):
        filing_breakdowns(NVIDIA, "10-K", filings=missing)
