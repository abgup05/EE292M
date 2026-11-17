# EE292M Work Log

## Week 9A (session of 16 November 2026)

*Work done on 17 November 2026, in the catch-up sprint. This log is drafted by the Claude Code session that did the work; the decisions are mine to check. I do not have this session's slides in the repository, so this log records the hand-in that was due and nothing about the lecture.*

**Due today: the new version that builds in last Monday's review, finding by finding**

- Handed in one day late as tag `capstone-v5`. The finding-by-finding account is in `Homework/Week 8/W8L2.md` and `Work Logs/Week 8/W8L2WL.md`: review 4's twelve findings (eight built in, four answered in the README) and the referee's ten (sixteen fixes, five rejections with reasons).

**Where the capstone stands against its plan**

| Milestone | Tag | State |
| --- | --- | --- |
| 1. A verified citation on one real page | `capstone-v1` | Done on 21 October |
| 2. Thesis claims against SEC filings | `capstone-v2` | Done |
| 3. Reported figures with an answer key; a number check; a tripwire | `capstone-v3` | Done |
| 4. Reviewer decisions, saved theses, backup | `capstone-v4` | Done |
| 5. Measured retrieval; a second-model check | `capstone-v5` | Done, on a golden set no person has read yet |
| 6. What changed between two filings | `capstone-v6` | The comparison is built and run on NVIDIA; the page for it is next |

Versions 2 to 5 were all built on 17 November. The tags mark the order of the work, not weeks of calendar time.

**What I have to do myself before the draft, in order**

1. Read the thirty golden cases and correct the expected stances. Until then every evaluation number here is agreement with a model.
2. Rotate the API key that was pasted into a conversation, and find out what is listening on port 8088.
3. Copy `backups/` somewhere that is not this laptop and run the restore check against that copy.
4. Click an "open in filing" link in a real browser.
5. Read the code, starting with `core/gate.py`, `core/numcheck.py` and `core/policy.py`: the three files the draft's claims rest on.
6. The reviews of colleagues' capstones that I owe for five sessions, and asking a colleague to review this one.
7. The lecture feedback for each session since 19 October, in my own words.

**Status**

Version 5 handed in. The draft is due on 30 November.

**Takeaway**

The list above is what a model session cannot do for me. All of it is reading, checking and talking to people.
