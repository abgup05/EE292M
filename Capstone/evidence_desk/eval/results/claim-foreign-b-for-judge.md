# Set B: the compiled claims, for an independent judge

A program reads each claim an analyst writes about one company and, when it can, turns it into a
test that can be computed from the company's reported figures. Below are the claims of set B that it
turned into a test (6 of 120; the other 114 it declined). For each one, decide whether the test
means what the sentence says: **right** if computing the test would answer exactly the question the
sentence asks, **wrong** if it would answer a different question (a different measure, period,
comparison or threshold, or only part of the sentence). Whether the claim is true is not the
question.

## How to read a test

A test is written `left operator right`. It holds when the comparison is true.

**Operators.** `>` more than; `>=` at least; `<` less than; `<=` at most.

**Measures**, each for one company as a whole: `revenue` (net sales), `gross_profit`,
`operating_income`, `net_income`, `rnd` (research and development expense),
`operating_expenses` (gross profit less operating income), `operating_cash_flow`, `capex`
(capital expenditure), `free_cash_flow` (operating cash flow less capex), `gross_margin`,
`operating_margin` and `net_margin` (each as a percent of revenue), `rnd_ratio` (R&D as a percent of
revenue), `fcf_margin` (free cash flow as a percent of revenue), `eps_diluted` (diluted earnings per
share), `cash` (cash and cash equivalents), `inventory`, `receivables` (accounts receivable).

**Functions of a measure.**

- `measure[P]`: its value for period P.
- `yoy(measure)[P]`: its growth over the same period a year earlier, in percent.
- `qoq(measure)[P]`: its growth over the previous quarter, in percent.
- `streak(measure)[P]`: how many periods in a row up to P it rose.
- `cagr(measure, Ny)[P]`: its compound annual growth over the N years to P, in percent.
- `share(segment "X")[filing]` or `share(geography "X")[filing]`: the share of total revenue of
  the one segment or geographic area named X, as the company's newest filing tags it, in percent.
- `max(share(customer))[filing]`: the largest single customer's share of revenue, in percent.

**Periods** (the company's own fiscal calendar).

- `Q`: the latest quarter. `Q-1` is the quarter before it; `Q-4` the same quarter a year earlier.
- `FY`: the latest fiscal year. `FY-3` is three fiscal years before it.
- `FY2025`: the fiscal year the company calls 2025. `Q2 FY2027`: the second quarter of fiscal 2027.
- `TTM`: the four latest quarters together (the trailing twelve months).
- `filing`: the newest 10-K or 10-Q filing (used only for shares of revenue).

**Constants.** `40%` is a percent; `$100B` is 100 billion US dollars; a plain number is a count.

Example: "Gross margin is expanding" becomes `gross_margin[Q] > gross_margin[Q-4]`: the latest
quarter's gross margin is higher than the same quarter's a year earlier.

## The compiled claims

| id | company | claim | test | verdict (right or wrong) | note |
|---|---|---|---|---|---|
| g004 | NVIDIA | Gross profit came in above $100 billion in fiscal 2026. | `gross_profit[FY2026] > $100B` | | |
| g025 | NVIDIA | FCF margin above 40% on a trailing twelve month basis. | `fcf_margin[TTM] > 40%` | | |
| g046 | Apple | Japan and Rest of Asia Pacific together are less than 15% of net sales. | `share(segment "Japan And Rest Of Asia Pacific Together")[filing] < 15%` | | |
| g066 | Apple | Greater China is under 20% of net sales. | `share(geography "Greater China")[filing] < 20%` | | |
| g081 | Microsoft | Revenue was above $270 billion in fiscal 2025. | `revenue[FY2025] > $270B` | | |
| g087 | Microsoft | Net margin was above 35% in fiscal 2025. | `net_margin[FY2025] > 35%` | | |
