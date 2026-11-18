# The page's design

Evidence Desk's page is a research note. It has one layout and one set of components, drawn in
two themes:

- **Paper** is the note as printed: warm paper, ink, a serif for prose and claims, hairline rules,
  and small capitals for labels.
- **Terminal** is the same note as a dense dark screen: near-black, a monospace for every label,
  number and control, an amber accent, and tighter rows.

Every rule in `src/web/styles.css` reads tokens only. The themes differ in their token values and
in a few rules scoped to `:root[data-theme="terminal"]`. The specimen page,
`src/web/specimen.html`, shows every component once on made-up data. It is linked from nowhere:
open it from disk, or see `docs/screenshots/specimen*.png` (`make screenshots`).

## The boundary still holds

The page draws and computes nothing a scientist would call a result. Every verdict, count,
outcome, change, flip and percentile on it is a record field or wording from `/api/meta`.
Three things are drawing, not computing:

- the time line places record dates on an axis;
- a sparkline places a series' values in a box;
- a negative number is set in `--neg` from the sign of the record's own value or display string.

Text from filings and from models is inserted as text, never as HTML.

## Themes and how one is chosen

The theme is `data-theme="paper|terminal"` on `<html>`. A small inline script sets it before the
first paint, and `app.js` owns it after that. It is chosen in this order:

1. `?theme=paper` or `?theme=terminal` in the address. This applies to one page load and is
   never stored; screenshots use it.
2. The reader's choice, from the toggle in the bar or the `t` key. It is stored under
   `localStorage["evidence-desk-theme"]` when the browser allows storage. Every read and write is
   wrapped in `try`, so the page works without storage.
3. The system: `prefers-color-scheme: dark` gives Terminal. With no stored choice, the page
   follows the system when it changes.

Without JavaScript, a dark system still gets the Terminal colours through
`@media (prefers-color-scheme: dark) :root:not([data-theme])`.

## Colour tokens: one meaning each

Colour is never the only signal: every mark also carries its glyph and its words.

| Token | Paper | Terminal | Meaning, and only this |
|---|---|---|---|
| `--bg` / `--surface` / `--surface-2` | #f2eee3 / #fbf9f3 / #ece6d8 | #07090c / #0d1116 / #151b22 | the page, the note's sheet, a raised row |
| `--ink` / `--ink-2` | #1d1b17 / #57524a | #e8e3d4 / #9ba4ae | text, secondary text |
| `--line` / `--line-strong` | #d9d1bf / #958c78 | #222b35 / #46525f | hairlines, rules |
| `--accent` | #1f4e8c ink blue | #ffad33 amber | something you can click, and focus. Never a heading. |
| `--support` | #1d6b3f | #62d28f | ✓ supported, a supporting finding, a test that holds |
| `--challenge` | #9a1f5a | #ff7ab8 | ✕ challenged, a challenging finding, a test that fails (± mixed shows both) |
| `--neutral` | #575c64 | #a4acb6 | ? not judged (dashed), ∅ not addressed, • context, tags about the page |
| `--limit` | #8a5800 | #f0dc5a | ▲ a limit of the record, including evidence an 8-K postdates |
| `--model` | #5a3fb8 | #b9a3ff | ✎ written by a model (solid rule); ◎ ◐ a second model's reading (double rule) |
| `--reject` | #b3261e | #ff6b6b | ! the server refused your input |
| `--rule` | #586112 | #b5cc6a | ƒ computed by a fixed rule (dotted border) |
| `--change` | #0b6670 | #5ad7e4 | # ~ + − what changed between two filings (square tags) |
| `--neg` | #9b3412 | #ff8a65 | a negative number, which always keeps its minus sign |
| `--mark-bg` | #f5df7a | #4d3f00 | a quote found word for word, inside its context |
| `--ink`, inverted | | | ▣ ☒ your own decision. A dark filled tag is only ever the reader's. |

The Terminal limit is sulphur yellow so that it is never confused with the amber accent.

**Contrast (WCAG AA).** Every token used as text was measured against `--bg`, `--surface` and
`--surface-2`, and against its own tint background. The lowest pair is Paper `--limit` on
`--surface-2`, at 4.85:1; the lowest in Terminal is `--reject` on its tint, at 6.03:1. All pairs
are at or above 4.5:1. Primary buttons are 7.9:1 on Paper and 10.7:1 on Terminal. These ratios
were computed from the hex values; they were not measured on screen.

## Type

There are no web fonts and nothing is fetched. These are system stacks:

| Stack | Fonts, in order |
|---|---|
| serif | Iowan Old Style, Charter, Bitstream Charter, Sitka Text, Cambria, Source Serif 4, Noto Serif, Georgia, FreeSerif |
| sans | -apple-system, Segoe UI, Helvetica Neue, Noto Sans, FreeSans, system-ui |
| mono | SF Mono, ui-monospace, JetBrains Mono, IBM Plex Mono, Cascadia Mono, Menlo, Consolas, DejaVu Sans Mono, Liberation Mono, FreeMono |

The Free\* faces come last. They are what the headless Chromium used for the screenshots
actually has, so the screenshots show a fallback, not a Mac.

Each kind of text is set through a role token:

| Role | Paper | Terminal |
|---|---|---|
| `--font-prose`: claims, the summary, findings | serif | sans |
| `--font-ui`: body, hints | sans | sans |
| `--font-control`: buttons, field labels, links in the bar | sans | mono |
| `--font-label`: block titles, column heads | serif, small capitals | mono, spaced capitals |
| `--font-data`: counts, tables, dates | sans | mono |
| `--font-code`: tickers, accessions, expressions | mono | mono |

Numbers are `tabular-nums` everywhere. The scale steps by about 1.2: 0.72, 0.8125, 0.9375,
1.0625, 1.3125, 1.75 and 2.375 rem. Data is dense; prose has room, with 72 characters at most
and a line height of 1.6.

## Layout

Two layouts, chosen by whether anything is on screen (`body.is-first` while `#empty-state` shows).

**The first screen: the form is the page.** It has three parts, top to bottom:

- *The lead* (the guide, `#howto`, open): one line of what this is, the takeaway, the configured engine, and the recorded samples as a list, each with what it shows.
- *The thesis form*, centred in one framed column, with the example loader beside the submit button.
- *How it works* (the four steps), below the form.

```
┌ bar ─ § Evidence Desk │ TICKER [NVDA] / │                         Paper|Terminal t │ Keys ? ┐
│ Test an investment thesis against …      │ RECORDED SAMPLES                               │
│ takeaway · configured engine             │ See a recorded run — what it shows …           │
├──────────────────────────────────────────┴───────────────────────────────────────────────┤
│                   ┌ YOUR THESIS ── decision · claims · Test | Load the example ┐         │
│                   └ lookups · saved theses · recent runs ──────────────────────┘         │
│                   HOW IT WORKS 1 2 3 4 · the illustrative record                         │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

**A run or another record: the note takes the whole width.** The form becomes a drawer from the left, opened by the bar's **Thesis** button or `e`. Esc, Close or the scrim closes it, and a refused field opens it. The run reads answer first:

```
┌ bar ─ § │ TICKER │ Thesis e │ (sample tag · Leave the sample) How to read this │ theme │ Keys ┐
│ STATUS ▲ Partial │ ENGINE read … / checked … (cut short; hover or focus) │ AS OF …        │
├──────────────────────────────────────────────────────────────────────────────────────────┤
│ company head (decision, engines, as of, the sample's provenance in one line)             │
│ ▲ Partial · 3 of 3 sources · 6 of 8 findings verified · 2 withheld · ▲ limits  all counts│
│ TAPE  revenue │ growth │ gross margin │ operating margin │ FCF margin │ diluted EPS       │
│ VRD   engine stamp │ after your review │ claim │ evidence                                │
│ TL    the time line                                                                      │
│ MOV · SUM · CLM dockets (quotes in the margin) · WHD (one line, folded) · FIG · EVT ·     │
│ UNK|NXT · SRC · LIM|ERR · the marks · provenance                                         │
└ (Terminal) status footer: / ticker  e thesis  j k claims  t theme  ? keys   run-id · status┘
```

At phone width the bar wraps, the tape is two columns, and a docket's stamp goes under its claim. Widths inside the note respond to the note's own width (container queries), not to the window's.

### What left the reading path, and where it lives now

| Was in view on every run | Now |
|---|---|
| The intro strip under the bar (takeaway, sample links) | "How to read this" (`#howto`), a panel opened from the bar. It is the lead of the first screen. |
| "Configured engine …" (`#engine-line`) | "How to read this". The engines that did the work stay in the bar and in the head. |
| "Each verdict follows by a fixed rule …" (`#distinction`) | "How to read this", under "How to read a run". It still names which model checked the meaning. |
| The time line's long caption | "How to read this"; the marks keep their tooltips, titles and the legend. |
| The sample note, shown twice | Once, in the head: its first sentence in view and the whole note one click away. |
| The coverage box | The status line, with every count one click away in the same element. |
| The withheld findings, open | One line with the record's count and the kinds of reason; the findings are one click away. |

The honesty labels stay in view and unshortened in meaning:

- which engine read and which checked (the bar and the head);
- "Model-written, not checked …" on the summary and on every reason;
- the sample's provenance;
- the caution and the 8-K note on each claim;
- the limit glyph on the status line.

## Components, and when to use each

**Command bar.** It holds the ticker (the `/` key focuses it), the theme switch and the keys. Beside a result it also holds:

- **Thesis**, which opens the form drawer (`e`);
- **How to read this**;
- in sample mode, the sample tag and **Leave the sample**.

On a run it adds a second row with three cells:

- the status: its glyph and word, never filled;
- the engines as the record names them, read by and checked by. Each is cut short to one line, focusable, and whole on hover or focus, with its full text as the title;
- `run.as_of.line`, with a link to the 8-K register.

The second row is hidden on every view that is not a run.

**Status line** (`#status-banner`). One line under the head. It shows:

- the status;
- `sources_read` of `sources_requested` sources;
- `findings_verified` of `findings_proposed` findings verified;
- `findings_withheld` withheld;
- the limit mark when the run has coverage limits.

It is the summary of a `<details>` whose body is the full strip: the status note, every count and the limit lines. Every count is a `[data-coverage]` node holding the record's number. A partial or failed run gets a limit rule at its left edge, and a running run's line is dashed.

**Tape** (`#tape`). The newest period's key figures in one dense row under the status line:

- revenue;
- year-over-year growth;
- gross margin;
- operating margin;
- free cash flow margin;
- diluted EPS.

Each cell is a metric from `run.metrics`: the quarter's when the record has one, else the year's. It shows the metric's label, its `display` string (split at the decimal point, not reformatted) and its sparkline from `run.series`. The period label heads the row. Selecting a cell opens that figure, with its arithmetic, among the reported figures. A key the record lacks has no cell.

**Panel codes.** Every block title carries a short code in `data-code`:

| Code | Block |
|---|---|
| VRD | Verdicts |
| TL | Time line |
| MOV | What moved |
| SUM | Summary |
| CLM | Claims |
| WHD | Withheld |
| FIG | Figures |
| EVT | 8-Ks |
| UNK | Unknowns |
| NXT | Next |
| SRC | Sources |
| LIM | Limits |
| ERR | Errors |
| RUN | Runs |

Terminal draws each code as a solid bar with an amber code cell. Paper keeps its small-capital rule and does not show the code.

**Terminal, the instrument.** On top of the code bars:

- the tape is a tight black board with amber figures;
- rows of the verdict board, the figures, the sources and the 8-Ks highlight on hover, with an amber edge;
- figures are mono and set on the decimal;
- a fixed status footer lists the keys and the run on screen.

Paper keeps the same note calm and typographic: no footer, no bars, and serif claims.

**Time line** (`#timeline`). One SVG date axis, drawn at the note's width and redrawn when that
changes. Use it on any run whose record has dated filings.

- *Above the axis:* a bar for each 10-K and 10-Q the run read (`data-tl="filing"`), with a yellow
  dot on top when a verified quote comes from it (`data-quoted`).
- *Below the axis:* each 8-K in `run.timeline` (`data-tl="8k"`). A filled diamond is substantive;
  a small hollow circle is routine. A substantive 8-K is labelled with its categories, and a
  yellow dot on the axis above one means a quote comes from it.
- *The run* is a rule with its date (`data-tl="run"`).
- *The gap* (`data-tl="gap"`) is a hatched band from `as_of.newest_filed` to the run, labelled
  with `as_of.days_since_newest`. It is drawn only when the record has an `as_of`.
- *Every mark* is a link to its filing, with an SVG `<title>`, an `aria-label` and a tooltip on
  hover or focus.

**Verdict board** (`#scorecard`). One row per claim on one baseline grid: the stamp, the claim, then the record's counts at the right. With a review it has four columns, the engine's stamp, the stamp after your review, the claim and the counts, under one header row (`#board-head`). Each row keeps its own column labels for screen readers, visually hidden.

**Verdict stamp** (`.pill.verdict`). Square corners, capitals, a tinted fill. Use it only for a
claim's verdict. A **stance pill** (`.pill.stance`) is round and is used only for a finding's
stance.

**Claim docket** (`details.claim`). The claim as a headline, its verdict stamp, and a meta line
with the record's finding and passage counts, flagged "▲ Caution" when the claim carries one.
The body holds:

- the caution (limit box) or the note on the 8-Ks;
- the assessed-by line;
- the findings.

Each finding (`article.finding`) has a main column (`.finding-main`): its statement, stance, the
"predates the 8-K of …" mark, checks, cited figures and review slot. Its quotes sit in the margin
(`.finding-margin`), beside it when the note is at least 56rem wide and inline below that.

**Quote** (`figure.evidence`). The excerpt in the serif, with the words found highlighted inside
their context, then where it sits and a link to the filing.

**Withheld findings** (`#withheld`). Folded behind one line: the record's `findings_withheld`, then the kinds of reason present, with `findings_failed_meaning` counted when the meaning check withheld any. Inside the fold they are grouped by kind, as before.

**Reported figures.** Two dense columns of rows: label, sparkline, value (set on its decimal point). The sparkline is the
`run.series` entry with the figure's key and period; the figure's own period is circled. A
negative value is in `--neg`. Opening a row shows the record's arithmetic and inputs.

**8-K register** (`#events`). The date in the left column, then the form and accession, kind and
status, the items with their categories, and the opening sentences quoted. A substantive 8-K
carries an ink rule.

**Tables** (sources, the comparison between runs, breakdowns, the restatement ledger). A heavy
rule under the heading, hairlines between rows, numbers right-aligned. A wide table scrolls
inside its own frame.

**Marks.** The decision mark, the meaning mark, the model badge, the rule mark, the change mark,
the limit line and the page tag are as before. Each keeps its colour, shape and border style, so
no two are confused. The legend at the end of the note lists them all.

**Print.** `@media print` forces the Paper colours. It hides the bar, the guide, the drawer, the footer, the controls,
the review slots and the legend, and puts each quote's link after it. `app.js` opens every closed
disclosure before printing and closes them after, so a run prints as a whole research note.

**Motion.** Two things move:

- the current stage's marker pulses;
- a claim's chevron turns.

`prefers-reduced-motion` turns both off, and the `j` and `k` scrolling with them.

## Version 14 components (on the specimen only, for now)

These draw records the backend does not send yet; each takes the shape below and computes
nothing. They live in `app.js` as `compiledTest`, `thesisOverTime`, `asOfControl`, `asOfBanner`,
`restatementLedger` and `peerStrip`.

1. **Compiled test on a claim.** `{claim_id, expression, outcome: "holds"|"fails"|"cannot_compute",
   outcome_label, operands: [{name, label, display, period_label, form, accession, filed,
   filed_label, url}], arithmetic, margin_display, note}`. The expression is in monospace. The
   outcome has its own glyphs: ⊨ holds, ⊭ fails, ⊘ cannot compute (dashed). They are not verdict
   glyphs, although holds and fails borrow the support and challenge colours. A table lists the
   operands with each one's filing and date. The arithmetic and the margin are the backend's
   strings.
2. **Thesis over time.** `{outcome_labels, claims: [{claim_id, text, points: [{filed, filed_label,
   form, accession, url, outcome}], flips: [{filed, to, label}]}]}`. Each claim gets one lane: a
   step line across the filing dates, with holds on top, cannot compute in the middle and fails
   at the bottom. The backend names the flips: they are ringed on the line and listed under it in
   its words.
3. **As of a date.** The control in the thesis form is a date field, `{min, max, value, hint?}`.
   The banner on a run made as of a past date, `run.as_of.requested = {date, label, line}`, shows
   the date large on a hatched ground, in the record's words.
4. **Restatement ledger.** `{rows: [{metric_label, period_label, first: {display, form,
   filed_label, url}, later: {…}, change_display, note}]}`. The first value is struck through,
   both filings are named and linked, and the change is the record's.
5. **Peer strip.** `{industry_label, metrics: [{metric_label, unit_label, company: {ticker,
   display, value}, min, q1, median, q3, max: {value, display}, percentile_label, peers:
   [value]}]}`. The industry's values are faint dots, the box is the middle half, the bar is the
   median and the company is one larger dot. The percentile is the record's sentence ("97th
   percentile of 212"); the page never ranks.

## Keys

| Key | Does |
|---|---|
| `/` | Put the cursor in the ticker (Esc leaves it) |
| `e` | Open or close your thesis (the form drawer) beside a result; Esc closes it |
| `j` / `k` | Next or previous claim: the focus goes to the claim's summary and the note scrolls to it |
| `Enter` | Open or close the claim in focus (the browser's own) |
| `t` | Switch between Paper and Terminal, and remember the choice |
| `?` | Show the keys (Esc or Close shuts the list) |

The keys do nothing while you type in a field or hold Ctrl, Cmd or Alt. Every control has a
visible focus ring in `--accent`.

## Tests

`uitests/test_keys_dom.py` reads what `uitests/keys.html` recorded. That page frames the
live-run sample, presses each key, clicks the theme button and notes the focus, the theme, the
stored value and the dialog after each step. It ends by opening the drawer with `e` and closing it with Esc.

`uitests/test_run_events_dom.py` checks the time line against each run's filings and 8-Ks:
every mark, its kind, whether it is quoted, its link, the run and the gap. It also checks the
live-run sample, the command bar, the caution and the predated mark. For every run sample it also checks:

- the tape: each cell is the record's metric, in order, with its own display string;
- the reading order: the head, the status line, the tape, the board, the time line, then the rest;
- the status line's counts, and that the full strip starts folded;
- the withheld fold and its counts;
- that the standing prose sits in "How to read this";
- the way out of a sample and the drawer button in the bar.

The specimen page has no browser test of its own; it is checked by eye in the screenshots. The API serves it at `/specimen.html` (`tests/test_api.py` checks that).
