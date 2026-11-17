# Testing

`make test` runs every offline test (no network, no key); `make verify` adds the build, lint, the
smoke test against the container and the browser test. Each test states one truth and fails
when the result is wrong. Each test added in version 3 was seen failing once, on a planted wrong
program, before it was kept.

## Four levels, one test at each

| Level | Test | Catches | Cannot catch |
| --- | --- | --- | --- |
| Unit | `tests/test_gate.py::test_identity_holds_for_every_evidence_record` | a gate that shows the model's wording, a wrong offset, a lost quote | whether real filings parse, or whether the pipeline calls the gate at all |
| Integration | `tests/test_thesis_run.py::test_every_excerpt_is_an_exact_slice_of_the_stored_filing` | broken wiring from ingest to chunk, retrieval, gate and store, on a recorded 10-Q | EDGAR's live answers, what a model would say |
| System | `tests/test_api.py::test_each_invalid_request_is_refused_naming_its_field` (and `tests/smoke.py` on the container) | validation at the API boundary, status codes, the field named in each refusal | anything the browser draws (`uitests/test_dom.py` covers the page) |
| End to end | `tests/test_golden.py::test_the_example_run_matches_the_golden_record` | any change upstream that moves an answer of the whole example run | whether that answer is right: it proves only that nothing moved |

## The tripwire

`tests/golden_run.py` runs the example thesis with the deterministic extractive engine on the
three recorded NVIDIA filings and their recorded XBRL facts, with a clock that never moves. It
keeps no timestamp and no run id, and groups the record into stages in pipeline order:
`sources` (form, period, sections, characters, content hash, Item coverage), `limits` (every
constant), `prompts` (SHA-256 of each Claude system prompt and schema), `retrieval` (passages
indexed, per claim its queries and the passages offered, in order, with locators), `evidence`
(per excerpt: source, start, length, locator, SHA-256 of the text), `verdicts`, `coverage`
(status and every count) and `figures` (every metric of the newest quarter and year). A
`sha256` of the whole record closes it. `tests/golden/golden.json` is the checked-in copy.

**Reading a failure.** `make golden-check` names the first stage that differs, lists the later
ones, and shows the first differing entries. Every stage before the named one is proven
unchanged, so start there: `sources` moved means the parser; `limits` a constant; `retrieval`
chunking or ranking; `evidence` the gate or the extractive engine; `figures` the metrics.

**When a new baseline is legitimate.** Only when the change was meant to move exactly the
stages that moved. Run `make golden-baseline`, read `git diff tests/golden` stage by stage, and
commit it with the change that caused it. Adding `MAX_CONCURRENT_ASSESSMENTS` moved only
`limits`; that was checked by comparing the rest of the record, sha256 included, with the old
baseline before re-baselining. A diff in a stage the change should not touch is a bug, not a
baseline.

## Wrong programs, and the test that now fails on each

| Wrong program (review 2, plus one) | Fails | Seen failing as |
| --- | --- | --- |
| `limits.PASSAGES_PER_CLAIM` 8 → 2 | `tests/test_limits_contract.py`, `tests/test_golden.py` | "limits differ from the contract: PASSAGES_PER_CLAIM (2, 8)"; tripwire: first stage `limits`, then `retrieval`, `evidence`, `coverage` |
| "Prefer findings that support the claim" added to the assess prompt | `tests/test_golden.py`, `tests/test_replay.py` | tripwire: first stage `prompts`; replay: "5 request(s) pending: the prompts no longer match the cassette" |
| Evidence locator set to a fixed "Item 1A. Risk Factors" in the gate | `tests/test_thesis_run.py::test_every_locator_is_the_heading_of_the_section_holding_its_excerpt`, `tests/test_gate.py::test_verified_finding_carries_evidence_fields`, `tests/test_golden.py` | tripwire: first stage `evidence` |
| `VERDICT_GLYPH` ✓ and ✕ swapped, or `.v-supported` given the challenge colour | `uitests/test_dom.py::test_scorecard_pills_carry_label_glyph_and_class`, `::test_verdict_classes_use_their_own_colours` | checked with the browser test (`make uitest`), which reads the page's own JS and CSS |
| The older of two close 10-Ks selected | `tests/test_edgar.py::test_the_newest_of_two_close_annual_reports_is_chosen_with_only_later_quarterlies` | the 10-K of 2026-02-17 and the 10-Q between them taken |
| A statement saying 65% above a quote saying 56% | `tests/test_numcheck.py::test_the_wrong_program_65_percent_above_a_56_percent_quote_fails`, `tests/test_thesis_run.py::test_a_percentage_its_quote_does_not_contain_is_withheld_naming_the_number` | the finding is withheld, naming 65% |

The brittle tests the review named were rewritten: `test_gate.py::test_locate_scales_linearly_with_the_text`
compares eight times the text with the base text (best of five each; linear ≈ 8x, quadratic ≈ 64x,
bound 20x) instead of a wall-clock bound, and failed at 33.6x on a planted quadratic build.
`test_demo.py` asserts each fact of the Markdown (claim, label, counts), not whole lines.

## The replay test

`tests/test_replay.py` replays a copy of `demo/cassettes/nvda-example`: the Claude engine's own
prompts for the example on the recorded filings, answered once and recorded
(`docs/cassettes.md`). It fails, never skips, when a request is pending, when any engine step
fell back, when an excerpt is not an exact slice of its filing, or when a claim's verdict,
finding count or withheld count differs from `tests/golden/replay.json`.

It proves that the prompts are the ones that were answered, and that the gate and the verdict
rule turn those answers into the recorded verdicts. It does not prove what a model would say
today: it is a recording, not a fresh answer, and these answers came through a Claude Code
subagent, not the API. It does not exercise the SDK call; only the stubbed-client tests in
`tests/test_engine_claude.py` and a live run do.

## What no test here can see

- Whether a highlighted quote actually supports or challenges the claim. The gate proves the
  text exists, not what it means.
- Whether "Open in filing" scrolls to and highlights the quote on live sec.gov.
- Whether a newcomer understands the page; colour, contrast, dark mode and the phone layout.
- Live services: real model output quality, EDGAR rate limits and outages, billing and key
  failures. Only one other company's full filing (Costco's 10-K) is a fixture.
