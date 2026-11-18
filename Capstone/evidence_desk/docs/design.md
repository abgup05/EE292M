# The page's design

Evidence Desk's page is a research note read in a workspace: on a wide screen it fills the
window as a frame of panes (the claims in a rail, the selection under tabs, an inspector for
whatever is picked) and the page itself does not scroll; on a phone and on paper the same
markup is one column in reading order. It has one frame and one set of components, drawn in two
themes:

- **Paper** is a typeset note inside the frame: warm paper, ink, a serif for prose and claims,
  hairline rules, and small capitals for labels.
- **Terminal** is the same frame as a market terminal: near-black, a monospace for every label,
  number and control, an amber accent, a code before every title, and tighter rows.

Every rule in `src/web/styles.css` reads tokens only. The themes differ in their token values and
in a few rules scoped to `:root[data-theme="terminal"]`. The specimen page,
`src/web/specimen.html`, shows every component once on made-up data. It is linked from nowhere:
open it at `/specimen.html`, or see `docs/screenshots/specimen*.png` (`make screenshots`). Its
note is the run view laid out flat, every panel and docket at once as on paper, and its "frame"
part draws the centre pane's head, the tabs and the inspector with the page's own code. At
0.13.0 the specimen drew nothing under its title, because the page's code hid a view the
specimen did not have; 0.13.1 gives it that view.

## The boundary still holds

The page draws and computes nothing a scientist would call a result. Every verdict, count,
outcome, change, flip and percentile on it is a record field or wording from `/api/meta`.
Three things are drawing, not computing:

- the time line places record dates on an axis;
- a sparkline places a series' values in a box;
- a negative number is set in `--neg` from the sign of the record's own value or display string.

And one is navigation, not computing: the rail's selection and the tabs decide which of the
record's items are on screen (one claim's docket, one tab's panel), and the
inspector which item is read at the side; with nothing picked it reads the first item the
record lists for that tab. No item is ranked, counted or filtered by a value.

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

## Layout: a workspace, not a document

On a screen at least 641px wide the page fills the window and does not scroll; its panes scroll
inside themselves. One command bar (one row at 1280px and wider), then the view.

**A run** is the status line across the top and three panes under it:

```
┌ bar ─ § Evidence Desk │ [NVDA] / │ Thesis e │ ▲ Partial  Run r │ As of 17 Nov 2026 (8-K) │ … sample · Inbox i · Guide · Paper t · Keys ? ┐
│ ▲ Partial · 3 of 3 sources · 6 of 8 findings verified · 2 withheld · ▲ limits                                all counts ▾ │
├ RAIL ──────────────────┬ CENTRE ───────────────────────────────────────────┬ INSPECTOR ─────────────────┤
│ NVIDIA CORP  NVDA  CIK │ c1  ± MIXED EVIDENCE  4 findings · 10 of 636 · ▲   │ Finding f1 of claim c1     │
│ Decision: Whether …    │ Buy NVDA because Jensen is gone                    │ ✓ Supports                 │
│ VERDICTS BY CLAIM      │ 1 Overview │ 2 Evidence │ 3 Over time │ 4 Events │  │ e1 · quote found word for  │
│ The whole thesis       │ 5 Figures │ 6 Limits                               │ word, highlighted          │
│ c1 ± MIXED    ▲Caution │ ─────────────────────────────────────────────────  │ …the text before, the      │
│ c2 ± MIXED             │ verdict rule · assessed by · the caution ·         │ quote, the text after…     │
│                        │ commentary · the findings in short                 │ Located under: Item 5.02 … │
│                        │                                                    │ s5 · 8-K · filed … ↗       │
└ (Terminal) footer: / ticker  e thesis  i inbox  j k claims  1-9 tabs  r run  t theme  ? keys      run-id · status ┘
```

- **The rail** (`#rail`) lists the claims once: the company and the decision, an entry for the
  whole thesis, then one row per claim (`#scorecard`): id, verdict stamp, the claim, the record's
  counts, and a caution flag. Selecting a row (a click, or `j` and `k`) drives the other two panes. A run opens on the
  whole thesis.
- **The centre pane** (`#centre`) shows the selection under tabs. Its head says what is selected
  (a claim's id, stamps, counts and flags are the record's). The tabs are a registry, `TABS` in
  `app.js`: a new tab is one entry there and one `.tabpanel[data-tab]` in `index.html`.

  | Tab | The whole thesis | One claim |
  |---|---|---|
  | Overview | the tape, the summary, what moved, unknowns and next steps | the verdict rule, who assessed, the caution or 8-K note, the engine's commentary, then the findings in short |
  | Evidence | the sources, the withheld findings (folded), which filings were compared | the findings in full (checks, cited figures, your decision, each quote) and the changed paragraphs |
  | Over time | the time line | the same |
  | Events | the as-of line in full, then the 8-K register | the same |
  | Figures | the reported figures, the tagged figures, the charts | the same |
  | Limits | coverage limits and errors | the same |

- **The inspector** (`#inspector`) reads whatever is picked in the centre pane: a finding's
  quotes in the text around them with where each sits and the link to the filing; an
  8-K whole (items, roles, opening sentences, link); a figure's formula and the reported values
  behind it. Pick by selecting the item or its button ("Read the quote in its context"). With
  nothing picked it reads the first item of the tab on show, and the item being read carries an
  accent edge on the inspector's side. What the inspector reads is not drawn twice: in the
  centre pane a quote is its own words cut to three lines, an 8-K its
  items. A tab with nothing to read at the side (Limits, the whole thesis's Evidence) gives the
  inspector's width to the centre pane.
- **The status line** (`#status-banner`) is one line; its full counts open over the panes and
  close again.
- **The Run drawer** (`#run-drawer`, from the right; the status chip or `r`) holds everything
  about who did the work: the engine, who checked meaning, who read the claims into tests and
  the counting rule, the run's id and times, the as-of line, the saved thesis, the sample's
  provenance. Under it: the guide (`#howto`, also opened by **Guide**), the marks (`#legend`) and
  the terms. The thesis form is the other drawer, from the left (`e`).

`?claim=c2&tab=evidence` opens a run on that claim and tab (read once; the screenshots use it).
`#claim-c4-changes` still selects the claim and shows the block.

**The first screen** is the same frame with two panes: the thesis form on the left, and on the
right the guide as the lead (what this is, the takeaway, the configured engine), how it works,
and the recorded samples in a column of their own.

**Any other view** (a filing comparison, tagged breakdowns, the inbox, a
saved thesis, figures only) is one pane that scrolls inside the frame, set to a measure of 66rem
and centred.

**Narrower windows.** Below 1100px the rail is a strip across the top (the entry for the whole
thesis, then the claims side by side, scrolling inside the strip) and the inspector is a sheet
from the bottom that opens when something is picked and closes with Close or Esc; the bar takes
a second row. Below 641px the page is one column that scrolls: the rail, the status line, then
the selection with its tabs stuck to the top of the window; there is no inspector, and what it
would read (a quote's context, an 8-K's opening sentences) is drawn in place.
Widths inside a pane respond to the pane's own width (container queries), not to the window's.

One spacing scale (`--s-1` to `--s-6`: 4, 8, 12, 16, 24, 32px) sets every gap and padding of the
frame, and one chrome every titled part: `.pane-label` for a pane, `.block-title` for a block
inside one.

### What left the reading path, and where it lives now

| Was in view on every run | Now |
|---|---|
| The provenance block under the company's name (engine, checker, run id, times) | The Run drawer, one step from the status chip. The bar keeps the status and an as-of chip. |
| The engines in the bar's second row | The Run drawer. The bar has one row. |
| The as-of line in the bar | A chip with the date and form of the newest filing read (`as_of.newest_filed`, `newest_form`); the record's whole line is the chip's title, its text for a screen reader, the first line of the Events tab, and in the Run drawer. |
| The claims twice (verdict board, dockets) | Once, in the rail. A docket has no heading of its own on screen. |
| "How to read this", the legend and the glossary | The Run drawer (**Guide**). The guide is still the lead of the first screen. |
| "Assessed by" on every row of the board | Said for the selected claim (its Overview) and to a screen reader on every row. On paper every row prints it. |
| A reason's "Model-written" badge under a statement that has one | The statement's badge and the violet rule on both; the reason's own badge is drawn on a phone and on paper. |

The honesty labels that stay in view: the status and the limit mark (the bar and the status
line), "Model-written, not checked …" on the summary and on every finding, the caution flag on
a claim's row and the caution itself in its Overview, and the sample tag.

## Components, and when to use each

**Command bar.** One row: the brand, the ticker (the `/` key), **Thesis** (`e`), then for a run
the status chip (glyph and word, never filled; it opens the Run drawer) and the as-of chip (it
opens the Events tab). At the right: the sample tag and **Leave the sample**, the watch's
health, **Inbox**, **Guide**, the theme switch (it names the theme in use; both names from
1520px) and **Keys**. The run's chips are hidden on every view that is not a run. The watch's
detail is what is cut short when the row is full.

**Status line** (`#status-banner`). The status, `sources_read` of `sources_requested`,
`findings_verified` of `findings_proposed`, `findings_withheld`, and the limit mark when the run
has coverage limits. It is the summary of a `<details>` whose body is the full strip (the
status note, every count, the limit lines), which opens over the panes. Every count is a
`[data-coverage]` node holding the record's number. A partial or failed run gets a limit rule
at its left edge; a running run's line is dashed and the stages follow it.

**Tape** (`#tape`). The newest period's key figures, first on the whole thesis's Overview. Each
cell is a metric from `run.metrics` (the quarter's when the record has one, else the year's):
its label, its `display` string (split at the decimal point, not reformatted) and its sparkline
from `run.series`. Selecting a cell reads that figure in the inspector. The row holds as many
cells as the record has of these figures and wraps to the pane: nothing is built around a count.

**Codes.** Every pane and block title carries a short code in `data-code` (VRD, SUM, MOV, FND,
WHD, FIG, EVT, UNK, NXT, SRC, LIM, ERR, TL, INS, RUN, GDE). Terminal draws each as an amber
cell before the title; Paper keeps its small-capital title and hairline and does not show it.

**Terminal, the instrument.** Mono for every label, number and control; amber for what you can
act on; the tabs as numbered keys with the one in use filled amber; the tape as a black board
with amber figures; rows that highlight with an amber edge; a footer with the keys and the run
on screen. Paper is the same frame as a typeset note: the centre pane is the sheet, the rail
and the inspector sit on the desk beside it, claims and prose are in the serif.

**Time line** (`#timeline`). One SVG date axis, drawn at its pane's width and redrawn when that
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

**Rail row** (`#scorecard a.score-row`). A claim's id, its verdict stamp and its caution flag
on one line; the claim; the record's finding and passage counts. With a review the row holds
two stamps under their own labels, the engine's and the one after your review, with the tally.
The row selected carries an accent rule and the sheet's ground; verdict colours stay in the
stamps.

**Verdict stamp** (`.pill.verdict`). Square corners, capitals, a tinted fill. Use it only for a
claim's verdict. A **stance pill** (`.pill.stance`) is round and is used only for a finding's
stance.

**Claim docket** (`details.claim`). One per claim, in two parts: why the verdict
(`[data-part="overview"]`) and the findings (`[data-part="evidence"]`). On screen only the
selected claim's docket is drawn, without its heading; every other docket is `inert` and off, so
neither the keyboard nor a screen reader reaches it. On paper every docket prints open under
its own heading (the verdict stamp, the id, the claim, the counts).

Each finding (`article.finding`) has its statement, stance, the "predates the 8-K of …" mark,
checks, cited figures and review slot, then its quotes and the button that reads them in the
inspector. A cited figure's link reads that figure in the inspector.

**Quote** (`figure.evidence`). In the inspector, on a phone and on paper: the excerpt in the
serif with the words found highlighted inside their context, then where it sits and a link to
the filing. In the centre pane: its own words, cut to three lines, and the source.

**Withheld findings** (`#withheld`). On the whole thesis's Evidence tab, folded behind one line:
the record's `findings_withheld`, then the kinds of reason present, with
`findings_failed_meaning` counted when the meaning check withheld any. Inside the fold they are
grouped by kind, as before.

**Reported figures.** Dense rows: label, sparkline, value (set on its decimal point). The
sparkline is the `run.series` entry with the figure's key and period; the figure's own period is
circled. A negative value is in `--neg`. Selecting a row reads its arithmetic and inputs in the
inspector; on a phone and on paper the row opens in place.

**8-K register** (`#events`). The date in the left column, then the form and accession, kind and
status, and the items with their categories. A substantive 8-K carries an ink rule. The roles a
5.02 names, the opening sentences and the link to each item are read in the inspector (in place
on a phone and on paper).

**Tables** (sources, the comparison between runs, breakdowns, the restatement ledger). A heavy
rule under the heading, hairlines between rows, numbers right-aligned, dates never broken. A
table wider than its pane scrolls inside its own frame. In the inspector a table of values
stacks, one value to a block, each cell named.

**Marks.** The decision mark, the meaning mark, the model badge, the rule mark, the change mark,
the limit line and the page tag are as before. Each keeps its colour, shape and border style, so
no two are confused. The legend in the Run drawer lists them all.

**Print.** `@media print` lays the note out as a document, whatever was selected: the company
and the decision, the verdicts (each row with "Assessed by"), how the run
was made, the status line with every count, then every tab's panel in order and every claim's
docket open under its own heading, with each quote in its context and each 8-K's opening
sentences in place. No bar, tabs, inspector, drawers, buttons or legend.
`app.js` opens every closed disclosure before printing, moves the Run drawer's block after the
rail and switches to Paper (the Terminal theme's own rules are not for a printer), and undoes
all three after.

**Motion.** Three things move: the current stage's marker pulses, and the two drawers slide.
`prefers-reduced-motion` turns them off.

## The standing watch (version 13)

The page draws the routes of `docs/watch.md` with the words of `GET /api/watch/meta`; every payload and field is in `docs/examples/v13/README.md`. It orders nothing: the inbox is drawn unread first, then newest first, as the API sends it. It counts one thing only: the folded items on the page it draws, because the API sends no count of them.

**Health** (`#watch-health`, in the bar; its detail is cut short when the bar is full, and whole in its title). One line from `GET /api/watch/health`:

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
| `i` | Open the inbox of the standing watch |
| `j` / `k` | Select the next or previous entry of the rail (the whole thesis, then each claim); the focus goes to its row, and it stops at the ends |
| `1` to `9` | Show that tab of the selection (the arrow keys move between tabs when one has the focus) |
| `Enter` | On the claim selected in the rail: move the focus to its tabs |
| `r` | Open or close the Run drawer; Esc closes it |
| `t` | Switch between Paper and Terminal, and remember the choice |
| `?` | Show the keys (Esc or Close shuts the list) |
| `Esc` | Close a drawer, the list of keys, or the inspector when it is a sheet |

The keys do nothing while you type in a field or hold Ctrl, Cmd or Alt. Every control has a
visible focus ring in `--accent`.

## Tests

`uitests/test_frame_dom.py` reads what `uitests/frame.html` recorded. That page frames the page
at 1440x900, 1280x800, 900x800 and 360x740 (a frame's size is its viewport), selects claims,
switches tabs and picks items, and records the browser's own measures after each step. The
tests hold the page to:

- no page scroll at 1440x900, 1280x800 and 900x800, each pane inside the window and scrolling
  inside itself, and the bar one row with every control inside the window;
- no sideways scroll at 360, one column, the tabs stuck to the top while the page scrolls;
- the claims listed once: every claim's row in the rail, and a claim's own words drawn a second
  time only in the centre pane's head while it is selected;
- the selection driving the panes: the docket, the head and the inspector, with the
  inspector's text checked against the record (a finding's evidence ids, excerpts and links; an
  8-K's opening sentences; a figure's label, value and concepts);
- a docket that is not on show being inert and out of the tab order, at every step;
- the Run drawer's contents, the first screen, and the strip and sheet below 1100px.

`uitests/test_print_dom.py` reads what `uitests/print.html` recorded: the live run with a claim
and the Events tab selected in Terminal, then the page's own `beforeprint` and the stylesheet's
print rules turned on (an emulation on a screen: page breaks and a printer are not checked).
Every docket is drawn open under its heading, every panel in reading order, no frame, each
quote's context and each 8-K's opening sentences in place, the theme
Paper, and how the run was made after the verdicts and back in the drawer afterwards.

`uitests/test_keys_dom.py` reads what `uitests/keys.html` recorded. That page frames the
live-run sample, presses each key, clicks the theme button and notes the focus, the rail's
selection, the docket on show, the tab, the theme, the stored value, the dialog and the drawers
after each step: `j` and `k` through the claims and back to the whole thesis, a digit for a
tab, `e` and `r` for the two drawers with Esc closing each, Enter on the selected claim.

`uitests/test_run_events_dom.py` checks the time line against each run's filings and 8-Ks:
every mark, its kind, whether it is quoted, its link, the run and the gap. It also checks the
live-run sample, the command bar, the caution and the predated mark. For every run sample it also checks:

- the tape: each cell is the record's metric, in order, with its own display string;
- the order of the markup (a phone's and paper's reading order): the company and decision, the verdicts, the status line, the tape and summary, the dockets, the time line, the figures; and that a run opens on the whole thesis's Overview;
- the status line's counts, and that the full strip starts folded;
- the withheld fold and its counts;
- that the standing prose sits in the guide, in the Run drawer, which starts closed and inert;
- that the Run drawer names the engines whole and the bar names none;
- the way out of a sample and the drawer button in the bar.

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
