# Cassette: the NVIDIA example again, with nothing said to the stand-in but "answer"

The prompts are exactly those of [`../nvda-example`](../nvda-example/README.md): the same example thesis on the same three recorded NVIDIA filings, and the keys of the plan and of the five assessments are the same. The answers are new, recorded on 17 November 2026.

`make replay ARGS='--cassette demo/cassettes/nvda-example-plain'` replays it; `tests/test_replay_tagged.py` asserts the result.

## Why it exists

Two reasons.

1. **The first recording was an upper bound.** Its stand-in was reminded of two of the engine's rules (copy each quote exactly; write no number that is not in a quote or a cited figure). The third referee pointed out that the project's first row of results rested on that. This recording gives the stand-in no rule at all.
2. **A control.** [`../nvda-example-tagged`](../nvda-example-tagged/README.md) offers the engine the figures tagged in the filings. To see what that changes, the same prompts without those figures had to be answered on the same day, by the same models, in the same way.

## How the answers were produced

Not through the Anthropic API, which refused every call from this project for lack of credit (checked again on 17 November). For each pending request the cassette wrote, `python -m tests.cassette_prompts` wrote the system prompt, the user prompt and the schema to a text file. The key and the step were cut from the top of the file and it was given a neutral name. One fresh Claude Code subagent per request was given that one file and these instructions, in full:

> You are standing in for one language-model API call. The file [path] holds the call: a system prompt, a user prompt, and the JSON schema the answer must satisfy. Read that one file in full. Answer exactly as the model receiving that system prompt and user prompt would: one JSON object that satisfies the schema. Use only what is in that file: do not read any other file, do not search, do not run commands. Write the JSON object, and nothing else, to [path], then reply with the one word: done.

Claude Sonnet 5.5 answered the five assessments and the summary. Claude Haiku 5.5 answered the five meaning checks, so the checker is not the model that wrote the findings. Each answer was checked against its request's schema and put, as written, into the envelope the cassette reads (`key`, `step`, `via`, `model`, `recorded_at`, `response`). No answer was edited.

**The plan was not asked again.** Its prompt is identical to the first recording's (same key), so `responses/fd60c9be9c9bc28435bd93d4.json` is that recording's answer, with its original time. All three recordings therefore search the filings with the same queries.

## What it shows

| | First recording (stand-in reminded of two rules) | This one (no reminder) |
| --- | --- | --- |
| Findings proposed, verified, withheld | 18, 18, 0 | 18, 18, 0 |
| Excerpts verified word for word; quotes rejected | 18; 0 | 18; 0 |
| Numbers in statements checked; not found | 25; 0 | 22; 0 |
| Meaning check: supported, partly, not supported | 17, 1, 0 | 16, 2, 0 |
| Verdicts, claims 1 to 5 | supported, supported, mixed, mixed, mixed | supported, supported, supported, mixed, mixed |
| Status | complete | complete |

Both rows are `make replay` on the cassette named; the first is `demo/recorded-run-v5.json`.

Two things follow, and one does not.

- **Without the reminder every quote still verified and no number went unmatched.** On this one example the reminder made no measurable difference to the two things it was about.
- **The same prompt, answered twice, gave a different verdict on claim 3** (export controls): mixed in the first recording, supported here. Nothing else differed. So a difference of one verdict between two recordings is what asking again can do by itself.
- It does not follow that the API would behave the same. See below.

## What it does not show

- A stand-in is a Claude model inside an agent harness, with that harness's own system prompt and tools around these instructions. It is not the API call the engine makes.
- The API's JSON-schema enforcement did not apply; a malformed answer would have been caught by the engine's own parsing, and none was.
- One answer per prompt. Nothing here says how often a quote would fail to verify over many samples.
- `AnthropicTransport`, the SDK call itself, is not exercised by a replay.
