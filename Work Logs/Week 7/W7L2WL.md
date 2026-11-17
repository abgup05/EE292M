# EE292M Work Log

## Week 7B: Curate, Test, Repeat (lecture of 4 November 2026)

*This log is drafted by the Claude Code session that did the work; the decisions are mine to check.*

**The check-in**

- Written at `Capstone/evidence_desk/docs/check-in.md`, with a pointer at `docs/check-in.md`. Its first paragraph says how the work was done.

**The new version, tag `capstone-v4`: Monday's feedback, finding by finding**

- **F1.** The speed note now starts by saying the offline profile is not a real run. Measured the live path: 1.01 s cold, 0.38 s with the filings cached.
- **F2.** Benchmarked the header cut over 20 alternating pairs: a median of 28.8 ms saved, faster in 18 of 20. Real, and under 1% of a live run.
- **F3.** Timed every stage. The unexplained quarter was 24 saves, each forced to disk. The reviewer had guessed the connection and the pragma; the measurement said the sync.
- **F4.** Reran the probe on eight companies against the one taken before the change: identical on all 14 filings.
- **F5.** Relabelled the concurrency result.
- **F6 to F10.** Redrew the system and rewrote the table of what cannot be rebuilt.
- **The suggestion.** Split storage into a backed-up record and a disposable cache, with `make backup` and `make restore-check`.

**New: decisions, saved theses, what moved**

- A reader can accept or reject each finding; a second verdict follows from what they accepted.
- A thesis can be saved and run again; the two newest runs are compared.
- `make live-walk` drives the running app through all of it on live filings. It passed.

**The hands-on**

- Curated `AGENTS.md`: a section of what an agent could not have found, drafted from this sprint's corrections.
- Turned the review procedure into a skill, `/blind-review`.
- Tested it in fifteen fresh sessions. It fires on three of three phrasings and stays quiet on a near miss. It did not improve the result: 5 of 5 good with it, 5 of 5 without, 5 of 5 in a bare checkout, because the same steps were also in a README and the agent found them.
- Acted on that: the procedure now lives only in the skill.

**What went wrong**

- Both controls in the skill test were contaminated. With skills disabled, the sessions read the skill's file from disk; from a bare checkout they went and found the main one. A clean control needs a machine that does not have the repository on it.
- The storage split left the API handing each run a cache that was thrown away. Caught at integration with a failing test first.

**Status**

Version 4. `make verify` green from a fresh clone: 805 offline tests, smoke, 33 page assertions. The live walk and the restore check pass. Retrieval is measured, and it is the weakest part.

**Takeaway**

The skill test was expected to show the skill helping, and it showed the documentation was already doing the job. Its useful output was a deletion.
