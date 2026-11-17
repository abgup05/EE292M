# Cassette: the NVIDIA example with the tagged figures offered

The example thesis on the three recorded NVIDIA filings, run with `tagged_figures` on: after the 37 company-facts figures, the engine is offered 40 figures read from the inline XBRL of the newest annual and quarterly report (revenue by segment, product and geography, each customer's share of revenue and of receivables, and each one's change from a year earlier). What the option does and its limits are in [`docs/tagged-figures.md`](../../../docs/tagged-figures.md).

`make replay ARGS='--cassette demo/cassettes/nvda-example-tagged --tagged-figures'` replays it; `tests/test_replay_tagged.py` asserts the result. The page's sample `?sample=run-tagged` is this run.

## How the answers were produced

Exactly as for [`../nvda-example-plain`](../nvda-example-plain/README.md), on the same day (17 November 2026): one fresh Claude Code subagent per request, given the request as a text file under a neutral name and the instructions quoted in that README, with no rule repeated. Claude Sonnet 5.5 answered the five assessments and the summary, Claude Haiku 5.5 the meaning checks. Each answer was checked against its schema and stored as written. The plan is the answer already recorded for the identical prompt.

**Two requests were asked twice, and why.** The first complete replay withheld two findings. One had done nothing wrong: its statement said "at fiscal year-end 2026" and the number check read 2026 as a quantity that no quote or figure contained. That was a fault in the check, now fixed with a test (`tests/test_numcheck.py::test_a_year_after_year_end_is_not_a_quantity_in_a_recorded_statement`). With that finding verified, the meaning check for claim 2 had one more finding to judge and the summary one more to restate, so both prompts changed and both were asked again. The two answers to the prompts that no longer occur were removed from the cassette; no answer was altered. The first replay's counts are given below beside the final ones.

## What it shows, against the control recorded the same day

| | Control: no tagged figures | Tagged figures offered |
| --- | --- | --- |
| Figures offered to the engine | 37 | 37 and 40 tagged |
| Citations of figures in verified findings | 8 | 20 |
| Findings that cite a tagged figure | none | 6 (5 verified, 1 withheld) |
| Findings verified, withheld | 18, 0 | 18, 1 (first replay, before the fix to the check: 17, 2) |
| Excerpts verified word for word; quotes rejected | 18; 0 | 16; 0 |
| Numbers in statements checked; not found | 22; 0 | 35; 1 |
| Verified findings that rest on figures alone, with no excerpt | 1 (counted as context) | 3 (two counted as support, one as context) |
| Meaning check: supported, partly, not supported | 16, 2, 0 | 17, 1, 0 |
| Verdicts, claims 1 to 5 | supported, supported, supported, mixed, mixed | supported, supported, supported, mixed, supported |
| Status | complete | partial (one finding withheld) |

Both columns are `make replay` on the cassette named.

What the tagged figures were used for, as the findings state them:

- **Claim 1** (data center revenue is growing): "For the full fiscal year ended 2026-01-25, tagged Data Center revenue was $193.74B, a change of +68.2% from the prior year." The company-facts figures hold no revenue by product.
- **Claim 2** (a few customers): the 22% and 14% shares of revenue beside the quoted sentence, and three customers at 25%, 18% and 13% of accounts receivable, which no offered passage states.
- **Claim 3** (export controls and China): revenue tagged under the geography member "China Including Hong Kong" of $19.68B for the fiscal year, down 21.4%, and the latest quarter's. In the control the only figure cited under this claim was the whole company's revenue growth, which says nothing about China.

**The finding that is still withheld** ends "In the second quarter of fiscal year 2026 two customers represented 23% and 16%." That sentence is true of the filing: it is in a passage the engine was shown. But the finding did not quote it, and the one tagged figure it cited says 16%. The engine's rule is that every number in a statement is in a quote or a figure the finding itself cites; with no reminder of that rule the stand-in broke it once in 35 numbers, and the number check withheld the finding. So this is the check holding a true statement to its evidence, not catching a false one.

## What it does not show

- **That tagged figures change a verdict.** The verdict on claim 5 (suppliers) differs between the two columns, and no finding under claim 5 cites a tagged figure. Between the control and the first recording of the same prompts, the verdict on claim 3 differs too. One answer per prompt cannot separate the option's effect on a verdict from asking again.
- **That a figure bears on its claim.** A finding that cites figures and quotes nothing is checked for its numbers and then read by the second model, and nothing else. With the option on there are three such findings, and two count as support.
- **Any company but NVIDIA**, and anything about the API path: the answers are a stand-in's, as the control's README sets out.
- The row labels come from tag names. No person has compared these figures with the printed tables.
