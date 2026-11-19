# The outside view

How often has what a claim says been true of other companies, and where does this one stand among
its peers? From SEC's XBRL frames: one value per filer for one concept and calendar period. It is
not wired into a run yet: `GET /api/companies/{ticker}/outside`, `make outside-view T=NVDA
CLAIM="..."` and the adapter `outside_analytics` are its three doors.

## Base rate (`core/base_rates.py`)

The claim is compiled to a typed test by the app's own compiler (`core/claimtest.py`), then read on
fiscal years as the annual frames place them. For each year t of the last 15 admitted:

- **the class** is decided in the earliest year the test reads (the base year of a growth), so the
  outcome cannot choose its own class. Two classes:
  - *size*: every filer whose revenue then was at least a floor: half the company's newest
    revenue, rounded down to 1, 2 or 5 times a power of ten (`min_revenue` overrides it);
  - *industry*: the filers SEC lists today under the company's SIC code, with revenue of at least
    $100M then;
- **a level of revenue is the exception**: a test of a *level* of revenue ("revenue was above $300
  billion") reads no earlier year, and its outcome is the measure the class is chosen on: decided in
  the year read, every filer of a class whose floor is above the threshold held by construction (the
  seventh referee's finding 6, shown by
  `tests/test_outside_view.py::test_a_revenue_level_is_not_counted_in_a_class_chosen_on_that_years_revenue`,
  2 of 2 before). Since version 14.3 the class of such a test is decided a year earlier, and the
  result's assumptions say so. A level of another measure (a margin) still takes the class of the
  year read;
- **the company itself is left out** of every count; the years the test held for it are listed apart;
- a filer in the class whose test cannot be computed in year t is counted as *not computable*, never
  as a failure;
- **persistence**: of the company-years in which the test held and year t + 1 can be read, those in
  which it held again;
- the **nearest cases** are named: the other filers' company-years that held, nearest to the
  company's own value, with what happened the next year.

A rate is always printed as a count over its denominator with the years and the class. The example
(`docs/examples/market/outside-view.txt`, `make market-examples`, frames as recorded on 18 November
2026): "revenue grew more than 50% year over year" held in **4 of 366** company-years (2011 to 2025)
among other filers with revenue of at least $100B, all four oil companies in 2021 and 2022, and in
**0 of those 4** did it hold again the next year; among other SIC 3674 filers of at least $100M, 81
of 1,045, of which 13 of the 69 readable a year later held again.

What is read and what is refused:

- Only annual frames. A term over the latest quarter or four quarters is read on the fiscal year,
  and the result says so. A sequential test, a streak of quarters, a test held in each of several
  periods, a share of revenue and a part of the company are refused with the reason.
- Measures built from one or two frame concepts: revenue and its growth, gross profit, operating
  income, net income, R&D, operating cash flow, capital expenditure, free cash flow, operating
  expenses, the gross, operating, net and free-cash-flow margins, R&D and capital expenditure as
  shares of revenue, cash conversion. Of the catalogue's 57 measures that is 15 (`coverage()`,
  printed at the end of every `make outside-view`); a claim naming another is refused, naming it.

## Peer standing (`core/peers.py`)

For twelve measures: the company's rank (1 is highest) and percentile (the share of the other
members with a lower value) among the industry class in the newest frame year that holds it and the
year before, with n, the class median and the two members on each side by name. Fewer than three
members with a value: no ranking. The adapter passes on only the standings of the measures the
claim's test names (for a revenue claim: revenue growth and revenue), else three defaults.

## How a frame is read (`core/frames.py`)

- **Periods by their dates.** A row is placed by its own start and end; an annual row not 350 to
  380 days long is dropped and counted. XBRL's `fy` and `fp` are not in a frame and nothing reads
  them. Two years are "a year apart" when their period ends are, within 10 days.
- **One idea, several tags.** Revenue is `RevenueFromContractWithCustomerExcludingAssessedTax`,
  `Revenues`, `SalesRevenueNet` and two more. Per filer and year the first tag with a row is taken,
  in the order the app's own metrics use (`core/facts.GROUPS`); how many filers had several and how
  many of those differ by more than 1% is counted on the result. Two tags of one filer and year
  that differ by a factor near a thousand (one number at two scales) leave the filer without a
  value that year: 5 filer-years of revenue in the example.
- **No filing date.** A frame holds the latest value SEC has. So, as of a date, only periods that
  ended at least a year before it are read (without a date: 120 days before today), and every
  result says that a value restated later is the restated value. This is the one place the app's
  as-of rule is approximate, and it errs towards reading less.
- Requests go through the app's EDGAR client with its User-Agent, 0.25 s apart on top of its limit
  (four a second at most), and every body is kept under `data/cache/frames` (disposable). The
  example read 94 frames.

## Limits a reader must hold on to

- **Survivorship.** A filer that was bought, went under or stopped filing has no later value. It
  stays in the class count and drops out of the computable count; the rate is of filers that can
  still be read.
- **The SIC code is today's and coarse.** On the eight probe companies (`make market-check`, 18
  November 2026, `docs/evidence/market-check-eight-companies.md`) the $100M floor keeps shells out
  and the neighbours are recognisable for 6 of 8: NVIDIA (Broadcom, Intel, Micron), Microsoft
  (Oracle, Salesforce), Coca-Cola (PepsiCo, Keurig Dr Pepper), JPMorgan (Bank of America,
  Citigroup, Wells Fargo), Tesla (Ford, GM, PACCAR), Costco (Walmart, Target, BJ's). They are weak
  for 2: Apple's code, 3571, has 5 filers with a value (Dell, Super Micro, Omnicell), and Amazon's,
  5961, is mail-order retail (Coupang, CDW, ThredUp), with no cloud company in it.
- **Not in a USD frame, so not a peer**: a filer that reports in another currency (TSMC reports
  in New Taiwan dollars), and a company that does not file with SEC at all.
- A parent and a subsidiary that both file are two filers.
- Company-years of one filer are not independent, and neither are the years of one cycle (the four
  oil companies above are one event). The count is a description, not a probability.
- Frames place a fiscal year in the calendar year it mostly covers: "2025" for NVIDIA is its fiscal
  year ended 25 January 2026.

## Not checked

- A frame's values against the filings they came from, beyond the tests' hand-counted panel
  (`tests/outside_fakes.py`) and the example's own totals.
- The industry class of any company beyond the eight.
- Whether SEC's company list by SIC code is complete; it is read as given (506 filers for 3674).
