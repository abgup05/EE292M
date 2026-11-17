# The filing comparison on eight companies' annual reports

Each block is taken from the output of `make changes ARGS="<TICKER> --form 10-K"`, run on 17 November 2026 (UTC 13:28 to 13:40) against live SEC EDGAR at version 0.6.0: the two filings compared, and the rows "Item 1A" and "Total" of the table "Paragraphs by Item". Columns of those rows: Item, present in, unchanged, numbers only, reworded, added, removed, short lines and table rows added / removed.

The JPM run was made after the change to the index described at the end; the other seven before it. That change does not touch them: their recent index already held two annual reports, and in that case no older page is read (`tests/test_edgar.py::test_older_pages_are_not_read_when_the_recent_index_already_has_two`).

No person has read these comparisons. The threshold for "reworded" was set on NVIDIA's filings only (`../filing-changes.md`).

## NVDA

| Period end | 2025-01-26 | 2026-01-25 |
| Filed | 2025-02-26 | 2026-02-25 |
| Item coverage | 97.0% | 96.9% |
| Item 1A. Risk Factors | both | 139 | 1 | 51 | 34 | 22 | 2 / 1 |
| Total | | 606 | 417 | 218 | 133 | 132 | 150 / 202 |

## AAPL

| Period end | 2025-09-27 | 2026-09-26 |
| Filed | 2025-10-31 | 2026-11-03 |
| Item coverage | 95.8% | 96.3% |
| Item 1A. Risk Factors | both | 35 | 12 | 58 | 24 | 8 | 3 / 0 |
| Total | | 410 | 465 | 111 | 46 | 25 | 126 / 78 |

## MSFT

| Period end | 2025-06-30 | 2026-06-30 |
| Filed | 2025-07-30 | 2026-07-29 |
| Item coverage | 98.2% | 98.2% |
| Item 1A. RISK FACTORS | both | 59 | 0 | 45 | 27 | 10 | 1 / 0 |
| Total | | 855 | 556 | 151 | 75 | 74 | 149 / 97 |

## KO

| Period end | 2024-12-31 | 2025-12-31 |
| Filed | 2025-02-20 | 2026-02-20 |
| Item coverage | 98.5% | 98.6% |
| Item 1A. RISK FACTORS | both | 60 | 0 | 39 | 7 | 9 | 0 / 0 |
| Total | | 1036 | 689 | 269 | 88 | 104 | 265 / 271 |

## JPM

| Period end | 2024-12-31 | 2025-12-31 |
| Filed | 2025-02-14 | 2026-02-13 |
| Item coverage | 99.4% | 99.4% |
| Item 1A. Risk Factors | both | 151 | 0 | 215 | 173 | 225 | 81 / 65 |
| Total | | 3133 | 2815 | 848 | 457 | 521 | 845 / 847 |
| Item 15. Exhibits, Financial Statement Schedules | both | 2886 | 2726 | 586 | 262 | 272 | 733 / 759 |

## TSLA

| Period end | 2024-12-31 | 2025-12-31 |
| Filed | 2025-01-30 | 2026-01-29 |
| Item coverage | 97.8% | 97.9% |
| Item 1A. RISK FACTORS | both | 65 | 2 | 45 | 15 | 13 | 0 / 0 |
| Total | | 580 | 448 | 227 | 127 | 93 | 174 / 259 |

## COST

| Period end | 2025-08-31 | 2026-08-30 |
| Filed | 2025-10-08 | 2026-10-07 |
| Item coverage | 96.3% | 96.4% |
| Item 1A. Risk Factors | both | 41 | 0 | 28 | 4 | 10 | 0 / 3 |
| Total | | 440 | 383 | 132 | 27 | 36 | 94 / 71 |

## AMZN

| Period end | 2024-12-31 | 2025-12-31 |
| Filed | 2025-02-07 | 2026-02-06 |
| Item coverage | 97.9% | 97.9% |
| Item 1A. Risk Factors | both | 96 | 0 | 26 | 4 | 5 | 0 / 0 |
| Total | | 584 | 438 | 139 | 48 | 38 | 132 / 120 |

## JPMorgan before the index fix

The first run for JPM, before `filings_of_form` read the older pages of EDGAR's index, ended with exit code 1 and this message:

    SEC EDGAR: JPMORGAN CHASE & CO has 1 10-K filing(s) in EDGAR's recent index; two are needed to compare
