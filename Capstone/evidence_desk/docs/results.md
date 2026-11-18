# Measured results (17 November 2026)

*The README carries these in one table. This is the full account: every number with the command that produced it, its denominator and its cautions. All of it was measured on one laptop on 17 November 2026.*

Every number below was produced by the command named. Where the output is not otherwise in the repository it is committed under [`docs/evidence/`](evidence/).

**A recorded, model-backed run** (`make replay`; the record as version 5 wrote it is [`demo/recorded-run-v5.md`](../demo/recorded-run-v5.md)). The example thesis on NVIDIA's 10-Q for the period ended 2026-07-26, its 10-Q for 2026-04-26 and its 10-K for 2026-01-25:

| | |
| --- | --- |
| Status | **COMPLETE** |
| Sources read | 3 of 3 filings, plus the XBRL company facts; 636 passages indexed |
| Verdicts | 2 supported, 3 mixed evidence, of 5 claims |
| Findings | 18 of 18 proposed findings verified, 0 withheld. 17 rest on a quote; **1 rests on reported figures only** |
| Quotes | 18 of 18 found word for word in a passage shown to the engine |
| Numbers in findings and their reasons | 25 checked against quotes and cited figures, 0 unmatched |
| Meaning check | 18 findings read by a second model: 17 agreed, 1 agreed only in part, 0 withheld |
| Reported figures | 156 computed (2 more reported as unavailable, with the reason) |

The model answers in that run did **not** come through the Anthropic API, which refused every call from this project for lack of credit on 17 November; what the API answered from 18 November is listed in [`README.md`](../README.md#where-the-model-answers-came-from). The engine's exact prompts were answered by Claude Sonnet 5.5, and the meaning check's by Claude Haiku 5.5, each running as a Claude Code subagent, and recorded ([how, and what that limits](../demo/cassettes/nvda-example/README.md)). The first recording verified 15 of 18 findings: three quotes read "Compute &amp;amp; Networking", as the prompt had escaped them. That was a bug in the engine, now fixed with a test. The instructions around this run's prompts reminded the stand-in of two of the engine's rules (copy each quote exactly; write no number that is not in a quote or a cited figure), which a plain API call would not get. So these counts were an upper bound until the same prompts were recorded again without the reminder, next.

The one finding that rests on figures alone is the case a hostile review singled out ([`docs/referee-triage.md`](referee-triage.md)): it sets company-wide revenue against a claim about China. Such a finding now counts toward a verdict only if the second model agrees that the figure bears on the claim. Here the second model did agree, so the verdict is unchanged. Two models of one family agreed with each other; that is a reason to reject the finding yourself if you disagree, not evidence that it is right.

**The same example recorded twice more, on one day, with nothing said to the stand-in but "answer"** (`make replay ARGS='--cassette demo/cassettes/nvda-example-plain'` and `make replay ARGS='--cassette demo/cassettes/nvda-example-tagged --tagged-figures'`; how they were made is in each cassette's README). The first repeats the prompts above. The second offers the engine 40 figures tagged in the filings as well ([`docs/tagged-figures.md`](tagged-figures.md)).

| | First recording (reminded of two rules) | Recorded again, no reminder | No reminder, tagged figures offered |
| --- | --- | --- | --- |
| Status | complete | complete | partial: one finding withheld |
| Findings verified, of those proposed | 18 of 18 | 18 of 18 | 18 of 19 |
| Excerpts verified word for word; quotes rejected | 18; 0 | 18; 0 | 16; 0 |
| Numbers in statements and reasons checked; not found | 25; 0 | 22; 0 | 35; 1 |
| Figures offered; citations of them in verified findings | 37; 9 | 37; 8 | 37 and 40 tagged; 20 |
| Verified findings with no excerpt, resting on figures alone | 1 | 1 | 3 |
| Meaning check: agreed, agreed in part, withheld | 17, 1, 0 | 16, 2, 0 | 17, 1, 0 |
| Verdicts on the five claims | supported, supported, mixed, mixed, mixed | supported, supported, supported, mixed, mixed | supported, supported, supported, mixed, supported |

Three readings of that table, each as far as it goes:

- **Without the reminder every quote still verified and no number went unmatched.** On this one example the reminder made no measurable difference to the two things it was about.
- **The same prompts answered twice gave a different verdict on claim 3**, and the third column differs from the second on claim 5, under which no finding cites a tagged figure. One answer per prompt cannot tell what the tagged figures do to a verdict from what asking again does.
- **What the tagged figures did change is what the findings cite**: Data Center revenue for the fiscal year ($193.74B, up 68.2%) under the claim about data center growth; customers at 22% and 14% of revenue and at 25%, 18% and 13% of receivables under the claim about concentration; revenue under the geography member "China Including Hong Kong" ($19.68B, down 21.4%) under the claim about export controls, where the middle column's only figure was the whole company's revenue growth.

The one withheld finding ends with a true sentence about two customers at 23% and 16%: the sentence is in a passage the engine was shown, but the finding did not quote it. The number check holds a statement to what the finding itself cites. The first replay of the tagged recording withheld a second finding, wrongly: "at fiscal year-end 2026" was read as the quantity 2026. That was a fault in the check, fixed with a test.

**Retrieval and generation on a golden set, scored apart** (`make eval`; [`eval/README.md`](../eval/README.md), [`docs/retrieval.md`](retrieval.md)). Thirty cases over five companies, each an analyst's claim in its own words with the excerpt a correct answer must cite; six are unanswerable on purpose.

| Retrieval: the passage that must come back, of 24 answerable cases | Top 3 | Top 8 (what the engine is shown) | Top 20 |
| --- | --- | --- | --- |
| The claim's own words | 5 | 9 | 13 |
| With the planner's queries (the pipeline when a model is configured) | 12 | 18 | 21 |
| Three other rankings, defined before any was measured | 10 to 13 | 16 to 18 | 20 to 22 |

None of the three other rankings beat the planner's queries without losing a case it had, so none is wired in.

| Generation, with the planner's queries | |
| --- | --- |
| Verdict agrees with the expected stance | 20 of 24 answerable cases; no case where "supports" came back "challenged" or the reverse |
| ... where the passage that must come back was among the eight shown (a passage counts when it holds at least half of one of the case's excerpts) | 14 of 18 |
| Unanswerable claims refused | 6 of 6 |
| Quotes found word for word | 84 of 84 |
| Numbers matched | 65 of 67; the 2 unmatched withheld 1 finding |
| Meaning check | 78 findings read: 67 agreed, 10 agreed only in part, 1 withheld. It changed no verdict: 20 of 24 before and after |
| Meaning check on planted mismatches (`make eval ARGS="mismatch ..."`) | 152 findings given real quotes that belong to another finding: 150 judged not supported, 2 agreed only in part, 0 agreed |

Read these with three cautions. The cases and their expected stances were drafted by a model from the filing text and validated mechanically; **no person has read them one by one yet**, so "agrees" means agrees with that model's reading. The model answers are recorded from a stand-in (with a minimal wrapper around the prompts, no reminder of the rules). And 24 cases is a small set: an earlier run of the same evaluation, before the per-filing cap was fixed and ten answers were recorded again, gave 17 of 24, so a difference of three cases is within what re-recording alone can move. It happened again on 17 November: a fix to the reported figures changed what the five Costco cases are shown, their answers were recorded again, and one case moved each way. The total stayed at 20 of 24; before that re-recording the rows above read 15 of 18, 67 of 70, 77 findings and 149 of 152. (One number fewer is checked since version 11: a year after "compared to" is read as a year.)

**The period check** (the same command; [`docs/period-check.md`](period-check.md)). Each year or fiscal label a verified finding names is looked for in its quotes, its cited figures and the period of each filing it quotes. It reports and withholds nothing.

| | |
| --- | --- |
| Years named by the golden set's verified findings | 34, in 25 findings |
| Found in the evidence | 34 of 34: no false alarm on the golden set, where the rules of years were developed |
| The same 25 findings with every year moved one year back, evidence unchanged | 21 flagged, 4 not |
| ... two years back | 24 flagged, 1 not |
| ... three years back | 25 flagged |
| ... one year forward | 23 flagged, 2 not |

Five of the seven that passed did so because the quote itself prints the planted year, which is the wrong-column error; two because a date falls in the calendar year of a filing's period end. The first run of this measurement flagged 19 one year forward, not 23: a date was passing as a fiscal label, which was a fault in the check, fixed from a failing test. On the three recordings of the example the check finds every year (10, 12 and 12). None of this shows the check catching a real error: the planted ones are mechanical.

**Reported figures against an answer key.** Twenty-eight published values, entered by hand with the statement each comes from: fiscal-year revenue, net income, diluted earnings per share and gross margin for Apple (fiscal 2022 to 2024), Microsoft (2023, 2024) and NVIDIA (2024, 2025). All match the recorded XBRL data. Nothing else is keyed: the other margins, cash flow and every quarterly figure rest on identities and on agreement between reported and differenced values, which is self-consistency, not truth. Free cash flow here is operating cash flow less purchases of property and equipment, which may differ from a company's own definition.

**Reported figures on eight companies** (`make figures`; [`docs/evidence/figures-eight-companies.md`](evidence/figures-eight-companies.md)). The answer key covers three companies' annual values, and for three versions nothing looked at the others. A third referee said Costco's fourth quarter could not be derived; a command written to check the fix on all eight probe companies then found two more faults on its first run:

| Company | What was wrong | Before | After |
| --- | --- | --- | --- |
| Costco | Its year is three quarters of 12 weeks and one of 16, so its 24- and 36-week periods to date matched no period length and were dropped | Newest quarter shown: the one ended 10 May 2026, beside an annual report for the year ended 30 August. No quarterly cash flow after the first. 44 of 158 metrics without a value | The 16-week quarter ended 30 August ($95.72B, up 11.1% on a year earlier), every quarter's cash flow, 22 of 152 without a value |
| Amazon | Its 10-Qs tag cash flows for the twelve months ended each quarter; periods that long were taken for fiscal years | The two newest "fiscal years" ended 30 September and 30 June 2026 and held a cash flow only; 26 figures offered to a run | Fiscal years are years an annual report reported; 38 figures offered |
| JPMorgan | A bank's total net revenue is tagged under a concept the tool did not read | No revenue figure at all; 11 figures offered | Revenue for eight quarters; 20 figures offered |

After the first fix only Costco's lines of the probe moved; after the other two, only Amazon's and JPMorgan's. A quarter is no longer compared with the quarter before it when their lengths differ by more than ten days, so Costco's 16 weeks are not shown as growth on 12. None of this says a figure is right: it says which lines a change moved.

**Filing structure on eight companies** (`make probe`, 14 filings; [`docs/speed/probe-v4.md`](speed/probe-v4.md)): NVIDIA, Apple, Microsoft, Coca-Cola, Tesla, Costco and Amazon have 95.8% to 98.6% of their text under a numbered Item. That is a share of text, not a count of Items found against Items present, and it cannot show a wrong boundary. JPMorgan's 10-Q has 1.6%: it prints no Item headings over its body, and a run on it is now marked partial. Its 10-K scores 99.4%, which overstates it, because its annual report follows Item 15.

**What changed between two filings** (`make changes`; [`docs/filing-changes.md`](filing-changes.md)), measured on NVIDIA on 17 November from filings fetched live:

| Paragraphs | Unchanged | Numbers only | Reworded | Added | Removed | Short lines and table rows: unchanged / numbers only / added / removed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Annual report for fiscal 2026 against fiscal 2025 | 251 | 60 | 218 | 133 | 132 | 355 / 357 / 150 / 202 |
| of which Item 1A, Risk Factors | 124 | 1 | 51 | 34 | 22 | 15 / 0 / 2 / 1 |
| Quarterly report for the second quarter of fiscal 2027 against the first | 99 | 14 | 108 | 71 | 66 | 215 / 168 / 239 / 187 |

The five counts are of paragraphs: lines of at least 60 characters that are not table rows. Shorter lines and table rows are counted apart and never listed. Every line of text under an Item in each filing is in exactly one count, which a test checks on two real filings. (Until version 7 the first two columns counted every line, table rows included, under the heading "paragraphs": the annual report's "606 unchanged, 417 numbers only" were 251 and 60 paragraphs.)

What the annual-report comparison shows, as the tool found it in the two filings: among the risk factors added is one about an investment and partnership agreement with OpenAI that was not yet final; among those removed, paragraphs about an export rule which, the later report says, the government announced in May 2025 it would rescind. A risk factor whose words did not change now says the company generated 31% of its revenue from sales outside the United States, where the year before it said 53%. Seven sub-headings under Item 1 are in the earlier report only, among them "Climate Change" and "Diversity, Inclusion and Belonging at NVIDIA"; the notes gained one headed "Note 2 - Groq".

The method's one threshold (how similar two paragraphs must be to count as reworded) was set by reading the pairs each candidate value would add, on these two comparisons only, and by a model. The comparison has been run on the annual reports of the other seven probe companies ([`docs/evidence/changes-eight-companies.md`](evidence/changes-eight-companies.md), every row of every run): it ran on all eight and matched every group (the cover page and each Item) of one report to its group in the other. The pairs near the threshold were read for Apple and Coca-Cola, also by a model; no person has checked the classification on any. Running it on JPMorgan found two things: its earlier annual report was not in EDGAR's recent index at all (fixed: older index pages are now read, up to twelve), and 7,193 of the 8,098 lines of its later report sit under "Item 15", because the bank's annual report follows its last Item heading. The exit check of the plan is a test: one planted paragraph comes back as exactly one added and one removed.

**Changes that bear on each claim** (`make sample-run-changes`; [`docs/claim-changes.md`](claim-changes.md)). For the recorded example, on 17 November: the annual report for fiscal 2026 against the one for fiscal 2025 and the second-quarter report of fiscal 2027 against the first hold 802 changed paragraphs. Between 126 and 276 distinct changes share two words with each of the five claims or with the search queries the run wrote for it; the five best are listed. Under "Gross margin is expanding" the first is a sentence the newest annual report added: "Gross margin decreased in fiscal year 2026 as our business model transitioned from offering Hopper HGX systems to Blackwell full-scale datacenter solutions." Under the claim about suppliers the first is a paragraph about vendor questionnaires under the cybersecurity Item: keyword overlap is not relevance. Nobody has judged these lists, and no number here says how often they help.

**Tagged breakdowns** (`make breakdowns`; [`docs/breakdowns.md`](breakdowns.md)), from filings fetched live on 17 November. NVIDIA's annual report for the year ended 25 January 2026, as the filing tags it:

| Revenue, USD millions: the breakdown, and the row as the tool labels it | Fiscal 2026 | Change | Fiscal 2025 |
| --- | ---: | ---: | ---: |
| By product or service: Data Center | 193,737 | +68.2% | 115,186 |
| By product or service: Gaming | 16,042 | +41.3% | 11,350 |
| By geography: US | 149,617 | +93.1% | 77,482 |
| By geography: China Including Hong Kong | 19,677 | -21.4% | 25,048 |
| Total (tagged, no dimension) | 215,938 | +65.5% | 130,497 |

One direct customer is tagged at 22% of revenue and another at 14%. The tests check these against the filing's own text: the table row "Data Center $193,737 $115,186", and the sentences "Data Center revenue for fiscal year 2026 was up 68% from a year ago" and "sales to one direct customer represented 22% of total revenue and sales to another direct customer represented 14%". That shows the reader attaches each number to the right member, period and scale; it does not prove the company's number. The same command ran on the annual and the quarterly reports of all eight probe companies ([`docs/evidence/breakdowns-eight-companies.md`](evidence/breakdowns-eight-companies.md)): wherever a filing tags a total, every breakdown's members add up to it. No person has compared a table with the printed one.

**The live application, end to end** (`make live-walk`; output in `docs/evidence/`): the running app over HTTP, filings fetched live, recorded answers. The walk fails unless the run is judged. It will fail after NVIDIA's next filing, when the recording no longer matches. Since version 10 it also starts a run that asks for the tagged figures and checks that 40 are read from the live filings, offered and recorded; that run's assessments are not in the recording the app replays, so they fall back and it is not judged.

**Backup and restore** (`make backup`, `make restore-check`; output in `docs/evidence/`): a restore of the newest backup is compared with the live record, every column of every run, decision and thesis, and the check fails on a record this version cannot read. What it shows is that the backup and the live record are the same at that moment. A row written after the backup was taken no longer makes it fail: since 14.1 it says BEHIND (exit code 2) and names what was written since, and it still fails on a row the backup should hold and does not, or holds otherwise with nothing dated after it. A run finished after the backup keeps its start time, so it still fails. It passes on the real record (18 November, version 0.14.1): 43 runs, 20 decisions and 10 theses, all readable. Until review 6 it compared runs by id and skipped what it could not parse on both sides; until the fourth referee it compared one column of each row. Same disk, same machine.

**Two processes writing one record** (`make two-writers`; [`docs/evidence/two-writers.txt`](evidence/two-writers.txt)): the app and a one-off container, on a scratch record, 2,000 decisions through the app and 2,000 runs written directly at the same time. No write failed, SQLite's integrity check passed, every row was present and readable. One run on this laptop; it says nothing about a power cut.

**Speed** ([`docs/speed.md`](speed.md)). The offline profile is not where a real run's time goes: a real run waits on EDGAR and, with a key, on the model, which has never been timed. What was measured: at version 11 a live run without a key was timed stage by stage inside the run, five runs under each of four conditions (`make time-live`): a median of 1,472 ms with an empty filing cache (EDGAR requests 940 ms, parsing 366 ms) and 545 ms with a warm one (EDGAR 380 ms). EDGAR's own latency moved between 603 and 1,006 ms for the same six requests across four sessions that afternoon, so medians of different sessions are not comparable to within a few hundred milliseconds. A run that asked for tagged figures made two more requests than one that did not (8 against 6 cold, 5 against 3 warm, 306 ms on a warm run in the session that found it); it now makes none more, because what is read from a filing's tags is kept and a first run reads them from the HTML it already has. At version 4 one pair of runs had given 1.01 s and 0.38 s. Offline, cutting the inline-XBRL header before parsing saves a median of 34.3 ms per run over 20 alternating pairs on an idle machine (interquartile range 27.9 to 58.7 ms; single pairs ranged from 16.6 to 65.3 ms; a second bench of 20 pairs gave 35.4 ms), about 7% of the offline run and about 2% of a live run with an empty cache. At version 4 the same bench gave 28.8 ms. The cut changes no document: each of 14 live filings of eight companies parses to the same text, hash and sections with and without it (`make header-cut-check`). Concurrent assessment of claims is a tested mechanism; its gain with a real model is unmeasured.
