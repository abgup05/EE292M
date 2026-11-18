# Events since the annual report (version 12)

## Why

A user tested "buy NVDA because Jensen is gone". The run read the annual report of 25 February 2026, in which Jen-Hsun Huang is chief executive, and the quarterly reports after it, and answered from them. It never read the 8-K of 12 November 2026 that reports his resignation, and nothing on the page said how old its evidence was. A run read the newest 10-K and the 10-Qs after it, never a current report (8-K), and had no "as of" date.

Version 12 adds three things, all deterministic. No model call is added.

1. **A timeline**: every 8-K and 8-K/A the company filed after the newest annual report the run read, newest first, each with its items. Some are read and split into those items.
2. **An as-of line** on every run: the newest filing read and its date, the newest periodic report, how many days before the run, and what became of each 8-K listed.
3. **A mark on evidence that a later filing postdates**: a finding whose filings are all older than an 8-K on its claim's subject says so, and a claim whose verdict rests on such a finding gets a caution.

The same timeline is available outside a run: `GET /api/companies/{ticker}/events` and `make events T=NVDA`.

## The rules, in plain words

Code: `core/events.py` (pure), `services/events.py` (listing and reading), `sources/current_report.py` (the splitter). The numbers are in `core/limits.py`, the wording in `core/policy.py`.

**Items and categories.** SEC's table of Form 8-K items, 1.01 to 9.01, each with its title and one category:

| Category | Items | Substantive |
| --- | --- | --- |
| leadership | 5.02 | yes |
| accounting | 4.01, 4.02 | yes |
| deal | 1.01, 1.02, 2.01 | yes |
| restructuring | 2.05, 2.06 | yes |
| incident | 1.05 | yes |
| financing | 2.03, 2.04, 3.02 | yes |
| control | 1.03, 5.01 | yes |
| listing | 3.01 | yes |
| results | 2.02 | no |
| governance | 5.03, 5.05, 5.07, 5.08, 3.03 | no |
| disclosure | 7.01, 8.01 | no |
| exhibits | 9.01 | no |
| other | the rest of SEC's table | no |

An item number that is not in the table is kept and labelled unknown. The category comes from the item number EDGAR's index lists, not from what the 8-K says: NVIDIA's agreement to acquire Hugging Face (3 September 2026) was filed under Item 8.01, so it is "disclosure", not "deal".

**Which 8-Ks are read.** All 8-Ks filed after the newest annual report are listed from EDGAR's submissions index. That is the index the run already fetched to choose its periodic reports, reused for up to 60 seconds, so listing them costs no request. Of those, the documents read are every 8-K filed after the newest periodic report, plus every substantive one since the annual report, newest first, at most `MAX_EVENTS_READ` (8). The rest are listed from the index only. Each listed 8-K ends in one of five states: read, could not be read (with the reason), not read because of the cap, not read because the run time limit came first, or routine and listed from the index only. The counts line states all five, and they add up to the number listed (`tests/test_events_service.py::test_the_cap_reads_the_newest_and_counts_the_rest`). A failure is a reason on that 8-K, never an error of the run.

**Splitting an 8-K.** One section per "Item N.NN" heading, as an exact slice of the stored text. A heading may name several items ("Items 2.02 and 9.01"), carry a sub-item letter ("Item 9.01(d).") or put its title on the next line. A reference inside a sentence ("Item 1.01 above") opens no section. The signature block, and an exhibit index after the last item, are a section of their own, except that an exhibit index directly under the last item is that item's body. For each item read the record keeps its opening sentences, verbatim, at most `EVENT_OPENING_SENTENCES` (2). For an Item 5.02 it also keeps the officer roles the section names, as whole words.

**A claim's categories.** One lexicon per substantive category, matched as whole words, plus one pattern for leadership: a capitalised name followed by a word of leaving ("Jensen is gone", "Huang resigned"). "Margins are gone" gives no category, because "Margins" is on a list of words that are not names. "The CEO transition is a risk" gives leadership through the lexicon. An auditor leaving is accounting, not leadership. Results, governance, disclosure, exhibits and other have no lexicon, so no claim is given them. The rule is a lexicon; it is measured below.

**What a claim is offered.** Item sections never join the BM25 pool. A claim with a substantive category is also offered up to `EVENT_PASSAGES_PER_CLAIM` (2) item sections of its own categories, from 8-Ks read, newest first. Each is a passage marked with its form and filing date, and its 8-K becomes a source of the run only then. The Claude engine's prompt carries those attributes, and one more rule about newer filings, only when such a passage is offered. A prompt without one is byte for byte what version 11 sent, so the recorded answers still match. The extractive engine quotes a pinned section's opening sentence first.

**Supersession.** An 8-K is later than a finding when it was filed after every filing the finding cites: the filing of each excerpt, and of each input of each cited figure. The finding is marked `predated_by` that 8-K when one of the 8-K's items is of a category of the finding's claim. The 8-K counts even if it was listed and not read: the index's item numbers decide. The verdict rule is unchanged. A claim whose supporting or challenging finding is predated gets a caution: "The evidence for this verdict was filed before the 8-K of 10 Mar 2026 (Item 5.02), which reports a change of directors or officers. Read that filing before relying on the verdict." A context finding decides no verdict, so it gives no caution.

**The note.** A claim of a substantive category with no 8-K of that category since the annual report gets this note: "No 8-K filed since 25 Feb 2026 reports a change of directors or officers (Item 5.02). The newest filing read is dated 12 Nov 2026; anything later is not in the record." It never says the claim is false. Where such an 8-K was listed but not read, the note says so and why. Where EDGAR's list could not be read, it says the answer is not known.

## What the record gains

`Run.timeline` (the 8-Ks, each with its items, status and reason), `Run.as_of` (the newest filing and its date, the newest periodic report, the days to the run's start, the counts, any index error, and the line the page shows), `Claim.categories`, `Claim.caution`, `Claim.event_note` and `Finding.predated_by`. Every field has a default, so a run recorded before version 12 loads unchanged and shows no panel. `tests/test_events_run.py::test_a_run_recorded_by_version_11_still_loads_with_empty_event_fields` loads a run recorded by 0.11.1, and `make restore-check` read all 40 runs of the live record under 0.12.0.

The page shows the as-of line under the run's details, a panel "Since the annual report", a claim's caution or note, and on a finding "Predates the 8-K of 12 Nov 2026, Item 5.02" linking to that 8-K in the panel. The Markdown brief carries the same, with 8-K text escaped as excerpts are. The page computes none of it.

## Measurements

**The motivating case** (`tests/test_events_run.py::test_the_motivating_case_the_8k_is_shown_offered_and_marks_the_older_finding`, offline). A fake EDGAR lists an Item 5.02 8-K after the 10-Q, and the claim is "Buy because Jane Smith is gone." The 8-K is on the timeline, the claim is categorised leadership, the 8-K's section is offered, and a finding quoting the older 10-K is marked predated with a caution. The opposite case, with no 5.02 since the annual report, gives the note and no verdict. The answers in these tests are scripted by the test, not a model's.

**NVIDIA, live** (`make events T=NVDA`, 18 November 2026; [`evidence/events-nvda.txt`](evidence/events-nvda.txt)). EDGAR lists 12 8-Ks since the 10-K of 25 February 2026. 8 were read, 0 failed, 0 were capped, and 4 routine ones filed before the 10-Q of 26 August were listed from the index only. The 8-K of 12 November carries Items 5.02 and 9.01. Its first sentence: "On November 11, 2026, the Board of Directors, or the Board, of NVIDIA Corporation accepted the resignation of Jen-Hsun Huang, as NVIDIA's President, Chief Executive Officer and member of the Board, effective immediately." The second names Colette M. Kress interim chief executive. Four other 8-Ks since the annual report carry Item 5.02: a compensation plan (6 March), the chief accounting officer's retirement (27 April), a director's appointment (8 May) and an executive vice president's retirement (2 July). The fixtures were recorded on 17 November with eleven of these 8-Ks. The twelfth, a results 8-K (Item 2.02) of 17 November, came after.

**The splitter on eight companies** (`make events-probe`, live; [`evidence/events-probe-before.md`](evidence/events-probe-before.md), [`evidence/events-probe-after.md`](evidence/events-probe-after.md)). It ran on every 8-K and 8-K/A filed in the 12 months to 18 November 2026 by NVDA, AAPL, MSFT, KO, JPM, TSLA, COST and AMZN: 107 filings listing 200 items. The denominator is the items EDGAR's index lists, and an item is found when the split document has a section headed with its number.

| | Found | Misses |
| --- | --- | --- |
| Before | 190 of 200 | Coca-Cola's Item 9.01 in all 8 of its 8-Ks that list it, written "Item 9.01(d)." with the exhibit index directly under it; JPMorgan's Item 5.02 twice, written "Item 5.02(e) Departure ..." |
| After two fixes | 200 of 200 | none |

The fixes: a heading may carry a sub-item letter after its number, and an exhibit index directly under the last item is its body. One 8-K of each layout is recorded as a fixture with a test. Ten sections were headed in a document but not listed by the index: NVIDIA, JPMorgan and Costco 8-Ks that head an Item 9.01 the index leaves out. On NVIDIA's own 8-Ks, opening sentences were also cut after "Mr." ("Huang's resignation, the Board appointed ..."). The sentence rule now rejoins a split after a title such as "Mr." or "Ms.", or before a span that starts in lower case or with a bracket.

**Claim categories** (`make event-categories`, offline; labels in [`../eval/claim-categories.json`](../eval/claim-categories.json)). 84 claims were labelled before the rule existed (commit `6bf3512`). 39 have no category, and the traps are among them: "margins are gone", "China is gone as a market", "Apple replaced Intel chips". The labels were written by the model that wrote the rule, and no person has read them.

| | Predicted | Labelled | Agreed | Precision | Recall | No-category claims kept at none | Exact |
| --- | --- | --- | --- | --- | --- | --- | --- |
| First score, before any tuning | 51 | 50 | 46 | 0.90 | 0.92 | 35 of 39 | 75 of 84 |
| After one tuning pass | 53 | 50 | 50 | 0.94 | 1.00 | 36 of 39 | 81 of 84 |

The tuning pass added "no longer rely on" (accounting), "agreement terminated" (deal), closing factories and exiting a business (restructuring), retiring or redeeming notes (financing). It also made "replaced" count only in the passive, and made an auditor leaving not count as leadership. It was made after reading the nine disagreements of the first score, on the same 84 claims, so the second score is fitted to them and is not a measure of the rule on new claims; the first score is the fairer one. Three disagreements remain, all false alarms: "China is gone as a market for its top chips" and "Intel has left the foundry race" read as a name leaving, and "Stock-based compensation is diluting shareholders" reads as financing. `tests/test_claim_categories_eval.py` pins the table.

**Speed** (`make time-live RUNS=5`, live, no key; [`speed/live-timing-v12-before.txt`](speed/live-timing-v12-before.txt), [`speed/live-timing-v12.txt`](speed/live-timing-v12.txt)). The example run, five runs per condition. Before is version 0.11.1 at 07:49 UTC and after is 0.12.0 at 08:24 UTC on 18 November, on one laptop. They were run one after the other, not alternated, because the old version would have had to run from a second worktree.

| Condition | Before: median (range), EDGAR requests | After: median (range), EDGAR requests |
| --- | --- | --- |
| Cold filing cache | 1360 ms (1007 to 1667), 5 | 2108 ms (2019 to 2496), 13 |
| Warm filing cache | 421 ms (380 to 504), 2 | 384 ms (303 to 463), 2 |
| Cold, tagged figures | 1236 ms (1004 to 1440), 5 | 2084 ms (2015 to 2489), 13 |
| Warm, tagged figures | 460 ms (333 to 1289), 2 | 313 ms (305 to 655), 2 |

A cold run now fetches the eight 8-Ks it reads, eight requests more, and listing them costs none. A warm run reads them from the filing cache and makes the same two requests as before. The warm medians moved within their own spread, and without alternation that difference says nothing. Reading and splitting the 8-Ks is not timed as a stage of its own; their requests are in "EDGAR requests".

## Limits

- **8-K only.** Foreign private issuers file 6-K, which is not read, and neither are proxy statements, Forms 4 or press releases outside an 8-K.
- **Nothing before EDGAR has it.** An event is in the record only once its 8-K is filed and EDGAR's index lists it. A company has four business days to file, so the days between the event and the filing are not covered. The as-of line says how old the newest filing read is.
- **Exhibits are not read.** An 8-K's press release (Exhibit 99.1) is often where the substance is; only the 8-K's own items are split and quoted.
- **The category of an 8-K is its item number.** What the item says is not read for the category: an acquisition filed under Item 8.01 is "disclosure".
- **The category of a claim is a lexicon.** It is measured on 84 claims labelled by a model and tuned on the same claims. A claim worded outside the lexicon gets no category, so it is offered no 8-K and gets no note, and a false alarm offers it 8-Ks it does not need. Both are shown in the claim's categories on the record.
- **Read at most eight per run, opening sentences only.** The cap counts what it leaves out, and an item's later paragraphs are in the section offered to a claim but not in the panel.
- **The newer-filings rule in the prompt has been answered once, live, and is replayed by no recording.** No recording offers an 8-K passage: no claim of the example thesis has a category (`tests/test_events_run.py::test_the_example_thesis_has_no_claim_an_8k_bears_on`). One live run of 18 November through the API (`?sample=run-events`, run-39d0b17b5396) was offered 8-K sections, and 4 of its 8 excerpts quote an 8-K ([`README.md`](../README.md#where-the-model-answers-came-from)).
