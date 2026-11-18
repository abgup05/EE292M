# The page's design

Evidence Desk's page is a research note. It has one layout and one set of components, drawn in
two themes:

- **Paper** is the note as printed: warm paper, ink, a serif for prose and claims, hairline rules,
  and small capitals for labels.
- **Terminal** is the same note as a dense dark screen: near-black, a monospace for every label,
  number and control, an amber accent, and tighter rows.

Every rule in `src/web/styles.css` reads tokens only. The themes differ in their token values and
in a few rules scoped to `:root[data-theme="terminal"]`. The specimen page,
`src/web/specimen.html`, shows every component once on made-up data, except its version 14 parts,
which are excerpts of `docs/examples/v14`. It is linked from nowhere: open it at `/specimen.html`,
or see `docs/screenshots/specimen*.png` (`make screenshots`). Its note was empty from version 13
until version 14: the page's code hid a view the specimen did not have.

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

## The standing watch (version 13)

The page draws the routes of `docs/watch.md` with the words of `GET /api/watch/meta`; every payload and field is in `docs/examples/v13/README.md`. It orders nothing: the inbox is drawn unread first, then newest first, as the API sends it. It counts one thing only: the folded items on the page it draws, because the API sends no count of them.

**Health** (`#watch-health`, in the bar). One line from `GET /api/watch/health`:

- a filled dot (support colour) and "Watch alive", or a hollow dot (limit colour) and "Watch not running";
- the last cycle's time of day; the whole time and the watcher's `note` are in the title;
- the queue depth and the runs waiting.

At phone width only the dot and the words show. It is read again every minute while the page is visible.

**Not running.** When `alive` is false, a limit line says so near every watch control, in the inbox view and on a saved thesis. It reads "The watcher is not running. No new filing will be noticed, and no watched thesis run, until it runs.", followed by the health's `note`.

**Inbox button** (`#inbox-button`, the `i` key, `#inbox`). It shows the unread count from the last inbox payload, or from a mark-read answer. The count sits on an accent fill, with a quiet outline at zero.

**Watch card** (`.watch-card`). The same card appears on a saved thesis (`#thesis-watch`) and in the inbox's list of watches. When the thesis is on watch, it shows:

- since when, and the policy label;
- the last check, the next check (or `next_check_note`) and the last error;
- the last failed job, when there is one;
- unread items and runs waiting, with a link to that thesis's inbox;
- the policy as two radios, a change of which is a `PUT`;
- "Take it off watch", a `DELETE`.

When the thesis is not on watch, the radios start on `default_policy`, and "Put it on watch" sends the `PUT`. Every refusal is said under the card in the server's words:

- a 422 names its fields;
- a 404 says the thesis is gone;
- a 503 adds "Nothing was saved";
- a 409 on a `DELETE` shows the watch as ended.

A refused policy puts the radio back on the server's policy.

**Inbox item** (`article.inbox-item`). Each item shows, in order:

1. The kind tag in the record's words, with a glyph: ◇ waiting (dashed), ◌ running (dotted), ◆ moved (change colour), · nothing moved, ▲ failed (limit colour), ○ not relevant.
2. Unread or read, then the thesis and the time.
3. The headline.
4. The filing: form and accession linked to sec.gov, filed and report dates, and each 8-K item with its title and category.
5. The triage: a rule mark "By rule, no model", the summary and the rules. Then each claim says whether it bears, gives its reasons and, for a 10-K or 10-Q, its changed paragraphs with their change mark, shared words and link.
6. The run:
   - a waiting run shows its reason and **Run now (uses the model)**. A 202 reads the item again and names the run. A 409 says the run was not started, in the server's words, and reads the item again.
   - otherwise the run's id and status, and who started it, with **Open the run in the note**. The run opens with the item's comparison under its head.
7. What moved: the record's line, each verdict that moved as two stamps, new cautions (limit lines), new 8-K notes and new 8-Ks.
8. "Compare with the previous run, claim by claim": the run comparison table, drawn from the item's `moved` (no counts: the payload has none).
9. Mark read or unread.

Unread items carry an accent rule at their left edge.

**Folded items** (`.inbox-folded`). Items with `collapsed: true` sit on one closed line under the list: "Seen, not relevant: N filings on this page".

**Paging.** "Older items" asks for the page's `next_offset`. "Newer items" goes back to an offset the page came from. "Mark this page read" sends the page's unread ids.

**Empty and failure states.** Each says so plainly:

- no watches;
- an empty inbox;
- an inbox route this server lacks (a 404);
- a server that cannot be reached, with "Try again".

**Recorded inbox** (`?sample=inbox`, `?sample=inbox-page-2`). It is drawn from the five example payloads that `make sample-inbox` copies unedited, and says where they come from. In sample mode nothing is sent, and the controls are disabled or say so.

## Computed claims, dates and restatements (version 14)

Drawn from the backend's own fields: `docs/examples/v14/README.md` is the contract and the
recorded samples are those payloads copied unedited (`make sample-v14`). The page computes no
outcome, margin, flip, count or change. It places dates on an axis and maps the outcome tokens
to glyphs and words. Every field is read defensively: a missing one is left out and an added one
is ignored, so additive changes to these payloads do not break the page. The functions are in
`app.js`, in the section "version 14".

1. **The computed test on a claim** (`computedTest`, from `Claim.computed`). It sits in the
   claim's docket before the findings, with an olive left rule and the fixed-rule mark ("Computed
   from the XBRL facts by a fixed rule, no model"). It shows, in order:
   - the canonical expression in monospace;
   - the outcome with its own glyphs: ⊨ holds, ⊭ fails, ⊘ cannot be computed (dashed). These
     are never a verdict's glyphs, although holds and fails borrow the support and challenge
     colours;
   - what the verdict rule counted (`counted_as`: "Counted as support", "Counted as a
     challenge", "Not counted");
   - the reason it could not be computed;
   - the bound test, and the date the facts were read up to (`as_of`);
   - the two sides compared;
   - a table of the operands: term, label, value, formula, and every fact read with its
     concept, period, value, filing (form and date, linked to EDGAR's index page of the
     accession) and its derived or restated flag;
   - the arithmetic, line by line, then the margin and the backend's note.

   A claim that did not compile shows its `compile_note` quietly instead, behind a dashed rule.
2. **Which part of a verdict is computed.** On the verdict board each claim keeps the engine's
   "Assessed by" line (the reading of the filings: a model's or the extractive engine's) and
   gains a second line: "Computed, no model:" with the outcome and what it counted, or "No
   computed test: the verdict rests on the findings". The docket's summary line adds "⊨
   Computed: Holds". The note under the verdicts ("How to read this") adds one sentence on
   computed tests when the run has one.
3. **Who read the claim.** The head says who read the claims into tests (`claim_readers`, with
   `claim_reader_detail`). Each test lists every reading in `Claim.readings` (however many
   readers there are) and names the readers of the test shown (`read_by`).

   The readings differ when a reader in `readings` is not in the test's `read_by` (or, for a
   claim that did not compile, when another reader read a test). Then the test, the board and
   the docket say "Readings differ: not counted" in the limit colour, and the backend's note
   says what each reader read. The page wants a field for this from the backend rather than
   working it out.
4. **The thesis over time** (`drawThesisOverTime`, from each compiled claim's `history`). It is
   a block of its own, directly under the time line (code `TOT`). Each compiled claim gets a
   lane:
   - the claim, its test now, and a step line over the filing dates: holds on top, cannot be
     computed in the middle, fails at the bottom, one dot per point;
   - a ring on each point the record marks `flipped`, labelled with its form and date when the
     note is wide enough;
   - under the line, the `history_note`, then the flips in words ("Flipped to Holds with the
     10-K filed 25 Feb 2026", linked, with the bound test and both sides);
   - every point as a table behind a fold.

   A claim with no history (a share of revenue) shows only its `history_note`. A claim that did
   not compile is named in one line. The lanes share one date axis and are drawn again when the
   note changes width.
5. **As of a date.** The drawer has a date field, "As of a past date" (`as_of`), sent with the
   run and used by the restatement lookup; the server checks the date and a refusal shows under
   the field. A run with `as_of.requested` is unmistakable:
   - a banner opens the note: a double rule on a hatched ground, the date large, and
     `requested_note`;
   - the company head gains a double left rule;
   - the command bar's As-of cell starts "Run as of 1 Mar 2026", and so does the status footer;
   - the time line ends at the requested date ("As of 1 Mar 2026"), not at the day the run ran.

   The banner and the rule print.
6. **The restatement ledger** (`restatementLedger`, `GET /api/companies/{ticker}/restatements`).
   It is a lookup beside the others in the drawer ("Restated values"), as of the drawer's date
   when one is set. Its view gives:
   - the company, the date, and "28 of 922 periods ... changed value in a later filing" in the
     record's two counts;
   - the metrics compared, the tolerance, the notes;
   - a table with one row per restated period: the first value struck through with its filing,
     each later value with its filing and the change in units and percent, "back to an earlier
     value" (`returns_to_earlier`), "tagged with another concept later" (`concept_changed`), and
     how many filings reported it.
7. **Coverage.** The status line's full counts gain "N of M claims compiled to a computed test:
   ⊨ holds, ⊭ fails, ⊘ cannot be computed", with each count the record's.
8. **The watch's version 14 fields.** The inbox's folded line uses the backend's `folded` count,
   of the whole inbox (or of the thesis), and says when this page draws none of them. An item
   shows `claims_line` and each computed test whose outcome changed (`moved.computed`: the
   canonical test, before and after). The saved theses list takes each thesis's `watch` from
   `GET /api/theses`.

The recorded samples are `?sample=computed` (the example run: two tests that hold, one that
fails, one that cannot be computed, one claim that does not compile), `?sample=as-of` (the same
claims as of 1 Mar 2026) and `?sample=restatements` (NVIDIA's ledger from the recorded facts).
All three were made offline with the extractive engine: no model, no cassette.

**Not built: the peer strip.** The backend has no peers route, so the strip is only on the
specimen, on made-up data, under the heading "Not built". It is not on the page.

## Keys

| Key | Does |
|---|---|
| `/` | Put the cursor in the ticker (Esc leaves it) |
| `e` | Open or close your thesis (the form drawer) beside a result; Esc closes it |
| `i` | Open the inbox of the standing watch |
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

`uitests/test_v14_dom.py` checks the version 14 samples against their JSON:

- the copies are byte for byte the examples;
- each compiled claim's expression, outcome, counted state, bound test, reason, margin and
  arithmetic, its operands and every fact with its filing and link;
- the compile note of a claim that did not compile;
- the board's computed part, and the readings;
- the computed counts in the status line;
- the thesis over time under the time line, with each history's points, outcomes and flips;
- the as-of banner, the bar, the body class and where the time line ends;
- the ledger's rows, values, changes and flags, and its denominator.

`uitests/v14.html` drives the page for what the examples do not show, and the same file checks
what it recorded:

- two and three readers, made the way the backend makes them;
- the ledger lookup's 422, 200 and 503;
- a run sent with `as_of`, refused and then drawn;
- an inbox item with `moved.computed`;
- the theses list with each thesis's `watch`.

`uitests/test_inbox_dom.py` checks the recorded inbox against its JSON:

- the copies are byte for byte the examples;
- the order of the items, and their kinds and headlines;
- the folded line's count;
- the unread number;
- that only the waiting item has the Run now button;
- the filings, the reasons per claim and what moved;
- the watch card's fields and the health.

It also reads what `uitests/watch.html` recorded. That page answers the page's watch requests with the example payloads and the README's refusal shapes: 202 and 409 on Run now, 422, 503 and 200 on a policy, 409 on taking a watch off, an empty inbox beside a watcher that never ran, an unreachable server, paging by offsets, and marking read. It records what the page showed and sent.

The specimen page has no browser test of its own; it is checked by eye in the screenshots. The API serves it at `/specimen.html` (`tests/test_api.py` checks that).
