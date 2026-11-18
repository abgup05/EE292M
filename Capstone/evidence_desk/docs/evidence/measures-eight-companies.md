# Claim-test measures on eight companies (18 November 2026, live EDGAR)

`make measures-probe` (by default `NVDA AAPL MSFT KO JPM TSLA COST AMZN`) reads each company's
XBRL company facts and newest 10-K from EDGAR. For every measure of the catalogue
(`app.core.measures`) it computes the newest fiscal year as a claim test does: the left side of
`measure[FY] > 0` through `app.core.claim_eval.evaluate`, so a value here is a value a claim test
gets and a miss carries the reason a claim test gives. The command computes nothing of its own.
Run once, on commit `a05dec3` plus the probe itself; the full output, with every reason, was
`results/measures-20261118T115625Z.md` (disposable, not committed). Denominator: the eight
companies, all eight read. Fiscal years read: NVDA FY2026, AAPL FY2026, MSFT FY2026, KO FY2025, JPM FY2025, TSLA FY2025, COST FY2026, AMZN FY2025.

## Measures the catalogue added (not on the metrics panel)

| Measure | Kind | Of the eight with a value | Without one |
| --- | --- | --- | --- |
| `sga_ratio` | ratio | 6 of 8 | JPM, AMZN |
| `sales_marketing_ratio` | ratio | 2 of 8 | NVDA, KO, JPM, TSLA, COST, AMZN |
| `opex_ratio` | ratio | 7 of 8 | JPM |
| `capex_ratio` | ratio | 7 of 8 | JPM |
| `sbc_ratio` | ratio | 8 of 8 | none |
| `effective_tax_rate` | ratio | 8 of 8 | none |
| `cash_and_securities` | instant | 7 of 8 | JPM |
| `net_cash` | instant | 6 of 8 | JPM, TSLA |
| `net_debt` | instant | 6 of 8 | JPM, TSLA |
| `long_term_debt` | instant | 6 of 8 | JPM, TSLA |
| `commercial_paper` | instant | 2 of 8 | NVDA, MSFT, JPM, TSLA, COST, AMZN |
| `total_debt` | instant | 6 of 8 | JPM, TSLA |
| `marketable_securities` | instant | 5 of 8 | NVDA, KO, JPM |
| `shareholder_returns` | flow | 6 of 8 | TSLA, AMZN |
| `share_repurchases` | flow | 6 of 8 | TSLA, AMZN |
| `dividends_paid` | flow | 6 of 8 | TSLA, AMZN |
| `diluted_shares` | shares | 8 of 8 | none |
| `total_operating_expenses` | flow | 7 of 8 | JPM |
| `sga` | flow | 6 of 8 | JPM, AMZN |
| `sales_marketing` | flow | 2 of 8 | NVDA, KO, JPM, TSLA, COST, AMZN |
| `general_admin` | flow | 3 of 8 | NVDA, KO, JPM, TSLA, COST |
| `sbc` | flow | 8 of 8 | none |
| `pretax_income` | flow | 8 of 8 | none |
| `income_tax` | flow | 8 of 8 | none |
| `interest_expense` | flow | 6 of 8 | AAPL, JPM |
| `interest_income` | flow | 5 of 8 | AAPL, MSFT, COST |
| `other_income` | flow | 6 of 8 | JPM, COST |
| `d_and_a` | flow | 6 of 8 | MSFT, TSLA |
| `deferred_revenue` | instant | 6 of 8 | KO, JPM |
| `deferred_revenue_current` | instant | 6 of 8 | KO, JPM |
| `deferred_revenue_noncurrent` | instant | 4 of 8 | AAPL, KO, JPM, COST |
| `current_debt` | instant | 7 of 8 | JPM |
| `total_assets` | instant | 8 of 8 | none |
| `total_liabilities` | instant | 6 of 8 | KO, AMZN |
| `equity` | instant | 8 of 8 | none |
| `goodwill` | instant | 7 of 8 | AAPL |
| `ppe` | instant | 6 of 8 | JPM, TSLA |
| `accounts_payable` | instant | 6 of 8 | KO, JPM |
| `cost_of_revenue` | flow | 7 of 8 | JPM |

**Measures most of the eight lack**, documented rather than hidden: `sales_marketing_ratio` (2 of 8), `commercial_paper` (2 of 8), `sales_marketing` (2 of 8), `general_admin` (3 of 8), `deferred_revenue_noncurrent` (4 of 8).
Each is a line only some companies report on its own: sales and marketing and G&A are tagged
apart by a company that reports them apart (most report SG&A as one line, or, like NVIDIA, a
single "sales, general and administrative"); commercial paper only by an issuer of it (it counts
zero inside total debt, and says so); non-current deferred revenue only where some is due after
a year. A claim about one of them on a company that does not tag it cannot be computed, and the
test says which concept was missing.

Other misses, as the probe reports them (each reason names the concepts it looked for and
found no value for). Why a company does not tag a concept was **not** checked against its
filings; the likely causes in brackets are unverified.

- JPM (a bank) has no value for cost of revenue, operating income, operating expenses, SG&A,
  capex, inventory, debt, PP&E or payables under these concepts, so most measures built on
  them miss for it, as the panel's do.
- TSLA: no value for long-term debt, so `long_term_debt`, `total_debt`, `net_cash` and
  `net_debt` miss (perhaps it tags debt together with finance leases, which the catalogue
  leaves out on purpose).
- TSLA and AMZN: no value for share repurchases or dividends paid in the newest fiscal year,
  so `share_repurchases`, `dividends_paid` and `shareholder_returns` miss (perhaps there were
  none; a company with no fact is not counted as zero, except for the optional parts of a sum).
- KO and AMZN: no value for total liabilities (`Liabilities`); the catalogue does not derive
  it from total liabilities and equity less equity.
- MSFT and TSLA: no value for depreciation and amortisation under the three concepts read
  (perhaps they tag it together with other items).
- AAPL: no goodwill balance and no interest expense for its newest fiscal year.

## The panel's measures, for comparison

These are unchanged by the catalogue: `make figures` on the same eight before and after it
printed identical output (`results/figures-20261118T113453Z.md` and
`results/figures-20261118T115322Z.md`, the same apart from the title line).

| Measure | Kind | Of the eight with a value | Without one |
| --- | --- | --- | --- |
| `fcf_margin` | ratio | 7 of 8 | JPM |
| `rnd_ratio` | ratio | 4 of 8 | KO, JPM, COST, AMZN |
| `gross_margin` | ratio | 7 of 8 | JPM |
| `operating_margin` | ratio | 7 of 8 | JPM |
| `net_margin` | ratio | 8 of 8 | none |
| `free_cash_flow` | flow | 7 of 8 | JPM |
| `operating_cash_flow` | flow | 8 of 8 | none |
| `capex` | flow | 7 of 8 | JPM |
| `cash` | instant | 7 of 8 | JPM |
| `inventory` | instant | 7 of 8 | JPM |
| `receivables` | instant | 6 of 8 | JPM, COST |
| `eps_diluted` | per_share | 8 of 8 | none |
| `gross_profit` | flow | 7 of 8 | JPM |
| `operating_income` | flow | 7 of 8 | JPM |
| `operating_expenses` | flow | 7 of 8 | JPM |
| `net_income` | flow | 8 of 8 | none |
| `rnd` | flow | 4 of 8 | KO, JPM, COST, AMZN |
| `revenue` | flow | 8 of 8 | none |

## The parts each newest 10-K tags

A part's revenue, its change on a year earlier ("Both years": the filing tags the year before
too, so the change is the filing's own), and a segment's operating income are read only from
the newest filing's tagged breakdowns and have no history. Segment operating income comes from
a breakdown built only for claim tests (`app.core.breakdowns.CLAIM_SPECS`).

| Ticker | 10-K period end | Segment revenue | Both years | Segment operating income | Product revenue | Both years | Geography revenue |
| --- | --- | --- | --- | --- | --- | --- | --- |
| NVDA | 2026-01-25 | yes | yes | yes | yes | yes | yes |
| AAPL | 2026-09-26 | yes | yes | yes | yes | yes | yes |
| MSFT | 2026-06-30 | yes | yes | yes | yes | yes | yes |
| KO | 2025-12-31 | yes | yes | yes | yes | yes | yes |
| JPM | 2025-12-31 | yes | yes | no | no | no | yes |
| TSLA | 2025-12-31 | yes | yes | no | yes | yes | yes |
| COST | 2026-08-30 | yes | yes | yes | yes | yes | no |
| AMZN | 2025-12-31 | yes | yes | yes | yes | yes | yes |
