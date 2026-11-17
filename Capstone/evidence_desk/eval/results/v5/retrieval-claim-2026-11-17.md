# Retrieval evaluation: variant `claim`

Generated 2026-11-17T12:54:29.580328+00:00. Queries: the claim text alone (the pipeline with no model key).

- Golden set version 1, SHA-256 `4ef5c8d35bf11a1e…`; filings pinned in `eval/filings.json` (SHA-256 `ce02e068cd1d831e…`).
- Cases: 30 in the set; 24 answerable cases scored; 6 unanswerable cases not scored (retrieval always returns something; whether the answer says so is a generation question).

| Metric | Value | Cases |
|---|---|---|
| recall@3 | 20.8% | 5 / 24 |
| recall@8 (pipeline cut: top 8, at most 5 per filing when there are several) | 37.5% | 9 / 24 |
| recall@20 | 54.2% | 13 / 24 |
| MRR (rank beyond 50 counts 0) | 0.258 | over 24 |

Every rate is over the 24 answerable cases. A case counts as a hit when a passage holding at least half of one of its must-retrieve excerpts ranks within the cut-off. recall@8 is what a thesis run would offer the engine: the top 8 with the pipeline's cap of 5 passages per filing applied when the case has more than one filing, exactly as `PassageIndex.cut`. recall@3, recall@20, the rank and MRR use the uncapped ranking; a rank beyond 50 is a miss.

## Per case

| Case | Ticker | Expected | Rank | Pipeline top 8 | Queries | First-ranked passage |
|---|---|---|---|---|---|---|
| nvda-data-center-drives-growth | NVDA | supports | 33 | no | claim | s3 Item 1. Business › Competition |
| nvda-few-buyers-dominate | NVDA | supports | not in top 50 | no | claim | s1 Part II, Item 1A. Risk Factors |
| nvda-china-reopened | NVDA | challenges | 13 | no | claim | s1 Part II, Item 1A. Risk Factors |
| nvda-margin-widened | NVDA | supports | 1 | #1 | claim | s1 Part I, Item 2. Management’s Discussion and Analysis of Financial … |
| nvda-cash-returned | NVDA | supports | not in top 50 | no | claim | s3 Item 12. Security Ownership of Certain Beneficial Owners and Manag… |
| nvda-no-borrowing | NVDA | challenges | not in top 50 | no | claim | s3 Item 15. Exhibits and Financial Statement Schedules › Note 7 - Cas… |
| nvda-commitments-small | NVDA | challenges | 28 | no | claim | s3 Item 1A. Risk Factors › Risks Related to Our Global Operating Busi… |
| nvda-custom-silicon-threat | NVDA | supports | 22 | no | claim | s2 Part II, Item 1A. Risk Factors |
| nvda-crypto-lawsuit-over | NVDA | challenges | not in top 50 | no | claim | s3 Item 1A. Risk Factors › Risks Related to Regulatory, Legal, Our St… |
| cost-members-renew | COST | supports | 4 | #4 | claim | s1 Item 1A. Risk Factors › Business and Operating Risks |
| cost-markup-widened | COST | mixed | 9 | no | claim | s1 Item 1. Business › ■Core Merchandise Categories: |
| cost-tariffs-unrecovered | COST | challenges | 7 | #7 | claim | s1 Item 1A. Risk Factors › Market and Other External Risks |
| cost-north-america-dependence | COST | supports | 48 | no | claim | s1 Item 1A. Risk Factors › Market and Other External Risks |
| aapl-china-shrinking | AAPL | challenges | 1 | #1 | claim | s1 Item 7. Management’s Discussion and Analysis of Financial Conditio… |
| aapl-margin-runway | AAPL | mixed | 1 | #1 | claim | s1 Item 7. Management’s Discussion and Analysis of Financial Conditio… |
| aapl-asian-assembly | AAPL | supports | 7 | #7 | claim | s1 Item 1A. Risk Factors › Macroeconomic and Industry Risks |
| aapl-eu-app-store | AAPL | supports | 1 | #1 | claim | s1 Item 1A. Risk Factors › Legal and Regulatory Compliance Risks |
| msft-azure-growth | MSFT | supports | 42 | no | claim | s1 Part II, Item 1A. RISK FACTORS › Business model competition |
| msft-cloud-margin | MSFT | challenges | 8 | #8 | claim | s2 Item 1. BUSINESS › Enterprise and Partner Services |
| msft-ai-harm | MSFT | supports | 41 | no | claim | s1 Part II, Item 1A. RISK FACTORS › Other digital safety abuses |
| msft-never-breached | MSFT | challenges | 1 | #1 | claim | s1 Part II, Item 1A. RISK FACTORS › Security of our information techn… |
| ko-north-america-volume | KO | challenges | 14 | no | claim | s1 Part I, Item 2. Management’s Discussion and Analysis of Financial … |
| ko-pricing-lifts-margin | KO | supports | 11 | no | claim | s2 Item 1A. RISK FACTORS › RISKS RELATED TO REGULATORY AND LEGAL MATT… |
| ko-irs-dispute-settled | KO | challenges | not in top 50 | no | claim | s2 Item 8. FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA › NOTE 15: INC… |
