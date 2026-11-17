# What changed between two filings (milestone 6)

`make changes ARGS="NVDA --form 10-K"` (or `--form 10-Q`) compares a company's latest report of the form with the
one before it and writes `results/changes-<ticker>-<form>-<UTC>.md` and `.json` (the `FilingChanges` record of
`core/change_models.py`). Code: `core/filing_diff.py` (pure), `services/filing_changes.py`, `changes.py`.

**What it does.** It compares the parser's text, Item by Item, line by line. Every line of the text under an Item
lands in exactly one count (sub-heading lines and "Part" lines are not lines of that text; sub-headings are compared
apart). Each listed paragraph is an exact span of the stored text, with its locator and a link that
says what it opens. A paragraph whose figures alone moved is listed with those figures marked. Sub-headings found
in only one filing are named. **Not:** it does not know why anything changed, and it does not read tables: a table
row whose figures moved is counted and not shown. It inherits the parser's lines: a paragraph split in two reads as
one reworded and one added; one cut by a page break in only one filing leaves a piece reworded or removed.

The counts were corrected after the second referee's reading ([`reviews/referee-2-version-6.md`](reviews/referee-2-version-6.md),
finding 1). Until then "unchanged" and "numbers only" counted every line, table rows included, beside three columns
that counted paragraphs only, under one heading that said "paragraphs". NVIDIA's "606 unchanged, 417 numbers only"
were 251 and 60 paragraphs; the rest were short lines and table rows.

## Method

1. Lines are grouped by Item (the heading before " › "), matched by Part and Item number, case, punctuation and
   title ignored. Cover page, unnumbered text and full document are their own groups.
2. *Unchanged*: identical after whitespace, case and typographic quotes are normalised, wherever it sits in the
   Item (a moved paragraph is unchanged). *Numbers only*: identical once every number, date and amount is masked.
3. A *paragraph* is a line of at least 60 characters that is not a table row (a table row is under half letters,
   or unpunctuated and either ending in a figure or at least 80% capitalised words). Shorter lines and table rows
   are matched in step 2 like any line and have four counts of their own; they are never listed and never paired
   in step 4. A matched pair is a paragraph or not by its line in the later filing.
4. *Reworded*: Jaccard similarity of the paragraphs' token sets (`core.text.tokenize`, digit-only tokens left out)
   of at least **0.5**, most similar pairs first; the rest are added or removed. Changed words come from
   `difflib.SequenceMatcher` over the two paragraphs only, for reworded and for numbers-only pairs alike.
5. So the later filing's lines are the matched ones plus added, the earlier filing's the matched ones plus removed,
   paragraphs and short lines each in their own counts. A test checks this sum on two real filings.
6. *Sub-headings* are not lines: the parser keeps a short bold line without a full stop apart from the text. Those
   under an Item in only one filing are named, compared without case, punctuation and figures. A sub-heading that
   only changes its year is not reported; a paragraph that moves under another sub-heading is still unchanged.

**The threshold.** At 0.6, many "added" Item 1A paragraphs had a twin among the "removed": the same paragraph
grown by a sentence ("Challenges in estimating demand…", J = 0.58) or with new figures counted as changed words
("Data Center revenue for fiscal year 2026 was up 68%…", J = 0.35). So figures no longer count as words (they
have their own class), and every pair each lower threshold would add was read, on both filing pairs, by the
model session that built this: from 0.50 to
0.55, 19 of 20 were the same paragraph rewritten (the doubtful one: a warranty paragraph cut to its lead-in);
from 0.45 to 0.50, 8 of 10, the other two only related (supply commitments against a new "Supply and capacity"
paragraph); from 0.55 to 0.60, 14 of 16, the other two a split paragraph or page-break pieces. The threshold stops at 0.5:
a false pairing hides a new paragraph inside "reworded", while a missed one still shows both texts.

## NVIDIA, measured 17 November 2026 (live EDGAR)

| Paragraphs | Unchanged | Numbers only | Reworded | Added | Removed | Short lines and table rows: unchanged / numbers only / added / removed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 10-K FY2026 against FY2025 | 251 | 60 | 218 | 133 | 132 | 355 / 357 / 150 / 202 |
| of which Item 1A, Risk Factors | 124 | 1 | 51 | 34 | 22 | 15 / 0 / 2 / 1 |
| 10-Q Q2 FY2027 against Q1 | 99 | 14 | 108 | 71 | 66 | 215 / 168 / 239 / 187 |
| of which Part II, Item 1A | 22 | 0 | 11 | 17 | 32 | 0 / 0 / 0 / 6 |

At 0.6 with figures counted, the 10-K gave 191 reworded, 166 added, 166 removed. Examples from its Item 1A:

- **Added:** "We are finalizing an investment and partnership agreement with OpenAI. There is no assurance that we
  will enter into an investment and partnership agreement with OpenAI or that a transaction will be completed."
- **Removed:** "The AI Diffusion IFR would encourage our customers to invest in alternatives that are not affected
  by USG regulations, including foreign competition." (The later report's own added paragraph: "In May 2025, the USG announced that it would rescind the AI Diffusion
  IFR and implement a replacement rule.")
- **Reworded** (0.88): "•Long manufacturing lead times and uncertain supply and ~~component~~ **capacity**
  availability, combined with a failure to estimate customer demand accurately has led and could lead to […]"
- **Numbers only:** "[…] and we generated ~~53%~~ **31%** of our revenue in fiscal year ~~2025~~ **2026** from sales
  outside the United States." In Item 7: "Revenue for fiscal year ~~2025~~ **2026** was ~~$130.5~~ **$215.9**
  billion, up ~~114%~~ **65%** from a year ago."
- **Sub-headings only in the earlier report, under Item 1:** Sustainability and Governance; Climate Change;
  Recruitment; Development and Retention; Compensation, Benefits, and Well-Being; Diversity, Inclusion and
  Belonging at NVIDIA; Flexible Working Environment. **Only in the later one, under Item 15:** Note 2 - Groq; Note 8 -
  Non-marketable Equity Securities; Foreign Currency Derivatives; Facility Lease Guarantees; Note 11 - Debt;
  Commitments. No paragraph count showed either list before sub-headings were compared.

## Eight companies' annual reports, 17 November 2026 (live EDGAR)

`make changes ARGS="<TICKER> --form 10-K"` for each; every row of each output is kept in
[`evidence/changes-eight-companies.md`](evidence/changes-eight-companies.md). The "Total" rows:

| Company | Fiscal years ended | Groups in both | Unchanged | Numbers only | Reworded | Added | Removed | Short lines and table rows: unchanged / numbers only / added / removed |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| NVIDIA | 2025-01-26, 2026-01-25 | 23 of 23 | 251 | 60 | 218 | 133 | 132 | 355 / 357 / 150 / 202 |
| Apple | 2025-09-27, 2026-09-26 | 24 of 24 | 154 | 68 | 111 | 46 | 25 | 256 / 397 / 126 / 78 |
| Microsoft | 2025-06-30, 2026-06-30 | 23 of 23 | 327 | 65 | 151 | 75 | 74 | 528 / 491 / 149 / 97 |
| Coca-Cola | 2024-12-31, 2025-12-31 | 23 of 23 | 495 | 123 | 269 | 88 | 104 | 541 / 566 / 265 / 271 |
| JPMorgan Chase | 2024-12-31, 2025-12-31 | 19 of 19 | 1,471 | 381 | 848 | 457 | 521 | 1,662 / 2,434 / 845 / 847 |
| Tesla | 2024-12-31, 2025-12-31 | 23 of 23 | 218 | 54 | 227 | 127 | 93 | 362 / 394 / 174 / 259 |
| Costco | 2025-08-31, 2026-08-30 | 23 of 23 | 173 | 55 | 132 | 27 | 36 | 267 / 328 / 94 / 71 |
| Amazon | 2024-12-31, 2025-12-31 | 23 of 23 | 278 | 69 | 139 | 48 | 38 | 306 / 369 / 132 / 120 |

A group is the cover page or one Item, so "23 of 23" is 22 Items and the cover page. What this shows is narrow:
the comparison runs on all eight, every group of one report finds its group in the other, and no run made a note
about coverage (the evidence file has each run's notes). It does not show that the classes are right.

**Two things the other seven found.**

- *JPMorgan could not be compared at all.* It files so often that EDGAR's recent index held one annual report, and
  the run ended "has 1 10-K filing(s) in EDGAR's recent index". `filings_of_form` now reads the index's older
  pages, newest first, until it has two filings of the form, at most `MAX_OLDER_INDEX_PAGES` (12) pages; a page
  name is used only if it is exactly that company's `CIK##########-submissions-###.json`. Ten tests, written first.
- *JPMorgan's Item labels mean little.* 7,193 of the 8,098 lines of its later report (89%) sit under "Item 15.
  Exhibits, Financial Statement Schedules": the bank's annual report follows its last Item heading, and the parser
  files the whole of it there. The lines compared are the right ones; the Item named beside them is not where
  a reader would look for them. Item coverage (99.4%) cannot see this: it measures text under *an* Item. (This
  sentence first said "6,460 of 7,253 paragraphs", a sum over columns that did not count the same thing.)

## The threshold on five more companies (read by a model, not by a person)

`make changes ARGS="<TICKER> --form 10-K --review 0.44"` adds a section, "Pairs to read before trusting the
threshold": the pairs the comparison paired with a similarity from 0.50 to under 0.56, and the pairs a threshold
of 0.44 would add, which it reports as one removed and one added paragraph. Neither list is cut. The session that
built this read every pair it printed for Apple, Coca-Cola, Microsoft, Tesla and Amazon on 17 November and asked of
each: is this one paragraph rewritten?

| Annual reports | Paired just above: one paragraph rewritten | Not paired just below: one paragraph rewritten |
| --- | ---: | ---: |
| NVIDIA (from "The threshold" above; its bands were 0.50 to 0.55 and 0.45 to 0.50, on two filing pairs) | 19 of 20 | 8 of 10 |
| Apple | 10 of 11 | 5 of 5 |
| Coca-Cola | 7 of 10 | 4 of 9 |
| Microsoft | 5 of 5 | 8 of 8 (two of them doubtful) |
| Tesla | 11 of 11 (one doubtful) | 10 of 11 |
| Amazon | 7 of 7 | 3 of 4 |
| All six | 59 of 64 | 38 of 47 |

- **Apple.** The one wrong pair above joins two different sentences that end alike ("…materially adversely affect
  the Company's business, results of operations, financial condition and stock price"). One of the ten is a piece
  of a paragraph the later report split. All five pairs below are the same paragraph rewritten and are shown as
  removed and added: a risk-factor heading turned from "Losses or unauthorized access…" into "The Company
  experiences cybersecurity incidents…", the Epic Games paragraph, the net sales lines for Greater China and Japan.
- **Microsoft.** All five pairs above are one paragraph rewritten. So are the eight below, which the comparison
  shows as removed and added: the opening of the risk factors, three risk-factor paragraphs, the lines on server and
  cloud revenue and on sales and marketing expense, an accounting policy, and a sentence on other income.
- **Tesla.** All eleven pairs above are one paragraph rewritten, among them the company's opening description of
  itself, which went from "We design, develop, manufacture, sell and lease high-performance fully electric vehicles"
  to "We are focused on bringing artificial intelligence (“AI”) into the real world". Ten of the eleven below are
  rewordings too.
- **Amazon.** All seven above; three of the four below. The fourth is two pieces of different paragraphs cut by a
  page break.
- **Coca-Cola.** Three of the ten pairs above are template matches: a bullet about one operating segment paired with
  a bullet about another, the paragraph on other income for 2023 paired with the one for 2025, and two unrelated
  footnotes about Latin America. Below, four are the same paragraph and five are not.

What this says: on risk factors, which are prose, the threshold behaves as it did on NVIDIA, and on Apple it is
if anything too strict. In a discussion of results that has one paragraph per year, one bullet per segment and
numbered footnotes, paragraphs built on one template are told apart mostly by their figures, and figures are
exactly what the similarity leaves out. There a pair just above the threshold is wrong about three times in ten,
and lowering the threshold would add more wrong pairs than right ones. Taken over the six companies, 38 of the 47 pairs just below the threshold are one paragraph rewritten, which the
comparison reports as one removed and one added, and 59 of the 64 just above it are rightly paired. That is evidence that 0.5 is too strict outside template-built
sections, and that a lower value would hide more new paragraphs inside "reworded" in Coca-Cola's kind of filing.
It has not been changed: the reading is a model's, a change moves every count in this document, and where to trade
a missed rewording against a hidden addition is a decision for a person who has read the pairs. Two ways to do better were not tried: let the year
a paragraph names keep two template paragraphs apart, and prefer the pair nearest in order within the Item.

This is still a model's reading of 81 pairs for five companies, by the session that built the feature. The command
is there so that a person can do the same in a few minutes.

## Speed

`make changes ARGS="NVDA --form 10-K --time 20"` times the comparison alone (`compare_pair`, no reading or
parsing): 20 runs with the candidate index and 20 over all pairs, interleaved, after one discarded run of each;
both give the same record. One laptop, Docker, median (fastest to slowest): 10-K pair 95.7 ms (95.0 to 103.1)
indexed against 100.5 ms (99.5 to 120.4) all pairs; 10-Q pair 39.9 ms (39.5 to 41.1) against 41.0 ms (40.6 to
48.4). The index saves only about 5% here, as exact and numbers-only matching remove most lines first. It matters
when much of a filing changes: in `tests/test_filing_diff.py` it gives exactly the all-pairs record on synthetic
documents, and doubling 900 paragraphs does not triple the time (ratio of best-of-five timings; fails all-pairs).

## Limits

- One machine. Pairs near the threshold were read for NVIDIA, Apple and Coca-Cola, by the model session that built
  this and by nobody else; the other five companies' comparisons are unread. A company whose earlier filing lies more than twelve
  index pages back is refused with a message that says how far the search went.
- A paragraph rewritten into several (NVIDIA's 3,700-character export-control paragraph became about six) shares
  under half its words with each piece: one removed, several added. A reworded pair at 1.00 differs only in
  stop words or punctuation ("; and" against ";").
- The method's constants (`MIN_PARAGRAPH_CHARS` 60, `REWORD_THRESHOLD` 0.5, `MAX_LISTED` 40,
  `TABLE_MAX_LETTER_SHARE` 0.5, `TITLE_ROW_CAPITAL_SHARE` 0.8) sit at the top of `core/filing_diff.py` and not in
  `core/limits.py`: that module is the contract of a thesis run, which no part of this comparison touches.
- A line of 59 characters in one filing and 61 in the other is a short line there and a paragraph here: if it also
  changed its words it reads as one short line removed and one paragraph added.
- A prose bullet with no full stop that ends in a figure, or whose words are mostly capitalised, is taken for a
  table row: counted, never listed, so a change in it does not appear in any list.
- *Unchanged* ignores case, spacing and the style of quotation marks, so an edit of those alone is unchanged.
  *Numbers only* also covers a figure that only changed its format ("$1,000" to "$1000"); the pair is listed and
  the marked words show it.
- *Numbers only* masks every figure, so "Item 1A" against "Item 7A" and "over 10%" against "over 50%" are the same
  class. For a paragraph the pair is listed with the figures marked; for a table row nothing is shown.
- What the parser takes for a sub-heading depends on bold type and a missing full stop, so the same kind of line
  is a sub-heading in one company's filing and a paragraph in another's.
- "An exact span" is a statement about the record. The page and the Markdown show an added or removed paragraph
  as the record holds it, and draw a reworded or numbers-only pair word by word, so the spacing there is normalised.
- No person has read the classification. `tests/test_sample_changes.py` checks that the recorded NVIDIA comparison
  agrees with itself (counts, lists, links, the changed words), not that a paragraph called reworded is one.
