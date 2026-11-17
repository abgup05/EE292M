# Reported figures on eight companies (17 November 2026, live EDGAR)

`make figures TICKERS="NVDA AAPL MSFT KO JPM TSLA COST AMZN"` reads each company's XBRL company facts from EDGAR, builds the report a thesis run builds and prints every quarter in it. Each cell is the display the report carries; the command computes nothing. It was written on 17 November 2026 to check a change to how periods are placed on more than one company, and it found two more faults on its first run.

It was run three times that day:

1. on the code as it was before the fix for companies that report in weeks (commit `28493db`, from a detached checkout with the command copied in and its own image);
2. after that fix (the figures code of commit `27d35ef`);
3. after the two faults it found were fixed (the figures code of commit `6164d7a`): twelve months to a quarter end taken for a fiscal year, and a bank's revenue concept not read.

## What moved between the runs

**Run 1 to run 2** (week-based years). Lines that differ: 14, all of COST. The other seven companies' lines are identical.

```
was: | COST | 2026-05-10 | 84 | $70.53B | reported | +11.6% | +1.3% | n/a |
was: | COST | 2026-02-15 | 84 | $69.60B | reported | +9.2% | +3.4% | n/a |
now: | COST | 2026-08-30 | 112 | $95.72B | derived | +11.1% | n/a | $4.68B |
now: | COST | 2026-05-10 | 84 | $70.53B | reported | +11.6% | +1.3% | $3.45B |
now: | COST | 2026-02-15 | 84 | $69.60B | reported | +9.2% | +3.4% | $3.00B |
was: | COST | 2025-05-11 | 84 | $63.20B | reported | +8.0% | -0.8% | n/a |
was: | COST | 2025-02-16 | 84 | $63.72B | reported | +9.0% | +2.5% | n/a |
now: | COST | 2025-08-31 | 112 | $86.16B | derived | +8.1% | n/a | $3.87B |
now: | COST | 2025-05-11 | 84 | $63.20B | reported | +8.0% | -0.8% | $3.46B |
now: | COST | 2025-02-16 | 84 | $63.72B | reported | +9.0% | +2.5% | $2.75B |
was: | COST | 2024-05-12 | 84 | $58.52B | reported | +9.1% | +0.1% | n/a |
was: | COST | 2024-02-18 | 84 | $58.44B | reported | +5.7% | +1.1% | n/a |
was: - COST: a run would offer 35 figures; 44 of the report's 158 metrics have no value (COSTCO WHOLESALE CORP /NEW). Without a value in some period: capex, fcf_margin, free_cash_flow, operating_cash_flow, receivables, receivables_yoy, revenue_qoq, rnd_ratio.
now: - COST: a run would offer 36 figures; 22 of the report's 152 metrics have no value (COSTCO WHOLESALE CORP /NEW). Without a value in some period: eps_diluted, receivables, receivables_yoy, revenue_qoq, rnd_ratio.
```

**Run 2 to run 3** (fiscal years; a bank's revenue). Lines that differ: 12, all of AMZN, JPM. The other six companies' lines are identical.

```
now: | JPM | 2026-09-30 | 92 | $50.17B | reported | +8.1% | -12.5% | $33.16B |
now: | JPM | 2026-06-30 | 91 | $57.35B | reported | +27.7% | +15.1% | -$25.28B |
now: | JPM | 2026-03-31 | 90 | $49.84B | reported | +10.0% | +8.8% | -$211.76B |
now: | JPM | 2025-12-31 | 92 | $45.80B | derived | +7.1% | -1.4% | $119.72B |
now: | JPM | 2025-09-30 | 92 | $46.43B | reported | +8.8% | +3.4% | -$45.21B |
now: | JPM | 2025-06-30 | 91 | $44.91B | reported | -10.5% | -0.9% | $29.55B |
now: | JPM | 2025-03-31 | 90 | $45.31B | reported | +8.1% | +5.9% | -$251.84B |
now: | JPM | 2024-12-31 | 92 | $42.77B | derived | +10.9% | +0.3% | $147.76B |
was: - JPM: a run would offer 11 figures; 124 of the report's 158 metrics have no value (JPMORGAN CHASE & CO). Without a value in some period: capex, cash, cash_yoy, eps_diluted, fcf_margin, free_cash_flow, gross_margin, inventory, inventory_yoy, net_margin, operating_margin, receivables, receivables_yoy, revenue, revenue_qoq, revenue_yoy, rnd_ratio.
now: - JPM: a run would offer 20 figures; 92 of the report's 158 metrics have no value (JPMORGAN CHASE & CO). Without a value in some period: capex, cash, cash_yoy, eps_diluted, fcf_margin, free_cash_flow, gross_margin, inventory, inventory_yoy, operating_margin, receivables, receivables_yoy, rnd_ratio.
was: - AMZN: a run would offer 26 figures; 35 of the report's 152 metrics have no value (AMAZON COM INC). Without a value in some period: eps_diluted, fcf_margin, gross_margin, net_margin, operating_margin, revenue, revenue_yoy, rnd_ratio.
now: - AMZN: a run would offer 38 figures; 14 of the report's 158 metrics have no value (AMAZON COM INC). Without a value in some period: eps_diluted, rnd_ratio.
```

## Run 3 in full

| Ticker | Quarter ended | Days | Revenue | Revenue is | On a year earlier | On the quarter before | Operating cash flow |
| --- | --- | --- | --- | --- | --- | --- | --- |
| NVDA | 2026-07-26 | 91 | $96.22B | reported | +105.9% | +17.9% | $24.08B |
| NVDA | 2026-04-26 | 91 | $81.61B | reported | +85.2% | +19.8% | $50.34B |
| NVDA | 2026-01-25 | 91 | $68.13B | derived | +73.2% | +19.5% | $36.19B |
| NVDA | 2025-10-26 | 91 | $57.01B | reported | +62.5% | +22.0% | $23.75B |
| NVDA | 2025-07-27 | 91 | $46.74B | reported | +55.6% | +6.1% | $15.37B |
| NVDA | 2025-04-27 | 91 | $44.06B | reported | +69.2% | +12.0% | $27.41B |
| NVDA | 2025-01-26 | 91 | $39.33B | derived | +77.9% | +12.1% | $16.63B |
| NVDA | 2024-10-27 | 91 | $35.08B | reported | +93.6% | +16.8% | $17.63B |
| AAPL | 2026-09-26 | 91 | $114.48B | derived | +11.7% | +4.6% | $28.10B |
| AAPL | 2026-06-27 | 91 | $109.42B | reported | +16.4% | -1.6% | $34.37B |
| AAPL | 2026-03-28 | 91 | $111.18B | reported | +16.6% | -22.7% | $28.70B |
| AAPL | 2025-12-27 | 91 | $143.76B | reported | +15.7% | +40.3% | $53.92B |
| AAPL | 2025-09-27 | 91 | $102.47B | derived | +7.9% | +9.0% | $29.73B |
| AAPL | 2025-06-28 | 91 | $94.04B | reported | +9.6% | -1.4% | $27.87B |
| AAPL | 2025-03-29 | 91 | $95.36B | reported | +5.1% | -23.3% | $23.95B |
| AAPL | 2024-12-28 | 91 | $124.30B | reported | +4.0% | +30.9% | $29.93B |
| MSFT | 2026-09-30 | 92 | $92.28B | reported | +18.8% | +2.5% | $58.00B |
| MSFT | 2026-06-30 | 91 | $90.01B | derived | +17.7% | +8.6% | $55.44B |
| MSFT | 2026-03-31 | 90 | $82.89B | reported | +18.3% | +2.0% | $46.68B |
| MSFT | 2025-12-31 | 92 | $81.27B | reported | +16.7% | +4.6% | $35.76B |
| MSFT | 2025-09-30 | 92 | $77.67B | reported | +18.4% | +1.6% | $45.06B |
| MSFT | 2025-06-30 | 91 | $76.44B | derived | +18.1% | +9.1% | $42.65B |
| MSFT | 2025-03-31 | 90 | $70.07B | reported | +13.3% | +0.6% | $37.04B |
| MSFT | 2024-12-31 | 92 | $69.63B | reported | +12.3% | +6.2% | $22.29B |
| KO | 2026-10-02 | 91 | $13.38B | reported | +7.4% | +0.0% | $4.93B |
| KO | 2026-07-03 | 91 | $13.38B | reported | +6.7% | +7.3% | $5.52B |
| KO | 2026-04-03 | 93 | $12.47B | reported | +12.1% | +5.5% | $2.02B |
| KO | 2025-12-31 | 96 | $11.82B | derived | +2.4% | -5.1% | $3.76B |
| KO | 2025-09-26 | 91 | $12.46B | reported | +5.1% | -0.6% | $5.04B |
| KO | 2025-06-27 | 91 | $12.54B | reported | +1.4% | +12.6% | $3.81B |
| KO | 2025-03-28 | 87 | $11.13B | reported | -1.5% | -3.6% | -$5.20B |
| KO | 2024-12-31 | 95 | $11.54B | derived | +6.4% | -2.6% | $3.95B |
| JPM | 2026-09-30 | 92 | $50.17B | reported | +8.1% | -12.5% | $33.16B |
| JPM | 2026-06-30 | 91 | $57.35B | reported | +27.7% | +15.1% | -$25.28B |
| JPM | 2026-03-31 | 90 | $49.84B | reported | +10.0% | +8.8% | -$211.76B |
| JPM | 2025-12-31 | 92 | $45.80B | derived | +7.1% | -1.4% | $119.72B |
| JPM | 2025-09-30 | 92 | $46.43B | reported | +8.8% | +3.4% | -$45.21B |
| JPM | 2025-06-30 | 91 | $44.91B | reported | -10.5% | -0.9% | $29.55B |
| JPM | 2025-03-31 | 90 | $45.31B | reported | +8.1% | +5.9% | -$251.84B |
| JPM | 2024-12-31 | 92 | $42.77B | derived | +10.9% | +0.3% | $147.76B |
| TSLA | 2026-09-30 | 92 | $28.05B | reported | -0.2% | -0.7% | $6.26B |
| TSLA | 2026-06-30 | 91 | $28.24B | reported | +25.5% | +26.1% | $4.70B |
| TSLA | 2026-03-31 | 90 | $22.39B | reported | +15.8% | -10.1% | $3.94B |
| TSLA | 2025-12-31 | 92 | $24.90B | derived | -3.1% | -11.4% | $3.81B |
| TSLA | 2025-09-30 | 92 | $28.09B | reported | +11.6% | +24.9% | $6.24B |
| TSLA | 2025-06-30 | 91 | $22.50B | reported | -11.8% | +16.3% | $2.54B |
| TSLA | 2025-03-31 | 90 | $19.34B | reported | -9.2% | -24.8% | $2.16B |
| TSLA | 2024-12-31 | 92 | $25.71B | derived | +2.1% | +2.1% | $4.81B |
| COST | 2026-08-30 | 112 | $95.72B | derived | +11.1% | n/a | $4.68B |
| COST | 2026-05-10 | 84 | $70.53B | reported | +11.6% | +1.3% | $3.45B |
| COST | 2026-02-15 | 84 | $69.60B | reported | +9.2% | +3.4% | $3.00B |
| COST | 2025-11-23 | 84 | $67.31B | reported | +8.3% | n/a | $4.69B |
| COST | 2025-08-31 | 112 | $86.16B | derived | +8.1% | n/a | $3.87B |
| COST | 2025-05-11 | 84 | $63.20B | reported | +8.0% | -0.8% | $3.46B |
| COST | 2025-02-16 | 84 | $63.72B | reported | +9.0% | +2.5% | $2.75B |
| COST | 2024-11-24 | 84 | $62.15B | reported | +7.5% | n/a | $3.26B |
| AMZN | 2026-09-30 | 92 | $201.94B | reported | +12.1% | +0.7% | $42.42B |
| AMZN | 2026-06-30 | 91 | $200.61B | reported | +19.6% | +10.5% | $45.39B |
| AMZN | 2026-03-31 | 90 | $181.52B | reported | +16.6% | -14.9% | $26.03B |
| AMZN | 2025-12-31 | 92 | $213.39B | derived | +13.6% | +18.4% | $54.46B |
| AMZN | 2025-09-30 | 92 | $180.17B | reported | +13.4% | +7.4% | $35.52B |
| AMZN | 2025-06-30 | 91 | $167.70B | reported | +13.3% | +7.7% | $32.52B |
| AMZN | 2025-03-31 | 90 | $155.67B | reported | +8.6% | -17.1% | $17.02B |
| AMZN | 2024-12-31 | 92 | $187.79B | derived | +10.5% | +18.2% | $45.64B |

- NVDA: a run would offer 37 figures; 2 of the report's 158 metrics have no value (NVIDIA CORP). Without a value in some period: eps_diluted.
- AAPL: a run would offer 37 figures; 2 of the report's 152 metrics have no value (Apple Inc.). Without a value in some period: eps_diluted.
- MSFT: a run would offer 37 figures; 2 of the report's 158 metrics have no value (MICROSOFT CORP). Without a value in some period: eps_diluted.
- KO: a run would offer 38 figures; 14 of the report's 158 metrics have no value (COCA COLA CO). Without a value in some period: eps_diluted, rnd_ratio.
- JPM: a run would offer 20 figures; 92 of the report's 158 metrics have no value (JPMORGAN CHASE & CO). Without a value in some period: capex, cash, cash_yoy, eps_diluted, fcf_margin, free_cash_flow, gross_margin, inventory, inventory_yoy, operating_margin, receivables, receivables_yoy, rnd_ratio.
- TSLA: a run would offer 38 figures; 2 of the report's 158 metrics have no value (Tesla, Inc.). Without a value in some period: eps_diluted.
- COST: a run would offer 36 figures; 22 of the report's 152 metrics have no value (COSTCO WHOLESALE CORP /NEW). Without a value in some period: eps_diluted, receivables, receivables_yoy, revenue_qoq, rnd_ratio.
- AMZN: a run would offer 38 figures; 14 of the report's 158 metrics have no value (AMAZON COM INC). Without a value in some period: eps_diluted, rnd_ratio.

## What this does and does not show

- It shows which lines a change moved, and that the others did not move. It does not show that a figure is right: the only values checked against published numbers are the 28 annual ones of the answer key in `tests/test_facts.py` (Apple, Microsoft, NVIDIA).
- Costco's fourth quarter is 16 weeks (112 days) and is derived as the fiscal year less the 36 weeks to date. It is compared with the fourth quarter a year earlier and not with the 12-week quarter before it.
- JPMorgan's "revenue" is its total net revenue (`RevenuesNetOfInterestExpense`). Its operating cash flow swings by hundreds of billions between quarters, which is what a bank's cash flow statement does; the free-cash-flow and margin figures built on it mean little for a bank, and nothing in the tool says so.
- No company has a diluted EPS for a derived fourth quarter: per-share values are never differenced. Coca-Cola and Amazon report no research and development expense under the concept the tool reads.
- The companies were chosen once, as the eight the parser is probed on. Nothing here says how the next company will read.
