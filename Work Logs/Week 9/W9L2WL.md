# EE292M Work Log

## Week 9B (session of 18 November 2026)

*Written on 17 November 2026, the day before the session, in the catch-up sprint. This log is drafted by the Claude Code session that did the work; the decisions are mine to check. Nothing here is about the lecture: it had not happened when this was written, and its slides are not in the repository.*

**The new version, tag `capstone-v6`: what changed between two filings**

- The last milestone of the plan. For one ticker it compares the latest annual report with the one before it (or the latest quarterly report with the previous one), Item by Item. Each paragraph of the later filing is unchanged, changed only in its numbers, reworded, or added; each paragraph of the earlier one with no counterpart is removed.
- Every listed paragraph is an exact span of the stored text with a link into its own filing. A reworded pair shows its changed words: added words underlined, removed words struck through.
- Three ways in: `make changes ARGS="NVDA --form 10-K"`, the route `GET /api/companies/{ticker}/changes`, and a third action on the page beside the thesis and the reported figures. `?sample=changes` shows a recorded comparison without the network.
- No model is involved in this feature.

**Measured, on filings fetched live on 17 November**

| Annual reports, paragraphs | Unchanged | Numbers only | Reworded | Added | Removed |
| --- | ---: | ---: | ---: | ---: | ---: |
| NVIDIA, fiscal 2026 against fiscal 2025 | 251 | 60 | 218 | 133 | 132 |
| of which Item 1A, Risk Factors | 124 | 1 | 51 | 34 | 22 |

*This table first read 606, 417 and 139 in its first two columns. Those counted every line, table rows included, beside three columns that counted paragraphs only. A referee found it later the same day (below); the numbers above are the corrected ones.*

- The same command on seven more companies (Apple, Microsoft, Coca-Cola, JPMorgan, Tesla, Costco, Amazon) ran on six at once and on JPMorgan after a fix (below), and matched every Item of one report to its Item in the other. The rows are in `Capstone/evidence_desk/docs/evidence/changes-eight-companies.md`.
- The gate from a fresh clone at the tag: 1,094 offline tests, the smoke test, 69 assertions on the rendered page. The live walk now also compares NVIDIA's two annual reports through the running app.

**How it was tested**

- The plan's exit check is a test: one planted paragraph comes back as exactly one added and one removed.
- Breaking the one threshold on purpose (0.5 to 0.0) failed 14 tests. Restored, they pass.
- The recorded sample has tests that damage a copy in eight ways (a wrong total, a missing paragraph, a link into the wrong filing, a lost changed word) and expect each to be reported.

**What went wrong**

- **Tested on one company, again.** `AGENTS.md` lists this as a mistake made more than once. The threshold was set and the feature finished on NVIDIA alone. Running the other seven took under a minute and found that JPMorgan could not be compared at all: it files so often that EDGAR's recent index held only one annual report. Fixed with ten tests written first: the index's older pages are now read, newest first, at most twelve.
- **JPMorgan's Item labels mean little.** 7,193 of the 8,098 lines of its later report sit under "Item 15", because the bank's annual report follows its last Item heading. The paragraphs compared are the right ones; the Item named beside them is not where a reader would look. "Item coverage" of 99.4% cannot see this.
- **The threshold was set by a model's reading.** At 0.6 many "added" paragraphs had a twin among the "removed". It went to 0.5 after the pairs near it were read on two NVIDIA comparisons, by the session and not by a person. On the other seven companies nobody has read anything.
- **The page tests were written after the view.** They passed at once, which shows nothing. The view was then broken in eight places and all nine failed. The check was made; the order was wrong.
- **A layout fault no test could see.** At phone width the column headings broke inside a word. It was found by looking at the screenshot. Fixed; still no test for layout.
- **"Moved numbers" was met only as a count.** The plan promised them. At the tag, a paragraph whose numbers alone changed was counted and not listed. Version 7 lists it with the figures marked; a table row whose figures moved is still only counted.
- The candidate index that was meant to make the comparison fast saves about 5%. Reported as measured.

**After the tag: a second referee, and version 7**

Version 6 had been tagged without any review, so the `referee` agent read it: another model, read-only, from a checkout with my notes, the earlier reviews and the first triage removed. Ten findings, kept unedited in `Capstone/evidence_desk/docs/reviews/referee-2-version-6.md`; every one is accepted with a fix or rejected with a reason in `docs/referee-2-triage.md`. The fixes are tag `capstone-v7`.

- **The headline table counted two different things.** "Unchanged" and "numbers only" counted every line; "reworded", "added" and "removed" counted paragraphs; all five were headed "paragraphs". The record now has nine counts and a test that every line of two real filings is in exactly one. The sentence about JPMorgan above had divided one mixed sum by another.
- **Sub-headings were invisible.** The parser keeps them apart from the text, so a renamed or dropped sub-heading showed nothing. They are now named when only one filing has them. On NVIDIA this shows seven sub-headings of Item 1 that are in the earlier report only, among them "Climate Change" and "Diversity, Inclusion and Belonging at NVIDIA".
- **A paragraph whose figures alone moved is now shown.** In NVIDIA's risk factors: revenue from sales outside the United States, 53% in one report and 31% in the next, in a sentence whose words did not change.
- **Two faults in the older pipeline.** A run whose meaning check failed still said "complete"; it is partial now. And "operating expenses grew 3%" passed the number check against a source saying "(3)%", a hole opened by the fix for the first referee's finding. Each of the referee's demonstrations became a test that failed first.
- **A wrong number in the README.** The speed change was "well under 1% of a live run"; the project's own measurements give about 3%.
- **The threshold, read on two more companies** by the session, with a new option that prints the pairs to read. Apple: 10 of 11 pairs just above it are one paragraph rewritten, and all 5 just below it are too. Coca-Cola: 7 of 10 above, and 4 of 9 below. In a discussion of results built on templates, about three in ten borderline pairs join two different paragraphs. The threshold stays; a person's reading is still owed.
- Rejected, with reasons: a minimum amount of evidence for "complete", a check of direction in the number check, and showing moved figures inside tables.

**A second pass the same day: a fifth review, and versions 8 and 9**

After the first pass I asked the session to keep going: another round of building and refining, with the hand-ins and logs kept up to date. This is that round, also on 17 November.

- **A fifth blind review**, of version 7, against the Week 6A checklist, because the page had gained two views since it was last read that way. Twelve findings, unedited in `Capstone/evidence_desk/docs/reviews/review-5-message-interface-tests.md`; the decisions are in `Homework/Week 9/W9L1.md`. Built in: a first screen that states the one takeaway; "Refused" for an input, so that "Rejected" is only my decision; a legend that says what a dashed border really means; a mark for what no person has checked; a tripwire stage for the filing comparison; a page test that refuses a stale dump.
- **Version 8: what changed that bears on each claim.** For each claim of a run, the paragraphs that changed in the filings it read, ranked by the words they share with the claim. No model. On the recorded example the first paragraph under "Gross margin is expanding" is one the newest annual report added: "Gross margin decreased in fiscal year 2026".
- **Does the second model reject what does not fit?** The reviewer's wrong program quotes any real sentence as support. An evaluation now plants 152 such cases, real quotes under statements they do not belong to. The second model rejected 149, called 3 "partly" and agreed with none; on the same findings with their own quotes it had rejected 1 of 76.
- **Version 9: segments, geographies and customers.** Read from each filing's own tagged facts, which the figures shown so far cannot give. NVIDIA's annual report: Data Center revenue $193,737 million, up 68.2%; the geography member labelled "China Including Hong Kong" $19,677 million, down 21.4%; one customer at 22% of revenue. Run on sixteen filings of eight companies; every breakdown adds up to the filing's tagged total.

**What went wrong in the second pass**

- **The first live output of the claim list wasted two of five places.** NVIDIA prints the same paragraph under two Items, and each copy was listed. Every test passed; it showed only when the feature was run on the real filings and read. Fixed with a test written first.
- **Real filings broke the breakdowns five times**: members that are sums of other members, two splits of one total, segments reconciled through eliminations, a customer share that leaked into the wrong table, and a 16-week quarter that was dropped without a word. Each was found by running the eight companies and looking, as the agent notes ask.
- **A screenshot that was never rewritten.** Headless Chromium exits 0 when it fails on a very tall page and writes nothing. One committed screenshot had been stale since version 6. The target now caps the height and fails if a file was not written anew.
- **The session pulled a make target out from under a running agent** while setting version 8 apart from version 9, and that agent's last check could not run. It was run afterwards.
- **A relabelled count that was not true.** The page's count of quotes that failed the check was renamed "not found" while fixing another label; a quote can also fail for its length. Caught on reading the report, before it was committed.
- **The evaluation measures the easy case.** A swapped quote is usually about another topic. Whether the second model catches a quote on the right topic that does not carry the statement is still not known.

**The second pass, continued: a third referee, and version 10**

- **A third hostile reading**, of version 9, which nobody but its builders had read: the `referee` agent again, another model, read-only, from a checkout with my notes, the earlier reviews and both triages removed. Nine findings, unedited in `Capstone/evidence_desk/docs/reviews/referee-3-version-9.md`. Each is accepted with a fix, accepted as a stated limit, or rejected with a reason in `docs/referee-3-triage.md`; the table is in `Homework/Week 9/W9L2.md`.
- **Sentences that said more than the code.** The plan's own "when the evidence is thin the brief says partial"; "shares two words with the claim", where the rule also counts the run's search queries; "the filings this run read", where the earlier filing of each pair never was; a README table with labels the tool does not print. All corrected, on the page too.
- **Two false passes in the number check**, each now a test that failed first: "revenue grew 3% while gross margin fell" against a source saying "(3)%", and "$46 million" against "46 customers".
- **Three faults a filing could reach**: one broken comparison failed the whole request for a run's changes; a second tagged total was taken without a word; and an `assert` stopped the breakdown reader. The referee wrote that it "constructed no input" for the last; the session constructed one.
- **Version 10: a finding can cite the tagged figures.** A run can ask to be offered the segment, product, geography and customer figures of the newest annual and quarterly report it read, at most 40. Off by default, because they change the engine's prompt and a recorded answer belongs to its prompt. Built by a Claude Opus session from a written brief; the page by another.
- **Two recordings to see what it changes**, made the same day by the same stand-in models, each told only to answer: the example without the option and with it. Without the option and without any reminder of the rules, 18 of 18 findings verified and no number went unmatched, which answers the referee's point that the first recording was an upper bound. With the option, five verified findings cite a tagged figure and citations of figures go from 8 to 20: Data Center revenue under the growth claim, customers' shares under the concentration claim, revenue tagged for China under the claim about export controls.
- **A command that prints each company's figures**, `make figures`, written to check one fix on eight companies. It found two more faults on its first run (below).

**What went wrong in this part**

- **Testing on few companies, for the third time, and this time in the oldest part of the tool.** The reported figures have been checked against published values for Apple, Microsoft and NVIDIA since version 3, and nothing looked at the others. Costco's year is in weeks, so its fourth quarter was never derived and the newest quarter shown was three months stale. Amazon tags cash flows for the twelve months to each quarter end, which were taken for fiscal years, so its real annual figures were never offered to a run. JPMorgan had no revenue figure at all. The referee suspected the first from reading; the other two showed the first time anyone printed the figures side by side. Each is fixed from a failing test, and after each fix only that company's lines moved.
- **A fix with a cost downstream.** Costco's figures changed, so 25 recorded answers no longer matched their prompts: five assessments and four meaning checks of the golden set, and sixteen planted-mismatch checks. All were answered again. Verdict agreement stayed at 20 of 24, with one case moving each way; planted mismatches rejected went from 149 to 150 of 152.
- **The number check withheld a true finding.** A stand-in wrote "at fiscal year-end 2026" and the check read 2026 as a quantity nothing cited. Only a recording made without reminders showed it. Fixed with the statement itself as a test.
- **A planted fault passed every unit test of the new module.** Offering a customer's share of 0.22 as 0.22% failed nothing in the feature's own tests; only the replay of the recording caught it. The unit test was added and seen failing.
- **The new sample told the reader its answers came from another recording.** The note was a fixed sentence. Found by reading the first screenshot; a test now holds each sample to the recording it was made from.
- **One check that checked nothing.** A script meant to switch a rule off before a test run stopped on an error and changed nothing, so the run passed and proved nothing. It was noticed from the output and done again; the tests then failed as they should.
- **What the comparison cannot say.** The verdict on one claim differs between the recording with tagged figures and the one without, and no finding under that claim cites a tagged figure. With one answer per prompt, nothing here shows that the option changes a verdict.
- **A year in a statement is still not checked** against its evidence. The referee is right that it is the commonest error in this kind of work. It is the next milestone, not built.

**Status**

Version 10. The gate from a fresh clone: 1,361 offline tests, the smoke test, 142 assertions on the rendered page, in 34 s. Ten tags; versions 2 to 10 were all built on 17 November. What that does not mean:

- No person has read the thirty golden cases, the code, a filing comparison, a list of changes under a claim, or a breakdown table against the printed one.
- The model path has not run through the API since October: both keys were refused again on 17 November, and every model answer here is a recording made by a stand-in.
- A finding can cite the tagged figures, on NVIDIA only and in recordings only. A finding that rests on figures alone is checked for its numbers and read by a second model, and by nothing else.
- The reported figures are checked against published values for three companies, and were wrong for three of the other five until this afternoon.
- No colleague has reviewed this, and my reviews of colleagues are still owed.
- The link that opens a filing at a passage has never been clicked in a real browser.

**To the draft, due 30 November**

A proposed order, mine to change. The outline is `Capstone/evidence_desk/docs/draft-outline.md`.

1. Read the thirty golden cases and correct them; re-run `make eval`. Every evaluation number depends on this. `Capstone/evidence_desk/eval/golden-reading.md` lays them out with links into the filings, starting with the four where the tool and the expected stance disagree.
2. Rotate the API key that was pasted into a conversation; get credit; record the cassettes again through the API.
3. Use the tool on a thesis of my own and write down where it was wrong.
4. Read five reworded pairs and five added paragraphs for a company other than NVIDIA, and say whether the classes hold.
5. Read the five changed paragraphs listed under each claim of the example, and say for each whether it bears on the claim. Hold one breakdown table for a company other than NVIDIA against the table the filing prints, and one quarter of `make figures` for Costco, Amazon and JPMorgan against the filing.
6. Ask a colleague to review it, and review theirs.
7. Decide on the check of periods (milestone 11 in the plan): build it and measure its false alarms, or leave it as a stated limit.
8. Write the draft from the outline, with the results table as it then stands.

**Takeaway**

Three, from one day. Everything that passed on NVIDIA passed. The failure was one command away on a different company, and the instruction to run that command was already written down. A rule in a file did not get it run until the documents had already been written around one company.

And 1,094 tests passed over a table whose columns did not count the same thing, because each test checked that a number was what the code computed and none asked what its heading claimed. A reader with no tool found it by reading one function beside one table.

And in the second pass each new feature's first fault showed in its first real output, not in its tests: a duplicated paragraph, a dropped quarter. Running the thing on real filings and reading what comes out is a check of its own kind, and the cheapest one here.

A fourth, from the end of the day. The oldest figures in the tool had been wrong for three companies of eight since version 3, under an answer key that covered the other three. An answer key says the checked values are right; it says nothing about the rows nobody keyed. Printing every company's figures side by side took one small command, and it had not been written because nothing was failing.
