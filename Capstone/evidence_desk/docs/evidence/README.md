# Evidence

Outputs that the README, the check-in and the hand-ins cite, kept here because the places they were first written to (`results/`, `backups/`) are ignored by git. Each file starts with the command that produced it and when.

| File | Command | What it shows |
| --- | --- | --- |
| `verify-fresh.txt` | `make verify-fresh` | The gate, run on a fresh clone of the committed branch: lint, the offline tests, the smoke test, the page test |
| `live-walk.txt` | `make live-walk` | The running app over HTTP on filings fetched live, with recorded model answers: a judged run, decisions, the reviewed brief, a saved thesis run twice, the comparisons, the breakdowns, and a run that asks for the tagged figures |
| `backup-restore.txt` | `make backup && make restore-check` | A backup of the record restores to the same runs, decisions and theses. Same disk, same machine |
| `changes-eight-companies.md` | `make changes ARGS="<TICKER> --form 10-K"`, eight times | The filing comparison on eight companies' annual reports: the filings compared, each run's notes and every row of its table. And the message JPMorgan's run ended with before older index pages were read |
| `breakdowns-eight-companies.md` | `make breakdowns ARGS="<TICKER> --form 10-K"` and `--form 10-Q`, eight times each | Which breakdowns each filing tags, how many members and periods, and whether the members add up to the tagged total; NVIDIA's tables in full |
| `figures-eight-companies.md` | `make figures TICKERS="NVDA AAPL MSFT KO JPM TSLA COST AMZN"`, three times | Each company's quarters as a run sees them, before and after the fix for a year reported in weeks, and after the two faults the command itself found (Amazon, JPMorgan): the lines that moved, and the last run in full |
| `../speed/live-timing-v10.txt`, `../speed/live-timing-v11.txt` | `make time-live` | A live run without a key timed stage by stage inside the run, five runs under each of four conditions, before and after a run stopped fetching two filings twice for their tags |
| `two-writers.txt` | `make two-writers ARGS="--rounds 2000"` | The app and a one-off container writing one scratch record at the same time: no failed write, SQLite's integrity check, every row present and readable |
| `header-cut-fourteen-filings.md` | `make header-cut-check TICKERS="NVDA AAPL MSFT KO JPM TSLA COST AMZN"` | Each of 14 live filings parsed with and without the parser's header cut, the two documents compared whole |
| `events-probe-before.md`, `events-probe-after.md` | `make events-probe` | Every 8-K the eight probe companies filed in the last 12 months: for each item EDGAR's index lists, whether the 8-K splitter found a section headed with it (190 of 200 before two fixes, 200 of 200 after), and each miss with its accession and reason |
| `probe-before-header-cut.md` | `make probe TICKERS="NVDA AAPL MSFT KO JPM TSLA COST AMZN" OUTLINE=1` | The structure of 14 filings as parsed before the parser's one speed change; `../speed/probe-v4.md` is the same probe after it |

These are single runs on one laptop. A file here shows that a command produced that output once; it does not show that it will again.
