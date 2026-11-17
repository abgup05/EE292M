# Item coverage before and after the header cut, eight companies

Before the cut: `results/probe-20261117T114758Z.md` (taken with version 2's parser).
After: `results/probe-20261117T122707Z.md` (`make probe OUTLINE=1 TICKERS="NVDA AAPL MSFT KO JPM TSLA COST AMZN"`, version 3's parser).
Both list the same 14 filings (same accessions). Compared with `diff` after removing the parse-time column:
every row (HTML size, text size, sections, Items found, Item coverage, verdict) and all 1,832 section
lines of the outlines (heading and length) are identical. Parse times (before, after):

| Ticker | Form | Before | After |
|---|---|---:|---:|
| NVDA | 10-K | 0.14 s | 0.14 s |
| NVDA | 10-Q | 0.10 s | 0.09 s |
| AAPL | 10-K | 0.14 s | 0.14 s |
| MSFT | 10-K | 0.60 s | 0.53 s |
| MSFT | 10-Q | 0.41 s | 0.40 s |
| KO | 10-K | 0.26 s | 0.22 s |
| KO | 10-Q | 0.22 s | 0.13 s |
| JPM | 10-K | 1.00 s | 0.92 s |
| JPM | 10-Q | 0.86 s | 0.81 s |
| TSLA | 10-K | 0.26 s | 0.21 s |
| TSLA | 10-Q | 0.11 s | 0.09 s |
| COST | 10-K | 0.12 s | 0.09 s |
| AMZN | 10-K | 0.15 s | 0.12 s |
| AMZN | 10-Q | 0.16 s | 0.13 s |

The table after the cut:

| Ticker | Form | Period end | Accession | HTML size | Text size | Sections | Items found | Item coverage | Parse time | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| NVDA | 10-K | 2026-01-25 | 0001045810-26-000021 | 1,968,291 B | 344,740 chars | 150 | 22 | 96.9% | 0.14 s | segmented |
| NVDA | 10-Q | 2026-07-26 | 0001045810-26-000075 | 1,517,522 B | 151,303 chars | 73 | 9 | 96.5% | 0.09 s | segmented |
| AAPL | 10-K | 2026-09-26 | 0000320193-26-000026 | 1,650,478 B | 237,179 chars | 116 | 23 | 96.3% | 0.14 s | segmented |
| MSFT | 10-K | 2026-06-30 | 0001193125-26-323660 | 8,585,976 B | 327,759 chars | 152 | 22 | 98.2% | 0.53 s | segmented |
| MSFT | 10-Q | 2026-09-30 | 0001193125-26-436133 | 5,483,335 B | 202,652 chars | 85 | 9 | 98.2% | 0.40 s | segmented |
| KO | 10-K | 2025-12-31 | 0001628280-26-010047 | 3,758,615 B | 605,743 chars | 158 | 22 | 98.6% | 0.22 s | segmented |
| KO | 10-Q | 2026-10-02 | 0001628280-26-067844 | 2,207,776 B | 220,266 chars | 69 | 9 | 97.1% | 0.13 s | segmented |
| JPM | 10-K | 2025-12-31 | 0001628280-26-008131 | 12,927,800 B | 1,184,295 chars | 336 | 18 | 99.4% | 0.92 s | segmented |
| JPM | 10-Q | 2026-09-30 | 0001628280-26-069523 | 11,541,094 B | 631,843 chars | 197 | 9 | 1.6% | 0.81 s | not segmented |
| TSLA | 10-K | 2025-12-31 | 0001628280-26-003952 | 2,392,004 B | 398,763 chars | 134 | 22 | 97.9% | 0.21 s | segmented |
| TSLA | 10-Q | 2026-09-30 | 0001628280-26-066775 | 1,605,614 B | 136,849 chars | 59 | 11 | 95.8% | 0.09 s | segmented |
| COST | 10-K | 2026-08-30 | 0000909832-26-000093 | 1,456,959 B | 213,371 chars | 77 | 22 | 96.4% | 0.09 s | segmented |
| AMZN | 10-K | 2025-12-31 | 0001018724-26-000004 | 1,968,817 B | 286,775 chars | 151 | 22 | 97.9% | 0.12 s | segmented |
| AMZN | 10-Q | 2026-09-30 | 0001018724-26-000040 | 1,646,480 B | 204,776 chars | 75 | 11 | 97.9% | 0.13 s | segmented |

