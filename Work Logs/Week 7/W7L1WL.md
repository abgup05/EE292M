# EE292M Work Log

## Week 7A: Design Your System for Your Problem (lecture of 2 November 2026)

*Work done on 17 November 2026, in the catch-up sprint. This log is drafted by the Claude Code session that did the work; the decisions are mine to check.*

**The hands-on: draw the system, then correct it**

- Gave a model the slide's prompt: draw this project as a system, each machine or container, each part on it, what each part owns, how code and data reach it; change no file.
- Marked three things wrong: GitHub was missing; the page's JavaScript was drawn inside the container; nothing showed that the database exists only on the laptop.
- Put the corrected drawing in `Capstone/evidence_desk/README.md` with a table of what cannot be rebuilt.

**The review session (Week 7A homework)**

- Had commit `1ecfcf1` reviewed blind by Claude Sonnet against the session's four items. Ten findings and one suggestion, unedited in `Capstone/evidence_desk/docs/reviews/review-3-speed-system.md`; decisions in `Homework/Week 7/W7L1.md`.
- Speed: the profile was of the offline run, which is not where a real run's time goes; the 8% did not follow from the stage table; a quarter of the run was a bucket called "Other".
- System: my corrected drawing was wrong in four more ways. One of them, the public pages a user can add, the model's first drawing had right and my correction removed.
- What cannot be rebuilt: "a filing never changes" is true and beside the point. The facts feed, the list of filings and my own parser all move, so no later run reproduces an earlier one.
- The suggestion: a disposable cache and a backed-up record. Taken.

**Also done between sessions**

- A golden set of 30 cases over five companies and a retrieval scorer (milestone 5, started early). First result: BM25 on the claim's own words finds the passage that matters in the top eight for 7 of 24 answerable cases. The claims are paraphrases and keyword matching misses them. The cases were drafted by a model and validated mechanically; I have not read them one by one.

**Status**

Version 3 reviewed. All ten findings accepted. The next version splits the database, adds decisions and backup, and re-measures the speed claims.

**Takeaway**

I corrected a drawing and made it worse in one place without noticing. Having drawn it myself, I would not have looked for what was missing; the reviewer checked each arrow against the compose file.
