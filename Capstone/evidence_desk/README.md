# Evidence Desk

Evidence Desk tests the claims of an investment thesis against a company's own SEC filings. It is for an equity analyst who has to decide whether a thesis still holds after a new filing: you enter a ticker, the decision and the claims; it reads the latest annual report (10-K) and the quarterly reports (10-Q) filed after it, computes the company's reported figures from its XBRL facts, and returns a verdict for each claim with the exact passages and figures behind it.

Two things are checked by the backend before anything reaches the page or the Markdown export: every quote is found word for word in the stored filing text, and every number in a finding is matched to one of its quotes or to a reported figure it cites. One thing is not checked: whether a quote means what the finding says. That is the engine's reading, and the page says so beside every verdict. So you accept or reject each finding yourself, and a second verdict follows, by the same rule, from the findings you accepted. A thesis can be saved and run again when a new filing arrives; the page then shows which verdicts moved.

This is version 4 (tag `capstone-v4`) of the capstone. The plan and the milestones are in [`../README.md`](../README.md), the design is in [`ARCHITECTURE.md`](ARCHITECTURE.md), and the tests are described in [`docs/testing.md`](docs/testing.md).

![A recorded run: verdicts first, then the summary and the reported figures](docs/screenshots/sample-run.png)

## Run it

You need Docker running and Make. From this directory, or from the repository root:

```sh
cp .env.example .env   # optional: ANTHROPIC_API_KEY, ANTHROPIC_MODEL, SEC_USER_AGENT
make up                # http://127.0.0.1:8766
make down
```

- **Without any key** the app works on real filings: the deterministic engine quotes the sentences that best match each claim and judges no stance, so claims read "passages found, not judged". **Reported figures only** needs just a ticker.
- **With `ANTHROPIC_API_KEY`** Claude plans the retrieval queries, drafts findings with a stance and writes the summary. The same checks apply to everything it returns.
- **Without the network or a key** you can still see a judged run: open <http://127.0.0.1:8766/?sample>, or run `make replay`. Both use three recorded NVIDIA filings and model answers replayed from a cassette ([`docs/cassettes.md`](docs/cassettes.md)).
- **With the network and no key**, `make up-recorded` starts the app with those recorded answers: **Load example**, then **Test the thesis**, gives the judged run on filings fetched live, and you can review it and save it. This works while NVIDIA's reported facts are as they were on 17 November 2026; after its next filing the prompts will no longer match the recording, and the run will fall back to the keyless engine and say so.

## What you see

1. Click **Load example** (five claims about NVIDIA) and **Test the thesis**.
2. The banner gives the status and what was read, each number with its denominator.
3. The verdicts come first, one row per claim, each naming the engine that assessed it. A legend on the page says what every mark means.
4. The reported figures follow: the newest quarter and the newest fiscal year, each figure opening to its arithmetic and the reported facts it used, with charts over time.
5. Open a claim to read its findings. Each excerpt is shown in its surrounding text with the Item of the filing it sits under and a link that opens the filing at that passage. Each finding lists its checks: the quote was found, the numbers matched, and whether its meaning was checked.
6. **Accept** or **Reject** each finding, with a note if you like. The scorecard shows two verdicts per claim: the engine's, and the one that follows from the findings you accepted. Undecided findings do not count toward yours.
7. **Save this thesis**, and later **Run again on the latest filings**. **What moved** compares the two newest runs: which verdicts changed, which excerpts are new, which filing is new.
8. **Download Markdown brief** exports the verified record; once every finding is decided, **Download reviewed brief** includes your decisions.

From the command line, `make run ARGS='example'` runs the same pipeline and writes `results/<run-id>.json` and `.md`. `make probe TICKERS="AAPL COST"` reports how well a company's filings split into their Items.

## The system

```mermaid
flowchart LR
  subgraph LAPTOP["My laptop (macOS)"]
    BROWSER["Browser<br/>runs the page's JavaScript:<br/>draws and polls, computes no result"]
    subgraph CLONE["Git clone of this repository"]
      CODE["Code<br/>src/, tests/, uitests/, docker/"]
      REC["Recorded data, in git<br/>EDGAR fixtures, cassette,<br/>golden records, golden set"]
      ENVF[".env<br/>API key, SEC user agent<br/>gitignored"]
      RECORD[("data/record/record.sqlite<br/>runs, decisions, saved theses<br/>gitignored; cannot be rebuilt")]
      CACHE[("data/cache/filings.sqlite<br/>filing text, once per filing<br/>gitignored; disposable")]
      BACKUPS["backups/<br/>copies of the record<br/>gitignored; same disk"]
      RESULTS["results/<br/>exports and probe reports<br/>gitignored; disposable"]
    end
    subgraph DOCKER["Docker Compose, started only by make"]
      APP["app container, make up<br/>FastAPI routes, pipeline, gate, policy<br/>published on 127.0.0.1:8766 only"]
      ONEOFF["one-off app containers<br/>make test, run, probe, replay,<br/>fixtures, eval, backup"]
      SHOTS["shots<br/>headless Chromium"]
      LOCK["lock (uv) and jscheck (node)"]
    end
  end
  GITHUB["GitHub, private repository<br/>second copy of code and recorded data"]
  SEC["SEC EDGAR<br/>the original filings and XBRL facts"]
  PAGES["Public web pages<br/>up to five a user adds to a run"]
  MODEL["Anthropic API<br/>optional"]
  REG["Registries, at build time<br/>PyPI, ghcr.io, Docker Hub"]
  APP -->|"serves the page"| BROWSER
  BROWSER -->|"JSON over HTTP, 127.0.0.1:8766"| APP
  CODE -->|"bind mount at /work"| APP
  CODE -->|"bind mount at /work"| ONEOFF
  ENVF -->|"environment variables"| APP
  REC -->|"fixtures for tests,<br/>recorded answers for replay"| ONEOFF
  APP <--> RECORD
  APP <--> CACHE
  ONEOFF <--> RECORD
  ONEOFF --> RESULTS
  RECORD -->|"make backup"| BACKUPS
  SEC -->|"HTTPS, one way,<br/>at most 7 requests a second"| APP
  SEC -->|"make probe, fixtures, eval"| ONEOFF
  PAGES -->|"HTTPS; private addresses refused"| APP
  APP -->|"HTTPS: passages as data in,<br/>drafted findings out"| MODEL
  REG -->|"image build"| APP
  REG -->|"make lock"| LOCK
  SHOTS -->|"http://app:8000"| APP
  SHOTS -->|"docs/screenshots"| CODE
  LOCK -->|"uv.lock"| CODE
  CODE <-->|"git over HTTPS"| GITHUB
  REC <-->|"git over HTTPS"| GITHUB
```

**Where each part runs.** Everything runs on one laptop. The served backend is one container. The page's JavaScript runs in the browser, not in the container that serves it. `make test`, `run`, `probe`, `replay`, `fixtures`, `eval` and `backup` each start a separate short-lived container from the same image; these bypass the served app, and the ones that read filings reach EDGAR themselves. Nothing listens beyond `127.0.0.1`.

**How code reaches it.** The repository is mounted into every container, so the running code is the working tree. Dependencies are installed when the image is built, from PyPI and the container registries, never while it runs. The only other copy of the code is the private GitHub repository, reached by `git push` over HTTPS.

**How data reaches it.** Filings and XBRL facts come one way from SEC EDGAR over HTTPS; nothing is written to EDGAR. A user may add up to five public pages to a run, fetched with private addresses refused. With a key, passages go to the Anthropic API as data and drafted findings come back.

**What cannot be rebuilt.** The storage is split along that line: a record that is backed up, and a cache that can be deleted.

| Data | Can it be rebuilt? | Copies |
| --- | --- | --- |
| Run records, decisions on findings, saved theses: `data/record/record.sqlite` | **No.** A run's inputs move: the facts feed changes with every filing and restatement, the list of "latest" filings moves, the parser changes, and a model does not repeat itself. A decision is a person's and exists nowhere else | The laptop, and `backups/` on the same disk (`make backup`, checked by `make restore-check`). **No copy off the laptop** |
| Filing text: `data/cache/` | Yes, from EDGAR, by the parser version that produced it | The laptop; disposable |
| The facts feed and the list of filings, as they were | No: EDGAR serves their current state | EDGAR |
| Recorded fixtures and golden records | Only as a new baseline: recording again gives different facts and moves the tripwire | Laptop and GitHub |
| The cassette of model answers | No | Laptop and GitHub |
| `results/` | Disposable. One copy; what is worth keeping is copied into `demo/` or `docs/` and committed | The laptop |
| Keys in `.env` | Yes, reissued by the provider | The laptop |

## Measured results (17 November 2026)

**A recorded, model-backed run** (`make replay`; the record is [`demo/recorded-run-v3.md`](demo/recorded-run-v3.md)). The example thesis on NVIDIA's 10-Q for the period ended 2026-07-26, its 10-Q for 2026-04-26 and its 10-K for 2026-01-25:

| | |
| --- | --- |
| Status | **COMPLETE** |
| Sources read | 3 of 3 filings, plus the XBRL company facts; 636 passages indexed |
| Verdicts | 2 supported, 3 mixed evidence, of 5 claims |
| Findings | 18 of 18 proposed findings verified, 0 withheld |
| Quotes | 18 of 18 found word for word in the stored filings |
| Numbers in findings | 25 checked against quotes and cited figures, 0 unmatched |
| Reported figures | 156 computed (2 more reported as unavailable, with the reason) |

The model answers in that run did **not** come through the Anthropic API. The API refused every call from this project for lack of credit, so the engine's exact prompts were answered by Claude Sonnet 5.5 running as a Claude Code subagent and recorded ([how, and what that limits](demo/cassettes/nvda-example/README.md)). The instructions around those prompts repeated the engine's rule about exact quotes, so 18 of 18 is an upper bound on what the API path would give. The first recording verified 15 of 18: three quotes read "Compute &amp;amp; Networking", as the prompt had escaped them, and the gate could not find them. That was a bug in the engine, now fixed with a test.

**Reported figures against an answer key.** Fiscal-year revenue and net income computed from XBRL facts equal the values published in the companies' annual reports for Apple (fiscal 2022 to 2024), Microsoft (2023, 2024) and NVIDIA (2024, 2025), fourteen figures in all, and the revenue growth rates derived from them. Wherever a company reported both a quarter and the year-to-date totals around it, the differenced value equals the reported one, except one NVIDIA quarter that differs by USD 1 million because each figure was rounded on its own.

**Filing structure on eight companies** (`make probe`, 14 filings): NVIDIA, Apple, Microsoft, Coca-Cola, Tesla, Costco and Amazon split into their Items with 95.8% to 98.6% of their text under a numbered Item. JPMorgan's 10-Q does not (1.6%): it prints no Item headings over its body. Its 10-K scores 99.4%, which overstates it, because its annual report follows Item 15 and is all labelled under that Item. The probe found three parser faults that NVIDIA's filings had hidden; all three are fixed and Costco's 10-K is now a second full-size fixture.

**The live application, end to end** (`make live-walk`: the running app over HTTP, live EDGAR, recorded answers). One walk on 17 November: the example run finished complete with 3 of 3 filings fetched live, 18 of 18 findings verified and no engine fallback; two decisions were recorded and the reviewed verdicts returned; the thesis was saved and run twice more, the later runs reading all three filings from the cache; the comparison reported "No verdict moved and no filing is new."

**Retrieval, measured on a golden set** (`make eval ARGS="run --variant claim"`). Thirty cases over five companies, each an analyst's claim in its own words with the excerpt a correct answer must cite. With BM25 on the claim's words alone, the passage is in the eight shown to the engine for **7 of 24** answerable cases (29.2%), and in the top twenty for 13 of 24. The claims are paraphrases, and keyword matching misses them. The cases were drafted by a model from the filing text and validated mechanically; no person has yet read them one by one ([`eval/README.md`](eval/README.md)).

**Backup and restore** (`make backup`, `make restore-check`). On the live record after that walk: "PASS: record-20261117T123824Z.sqlite restores to the live record: 5 runs, 2 decisions, 1 theses".

**Speed** ([`docs/speed.md`](docs/speed.md)). The offline profile is not where a real run's time goes: a real run waits on EDGAR and, with a key, on the model, which has never been timed. What was measured: a first live keyless run took 1.01 s and a second, with all three filings read from the cache, 0.38 s (one pair of runs). Offline, cutting the inline-XBRL header before parsing saves a median of 28.8 ms per run over 20 alternating pairs (faster in 18 of 20), about 7 to 9% of the offline run and well under 1% of a live one, with identical output on all 14 probed filings. Saving progress without forcing each commit to disk took 24 saves from 33 ms to 14 ms. Concurrent assessment of claims is a mechanism that is tested; its gain with a real model is unmeasured.

**The live keyless path** was measured in version 2: three filings fetched from EDGAR and parsed, 636 passages indexed, 15 of 15 quotes verified, 3.2 s ([`demo/demo-2026-11-17-v2.md`](demo/demo-2026-11-17-v2.md)).

## Verification

```sh
make verify         # build, lint, 805 offline tests, smoke test, browser-level test
make test           # offline tests only (T=tests/test_gate.py for one file)
make golden-check   # the tripwire: one recorded run, compared stage by stage
make replay         # the recorded model-backed run, offline
make uitest         # headless Chromium renders two records; 33 assertions on the DOM
make live-walk      # the running app end to end over HTTP: needs EDGAR, no key
make eval ARGS="run --variant claim"   # score retrieval on the golden set
make backup         # copy the record to backups/; make restore-check proves it restores
make screenshots    # renders the page into docs/screenshots, for a person to look at
```

[`docs/testing.md`](docs/testing.md) names one test at each of four levels, the wrong programs each new test now fails on, the tripwire and how to read it, and what no test here can see.

## Known limitations

- **The Anthropic API path has not been exercised live since version 1** (22 October). The engine is tested against a stub client and through recorded answers; neither exercises the SDK call.
- **Whether a quote supports the statement made about it is not checked.** The quote check and the number check are mechanical. A second-model check of meaning is milestone 5; until then a "Supported" verdict rests on a model's reading of real sentences.
- **Retrieval is the weakest part.** With keyword ranking on the claim's own words, the passage that matters is among the eight shown to the engine in 7 of 24 golden cases. A claim can read "not addressed", or be judged on weaker evidence, when the filing does address it. Model-written queries are used when a model is configured; their effect is not yet measured.
- **The record has no copy off this laptop.** `make backup` writes to the same disk.
- **The number check has blind spots.** It ignores numbers written as words, bare integers up to 12, and years; it accepts a table number at any of four scales. It catches a figure that is nowhere in the evidence, not one that is attached to the wrong thing.
- **Filings without Item headings over their body** (JPMorgan's 10-Q) are kept and quotable but located by sub-heading only; the run says so.
- **The page was checked by eye from four screenshots** and by a DOM test, not by a user. Dark mode and the links that open a filing at a passage were not checked in a real browser.
- Only 10-K and 10-Q filers. No PDFs, 8-K exhibits, foreign filers or transcripts. Runs execute in a worker thread inside the API process; there is no queue and no resume after a restart.
