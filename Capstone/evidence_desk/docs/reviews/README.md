# Reviews

Each file here is one review of a tagged version, kept as the reviewer wrote it. Decisions on the findings are recorded in the hand-in for that session (`Homework/`), and anything not built in gets one line, with the reason, in `Capstone/README.md`.

## How a review is run

There were no colleague review sessions for these hand-ins. Each review was done by a model that did not write the code, in a fresh context, read-only, from a clean checkout of the tag, with the session's checklist and nothing else: not the planning conversation, not the author's logs, not an earlier review. Its text is saved unedited.

The steps are in one place, the skill at `.claude/skills/blind-review/SKILL.md` (`/blind-review` in Claude Code), with the four session checklists beside it. They used to be listed here as well; a test of the skill showed that an agent follows whichever copy it finds, so there is now one ([`../skill-test.md`](../skill-test.md)).

What this does not replace: a colleague who knows the field and can say whether the result is useful to a real analyst. A model reviewer checks the work against its own stated purpose; it does not know my purpose better than the README tells it.

## How the referee is run

The referee is not a checklist review. It is the agent in `.claude/agents/referee.md`: another model, with Read, Grep and Glob only, told to expect the work to be wrong and to attack the claims the project makes about itself.

1. Make a worktree of the commit to be read: `git worktree add --detach .claude/worktrees/referee-<tag> <commit>`.
2. Delete from that checkout what the referee must not see: `Work Logs/`, `Homework/`, `Capstone/evidence_desk/docs/reviews/` and both triage files under `docs/`. Then `touch .claude/worktrees/referee-<tag>.started`.
3. From the root of that checkout: `make -s referee > <somewhere outside it>/referee.json`. The target starts a fresh headless session that uses the agent by name and returns its text; the `result` field is the report.
4. Check that nothing in the checkout is newer than the `.started` file and that every file the referee says it opened is inside the checkout. Save the text unedited under a header that says what was read, by which model, and what was removed. Triage every finding in a file of its own.
5. Remove the worktree.

The first two referee runs were started with that command typed directly, before the target existed; the third to the sixth used the target.

## Index

| Review | Session | Version | Topic |
| --- | --- | --- | --- |
| [review-1-structure.md](review-1-structure.md) | Week 5A | `capstone-v1` | Messaging, organization, patterns and interfaces |
| [review-2-message-interface-tests.md](review-2-message-interface-tests.md) | Week 6A | `capstone-v2` | The message, the interface, the tests, time and limits |
| [review-3-speed-system.md](review-3-speed-system.md) | Week 7A | `capstone-v3` plus the system drawing (commit `1ecfcf1`) | Speed, the system, what cannot be rebuilt, one boundary |
| [review-4-check-in-safety.md](review-4-check-in-safety.md) | Week 8A | `capstone-v4` plus the safety-nets note (commit `413efe9`) | The check-in, the agent notes, the skill, safety nets |
| [referee-1-version-4.md](referee-1-version-4.md) | Week 8B | `capstone-v4` plus the safety-nets note (commit `413efe9`) | A hostile referee: the project's own claims |
| [referee-2-version-6.md](referee-2-version-6.md) | before Week 9B | `capstone-v6` plus three commits without code (commit `a79cf92`) | A hostile referee again: the filing comparison's claims, and the older ones |
| [review-5-message-interface-tests.md](review-5-message-interface-tests.md) | before Week 9B | `capstone-v7` | The message, the interface, the tests, time and limits, on the page as it now stands |
| [referee-3-version-9.md](referee-3-version-9.md) | before Week 9B | `capstone-v9` | A hostile referee a third time: the changes under each claim, the tagged breakdowns, and the older claims again |
| [review-6-speed-system.md](review-6-speed-system.md) | before Week 9B | `capstone-v10` | Speed, the system, what cannot be rebuilt, one boundary, on the system as it now stands |
| [referee-4-version-11.md](referee-4-version-11.md) | before Week 9B | `capstone-v11` | A hostile referee a fourth time: findings that cite tagged figures, the period check, the restore check and the speed measurements, and the older claims again. Eight findings, each decided in [`../referee-4-triage.md`](../referee-4-triage.md) |
| [referee-5-version-14.md](referee-5-version-14.md) | before Week 9B | `capstone-v14` | A hostile referee a fifth time: where the model answers came from, the summary beside the computed verdicts, the computed tests' arithmetic and readers, the number check, the gate's and the restore check's evidence, and the older claims again. Thirteen findings, each decided in [`../referee-5-triage.md`](../referee-5-triage.md) |
| [referee-6-version-14.2.md](referee-6-version-14.2.md) | after Week 9B | `capstone-v14.2` | A hostile referee a sixth time. Its brief predates version 12 and it read the older checks, not the analysis 14.2 added: the quote gate at the edge of a unit, what a partly supported finding does to a verdict, the period check on a fiscal label, the speed and gate evidence. Eleven findings, each decided in [`../referee-6-triage.md`](../referee-6-triage.md); the four about documents fixed, seven open |
