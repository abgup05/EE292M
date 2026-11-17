# Measured results (17 November 2026)

*The README carries these in one table. This is the full account: every number with the command that produced it, its denominator and its cautions. All of it was measured on one laptop on 17 November 2026.*

Every number below was produced by the command named. Where the output is not otherwise in the repository it is committed under [`docs/evidence/`](evidence/).

**A recorded, model-backed run** (`make replay`; the record is [`demo/recorded-run-v5.md`](../demo/recorded-run-v5.md)). The example thesis on NVIDIA's 10-Q for the period ended 2026-07-26, its 10-Q for 2026-04-26 and its 10-K for 2026-01-25:

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

The model answers in that run did **not** come through the Anthropic API, which refused every call from this project for lack of credit. The engine's exact prompts were answered by Claude Sonnet 5.5, and the meaning check's by Claude Haiku 5.5, each running as a Claude Code subagent, and recorded ([how, and what that limits](../demo/cassettes/nvda-example/README.md)). The first recording verified 15 of 18 findings: three quotes read "Compute &amp;amp; Networking", as the prompt had escaped them. That was a bug in the engine, now fixed with a test. **These counts are an upper bound.** The instructions around this run's prompts reminded the stand-in of two of the engine's rules (copy each quote exactly; write no number that is not in a quote or a cited figure), which a plain API call would not get. The stand-ins that answered the golden set, below, were given no such reminder.

The one finding that rests on figures alone is the case a hostile review singled out ([`docs/referee-triage.md`](referee-triage.md)): it sets company-wide revenue against a claim about China. Such a finding now counts toward a verdict only if the second model agrees that the figure bears on the claim. Here the second model did agree, so the verdict is unchanged. Two models of one family agreed with each other; that is a reason to reject the finding yourself if you disagree, not evidence that it is right.

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
| ... where the passage that must come back was among the eight shown (a passage counts when it holds at least half of one of the case's excerpts) | 15 of 18 |
| Unanswerable claims refused | 6 of 6 |
| Quotes found word for word | 84 of 84 |
| Numbers matched | 67 of 70; the 3 unmatched withheld 2 findings |
| Meaning check | 77 findings read: 66 agreed, 10 agreed only in part, 1 withheld. It changed no verdict: 20 of 24 before and after |
| Meaning check on planted mismatches (`make eval ARGS="mismatch ..."`) | 152 findings given real quotes that belong to another finding: 149 judged not supported, 3 agreed only in part, 0 agreed |

Read these with three cautions. The cases and their expected stances were drafted by a model from the filing text and validated mechanically; **no person has read them one by one yet**, so "agrees" means agrees with that model's reading. The model answers are recorded from a stand-in (with a minimal wrapper around the prompts, no reminder of the rules). And 24 cases is a small set: an earlier run of the same evaluation, before the per-filing cap was fixed and ten answers were recorded again, gave 17 of 24, so a difference of three cases is within what re-recording alone can move.

**Reported figures against an answer key.** Twenty-eight published values, entered by hand with the statement each comes from: fiscal-year revenue, net income, diluted earnings per share and gross margin for Apple (fiscal 2022 to 2024), Microsoft (2023, 2024) and NVIDIA (2024, 2025). All match the recorded XBRL data. Nothing else is keyed: the other margins, cash flow and every quarterly figure rest on identities and on agreement between reported and differenced values, which is self-consistency, not truth. Free cash flow here is operating cash flow less purchases of property and equipment, which may differ from a company's own definition.

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

**Changes that bear on each claim** (`make sample-run-changes`; [`docs/claim-changes.md`](claim-changes.md)). For the recorded example, on 17 November: the annual report for fiscal 2026 against the one for fiscal 2025 and the second-quarter report of fiscal 2027 against the first hold 802 changed paragraphs. Between 126 and 276 distinct changes share two words with each of the five claims; the five best are listed. Under "Gross margin is expanding" the first is a sentence the newest annual report added: "Gross margin decreased in fiscal year 2026 as our business model transitioned from offering Hopper HGX systems to Blackwell full-scale datacenter solutions." Under the claim about suppliers the first is a paragraph about vendor questionnaires under the cybersecurity Item: keyword overlap is not relevance. Nobody has judged these lists, and no number here says how often they help.

**Tagged breakdowns** (`make breakdowns`; [`docs/breakdowns.md`](breakdowns.md)), from filings fetched live on 17 November. NVIDIA's annual report for the year ended 25 January 2026, as the filing tags it:

| Revenue, USD millions: the breakdown, and the row as the tool labels it | Fiscal 2026 | Change | Fiscal 2025 |
| --- | ---: | ---: | ---: |
| By product or service: Data Center | 193,737 | +68.2% | 115,186 |
| By product or service: Gaming | 16,042 | +41.3% | 11,350 |
| By geography: US | 149,617 | +93.1% | 77,482 |
| By geography: China Including Hong Kong | 19,677 | -21.4% | 25,048 |
| Total (tagged, no dimension) | 215,938 | +65.5% | 130,497 |

One direct customer is tagged at 22% of revenue and another at 14%. The tests check these against the filing's own text: the table row "Data Center $193,737 $115,186", and the sentences "Data Center revenue for fiscal year 2026 was up 68% from a year ago" and "sales to one direct customer represented 22% of total revenue and sales to another direct customer represented 14%". That shows the reader attaches each number to the right member, period and scale; it does not prove the company's number. The same command ran on the annual and the quarterly reports of all eight probe companies ([`docs/evidence/breakdowns-eight-companies.md`](evidence/breakdowns-eight-companies.md)): wherever a filing tags a total, every breakdown's members add up to it. No person has compared a table with the printed one.

**The live application, end to end** (`make live-walk`; output in `docs/evidence/`): the running app over HTTP, filings fetched live, recorded answers. The walk fails unless the run is judged. It will fail after NVIDIA's next filing, when the recording no longer matches.

**Backup and restore** (`make backup`, `make restore-check`; output in `docs/evidence/`): a restore of the newest backup is compared with the live record, every run, decision and thesis. Same disk, same machine.

**Speed** ([`docs/speed.md`](speed.md)). The offline profile is not where a real run's time goes: a real run waits on EDGAR and, with a key, on the model, which has never been timed. What was measured: a first live keyless run took 1.01 s and a second, with all three filings read from the cache, 0.38 s (one pair of runs). Offline, cutting the inline-XBRL header before parsing saves a median of 28.8 ms per run over 20 alternating pairs, (interquartile range 21.5 to 56.9 ms; single pairs ranged from −8.6 to 93.0 ms; a second bench of 12 pairs gave 37.9 ms), about 7 to 9% of the offline run and about 3% of a live run without a key (28.8 ms of 1.01 s). Concurrent assessment of claims is a tested mechanism; its gain with a real model is unmeasured.
