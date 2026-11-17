# The filing comparison on eight companies' annual reports

Each block is cut from the output of `make changes ARGS="<TICKER> --form 10-K"`, run on 17 November 2026 (UTC 14:07 to 14:08) against live SEC EDGAR, with the counts as they are since the second referee's first finding was fixed: the two filings compared, any note the run made, and the whole table "Paragraphs by Item".

The five counts are of paragraphs. The last column is the same four classes for short lines and table rows: unchanged / numbers only / added / removed. Every line of each filing is in exactly one count (`tests/test_filing_diff.py::test_every_line_of_two_real_filings_is_counted_exactly_once`).

No person has read these comparisons. The threshold for "reworded" was set on NVIDIA's filings; the pairs near it were also read, by a model, for Apple and Coca-Cola (`../filing-changes.md`).

## NVIDIA (NVDA)

| Period end | 2025-01-26 | 2026-01-25 |
| Filed | 2025-02-26 | 2026-02-25 |
| Accession | 0001045810-25-000023 | 0001045810-26-000021 |
| Item coverage | 97.0% | 96.9% |

Notes made by the run: none.

| Item | In | Unchanged | Numbers only | Reworded | Added | Removed | Short lines and table rows: unchanged / numbers only / added / removed |
|---|---|---|---|---|---|---|---|
| Cover page | both | 13 | 3 | 4 | 0 | 2 | 35 / 17 / 9 / 5 |
| Item 1. Business | both | 24 | 1 | 37 | 29 | 41 | 4 / 5 / 0 / 3 |
| Item 1A. Risk Factors | both | 124 | 1 | 51 | 34 | 22 | 15 / 0 / 2 / 1 |
| Item 1B. Unresolved Staff Comments | both | 0 | 0 | 0 | 0 | 0 | 0 / 0 / 1 / 1 |
| Item 1C. Cybersecurity | both | 4 | 0 | 3 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 2. Properties | both | 1 | 0 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 3. Legal Proceedings | both | 1 | 0 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 4. Mine Safety Disclosures | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 5. Market for Registrant's Common Equity, Related Stockholder Matters and Issuer Purchases of Equity Securities | both | 3 | 6 | 5 | 0 | 2 | 1 / 8 / 0 / 0 |
| Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations | both | 13 | 8 | 33 | 28 | 30 | 21 / 41 / 13 / 22 |
| Item 7A. Quantitative and Qualitative Disclosures about Market Risk | both | 3 | 2 | 3 | 3 | 1 | 0 / 0 / 0 / 0 |
| Item 8. Financial Statements and Supplementary Data | both | 1 | 0 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 9. Changes in and Disagreements with Accountants on Accounting and Financial Disclosure | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 9A. Controls and Procedures | both | 1 | 2 | 2 | 1 | 0 | 1 / 0 / 0 / 0 |
| Item 9B. Other Information | both | 2 | 0 | 1 | 0 | 1 | 0 / 0 / 2 / 3 |
| Item 9C. Disclosure Regarding Foreign Jurisdictions that Prevent Inspections | both | 0 | 1 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 10. Directors, Executive Officers and Corporate Governance | both | 1 | 5 | 0 | 1 | 0 | 0 / 0 / 0 / 0 |
| Item 11. Executive Compensation | both | 0 | 1 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 12. Security Ownership of Certain Beneficial Owners and Management and Related Stockholder Matters | both | 0 | 2 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 13. Certain Relationships and Related Transactions, and Director Independence | both | 0 | 1 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 14. Principal Accountant Fees and Services | both | 0 | 1 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 15. Exhibits and Financial Statement Schedules | both | 58 | 25 | 79 | 37 | 33 | 257 / 274 / 123 / 161 |
| Item 16. Form 10-K Summary | both | 2 | 1 | 0 | 0 | 0 | 18 / 12 / 0 / 6 |
| Total | | 251 | 60 | 218 | 133 | 132 | 355 / 357 / 150 / 202 |

## Apple (AAPL)

| Period end | 2025-09-27 | 2026-09-26 |
| Filed | 2025-10-31 | 2026-11-03 |
| Accession | 0000320193-25-000079 | 0000320193-26-000026 |
| Item coverage | 95.8% | 96.3% |

Notes made by the run: none.

| Item | In | Unchanged | Numbers only | Reworded | Added | Removed | Short lines and table rows: unchanged / numbers only / added / removed |
|---|---|---|---|---|---|---|---|
| Cover page | both | 14 | 3 | 1 | 0 | 0 | 40 / 23 / 1 / 1 |
| Item 1. Business | both | 17 | 0 | 13 | 2 | 1 | 9 / 4 / 0 / 0 |
| Item 1A. Risk Factors | both | 34 | 0 | 58 | 24 | 8 | 1 / 12 / 3 / 0 |
| Item 1B. Unresolved Staff Comments | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 1C. Cybersecurity | both | 4 | 0 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 2. Properties | both | 0 | 1 | 0 | 0 | 0 | 0 / 0 / 0 / 1 |
| Item 3. Legal Proceedings | both | 2 | 0 | 1 | 1 | 1 | 4 / 0 / 1 / 0 |
| Item 4. Mine Safety Disclosures | both | 0 | 0 | 0 | 0 | 0 | 1 / 1 / 0 / 0 |
| Item 5. Market for Registrant’s Common Equity, Related Stockholder Matters and Issuer Purchases of Equity Securities | both | 1 | 3 | 1 | 1 | 0 | 1 / 12 / 1 / 0 |
| Item 6. \[Reserved\] | both | 0 | 0 | 0 | 0 | 0 | 0 / 1 / 0 / 0 |
| Item 7. Management’s Discussion and Analysis of Financial Condition and Results of Operations | both | 5 | 14 | 18 | 5 | 9 | 26 / 38 / 15 / 18 |
| Item 7A. Quantitative and Qualitative Disclosures About Market Risk | both | 3 | 2 | 0 | 0 | 0 | 0 / 4 / 0 / 0 |
| Item 8. Financial Statements and Supplementary Data | both | 58 | 37 | 17 | 8 | 5 | 105 / 271 / 97 / 48 |
| Item 9. Changes in and Disagreements with Accountants on Accounting and Financial Disclosure | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 9A. Controls and Procedures | both | 4 | 3 | 1 | 0 | 0 | 0 / 1 / 0 / 0 |
| Item 9B. Other Information | both | 0 | 0 | 0 | 1 | 1 | 0 / 0 / 0 / 1 |
| Item 9C. Disclosure Regarding Foreign Jurisdictions that Prevent Inspections | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 10. Directors, Executive Officers and Corporate Governance | both | 0 | 1 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 11. Executive Compensation | both | 0 | 1 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 12. Security Ownership of Certain Beneficial Owners and Management and Related Stockholder Matters | both | 0 | 1 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 13. Certain Relationships and Related Transactions, and Director Independence | both | 0 | 1 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 14. Principal Accountant Fees and Services | both | 0 | 1 | 0 | 0 | 0 | 0 / 1 / 0 / 0 |
| Item 15. Exhibit and Financial Statement Schedules | both | 10 | 0 | 0 | 4 | 0 | 52 / 19 / 2 / 5 |
| Item 16. Form 10-K Summary | both | 2 | 0 | 1 | 0 | 0 | 14 / 10 / 6 / 4 |
| Total | | 154 | 68 | 111 | 46 | 25 | 256 / 397 / 126 / 78 |

## Microsoft (MSFT)

| Period end | 2025-06-30 | 2026-06-30 |
| Filed | 2025-07-30 | 2026-07-29 |
| Accession | 0000950170-25-100235 | 0001193125-26-323660 |
| Item coverage | 98.2% | 98.2% |

Notes made by the run: none.

| Item | In | Unchanged | Numbers only | Reworded | Added | Removed | Short lines and table rows: unchanged / numbers only / added / removed |
|---|---|---|---|---|---|---|---|
| Cover page | both | 10 | 2 | 0 | 0 | 0 | 45 / 14 / 0 / 0 |
| Item 1. BUSINESS | both | 70 | 1 | 31 | 6 | 21 | 55 / 6 / 3 / 3 |
| Item 1A. RISK FACTORS | both | 28 | 0 | 45 | 27 | 10 | 31 / 0 / 1 / 0 |
| Item 1B. UNRESOLVED STAFF COMMENTS | both | 0 | 1 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 1C. CYBERSECURITY | both | 3 | 0 | 6 | 1 | 4 | 3 / 0 / 0 / 3 |
| Item 2. PROPERTIES | both | 0 | 2 | 1 | 0 | 0 | 2 / 3 / 0 / 0 |
| Item 3. LEGAL PROCEEDINGS | both | 1 | 0 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 4. MINE SAFETY DISCLOSURES | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 5. MARKET FOR REGISTRANT’S COMMON EQUITY, RELATED STOCKHOLDER MATTERS, AND ISSUER PURCHASES OF EQUITY SECURITIES | both | 2 | 4 | 0 | 0 | 2 | 5 / 5 / 0 / 1 |
| Item 7. MANAGEMENT’S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS | both | 49 | 16 | 31 | 28 | 25 | 61 / 50 / 32 / 14 |
| Item 7A. QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK | both | 6 | 5 | 0 | 0 | 0 | 3 / 1 / 0 / 0 |
| Item 8. FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA | both | 137 | 28 | 36 | 10 | 10 | 251 / 380 / 98 / 66 |
| Item 9. CHANGES IN AND DISAGREEMENTS WITH ACCOUNTANTS ON ACCOUNTING AND FINANCIAL DISCLOSURE | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 9A. CONTROLS AND PROCEDURES | both | 7 | 3 | 0 | 0 | 0 | 2 / 1 / 1 / 1 |
| Item 9B. OTHER INFORMATION | both | 0 | 0 | 1 | 2 | 0 | 0 / 0 / 1 / 0 |
| Item 9C. DISCLOSURE REGARDING FOREIGN JURISDICTIONS THAT PREVENT INSPECTIONS | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 10. DIRECTORS, EXECUTIVE OFFICERS, AND CORPORATE GOVERNANCE | both | 2 | 1 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 11. EXECUTIVE COMPENSATION | both | 1 | 0 | 0 | 0 | 0 | 0 / 0 / 1 / 0 |
| Item 12. SECURITY OWNERSHIP OF CERTAIN BENEFICIAL OWNERS AND MANAGEMENT AND RELATED STOCKHOLDER MATTERS | both | 1 | 0 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 13. CERTAIN RELATIONSHIPS AND RELATED TRANSACTIONS, AND DIRECTOR INDEPENDENCE | both | 1 | 0 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 14. PRINCIPAL ACCOUNTANT FEES AND SERVICES | both | 1 | 0 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 15. EXHIBIT AND FINANCIAL STATEMENT SCHEDULES | both | 8 | 0 | 0 | 1 | 2 | 35 / 31 / 8 / 7 |
| Item 16. FORM 10-K SUMMARY | both | 0 | 2 | 0 | 0 | 0 | 32 / 0 / 4 / 2 |
| Total | | 327 | 65 | 151 | 75 | 74 | 528 / 491 / 149 / 97 |

## Coca-Cola (KO)

| Period end | 2024-12-31 | 2025-12-31 |
| Filed | 2025-02-20 | 2026-02-20 |
| Accession | 0000021344-25-000011 | 0001628280-26-010047 |
| Item coverage | 98.5% | 98.6% |

Notes made by the run: none.

| Item | In | Unchanged | Numbers only | Reworded | Added | Removed | Short lines and table rows: unchanged / numbers only / added / removed |
|---|---|---|---|---|---|---|---|
| Cover page | both | 12 | 3 | 2 | 0 | 0 | 63 / 6 / 1 / 1 |
| Item 1. BUSINESS | both | 61 | 3 | 28 | 4 | 1 | 11 / 0 / 1 / 2 |
| Item 1A. RISK FACTORS | both | 59 | 0 | 39 | 7 | 9 | 1 / 0 / 0 / 0 |
| Item 1B. UNRESOLVED STAFF COMMENTS | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 1C. CYBERSECURITY | both | 5 | 0 | 4 | 0 | 1 | 0 / 0 / 0 / 0 |
| Item 2. PROPERTIES | both | 2 | 1 | 1 | 0 | 0 | 3 / 4 / 2 / 3 |
| Item 3. LEGAL PROCEEDINGS | both | 16 | 3 | 8 | 3 | 3 | 3 / 0 / 0 / 0 |
| Item 4. MINE SAFETY DISCLOSURES | both | 1 | 7 | 4 | 1 | 1 | 3 / 0 / 0 / 0 |
| Item 5. MARKET FOR REGISTRANT’S COMMON EQUITY, RELATED STOCKHOLDER MATTERS AND ISSUER PURCHASES OF EQUITY SECURITIES | both | 3 | 5 | 1 | 0 | 0 | 3 / 8 / 0 / 0 |
| Item 7. MANAGEMENT’S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS | both | 77 | 23 | 79 | 23 | 28 | 30 / 56 / 27 / 57 |
| Item 7A. QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK | both | 5 | 3 | 2 | 1 | 0 | 0 / 0 / 0 / 0 |
| Item 8. FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA | both | 180 | 70 | 93 | 49 | 59 | 266 / 478 / 222 / 202 |
| Item 9. CHANGES IN AND DISAGREEMENTS WITH ACCOUNTANTS ON ACCOUNTING AND FINANCIAL DISCLOSURE | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 9A. CONTROLS AND PROCEDURES | both | 0 | 3 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 9B. OTHER INFORMATION | both | 0 | 0 | 1 | 0 | 2 | 0 / 0 / 0 / 0 |
| Item 9C. DISCLOSURE REGARDING FOREIGN JURISDICTIONS THAT PREVENT INSPECTIONS | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 10. DIRECTORS, EXECUTIVE OFFICERS AND CORPORATE GOVERNANCE | both | 0 | 0 | 1 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 11. EXECUTIVE COMPENSATION | both | 0 | 0 | 1 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 12. SECURITY OWNERSHIP OF CERTAIN BENEFICIAL OWNERS AND MANAGEMENT AND RELATED STOCKHOLDER MATTERS | both | 0 | 0 | 1 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 13. CERTAIN RELATIONSHIPS AND RELATED TRANSACTIONS, AND DIRECTOR INDEPENDENCE | both | 0 | 0 | 1 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 14. PRINCIPAL ACCOUNTANT FEES AND SERVICES | both | 0 | 0 | 1 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 15. EXHIBITS AND FINANCIAL STATEMENT SCHEDULES | both | 71 | 2 | 2 | 0 | 0 | 136 / 5 / 8 / 5 |
| Item 16. FORM 10-K SUMMARY | both | 3 | 0 | 0 | 0 | 0 | 19 / 9 / 4 / 1 |
| Total | | 495 | 123 | 269 | 88 | 104 | 541 / 566 / 265 / 271 |

## JPMorgan Chase (JPM)

| Period end | 2024-12-31 | 2025-12-31 |
| Filed | 2025-02-14 | 2026-02-13 |
| Accession | 0000019617-25-000270 | 0001628280-26-008131 |
| Item coverage | 99.4% | 99.4% |

Notes made by the run: none.

| Item | In | Unchanged | Numbers only | Reworded | Added | Removed | Short lines and table rows: unchanged / numbers only / added / removed |
|---|---|---|---|---|---|---|---|
| Cover page | both | 21 | 1 | 0 | 1 | 0 | 20 / 27 / 2 / 1 |
| Item 1. Business | both | 18 | 6 | 35 | 12 | 18 | 6 / 8 / 10 / 10 |
| Item 1A. Risk Factors | both | 85 | 0 | 215 | 173 | 225 | 66 / 0 / 81 / 65 |
| Item 1B. Unresolved Staff Comments | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 1C. Cybersecurity | both | 0 | 1 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 2. Properties | both | 0 | 3 | 0 | 2 | 1 | 9 / 16 / 2 / 2 |
| Item 3. Legal Proceedings | both | 1 | 0 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 4. Mine Safety Disclosures | both | 1 | 5 | 3 | 0 | 1 | 1 / 4 / 5 / 4 |
| Item 6. Reserved | both | 1 | 1 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 7A. Quantitative and Qualitative Disclosures About Market Risk | both | 0 | 0 | 1 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 8. Financial Statements and Supplementary Data | both | 1 | 2 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 9A. Controls and Procedures | both | 1 | 1 | 2 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 9B. Other Information | both | 1 | 0 | 3 | 6 | 1 | 0 / 0 / 11 / 5 |
| Item 9C. Disclosure regarding Foreign Jurisdictions that Prevent Inspections | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 1 |
| Item 10. Directors, Executive Officers and Corporate Governance | both | 1 | 8 | 2 | 1 | 3 | 1 / 3 / 1 / 0 |
| Item 11. Executive Compensation | both | 5 | 2 | 1 | 0 | 0 | 2 / 1 / 0 / 0 |
| Item 13. Certain Relationships and Related Transactions, and Director Independence | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 14. Principal Accounting Fees and Services | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 15. Exhibits, Financial Statement Schedules | both | 1335 | 351 | 586 | 262 | 272 | 1551 / 2375 / 733 / 759 |
| Total | | 1471 | 381 | 848 | 457 | 521 | 1662 / 2434 / 845 / 847 |

## Tesla (TSLA)

| Period end | 2024-12-31 | 2025-12-31 |
| Filed | 2025-01-30 | 2026-01-29 |
| Accession | 0001628280-25-003063 | 0001628280-26-003952 |
| Item coverage | 97.8% | 97.9% |

Notes made by the run: none.

| Item | In | Unchanged | Numbers only | Reworded | Added | Removed | Short lines and table rows: unchanged / numbers only / added / removed |
|---|---|---|---|---|---|---|---|
| Cover page | both | 12 | 3 | 1 | 0 | 0 | 34 / 21 / 0 / 0 |
| Item 1. BUSINESS | both | 24 | 1 | 37 | 14 | 36 | 16 / 0 / 0 / 0 |
| Item 1A. RISK FACTORS | both | 62 | 2 | 45 | 15 | 13 | 3 / 0 / 0 / 0 |
| Item 1B. UNRESOLVED STAFF COMMENTS | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 1C. CYBERSECURITY | both | 8 | 2 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 2. PROPERTIES | both | 2 | 0 | 0 | 0 | 0 | 9 / 0 / 0 / 0 |
| Item 3. LEGAL PROCEEDINGS | both | 0 | 0 | 1 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 4. MINE SAFETY DISCLOSURES | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 5. MARKET FOR REGISTRANT’S COMMON EQUITY, RELATED STOCKHOLDER MATTERS AND ISSUER PURCHASES OF EQUITY SECURITIES | both | 3 | 2 | 0 | 0 | 1 | 1 / 0 / 1 / 0 |
| Item 7. MANAGEMENT’S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS | both | 11 | 3 | 48 | 22 | 15 | 19 / 42 / 14 / 24 |
| Item 7A. QUANTITATIVE AND QUALITATIVE DISCLOSURES ABOUT MARKET RISK | both | 2 | 1 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 8. FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA | both | 83 | 31 | 93 | 70 | 26 | 209 / 317 / 142 / 125 |
| Item 9. CHANGES IN AND DISAGREEMENTS WITH ACCOUNTANTS ON ACCOUNTING AND FINANCIAL DISCLOSURE | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 9A. CONTROLS AND PROCEDURES | both | 3 | 4 | 1 | 0 | 0 | 3 / 0 / 0 / 0 |
| Item 9B. OTHER INFORMATION | both | 0 | 1 | 0 | 5 | 1 | 0 / 0 / 2 / 0 |
| Item 9C. DISCLOSURE REGARDING FOREIGN JURISDICTIONS THAT PREVENT INSPECTIONS | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 10. DIRECTORS, EXECUTIVE OFFICERS AND CORPORATE GOVERNANCE | both | 0 | 0 | 1 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 11. EXECUTIVE COMPENSATION | both | 0 | 1 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 12. SECURITY OWNERSHIP OF CERTAIN BENEFICIAL OWNERS AND MANAGEMENT AND RELATED STOCKHOLDER MATTERS | both | 0 | 1 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 13. CERTAIN RELATIONSHIPS AND RELATED TRANSACTIONS AND DIRECTOR INDEPENDENCE | both | 0 | 1 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 14. PRINCIPAL ACCOUNTANT FEES AND SERVICES | both | 0 | 1 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 15. EXHIBITS AND FINANCIAL STATEMENT SCHEDULES | both | 6 | 0 | 0 | 1 | 1 | 49 / 5 / 11 / 109 |
| Item 16. FORM 10-K SUMMARY | both | 2 | 0 | 0 | 0 | 0 | 15 / 9 / 4 / 1 |
| Total | | 218 | 54 | 227 | 127 | 93 | 362 / 394 / 174 / 259 |

## Costco (COST)

| Period end | 2025-08-31 | 2026-08-30 |
| Filed | 2025-10-08 | 2026-10-07 |
| Accession | 0000909832-25-000101 | 0000909832-26-000093 |
| Item coverage | 96.3% | 96.4% |

Notes made by the run: none.

| Item | In | Unchanged | Numbers only | Reworded | Added | Removed | Short lines and table rows: unchanged / numbers only / added / removed |
|---|---|---|---|---|---|---|---|
| Cover page | both | 11 | 3 | 2 | 0 | 0 | 34 / 17 / 0 / 0 |
| Item 1. Business | both | 12 | 4 | 17 | 2 | 6 | 8 / 14 / 8 / 10 |
| Item 1A. Risk Factors | both | 40 | 0 | 28 | 4 | 10 | 1 / 0 / 0 / 3 |
| Item 1B. Unresolved Staff Comments | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 1C. Cybersecurity | both | 2 | 0 | 4 | 0 | 1 | 0 / 0 / 0 / 0 |
| Item 2. Properties | both | 0 | 1 | 1 | 0 | 0 | 2 / 5 / 0 / 0 |
| Item 3. Legal Proceedings | both | 1 | 0 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 4. Mine Safety Disclosures | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 5. Market for Registrant’s Common Equity, Related Stockholder Matters and Issuer Purchases of Equity Securities | both | 5 | 2 | 1 | 0 | 0 | 6 / 17 / 0 / 0 |
| Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations (amounts in millions, except per share, share, percentages and warehouse count data) | both | 10 | 6 | 38 | 6 | 5 | 8 / 38 / 2 / 4 |
| Item 7A. Quantitative and Qualitative Disclosures About Market Risk (amounts in millions) | both | 2 | 2 | 3 | 1 | 1 | 3 / 0 / 0 / 0 |
| Item 8. Financial Statements and Supplementary Data | both | 76 | 32 | 36 | 14 | 13 | 146 / 234 / 75 / 48 |
| Item 9. Changes in and Disagreements with Accountants on Accounting and Financial Disclosure | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 9A. Controls and Procedures | both | 1 | 4 | 1 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 9B. Other Information | both | 0 | 1 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 9C. Disclosure Regarding Foreign Jurisdictions that Prevent Inspections | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 10. Directors, Executive Officers, and Corporate Governance | both | 0 | 0 | 1 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 11. Executive Compensation | both | 1 | 0 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 12. Security Ownership of Certain Beneficial Owners and Management and Related Stockholder Matters | both | 1 | 0 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 13. Certain Relationships and Related Transactions, and Director Independence | both | 1 | 0 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 14. Principal Accounting Fees and Services | both | 2 | 0 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 15. Exhibits, Financial Statement Schedules | both | 6 | 0 | 0 | 0 | 0 | 45 / 1 / 3 / 0 |
| Item 16. Form 10-K Summary | both | 2 | 0 | 0 | 0 | 0 | 10 / 2 / 6 / 6 |
| Total | | 173 | 55 | 132 | 27 | 36 | 267 / 328 / 94 / 71 |

## Amazon (AMZN)

| Period end | 2024-12-31 | 2025-12-31 |
| Filed | 2025-02-07 | 2026-02-06 |
| Accession | 0001018724-25-000004 | 0001018724-26-000004 |
| Item coverage | 97.9% | 97.9% |

Notes made by the run: none.

| Item | In | Unchanged | Numbers only | Reworded | Added | Removed | Short lines and table rows: unchanged / numbers only / added / removed |
|---|---|---|---|---|---|---|---|
| Cover page | both | 13 | 1 | 0 | 0 | 0 | 45 / 17 / 0 / 0 |
| Item 1. Business | both | 17 | 3 | 4 | 0 | 0 | 2 / 15 / 3 / 3 |
| Item 1A. Risk Factors | both | 80 | 0 | 26 | 4 | 5 | 16 / 0 / 0 / 0 |
| Item 1B. Unresolved Staff Comments | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 1C. Cybersecurity | both | 5 | 0 | 1 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 2. Properties | both | 3 | 4 | 0 | 0 | 0 | 4 / 9 / 0 / 0 |
| Item 3. Legal Proceedings | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 4. Mine Safety Disclosures | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 5. Market for the Registrant’s Common Stock, Related Shareholder Matters, and Issuer Purchases of Equity Securities | both | 1 | 1 | 0 | 0 | 0 | 2 / 0 / 0 / 0 |
| Item 7. Management’s Discussion and Analysis of Financial Condition and Results of Operations | both | 26 | 10 | 31 | 8 | 13 | 32 / 49 / 11 / 33 |
| Item 7A. Quantitative and Qualitative Disclosures About Market Risk | both | 3 | 3 | 3 | 0 | 0 | 0 / 9 / 4 / 6 |
| Item 8. Financial Statements and Supplementary Data | both | 101 | 32 | 65 | 33 | 20 | 149 / 265 / 113 / 76 |
| Item 9. Changes in and Disagreements with Accountants On Accounting and Financial Disclosure | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 9A. Controls and Procedures | both | 6 | 4 | 1 | 0 | 0 | 4 / 1 / 0 / 0 |
| Item 9B. Other Information | both | 0 | 0 | 5 | 2 | 0 | 0 / 0 / 0 / 0 |
| Item 9C. Disclosure Regarding Foreign Jurisdictions that Prevent Inspections | both | 0 | 0 | 0 | 0 | 0 | 1 / 0 / 0 / 0 |
| Item 10. Directors, Executive Officers, and Corporate Governance | both | 0 | 0 | 1 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 11. Executive Compensation | both | 0 | 1 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 12. Security Ownership of Certain Beneficial Owners and Management and Related Shareholder Matters | both | 0 | 1 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 13. Certain Relationships and Related Transactions, and Director Independence | both | 0 | 1 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 14. Principal Accountant Fees and Services | both | 0 | 1 | 0 | 0 | 0 | 0 / 0 / 0 / 0 |
| Item 15. Exhibits, Financial Statement Schedules | both | 23 | 5 | 2 | 1 | 0 | 13 / 4 / 1 / 2 |
| Item 16. Form 10-K Summary | both | 0 | 2 | 0 | 0 | 0 | 34 / 0 / 0 / 0 |
| Total | | 278 | 69 | 139 | 48 | 38 | 306 / 369 / 132 / 120 |

## JPMorgan before the index fix

The first run for JPM, before `filings_of_form` read the older pages of EDGAR's index, ended with exit code 1 and this message:

    SEC EDGAR: JPMORGAN CHASE & CO has 1 10-K filing(s) in EDGAR's recent index; two are needed to compare
