# Tagged breakdowns on eight companies' annual and quarterly reports

Each row is read from the record written by `make breakdowns ARGS="<TICKER> --form 10-K"` (or `--form 10-Q`), run on 17 November 2026 (UTC 17:08 to 17:10) against live SEC EDGAR at the code of `capstone-v9`. "Facts" are the numeric facts the filing tags (`ix:nonFraction`); "unread" are those left out, each with its reason in the record (on these filings every one is a nil fact: a tag with no value). "Adds up" says whether the members' sum equals the filing's own tagged total in every period checked, within the rounding the tags declare; concentration percentages are not summed.

No person has compared these with the printed tables. The answer key in the tests covers NVIDIA's annual report only (`../breakdowns.md`).

## Annual reports (10-K)

| Company | Period ended | Facts | Unread | Breakdown | Concept | Members | Periods | Kind of period | Adds up |
| --- | --- | ---: | ---: | --- | --- | ---: | ---: | --- | --- |
| NVIDIA | 2026-01-25 | 1,127 | 0 | Revenue by business segment | `us-gaap:Revenues` | 2 | 3 | fiscal year | yes |
| | | | | Revenue by product or service | `us-gaap:Revenues` | 7 | 3 | fiscal year | yes |
| | | | | Revenue by geography | `us-gaap:Revenues` | 4 | 3 | fiscal year | yes |
| | | | | Share of revenue by major customer | `us-gaap:ConcentrationRiskPercentage1` | 2 | 3 | fiscal year | not checked |
| | | | | Share of accounts receivable by major customer | `us-gaap:ConcentrationRiskPercentage1` | 3 | 2 | fiscal year | not checked |
| Apple | 2026-09-26 | 1,068 | 2 | Revenue by business segment | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | 5 | 3 | fiscal year | yes |
| | | | | Revenue by product or service | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | 6 | 3 | fiscal year | yes |
| | | | | Revenue by geography | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | 3 | 3 | fiscal year | yes |
| Microsoft | 2026-06-30 | 1,583 | 2 | Revenue by business segment | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | 3 | 3 | fiscal year | yes |
| | | | | Revenue by product or service | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | 12 | 3 | fiscal year | yes |
| | | | | Revenue by geography | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | 2 | 3 | fiscal year | yes |
| Coca-Cola | 2025-12-31 | 2,530 | 0 | Revenue by business segment | `us-gaap:Revenues` | 5 | 3 | fiscal year | yes |
| | | | | Revenue by product or service | `us-gaap:Revenues` | 2 | 3 | fiscal year | yes |
| | | | | Revenue by geography | `us-gaap:Revenues` | 2 | 3 | fiscal year | yes |
| | | | | Share of revenue by major customer | `us-gaap:ConcentrationRiskPercentage1` | 1 | 1 | fiscal year | not checked |
| JPMorgan Chase | 2025-12-31 | 7,961 | 2 | Revenue by business segment | `us-gaap:RevenuesNetOfInterestExpense` | 3 | 3 | fiscal year | yes |
| | | | | Revenue by geography | `us-gaap:Revenues` | 5 | 3 | fiscal year | yes |
| Tesla | 2025-12-31 | 1,477 | 2 | Revenue by business segment | `us-gaap:Revenues` | 2 | 3 | fiscal year | yes |
| | | | | Revenue by product or service | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | 9 | 3 | fiscal year | yes |
| | | | | Revenue by geography | `us-gaap:Revenues` | 3 | 3 | fiscal year | yes |
| Costco | 2026-08-30 | 846 | 0 | Revenue by business segment | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | 3 | 3 | fiscal year | yes |
| | | | | Revenue by product or service | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | 6 | 3 | fiscal year | yes |
| Amazon | 2025-12-31 | 1,376 | 2 | Revenue by business segment | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | 3 | 3 | fiscal year | yes |
| | | | | Revenue by product or service | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | 9 | 3 | fiscal year | yes |
| | | | | Revenue by geography | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | 5 | 3 | fiscal year | yes |

## Quarterly reports (10-Q)

| Company | Period ended | Facts | Unread | Breakdown | Concept | Members | Periods | Kind of period | Adds up |
| --- | --- | ---: | ---: | --- | --- | ---: | ---: | --- | --- |
| NVIDIA | 2026-07-26 | 1,002 | 2 | Revenue by business segment | `us-gaap:Revenues` | 2 | 2 | quarter | yes |
| | | | | Revenue by product or service | `us-gaap:Revenues` | 4 | 2 | quarter | yes |
| | | | | Revenue by geography | `us-gaap:Revenues` | 4 | 2 | quarter | yes |
| | | | | Share of revenue by major customer | `us-gaap:ConcentrationRiskPercentage1` | 3 | 2 | quarter | not checked |
| | | | | Share of accounts receivable by major customer | `us-gaap:ConcentrationRiskPercentage1` | 5 | 1 | year to date | not checked |
| Apple | 2026-06-27 | 762 | 2 | Revenue by business segment | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | 5 | 2 | quarter | yes |
| | | | | Revenue by product or service | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | 6 | 2 | quarter | yes |
| Microsoft | 2026-09-30 | 1,044 | 2 | Revenue by business segment | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | 2 | 2 | quarter | yes |
| | | | | Revenue by product or service | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | 10 | 2 | quarter | yes |
| | | | | Revenue by geography | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | 2 | 2 | quarter | yes |
| Coca-Cola | 2026-10-02 | 1,696 | 0 | Revenue by business segment | `us-gaap:Revenues` | 5 | 2 | quarter | yes |
| | | | | Revenue by product or service | `us-gaap:Revenues` | 2 | 2 | quarter | yes |
| | | | | Revenue by geography | `us-gaap:Revenues` | 2 | 2 | quarter | yes |
| JPMorgan Chase | 2026-09-30 | 7,372 | 2 | Revenue by business segment | `us-gaap:RevenuesNetOfInterestExpense` | 3 | 2 | quarter | yes |
| Tesla | 2026-09-30 | 1,137 | 2 | Revenue by business segment | `us-gaap:Revenues` | 2 | 2 | quarter | yes |
| | | | | Revenue by product or service | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | 9 | 2 | quarter | yes |
| | | | | Revenue by geography | `us-gaap:Revenues` | 3 | 2 | quarter | yes |
| Costco | 2026-05-10 | 593 | 0 | Revenue by business segment | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | 3 | 2 | quarter | yes |
| | | | | Revenue by product or service | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | 6 | 2 | quarter | yes |
| Amazon | 2026-09-30 | 1,302 | 2 | Revenue by business segment | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | 3 | 2 | quarter | yes |
| | | | | Revenue by product or service | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | 9 | 2 | quarter | yes |

## NVIDIA's annual report, as the command prints it

## Revenue by business segment

Concept `us-gaap:Revenues` on `us-gaap:StatementBusinessSegmentsAxis`; periods: fiscal year; USD millions. Members add up to the tagged total: yes.

| Member | Fiscal year ended 2026-01-25 | Fiscal year ended 2025-01-26 | Fiscal year ended 2024-01-28 |
|---|---|---|---|
| Compute and Networking Segment | 193,479 (+66.5%) | 116,193 (+145.1%) | 47,405 |
| Graphics Segment | 22,459 (+57.0%) | 14,304 (+5.8%) | 13,517 |
| Total (tagged, no dimension) | 215,938 (+65.5%) | 130,497 (+114.2%) | 60,922 |

- The members add up to the tagged total in each of the 3 period(s) checked, within the rounding the tags declare.
- Labels are derived from each member's tag name (the "Member" suffix dropped and the words split); they are not the company's own labels.

## Revenue by product or service

Concept `us-gaap:Revenues` on `srt:ProductOrServiceAxis`; periods: fiscal year; USD millions. Members add up to the tagged total: yes.

| Member | Fiscal year ended 2026-01-25 | Fiscal year ended 2025-01-26 | Fiscal year ended 2024-01-28 |
|---|---|---|---|
| Data Center | 193,737 (+68.2%) | 115,186 (+142.4%) | 47,525 |
| Compute | 162,361 (+58.9%) | 102,196 (+162.4%) | 38,950 |
| Networking | 31,376 (+141.5%) | 12,990 (+51.5%) | 8,575 |
| Gaming | 16,042 (+41.3%) | 11,350 (+8.6%) | 10,447 |
| Professional Visualization | 3,191 (+69.9%) | 1,878 (+20.9%) | 1,553 |
| Automotive | 2,349 (+38.7%) | 1,694 (+55.3%) | 1,091 |
| OEM and Other | 619 (+59.1%) | 389 (+27.1%) | 306 |
| Total (tagged, no dimension) | 215,938 (+65.5%) | 130,497 (+114.2%) | 60,922 |

- Data Center equals Compute plus Networking; these parts are tagged as members too. With Data Center counted once, the members add up to the tagged total in 3 of the 3 period(s) checked.
- Labels are derived from each member's tag name (the "Member" suffix dropped and the words split); they are not the company's own labels.

## Revenue by geography

Concept `us-gaap:Revenues` on `srt:StatementGeographicalAxis`; periods: fiscal year; USD millions. Members add up to the tagged total: yes.

| Member | Fiscal year ended 2026-01-25 | Fiscal year ended 2025-01-26 | Fiscal year ended 2024-01-28 |
|---|---|---|---|
| US | 149,617 (+93.1%) | 77,482 (+145.7%) | 31,533 |
| TW | 42,345 (+79.4%) | 23,600 (+58.3%) | 14,912 |
| China Including Hong Kong | 19,677 (-21.4%) | 25,048 (+103.1%) | 12,330 |
| Other Countries | 4,299 (-1.6%) | 4,367 (+103.4%) | 2,147 |
| Total (tagged, no dimension) | 215,938 (+65.5%) | 130,497 (+114.2%) | 60,922 |

- The members add up to the tagged total in each of the 3 period(s) checked, within the rounding the tags declare.
- Labels are derived from each member's tag name (the "Member" suffix dropped and the words split); they are not the company's own labels.

## Share of revenue by major customer

Concept `us-gaap:ConcentrationRiskPercentage1` on `srt:MajorCustomersAxis`; periods: fiscal year; percent of revenue. Members add up to the tagged total: not checked.

| Member | Fiscal year ended 2026-01-25 | Fiscal year ended 2025-01-26 | Fiscal year ended 2024-01-28 |
|---|---|---|---|
| Customer One · Compute and Networking Segment | 22.0% | 12.0% | 13.0% |
| Customer Two · Compute and Networking Segment | 14.0% | 11.0% | |

- Each value is one customer's share of revenue (benchmark us-gaap:SalesRevenueNetMember on us-gaap:ConcentrationRiskByBenchmarkAxis), as a fraction: 0.22 is 22%. Only the customers the filing discloses are tagged (usually those of 10% or more), so the shares have no total.
- Rows marked with · are also tagged with a business segment (us-gaap:StatementBusinessSegmentsAxis = nvda:ComputeAndNetworkingSegmentMember); the label after the · names it. The tags do not say whether such a share is of total revenue or of the segment's revenue; the filing's text does. Shares tagged with any other dimension (a geography, a product) are left out: they are shares of something else.
- Labels are derived from each member's tag name (the "Member" suffix dropped and the words split); they are not the company's own labels.

## Share of accounts receivable by major customer

Concept `us-gaap:ConcentrationRiskPercentage1` on `srt:MajorCustomersAxis`; periods: fiscal year; percent of accounts receivable. Members add up to the tagged total: not checked.

| Member | Fiscal year ended 2026-01-25 | Fiscal year ended 2025-01-26 |
|---|---|---|
| Customer One | 25.0% | 17.0% |
| Customer Two | 18.0% | 16.0% |
| Customer Three | 13.0% | |

- Each value is one customer's share of accounts receivable (benchmark us-gaap:AccountsReceivableMember on us-gaap:ConcentrationRiskByBenchmarkAxis), as a fraction: 0.22 is 22%. Only the customers the filing discloses are tagged (usually those of 10% or more), so the shares have no total.
- Kept apart from the share of revenue: a share of receivables at a date says who owes the company money, not who it sells most to.
- Labels are derived from each member's tag name (the "Member" suffix dropped and the words split); they are not the company's own labels.
