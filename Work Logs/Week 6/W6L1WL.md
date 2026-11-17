# EE292M Work Log

## Week 6A: Challenge Builds Trust (lecture of 26 October 2026)

*Work done on 17 November 2026, in the catch-up sprint. This log is drafted by the Claude Code session that did the work; the decisions are mine to check.*

**The review session (Week 6A homework)**

- Had `capstone-v2` reviewed blind by Claude Sonnet from a clean checkout of the tag, against the session's four items: the message, the interface, the tests, time and limits. Twelve findings, five wrong programs, one tripwire specification. Kept unedited in `Capstone/evidence_desk/docs/reviews/review-2-message-interface-tests.md`; decisions in `Homework/Week 6/W6L1.md`.
- The reviewer could repeat the first screen's message word for word, and then said of the result screen that "something went wrong and nothing was concluded". The sample record is the run where the model was refused for lack of credit.
- Its first finding: the page says a verdict is computed from quotes checked word for word, when the check only proves a quote exists. The stance is the model's reading.

**The hands-on: a tripwire in my own tests**

- Asked what wrong program would still pass. The reviewer gave five specific edits that leave all 385 tests green: fewer passages per claim, a biased prompt, a locator from the wrong passage, swapped glyphs, the older annual report.
- There is no tripwire. Every test checks one value; nothing records a whole run.

**The reviewer panel**

- The lecture's panel is several reviewers, each with one goal, told to prove the code wrong. So far I have used one reviewer per version with the session's checklist. A second reviewer with a different brief (a hostile referee) is planned for Week 8.

**Status**

Version 2 reviewed. Twelve findings accepted, one answered in the README. Nothing built yet for this session.

**Takeaway**

Asking "what wrong program would pass?" was more useful than asking "what is not tested?". The second question gets a list of files. The first got five edits I could make in a minute, each of which would ship.
