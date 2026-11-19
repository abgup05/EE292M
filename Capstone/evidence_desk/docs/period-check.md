# The period check: is the year a finding names in its evidence? (milestone 11)

The number check has never looked at a year. A statement that puts a figure in fiscal 2023 passed above a quote about fiscal 2025, and the third referee called that the commonest error in this kind of work ([`referee-3-triage.md`](referee-3-triage.md), 2a). Version 11 adds a check that reads the years a finding's statement names and looks for each in the finding's own evidence.

It **reports**. It withholds no finding and changes no verdict and no status. Code: `core/periods.py` (pure). A finding carries the result in `checks.periods`, `checks.periods_detail` and `checks.periods_unverified`; a run counts it in `coverage.periods_checked`, `periods_unverified` and `periods_comparative`.

## What it reads, and what counts as evidence

**The years a statement names**, with the number check's own recognition of what is a year and what is a quantity, so the two cannot disagree ("2000 employees" is a count). Three kinds:

- a **fiscal label**: "fiscal 2026", "fiscal years 2025 and 2026", "FY26", "at fiscal year-end 2026";
- a **date**: "July 26, 2026", "June 2026", "2026-07-26", which names a calendar year;
- a **bare year**: "in 2026", "compared to 2025", which may be meant either way. Since version 11.1 a year directly before one of fourteen financial nouns is one too ("2025 revenue", "2026 net income"; the list is `numcheck.YEAR_NOUNS`). Until then it was read as a count of 2,025, never reached this check, and "2023 revenue" passed the number check against a quote that said "2023 employees". "2025 employees" is still a count.

**The evidence** for a year is: any year a quoted excerpt shows, in any context; the fiscal year and the calendar year of the period end of each filing quoted; and the same two for each cited figure's period and for the periods of the figure's inputs, so that the base year of a year-over-year change counts. An excerpt's years are read over the same range as a statement's, 1900 to 2100. Until version 11.1 they began at 1990, so "incorporated in 1919" above a quote that printed 1919 was reported as unverified: a false alarm that the measurement below could not show, because no finding of the golden set names a year before 1990.

| A year named as | passes when it is |
| --- | --- |
| a fiscal label | in a quote, or the fiscal year of a filing quoted or of a cited figure |
| a date | in a quote, or the calendar year of a period end |
| a bare year | any of those |

A calendar year is not enough for a fiscal label, because the two differ: NVIDIA's quarter ended 26 July 2026 is in its fiscal 2027. A year that does not pass is **unverified**. When it is one or two less than the fiscal year of a filing quoted or of a cited figure it is also marked **comparative**: the years a report prints beside its own. That mark changes nothing; it is there to be counted.

**The fiscal calendar** of a company comes from the newest annual report in its SEC company facts: the fiscal year that filing says it is for, and the end of its own year. This is the one place the facts' `fy` field is read. Everywhere else in this project it is ignored, because it describes the filing and not the fact; here the filing's own label is what is wanted. A company that names its fiscal year after the calendar year it begins in gets an offset of minus one. When the facts cannot be read, a period end is taken to fall in the fiscal year of its own calendar year or of the next, and the check says so.

## Measured on real findings: no false alarm on the golden set

The golden set is also where the rules of years (`years_in`, `EVIDENCE_YEARS`) were widened to avoid false alarms, so this is a measure on the check's own development data, not on findings it has not seen.

`make eval ARGS="generate --cassette eval/cassettes/golden --queries eval/queries.json --check"` runs the check on every verified finding of the golden set, and `make replay` on the three recordings of the example (17 November 2026; the model answers are a stand-in's, as everywhere here).

| Findings of | Years named | Found in the evidence | Not found |
| --- | ---: | ---: | ---: |
| The golden set, 30 cases over five companies | 34 | 34 | 0 |
| The example, first recording | 10 | 10 | 0 |
| The example, recorded again with no reminder | 12 | 12 | 0 |
| The example, tagged figures offered | 12 | 12 | 0 |

The three recordings are one thesis, so their rows are not independent. On these findings the check raises no alarm. That is a measure of false alarms only: none of these findings is known to name a wrong year, so this says nothing yet about what the check catches.

## Measured on the same findings made wrong: what it catches

The same command then plants an error. For each of the 25 verified findings of the golden set that name a year, every year in the statement is moved by the same amount and the evidence is left as it is. No model is involved.

| Years moved by | Findings | Flagged | Not flagged |
| --- | ---: | ---: | ---: |
| one year back (a report's comparison column) | 25 | 21 | 4 |
| two years back | 25 | 24 | 1 |
| three years back | 25 | 25 | 0 |
| one year forward | 25 | 23 | 2 |

Every one of the seven that passed is listed, with the reason, in `eval/results/generation-checked-2026-11-17.md`. They are of two kinds:

- **The quote prints the planted year itself** (five of the seven). "Gross margin for the first quarter of fiscal year 2026 was 74.9% against 60.5% a year earlier" passes because the quoted sentence compares the quarter with fiscal 2026 and so contains "2026". This is the wrong-column error, and a check that asks only whether the year appears cannot see it.
- **A date in the same calendar year as a filing's period end** (two). "Licences granted in August 2026" passes against the report for the year ended 25 January 2026: the year matches, and the check does not know that a report cannot describe a later month.

So the check catches a year that is nowhere in the evidence, and misses a year that is in the evidence for another reason. The commonest real slip, the prior-year column, is the case it catches least: 21 of 25.

### One wrong year beside right ones

Moving every year of a statement together is kinder to the check than a real slip, which is one wrong year beside a right one (the fourth referee's point, [`referee-4-triage.md`](referee-4-triage.md)). So since version 11.1 the same command also takes each verified finding that names two or more years and moves one year at a time, one year back, leaving the other years and the evidence as they are.

| Findings that name two or more years | Statements planted | Flagged | Not flagged |
| ---: | ---: | ---: | ---: |
| 9 | 18 | 13 | 5 |

That is 72% caught, against 84% (21 of 25) when every year moves. The five that passed are one case five times: the statement compares two consecutive years, and the later one, moved back, lands on the earlier. "Gross margin fell to 71.1% in fiscal year 2025 from 75.0% in fiscal year 2025" passes, because fiscal 2025 is in the quote. A reader would see it at once; a check that asks only whether each year appears cannot. Nine findings is a small sample.

**What planting found in the check itself.** The first run of this measurement flagged only 19 of the 25 moved one year forward. Four of the six misses were dates: "as of July 26, 2027" passed against the report for the quarter ended 26 July 2026, because 2027 is that filing's fiscal-year label and a year that is not a fiscal label was allowed to pass as one. A date is not a bare year. Dates now pass on calendar years only (`tests/test_periods.py::test_a_date_does_not_pass_as_a_fiscal_label`, written first), and the count rose to 23. Planting also showed "during 2026 compared to 2025" with only its first year recognised: the year after "compared to" was being read as a quantity. It is a year now.

## Limits

- **It reports and does not withhold.** A finding with an unverified year still counts toward its verdict. Whether it should be withheld is a decision for after more than one thesis has been read with it; on the evidence so far it would have withheld nothing true, and that evidence is 34 years in 25 findings.
- **The wrong column of a table passes** whenever the quote shows both years, which a row of a comparative table always does.
- **A year is checked, not a date.** "The quarter ended 26 July 2026" passes on 2026 alone.
- **It reads the statement only.** A finding's reason, the commentary and the summary are not checked for years.
- **The fiscal calendar is read from one filing's label.** For Costco and Coca-Cola it was read from the cached facts and not compared with their reports by a person. A company that changed its year end would be read by its newest year.
- **No real error has been seen.** The planted errors are mechanical. Whether a model's actual period slips look like them is not known.
- **The planting uses the check's own recogniser of years.** It cannot plant a year the recogniser does not see, so it says nothing about those. The year before a financial noun was such a case until the fourth referee named it.
- **A fiscal label passes on a calendar date in the quote.** A year found anywhere in the quote passes before fiscal and calendar labels are told apart, so "fiscal 2026" said of the quarter ended 26 July 2026 (which is in fiscal 2027) passes when the quote prints "Jul 26, 2026". For a company whose fiscal year is not the calendar year this is the likeliest wrong label, and the rule stated above is not what the code does here. Read from the code by the sixth referee; not yet shown by a test or fixed ([`referee-6-triage.md`](referee-6-triage.md), finding 3).
- **The same year twice passes.** "From 75.0% in fiscal 2025 to 71.1% in fiscal 2025" is two mentions of a year the evidence carries.
- The four recognitions added to the number check while building this ("year-end", "end-of-", "versus", "compared to" and the like before a year) each began as a year read as a quantity; there are certainly more.
