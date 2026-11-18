# The readings that would count, for an independent judge (claim-tests-foreign-b)

A program reads each claim an analyst writes about one company and, when it can, turns it into a
test that can be computed from the company's reported figures. Below are the 20 claims
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
| g004 | NVDA | Gross profit came in above $100 billion in fiscal 2026. | `gross_profit[FY2026] > $100B` | | |
| g009 | NVDA | Total shareholders' equity more than doubled from fiscal 2024 to fiscal 2025. | `yoy(equity)[FY2025] > 100%` | | |
| g014 | NVDA | Operating expenses were under 15% of revenue in the most recent quarter. | `opex_ratio[Q] < 15%` | | |
| g018 | NVDA | The income tax provision was above 13% of pre-tax income last year. | `effective_tax_rate[FY] > 13%` | | |
| g022 | NVDA | Accounts payable has risen four quarters in a row. | `streak(accounts_payable)[Q] >= 4` | | |
| g025 | NVDA | FCF margin above 40% on a trailing twelve month basis. | `fcf_margin[TTM] > 40%` | | |
| g027 | NVDA | Stock-based compensation topped $4 billion in fiscal 2025. | `sbc[FY2025] > $4B` | | |
| g046 | AAPL | Japan and Rest of Asia Pacific together are less than 15% of net sales. | `share(segment "japan and rest of asia pacific together")[filing] < 15%` | | |
| g051 | AAPL | Commercial paper outstanding is down from a year ago. | `commercial_paper[Q] < commercial_paper[Q-4]` | | |
| g055 | AAPL | Total shareholders' equity remains below $100 billion. | `equity[Q] < $100B` | | |
| g062 | AAPL | The effective tax rate rose above 16% last fiscal year. | `effective_tax_rate[FY] > 16%` | | |
| g063 | AAPL | Total liabilities exceed $260 billion. | `total_liabilities[Q] > $260B` | | |
| g066 | AAPL | Greater China is under 20% of net sales. | `share(geography "greater china")[filing] < 20%` | | |
| g081 | MSFT | Revenue was above $270 billion in fiscal 2025. | `revenue[FY2025] > $270B` | | |
| g087 | MSFT | Net margin was above 35% in fiscal 2025. | `net_margin[FY2025] > 35%` | | |
| g089 | MSFT | Long-term debt is down year over year. | `long_term_debt[Q] < long_term_debt[Q-4]` | | |
| g092 | MSFT | Common stock repurchased exceeded $15 billion last fiscal year. | `share_repurchases[FY] > $15B` | | |
| g100 | MSFT | Total assets passed $500 billion in fiscal 2025. | `total_assets[FY2025] > $500B` | | |
| g101 | MSFT | Other income and expense, net, was negative in fiscal 2025. | `other_income[FY2025] < $0` | | |
| g106 | MSFT | Income before income taxes surpassed $120 billion. | `pretax_income[FY] > $120B` | | |
