# Cassettes: recorded model answers

A cassette is a directory of the Claude engine's requests and the answers recorded for them.
Replaying one makes a model-backed run reproducible: the same filings and thesis give the same
prompts, the same prompts find the same answers, and the gate and verdict rule run unchanged on
them. It also gives a way to produce such a run when the Anthropic API cannot be called (this
project's account has no credit): each prompt is saved in full and can be answered elsewhere.

## Layout

    <cassette>/responses/<key>.json   one recorded answer
    <cassette>/pending/<key>.json     a request with no answer yet

`<key>` is the first 24 hex characters of the SHA-256 of the canonical JSON (sorted keys, no
whitespace, UTF-8) of `{step, system, user, schema}`; the output-token limit is not part of it.
A pending file holds `key`, `step`, `system`, `user`, `schema` and `how_to_answer`. A response
file is this envelope:

    {"key": "<key>", "step": "plan" | "assess" | "summarize",
     "via": "<how it was produced, e.g. the Anthropic API>",
     "model": "<the model that produced it>",
     "recorded_at": "<UTC ISO 8601, e.g. 2026-11-17T12:00:00+00:00>",
     "response": { ...the JSON object the model returned, satisfying `schema`... }}

## The answer loop

1. Run with the cassette: `make run ARGS='example --engine cassette --cassette cassettes/nvda'`.
   A request the cassette lacks is written to `pending/`, the step falls back for this run only,
   and the command exits 3 without writing any result file.
2. Answer each pending file: respond to its `system` and `user` prompt exactly as the model would,
   with one JSON object that satisfies its `schema`, and save the envelope above as
   `responses/<key>.json`. `make run ARGS='cassette cassettes/nvda'` lists what is pending.
3. Run again. A full run takes three rounds of answers: the plan, then one assessment per claim,
   then the summary. Each step's prompt depends on the answers before it, so a request built on
   a missing answer is not saved; once all three rounds are answered the run replays end to end.

With `EVIDENCE_DESK_CASSETTE=<dir>` the API and `--engine auto` use the cassette too; adding
`EVIDENCE_DESK_CASSETTE_RECORD=1` and `ANTHROPIC_API_KEY` sends missing requests to the API and
records the answers (`via` "the Anthropic API", `model` the configured model name).

## The honesty rule

Every response records who produced it: `model` and `via`. A run built from a cassette says so in
its `engine_detail`, for example "replayed from cassette nvda: 6 responses recorded via Claude
Code with claude-opus-5-5, 2026-11-17 to 2026-11-17". Never edit an answer after recording it to
change a verdict; record a new cassette instead. A cassette holds no key and no header.

## What a cassette does not prove

- It does not exercise the SDK call: a replay never reaches the API, so a change to the request
  shape is tested only by the stubbed-client tests and a live run.
- A replay is not a fresh model answer. It shows what one model said once, under these prompts;
  a new run against the API may differ. Answers written by hand through another channel are only
  as faithful as that channel, which is why `via` names it.
- A changed prompt, filing or thesis changes the key, so old answers stop matching and new
  requests become pending; nothing stale is replayed silently.
