# Cassettes: recorded model answers

A cassette is a directory of the Claude engine's requests, and the meaning checker's, and the
answers recorded for them.
Replaying one makes a model-backed run reproducible: the same filings and thesis give the same
prompts, the same prompts find the same answers, and the gate and verdict rule run unchanged on
them. It also gives a way to produce such a run when the Anthropic API cannot be called (this
project's account had no credit until 18 November): each prompt is saved in full and can be answered
elsewhere. Which recordings a stand-in answered and which the API answered is listed in
[`README.md`](../README.md#where-the-model-answers-came-from).

## Layout

    <cassette>/responses/<key>.json   one recorded answer
    <cassette>/pending/<key>.json     a request with no answer yet

`<key>` is the first 24 hex characters of the SHA-256 of the canonical JSON (sorted keys, no
whitespace, UTF-8) of `{step, system, user, schema}`; the output-token limit is not part of it.
A pending file holds `key`, `step`, `system`, `user`, `schema` and `how_to_answer`. A response
file is this envelope:

    {"key": "<key>", "step": "plan" | "assess" | "check" | "summarize" | "read" | "read_2" |
              "propose" | "analyse",
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
3. Run again. A full run takes up to four rounds of answers: the plan, then one assessment per
   claim, then one meaning check per claim with a verified finding (step `check`, see below),
   then the summary. Each step's prompt depends on the answers before it, so a request built on
   a missing answer is not saved; once all four rounds are answered the run replays end to end.
   A claim's check reads only that claim's assessment, but the summary reads the verdicts the
   checks decide, so the summary waits for every check.

The model readers (`engines/claim_reader.py`, off unless `EVIDENCE_DESK_CLAIM_READER` is `model`
or `models`) ask one `read` request per claim (and, with `models`, one `read_2` for the second
reader), from the same cassette as the engine, before the plan. The request holds only the claim,
the readers' system prompt and the reading schema, so `make eval ARGS='claim-readers ...'` and a run
ask the same request for the same claim and share answers. No later step depends on its answer, so
a pending read blocks nothing; that reader reads nothing for that run. With the readers off no read
request is made and every recorded request is unchanged. A change to the readers' prompt or to
`READING_SCHEMA` changes every read key: the answers recorded before it stay in the cassette but are
no longer replayed.

The meaning checker (`engines/checker.py`) answers from the same cassette and the same run as
the engine (`CassetteTransport.sibling`): a pending check blocks the summary, and a new plan
request starts a new run for both. Its system prompt is `CHECK_SYSTEM`; it is shown each
finding's statement, stance, verified excerpts and cited figures, never the engine's rationale
or confidence. A check that is pending leaves that claim's findings "unchecked" for this run.

With `EVIDENCE_DESK_CASSETTE=<dir>` the API and `--engine auto` use the cassette too; adding
`EVIDENCE_DESK_CASSETTE_RECORD=1` and `ANTHROPIC_API_KEY` sends missing requests to the API and
records the answers (`via` "the Anthropic API", `model` the configured model name: the engine's
`ANTHROPIC_MODEL`, or for a check `ANTHROPIC_CHECK_MODEL`, default `claude-haiku-5-5`).

The analysing model (`engines/analyser.py`, version 0.14.2, `docs/analysis.md`) asks, after the
summary: one `propose` request (corollaries for every claim), one `analyse` request per claim
(its argument, which reads the computed corollaries; several are sent at once) and one `conclude`
request (the thesis's argument, which reads the claims' audited arguments). Each is keyed by its
content like any other request, so a claim's answer is recorded and replayed apart from the
others'. Recording, they are recorded in the engine's cassette (`model` is
`ANTHROPIC_ANALYSIS_MODEL`, default the engine's model). Replaying, the cassette is **read-only**
for them: a missing answer is never written to `pending/`, so a cassette recorded before 0.14.2
still replays every other request, and the run records what the cassette does hold (the
corollaries; the argument of each claim it answers) with a note on what it lacks and one line in
its errors. `make record-analysis` adds the answers through the API to the example cassette and to
`demo/cassettes/analysis-example` (the analysis example of `docs/examples/analysis`, whose engine
is the extractive one, so that cassette holds nothing else): up to 7 requests each, 14 in all. It
prints the number first, sends only a request a cassette lacks and never more than `MAX_CALLS`
(default: all); see `docs/analysis.md`.

## The honesty rule

Every response records who produced it: `model` and `via`. A run built from a cassette says who
answered **the requests it used**, step by step, never the directory at large (since the fixes
after 14.2; the seventh referee's finding 3): `engine_detail` for the plan, the assessments and
the summary, `checker_detail` for the meaning checks, `claim_reader_detail` for each reader's
readings, `analysis.corollaries_by` for the proposal and `analysis.argument_detail` for the
argument. For example, on `demo/cassettes/nvda-example`, which holds a stand-in's 12 answers and
the API's 14: "replayed from cassette nvda-example: 6 of its 26 recorded answers used (analyse,
conclude), recorded via the Anthropic API with claude-opus-5-5, 2026-11-19". Until then each of
those lines described all 26 at once, so a replayed run could not say that the argument was the
API model's and the findings a stand-in's. A transport keeps the list of answers it gave
(`CassetteTransport.describe_used`); the description of the whole directory is still
`Cassette.describe()` and is what `make run ARGS='cassette <dir>'` prints. Two runs replaying one
cassette at the same time through one app are not told apart: each would name the other's
answers given meanwhile. Never edit an answer after recording it to
change a verdict; record a new cassette instead. A cassette holds no key and no header.

## The cassettes in this repository

| Cassette | What it holds |
| --- | --- |
| `demo/cassettes/nvda-example` | The first recording of the example thesis on the three recorded NVIDIA filings. Its stand-in was reminded of two of the engine's rules. `make replay`, `tests/test_replay.py` and the page's `?sample` use it |
| `demo/cassettes/nvda-example-plain` | The same prompts answered again with no reminder: the control |
| `demo/cassettes/nvda-example-tagged` | The example with `tagged_figures` on. The page's `?sample=run-tagged` |
| `eval/cassettes/golden` | The plans, assessments and meaning checks of the 30-case golden set |
| `eval/cassettes/mismatch` | The meaning check's answers to planted mismatches |
| `eval/cassettes/claim-readers` | Set C (`eval/claim-tests-foreign-c.json`) read once by the two model readers through the Anthropic API on 18 November 2026: 240 answers, `read` by `claude-haiku-5-5` and `read_2` by `claude-sonnet-5-5` (each envelope's `model` and `via`), under the prompt and schema of d35b279; the record of set C's score (`docs/claim-tests.md`) |

Each has, or is described in, a README that says who answered and what they were told. `tests/test_replay_tagged.py` replays the second and third.

## What a cassette does not prove

- It does not exercise the SDK call: a replay never reaches the API, so a change to the request
  shape is tested only by the stubbed-client tests and a live run.
- A replay is not a fresh model answer. It shows what one model said once, under these prompts;
  a new run against the API may differ. Answers written by hand through another channel are only
  as faithful as that channel, which is why `via` names it.
- A changed prompt, filing or thesis changes the key, so old answers stop matching and new
  requests become pending; nothing stale is replayed silently.
- A check answered by the same stand-in that answered the assessments is not an independent
  reading, whatever `model` the envelope names: the check is only as independent as the channel
  that answered it. Record who answered each check in `via` and `model`.
