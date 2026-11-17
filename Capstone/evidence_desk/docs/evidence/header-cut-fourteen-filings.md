# Cutting the inline-XBRL header before parsing: the whole document, on fourteen live filings

`make header-cut-check TICKERS="NVDA AAPL MSFT KO JPM TSLA COST AMZN"`, run on 2026-11-17T18:34:34Z against live SEC EDGAR. Each filing is parsed twice, with the parser's header cut and with it switched off, and the two documents are compared whole: the text, its hash and every section. Review 6 asked for this: until then the seven companies other than NVIDIA and Costco had been compared by their section headings and lengths only.

| Ticker | Form | Period end | Has an ix:header | Text, characters | SHA-256 of the text | Same document without the cut |
| --- | --- | --- | --- | --- | --- | --- |
| NVDA | 10-K | 2026-01-25 | yes | 344,740 | 9925c5689449a66c… | yes |
| NVDA | 10-Q | 2026-07-26 | yes | 151,303 | 53e6daca7f0d5bab… | yes |
| AAPL | 10-K | 2026-09-26 | yes | 237,179 | d5e4e0a808cd311e… | yes |
| MSFT | 10-K | 2026-06-30 | yes | 327,759 | b268cfbae2252aba… | yes |
| MSFT | 10-Q | 2026-09-30 | yes | 202,652 | 7f292edd4a00e38b… | yes |
| KO | 10-K | 2025-12-31 | yes | 605,743 | 246290c9922b5019… | yes |
| KO | 10-Q | 2026-10-02 | yes | 220,266 | dce8370b3b421597… | yes |
| JPM | 10-K | 2025-12-31 | yes | 1,184,295 | 313da9330de4e03f… | yes |
| JPM | 10-Q | 2026-09-30 | yes | 631,843 | 2bbc10f3f95ba8f9… | yes |
| TSLA | 10-K | 2025-12-31 | yes | 398,763 | 0f44e4c92a987767… | yes |
| TSLA | 10-Q | 2026-09-30 | yes | 136,849 | 1f2f67e052a198fb… | yes |
| COST | 10-K | 2026-08-30 | yes | 213,371 | 1a49fb5011af66fb… | yes |
| AMZN | 10-K | 2025-12-31 | yes | 286,775 | 9e1a8bd7a923fac0… | yes |
| AMZN | 10-Q | 2026-09-30 | yes | 204,776 | d1c5805957fb42f6… | yes |
14 of 14 filings parse to the same document with and without the header cut; 0 could not be compared.

It shows that the two parses agree on these filings on this day. It says nothing about a filing nobody has parsed.
