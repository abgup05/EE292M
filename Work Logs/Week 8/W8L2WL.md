# EE292M Work Log

## Week 8B: Decide What Enters the Context (lecture of 11 November 2026)

*Work done on 17 November 2026, in the catch-up sprint. This log is drafted by the Claude Code session that did the work; the decisions are mine to check.*

**The hands-on: a hostile referee**

- Defined the referee as an agent in `.claude/agents/referee.md`: another model, read-only tools, briefed to expect the work to be wrong and to attack the project's own claims. Started it by name in a fresh session.
- Ten findings, kept unedited in `Capstone/evidence_desk/docs/reviews/referee-1-version-4.md`. Three that no checklist review had found: a finding with no passage set a verdict; the number check read a finding's statement and not its reason; a quote could be shown under a section it did not come from.
- Triaged every finding in `Capstone/evidence_desk/docs/referee-triage.md`: 16 accepted with a fix, 5 rejected with a reason. Each fix began as the referee's own demonstration written as a test and seen failing.

**The new version, tag `capstone-v5`: Monday's review, finding by finding**

- **F1.** The safety-nets note now calls the settings file partial enforcement and says what gets past it.
- **F2.** A review checkout is now an export of the tag that does not contain my notes; the reviewer lists every file it opened.
- **F3.** The skill test says it has a ceiling; two more near misses; every run's score committed.
- **F4.** The live walk fails unless the run is judged, and says when its recording expires.
- **F5, F7.** The outputs the README cites are committed under `docs/evidence/`.
- **F6.** The check-in gained the five things it had left out.
- **F8.** The plan's milestone table has a status column.
- **F9, F10.** One line cut from `AGENTS.md`; the root Makefile forwards every target.
- **F11, F12.** Answered in `Capstone/README.md`, with the reason.

**New in this version**

- Retrieval scored on the golden set: the passage that must come back is in the top eight for 9 of 24 cases with the claim's own words and 18 of 24 with the planner's queries. Three other rankings were defined before measuring and none earned its place.
- Generation scored apart from retrieval: the verdict agrees with the expected stance in 20 of 24; 6 of 6 unanswerable claims refused; 84 of 84 quotes found.
- A second-model check of meaning, by a different model that is not shown the first one's reasoning. On the golden set it withheld 1 of 77 findings and changed no verdict.
- The answer key for the figures went from 14 published values to 28.

**What went wrong**

- The fix for the referee's worst finding did not change its own example. A finding that cites only figures now counts toward a verdict only if the second model agrees. On the referee's case the second model agreed. Two models of one family backed each other.
- The meaning check changed no verdict on the golden set. It may be that the findings are mostly right; it may be that the checker shares the engine's reading. With an answer key no person has read, the two cannot be told apart.
- A label that was to be changed turned out to be part of the model's prompt. Changing it would have invalidated every recorded answer, so the definition went into a note instead.
- A headless browser sent to sec.gov to check a link was refused as an undeclared automated tool. The link is still unverified.

**Status**

Version 5. The gate passes from a fresh clone. Milestone 5 is done with one caveat that matters: the golden set is still a model's reading.

**Takeaway**

The checklist reviews found what their checklists asked about. The referee found three faults in tested code, because the tests asserted the faulty behaviour on purpose. A test records what its author believed, and it took a reader with no stake in that belief to see it.
