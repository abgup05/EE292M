# Cassette: the NVIDIA example thesis

Recorded model answers for the example thesis (`src/app/services/examples.py`) run on the
three recorded NVIDIA filings and the recorded XBRL facts under `tests/fixtures/edgar/`.
`make replay` runs it; `tests/test_replay.py` asserts the result. The layout is described in
`docs/cassettes.md`.

## How these answers were produced

They did not come through the Anthropic API. On 17 November 2026 the API refused every call
from this project with "credit balance is too low". The engine's prompts were therefore
written out by the cassette as pending requests and answered by Claude Sonnet 5.5 running as
a Claude Code subagent, one fresh context per batch, in three rounds: the plan, then the five
claim assessments, then the summary. Each response file records this in its `model` and
`via` fields.

The subagent was given each request's system prompt, user prompt and JSON schema unchanged,
inside these instructions:

> You are standing in for a language-model API call. [...] Answer exactly as a careful,
> capable model would answer that system prompt and user prompt: ONE JSON object that
> satisfies the schema exactly. Follow the system prompt's rules to the letter. Use ONLY
> what is inside that prompt file. Do not read any other file in the repository, do not
> search, and do not use outside knowledge about the company. Judge honestly: if the
> passages challenge the claim or only give context, say so; do not lean toward supporting
> it. A quote must be copied character for character from one passage in the prompt, from
> within a single line of that passage. [...] Before writing each quote, re-read the
> passage and check the quote is an exact substring of it. Any number you write in a
> finding's statement must appear in one of that finding's quotes or in a figure it cites
> by id; do not compute new numbers.

## The meaning check's answers

Version 5 added a second-model check of meaning. Its five requests (one per claim) were answered the same way but by a different model, Claude Haiku 5.5, so that the checker is not the model that wrote the findings. The instructions around those five prompts were minimal: answer as the model would, as one JSON object that satisfies the schema, using only the prompt. No rule was repeated.

## What follows from that

- The answers are real model output to the engine's exact prompts, but the instructions
  around them repeat two of the engine's rules (exact quotes, no new numbers). A plain API
  call would not get that reminder, so **the share of quotes that verify in this recording
  is an upper bound** on what the API path would give.
- The JSON-schema enforcement of the API did not apply. A malformed answer is caught by the
  engine's own strict parsing instead.
- The SDK call itself (`AnthropicTransport`) is not exercised by a replay.
- A replay is a recording. If a prompt changes, the keys no longer match, the replay reports
  pending requests, and the cassette has to be recorded again and the new answers read.
