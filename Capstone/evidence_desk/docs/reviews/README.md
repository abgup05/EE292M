# Reviews

Each file here is one review of a tagged version, kept as the reviewer wrote it. Decisions on the findings are recorded in the hand-in for that session (`Homework/`), and anything not built in gets one line, with the reason, in `Capstone/README.md`.

## How a review is run

There were no colleague review sessions for these hand-ins. Each review was done by a model that did not write the code, in a fresh context, read-only, from a clean checkout of the tag, with the session's checklist and nothing else: not the planning conversation, not the author's logs, not an earlier review. Its text is saved unedited.

The steps are in one place, the skill at `.claude/skills/blind-review/SKILL.md` (`/blind-review` in Claude Code), with the four session checklists beside it. They used to be listed here as well; a test of the skill showed that an agent follows whichever copy it finds, so there is now one ([`../skill-test.md`](../skill-test.md)).

What this does not replace: a colleague who knows the field and can say whether the result is useful to a real analyst. A model reviewer checks the work against its own stated purpose; it does not know my purpose better than the README tells it.

## Index

| Review | Session | Version | Topic |
| --- | --- | --- | --- |
| [review-1-structure.md](review-1-structure.md) | Week 5A | `capstone-v1` | Messaging, organization, patterns and interfaces |
| [review-2-message-interface-tests.md](review-2-message-interface-tests.md) | Week 6A | `capstone-v2` | The message, the interface, the tests, time and limits |
| [review-3-speed-system.md](review-3-speed-system.md) | Week 7A | `capstone-v3` plus the system drawing (commit `1ecfcf1`) | Speed, the system, what cannot be rebuilt, one boundary |
| [review-4-check-in-safety.md](review-4-check-in-safety.md) | Week 8A | `capstone-v4` plus the safety-nets note (commit `413efe9`) | The check-in, the agent notes, the skill, safety nets |
| [referee-1-version-4.md](referee-1-version-4.md) | Week 8B | `capstone-v4` plus the safety-nets note (commit `413efe9`) | A hostile referee: the project's own claims |
| [referee-2-version-6.md](referee-2-version-6.md) | before Week 9B | `capstone-v6` plus three commits without code (commit `a79cf92`) | A hostile referee again: the filing comparison's claims, and the older ones |
