Judge: Claude Sonnet 5.5 (claude-sonnet-5-5). I read only the judge's file (claim-readers-claim-tests-foreign-c-for-judge.md), nothing else in the repository.

| id | sentence | test | verdict | reason |
|---|---|---|---|---|
| h003 | FCF north of $90B in FY26. | `free_cash_flow[FY2026] > $90B` | right | Same measure, fiscal year, strict threshold. |
| h005 | Gross margin widened sequentially in each of the last two quarters. | `streak(gross_margin)[Q] >= 2` | right | Streak counts consecutive rises up to the latest quarter; at least 2 matches "each of the last two". |
| h006 | The effective tax rate was higher in fiscal 2025 than in fiscal 2024. | `effective_tax_rate[FY2025] > effective_tax_rate[FY2024]` | right | Correct measure, periods and direction. |
| h011 | Diluted EPS more than doubled from fiscal 2024 to fiscal 2025. | `yoy(eps_diluted)[FY2025] > 100%` | right | Doubling is +100% growth; "more than" is strict. |
| h014 | Income from operations beat $80 billion in fiscal 2025. | `operating_income[FY2025] > $80B` | right | Matches measure, year and threshold. |
| h015 | Payables are growing faster than cost of revenue. | `yoy(accounts_payable)[Q] > yoy(cost_of_revenue)[Q]` | right | Both growth rates over a year earlier at the latest quarter; no period stated, latest quarter is a fair reading. |
| h016 | Revenue growth in Q2 FY2026 over the first was above 10% sequentially. | `qoq(revenue)[Q2 FY2026] > 10%` | right | Sequential growth for that quarter, strict threshold. |
| h017 | SG&A is a sliver, less than 4% of revenue. | `sga_ratio[Q] < 4%` | right | SG&A share of revenue, strict threshold; latest quarter is a fair reading of "is". |
| h019 | Dividends paid stayed below $1 billion in fiscal 2025. | `dividends_paid[FY2025] < $1B` | right | Matches measure, year and threshold. |
| h021 | Cost of revenue grew more than 50% in fiscal 2025. | `yoy(cost_of_revenue)[FY2025] > 50%` | right | Matches. |
| h022 | Over the three years to fiscal 2026 revenue compounded at more than 90% a year. | `cagr(revenue, 3y)[FY2026] > 90%` | right | Matches. |
| h023 | Net income more than tripled in fiscal 2024. | `yoy(net_income)[FY2024] > 200%` | right | Tripling is +200%; strict. |
| h027 | Operating margin was above 60% last quarter. | `operating_margin[Q] > 60%` | right | Matches. |
| h043 | Products net sales fell in fiscal 2023. | `yoy(revenue(segment "products"))[FY2023] < 0%` | right | Growth below zero for FY2023. (The notation defines segment figures only at [filing]; the intent is clear, so I accept.) |
| h044 | iPhone net sales cleared $200 billion in fiscal 2025. | `revenue(segment "iphone")[FY2025] > $200B` | right | Matches. |
| h046 | Rest of Asia Pacific grew faster than Japan last fiscal year. | `yoy(revenue(geography "japan"))[FY] < yoy(revenue(geography "rest of asia pacific"))[FY]` | right | Same comparison written with the smaller one on the left; FY is the latest year. |
| h056 | Free cash flow ran above 100% of net income last fiscal year. | `free_cash_flow[FY] > net_income[FY]` | right | Above 100% of net income equals above net income. |
| h057 | Diluted EPS in fiscal 2025 was above $7. | `eps_diluted[FY2025] > $7` | right | Matches. |
| h058 | Mac net sales were over $30 billion in fiscal 2025. | `revenue(segment "mac")[FY2025] > $30B` | right | Matches. |
| h063 | R&D spend passed $30 billion. | `rnd[Q] > $30B` | wrong | $30B is an annual-scale figure; the test measures one quarter, so a different period (should be FY or TTM). |
| h065 | Cost of sales grew more slowly than net sales in each of the last two fiscal years. | `each(2): yoy(cost_of_revenue)[FY] < yoy(revenue)[FY]` | unsure | `each(2)` is not defined in the notation; I cannot tell that it applies the test to the latest two fiscal years. |
| h066 | Diluted shares are down more than 10% since fiscal 2021. | `change(diluted_shares, FY2021)[FY] < -10%` | unsure | `change(...)` is not defined in the notation (percent change from FY2021 to FY is likely, but it is not stated). |
| h082 | Intelligent Cloud revenue grew by more than 20% in fiscal 2025. | `yoy(revenue(segment "intelligent cloud"))[FY2025] > 20%` | right | Matches. |
| h083 | Operating income topped $125 billion in fiscal 2025. | `operating_income[FY2025] > $125B` | right | Matches. |
| h084 | Capex is now above 20% of revenue. | `capex_ratio[Q] > 20%` | right | Capex share of revenue at the latest quarter, strict. |
| h085 | Total stockholders' equity exceeded $300 billion at the June 2025 year end. | `equity[FY2025] > $300B` | right | Year-end balance for FY2025, strict. |
| h091 | LinkedIn brought in over $17 billion in fiscal 2025. | `revenue(segment "linkedin")[FY2025] > $17B` | right | Matches (the notation allows product lines as parts). |
| h093 | Stock-based compensation expense is above $12 billion a year. | `sbc[FY] > $12B` | right | Annual, latest fiscal year, strict. |
| h095 | The effective tax rate was higher in fiscal 2024 than in fiscal 2023. | `effective_tax_rate[FY2024] > effective_tax_rate[FY2023]` | right | Matches. |
| h097 | Accounts receivable stood above $50 billion at the latest year end. | `receivables[FY] > $50B` | right | Matches. |
| h098 | Inventories are small, under $2 billion. | `inventory[Q] < $2B` | right | Current balance (latest quarter), strict. |
| h099 | Unearned revenue was above $60 billion at the end of the fiscal year. | `deferred_revenue[FY] > $60B` | right | Deferred revenue is defined as current plus non-current unearned revenue; the year-end balance is tested. |
| h100 | Operating cash flow rose by more than 15% in fiscal 2025. | `yoy(operating_cash_flow)[FY2025] > 15%` | right | Matches. |
| h102 | Short-term investments fell year over year. | `marketable_securities[Q] < marketable_securities[Q-4]` | right | Current marketable securities are short-term investments; latest quarter against the same quarter a year earlier. |
| h103 | R&D grew faster than sales and marketing last year. | `yoy(rnd)[FY] > yoy(sales_marketing)[FY]` | right | Matches. |
| h105 | Operating margin was higher last quarter than in the same quarter a year earlier. | `operating_margin[Q] > operating_margin[Q-4]` | right | Matches. |
