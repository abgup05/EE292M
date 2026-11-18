# The readings that would count, for an independent judge (claim-tests-foreign-c)

A program reads each claim an analyst writes about one company and, when it can, turns it into a
test that can be computed from the company's reported figures. Below are the 36 claims
of the 120 in this set whose test it would count; for the others it would count none.
For each one, decide whether the test means what the sentence says: **right** if computing the
test would answer exactly the question the sentence asks, **wrong** if it would answer a
different question (a different measure, period, comparison or threshold, or only part of the
sentence). Whether the claim is true is not the question.

## How to read a test

A test is written `left operator right`. It holds when the comparison is true.

**Operators.** `>` more than; `>=` at least; `<` less than; `<=` at most.

**Measures**, each for one company as a whole, with how a derived one is computed:

- `sga_ratio`: SG&A as a share of revenue. SG&A as a share of revenue is SG&A ÷ revenue.
- `sales_marketing_ratio`: Sales and marketing as a share of revenue. Sales and marketing as a share of revenue is that expense ÷ revenue.
- `opex_ratio`: Operating expenses as a share of revenue. Operating expenses as a share of revenue is total operating expenses (as reported, OperatingExpenses; else gross profit less operating income) ÷ revenue.
- `capex_ratio`: Capital expenditure as a share of revenue. Capital expenditure as a share of revenue is capex ÷ revenue.
- `sbc_ratio`: Stock-based compensation as a share of revenue. Stock-based compensation as a share of revenue is that expense ÷ revenue.
- `effective_tax_rate`: Effective tax rate. The effective tax rate here is income tax expense ÷ income before income taxes.
- `cash_and_securities`: Cash, cash equivalents and marketable securities. Cash and marketable securities here is cash and cash equivalents + current marketable securities (short-term investments); non-current securities are left out.
- `net_cash`: Net cash. Net cash here is cash and marketable securities − total debt (see each).
- `net_debt`: Net debt. Net debt here is total debt − cash and marketable securities (see each).
- `long_term_debt`: Long-term debt. The non-current part only; total debt adds the current part and commercial paper.
- `commercial_paper`: Commercial paper. Tagged only by a company that has issued commercial paper.
- `total_debt`: Total debt. Total debt here is long-term debt (non-current) + its current portion + commercial paper; a part the company does not report on that balance sheet counts as zero. Leases are left out.
- `marketable_securities`: Marketable securities (current). Current marketable securities only (short-term investments).
- `shareholder_returns`: Buybacks and dividends. Returned to shareholders here is share repurchases + dividends paid (cash flow statement); a company that pays no dividend counts zero for it.
- `share_repurchases`: Share repurchases. Cash paid for repurchases of common stock, from the cash flow statement.
- `dividends_paid`: Dividends paid. Cash dividends paid, from the cash flow statement.
- `diluted_shares`: Diluted share count. The weighted-average diluted share count of the period; it is never differenced, so a fourth quarter needs its own fact, and it has no four-quarter total.
- `total_operating_expenses`: Total operating expenses. Total operating expenses as reported (OperatingExpenses); where a company does not tag them, gross profit less operating income.
- `sga`: SG&A. SG&A as reported (SellingGeneralAndAdministrativeExpense); where a company tags only its parts, sales and marketing + general and administrative.
- `sales_marketing`: Sales and marketing. Tagged only by a company that reports sales and marketing on its own line.
- `general_admin`: General and administrative. Tagged only by a company that reports G&A on its own line.
- `sbc`: Stock-based compensation.
- `pretax_income`: Income before income taxes.
- `income_tax`: Income tax expense.
- `interest_expense`: Interest expense.
- `interest_income`: Interest income.
- `other_income`: Other income and expense.
- `d_and_a`: Depreciation and amortization.
- `deferred_revenue`: Deferred revenue. Deferred revenue here is the current + non-current contract liabilities (deferred or unearned revenue); a non-current part not reported counts as zero.
- `deferred_revenue_current`: Deferred revenue (current).
- `deferred_revenue_noncurrent`: Deferred revenue (non-current).
- `current_debt`: Current portion of debt.
- `total_assets`: Total assets.
- `total_liabilities`: Total liabilities.
- `equity`: Shareholders' equity.
- `goodwill`: Goodwill.
- `ppe`: Property and equipment, net.
- `accounts_payable`: Accounts payable.
- `cost_of_revenue`: Cost of revenue.
- `fcf_margin`: Free cash flow margin.
- `rnd_ratio`: R&D as a share of revenue.
- `gross_margin`: Gross margin.
- `operating_margin`: Operating margin.
- `net_margin`: Net margin.
- `free_cash_flow`: Free cash flow.
- `operating_cash_flow`: Operating cash flow.
- `capex`: Capital expenditure.
- `cash`: Cash and cash equivalents.
- `inventory`: Inventory.
- `receivables`: Accounts receivable.
- `eps_diluted`: Diluted EPS.
- `gross_profit`: Gross profit.
- `operating_income`: Operating income.
- `operating_expenses`: Operating expenses.
- `net_income`: Net income.
- `rnd`: Research and development.
- `revenue`: Revenue.

**Functions of a measure.**

- `measure[P]`: its value for period P (an amount over the period, or a balance at its end).
- `yoy(measure)[P]`: its growth over the same period a year earlier, in percent.
- `qoq(measure)[P]`: its growth over the previous quarter, in percent.
- `streak(measure)[P]`: how many periods in a row up to P it rose.
- `cagr(measure, Ny)[P]`: its compound annual growth over the N years to P, in percent.
- `share(segment "X")[filing]` or `share(geography "X")[filing]`: the share of total revenue of
  the one segment or geographic area named X, as the company's newest filing tags it, in percent.
- `max(share(customer))[filing]`: the largest single customer's share of revenue, in percent.
- `revenue(segment "X")[filing]` (or `geography`): a part of the company's own figure, here the
  revenue of the segment, product line or area named X, as the newest filing tags it;
  `yoy(revenue(segment "X"))[filing]` its change on a year earlier as the filing tags it. The
  measures a part has: `revenue` (Revenue), `operating_income` (Operating income); only a segment has an operating income.

**Periods** (the company's own fiscal calendar).

- `Q`: the latest quarter. `Q-1` is the quarter before it; `Q-4` the same quarter a year earlier.
- `FY`: the latest fiscal year. `FY-3` is three fiscal years before it.
- `FY2025`: the fiscal year the company calls 2025. `Q2 FY2027`: the second quarter of fiscal 2027.
- `TTM`: the four latest quarters together (the trailing twelve months); `TTM-4` the four
  quarters a year before.
- `filing`: the newest 10-K or 10-Q filing (for a share, or a part's figure).

**Constants.** `40%` is a percent; `$100B` is 100 billion US dollars; a plain number is a count
(of periods, or of shares for the diluted share count).

**One way of writing.** Each test is written one way: the more recent period on the left, growth
above zero as a rise (`revenue[Q] > revenue[Q-4]` rather than `yoy(revenue)[Q] > 0%`), and a count
of periods as "at least" (`>= 4` rather than `> 3`).

Example: "Gross margin is expanding" becomes `gross_margin[Q] > gross_margin[Q-4]`: the latest
quarter's gross margin is higher than the same quarter's a year earlier.

## The tests

| id | company | claim | test | verdict (right or wrong) | note |
|---|---|---|---|---|---|
| h003 | NVDA | FCF north of $90B in FY26. | `free_cash_flow[FY2026] > $90B` | | |
| h005 | NVDA | Gross margin widened sequentially in each of the last two quarters. | `streak(gross_margin)[Q] >= 2` | | |
| h006 | NVDA | The effective tax rate was higher in fiscal 2025 than in fiscal 2024. | `effective_tax_rate[FY2025] > effective_tax_rate[FY2024]` | | |
| h011 | NVDA | Diluted EPS more than doubled from fiscal 2024 to fiscal 2025. | `yoy(eps_diluted)[FY2025] > 100%` | | |
| h014 | NVDA | Income from operations beat $80 billion in fiscal 2025. | `operating_income[FY2025] > $80B` | | |
| h015 | NVDA | Payables are growing faster than cost of revenue. | `yoy(accounts_payable)[Q] > yoy(cost_of_revenue)[Q]` | | |
| h016 | NVDA | Revenue growth in the second quarter of fiscal 2026 over the first was above 10% sequentially. | `qoq(revenue)[Q2 FY2026] > 10%` | | |
| h017 | NVDA | SG&A is a sliver, less than 4% of revenue. | `sga_ratio[Q] < 4%` | | |
| h019 | NVDA | Dividends paid stayed below $1 billion in fiscal 2025. | `dividends_paid[FY2025] < $1B` | | |
| h021 | NVDA | Cost of revenue grew more than 50% in fiscal 2025. | `yoy(cost_of_revenue)[FY2025] > 50%` | | |
| h022 | NVDA | Over the three years to fiscal 2026 revenue compounded at more than 90% a year. | `cagr(revenue, 3y)[FY2026] > 90%` | | |
| h023 | NVDA | Net income more than tripled in fiscal 2024. | `yoy(net_income)[FY2024] > 200%` | | |
| h027 | NVDA | Operating margin was above 60% last quarter. | `operating_margin[Q] > 60%` | | |
| h043 | AAPL | Products net sales fell in fiscal 2023. | `yoy(revenue(segment "products"))[FY2023] < 0%` | | |
| h044 | AAPL | iPhone net sales cleared $200 billion in fiscal 2025. | `revenue(segment "iphone")[FY2025] > $200B` | | |
| h046 | AAPL | Rest of Asia Pacific grew faster than Japan last fiscal year. | `yoy(revenue(geography "japan"))[FY] < yoy(revenue(geography "rest of asia pacific"))[FY]` | | |
| h056 | AAPL | Free cash flow ran above 100% of net income last fiscal year. | `free_cash_flow[FY] > net_income[FY]` | | |
| h057 | AAPL | Diluted EPS in fiscal 2025 was above $7. | `eps_diluted[FY2025] > $7` | | |
| h058 | AAPL | Mac net sales were over $30 billion in fiscal 2025. | `revenue(segment "mac")[FY2025] > $30B` | | |
| h063 | AAPL | R&D spend passed $30 billion. | `rnd[Q] > $30B` | | |
| h065 | AAPL | Cost of sales grew more slowly than net sales in each of the last two fiscal years. | `each(2): yoy(cost_of_revenue)[FY] < yoy(revenue)[FY]` | | |
| h066 | AAPL | Diluted shares are down more than 10% since fiscal 2021. | `change(diluted_shares, FY2021)[FY] < -10%` | | |
| h082 | MSFT | Intelligent Cloud revenue grew by more than 20% in fiscal 2025. | `yoy(revenue(segment "intelligent cloud"))[FY2025] > 20%` | | |
| h083 | MSFT | Operating income topped $125 billion in fiscal 2025. | `operating_income[FY2025] > $125B` | | |
| h084 | MSFT | Capex is now above 20% of revenue. | `capex_ratio[Q] > 20%` | | |
| h085 | MSFT | Total stockholders' equity exceeded $300 billion at the June 2025 year end. | `equity[FY2025] > $300B` | | |
| h091 | MSFT | LinkedIn brought in over $17 billion in fiscal 2025. | `revenue(segment "linkedin")[FY2025] > $17B` | | |
| h093 | MSFT | Stock-based compensation expense is above $12 billion a year. | `sbc[FY] > $12B` | | |
| h095 | MSFT | The effective tax rate was higher in fiscal 2024 than in fiscal 2023. | `effective_tax_rate[FY2024] > effective_tax_rate[FY2023]` | | |
| h097 | MSFT | Accounts receivable stood above $50 billion at the latest year end. | `receivables[FY] > $50B` | | |
| h098 | MSFT | Inventories are small, under $2 billion. | `inventory[Q] < $2B` | | |
| h099 | MSFT | Unearned revenue was above $60 billion at the end of the fiscal year. | `deferred_revenue[FY] > $60B` | | |
| h100 | MSFT | Operating cash flow rose by more than 15% in fiscal 2025. | `yoy(operating_cash_flow)[FY2025] > 15%` | | |
| h102 | MSFT | Short-term investments fell year over year. | `marketable_securities[Q] < marketable_securities[Q-4]` | | |
| h103 | MSFT | R&D grew faster than sales and marketing last year. | `yoy(rnd)[FY] > yoy(sales_marketing)[FY]` | | |
| h105 | MSFT | Operating margin was higher last quarter than in the same quarter a year earlier. | `operating_margin[Q] > operating_margin[Q-4]` | | |
