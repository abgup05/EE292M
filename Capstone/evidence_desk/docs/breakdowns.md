# Segments, geographies and customers from a filing's own tags (milestone 9)

The reported figures this tool has shown since version 3 come from the SEC's company-facts API. That API carries no dimensional facts: no revenue by segment, by product or by geography, and no share of revenue by customer. Those are what a thesis is usually about ("data center revenue is still growing", "a few customers account for a large share of revenue", "sales to China are restricted"), and they are in every filing's own inline XBRL. This reads them.

`make breakdowns ARGS="NVDA --form 10-K"` (or `--form 10-Q`) prints the tables and writes `results/breakdowns-<ticker>-<form>-<UTC>.md` and `.json`; `GET /api/companies/{ticker}/breakdowns?form=10-K` returns the record (`BreakdownReport`, `core/breakdown_models.py`); the page shows it as a fourth action. Code: `sources/ixbrl.py` (the reader), `core/breakdowns.py` (pure), `services/breakdowns.py`, `breakdowns.py`. No model is involved.

## What it reads

A filing's primary document tags each number it prints (`ix:nonFraction`) with a concept, a unit, a scale, a sign and a context; the context gives the period by its dates and, for a breakdown, the dimension members (a segment, a product line, a country, a customer). The reader scans the document's text for those elements. It does not use the project's HTML parser, which cuts the `ix:header` holding the contexts for speed. A number whose format it does not know, a nil fact, or a fact whose context is missing is counted as unread with the reason. It is never guessed.

## What it builds

Five breakdowns, when the filing has them: revenue by business segment, by product or service, by geography; share of revenue by major customer; share of accounts receivable by major customer.

- **One axis, nothing else.** A breakdown takes the facts whose context has that breakdown's axis and no other dimension, so product revenue within one segment is not mistaken for product revenue.
- **The revenue concept differs by company**, and each breakdown records the one it used.
- **Every value is placed by its context's dates**, never by the filing's fiscal-year fields. An annual report gives full fiscal years; a quarterly report gives the quarter alone, or year-to-date values when only those are tagged, and says so. The two are never mixed. A quarter is 12 to 17 weeks, so a retailer's 12- and 16-week quarters count.
- **The change** is from the same kind of period ending about a year earlier, computed by the backend and written out as a formula. A customer's share gets no change: "Customer One" is a position in the filing's list, not shown to be the same customer each year.
- **The members are added up and compared with the filing's own tagged total**, period by period, within the rounding the tags declare. Real filings tag more than a flat list, and each shape found is handled and named in a note: a member that is the sum of others (NVIDIA's Data Center is Compute plus Networking) is counted once; two splits of one total on the same axis (Microsoft's and Amazon's) are recognised; segments whose revenue includes sales to each other are reconciled with the eliminations the filing tags (Coca-Cola, JPMorgan). Anything else is reported as not adding up, with the numbers.
- **The page computes nothing.** The record carries each column's heading, each cell as displayed, each change as displayed and the unit of the table.

## The answer key

The tests on NVIDIA's recorded annual report do not trust the reader's own output. They find the same quantity in the filing's text, as the project's other parser extracts it, and compare:

| Tagged fact | What the filing's text says | Checked |
| --- | --- | --- |
| Data Center revenue, fiscal 2026 and 2025 | the table row "Data Center $193,737 $115,186 …" | the two tagged values equal the row's first two amounts, in millions |
| its change | "Data Center revenue for fiscal year 2026 was up 68% from a year ago." | the computed change rounds to 68 |
| Compute & Networking segment revenue and its change | the segment table's row, which ends in the percentage | values and rounded change equal the row's |
| Customers' share of revenue | "For fiscal year 2026, sales to one direct customer represented 22% of total revenue and sales to another direct customer represented 14% of total revenue" | the two tagged shares are 0.22 and 0.14 |

The printed amount and the tagged amount are the same characters in the same document, so this does not prove the company's number. It proves that the reader attaches each number to the right member, the right period and the right scale, and that the arithmetic on top is right. Ignoring `scale` on purpose failed 25 of the feature's 67 tests.

## Eight companies, 17 November 2026 (live EDGAR)

Every row of every run is in [`evidence/breakdowns-eight-companies.md`](evidence/breakdowns-eight-companies.md). Annual reports:

| Company | Segments | Products | Geography | Customers' share of revenue |
| --- | --- | --- | --- | --- |
| NVIDIA | 2, adds up | 7, adds up | 4, adds up | 2 tagged |
| Apple | 5, adds up | 6, adds up | 3, adds up | none tagged |
| Microsoft | 3, adds up | 12, adds up (two splits of the total) | 2, adds up | none tagged |
| Coca-Cola | 5, adds up (reconciled with eliminations) | 2, adds up | 2, adds up | 1 tagged |
| JPMorgan Chase | 3, adds up (reconciled) | none tagged | 5, adds up | none tagged |
| Tesla | 2, adds up | 9, adds up (nested subtotals) | 3, adds up | none tagged |
| Costco | 3, adds up | 6, adds up | none tagged | none tagged |
| Amazon | 3, adds up | 9, adds up (two splits) | 5, adds up | none tagged |

The eight quarterly reports were run too: every breakdown found adds up to its tagged total. Between 593 and 7,961 numeric facts were read per filing; in eleven of the sixteen filings two facts were left out, each a nil fact with no value.

What the first one shows, as tagged in NVIDIA's annual report for the year ended 25 January 2026: Data Center revenue of $193,737 million, up 68.2%; revenue under the geography member the tool labels "China Including Hong Kong" of $19,677 million, down 21.4%, while the member "US" rose 93.1%; one direct customer at 22% of revenue and another at 14%, where the two shares tagged for the year before were 12% and 11% (the tags do not say they are the same two customers). Each of the example thesis's first three claims has a number here that the company-facts figures could not give.

## Limits

- **Labels are made from tag names**, not taken from the company's own presentation: "Wearables Homeand Accessories" for Apple's `WearablesHomeandAccessoriesMember`, "TW" and "US" for country members. The record and the page say so. The company's labels are in a separate file of the filing that is not read.
- **"Adds up" is the result of a search, not of one sum.** The members are added as they stand; where that fails, the code looks for an arrangement that real filings use (a member that is the sum of others counted once, two splits of the total, eliminations that reconcile segments) among up to sixteen members, within the rounding the tags declare, and says in a note which one it found. A coincidence could satisfy it. So "every breakdown adds up" on sixteen filings is weaker than sixteen plain sums, and each note is worth reading.
- **A company's segments are whatever it reports.** Apple's five "business segments" are regions (Americas, Europe, Greater China, Japan, Rest of Asia Pacific): the title comes from the axis the filing uses, not from what the members look like.
- **A customer row is a position, not a customer.** "Customer One" sits in one row across the years, as the filing tags it; nothing says it is the same customer each year, which is why those rows carry no change.
- **It is a view of its own.** The breakdowns are read from the company's latest filing of the form when the view is asked for. They are not tied to a run, so a saved run made on an earlier filing would sit beside a later filing's figures.
- **No person has compared a table here with the printed one.** The answer key covers one company's annual report. For the other seven, "adds up to the tagged total" is the only check, and it would not notice a member attached to the wrong label.
- **Only the latest filing of the form is read.** Earlier periods are what that filing itself restates.
- **Not offered to the engine.** These figures are shown beside a thesis run; findings cannot cite them yet, so they cannot support or challenge a claim. Offering them would change the engine's prompt and so every recorded answer.
- **What a company does not tag is not there**: Costco tags no geography, most of these companies tag no customer shares. The record says what was looked for and not found.
- **A filing is untrusted text, and the first version of the reader did not treat it so.** Its search for each context ran to the end of the document whenever a tag was never closed: eight times as many unclosed tags took 63 times as long. No real filing does that, and one that did would have tied up a request. The scan is linear now; unclosed elements are counted and reported (`tests/test_ixbrl.py::test_unclosed_context_tags_do_not_make_the_scan_quadratic`).
- The method's constants (how many members and periods are shown, the length of a quarter in days) sit at the top of `core/breakdowns.py`.
