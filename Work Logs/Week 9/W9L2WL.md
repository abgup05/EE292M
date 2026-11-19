# EE292M Work Log

## Week 9B (session of 18 November 2026)

*This log is drafted by the Claude Code session that did the work; the decisions are mine to check. Nothing here is about the lecture: its slides are not in the repository.*

**The new version, tag `capstone-v6`: what changed between two filings**

- The last milestone of the plan. For one ticker it compares the latest annual report with the one before it (or the latest quarterly report with the previous one), Item by Item. Each paragraph of the later filing is unchanged, changed only in its numbers, reworded, or added; each paragraph of the earlier one with no counterpart is removed.
- Every listed paragraph is an exact span of the stored text with a link into its own filing. A reworded pair shows its changed words: added words underlined, removed words struck through.
- Three ways in: `make changes ARGS="NVDA --form 10-K"`, the route `GET /api/companies/{ticker}/changes`, and a third action on the page beside the thesis and the reported figures. `?sample=changes` shows a recorded comparison without the network.
- No model is involved in this feature.

**Measured, on filings fetched live**

| Annual reports, paragraphs | Unchanged | Numbers only | Reworded | Added | Removed |
| --- | ---: | ---: | ---: | ---: | ---: |
| NVIDIA, fiscal 2026 against fiscal 2025 | 251 | 60 | 218 | 133 | 132 |
| of which Item 1A, Risk Factors | 124 | 1 | 51 | 34 | 22 |

*This table first read 606, 417 and 139 in its first two columns. Those counted every line, table rows included, beside three columns that counted paragraphs only. A referee found it later (below); the numbers above are the corrected ones.*

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

**A second pass: a fifth review, and versions 8 and 9**

After the first pass I asked the session to keep going: another round of building and refining, with the hand-ins and logs kept up to date. This is that round.

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

**The second pass, to its end: a sixth review, and version 11**

- **A sixth blind review**, of version 10, against the Week 7A checklist: speed, the system, what cannot be rebuilt, one boundary. The system had not been read that way since version 3. Nine findings and a suggestion, unedited in `Capstone/evidence_desk/docs/reviews/review-6-speed-system.md`; the decisions are in `Homework/Week 9/W9L2.md`.
- **The restore check could not have failed on the case it exists for.** It compared runs by their ids and skipped, on both sides, any decision or thesis that no longer parsed, so a backup and a record that were equally unreadable agreed. It now compares every stored record as text and fails, by name, on one this version cannot read. On the real record: 35 runs, 18 decisions, 9 theses, all readable.
- **Two writers, run for the first time.** The README draws the app and a one-off container writing one record at once. `make two-writers` does it on a scratch record: 2,000 writes from each side at the same time, no failed write, every row there.
- **A live run, timed inside the run.** Five runs under each of four conditions. About two thirds of a run without a key is waiting for EDGAR; parsing is a quarter of a cold run. The earlier note had inferred this by subtracting an offline profile from one live run.
- **Version 11: the year a finding names.** A check that reads the years in a verified finding's statement and looks for each in its quotes, its cited figures and the period of each filing it quotes. It reports and withholds nothing. Built by a Claude Opus session from a written contract; the page by another.
- **Measured both ways before it is believed.** On the golden set's findings: 34 years named, 34 found. With a wrong year planted in each of the 25 findings that name one: 21 flagged moved one year back, 24 two back, 25 three back, 23 one forward.

**What went wrong in this part**

- **The first timing showed a fault nobody had looked for.** A run that asked for tagged figures made two more requests to EDGAR than one that did not, every time: the cache keeps a filing's parsed text and the tags are in the HTML. Version 10 had been tagged that way. Fixed in two steps, each from a failing test: what is read from the tags is kept, and a first run reads them from the HTML it already has.
- **The period check let a date pass as a fiscal label.** "As of July 26, 2027" passed against the quarter ended 26 July 2026, because 2027 is that filing's fiscal year. No unit test had it; planting wrong years found it, four times in twenty-five.
- **It misses the commonest slip most.** A year moved one back passes whenever the quote itself prints that year, and a sentence that compares a quarter with the year before always does. Four of twenty-five. That is the wrong column of a table, and this check cannot see it.
- **No real period error has been seen.** The planted ones are mechanical: the same shift applied to every year. What a model's own slips look like is not known.
- **The first version of the check read its own sentences back** to find which years had failed, in the brief and in the replay. Changed in review: the record carries them as data.
- **A benchmark taken while other work ran did not agree with itself**: 32 ms saved on the parse and 52 ms on the whole run. Taken again on an idle machine, twice, the two agree at 30 and 34 ms. The disagreement was the only sign that the first was disturbed.
- **A false alarm of the session's own.** A test seemed to show one filing fetched again on every run, as if the cache were broken. The fake source used in that test leaves that filing out on purpose, and says so in a comment. Several scratch runs went to finding that the fault was in the test.
- **The build agent ran `python3` on the host twice**, against the rule that everything runs through make. Read-only, nothing installed; it said so in its report.
- **The record is still on one disk.** The review's suggestion, a copy of the decisions on a branch of their own, was not carried out: where the record goes is mine to decide.

**After version 11: a fourth referee, and version 11.1**

- **A fourth hostile reading**, of version 11: the referee agent again, Claude Sonnet 5.5, read-only, on a checkout without the logs, the hand-ins, the earlier reviews and the triage notes. Its brief had gained four lines naming the claims of versions 10 and 11. Eight findings, unedited in `Capstone/evidence_desk/docs/reviews/referee-4-version-11.md`; the decisions are in `Capstone/evidence_desk/docs/referee-4-triage.md` and in `Homework/Week 9/W9L2.md`.
- **Checked before anything was changed.** Each claim was read against the code first. Seven held. One, a restore-check output from an older version, was true of the tag and already fixed in the commit after it.
- **Two build sessions, test first, on files that do not overlap.** One on the gate and the years: a quote must be whole, years from 1900, a year before a financial noun, one wrong year planted beside right ones. One on the record and the brief: the restore check column by column, the Markdown brief's escaping, a count of filings in its verdict table, the wording of the changed-paragraph lists, and of a figure tagged twice the more precise. 81 new tests; 1,580 in all.
- **The two measurements were corrected and taken again.** The benchmark alternates the order within a pair and runs the garbage collector before each timed run: 25 to 27 ms saved, in 20 of 20 pairs, three times. The live timing uses one client with the company list already loaded: 5 requests cold and 2 warm.
- **Nothing recorded moved.** Both evaluations and the replays were run again: the same verdicts, the same 84 of 84 quotes, the same 34 of 34 years. The new measurement, one year moved beside right ones: 13 of 18 flagged.
- **Tagged `capstone-v11.1`** after the gate passed on a fresh clone: 1,580 tests, the smoke test, 156 page assertions, 38 s. The live walk passes, 33 checks. The restore check passes column by column on 40 runs, 20 decisions and 10 theses.

**What went wrong in this part**

- **Two published numbers were wrong.** "The header cut saves 34 ms" and "a live run makes 6 requests, two thirds of it waiting" both came from measurements written up with a spread and a repeat. The first always ran the cut first and let one run's garbage collection land in the next. The second counted a request the app makes once a day. 25 to 27 ms, and 5 requests.
- **The evidence was in the committed output.** The benchmark's twenty pairs sat in the repository beside the sentence they contradicted. A reader with no tools found the cycle of five by reading the columns.
- **A guess stated as a fact was false.** "Mostly rebuilding the three documents from the cached text" had never been timed. Timed, it is 1 ms. About 45 ms of every run is still attributed to nothing; the note says so now and guesses nothing.
- **Checking one false sentence found another.** "Each filing this run read is compared" was the referee's. "The run did not read the earlier filing" had been added after the third referee and is untrue for the quarterly pair: the recorded sample compares two quarterly reports that the run read.
- **The stricter quote rule broke three tests, and the tests were at fault.** Each built a quote by slicing a string at a fixed length, in the middle of a word. The golden set is validated with the gate's own search, so a cut excerpt there would have failed as well: all thirty cases still validate.
- **One wrong year beside a right one is caught less often than every year moved**: 13 of 18 against 21 of 25. The five misses are one case: the later of two consecutive years, moved back, lands on the earlier, and the statement names one year twice.
- **A build session started `python3` on the host again**, by mistake, and stopped it. The other wrote a log to `/tmp` and deleted it. Nothing was installed. The first rule was in its brief; the second, that nothing is written outside the repository, was in neither brief.

**After version 11.1: versions 12, 13 and 14**

Built by Claude Opus 5.5 sessions and merged by an orchestrating session, Claude Fable 5.2, as the commits' co-author lines say. Each version is in `Homework/Week 9/W9L2.md`, sections 12 to 14.

- **Version 12: the 8-Ks since the annual report.** It began with a fault: "buy NVDA because Jensen is gone" was answered from the annual report in which he is chief executive, and the 8-K of 12 November reporting his resignation was never read. Now every 8-K since the annual report is listed, up to eight are read and split into their items, a claim about leadership (or accounting, a deal, financing and a few more) is offered the matching sections, a finding that a later 8-K on its subject postdates is marked, and every run says how old its evidence is. All by rule, no model. Live on NVIDIA (`make events T=NVDA`): 12 8-Ks since the 10-K, 8 read, the 12 November one carrying Item 5.02.
- **Version 13: the page redesigned, and a standing watch.** The page became a research note in two themes, Paper and Terminal, leading with a status line, a tape of the record's figures, a board of verdicts and a time line of the filings and 8-Ks. A second process, the watcher, reads a watched thesis's company's filing index every fifteen minutes, decides by rule which claims a new filing bears on, and runs the thesis again or leaves the run waiting; an inbox says what came and why it matters or does not. On NVIDIA's 19 filings of the past year (`make watch-replay`), triage agreed with labels written beforehand on 12 of 19 and flagged 11 of the 13 labelled as bearing.
- **Version 14: dated facts, and claims as computed tests.** Every fact carries the date its filing was filed; a run can be as of a past date and reads only what was filed by then, shown on 414 dates of three companies against a payload with the later facts deleted. A claim such as "gross margin is expanding" compiles to a test computed from those facts, with its arithmetic and its outcome over five years of filings, and counts in the verdict only when the test explains every word of the claim. 28 of NVIDIA's 922 periods reported twice changed value in a later filing.
- **Three sets of claims written by another model** (Claude Sonnet 5.5), each committed before it was scored. Set A showed 11 wrong readings on its held-out half, which became the whole-sentence rule. Set B, scored once on the grammar alone, gave 5 right and 1 wrong of 80; its refusals became a catalogue of 39 more measures, five new forms, and a second model reader with the rule that two of three readers must agree. Set C was read once through the API by the grammar, Haiku 5.5 and Sonnet 5.5 (240 calls): 36 of 80 numeric claims counted, 33 of them judged right by Sonnet 5.5 shown only the judge's file.
- **Rule 3, after set C.** A flow against an amount must name its period, or it is not read: h063, "R&D spend passed $30 billion", had been read by both models as a quarter's.

**What went wrong in this part**

- **Real filings broke the 8-K splitter on its first run.** The live probe on eight companies (`make events-probe`) found 190 of 200 listed items: Coca-Cola writes "Item 9.01(d)." with the exhibit index under it, JPMorgan "Item 5.02(e)". NVIDIA's own opening sentences were cut after "Mr.". Each became a failing test, then 200 of 200.
- **A rule scored on what it was tuned on.** The claim categories scored 0.90 precision and 0.92 recall on 84 labelled claims, then 0.94 and 1.00 after a tuning pass on the same 84. The first is the fair one, and the labels were written by the model that wrote the rule.
- **A before and after not alternated.** Version 12's speed was measured on the old version and then on the new one, not in turn. The referee later named it, and it is still not measured again.
- **Triage that cannot tell one officer from another.** On NVIDIA's year, five false alarms were all Item 5.02, an officer who is not the chief executive, and the two misses, a $25 billion note issue and an $11.9 billion acquisition, were filed under Item 8.01. Not fixed: a fix fitted to these seven would be measured on them.
- **Two faults found by writing the examples, not by the tests.** A started run whose inbox item still said it waited, and a failed run whose item still said it ran. Each became an assertion that failed first.
- **The specimen page's note was empty from version 13 to version 14**: the page's code hid a view the specimen did not have.
- **The grammar on claims it had not seen.** On set A's held-out half it first read 15 of 40 numeric claims wrongly; on set B, with the whole-sentence rule, it read 6 of 80 at all. A wrong reading is worse than none, and the first answer to it was to refuse almost everything.
- **An answer key that was wrong.** The independent route for the golden computed claims gave NVIDIA's fiscal 2008 the wrong year labels; the route was fixed and that one case changed.
- **The API refused the readers' schema twice**, for 28 union-typed parameters and then for a grammar too large to compile, and one answer was cut off at 1,000 tokens. Found only by calling it.
- **A rule made after the measurement.** Rule 3 came after set C was read, so set C's score does not include it, four of my own labels now refuse, and none of set C's 240 recordings replays under the new prompt.
- **The gate's output was not kept** at versions 13 and 14, and twice the whole gate could not be run on a branch because another checkout's app held port 8766.

**After version 14: a fifth referee, and version 14.1**

- **A fifth hostile reading**, of version 14: the referee agent, Claude Sonnet 5.5, read-only, on a checkout without the logs, the hand-ins, the earlier reviews and the triage files. Its brief predated version 12, so it chose what to read. Thirteen findings, unedited in `Capstone/evidence_desk/docs/reviews/referee-5-version-14.md`; the decisions are in `Capstone/evidence_desk/docs/referee-5-triage.md` and in `Homework/Week 9/W9L2.md`, section 15.
- **Checked before anything was changed.** Each claim was read against the code at the tag. All thirteen held in substance; the first was half true, since the API had answered on 18 November and three older lines of the README said it never had.
- **Fixed, test first for all but one**: one section of the README on where every model answer came from; a template summary written again from the final verdicts, and a line written by code after a model's summary saying what the computed tests moved; a computed test that prints the comparison it made; who reads a computed test in each configuration; three wrong numbers the number check let through; a restore check that says BEHIND, exit 2, for a backup that is only behind the record.
- **Nothing recorded moved.** The examples and the page's samples were made again through their targets; every recording replays and the tripwire did not move.
- **The gate at version 14.1 from a fresh clone**, kept this time: 2,361 offline tests, the smoke test, 337 page assertions and 2 skipped, 149 s. The restore check on the real record: PASS, 43 runs, 20 decisions, 10 theses.

**What went wrong in this part**

- **The worst finding was about the documents.** Three lines of the README written on 17 November said the API had never answered. Credit was added on 18 November, live runs and set C went through the API, and the new results were written beside the old lines without rereading them. Two more sentences about 8-K passages were false the same way.
- **A choice applied where it had no reason.** The summariser is shown the findings' verdicts alone, so that recorded requests stay as recorded. The template summary followed the same order and needed no recording, and the committed example brief said "Passages found, not judged: 5" above three judged rows.
- **One fix came before its test.** The restore check's change was written first; its tests were then run against version 14's `backup.py`, put back for the purpose, and 2 of 24 failed. Two more tests, a history point's sides and a watch row changed with nothing dated after the backup, were written after their fixes and not seen failing. `docs/testing.md` says so.
- **A commit holds more than its message says.** The code of the brief's note on who read a computed test went into the commit for the summary (`2f68aea`), and its test into the next (`29af083`). Left as it is: published history is not rewritten.
- **The page is behind the backend.** It still labels the computed tests "Computed, no model", which is false when model readers are on. That is the page's to change.

**After version 14.1: versions 13.1 and 14.2, and every version live on the site**

This part began with three things I said after opening the page and the site: the page was janky, a long scroll through oddly shaped blocks; a run's output was a regurgitation of data with no analysis in it; and the site's banner said a live run needs the app running locally, which I wanted changed to the versions running there with the key. A fourth came when I saw the first plan for the analysis: it only read the company's own filings, and I wanted real financial and data analysis. Each is in `Homework/Week 9/W9L2.md`, sections 17 to 19. Built by agents and merged by an orchestrating session, Claude Fable 5.2, as the co-author lines say.

- **Version 13.1: the page as a workspace.** The claims once, in a rail; tabs in the centre; an inspector at the right; nothing scrolls but the panes. Built on version 14.1's page, then carried to version 13 as a layout-only release. Reviewed from screenshots by Claude instances that had not seen the page: the first verdict was "not yet professional" with 22 defects, which went back to the builder; the last was "Paper is close to professional; Terminal is not yet."
- **Version 14.2: an analysis on every run.** For each claim: the figures that bear on it and what follows from them, computed by code; corollaries a model proposes and code computes; odds that a "has stayed" claim keeps holding; base rates and peer ranks across SEC filers; a price derived from Form 13F tables, the multiples, and the growth the price needs. Then an argument a model writes per claim and for the thesis, each sentence audited by code against what it cites. The page opens on it, and a Method tab draws who did what in the run.
- **A reference pack.** The outside and market views read 3.8 MB of SEC data shipped inside the app, so they answer in about a second and need no fetch.
- **The site runs every version.** Fourteen versions behind one function, a guard in front of them because the key is public money, and the key set on the server without being printed.
- **Two live runs with everything on**, 19 November UTC, through the API: NVIDIA in 123 seconds, 101 of 105 analysis sentences passing the audit; Costco in 126 seconds, 85 of 92.
- **The gate from a fresh clone.** Version 13.1: 1,782 offline tests, the smoke test, 423 page assertions and 1 skipped. Version 14.2: 2,568 offline tests, the smoke test, 573 page assertions and 2 skipped.
- **A sixth hostile reading**, of version 14.2, by the referee agent on a checkout without the logs, the hand-ins and the earlier reviews. Its text is in `Capstone/evidence_desk/docs/reviews/referee-6-version-14.2.md` and the decisions in `Homework/Week 9/W9L2.md`, section 20.

**What went wrong in this part**

- **I changed builders halfway.** The analysis, the two views and the live site were begun by Claude Opus 5.5 agents. I did not trust the result and had them stopped; Claude Fable 5.2 agents took over each worktree with the instruction to assume nothing was verified. They found a made-up share price of $150 under the example's valuation, the company counted inside its own reference class, balances from 2018 in a 2026 enterprise value, a disagreement between two readers counted as an outcome, and a test suite that never finished because its client spun. None of these had been reported as open.
- **Every builder stopped at the plan gate.** `AGENTS.md` asks for a plan and my approval before work on more than one file. Each agent stopped and asked, and the orchestrating session approved under the standing instruction I had given it to decide and keep going. I did not read those plans. The rule did what it says; what approved the plans was a delegation, and the hand-in should not read as though I reviewed them.
- **The first real request for an argument failed three ways.** The API accepted the corollary request and refused the argument's answer format: "the compiled grammar is too large". Flattened so that a sentence appears once in the format, it was accepted and the answer was cut off at 10,000 tokens. Split into one request per claim and one for the thesis, one thesis answer was still cut off at 4,000 and got its own limit. No test could have shown any of this: the builders had no key, and a stand-in for the API accepts any format. 33 requests were sent to record two examples; the 14 of the last recording are the ones that stand.
- **The first live run on a second company was the first honest test of the two views.** On Costco, with nothing cached, both ran out of their time and the run had no base rate, no peer rank and no valuation; the run took 3 minutes 38 seconds. Everything before it had been run on NVIDIA's recorded fixtures. The reference pack and sending requests concurrently came out of that one run.
- **A peer claim had nothing to stand on.** "Costco is growing faster than its retail peers" compiled to no test and got no figure. It now gets the company's rank on revenue growth in its industry; it is still not computed as a test.
- **The audit cried wolf on years, and still does on thresholds.** A sentence citing an 8-K filed in 2026 was marked for writing "2026". Fixed: a year that is the year of a cited item's own date is carried by it. A sentence that restates its own claim's threshold is still marked, and the page's reviewers read that as a false alarm.
- **The deployed site told a visitor something false.** EDGAR refused the server its company list, a recorded list of five tickers stood in, and Costco was reported as not in SEC's list. The emulation had the same fault and its test never asked for a company outside the seed. The message is fixed. The cause is not: there is no contact string for EDGAR on the server, and I have not set one.
- **A gate was stopped by mistake, for the wrong reason.** The page builder's gate had made no progress in two hours and the orchestrating session stopped it as hung. It was not hung. Four test containers left by one of the stopped builders had each been using a whole processor for about eight hours, and the offline tests, four minutes on a quiet machine, were at 14% after 48. Stopping those four fixed it. Nothing had been watching what the stopped agents left running.
- **A network drop ended three agents at once**, mid-task. Each was resumed from where it stopped; one had just found the false message above and its notes on it were lost with the session's reply.
- **A builder delegated and waited.** The page builder handed the Analysis and Method tabs to a second agent, which produced nothing for an hour; the builder then did the work itself.
- **The last state of the page was not reviewed from outside.** Two rounds of outside review were answered; nobody but the builder read the screenshots after the final changes.

**Status at version 14.2**

Version 14.2, tags `capstone-v13.1` and `capstone-v14.2`, both merged to `main` and live at `/v13/` and `/v14/`. The gate from a fresh clone: 2,568 offline tests, the smoke test, 573 assertions on the rendered page and 2 skipped. `make restore-check` on the real record: PASS, 46 runs, 20 decisions, 10 theses. What that does not mean, beyond the list above, which still stands except where noted:

- No person has read the 197 sentences of the two live arguments against what they cite. The audit says each number and each source is real; it does not say the sentence follows.
- Every model in the analysis is a Claude model: Opus 5.5 proposes and argues, Haiku 5.5 and Sonnet 5.5 read, Haiku 5.5 checks meaning, and the referee is Sonnet 5.5.
- The price is a quarter-end close derived from 13F tables, never compared with an exchange, and up to four and a half months old.
- The reference pack is a day's snapshot. Nothing rebuilds it on a schedule.
- Online, only the seeded tickers can be relied on until EDGAR is given a contact string, and the caps on model runs are per server instance. The key has been pasted into a chat more than once and has not been rotated; no spend limit is set on it.
- The page was seen in headless Chromium only. Printing was not looked at after the last changes.
- The page now says who read each computed test (the last item of the earlier list), and a model-backed run has now been timed twice.

Next, in order: set a contact string for EDGAR on the server and test a company outside the seed there; rotate the key and set a spend limit; read one whole argument against its citations myself; have the audit accept a claim's own threshold; decide what the referee's findings change.

**Status at version 14.1**

Version 14.1. The gate from a fresh clone: 2,361 offline tests, the smoke test, 337 assertions on the rendered page and 2 skipped, in 149 s. Tags `capstone-v1` to `capstone-v14` and `capstone-v11.1`. What that does not mean:

- No person has read the thirty golden cases, the code, a filing comparison, a list of changes under a claim, or a breakdown table against the printed one; nor the 8-K category labels, the watch replay's labels, the 28 restatements or set C's readings. Every judge here is a Claude model.
- Credit was added on 18 November and the API answers: two live runs and 252 readings went through it. Every other model answer here is still a stand-in's recording of 17 November, and none has been recorded again through the API.
- A finding can cite the tagged figures, on NVIDIA only and in recordings only. A finding that rests on figures alone is checked for its numbers and read by a second model, and by nothing else.
- The reported figures are checked against published values for three companies, and were wrong for three of the other five until version 10.
- The period check reports and withholds nothing, has seen no real error, cannot see the wrong column of a table, and misses one wrong year beside a right one in 5 of 18 planted cases.
- About 45 ms of every live run is attributed to no stage, an older quarterly report a run read is compared with nothing, and a bare number in a quote still matches an amount a thousand, a million or a billion times its size.
- The record has no copy off this laptop; `make backup-status` now says so each time the app starts, and the restore check tells a backup that is behind from one that is wrong, except for a run finished after the backup, which still fails.
- No colleague has reviewed this, and my reviews of colleagues are still owed.
- The link that opens a filing at a passage has never been clicked in a real browser.
- The 8-Ks are read by rule: an 8-K's category is its item number, the exhibits are not read, and on NVIDIA's year the watch's triage gave five false alarms and two misses. The watcher has not run as a service for days.
- On claims nobody here wrote, the grammar alone reads 22 of 80 rightly (set B, now development material). With two model readers, 36 of 80 were counted on set C, and one model wrote, read and judged them. When both models read a claim the same wrong way, the wrong test counts.
- A model's summary can still say what the verdicts do not; the line after it names what moved, and nothing reads the prose.
- The page still labels the computed tests "Computed, no model".
- Version 14 is not timed, and no model-backed run has been.

**To the draft, due 30 November**

A proposed order, mine to change. The outline is `Capstone/evidence_desk/docs/draft-outline.md`.

1. Read the thirty golden cases and correct them; re-run `make eval`. Every evaluation number depends on this. `Capstone/evidence_desk/eval/golden-reading.md` lays them out with links into the filings, starting with the four where the tool and the expected stance disagree.
2. Credit was added on 18 November and the API answers. Still to do: rotate the API key that was pasted into a conversation (nothing in the repository says it has been), and record the cassettes again through the API, so that the golden set, the mismatches and the example stop resting on a stand-in's answers.
3. Use the tool on a thesis of my own and write down where it was wrong.
4. Read five reworded pairs and five added paragraphs for a company other than NVIDIA, and say whether the classes hold.
5. Read the five changed paragraphs listed under each claim of the example, and say for each whether it bears on the claim. Hold one breakdown table for a company other than NVIDIA against the table the filing prints, and one quarter of `make figures` for Costco, Amazon and JPMorgan against the filing.
6. Ask a colleague to review it, and review theirs.
7. Copy the record off this laptop: at least `backups/decisions-<UTC>.jsonl`, and say where.
8. Decide whether an unverified year should withhold a finding, after reading a second thesis with the check on. Milestone 15 (table rows that keep their column headings) is what the wrong-column case waits on.
9. Find what the 45 ms of every run that no stage covers is, or say in the draft that it is not known.
10. Read set C's 36 counted readings and the 43 claims no reader read, and judge them myself; a model wrote, read and judged them.
11. Decide whether the 8-K rules should tell the chief executive from other officers and read Item 8.01, and measure any change with `make event-categories` and a replay of a company other than NVIDIA.
12. Have the page say who read each computed test, as the brief now does.
13. Write the draft from the outline, with the results table as it then stands.

**Takeaway**

Three. Everything that passed on NVIDIA passed. The failure was one command away on a different company, and the instruction to run that command was already written down. A rule in a file did not get it run until the documents had already been written around one company.

And 1,094 tests passed over a table whose columns did not count the same thing, because each test checked that a number was what the code computed and none asked what its heading claimed. A reader with no tool found it by reading one function beside one table.

And in the second pass each new feature's first fault showed in its first real output, not in its tests: a duplicated paragraph, a dropped quarter. Running the thing on real filings and reading what comes out is a check of its own kind, and the cheapest one here.

A fourth, from the end of the day. The oldest figures in the tool had been wrong for three companies of eight since version 3, under an answer key that covered the other three. An answer key says the checked values are right; it says nothing about the rows nobody keyed. Printing every company's figures side by side took one small command, and it had not been written because nothing was failing.

And a fifth, about measuring. The period check passed every test written for it and every real finding it was shown. What told its strength and its one fault apart was making true statements wrong on purpose and counting. The same afternoon a restore check that had passed for seven versions turned out unable to fail, and a timing nobody had needed showed two requests too many. In all three the passing check was the less informative one.

And a sixth, about the measurements themselves. Two numbers were written up with twenty pairs, a spread and a repeat, and both were wrong in how they were taken: an order that never changed, a collector nobody had thought about, a request the app does not make. The pairs that showed it were committed beside the summary. Reporting a number carefully is not a check of how it was taken; that took a reader who was told to expect it to be wrong.

And a seventh, from version 14.1. A sentence that is true when written can become false without anyone touching it. The README said the API had never answered, and that was true until credit was added on 18 November; every new result after that was labelled with where its answers came from, and the old sentences beside them were never read again. The rule about where answers come from was kept one result at a time and broken in the whole. A fact that changes, like whether the API answers, belongs in one place that everything else points to.

And with it, a choice made for one reason and applied where the reason did not hold. The model's summary is shown the findings' verdicts alone so that its recordings still match. The template summary followed the same order, needed no recording, and contradicted the verdict table in the committed example. The reason for a choice is worth writing beside it, so that the next place it is copied to can be checked against the reason.

And an eighth, from versions 13.1 and 14.2. The things I asked for at the end were the only ones stated as a person would state them, and the gate said nothing about any of them. A page can pass 341 assertions and be unpleasant to use; a run can verify 17 of 20 findings and contain no analysis. Each needed a check of a kind the project did not have: someone looking at the page who had not built it, and a run on a company nobody had prepared for. The second one, a single Costco run, found in four minutes what two builders and 2,500 tests had not: the two new views had only ever been run on recorded NVIDIA data.

And a ninth, about replacing builders. Stopping the first agents left their mistakes in the tree and their processes on the machine. The mistakes were found because the agents that took over were told to trust nothing. The processes were not looked for by anyone, and four of them slowed every gate for eight hours until one was mistaken for a hang. Taking over work means taking over what it left running too.
