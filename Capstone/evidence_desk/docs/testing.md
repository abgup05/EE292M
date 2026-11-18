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
mismatches the second model judged 150 not supported, 2 partly and none supported; on the same 76
findings with their own quotes it had judged 1 not supported, 10 partly and 65 supported
(`eval/results/mismatch-2026-11-17.md`). The answers are a stand-in's (Claude Haiku as a Claude
Code subagent, given the prompts under neutral file names and not told they were planted; 16 of
the 48 were recorded again when the Costco findings changed, `eval/README.md`). A swapped quote is the easy kind of mismatch: usually
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
| A reader that searches to the end of the filing for every tag that is never closed | `tests/test_ixbrl.py::test_unclosed_context_tags_do_not_make_the_scan_quadratic` | written against the first version: "8x the openings took 63.5x as long" |
| A page that puts a figure under the wrong period when a row lacks one | `uitests/test_breakdowns_dom.py::test_a_value_missing_in_the_middle_leaves_that_column_empty_and_moves_nothing`, on a synthetic sample with one value taken out | cells placed by position: this test failed and the 123 others passed |
| A deep link to a claim that opens nothing | `uitests/test_run_changes_dom.py::test_the_deep_link_opens_that_claims_block_and_no_other` | checked against the dump without the hash, where no block is open |
| A page that draws a breakdown cell it computed, or a changed paragraph with a stance mark | `uitests/test_breakdowns_dom.py`, `uitests/test_run_changes_dom.py` | each new assertion under its own deliberate break, by the session that built the page |

What these cannot see: whether a changed paragraph listed under a claim bears on it, and whether a breakdown's label is the company's. Both are stated on the page.

## The third referee's findings and milestone 10 (version 10)

| Wrong program | Fails | Seen failing as |
| --- | --- | --- |
| A company whose year is in weeks: its 24- and 36-week periods dropped, its fourth quarter never derived | `tests/test_facts.py::test_a_52_week_retailer_gets_its_sixteen_week_fourth_quarter`, on Costco's own facts for two fiscal years | written first; failed before the period lengths were widened |
| A 16-week quarter shown as growth on the 12 weeks before it | `tests/test_metrics.py::test_quarters_of_unequal_length_are_not_compared_with_each_other` and the test beside it | the length rule switched off: 2 failed, 66 passed |
| Twelve months to a quarter end taken for a fiscal year | `tests/test_facts.py::test_twelve_months_to_a_quarter_end_is_not_a_fiscal_year`, `tests/test_metrics.py::test_the_reports_fiscal_years_are_fiscal_years` | written first, after `make figures` showed it on Amazon |
| A bank with no revenue figure | `tests/test_facts.py::test_a_bank_reports_its_revenue_net_of_interest_expense` | written first, after `make figures` showed it on JPMorgan |
| "Revenue grew 3% while gross margin fell" passing against "(3)%" | `tests/test_numcheck.py::test_a_word_of_decline_about_something_else_does_not_let_growth_match_a_fall` | written first: all three cases passed the old check |
| "$46 million" passing against "46 customers" | `::test_a_count_of_things_in_a_quote_does_not_match_a_dollar_amount` | written first: four cases |
| "at fiscal year-end 2026" read as the quantity 2026, and a true finding withheld | `::test_a_year_after_year_end_is_not_a_quantity_in_a_recorded_statement`, on the statement a stand-in wrote | found by the first replay of the tagged recording |
| One comparison that breaks failing the whole request for a run's changes | `tests/test_claim_changes.py::test_a_comparison_that_breaks_costs_only_its_own_list` | written first: failed with the `ValueError` |
| A second tagged total taken without a word; a reader stopped by an `assert` | `tests/test_breakdowns.py::test_two_tagged_totals_for_one_period_are_noted_not_silently_resolved`, `::test_annual_values_in_the_rarer_unit_do_not_stop_the_report` | written first: the second failed with `AssertionError`, on an input the referee had not been able to construct |
| The option ignored, or a failure to read a filing's tags not reported | 12 and 5 tests of `tests/test_tagged_figures.py` | planted by the session that built the feature; restored |
| A customer's share of 0.22 offered as 0.22% | `tests/test_tagged_figures.py::test_a_share_tagged_as_a_fraction_is_offered_as_a_percentage`, and the replay of the tagged recording | planted in review: it passed every unit test of the module and only the replay failed, so the unit test was added and seen failing |
| A sample that tells the reader its answers came from another recording | `tests/test_replay_tagged.py::test_a_sample_names_the_recording_it_was_made_from` | found by reading the first screenshot of the new sample |
| A page that adds up the two offered counts, drops a tagged figure's row, or keeps one of three untrue wordings | `uitests/test_tagged_dom.py` (18 assertions) | the group made to drop its last row: 2 failed |

**A probe, because the answer key covers three companies.** `make figures TICKERS="..."` (`src/app/figures.py`) prints each company's quarters as a run sees them: the quarter's length, its revenue and whether that is reported or derived, its change on a year earlier and on the quarter before, its cash flow, and how many metrics have no value. It computes nothing. Run on the eight probe companies before and after a change, it shows which lines moved (`docs/evidence/figures-eight-companies.md`). It is how the Amazon and JPMorgan faults were found. It cannot say a figure is right.

**Two more recordings replayed** (`tests/test_replay_tagged.py`). Each builds every prompt afresh, as `test_replay.py` does for the first, and compares the verdicts and counts with a baseline read once from the first complete replay. A baseline is not an answer key: it says what the gate, the number check and the verdict rule make of those recorded answers, so a change in any of them is seen.

## The period check and what planting found (version 11)

| Wrong program | Fails | Seen failing as |
| --- | --- | --- |
| A statement that puts a figure in a year its evidence does not carry, and nothing says so | `tests/test_periods.py`, the referee's case: "fiscal 2023" over a quote about fiscal 2025 from the fiscal 2026 report is unverified; "fiscal 2025" and "fiscal 2026" pass | 53 tests failed against stubs before the module existed |
| A fiscal label passing on a calendar year (NVIDIA's quarter ended July 2026 called "fiscal 2026") | 4 tests of `tests/test_periods.py` | planted by the session that built it; restored |
| A date passing as a fiscal label ("as of July 26, 2027" against the quarter ended 26 July 2026) | `::test_a_date_does_not_pass_as_a_fiscal_label` | found by planting wrong years in the golden set's findings: 4 of 25 moved one year forward passed this way; the test was written, failed, and the count rose from 19 to 23 |
| A year after "compared to", "versus", "year-end" or "end-of-" read as a quantity | the year contexts of `tests/test_numcheck.py::test_a_year_in_a_date_like_context_is_exempt`; `tests/test_periods.py::test_the_comparison_year_after_compared_to_is_a_year` | each written first; one came from a recorded statement, one from the planted statements |
| A check that withholds, or moves a verdict or a status | `tests/test_thesis_run.py`: a finding with a wrong fiscal year is still verified and counted, and the run's status is what it would be without the check | written first |
| A brief or a page that reads the check's sentences back to find the years | the record carries them (`FindingChecks.periods_unverified`); `tests/test_export.py`, `tests/test_replay_periods.py` | changed in review: the first version parsed its own sentences |
| A run that fetches two filings again for their tags every time | `tests/test_tagged_cache.py::test_a_second_run_with_the_same_cache_fetches_no_filing_at_all` | written first: the second run fetched both |

**The check is measured, not only tested.** The checked evaluation runs it on every verified finding of the golden set (34 years, none unverified) and then plants a wrong year in each of the 25 findings that name one: every year moved by the same amount, the evidence left alone. It lists every planted error that passed, with the reason (`docs/period-check.md`). That measurement found a fault in the check that no unit test had: a date allowed to pass as a fiscal label.

## The sixth review: the backup, two writers, and the header cut (after version 10)

| Wrong program | Fails | Seen failing as |
| --- | --- | --- |
| A restore check that compares runs by their ids only: a run rewritten after the backup passes | `tests/test_backup.py::test_restore_check_fails_when_a_run_changed_though_its_id_did_not` | written first: the old check passed it |
| A restore check that skips what it cannot parse on both sides, and so agrees | `::test_restore_check_fails_on_records_this_version_cannot_read`, `::test_a_record_changed_in_a_way_no_parser_sees_still_fails` | written first, from the reviewer's reading of the code |
| A backup of any age reported as if it were current | `::test_the_pass_line_says_how_old_the_backup_is`, `::test_status_says_what_the_newest_backup_does_not_hold` | written first |
| A header-cut check that reports "the same" whatever it finds | `tests/test_header_cut_check.py::test_a_difference_is_seen_and_fails_the_command` | the uncut parse made to differ: the row says NO and the command exits 1 |

Two checks are commands, not tests, because they need what the gate must not need. `make two-writers` starts the app on a scratch record and has it and a one-off container write that record at the same time, then checks SQLite's integrity and every row (`docs/evidence/two-writers.txt`). `make header-cut-check` parses live filings with and without the parser's header cut and compares the documents whole (`docs/evidence/header-cut-fourteen-filings.md`). Each shows that something held once, on one laptop, on one day.

## The fourth referee's findings (version 11.1)

Each fix began as a test that failed ([`referee-4-triage.md`](referee-4-triage.md)):

- **A whole quote** (`tests/test_gate.py`): a quote that cuts a number at a decimal point or a thousands separator, on either side, is not found (ten cases); nor is one that cuts a word; a later whole occurrence is found after one that is cut; a number or a word before a full stop, a comma or an apostrophe is still quotable; and a finding whose only quote cuts a number is withheld. Each case runs on the exact and on the normalised search.
- **Years** (`tests/test_periods.py`, `tests/test_numcheck.py`): a year from 1900 to 1989 that the quote prints is found, and one it does not print is still reported; a year directly before each of the fourteen financial nouns is a year, and "2025 employees", "2,025 stores", "2025 units" and "2025 customers" stay counts; a wrong year before "revenue" is no longer matched against a bare number in a quote.
- **One wrong year beside right ones** (`tests/test_periods.py`, `tests/test_evaluation_generation.py`): one planted statement per year named, each with exactly one year moved, and the report's second table.
- **The restore check, column by column** (`tests/test_backup.py`, `tests/test_store.py`): a backup that differs from the record only in a run's `thesis_id`, in a decision's time or in a thesis's creation time fails, and the failure names the record and the column; an untouched copy passes.
- **The Markdown brief** (`tests/test_export.py`): an excerpt cannot become an image, a link, emphasis, code or a heading; undoing the escapes gives back the stored excerpt exactly; an ordinary excerpt is written unchanged; every other piece of text the export did not write is escaped too; the export's own links still work and a URL cannot close one early. The verdict table counts the distinct filings each claim's verified findings quote.
- **A figure tagged twice** (`tests/test_breakdowns.py`): the most precisely tagged value is shown whichever comes first, and a coarser value that disagrees beyond its rounding is still noted.

Three existing tests had cut a quote in the middle of a word by slicing a string at a fixed length, which the gate now refuses, as it should; they cut at a word now. Their expectations did not change.

The two measurements the referee faulted are commands, not tests (`make bench`, `make time-live`), and what changed in them is in [`speed.md`](speed.md).

## Events since the annual report (version 12)

| Wrong program | Fails | Seen failing as |
| --- | --- | --- |
| A run that never lists the 8-Ks, or lists them with a request of its own | `tests/test_edgar.py`, the seven `current_reports` tests (newest first, filed after the date, 8-K/A included, items read, the index reused within a minute, a malformed items column) | written first: AttributeError against the old client |
| A splitter that loses an item, joins the signature block to the last one, or opens a section at "Item 1.01 above" | `tests/test_current_report.py` (19 tests, on six recorded 8-Ks of NVIDIA, Coca-Cola and JPMorgan and on made-up ones) | written first: ImportError; two more ("Item 9.01(d).", "Item 5.02(e)") written from the live probe's misses, each failing before its fix |
| A category, a claim rule, a supersession or a note that is wrong ("margins are gone" as leadership, an 8-K filed the same day as the finding's filing counted as later, a note that reads as "this is not true") | `tests/test_events.py` (53 tests) | written first: ImportError, then two failures on the table's size and an example sentence |
| An opening sentence cut after "Mr." | `tests/test_events.py::test_an_opening_sentence_is_not_cut_after_a_title_or_a_company_suffix` | seen live in NVIDIA's 8-Ks; written, failed, then fixed |
| Counts that do not add up, or a failure that ends the run | `tests/test_events_service.py` (13 tests) | written before `services/events.py` was wired in |
| The motivating case: a 5.02 after the 10-Q and "Buy because Jane Smith is gone" answered from the 10-K with nothing said | `tests/test_events_run.py::test_the_motivating_case_the_8k_is_shown_offered_and_marks_the_older_finding`, and its opposite, `::test_with_no_5_02_since_the_annual_report_the_claim_gets_a_note_not_a_verdict` | 6 of the 7 first whole-run tests failed before the pipeline change (the seventh loads a version-11 run) |
| A caution on a verdict that a context finding cannot decide | `::test_a_predated_context_finding_is_marked_but_cautions_no_verdict` | written after reading `policy.mark_counted`; failed, then fixed |
| A prompt that changes when no 8-K is offered, so the recordings stop matching | `::test_the_model_is_told_about_newer_filings_only_when_an_8k_passage_is_offered`, `::test_the_example_thesis_has_no_claim_an_8k_bears_on`; `make replay` with all 12 answers of each cassette matched | failed before the change to `engines/claude.py` |
| A run from before version 12 that no longer loads | `::test_a_run_recorded_by_version_11_still_loads_with_empty_event_fields`, on a run of 0.11.1 kept in `tests/fixtures/record/` | passed from the start, as it should: every field has a default |
| A brief that leaves out the events or lets 8-K text act as Markdown | `::test_the_brief_carries_the_as_of_line_the_events_the_caution_and_the_mark`, `::test_8k_text_in_the_brief_is_escaped_as_excerpts_are` | written after the export code; the export change removed, all three brief tests failed |
| A route that answers for a bad ticker, or fails on an unreadable 8-K list | `tests/test_api.py`, the five events and meta tests | written after the route; the route removed, all five failed |
| A page that computes or reorders what it shows, or shows a mark the record does not carry | `uitests/test_events_dom.py` (12 assertions on two sample runs and one record from before version 12) | written after the page code; first run failed on samples made before the wording reached `/api/meta` |
| A claim rule that drifts | `tests/test_claim_categories_eval.py` pins the table of `make event-categories` | the labels were committed before the rule existed |
| A time line that drops, adds or misdraws a filing or an 8-K, or shades a gap the record does not have | `uitests/test_run_events_dom.py`, the time-line tests on four sample runs | written after the drawing; the newest 8-K then dropped from it on purpose: the three runs with 8-Ks failed |
| A live-run sample that is not the run's record, or a page that hides where it came from | `uitests/test_run_events_dom.py::test_the_sample_is_the_live_run_unedited` (skipped where `results/` is not), `::test_the_page_says_where_the_sample_comes_from` | written with the sample |
| Keys that act while you type, j and k that skip or wrap, a theme that is not remembered | `uitests/test_keys_dom.py`, on what `uitests/keys.html` recorded | written after the code; the guard on typing then removed on purpose: three of its tests failed |
| A tape that shows a figure other than the record's (the year's where the record has the quarter's, a reformatted value, another order) | `uitests/test_run_events_dom.py::test_the_tape_shows_the_records_own_figures_in_order`, on four sample runs | written after the tape; the page then made to prefer the year's metric on purpose: all four runs failed |
| A run that does not lead with its answer, a count lost from the status line, the withheld findings or the full counts left open, standing prose back on the reading path | the other second-pass tests of `uitests/test_run_events_dom.py` | written after the page code and not seen failing |
| The specimen page not served | `tests/test_api.py::test_static_files_are_served[/specimen.html…]` | written first: it failed with 404 before the route was added |

The command-line tools (`tests/test_events_cli.py`, `tests/test_events_probe.py`) were written after their code and were not seen failing.

## The standing watch (version 13)

79 tests in ten files, all offline (`tests/fakes.py`: a fake EDGAR whose index gains filings, a scripted
engine, a wall clock the test moves). The design and its measurements are in `docs/watch.md`.

| Wrong program | Fails | Seen failing as |
| --- | --- | --- |
| Triage that flags the wrong claims, skips a 2.02, lets a vote or an exhibits-only 8-K start a run, or names no changed paragraph under a claim for a new 10-Q | `tests/test_triage.py` (12 tests) | all 12, against a stub with the real signatures |
| Two workers that take the same job; a filing queued twice for one thesis; a retry before its backoff or after the cap; a job lost when its worker dies; the daily cap counted twice for one job | `tests/test_watch_store.py` (13 tests: two of them race two processes on one file, one loads a record from before version 13) | ImportError first; then a planted select-then-update claim failed both race tests 3 times in 3 (both workers took one job; 62 to 66 claims for 60 jobs) |
| A backup that leaves out the watch tables, or a restore check that does not compare them | `tests/test_watch_backup.py` (6 tests) | 5 of 6 failed before `backup.py` changed; the sixth, a backup from before version 13, passed from the start, as it should |
| A report of what moved that misses a verdict, a caution, a note or a new 8-K, or calls a re-dated note new | `tests/test_watch_report.py` (4 tests) | all 4 |
| An index listing that costs more than one request, or misses 8-K/A | `tests/test_watch_edgar.py` (1 test) | failed before `EdgarClient.recent_filings` existed |
| The end to end: a 5.02 8-K appears; one job; claim 1 bears and claim 2 does not; the thesis runs; the inbox names the filing, its link and what moved; the next cycle queues nothing | `tests/test_watch_service.py::test_end_to_end_a_new_5_02_8k_runs_the_thesis_and_the_inbox_says_what_moved`, and 9 more on policy, cap, retries, index errors, one request per company, periodic reports, unwatching and re-watching | ImportError first; the end to end failed on a planted comparison with no previous run |
| A started run whose item still says it waits; a failed run whose item still says it runs | two assertions in `tests/test_watch_service.py` | both, found while writing the example payloads, before their fixes |
| A waiting run that two requests can both start | `tests/test_watch_api.py::test_a_waiting_run_is_started_once_and_its_item_then_says_what_moved` | failed on a planted start that checked the kind and then changed it in two steps |
| An example payload that no longer matches its route, or a README that leaves a field unnamed | `tests/test_watch_examples.py` (13 tests) | the README test, on a planted missing field |
| A page that reorders the inbox, shows a kind, headline, filing, reason or move other than the record's, offers Run now on an item with no waiting run, or shows an unread number other than the API's | `uitests/test_inbox_dom.py`, on the recorded inbox (`?sample=inbox`, `?sample=inbox-page-2`) | written after the page code; the page then made to reverse the API's order on purpose: 3 failed (both orders and the paging) |
| A page that swallows a refusal of a watch route (202 and 409 on Run now; 422, 503 and 200 on a policy; 409 on taking a watch off), hides an empty inbox or a watcher not running, or pages by anything but the API's offsets | `uitests/test_inbox_dom.py`, on what `uitests/watch.html` recorded | written after the page code and not seen failing; the harness itself stalled once, on controls drawn disabled in sample mode |
| A recorded inbox that is not the example payloads | `uitests/test_inbox_dom.py::test_the_samples_are_the_example_payloads_unedited` (5) | written with the copies |
| A page that draws a computed test, its counted state, an operand, a fact's filing, a history point or flip, the as-of banner or a ledger row other than the record's, or loses the compile note, the readers or the computed counts | `uitests/test_v14_dom.py`, on `?sample=computed`, `?sample=as-of` (Terminal) and `?sample=restatements` | written after the page code; the page then made to count a test that holds as a challenge and to draw each history newest first, on purpose: 6 failed (counted state in both samples, histories in both, the example's flips, the agreeing readers) |
| A page that hides readings that differ or counts them, lists only two readers, swallows a refusal of the ledger lookup or of a dated run, drops `as_of` from the request, or ignores `folded`, `claims_line`, `moved.computed` or a thesis's own `watch` | `uitests/test_v14_dom.py`, on what `uitests/v14.html` recorded | written after the page code; the two refusal tests first failed on the refusal mark before the server's words, which the tests had left out |
| Version 14 samples that are not the example payloads | `uitests/test_v14_dom.py::test_the_samples_are_the_example_payloads_unedited` (3) | written with the copies |

Not seen failing, because they were written after their code: the other 10 API tests, the 8 tests of the
watcher process, its settings and its health (`tests/test_watch_cli.py`), the 12 parse checks of the example
payloads, and the contention test (`tests/test_watch_contention.py`: a run and watcher cycles writing one record
from two processes; nothing was planted to make it fail).

## Facts with dates and computed claims (version 14)

| Wrong program | Fails | Seen failing as |
| --- | --- | --- |
| A fact book, metrics report or fiscal calendar as of a date that reads a fact filed later | `tests/test_facts_as_of.py` (8 tests; on every periodic filing date of NVIDIA, Apple and Microsoft and the day before, 414 dates, against `tests/lookahead.py`) | written first: 278 and more problems per company before `FactBook(as_of=)` filtered; `::test_the_checks_catch_a_filter_that_reads_the_period_end_instead_of_the_filing_date` plants such a filter and both checks fire |
| A fact store that loses a fact, keeps a fact without its filing, or duplicates a company | `tests/test_fact_store.py` (9 tests) | not seen failing in this session's log: its first recorded run passed |
| A ledger that misses a restatement, counts an unchanged report, or sees later filings as of a date | `tests/test_restatements.py` (14 tests, NVIDIA's fiscal 2024 EPS across the split among them) | written first: ImportError |
| A run as of a date that reads a 10-K, 10-Q, 8-K or fact filed later, or a run without a date that changes | `tests/test_as_of_run.py` (14 tests) and two in `tests/test_cli.py` | written first: every request test failed on the missing field |
| A compiler that prints the wrong test, or compiles a forecast, a cause or a valuation | `tests/test_claimtest.py` (48 cases in 7 tests) and `make claim-labels` | written first: ModuleNotFoundError |
| An evaluator with the wrong period, the wrong arithmetic, a leak, or a history past five years | `tests/test_claim_eval.py` (17 tests, with a planted leak) | written first: ModuleNotFoundError |
| An evaluator that disagrees with expected values computed by another route, or a key edited by hand | `tests/test_claim_results.py` (52 cases and 2 tests) | failed on r14 (NVIDIA fiscal 2008): the oracle's year labels were wrong; the oracle was fixed, r14 alone changed |
| A run that does not compute, counts a test wrongly, shows the summariser the new verdicts, or leaks as of a date | `tests/test_computed_run.py` (6 tests) | written first: `Claim` had no `computed`; the verdicts were all not addressed |
| A brief without the computed tests or their history | `tests/test_computed_run.py::test_the_brief_has_a_deterministic_section_of_computed_tests` | written first, with the run tests |
| A compiler-vs-model harness that calls before it says how many, or above the cap | `tests/test_compiler_vs_model.py` (6 tests, fake transport only) | written first: ImportError |
| Example payloads that fall behind the code | `tests/test_examples_v14.py` | written first: ImportError |
| A grammar change that moves a reading of the foreign claims without its being judged, or moves the final numbers | `tests/test_foreign_claims.py` (9 tests) | written after the scorer and the judgements; pins the numbers of `make claim-foreign` |
| A claim compiled with words its test does not explain (a part read as the whole, an unknown measure, a named period ignored, half a claim) | `tests/test_whole_sentence.py` (31 tests) | 16 sentences and 2 wording tests written first: all 18 failed on the grammar before the rule |
| A model parser's answer accepted when it does not validate or names something unsupported; a test counted when the two readers differ; the parser on by default, or asking anything when off | `tests/test_claim_reading.py` (37 tests, fake transport only) | written first: ImportError |
| A claim-readers evaluation that calls before it says how many, or above the cap | `tests/test_claim_readers_eval.py` (6 tests, fake transport only) | written first: ImportError |
| A rule taken from the foreign development half that does not hold | `tests/test_claimtest.py`, 16 new cases on new sentences | all 16 failed on the grammar before the change |
| An inbox whose folded count the page must work out, an inbox item that says what moved but not how many of the claims, a computed test's change of outcome left unsaid (or a test read differently called one), a 404 in a shape other than the app's refusals, a thesis list that does not say which theses are watched | `tests/test_watch_api.py` (3 new tests), `tests/test_watch_report.py` (3 new tests) | written first, after the merge with version 13: all 6 failed |
| A run the watch starts that skips the fact store or the second reader the app's runs use | `tests/test_claim_reading.py::test_a_run_the_watch_starts_reads_its_claims_as_the_app_does` | failed first: the watch's executor took neither |

The tripwire was re-baselined on purpose (commit 62846b1): only the verdicts stage (c4 from unjudged to
supported) and the coverage stage (four new counts) moved; the prompts stage did not, and neither did the
replay's requests (`tests/golden/replay.json`). `tests/test_thesis_run.py::test_the_time_limit_leaves_later_claims_unassessed_and_says_so`
failed once on the change, because a claim the time limit skipped took its computed verdict; such a claim now
keeps none.

## How long the gate takes

Measured on this laptop on 17 November 2026 at version 8, with the Docker image's layers already
built (review 5, finding 12): the offline tests take 21 s (pytest reports 21.14 s for 1,182
tests), and `make verify-fresh`, the whole gate on a fresh clone (clone, lint, the tests, the
smoke test, three page renders and 99 page assertions), took 33 s by the wall clock. One run of
each; a first build of the image takes minutes and was not timed. At version 10 the same two
measurements, once each: 23 s (pytest reports 23.06 s for 1,361 tests) and 34 s for the whole
gate on a fresh clone, now with seven page renders and 142 page assertions. At version 11: 26 s
(pytest reports 26.19 s for 1,499 tests) and 38 s for the whole gate, with 156 page assertions.
At version 11.1: 26 s again (26.03 s for 1,580 tests) and 38 s for the whole gate, with the same
156 page assertions. At version 12, on 18 November: 29 s (28.85 s for 1,702 tests) and 42 s for the
whole gate, with 168 page assertions (`docs/evidence/verify-fresh.txt`). On the version 13 watch branch,
18 November, once: pytest reports 32.12 s for 1,781 tests. The smoke test and the page step were not run
there (port 8766 was held by another checkout's app), so the whole gate was not timed. On the version 14
branch, 18 November, before the watch was merged in: 87 s
(87.35 s for 1,894 tests; 1,919 after the foreign-claims work, 88.29 s; 1,993 after the whole-sentence rule and the second reader, 87.79 s; 2,079 after version 13 was merged in, 92.96 s), measured once while other projects' containers ran on the same laptop, so not
comparable with the figures before it; the whole gate was not run, because another app held port 8766 and
the smoke and browser tests need it.

## What no test here can see

- Whether a highlighted quote actually supports or challenges the claim. The gate proves the
  text exists, not what it means. The meaning check is a second model's reading, not proof: it
  can be wrong in either direction, and no test here measures how often.
- Whether "Open in filing" scrolls to and highlights the quote on live sec.gov.
- Whether a newcomer understands the page; colour, contrast, dark mode and the phone layout.
- Live services: real model output quality, EDGAR rate limits and outages, billing and key
  failures. Only one other company's full filing (Costco's 10-K) is a fixture.
