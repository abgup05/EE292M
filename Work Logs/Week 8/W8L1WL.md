# EE292M Work Log

## Week 8A: Know What You Know, and What You Don't (lecture of 9 November 2026)

*This log is drafted by the Claude Code session that did the work; the decisions are mine to check.*

**The hands-on: safety nets, written down**

- Copies, keys and ports, each read by a command on this laptop (`Capstone/evidence_desk/docs/safety-nets.md`). The code has two copies. The record of runs and decisions has one disk. Nothing is offline, and there is no Time Machine destination.
- Two things listen on all interfaces that are not this project's. A GitHub token with write access to every repository sits behind every agent session.
- Ten layers that catch a wrong result, each with its hole. Three things get past all of them: a wrong stance on a real quote, a passage retrieval never offered, and reviewers of the same model family as the builder.
- Added a settings file with a short deny list.

**The hands-on: retrieval by hand**

- Traced one golden case. The claim says "buyers" and "slice of sales"; the passage says "customers" and "concentrated". No shared content word, so keyword ranking put it outside the top fifty. With the planner's queries it ranked seventh.

**Retrieval and generation, scored apart (milestone 5, in progress)**

- With model-written queries the passage that must come back is in the top eight for 18 of 24 answerable cases, against 7 with the claim's own words.
- Generation on the same thirty cases: the verdict agrees with the expected stance in 17 of 24, with no case where "supports" came back "challenged" or the reverse; all 6 unanswerable claims were refused; 81 of 82 quotes verified; the number check withheld two findings.
- The model answers were recorded from a stand-in with a minimal wrapper. The expected stances are a model's reading until I have read the cases.

**The review session (Week 8A homework)**

- Had the version reviewed blind by Claude Sonnet against the session's five items. Twelve findings, unedited in `Capstone/evidence_desk/docs/reviews/review-4-check-in-safety.md`; decisions in `Homework/Week 8/W8L1.md`.
- The ones that changed something: the live walk could pass without a judged run; the check-in left out five things the repository shows; the settings file was called enforcement and is not; the skill's blindness was only words.
- Built in: the walk fails unless judged; the check-in is corrected; the review checkout no longer contains my notes; the plan shows each milestone's status; the root Makefile forwards every target.

**Status**

Version 4 reviewed. Eight findings built in, four answered in the README.

**Takeaway**

The check-in said "live walk: PASS", and the walk would have printed that for a run with no verdict in it. A check that cannot fail is the same hole as a count that survives a failure upstream, one level up.
