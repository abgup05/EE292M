# EE292M capstone idea pitches

These ideas serve the same research workflow at RD2 / Radius: move from a company or theme to a defensible list of related businesses and the evidence behind each connection. The Week 2 visualization can be the starting point for any of them. The NYSE sector workbook supplies the initial company classifications; it does not supply customer or supplier relationships.

## 1. Evidence-backed company relationship graph (recommended)

**Question.** Given a company or investment theme, which other businesses are linked to it, how are they linked, and what public evidence supports each link?

**Product.** An interactive graph with company and subsector views. A researcher can search a company, expand upstream or downstream one step, and open an edge to read its relationship type, source passage, publication date, and review status. A Python pipeline proposes new relationships from filings and company announcements. A reviewer accepts, corrects, or rejects each proposal before it enters the trusted graph. The app exports the reviewed relationships as clean CSV.

**Data and method.** Start with one bounded theme, such as AI infrastructure, and roughly 10–20 companies. Use the supplied classification workbook for company-to-sector mapping, SEC filings and issuer announcements for candidate company relationships, and a small manually curated reference set. Store relationships with stable company identifiers, direction, type, evidence URL, publication date, and last review date. Treat supplier, customer, partnership, shared input, and analyst hypothesis as different types. A missing edge means unknown, not no relationship.

**Validation.** Label a held-out set of passages with whether they state a relationship, its direction, and its type. Report precision and recall for candidate detection, accuracy for type and direction, and the share of accepted edges with a working citation. Compare the time needed to complete the same research task manually and with the app. Test parsing, duplicate handling, filtering, and CSV export with cases designed to fail when the output is wrong.

**Scope and risk.** Public disclosures omit many commercial relationships and rarely quantify revenue exposure. The graph must never convert an announcement into a revenue estimate. The capstone succeeds if it makes a narrow, reviewable research process faster and more accurate; it does not require a complete supply chain.

## 2. Investment thesis change tracker

**Question.** When new disclosures arrive, which specific claims in a watchlist thesis gain support, face contrary evidence, or still lack evidence?

**Product.** A lightweight site where a researcher writes testable claims and attaches dated source passages. New filings or announcements create candidate updates beside the relevant claim, with the earlier and newer evidence visible together. The researcher records a disposition and can export a dated change log for earnings preparation.

**Data and method.** Use a small public-company watchlist and public filings first, so evaluation is reproducible. Each claim has a company, metric or operational assertion, period, expected direction, and original citation. Keep source text and publication dates, and distinguish a changed fact from new wording that says the same thing. Confidential Radius notes are optional and would stay local.

**Validation.** Hand-label material changes in several document pairs. Measure missed changes, false alerts, citation support, and reviewer time against reading the same documents unaided. Include cases where a filing is silent on a claim, where a period changes, and where a numerical value is restated.

**Scope and risk.** This is the most directly useful option if the main bottleneck is keeping investment notes current. The difficult part is defining claims precisely enough that the app can compare evidence without overstating what a document says.

## 3. Shared-exposure and shock research lab

**Question.** Which companies in different sectors share exposure to an input, customer industry, or demand theme, and do those links add information beyond their sector labels?

**Product.** A network and subsector matrix that lets a researcher select a driver, inspect connected companies, and compare them with ordinary sector peers. A separate historical study view can compare event-window behavior if suitable, point-in-time market data is available. An illustrative scenario view would show its assumptions and economic exposure, not a predicted stock return.

**Data and method.** Combine the reviewed relationship graph with a documented mapping from the workbook's custom sectors to a fixed vintage of BEA input-output industries. Keep company-specific links separate from industry averages. Select a few pre-defined events and freeze each graph at the information available before the event to avoid hindsight.

**Validation.** Test the industry crosswalk and graph calculations with known cases. Compare results against a sector-only baseline, report how conclusions change when uncertain edges are removed, and use held-out events for any empirical claim. Record data coverage and avoid interpreting correlation as causation.

**Scope and risk.** This is the most quantitative option and has the largest data burden. It is best if the goal is to study hidden common exposure; it should follow, rather than precede, a reliable relationship dataset.

## Recommendation

Build the Week 2 app as a small sector and dependency explorer, then choose idea 1 for the capstone. It reuses the same user interface and data model while adding the course's larger requirement: useful automation whose accuracy can be measured. Idea 2 is a strong alternative if ongoing thesis review is the bigger Radius pain point. Idea 3 is better suited to a later extension once the graph and market data are trustworthy.
