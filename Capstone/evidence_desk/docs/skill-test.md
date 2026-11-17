# Testing the `/blind-review` skill

*Run on 17 November 2026 for the Week 7B homework: "Test a skill like any claim: with it and without it, in a fresh session." Every session below was a fresh headless Claude Code session (`claude -p`, Claude Sonnet 5.5), started from the repository root unless stated. The score of every run, with its turn count, cost and first lines, is committed as [`skill-test-scores.json`](skill-test-scores.json); the full outputs were in `results/skill-test/`, which is not committed.*

The skill is `.claude/skills/blind-review/SKILL.md`. It was drafted by the agent from the review procedure it had already run three times with ad hoc prompts.

## 1. Does it fire when it should, and stay quiet when it should not?

Each request was sent to a fresh session and the first tool call was read from the session's event stream.

| Request | First tool call | Result |
| --- | --- | --- |
| "Get the Week 7 review done on capstone-v3: a blind review against the speed-system checklist." | `Skill(blind-review)` | fired |
| "I need an independent review of the capstone by a model that did not write it." | `Skill(blind-review)` | fired |
| "Run a foreign-model review of tag capstone-v2 and save what the reviewer says." | `Skill(blind-review)` | fired |
| Near miss: "Look over the diff I have staged and tell me if there are bugs before I commit." | `Skill(code-review)` | stayed quiet |
| Near miss: "Review my pull request before I merge it." | `Skill(code-review)` | stayed quiet |
| Near miss: "Summarise what review 2 said about the tests." | no skill; it read the file | stayed quiet |

Three of three, and quiet on three near misses. The last two near misses were added after review 4 asked for them. There is no baseline for this part: with skills disabled the tool that would fire does not exist.

## 2. Does it help?

**The task**, the same words in every session: prepare a blind review of tag `capstone-v3` against the speed-system checklist, do not start the reviewer and change no file; write out in full the brief you would give the reviewer, where you would save its output, and what you would check afterwards.

**The score.** Six things a good brief must contain, each checked by a pattern on the output: a reviewer that did not write the code; a clean checkout of the tag; the author's notes (`Work Logs/`, `Homework/`) forbidden; read-only; the session's checklist word for word; the output saved unedited under `docs/reviews/`. A run is good with five of six.

| Condition | Good runs | Criteria met (of 30) | Turns per run | Cost, five runs |
| --- | --- | --- | --- | --- |
| With the skill | 5 of 5 | 30 | 8, 8, 5, 5, 5 (mean 6.2) | $0.84 |
| Skills disabled, same directory | 5 of 5 | 30 | 7, 11, 8, 7, 7 (mean 8.0) | $0.77 |
| Skills disabled, in a checkout of `capstone-v1`, which has neither the skill nor any review notes | 5 of 5 | 29 | 12, 11, 13, 15, 9 (mean 12.0) | $0.87 |

**The skill did not improve the result.** Five of five with it, five of five without.

**Why, from reading the outputs.** Neither control was clean. With skills disabled, the sessions still found the skill's file on disk and read it; one said so in its first line: "I only read the `blind-review` skill, its checklists and `docs/reviews/README.md`". In the `capstone-v1` checkout they went looking for the tag they were asked about, found the main checkout beside them, and followed `docs/reviews/README.md`, which described the same seven steps. One of those five could not find the checklist text and left a marked slot for it; that is the one criterion lost.

**What the skill does change** is how much looking the agent does: 6.2 turns on average with it, 8.0 without it in the same directory, 12.0 from the checkout that had to search. It did not make the runs cheaper. Five runs a side is too few to say more than that.

## 3. What I take from it, and what changed

This is the lecture's rule, measured on my own repository: what helps is what the agent could not find. The procedure was written down twice, in the skill and in `docs/reviews/README.md`, and an agent finds a README without being told.

- **Changed:** the procedure now lives in one place. `docs/reviews/README.md` keeps why reviews are done this way and the index of reviews, and points to the skill for the steps. A procedure belongs in a skill; two copies would drift.
- **Kept:** the skill, for three reasons the test does support: it fires on the request without a search, it carries the four session checklists, and it is the place the next correction goes.
- **Not shown:** that the skill produces a better review. That would need the reviews themselves run and compared, which this test did not do; it compared the briefs only.

## 4. Limits of this test

- **The test has a ceiling.** Every run in every condition scored five or six of six, so it cannot separate the conditions. A harder task, or criteria that a brief can fail, would be needed to see a difference in either direction.
- The turn counts are five runs a side with no measure of spread.

- The scoring is six patterns on text. A brief can contain all six and still be a poor brief.
- All fifteen sessions used one model, Claude Sonnet 5.5. The skill's trigger was not tried on another model.
- The sessions ran while other agent sessions were editing the working tree, and the briefs mention those uncommitted files. That did not affect the six criteria.
