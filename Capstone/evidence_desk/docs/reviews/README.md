# Reviews

Each file here is one review of a tagged version, kept as the reviewer wrote it. Decisions on the findings are recorded in the hand-in for that session (`Homework/`), and anything not built in gets one line, with the reason, in `Capstone/README.md`.

## How a review is run

There were no colleague review sessions for these hand-ins. Each review was done by a model that did not write the code, so that it could not agree with the author by construction:

1. **Pick the version.** A tag, so the review can be read against exactly what was reviewed.
2. **Pick a reviewer that did not write it.** The code is written by Claude Opus sessions directed by one planning session. The reviewer is a different model (Claude Sonnet) started in a fresh context. It is never shown the planning conversation.
3. **Give it only the work.** The repository at that tag and the session's checklist, quoted from the course slide. It is told not to read `Work Logs/`, `Homework/`, `Slides/` or the earlier reviews, so it cannot pick up the author's own account of the work.
4. **Read-only.** It may read and search; it may not edit, run the app or touch git.
5. **Ask for evidence.** Every finding names a file and a line the reviewer opened. No praise.
6. **Keep the text.** The review is saved unedited, with a header saying what was reviewed, by which model, and when.
7. **Triage every finding.** Build it in, or answer it in one line with the reason.

What this does not replace: a colleague who knows the field and can say whether the result is useful to a real analyst. A model reviewer checks the work against its own stated purpose; it does not know my purpose better than the README tells it.

## Index

| Review | Session | Version | Topic |
| --- | --- | --- | --- |
| [review-1-structure.md](review-1-structure.md) | Week 5A | `capstone-v1` | Messaging, organization, patterns and interfaces |
| [review-2-message-interface-tests.md](review-2-message-interface-tests.md) | Week 6A | `capstone-v2` | The message, the interface, the tests, time and limits |
| [review-3-speed-system.md](review-3-speed-system.md) | Week 7A | `capstone-v3` plus the system drawing (commit `1ecfcf1`) | Speed, the system, what cannot be rebuilt, one boundary |
