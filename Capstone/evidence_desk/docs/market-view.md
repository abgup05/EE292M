# The market view

What a price says about a company, beside what its filings say: the valuation at a dated price, the
revenue growth that price needs under stated assumptions, and the stock's move after an 8-K. It is
not wired into a run yet: `GET /api/companies/{ticker}/market`, `make market-view T=NVDA` and the
adapter `market_analytics` (below) are its three doors.

Every result is arithmetic on dated inputs, each printed with its source. Nothing here is a
forecast or advice.

## Where the price comes from

The plan asked for a price source that works from a container with no account or key and whose
terms allow the use. `make market-probe` asked each candidate once (18 November 2026, 20:51 UTC,
5 candidates; the report is `results/market-probe-<UTC>.md`):

| Candidate | What came back | Used |
| --- | --- | --- |
| SEC XBRL frames, SEC company list by SIC code | the expected JSON and Atom | yes (the outside view) |
| Stooq daily CSV, `aapl.us` | 796 bytes of HTML: "This site requires JavaScript to verify..." | no: it no longer answers a script |
| FRED graph CSV, `SP500` | 2,608 lines of CSV | only as an index, only when asked (see Terms) |
| Nasdaq's historical-quotes API | on an earlier run that day, HTTP 200 with an empty table | no, and no longer asked: see Terms |

So **no site gave a script daily single-stock prices under terms I could accept.** The previous
builder stopped there and required the user to type a price. But SEC itself holds a price:

**Quarter-end prices from Form 13F** (`core/thirteenf.py`, `sources/thirteenf.py`). An
institutional manager's 13F-HR lists each position's market value and share count on the last day
of a calendar quarter. Value ÷ shares is the price the manager valued the position at, which for a
listed share is that day's close. The filing has a filing date, so the price can be placed in time
exactly: a view as of a date reads the newest 13F **filed** on or before it.

- Three managers are read, in this order: Swiss National Bank, California Public Employees
  Retirement System, New York State Common Retirement Fund. `make market-probe ARGS=--thirteenf`
  (18 November 2026): their newest tables hold 2,300, 1,042 and 2,975 share positions and were filed
  43, 47 and 48 days after the quarter's end. The first holds no banks; the others do.
- The newest quarter any of them has filed for wins; among managers of that quarter, the first that
  holds the company gives the price, and each other one that holds the same CUSIP **confirms it
  within 0.5%** or the result says by how much it differs. An unconfirmed price says so.
- **The issuer is matched by name.** SEC publishes no table from a filer to its CUSIP, and a 13F
  names an issuer in the manager's own abbreviations ("COSTCO WHSL CORP NEW"). Both names are
  reduced to the words that identify them (`issuer_key`) and must be equal. Positions of two CUSIPs
  under one name are two share classes: no price is taken, and the reason lists them. The result
  always prints the issuer name and CUSIP it matched, so a wrong match is visible.
- **The unit is read from the table.** The form has asked for dollars since 3 January 2023 and
  thousands before. One of the three managers still reported thousands in February 2025 (met live:
  NVIDIA at "$0.13" beside two filings at $134.29), so the unit is decided by the table's median
  value ÷ shares: under one dollar means thousands.

What it is not: a daily price. It is one close a quarter, public from this source only when the 13F
is filed, so the newest price is between about six weeks and four and a half months old. The view
prints the price's date and its filing date on every result that uses it.

The second provider is **the user's own price** (`price` with `price_date`), labelled "not checked
against any source". Both sit behind `PriceProvider` (`sources/prices.py`).

Checked against what I know from outside the data: as of 1 March 2025 the view gives NVIDIA $134.29
for 31 December 2024, and as of 30 June 2022 JPMorgan $136.32 for 31 March 2022 (a table in
thousands). Both are those days' closes as I remember them; I could not look them up from here.

### Terms

- **SEC EDGAR** (frames, company lists, 13F filings): public records. SEC asks automated clients to
  identify themselves and to stay under 10 requests a second; every request goes through the app's
  own EDGAR client (7 a second at most), and the frames and 13F sources add 0.25 s between their
  own requests. I did not re-read SEC's access policy in this session.
- **FRED `SP500`**: the series is S&P Dow Jones Indices' data, and S&P's notice on FRED forbids
  reproducing it without permission. It is read live only when a request asks for it
  (`"index": "fred_sp500"`, `INDEX=fred`), kept for the day in the disposable cache, never committed,
  and a reaction shows the two index closes it used. **Whether that is permitted is the user's
  call**; the default is no index, and an index can be supplied as a file instead.
- **Nasdaq's API, Yahoo Finance**: as I recall their terms forbid automated collection. Nasdaq was
  asked once by the previous builder's probe and is no longer in it; Yahoo was never asked. I did not
  re-read either's terms in this session.
- Non-SEC hosts are sent a generic User-Agent naming the tool and no person, and only the ticker.

## Valuation (`core/valuation.py`)

| Result | Formula | Inputs |
| --- | --- | --- |
| Market value | price × shares outstanding | the cover page's share count of the newest filing filed by the price's date |
| Enterprise value | market value + total debt − cash and current marketable securities | both balances **of the newest balance sheet** filed by the price's date |
| EV ÷ revenue, market value ÷ net income, market value ÷ free cash flow, free cash flow yield | as named | the trailing four quarters (the newest fiscal year when four quarters cannot be summed) |

Rules a reader should know:

- **Facts are those filed by the price's date**, not by the view's: what the price could know.
- **A balance is never carried forward.** The inherited code took a measure's newest reported date,
  which for Tesla's non-current debt and JPMorgan's cash is 31 December 2018. Now a balance must be
  dated the newest balance sheet (the newest date total assets is tagged for).
- **Debt**: long-term debt + its current portion + commercial paper; when the company does not tag
  the non-current part there, the first tagged total of `DEBT_TOTALS`, named in the result with
  what it means (Tesla: `DebtInstrumentCarryingAmount`).
- **Cash**: cash and equivalents + current marketable securities. NVIDIA stopped tagging
  `MarketableSecuritiesCurrent` after October 2025 and tags `DebtSecuritiesCurrent` ($34.14B on
  26 July 2026); that is added and said. Non-current securities are not subtracted (Apple holds
  $80.21B of them on 26 September 2026), so the enterprise value here is higher than one that
  counts them. (Both figures: `make market-probe ARGS="--concepts 'NVDA:Securities'"` and
  `'AAPL:^Marketable'`, 18 November 2026. The app's own `cash_and_securities` measure, which the
  claim tests read, still counts NVIDIA's securities as zero: `core/facts.py` is not mine to change
  in this work.)
- Leases, preferred stock and minority interests are left out. Several share classes are priced at
  the one price given, and the result says so. A share count that moved by more than 25% between two
  cover pages is flagged: a split between the count's date and the price's would put the market
  value off by that factor.
- A bank tags neither debt nor cash this way: no enterprise value, with that reason.

## What the price implies (`core/reverse_dcf.py`)

The constant revenue growth g, held for ten years, at which this model's value equals the
enterprise value:

    cash flow(t) = revenue(t) × margin × (1 − tax) − (revenue(t) − revenue(t−1)) ÷ sales-to-capital
    value = Σ cash flow(t) ÷ (1 + r)^t  +  cash flow(11) ÷ (r − terminal growth) ÷ (1 + r)^10

Defaults, each printed on the result and each settable on the request: margin = the trailing
operating margin; tax 21%; sales-to-capital = trailing revenue ÷ (equity + debt − cash and
securities), or 1.5 when that is not positive; r = 9%; terminal growth 3%. A grid varies r by ±1
and ±2 points and the margin by ±5 points. When the return on new capital (margin × (1 − tax) ×
sales-to-capital) is under r, growth lowers the value, and the result says so.

The number alone means little, so it is set beside four things:

1. the company's own growth (newest fiscal year, and compound over three);
2. the revenue the growth reaches in year ten, beside the largest revenue any filer reported in the
   newest frame year;
3. the ten-year growth of filers that started at its size (revenue between half and twice its own,
   in any start year the frames hold a ten-year end for): how many grew at least that fast, the
   median and the 90th percentile, and how many could not be followed (survivors only; the spans
   overlap, so they are not independent);
4. the same model with the margin at the industry's median and at its 90th percentile (the other
   filers of its SIC code with revenue of at least $100M; needs five).

**Checked**: `tests/test_market_examples.py` rebuilds the example's value two ways that do not call
the solver (year by year, and the closed form of the geometric series) and gets the enterprise
value back to 0.1% (the tolerance is the printed rounding of one input).

## Reaction to an 8-K (`core/reaction.py`)

From the last close before the filing day to the Nth close after it (default 3) and to the latest
close on or before the as-of date: the stock's return, the index's over the same dates, the
difference, and that difference in units of the stock's normal move (the standard deviation of its
daily excess return over the 250 trading days ending at the close before the filing, × √days;
needs 60). Closes after the as-of date are cut before anything is computed.

- **It needs daily closes, and none can be fetched**: they come in the request body, or from a CSV
  the user puts in the repository (`PRICES=`), with the index from a file or, when asked, FRED.
- EDGAR's index gives a filing's day, not its hour. An 8-K accepted after the close moves the next
  day's price, so its filing day is a day of the window on which nothing was known.
- Excess return is not adjusted for beta; days are assumed independent.

## On the eight probe companies

`make market-check`, 18 November 2026 20:56 UTC (`docs/evidence/market-check-eight-companies.md`;
NVDA, AAPL, MSFT, KO, JPM, TSLA, COST, AMZN):

- a 13F price for 8 of 8, each confirmed by at least one other manager (7 from Swiss National Bank,
  JPMorgan from CalPERS);
- an enterprise value for 7 of 8 (not JPMorgan: a bank);
- an implied growth for 6 of 8. JPMorgan has no operating income. For Tesla no growth between −50%
  and +100% a year is worth the price at its 4.2% trailing margin, and the result says that;
- of the 6, the ten-year spans of filers that started at the company's size that grew at least as
  fast as the price implies: 0 of 40 (NVIDIA), 0 of 16 (Apple), 0 of 31 (Microsoft), 0 of 44
  (Costco), 0 of 11 (Amazon), 9 of 463 (Coca-Cola).

## The example

`docs/examples/market/` (`make market-examples`, offline, from `make fixtures-market`):
`market-view.json` and `.txt`, `analytics.json`, `reactions.json`. The price and every fact are
SEC's as recorded. **The daily closes of `reactions.json` are made up** (a seeded random walk with
one drop put in by hand): it shows the shape and the arithmetic of a reaction and says nothing
about NVIDIA's stock.

## Not checked

- The 13F price against an exchange's own close, beyond the two closes above from memory.
- The name match beyond the eight probe companies. Companies with two listed classes (Alphabet) get
  no price by design; a company whose EDGAR name and 13F name differ by more than the abbreviations
  in `core/thirteenf.py` gets none either, and says so.
- A company none of the three managers holds.
- The reaction on real closes: there are none in the repository.
- The reverse DCF's defaults are conventions, not estimates. The grid shows how far the answer
  moves with two of them.
