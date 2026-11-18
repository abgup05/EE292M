# The readings that would count, for an independent judge (claim-tests-foreign)

A program reads each claim an analyst writes about one company and, when it can, turns it into a
test that can be computed from the company's reported figures. Below are the 31 claims
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
| f001 | NVDA | NVIDIA's revenue more than doubled in fiscal 2024. | `yoy(revenue)[FY2024] > 100%` | | |
| f004 | NVDA | Operating income grew faster than revenue in fiscal 2025. | `yoy(operating_income)[FY2025] > yoy(revenue)[FY2025]` | | |
| f005 | NVDA | Net income exceeded $50 billion in the most recent fiscal year. | `net_income[FY] > $50B` | | |
| f007 | NVDA | Quarterly revenue grew sequentially in each of the last six quarters. | `streak(revenue)[Q] >= 6` | | |
| f008 | NVDA | R&D spending as a share of revenue fell below 15% in fiscal 2025. | `rnd_ratio[FY2025] < 15%` | | |
| f013 | NVDA | Cash and marketable securities topped $40 billion at fiscal year-end. | `cash_and_securities[FY] > $40B` | | |
| f014 | NVDA | Long-term debt is under $10 billion. | `long_term_debt[Q] < $10B` | | |
| f015 | NVDA | Share repurchases exceeded $20 billion over the trailing twelve months. | `share_repurchases[TTM] > $20B` | | |
| f016 | NVDA | Capital expenditures at least doubled between fiscal 2024 and fiscal 2025. | `yoy(capex)[FY2025] >= 100%` | | |
| f017 | NVDA | A single customer accounted for more than 10% of revenue. | `max(share(customer))[filing] > 10%` | | |
| f018 | NVDA | Gaming revenue is now less than 10% of the total. | `share(segment "gaming")[filing] < 10%` | | |
| f023 | NVDA | Net margin hit 55% last quarter. | `net_margin[Q] >= 55%` | | |
| f024 | NVDA | Operating expenses are growing slower than gross profit. | `yoy(gross_profit)[Q] > yoy(operating_expenses)[Q]` | | |
| f041 | AAPL | Apple's total net sales were above $390 billion in fiscal 2024. | `revenue[FY2024] > $390B` | | |
| f046 | AAPL | Apple repurchased more than $90 billion of its stock last fiscal year. | `share_repurchases[FY] > $90B` | | |
| f048 | AAPL | Free cash flow exceeded $100 billion. | `free_cash_flow[FY] > $100B` | | |
| f053 | AAPL | EPS rose by more than 10% in fiscal 2025. | `yoy(eps_diluted)[FY2025] > 10%` | | |
| f059 | AAPL | iPad sales are less than 10% of the total. | `share(segment "ipad")[filing] < 10%` | | |
| f062 | AAPL | Net income was down in fiscal 2023 versus 2022. | `net_income[FY2023] < net_income[FY2022]` | | |
| f064 | AAPL | SG&A is growing more slowly than gross profit. | `yoy(gross_profit)[Q] > yoy(sga)[Q]` | | |
| f067 | AAPL | Net margin has held at or above 24% for the trailing twelve months. | `net_margin[TTM] >= 24%` | | |
| f081 | MSFT | Microsoft's revenue grew more than 14% in fiscal 2025. | `yoy(revenue)[FY2025] > 14%` | | |
| f083 | MSFT | Operating margin was above 44% last fiscal year. | `operating_margin[FY] > 44%` | | |
| f086 | MSFT | Net income topped $100 billion in fiscal 2025. | `net_income[FY2025] > $100B` | | |
| f087 | MSFT | Diluted EPS compounded at better than 15% over the past three fiscal years. | `cagr(eps_diluted, 3y)[FY] > 15%` | | |
| f088 | MSFT | More Personal Computing revenue is under 25% of the total. | `share(segment "more personal computing")[filing] < 25%` | | |
| f091 | MSFT | R&D expense exceeded $30 billion. | `rnd[FY] > $30B` | | |
| f095 | MSFT | Microsoft returned over $30 billion to shareholders through buybacks and dividends. | `shareholder_returns[FY] > $30B` | | |
| f098 | MSFT | Operating cash flow was over $120 billion on a trailing basis. | `operating_cash_flow[TTM] > $120B` | | |
| f099 | MSFT | Revenue from the United States is above half of the total. | `share(geography "united states")[filing] > 50%` | | |
| f106 | MSFT | Sales and marketing expense as a percent of revenue is shrinking. | `sales_marketing_ratio[Q] < sales_marketing_ratio[Q-4]` | | |
