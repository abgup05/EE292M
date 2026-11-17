# Retrieval evaluation: variant `queries-heading`

Generated 2026-11-17T12:54:37.402048+00:00. Queries: the claim plus up to 4 queries per case from --queries (a case without an entry falls back to the claim alone); best score over queries, each passage scored with its section locator before its text.

- Golden set version 1, SHA-256 `4ef5c8d35bf11a1e…`; filings pinned in `eval/filings.json` (SHA-256 `ce02e068cd1d831e…`).
- Cases: 30 in the set; 24 answerable cases scored; 6 unanswerable cases not scored (retrieval always returns something; whether the answer says so is a generation question).
- Extra queries from `eval/queries.json` for 24 of 24 cases; 0 fell back to the claim alone.

| Metric | Value | Cases |
|---|---|---|
| recall@3 | 50.0% | 12 / 24 |
| recall@8 (pipeline cut: top 8, at most 5 per filing when there are several) | 75.0% | 18 / 24 |
| recall@20 | 83.3% | 20 / 24 |
| MRR (rank beyond 50 counts 0) | 0.472 | over 24 |

Every rate is over the 24 answerable cases. A case counts as a hit when a passage holding at least half of one of its must-retrieve excerpts ranks within the cut-off. recall@8 is what a thesis run would offer the engine: the top 8 with the pipeline's cap of 5 passages per filing applied when the case has more than one filing, exactly as `PassageIndex.cut`. recall@3, recall@20, the rank and MRR use the uncapped ranking; a rank beyond 50 is a miss.

## Per case

| Case | Ticker | Expected | Rank | Pipeline top 8 | Queries | First-ranked passage |
|---|---|---|---|---|---|---|
| nvda-data-center-drives-growth | NVDA | supports | 20 | no | claim + 4 | s3 Item 1. Business › Competition |
| nvda-few-buyers-dominate | NVDA | supports | 7 | #7 | claim + 4 | s3 Item 7. Management's Discussion and Analysis of Financial Conditio… |
| nvda-china-reopened | NVDA | challenges | 15 | no | claim + 4 | s1 Part II, Item 1A. Risk Factors |
| nvda-margin-widened | NVDA | supports | 3 | #3 | claim + 4 | s3 Item 7. Management's Discussion and Analysis of Financial Conditio… |
| nvda-cash-returned | NVDA | supports | 6 | #6 | claim + 4 | s2 Part II, Item 2. Unregistered Sales of Equity Securities and Use o… |
| nvda-no-borrowing | NVDA | challenges | 3 | #3 | claim + 4 | s3 Item 7. Management's Discussion and Analysis of Financial Conditio… |
| nvda-commitments-small | NVDA | challenges | 21 | no | claim + 4 | s3 Item 1A. Risk Factors › Risks Related to Our Global Operating Busi… |
| nvda-custom-silicon-threat | NVDA | supports | 25 | no | claim + 4 | s2 Part I, Item 2. Management's Discussion and Analysis of Financial … |
| nvda-crypto-lawsuit-over | NVDA | challenges | 2 | #2 | claim + 4 | s3 Item 15. Exhibits and Financial Statement Schedules › Securities C… |
| cost-members-renew | COST | supports | 6 | #6 | claim + 4 | s1 Item 1A. Risk Factors › Business and Operating Risks |
| cost-markup-widened | COST | mixed | 1 | #1 | claim + 4 | s1 Item 7. Management's Discussion and Analysis of Financial Conditio… |
| cost-tariffs-unrecovered | COST | challenges | 1 | #1 | claim + 4 | s1 Item 7. Management's Discussion and Analysis of Financial Conditio… |
| cost-north-america-dependence | COST | supports | not in top 50 | no | claim + 4 | s1 Item 1A. Risk Factors › Market and Other External Risks |
| aapl-china-shrinking | AAPL | challenges | 1 | #1 | claim + 4 | s1 Item 7. Management’s Discussion and Analysis of Financial Conditio… |
| aapl-margin-runway | AAPL | mixed | 1 | #1 | claim + 4 | s1 Item 7. Management’s Discussion and Analysis of Financial Conditio… |
| aapl-asian-assembly | AAPL | supports | 1 | #1 | claim + 4 | s1 Item 1A. Risk Factors › Business Risks |
| aapl-eu-app-store | AAPL | supports | 1 | #1 | claim + 4 | s1 Item 1A. Risk Factors › Legal and Regulatory Compliance Risks |
| msft-azure-growth | MSFT | supports | 6 | #6 | claim + 4 | s1 Part I, Item 2. MANAGEMENT’S DISCUSSION AND ANALYSIS OF FINANCIAL … |
| msft-cloud-margin | MSFT | challenges | 8 | #7 | claim + 4 | s2 Item 7. MANAGEMENT’S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITIO… |
| msft-ai-harm | MSFT | supports | 1 | #1 | claim + 4 | s1 Part II, Item 1A. RISK FACTORS › Other digital safety abuses |
| msft-never-breached | MSFT | challenges | 1 | #1 | claim + 4 | s2 Item 1A. RISK FACTORS › Security of our information technology |
| ko-north-america-volume | KO | challenges | 5 | #5 | claim + 4 | s2 Item 7. MANAGEMENT’S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITIO… |
| ko-pricing-lifts-margin | KO | supports | 1 | #1 | claim + 4 | s1 Part I, Item 2. Management’s Discussion and Analysis of Financial … |
| ko-irs-dispute-settled | KO | challenges | not in top 50 | no | claim + 4 | s2 Item 7. MANAGEMENT’S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITIO… |
