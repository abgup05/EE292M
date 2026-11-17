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
| End to end, offline | `tests/test_golden.py::test_the_example_run_matches_the_golden_record` | any change upstream that moves an answer of the whole example run | whether that answer is right: it proves only that nothing moved. It runs on recorded filings through a fake EDGAR with the deterministic engine, so it is a regression check of the whole pipeline, not a test of the live one. The only live end-to-end check is `make live-walk`, which needs EDGAR and is outside `make verify` |

## The tripwire

`tests/golden_run.py` runs the example thesis with the deterministic extractive engine on the
three recorded NVIDIA filings and their recorded XBRL facts, with a clock that never moves. It
keeps no timestamp and no run id, and groups the record into stages in pipeline order:
`sources` (form, period, sections, characters, content hash, Item coverage), `limits` (every
constant), `prompts` (SHA-256 of each Claude system prompt and schema), `retrieval` (passages
indexed, per claim its queries and the passages offered, in order, with locators), `evidence`
(per excerpt: source, start, length, locator, SHA-256 of the text), `verdicts`, `coverage`
(status and every count), `figures` (every metric of the newest quarter and year) and `changes`
(the comparison of the two newest quarterly reports with no list cut: per Item the nine counts,
the sub-headings in one filing only and a hash of every listed paragraph). A
`sha256` of the whole record closes it. `tests/golden/golden.json` is the checked-in copy.

**Reading a failure.** `make golden-check` names the first stage that differs, lists the later
ones, and shows the first differing entries. Every stage before the named one is proven
unchanged, so start there: `sources` moved means the parser; `limits` a constant; `retrieval`
chunking or ranking; `evidence` the gate or the extractive engine; `figures` the metrics;
`changes` what counts as a paragraph, the pairing, or a link.

**When a new baseline is legitimate.** Only when the change was meant to move exactly the
stages that moved. Run `make golden-baseline`, read `git diff tests/golden` stage by stage, and
commit it with the change that caused it. Adding `MAX_CONCURRENT_ASSESSMENTS` moved only
`limits`; that was checked by comparing the rest of the record, sha256 included, with the old
baseline before re-baselining. The fixes for the referee's findings on version 4 moved only
`coverage`, by four new counts (`filings_asked` 3, `quotes_found` 15, `findings_without_quote` 0,
`reasons_withheld` 0) with the status and every other count unchanged; that was checked the same
way. Adding the `changes` stage (review 5, finding 7) moved only that stage, which was new. A
diff in a stage the change should not touch is a bug, not a baseline.

The tripwire cannot tell a wrong change from an intended one; only the reading of the diff
does. There is no CI here to make that reading a condition of a merge, so it rests on the rule
in `AGENTS.md` and on whoever reviews the pull request.

## Wrong programs, and the test that now fails on each

| Wrong program (review 2, plus one) | Fails | Seen failing as |
| --- | --- | --- |
| `limits.PASSAGES_PER_CLAIM` 8 → 2 | `tests/test_limits_contract.py`, `tests/test_golden.py` | "limits differ from the contract: PASSAGES_PER_CLAIM (2, 8)"; tripwire: first stage `limits`, then `retrieval`, `evidence`, `coverage` |
| "Prefer findings that support the claim" added to the assess prompt | `tests/test_golden.py`, `tests/test_replay.py` | tripwire: first stage `prompts`; replay: "5 request(s) pending: the prompts no longer match the cassette" |
| Evidence locator set to a fixed "Item 1A. Risk Factors" in the gate | `tests/test_thesis_run.py::test_every_locator_is_the_heading_of_the_section_holding_its_excerpt`, `tests/test_gate.py::test_verified_finding_carries_evidence_fields`, `tests/test_golden.py` | tripwire: first stage `evidence` |
| `VERDICT_GLYPH` ✓ and ✕ swapped, or `.v-supported` given the challenge colour | `uitests/test_dom.py::test_scorecard_pills_carry_label_glyph_and_class`, `::test_verdict_classes_use_their_own_colours` | checked with the browser test (`make uitest`), which reads the page's own JS and CSS |
| The older of two close 10-Ks selected | `tests/test_edgar.py::test_the_newest_of_two_close_annual_reports_is_chosen_with_only_later_quarterlies` | the 10-K of 2026-02-17 and the 10-Q between them taken |
| A statement saying 65% above a quote saying 56% | `tests/test_numcheck.py::test_the_wrong_program_65_percent_above_a_56_percent_quote_fails`, `tests/test_thesis_run.py::test_a_percentage_its_quote_does_not_contain_is_withheld_naming_the_number` | the finding is withheld, naming 65% |

The referee's demonstrations on version 4 (`docs/reviews/referee-1-version-4.md`), each written
as a test and seen failing on the version 4 code before its fix:

| Wrong program (referee finding) | Fails | Seen failing as |
| --- | --- | --- |
| A finding with a reported figure and no passage counts as its stance (1) | `tests/test_policy.py::test_a_figure_only_challenge_moves_the_verdict_only_when_the_meaning_check_passed`, `tests/test_thesis_run.py::test_a_figure_only_challenge_moves_the_verdict_only_when_the_meaning_check_passed`, `tests/test_export.py::test_the_export_says_which_findings_were_counted_as_context` | "mixed" where two quoted findings support and an unchecked figure-only finding challenges; the record had no `counted_as` |
| A quote found anywhere in the source is accepted, under the named passage's locator (2a) | `tests/test_gate.py::test_a_quote_from_a_section_that_was_not_offered_is_rejected`, `::test_a_quote_from_another_offered_passage_is_kept_under_that_passages_locator`, `tests/test_thesis_run.py::test_every_locator_is_the_heading_of_the_section_holding_its_excerpt[quotes-across-passages]` | a sentence of an unoffered section kept; on the recorded 10-Q, an excerpt labelled with an MD&A sub-heading that does not hold it |
| A quote that includes a heading line the parser wrote (2b) | `tests/test_gate.py::test_a_quote_that_includes_a_heading_line_is_rejected` | the finding kept |
| A reason saying "Revenue grew 65%" above a 56% quote and an honest statement (3a) | `tests/test_gate.py::test_a_reason_citing_a_number_its_quotes_lack_is_withheld_and_the_finding_kept`, `tests/test_thesis_run.py::test_a_finding_whose_reason_cites_a_number_its_quote_lacks_keeps_its_place`, `::test_a_claims_commentary_citing_an_unverified_number_is_withheld`, `::test_unknowns_and_next_steps_citing_unverified_numbers_are_dropped` | the reason shown as written; the commentary, unknown and next step kept |
| A filing almost entirely outside numbered Items, or unreadable XBRL facts, leaves a run complete (4a) | `tests/test_thesis_run.py::test_a_filing_without_item_headings_can_no_longer_finish_complete`, `::test_unreadable_facts_leave_the_run_to_the_filings_and_say_so`, `tests/test_policy.py::test_a_filing_mostly_outside_item_headings_makes_the_run_partial`, `::test_unreadable_reported_figures_make_the_run_partial` | status "complete" |
| Three filings asked for, one listed, and the record does not say three were asked for (4b) | `tests/test_thesis_run.py::test_the_record_keeps_how_many_filings_were_asked_for` | no `filings_asked` on the record |
| A quote found word for word inside a withheld finding reads as not found (5) | `tests/test_gate.py::test_found_and_rejected_quotes_add_up_to_the_quotes_offered`, `tests/test_thesis_run.py::test_a_percentage_its_quote_does_not_contain_is_withheld_naming_the_number` (and `assert_quotes_add_up` in the pipeline tests) | no count of quotes found: "0 of 1 found, 0 rejected" |
| The filings-only provenance note on a run that read a page the user added (6a) | `tests/test_thesis_run.py::test_a_run_that_reads_a_page_you_added_says_so_in_its_provenance`, `tests/test_policy.py::test_the_provenance_note_says_when_a_page_you_added_was_read`, `tests/test_export.py::test_the_export_uses_the_runs_own_provenance_note` | the run kept no provenance of its own; the export printed the filings-only sentence |

The brittle tests the review named were rewritten: `test_gate.py::test_locate_scales_linearly_with_the_text`
compares eight times the text with the base text (best of five each; linear ≈ 8x, quadratic ≈ 64x,
bound 20x) instead of a wall-clock bound, and failed at 33.6x on a planted quadratic build.
`test_demo.py` asserts each fact of the Markdown (claim, label, counts), not whole lines.

## The filing comparison (version 6)

| Wrong program | Fails | Seen failing as |
| --- | --- | --- |
| `REWORD_THRESHOLD` 0.5 → 0.0 in `core/filing_diff.py`: every new paragraph pairs with some old one | 12 tests of `tests/test_filing_diff.py`, among them the plan's exit check `::test_a_planted_paragraph_change_is_reported_as_added_and_removed`, and 2 of `tests/test_filing_changes.py` | run on 17 November: 14 failed; restored, 37 passed |
| No route for the comparison | `tests/test_api.py::test_filing_changes_for_a_ticker` and the three beside it | written before the route: `assert 404 == 200` |
| The index's older pages are never read, so a company that files daily has "1 10-K filing(s)" | ten tests of `tests/test_edgar.py`, from `::test_an_earlier_filing_of_the_form_is_found_in_an_older_page_of_the_index` on | written before the change: 10 failed, 47 passed. The same failure live: `make changes ARGS="JPM --form 10-K"` ended with that message |
| A page name from the index used in a URL unchecked (another company's file, a path, another host) | `tests/test_edgar.py::test_an_older_page_with_an_unexpected_name_is_refused_and_never_requested` (six names) | failed with the ten above |
| A recorded comparison whose total, list, link or changed words disagree | `tests/test_sample_changes.py::test_each_kind_of_damage_to_the_record_is_reported` | the test itself damages a copy in eight ways and expects each to be reported; it runs with the suite |
| The page drawing the comparison wrongly (a count from the wrong field, a link into the wrong filing, added and removed words given the same mark, a cut list not saying so) | the nine tests of `uitests/test_changes_dom.py` | written after the view, so they first passed; the page was then broken in eight places and all nine failed, by the session that built it |

What these cannot see: whether a paragraph called "reworded" is the same paragraph to a reader. Nothing checks the classification against a person's reading.

And no test here reads a heading. All of the above passed while two of the five columns headed "paragraphs" counted every line, table rows included. The second referee found that by reading one function beside one table.

## The second referee's findings (version 7)

| Wrong program (referee 2) | Fails | Seen failing as |
| --- | --- | --- |
| "Unchanged" and "numbers only" count every line while the other three columns count paragraphs (1) | `tests/test_filing_diff.py::test_every_line_of_two_real_filings_is_counted_exactly_once`, `::test_the_five_counts_are_of_paragraphs_and_short_lines_and_rows_are_counted_apart` | written first: 7 failed, 47 passed, these among them |
| A sub-heading renamed over an unchanged body shows nothing (2) | `::test_a_changed_sub_heading_is_reported_though_its_paragraphs_are_unchanged` | the same run |
| A paragraph whose figures alone moved is counted and never shown (3) | `::test_a_paragraph_whose_numbers_alone_changed_is_listed_with_the_numbers_marked` | the same run |
| A listed paragraph that is not an exact span of a real filing, in any of the four lists (4) | `::test_every_listed_paragraph_of_two_real_filings_is_an_exact_span_and_says_its_link` | the same run (the record had no link kind and no numbers-only list) |
| A run whose meaning check failed says "complete" (6) | `tests/test_thesis_run.py::test_a_checker_that_fails_leaves_findings_unchecked_and_the_run_partial`, `tests/test_policy.py::test_each_reason_alone_makes_the_run_partial` | the older test asserted "complete"; changed first: 2 failed, 86 passed |
| "Operating expenses grew 3%" passes against "(3)%" (7) | `tests/test_numcheck.py::test_a_word_for_an_outflow_does_not_let_a_percentage_match_a_decline` | written first: `assert 'passed' == 'failed'` for each of the three statements |
| A recorded comparison with a bare link called a passage link, a numbers-only pair that differs in a word, or a sub-heading on both sides | `tests/test_sample_changes.py::test_each_kind_of_damage_to_the_record_is_reported` (eleven kinds of damage now) | the test damages a copy and expects each to be reported |

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

Since the meaning check was added, the replay also sends one `check` request per claim with a
verified finding. Until those are answered in the cassette it fails on them, by design: a
pending request is never a pass.

## The meaning check

A second model reads each claim's verified findings (statement, stance, excerpts, cited figures;
never the engine's rationale or confidence) and judges each one supported, partly or not
supported. Its tests run with scripted checkers and transports, never the API:

- `tests/test_engine_checker.py`: what the request shows and hides, escaping on the way in and
  out, the three verdicts, and a table of malformed answers that each raise `EngineError`.
- `tests/test_thesis_run.py` ("The meaning check"): a rejected finding is withheld with its reason
  and moves the verdict (mixed to supported); "partly" is kept and counted; a failing checker
  leaves findings unchecked with one error line, and the run partial (complete until version 7); a
  checker on the engine's own model is a coverage limit; checking claims concurrently gives the
  sequential record.
- `tests/test_cassette.py`: a pending check blocks the summary but not the next claim's
  assessment; a checker sibling shares the engine's run and records with its own model.
- `tests/test_cli.py`: the cassette loop now takes four rounds (plan, assess, check, summarize).
- `tests/test_evaluation_generation.py`: `generate --check` scores agreement before and after the
  check, and without `--check` the record and report are byte-for-byte what they were.

Each was seen failing on a planted fault (the rationale sent to the checker, unescaped excerpts,
a rejected finding kept, a checker exception not caught, the old cassette reset rule, the export
without its meaning line, the eval's "broken" count reversed) before it passed.

**Whether the check would catch anything.** None of the tests above can say: they script the
checker. `make eval ARGS="mismatch --cassette eval/cassettes/mismatch --queries eval/queries.json"`
(`evaluation/mismatch_eval.py`, review 5 finding 6) keeps each of the 76 verified golden-set
findings that has a quote, with its claim, statement and stance, and swaps in real, verified quotes
that belong to a finding about another company, or to another claim about the same company. The
request is built by the production prompt builder and judged like any other. Of 152 such
mismatches the second model judged 149 not supported, 3 partly and none supported; on the same 76
findings with their own quotes it had judged 1 not supported, 10 partly and 65 supported
(`eval/results/mismatch-2026-11-17.md`). The answers are a stand-in's (Claude Haiku as a Claude
Code subagent, in six fresh contexts of eight requests, given the prompts under neutral file
names and not told they were planted). A swapped quote is the easy kind of mismatch: usually
another topic. A quote on the right topic that does not carry the statement is the hard kind,
and nothing here measures it.

## The two features of versions 8 and 9

| Wrong program | Fails | Seen failing as |
| --- | --- | --- |
| A changed paragraph listed under a claim it shares no words with (`MIN_SHARED_TERMS` 2 → 0 in `core/claim_changes.py`) | 7 tests of `tests/test_claim_changes.py`, among them the plan's exit check `::test_exit_check_a_planted_china_paragraph_reaches_the_china_claim_only` | run by the session that built it; restored |
| The run's filing compared with the wrong earlier one (the oldest listed, not the one just before) | `::test_the_run_filing_is_compared_with_the_one_before_it_not_with_the_newest` | the same way |
| A paragraph printed under two Items taking two of a claim's five places | the two tests on repeats in `tests/test_claim_changes.py` | written first, failed with the second copy listed |
| No route for a run's changes, or its answer never kept | `tests/test_api.py::test_the_changes_of_a_run_are_listed_under_each_of_its_claims` and the two beside it | route renamed and the cache write removed: 3 failed |
| A tagged number read without its `scale` | 25 of the 67 tests of `tests/test_ixbrl.py` and `tests/test_breakdowns.py`, among them the answer key against the filing's text | run by the session that built it; restored |
| A value placed by the filing's fiscal year and not by its context's dates; a quarter mixed with year to date | `tests/test_breakdowns.py::test_an_annual_report_gives_three_fiscal_years_newest_first`, `::test_a_quarterly_report_gives_quarters_and_never_year_to_date` | written first |
| No route for the breakdowns | the four tests on it in `tests/test_api.py` | route renamed: 4 failed |
| A page that draws a breakdown cell it computed, or a changed paragraph with a stance mark | `uitests/test_breakdowns_dom.py`, `uitests/test_run_changes_dom.py` | each new assertion under its own deliberate break, by the session that built the page |

What these cannot see: whether a changed paragraph listed under a claim bears on it, and whether a breakdown's label is the company's. Both are stated on the page.

## How long the gate takes

Measured on this laptop on 17 November 2026 at version 8, with the Docker image's layers already
built (review 5, finding 12): the offline tests take 21 s (pytest reports 21.14 s for 1,182
tests), and `make verify-fresh`, the whole gate on a fresh clone (clone, lint, the tests, the
smoke test, three page renders and 99 page assertions), took 33 s by the wall clock. One run of
each; a first build of the image takes minutes and was not timed.

## What no test here can see

- Whether a highlighted quote actually supports or challenges the claim. The gate proves the
  text exists, not what it means. The meaning check is a second model's reading, not proof: it
  can be wrong in either direction, and no test here measures how often.
- Whether "Open in filing" scrolls to and highlights the quote on live sec.gov.
- Whether a newcomer understands the page; colour, contrast, dark mode and the phone layout.
- Live services: real model output quality, EDGAR rate limits and outages, billing and key
  failures. Only one other company's full filing (Costco's 10-K) is a fixture.
