// Evidence Desk frontend (the research-note design: docs/design.md).
//
// Collects a thesis, starts a run, polls it, and draws the record the API
// returns; records the reader's decision on each verified finding; saves a
// thesis and shows what moved between its runs. It computes nothing a reader
// would call a result: verdicts (the engine's and the one after review),
// counts, coverage, comparisons, reported figures and their display strings,
// excerpt context and all status, verdict and decision wording come from the
// API (`GET /api/runs/{id}`, `/api/runs/{id}/review`, `/api/theses/...`,
// `GET /api/companies/{ticker}/metrics` and `GET /api/meta`). A decision is
// shown as the server's Review returns it, never as a local guess. Optional
// routes that answer 404 hide their feature without an error. Chart geometry
// maps given values to pixels; every number a reader sees is a record field.
// Client-side validation is immediate feedback only, using the limits from
// `/api/meta`; the server decides. Every string from the API is inserted as
// text, never as markup, and only http(s) links from the API become hrefs.
//
// One meaning per mark (see the legend in index.html):
//   ▲ amber   something limits this record
//   ✎ violet  written by a model and not checked for meaning (solid rule, filled badge)
//   ◎ ◐ violet a second model read the evidence and agrees (◎) or agrees only in
//             part (◐): still a model's reading, so the same violet, but a double
//             rule and no fill, never the engine's badge. A finding the second model
//             rejects is withheld, which is a limit (▲).
//   ! red     the server refused your input ("Refused"; "Rejected" is only ever your decision)
//   ƒ olive   computed by a fixed rule, not checked by a person (dotted border)
//   status    ◇ complete, ⋯ running, ▲ partial or failed: never a filled tag
//   dashed    not final: a claim not judged, a decision still to make, a run in progress
//   verdicts  ✓ supported, ✕ challenged, ± mixed, ? unjudged, ∅ not addressed
//   stances   reuse ✓ and ✕; context is •
//   decisions ▣ accepted, ☒ rejected (dark filled tag: only ever the reader's own);
//             ☐ undecided is dashed, because the verdict after review is provisional
//   changes   between two filings (`/api/companies/{ticker}/changes`), cyan, square tags:
//             # numbers only, ~ reworded, + added, − removed; inside a reworded
//             paragraph, added words are underlined and removed ones struck through
//   computed  ⊨ holds, ⊭ fails, ⊘ cannot be computed (a test's outcome, never a verdict)
//   readers   ● read the test shown, ≠ read another test, ○ read no test (one mark per reader)
//
// Drawing, not computing: the time line places record dates on an axis, a sparkline places
// a series' values in a box, and a negative number is set in its colour from the sign of the
// record's own value. Every date, label, count, outcome and percentile a reader sees is a
// record field or wording from /api/meta. The theme ("paper" or "terminal") is the reader's
// setting, kept in localStorage when the browser allows it, else it follows the system.

"use strict";

const POLL_MS = 1500;

/** Pipeline stages in order, with the words shown on the progress line. */
const STAGES = [
  ["queued", "Queued"],
  ["company", "Company"],
  ["filings", "Filings"],
  ["events", "Current reports (8-K)"],
  ["numbers", "Reported figures"],
  ["planning", "Planning"],
  ["retrieving", "Retrieving passages"],
  ["assessing", "Assessing"],
  ["verifying", "Verifying quotes"],
  ["done", "Done"],
];

const VERDICT_GLYPH = {
  supported: "✓",
  challenged: "✕",
  mixed: "±",
  unjudged: "?",
  not_addressed: "∅",
};
/** Stances reuse the supported and challenged marks exactly; context is a grey dot. */
const STANCE_MARK = {
  supports: ["✓", "Supports"],
  challenges: ["✕", "Challenges"],
  context: ["•", "Context"],
};
/**
 * The reader's decision on a finding: its own glyphs, never a verdict or stance mark.
 * ▣ rather than ☑, which headless Chromium draws as a colour emoji.
 */
const DECISION_MARK = { accepted: "▣", rejected: "☒", undecided: "☐" };
/** Used only when /api/meta has no decision_labels. */
const DECISION_FALLBACK = { accepted: "Accepted", rejected: "Rejected", undecided: "Undecided" };
/** The second model's reading of a finding's evidence (`checks.support`), in words; ◎ and ◐ are its marks. */
const MEANING_MARK = { passed: "◎", partly: "◐" };
const MEANING_WORDS = {
  passed: "Meaning: a second model agrees",
  partly: "Meaning: a second model agrees only in part",
  failed: "Meaning: a second model disagrees",
  unchecked: "Meaning: not checked",
};
const MODEL_BADGE = "Model-written, not checked for meaning";
/** On a finding a second model has read: its meaning was checked, but only by a model. */
const MODEL_BADGE_READ = "Model-written, not checked by a person";
/** A run's status. Complete is an open diamond: a filled dark square would read as the reader's decision. */
const STATUS_GLYPH = { running: "⋯", complete: "◇", partial: "▲", failed: "▲" };
const LIMITING_STATUS = new Set(["partial", "failed"]);

/** The engine name the deterministic engine reports; anything else non-empty is a model. */
const EXTRACTIVE = "extractive";
const MODEL_ORIGIN = "model";
const SAMPLE_NAME = /^[a-z0-9-]{1,40}$/;

const FORM_GLOSS = {
  "10-K": "annual report",
  "10-Q": "quarterly report",
  "10-K/A": "amended annual report",
  "10-Q/A": "amended quarterly report",
};
const ENGINE_GLOSS = {
  claude: "a language model reads the passages and proposes findings; the backend checks every quote and number",
  extractive: "no model: it quotes the best-matching sentences and judges no stance",
};
const ITEM_GLOSS = "Where the passage sits in the filing. An Item is a numbered section, such as Item 1A, Risk Factors.";
/**
 * What an evidence link opens, by the record's `link_kind`, for a filing and for a page.
 * A record without `link_kind` keeps the plain words ("Open in filing", "Open the page").
 */
const LINK_WORDS = {
  passage: ["Open in filing, at this passage", "Open the page, at this passage"],
  "first-line": ["Open in filing, at the first line of this passage", "Open the page, at the first line of this passage"],
  document: ["Open the filing (this link does not locate the passage)", "Open the page (this link does not locate the passage)"],
};
const ACCESSION_GLOSS = "Accession number (the SEC's identifier for this filing)";
const FIELD_NAMES = {
  ticker: "Ticker",
  decision: "Decision",
  claims: "Claims",
  scope_notes: "Scope notes",
  filings: "Number of filings",
  extra_urls: "Extra public pages",
  thesis_name: "Thesis name",
  changes_form: "Filings to compare",
  breakdowns_form: "Filing to read",
  tagged_figures: "Tagged figures",
  as_of: "As of",
};

/**
 * What changed between two filings: its own family of marks, never a verdict, stance,
 * limit, model, decision or meaning mark. Unchanged paragraphs carry no mark.
 */
const CHANGE_MARK = {
  numbers_only: ["#", "Numbers only"],
  reworded: ["~", "Reworded"],
  added: ["+", "Added"],
  removed: ["−", "Removed"],
};
/** The five per-Item counts, in the order the rows show them. */
const CHANGE_COUNTS = ["unchanged", "numbers_only", "reworded", "added", "removed"];

/** Charts drawn from `series`, in order; each picks the quarterly series, else the annual one. */
const CHARTS = [
  { kind: "bars", keys: ["revenue"], title: "Revenue by period, in US dollars", axis: "USD" },
  { kind: "lines", keys: ["revenue_yoy"], title: "Revenue growth, year over year, in percent", axis: "Percent" },
  {
    kind: "lines",
    keys: ["gross_margin", "operating_margin", "net_margin"],
    title: "Gross, operating and net margin, in percent of revenue",
    axis: "Percent of revenue",
  },
];
/** Line identity never rests on colour: each series has its own dash pattern and marker. */
const LINE_STYLES = [
  { dash: "", marker: "circle" },
  { dash: "7 4", marker: "square" },
  { dash: "2 3", marker: "triangle" },
];

const state = {
  meta: null,
  sample: false,
  runId: null,
  viewSeq: 0, // bumped on every run or lookup selection; stale responses are dropped
  recentSeq: 0,
  timer: null,
  controller: null,
  bannerKey: "",
  chartSeq: 0,
  run: null, // the run on screen
  review: null, // the Review the server last returned for that run
  comparison: null, // the RunComparison whose later run is on screen
  thesisId: null, // the saved thesis on screen
  theses: new Map(), // saved theses by id, from GET /api/theses
  thesesSeq: 0,
  sampleName: "", // which sample file is on screen, in sample mode
  // The RunChanges of the finished run on screen: {runId, status: "loading" | "ready" | "failed", record, error}.
  claimChanges: null,
  claimChangesOpen: new Set(), // claim ids whose "Changed in the filings" block the reader opened
  sampleNote: "", // where a sample record came from, said in the run's head
  timelineRun: null, // the run whose time line is drawn, redrawn when the note changes width
  totRun: null, // the run whose thesis over time is drawn, redrawn likewise
  // The standing watch (version 13): /api/watch/meta, the watches by thesis, the health, the inbox.
  watchMeta: null,
  watches: new Map(),
  watchesLoaded: false,
  health: null,
  inboxUnread: null,
  inboxPage: null,
  inboxThesis: null, // the thesis the inbox is filtered to, or null for every thesis
  inboxOffsets: [], // the offsets of the pages before this one, to go back by the API's own offsets
  inboxSeq: 0,
  itemComparison: null, // an inbox item's `moved`, shown under the run it made
  // The workspace (navigation, never a result): what the rail has selected ("" is the whole
  // thesis, else a claim id), the centre pane's tab, and what the inspector was asked to show.
  selected: "",
  tab: "",
  picked: null, // {kind: "finding" | "test" | "event" | "figure", id}, or null for the tab's own first item
  ctx: null, // the run on screen, indexed by id (sources, evidence, findings, claims, metrics)
};

/** Samples that have a recorded RunChanges beside them; any other sample shows no such block and asks for none. */
const SAMPLE_RUN_CHANGES = { run: "sample-run-changes.json" };

/**
 * Samples stored as a bare run, copied unedited from a run's own record (results/<run>.json):
 * they carry no note and no wording, so the note is here and the wording comes from /api/meta.
 */
const BARE_SAMPLE_NOTES = {
  computed: `Version 14's example run (docs/examples/v14/run.json): five claims on NVIDIA's newest filings, two computed tests that hold, one that fails, one that cannot be computed and one claim that does not compile. It was ${"made offline by make examples (tests/examples_v14.py) from the recorded NVIDIA fixtures with the extractive engine: no model was asked and no cassette was replayed, and no EDGAR request was made. Clock times are fixed at 2026-11-18 12:00 UTC. The extractive engine judges no stance, so a verdict here is supported or challenged only through its computed test. Copied unedited from docs/examples/v14/ by make sample-v14."}`,
  "as-of": `Version 14's example run as of 1 Mar 2026 (docs/examples/v14/as-of-run.json): the same five claims, reading only what was filed by that date. It was ${"made offline by make examples (tests/examples_v14.py) from the recorded NVIDIA fixtures with the extractive engine: no model was asked and no cassette was replayed, and no EDGAR request was made. Clock times are fixed at 2026-11-18 12:00 UTC. The extractive engine judges no stance, so a verdict here is supported or challenged only through its computed test. Copied unedited from docs/examples/v14/ by make sample-v14."}`,
  "run-events":
    "A live run of 18 November 2026 on NVIDIA (run run-39d0b17b5396), answered by the Anthropic API: claude-opus-5-5 read the passages and claude-haiku-5-5 checked their meaning. It is copied unedited from results/run-39d0b17b5396.json. Its first claim is about the chief executive leaving, and the 8-K of 12 Nov 2026 postdates the evidence of one of its findings.",
  "run-live":
    "A live run of 19 November 2026 (UTC) on NVIDIA (run run-a3c830947e19, deciding whether to buy NVIDIA now), answered by the Anthropic API: claude-opus-5-5 read the passages, proposed the corollaries and wrote the argument; claude-haiku-5-5 checked the findings' meaning; and three readers turned each claim into a test: the grammar (a fixed rule, no model), claude-haiku-5-5 and claude-sonnet-5-5. Code computed every figure, test and analytic and audited every sentence of the argument against what it cites. It is copied unedited from results/run-a3c830947e19.json.",
  "run-costco":
    "A live run of 19 November 2026 (UTC) on Costco (run run-6560ff7f364f, deciding whether to keep holding Costco at this price), answered by the Anthropic API: claude-opus-5-5 read the passages, proposed the corollaries and wrote the argument; claude-haiku-5-5 checked the findings' meaning; and three readers turned each claim into a test: the grammar (a fixed rule, no model), claude-haiku-5-5 and claude-sonnet-5-5. Code computed every figure, test and analytic and audited every sentence of the argument against what it cites. It is copied unedited from results/run-6560ff7f364f.json.",
  "analysis-shapes":
    "The analysis example that shows every shape (docs/examples/analysis/run-hand-built-argument.json): five claims on NVIDIA's recorded filings with a hand-built argument. Its sentences and corollaries are scripted answers written by tests/examples_analysis.py from the run's own figures: no model wrote them, so read it for the shapes (a lean that contradicts its verdict, sentences the audit did not verify, corollaries the readers disagree on), not for the argument. Code computed the analytics and audited the sentences as it does a model's. Made offline by make examples-analysis; copied unedited by make sample-analysis.",
  readers: `Version 14's example run with two model readers (docs/examples/v14/run-readers.json): six claims of set C read by the grammar, claude-haiku-5-5 and claude-sonnet-5-5. The readers' answers were ${"replayed read-only from the cassette eval/cassettes/claim-readers, recorded through the Anthropic API on 18 Nov 2026; the findings come from the extractive engine (no model) on the recorded NVIDIA fixtures, made offline by make examples with no EDGAR request. Clock times are fixed at 2026-11-18 12:00 UTC. Copied unedited from docs/examples/v14/ by make sample-v14."}`,
};

/** Samples stored as a bare RestatementLedger, copied unedited from docs/examples/v14 by make sample-v14. */
const LEDGER_SAMPLE_NOTES = {
  restatements:
    "Version 14's example restatement ledger (docs/examples/v14/restatements.json): NVIDIA's ledger from the recorded XBRL facts (tests/fixtures/edgar, facts to 26 Aug 2026), made offline by make examples with no model and no EDGAR request, and copied unedited by make sample-v14. Nobody has read these periods against the filings to say which are restatements and which are tagging errors.",
};

const THEMES = ["paper", "terminal"];
const THEME_KEY = "evidence-desk-theme";
const THEME_NAMES = { paper: "Paper", terminal: "Terminal" };

const $ = (id) => document.getElementById(id);

const els = {
  sampleTag: $("sample-tag"),
  engineLine: $("engine-line"),
  metaError: $("meta-error"),
  form: $("thesis-form"),
  ticker: $("ticker"),
  decision: $("decision"),
  claims: $("claims"),
  scope: $("scope_notes"),
  filings: $("filings"),
  urls: $("extra_urls"),
  tagged: $("tagged_figures"),
  advanced: $("advanced"),
  decisionCount: $("decision-count"),
  claimsCount: $("claims-count"),
  scopeHint: $("scope-hint"),
  filingsHint: $("filings-hint"),
  urlsHint: $("urls-hint"),
  formErrors: $("form-errors"),
  submit: $("submit"),
  figuresOnly: $("figures-only"),
  filingChanges: $("filing-changes"),
  changesForm: $("changes_form"),
  breakdowns: $("breakdowns"),
  breakdownsForm: $("breakdowns_form"),
  example: $("load-example"),
  saveThesis: $("save-thesis"),
  savePanel: $("save-panel"),
  thesisName: $("thesis_name"),
  saveConfirm: $("save-confirm"),
  saveCancel: $("save-cancel"),
  formNote: $("form-note"),
  thesesBlock: $("theses-block"),
  theses: $("theses"),
  recent: $("recent"),
  resultPanel: $("result-panel"),
  empty: $("empty-state"),
  loading: $("loading"),
  loadError: $("load-error"),
  figuresView: $("figures-view"),
  figuresHead: $("figures-head"),
  figuresStandalone: $("figures-standalone"),
  changesView: $("changes-view"),
  changesHead: $("changes-head"),
  changesBody: $("changes-body"),
  breakdownsView: $("breakdowns-view"),
  breakdownsHead: $("breakdowns-head"),
  breakdownsBody: $("breakdowns-body"),
  thesisView: $("thesis-view"),
  thesisHead: $("thesis-head"),
  runAgain: $("run-again"),
  runAgainMessage: $("run-again-message"),
  thesisRuns: $("thesis-runs"),
  thesisChangesSection: $("thesis-changes-section"),
  thesisChanges: $("thesis-changes"),
  runView: $("run-view"),
  banner: $("status-banner"),
  stagesWrap: $("stages-wrap"),
  stages: $("stages"),
  runHead: $("run-head"),
  reviewLine: $("review-line"),
  scorecard: $("scorecard"),
  distinction: $("distinction"),
  changesSection: $("changes-section"),
  changes: $("changes"),
  summarySection: $("summary-section"),
  summaryBox: $("summary-box"),
  summaryOrigin: $("summary-origin"),
  summary: $("summary"),
  figuresSection: $("figures-section"),
  figures: $("figures"),
  eventsSection: $("events-section"),
  eventsTitle: $("events-title"),
  events: $("events"),
  claimList: $("claim-list"),
  runFilingChanges: $("run-filing-changes"),
  withheldSection: $("withheld-section"),
  withheld: $("withheld"),
  unknownsSection: $("unknowns-section"),
  unknowns: $("unknowns"),
  nextSection: $("next-section"),
  nextSteps: $("next-steps"),
  sourcesBody: document.querySelector("#sources tbody"),
  limits: $("limits"),
  errors: $("errors"),
  errorsMore: $("errors-more"),
  provenance: $("provenance"),
  cmdRun: $("cmd-run"),
  cmdStatus: $("cmd-status"),
  cmdAsof: $("cmd-asof"),
  themeToggle: $("theme-toggle"),
  keysButton: $("keys-button"),
  keysDialog: $("keys-dialog"),
  timelineSection: $("timeline-section"),
  timeline: $("timeline"),
  tapeSection: $("tape-section"),
  tape: $("tape"),
  tapeTitle: $("tape-title"),
  analysis: $("analysis"),
  method: $("method"),
  boardHead: $("board-head"),
  howto: $("howto"),
  howtoButton: $("howto-button"),
  thesisButton: $("thesis-button"),
  formPanel: $("form-panel"),
  drawerClose: $("drawer-close"),
  drawerScrim: $("drawer-scrim"),
  leaveSample: $("leave-sample"),
  statusbarRun: $("statusbar-run"),
  keysHowto: $("keys-howto"),
  inboxView: $("inbox-view"),
  inboxHead: $("inbox-head"),
  inboxButton: $("inbox-button"),
  inboxCount: $("inbox-count"),
  inboxItems: $("inbox-items"),
  inboxCollapsed: $("inbox-collapsed"),
  inboxPaging: $("inbox-paging"),
  inboxMessage: $("inbox-message"),
  watches: $("watches"),
  watchesSection: $("watches-section"),
  watchDown: $("watch-down"),
  watchHealth: $("watch-health"),
  thesisWatch: $("thesis-watch"),
  thesisWatchSection: $("thesis-watch-section"),
  asOf: $("as_of"),
  restatements: $("restatements"),
  ledgerView: $("ledger-view"),
  ledgerHead: $("ledger-head"),
  ledgerBody: $("ledger-body"),
  totSection: $("tot-section"),
  tot: $("tot"),
  asofBanner: $("asof-banner"),
  // The workspace: the rail, the centre pane with its tabs, the inspector, and the Run drawer.
  workspace: $("workspace"),
  rail: $("rail"),
  railHead: $("rail-head"),
  railThesis: $("rail-thesis"),
  centre: $("centre"),
  selHead: $("sel-head"),
  tabs: $("tabs"),
  centreScroll: $("centre-scroll"),
  inspector: $("inspector"),
  inspectBody: $("inspect-body"),
  inspectClose: $("inspect-close"),
  runButton: $("run-button"),
  runDrawer: $("run-drawer"),
  runDrawerClose: $("run-drawer-close"),
  runInfo: $("run-info"),
  guideSlot: $("guide-slot"),
  leadSlot: $("lead-slot"),
  cmdVerdicts: $("cmd-verdicts"),
  overviewMast: $("overview-mast"),
  verdictTable: $("verdict-table"),
  barMenu: $("bar-menu"),
};

// ---------------------------------------------------------------- helpers

/**
 * Build an element. `props` keys: `class`, `text`, `on<event>`, or any
 * attribute. Children may be nodes or strings; strings become text nodes.
 * Never pass an API value as `href`: use `externalLink` for those.
 */
function h(tag, props = null, ...children) {
  const node = document.createElement(tag);
  if (props) {
    for (const [key, value] of Object.entries(props)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = String(value);
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value === true ? "" : String(value));
    }
  }
  appendAll(node, children);
  return node;
}

const SVG_NS = "http://www.w3.org/2000/svg";

/** Build an SVG element; same conventions as `h`. */
function s(tag, attrs = null, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  if (attrs) {
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") node.setAttribute("class", value);
      else if (key === "text") node.textContent = String(value);
      else node.setAttribute(key, String(value));
    }
  }
  appendAll(node, children);
  return node;
}

function appendAll(node, children) {
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false || child === "") continue;
    node.append(child instanceof Node ? child : String(child));
  }
}

/** The URL if it is an absolute http(s) address, otherwise null. */
function safeUrl(value) {
  if (typeof value !== "string") return null;
  return value.startsWith("https://") || value.startsWith("http://") ? value : null;
}

/** A new-tab link to an API-supplied URL, or plain text when the URL is unsafe. */
function externalLink(url, text, className = "ext") {
  const href = safeUrl(url);
  if (!href) return h("span", { class: "muted", text: "No link available" });
  return h(
    "a",
    { href, target: "_blank", rel: "noopener noreferrer", class: className },
    text,
    h("span", { class: "visually-hidden", text: " (opens in a new tab)" }),
    h("span", { "aria-hidden": "true", text: " ↗" }),
  );
}

/** A count from the record, grouped for reading; a missing count shows as a dash. */
function num(value) {
  return Number.isFinite(value) ? value.toLocaleString("en-US") : "—";
}

/** The unit word after a count from the record: "1 claim", "3 claims". */
function unit(count, one, many) {
  return count === 1 ? one : many;
}

/** "1 filing" / "3 filings": a count from the API with its unit. */
function plural(count, one, many) {
  return `${num(Number.isFinite(count) ? count : 0)} ${unit(count, one, many)}`;
}

/** A count from `run.coverage`, tagged with its field so the browser test can compare it. */
function cov(coverage, field) {
  return h("span", { class: "count-value", "data-coverage": field, text: num(coverage?.[field]) });
}

/** An ISO timestamp shown as "YYYY-MM-DD HH:MM UTC". */
function utc(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso);
  return `${date.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

function capitalize(word) {
  const text = String(word ?? "");
  return text ? text[0].toUpperCase() + text.slice(1) : text;
}

/** Only known enum values become CSS class suffixes. */
function token(value, allowed) {
  return Object.hasOwn(allowed, value) ? value : "unknown";
}

function formGloss(form) {
  if (!form) return "";
  return FORM_GLOSS[String(form).toUpperCase()] ?? "";
}

function str(value) {
  return typeof value === "string" ? value : "";
}

function list(value) {
  return Array.isArray(value) ? value : [];
}

// ---------------------------------------------------------------- marks

/** ▲ amber: something limits this record. */
function limitGlyph() {
  return h("span", { class: "glyph g-limit", "aria-hidden": "true", text: "▲" });
}

/** A line that says what limits the record, with its mark. */
function limitLine(tag, ...content) {
  return h(tag, { class: "mark-limit" }, limitGlyph(), " ", ...content);
}

/** ✎ violet: written by a model and not checked for meaning (by a person, when a second model read it). */
function modelBadge(words = MODEL_BADGE) {
  return h(
    "span",
    { class: "badge-model" },
    h("span", { class: "glyph g-model", "aria-hidden": "true", text: "✎" }),
    ` ${words}`,
  );
}

/** ◎ / ◐ violet, double rule: a second model agrees, or agrees only in part. */
function meaningMark(support) {
  return h(
    "span",
    { class: `meaning-mark m-${support}` },
    h("span", { class: "glyph g-meaning", "aria-hidden": "true", text: MEANING_MARK[support] }),
    h("span", { class: "meaning-words", text: MEANING_WORDS[support] }),
  );
}

/** The second model's own sentence, under its double violet rule. `attr` tags it for the browser test. */
function checkerReason(reason, attr) {
  return h("p", { class: "checker-reason" }, h("span", { class: "label", text: "Second model's reason: " }), h("span", { [attr]: "", text: reason }));
}

/** Whether a second model read a finding's evidence: its support check has an outcome. */
function meaningRead(finding) {
  return ["passed", "partly", "failed"].includes(str(finding?.checks?.support));
}

/** Whether the run's record names a second model that checked meaning. */
function runMeaningChecked(run) {
  const checker = str(run?.checker);
  return checker !== "" && checker !== "none";
}

/**
 * ƒ olive, dotted: computed by a fixed rule and not checked by a person. `label` is the
 * mark's words; the legend defines it once.
 */
function ruleMark(label = "Fixed rule, not checked by a person") {
  return h(
    "span",
    { class: "rule-mark" },
    h("span", { class: "glyph g-rule", "aria-hidden": "true", text: "ƒ" }),
    h("span", { class: "rule-label", text: label }),
  );
}

/**
 * A long provenance note from the record, shortened for the eye and kept whole in the DOM.
 * The backend writes a replayed engine's note as "replayed from cassette …: N responses
 * recorded via <who answered> …; … with <models>, <dates>": the first clause (recorded, and
 * by whom) and the models stay in view; the full note is one click away. A note without a
 * second clause is shown as it is.
 */
function provenanceDetail(detail) {
  const full = str(detail);
  const first = provenanceFirst(full);
  if (!first) return full;
  return h("details", { class: "prov-more" }, h("summary", { class: "prov-first", text: first }), h("span", { class: "prov-full", text: full }));
}

/** The short form of a replayed engine's note (see provenanceDetail), or "" when it is not one or is already short. */
function provenanceFirst(detail) {
  const full = str(detail);
  const cut = full.indexOf("; ");
  if (!full.startsWith("replayed from cassette ") || cut < 0) return "";
  let first = full.slice(0, cut);
  const withAt = full.lastIndexOf(" with ");
  if (withAt > cut) first += ` … with ${full.slice(withAt + " with ".length)}`;
  return first;
}

/**
 * Sample mode, answers replayed from a cassette: the masthead's first line says so and who
 * answered, from the run's own note; the configured engine and checker, in full, are one
 * click away and stay in the DOM.
 */
function foldEngineLine(detail) {
  const first = provenanceFirst(detail);
  if (!first) return;
  const rest = [...els.engineLine.childNodes];
  els.engineLine.replaceChildren(
    h(
      "details",
      { class: "prov-more engine-more" },
      h("summary", { class: "prov-first" }, h("span", { class: "engine-name", text: "Recorded answers: " }), first),
      h("span", { class: "prov-full" }, ...rest),
    ),
  );
}

/** ! red: the server refused your input. */
function rejectGlyph() {
  return h("span", { class: "glyph g-reject", "aria-hidden": "true", text: "!" });
}

/**
 * A field that may have been written by a model. `id` names it for the browser
 * test; when `model` is true it carries the violet badge and border. `badge`
 * overrides the badge's words.
 */
function writtenField(tag, id, model, content, badge = MODEL_BADGE) {
  return h(tag, { class: model ? "mw is-model" : "mw", "data-mw": id }, content, model ? modelBadge(badge) : "");
}

/** A claim was assessed by a model when its engine is named and is not the extractive one. */
function modelAssessed(claim) {
  const by = str(claim?.assessed_by);
  return by !== "" && by !== EXTRACTIVE;
}

function verdictLabel(verdict) {
  return state.meta?.verdict_labels?.[verdict] ?? verdict ?? "Not assessed yet";
}

function verdictNote(verdict) {
  return state.meta?.verdict_notes?.[verdict] ?? "";
}

function verdictPill(verdict) {
  const key = verdict ? token(verdict, VERDICT_GLYPH) : "pending";
  return h(
    "span",
    { class: `pill verdict v-${key}`, "data-verdict": verdict ?? "pending", title: verdictNote(verdict) || null },
    h("span", { class: "glyph", "aria-hidden": "true", text: VERDICT_GLYPH[verdict] ?? "…" }),
    h("span", { class: "pill-label", text: verdictLabel(verdict) }),
  );
}

function stancePill(stance) {
  const key = token(stance, STANCE_MARK);
  const [glyph, label] = STANCE_MARK[stance] ?? ["•", String(stance)];
  return h(
    "span",
    { class: `pill stance s-${key}` },
    h("span", { class: "glyph", "aria-hidden": "true", text: glyph }),
    h("span", { class: "pill-label", text: label }),
  );
}

function decisionLabel(value) {
  return str(state.meta?.decision_labels?.[value]) || DECISION_FALLBACK[value] || String(value);
}

/** The reader's decision, as the server recorded it: "accepted", "rejected" or "undecided". */
function decisionMark(value) {
  const key = token(value, DECISION_MARK);
  return h(
    "span",
    { class: `decision-mark d-${key}`, "data-decision": key },
    h("span", { class: "glyph", "aria-hidden": "true", text: DECISION_MARK[key] ?? DECISION_MARK.undecided }),
    h("span", { class: "decision-label", text: decisionLabel(value) }),
  );
}

function statusMark(status) {
  const glyph = STATUS_GLYPH[status] ?? "·";
  return h("span", { class: LIMITING_STATUS.has(status) ? "glyph g-limit" : "glyph g-status", "aria-hidden": "true", text: glyph });
}

function fillList(listEl, items, emptyText, limit = false) {
  listEl.replaceChildren();
  const entries = list(items);
  if (entries.length === 0) {
    if (emptyText) listEl.append(h("li", { class: "muted", text: emptyText }));
    return;
  }
  for (const item of entries) listEl.append(limit ? limitLine("li", String(item)) : h("li", { text: String(item) }));
}

// ---------------------------------------------------------------- API

class ApiError extends Error {
  constructor(message, status, details = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.details = details;
  }
}

/** Fetch JSON; on failure throw an ApiError carrying the server's own message. */
async function api(url, options = {}) {
  let response;
  try {
    response = await fetch(url, { ...options, headers: { accept: "application/json", ...(options.headers ?? {}) } });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError("the server could not be reached", 0);
  }
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    // The app's refusals carry `error`; FastAPI's own 404s carry `detail`.
    const message =
      typeof payload?.error === "string" ? payload.error : typeof payload?.detail === "string" ? payload.detail : `the server answered HTTP ${response.status}`;
    const details = Array.isArray(payload?.details) ? payload.details : [];
    throw new ApiError(message, response.status, details);
  }
  if (payload === null || typeof payload !== "object") {
    throw new ApiError("the server's answer was not readable JSON", response.status);
  }
  return payload;
}

// ---------------------------------------------------------------- meta

async function loadMeta() {
  els.metaError.hidden = true;
  setFormEnabled(false);
  try {
    applyMeta(await api("/api/meta"));
  } catch (error) {
    showAlert(
      els.metaError,
      `The page could not load its limits and wording from the server: ${error.message}. The form stays disabled until they load.`,
      "Try again",
      loadMeta,
    );
  }
}

/** `sample`: the engine line will be folded by foldEngineLine, so the checker's note is left whole here. */
function applyMeta(meta, { sample = false } = {}) {
  if (!meta || typeof meta !== "object" || !meta.limits) throw new ApiError("the wording and limits are missing", 0);
  state.meta = meta;
  const limits = meta.limits;
  const engine = str(meta.engine);
  // `checker` is absent from servers older than the meaning check: then nothing is said about it.
  const checker = meta.checker && typeof meta.checker === "object" ? meta.checker : null;
  const checkerName = str(checker?.name);
  // A replayed checker's long note keeps its first clause (recorded, and by whom) in view.
  let checkerText = [];
  if (checker) {
    checkerText = checkerName && checkerName !== "none"
      ? [" Configured meaning check: ", sample ? str(checker.detail) || checkerName : provenanceDetail(str(checker.detail) || checkerName), "."]
      : [" No second model is configured to check meaning."];
  }
  els.engineLine.replaceChildren(
    h("span", { class: "engine-name", text: `Configured engine: ${engine || "not stated"}` }),
    ENGINE_GLOSS[engine] ? ` (${ENGINE_GLOSS[engine]}). Each result names the engine that actually did the work.` : "",
    ...checkerText,
  );
  if (Number.isInteger(limits.MAX_DECISION_CHARS)) els.decision.maxLength = limits.MAX_DECISION_CHARS;
  if (Number.isInteger(limits.MAX_SCOPE_CHARS)) els.scope.maxLength = limits.MAX_SCOPE_CHARS;
  els.filings.min = "1";
  els.filings.max = String(limits.MAX_FILINGS);
  if (!els.filings.value) els.filings.value = String(limits.DEFAULT_FILINGS);
  els.scopeHint.textContent = `Definitions and exclusions the engine should respect. Up to ${plural(limits.MAX_SCOPE_CHARS, "character", "characters")}.`;
  els.filingsHint.textContent = `1 to ${limits.MAX_FILINGS}; default ${limits.DEFAULT_FILINGS}. The latest annual report (10-K), then the quarterly reports (10-Q) filed after it, newest first.`;
  els.urlsHint.textContent = `A press release or investor-relations page, one http(s) address per line, up to ${limits.MAX_EXTRA_URLS}.`;
  if (Number.isInteger(limits.MAX_THESIS_NAME_CHARS)) {
    els.thesisName.maxLength = limits.MAX_THESIS_NAME_CHARS;
    $("thesis-name-hint").textContent = `Up to ${plural(limits.MAX_THESIS_NAME_CHARS, "character", "characters")}. Saved with the ticker, decision and claims above, so you can run it again when a new filing arrives.`;
  }
  updateCounts();
  setFormEnabled(!state.sample);
  els.example.disabled = state.sample || !meta.example;
}

function setFormEnabled(enabled) {
  els.submit.disabled = !enabled;
  els.figuresOnly.disabled = !enabled;
  els.filingChanges.disabled = !enabled;
  els.changesForm.disabled = !enabled;
  els.breakdowns.disabled = !enabled;
  els.breakdownsForm.disabled = !enabled;
  if (els.restatements) els.restatements.disabled = !enabled;
  if (els.asOf) els.asOf.disabled = !enabled;
  els.example.disabled = !enabled;
  els.saveThesis.disabled = !enabled;
}

// ---------------------------------------------------------------- form

/** Non-empty trimmed lines of a textarea. */
function lines(textarea) {
  return textarea.value
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

function readForm() {
  const filingsText = els.filings.value.trim();
  return {
    ticker: els.ticker.value.trim(),
    decision: els.decision.value.trim(),
    claims: lines(els.claims),
    scope_notes: els.scope.value.trim(),
    filings: filingsText === "" ? state.meta?.limits?.DEFAULT_FILINGS : Number(filingsText),
    extra_urls: lines(els.urls),
    // A strict boolean: the server refuses anything else.
    tagged_figures: els.tagged.checked === true,
    // "YYYY-MM-DD" from the date control, or null for a run of the newest filings. The server checks the date.
    as_of: els.asOf?.value.trim() || null,
  };
}

/** Immediate feedback against the limits from /api/meta. The server re-checks everything. */
function validate(body, limits) {
  const problems = [];
  const add = (field, message) => problems.push({ field, message });

  if (!body.ticker) add("ticker", "Enter a ticker, such as NVDA.");

  const d = body.decision.length;
  if (d < limits.MIN_DECISION_CHARS || d > limits.MAX_DECISION_CHARS) {
    add("decision", `Must be ${limits.MIN_DECISION_CHARS} to ${limits.MAX_DECISION_CHARS} characters; it has ${d}.`);
  }

  if (body.claims.length === 0) add("claims", "Enter at least one claim, one per line.");
  if (body.claims.length > limits.MAX_CLAIMS) {
    add("claims", `At most ${limits.MAX_CLAIMS} claims; there are ${body.claims.length}.`);
  }
  const seen = new Map();
  body.claims.forEach((claim, index) => {
    const text = claim.split(/\s+/).filter(Boolean).join(" ");
    if (text.length < limits.MIN_CLAIM_CHARS || text.length > limits.MAX_CLAIM_CHARS) {
      add("claims", `Claim ${index + 1} must be ${limits.MIN_CLAIM_CHARS} to ${limits.MAX_CLAIM_CHARS} characters; it has ${text.length}.`);
    }
    const key = text.toLowerCase();
    if (seen.has(key)) add("claims", `Claim ${index + 1} repeats claim ${seen.get(key) + 1}.`);
    else seen.set(key, index);
  });

  if (body.scope_notes.length > limits.MAX_SCOPE_CHARS) {
    add("scope_notes", `At most ${limits.MAX_SCOPE_CHARS} characters; it has ${body.scope_notes.length}.`);
  }

  if (!Number.isInteger(body.filings) || body.filings < 1 || body.filings > limits.MAX_FILINGS) {
    add("filings", `Enter a whole number from 1 to ${limits.MAX_FILINGS}.`);
  }

  if (body.extra_urls.length > limits.MAX_EXTRA_URLS) {
    add("extra_urls", `At most ${limits.MAX_EXTRA_URLS} pages; there are ${body.extra_urls.length}.`);
  }
  const seenUrls = new Set();
  body.extra_urls.forEach((url, index) => {
    if (!safeUrl(url)) add("extra_urls", `Line ${index + 1} must start with https:// or http://.`);
    if (seenUrls.has(url)) add("extra_urls", `Line ${index + 1} repeats an earlier address.`);
    seenUrls.add(url);
  });
  return problems;
}

/**
 * The form field a server or client error path belongs to: "claims.2" -> "claims",
 * "path.ticker" -> "ticker", "request.claims.0" (saving a thesis) -> "claims".
 */
function rootField(field) {
  return String(field ?? "")
    .replace(/^(path|query|request)\./, "")
    .split(/[.[]/)[0];
}

function clearFieldErrors() {
  for (const field of Object.keys(FIELD_NAMES)) setFieldError(field, []);
  els.formErrors.replaceChildren();
  els.formErrors.className = "alert form-alert";
  els.formErrors.hidden = true;
}

function setFieldError(field, messages) {
  const input = $(field);
  const slot = $(`err-${field}`);
  if (!input || !slot) return;
  slot.replaceChildren();
  if (messages.length) slot.append(rejectGlyph(), ` ${messages.join(" ")}`);
  slot.hidden = messages.length === 0;
  if (messages.length) input.setAttribute("aria-invalid", "true");
  else input.removeAttribute("aria-invalid");
}

/**
 * Show problems next to their fields and, with their field names, in one list
 * above the buttons. `problems` is [{field, message}] from the client or a 422.
 */
function showProblems(problems, heading) {
  clearFieldErrors();
  if (problems.length === 0) return;
  const byField = new Map();
  for (const { field, message } of problems) {
    const root = rootField(field);
    if (!byField.has(root)) byField.set(root, []);
    byField.get(root).push(String(message));
  }
  for (const [root, messages] of byField) setFieldError(root, messages);
  if ([...byField.keys()].some((root) => ["scope_notes", "filings", "extra_urls"].includes(root))) {
    els.advanced.open = true;
  }
  const items = h("ul");
  for (const { field, message } of problems) {
    const name = FIELD_NAMES[rootField(field)];
    items.append(h("li", null, h("code", { text: String(field ?? "request") }), name ? ` (${name})` : "", `: ${message}`));
  }
  els.formErrors.replaceChildren(h("p", { class: "alert-title" }, rejectGlyph(), ` ${heading}`), items);
  els.formErrors.className = "alert form-alert reject";
  els.formErrors.hidden = false;
  const first = $(rootField(problems[0].field));
  if (first) first.focus();
}

/** A message that is not a rejected input (the service is down, say): neutral, no mark. */
function showFormMessage(message) {
  clearFieldErrors();
  els.formErrors.replaceChildren(h("p", { text: message }));
  els.formErrors.hidden = false;
}

/** Live hints while typing: how many claims and decision characters, against the limits. */
function updateCounts() {
  const limits = state.meta?.limits;
  if (!limits) return;
  const claimCount = lines(els.claims).length;
  const over = claimCount > limits.MAX_CLAIMS;
  els.claimsCount.replaceChildren(over ? rejectGlyph() : "", `${over ? " " : ""}${claimCount} of ${limits.MAX_CLAIMS} claims.`);
  els.claimsCount.classList.toggle("over", over);
  const chars = els.decision.value.trim().length;
  els.decisionCount.textContent = `${chars} of ${limits.MAX_DECISION_CHARS} characters (at least ${limits.MIN_DECISION_CHARS}).`;
}

async function onSubmit(event) {
  event.preventDefault();
  if (state.sample || !state.meta) return;
  const body = readForm();
  const problems = validate(body, state.meta.limits);
  if (problems.length) {
    showProblems(problems, "Check these fields before the run can start:");
    return;
  }
  clearFieldErrors();
  els.submit.disabled = true;
  els.submit.textContent = "Starting…";
  try {
    const started = await api("/api/runs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (typeof started.id !== "string" || !started.id) throw new ApiError("the server did not return a run id", 0);
    watchRun(started.id);
    refreshRecent();
    focusResults();
  } catch (error) {
    if (error.status === 422 && error.details.length) {
      showProblems(error.details, "The server refused the request:");
    } else if (error.status === 503) {
      showFormMessage(`The service is unavailable: ${error.message}`);
    } else {
      showFormMessage(`The run could not be started: ${error.message}.`);
    }
  } finally {
    els.submit.disabled = false;
    els.submit.textContent = "Test the thesis";
  }
}

function focusResults() {
  els.resultPanel.focus({ preventScroll: true });
  if (window.matchMedia("(max-width: 900px)").matches) {
    els.resultPanel.scrollIntoView({ block: "start", behavior: "smooth" });
  }
}

function loadExample() {
  const example = state.meta?.example;
  if (!example) return;
  els.ticker.value = example.ticker ?? "";
  els.decision.value = example.decision ?? "";
  els.claims.value = list(example.claims).join("\n");
  els.scope.value = example.scope_notes ?? "";
  els.filings.value = String(example.filings ?? state.meta.limits.DEFAULT_FILINGS);
  els.urls.value = list(example.extra_urls).join("\n");
  els.tagged.checked = example.tagged_figures === true;
  if (els.asOf) els.asOf.value = str(example.as_of);
  els.advanced.open = Boolean(example.scope_notes || list(example.extra_urls).length || els.tagged.checked);
  clearFieldErrors();
  updateCounts();
  els.ticker.focus();
}

// ---------------------------------------------------------------- reported figures only

/** Look up a company's reported figures without starting a run. */
async function onFiguresOnly() {
  if (state.sample || !state.meta) return;
  const ticker = els.ticker.value.trim();
  if (!ticker) {
    showProblems([{ field: "ticker", message: "Enter a ticker, such as NVDA." }], "Check this field before looking up figures:");
    return;
  }
  clearFieldErrors();
  stopWatching();
  const seq = ++state.viewSeq;
  state.runId = null;
  state.run = null;
  state.thesisId = null;
  markRecent();
  history.replaceState(null, "", `${location.pathname}${location.search}`);
  hideRunView();
  els.loading.textContent = `Looking up the reported figures for ${ticker.toUpperCase()}…`;
  els.loading.hidden = false;
  els.figuresOnly.disabled = true;
  try {
    const report = await api(`/api/companies/${encodeURIComponent(ticker.toUpperCase())}/metrics`);
    if (seq !== state.viewSeq) return;
    if (!Array.isArray(report.metrics)) throw new ApiError("the answer has no list of figures", 0);
    renderFiguresOnly(report);
    focusResults();
  } catch (error) {
    if (seq !== state.viewSeq) return;
    els.loading.hidden = true;
    if (error.status === 422 && error.details.length) {
      showProblems(error.details, "The server refused the lookup:");
    } else if (error.status === 503) {
      showFormMessage(`The service is unavailable: ${error.message}`);
    } else {
      showLoadError(`The reported figures could not be loaded: ${error.message}.`, onFiguresOnly);
    }
  } finally {
    els.figuresOnly.disabled = state.sample;
  }
}

function renderFiguresOnly(report) {
  renderCommandBar(null);
  els.loading.hidden = true;
  els.loadError.hidden = true;
  els.empty.hidden = true;
  els.runView.hidden = true;
  els.thesisView.hidden = true;
  els.inboxView.hidden = true;
  els.ledgerView.hidden = true;
  els.changesView.hidden = true;
  els.breakdownsView.hidden = true;
  els.figuresView.hidden = false;
  document.body.classList.add("has-run");
  els.figuresHead.replaceChildren(
    h(
      "div",
      { class: "run-head-main" },
      companyTitle({ name: str(report.company), cik: report.cik }, str(report.ticker)),
      h("p", { class: "run-meta", text: "Reported figures read from the company's XBRL data. No run was started and no claim was tested." }),
    ),
  );
  renderFigures(els.figuresStandalone, { metrics: report.metrics, series: report.series, notes: report.notes });
}

// ---------------------------------------------------------------- what changed between two filings

/** Compare the company's two latest filings of the chosen form, without starting a run. */
async function onFilingChanges() {
  if (state.sample || !state.meta) return;
  const ticker = els.ticker.value.trim();
  const form = els.changesForm.value;
  if (!ticker) {
    showProblems([{ field: "ticker", message: "Enter a ticker, such as NVDA." }], "Check this field before comparing filings:");
    return;
  }
  clearFieldErrors();
  stopWatching();
  const seq = ++state.viewSeq;
  state.runId = null;
  state.run = null;
  state.thesisId = null;
  markRecent();
  history.replaceState(null, "", `${location.pathname}${location.search}`);
  hideRunView();
  els.loading.textContent = `Comparing the two latest ${form} filings of ${ticker.toUpperCase()}…`;
  els.loading.hidden = false;
  els.filingChanges.disabled = true;
  try {
    const record = await api(`/api/companies/${encodeURIComponent(ticker.toUpperCase())}/changes?form=${encodeURIComponent(form)}`);
    if (seq !== state.viewSeq) return;
    renderChanges(record, "");
    focusResults();
  } catch (error) {
    if (seq !== state.viewSeq) return;
    els.loading.hidden = true;
    if (error.status === 422 && error.details.length) {
      // The server names the form choice "form"; on this page it is the "changes_form" select.
      const details = error.details.map((d) => ({ ...d, field: rootField(d.field) === "form" ? "changes_form" : d.field }));
      showProblems(details, "The server refused the comparison:");
    } else {
      // 503: EDGAR could not be read, or it lists fewer than two such filings; the server says which.
      showLoadError(`The filings could not be compared: ${error.message}.`, onFilingChanges);
    }
  } finally {
    els.filingChanges.disabled = state.sample;
  }
}

/** A change mark: its glyph and label, in the change family's own style. */
function changeMark(kind) {
  const [glyph, label] = CHANGE_MARK[kind];
  return h(
    "span",
    { class: `chg-mark c-${kind}` },
    h("span", { class: "glyph g-chg", "aria-hidden": "true", text: glyph }),
    h("span", { class: "chg-label", text: label }),
  );
}

/** Only the glyph of a change mark, for a column of counts; its label is in the column head. */
function changeGlyph(kind) {
  return h("span", { class: `glyph g-chg c-${kind}`, "aria-hidden": "true", text: CHANGE_MARK[kind][0] });
}

/** One filing of the pair in words, as a link to its document. */
function filingLink(side) {
  return externalLink(side?.url, `the ${str(side?.form) || "filing"} for the period ended ${str(side?.period_end) || "—"}, filed ${str(side?.filed_date) || "—"}`);
}

/** Draw a FilingChanges record exactly as the server computed it: message, notes, totals, then each Item. */
function renderChanges(record, sampleNote) {
  if (!record || typeof record !== "object" || !Array.isArray(record.items) || !record.earlier || !record.later) {
    showLoadError("The comparison could not be shown: the record names no filings or Items.", null);
    return;
  }
  renderCommandBar(null);
  els.loading.hidden = true;
  els.loadError.hidden = true;
  els.empty.hidden = true;
  els.runView.hidden = true;
  els.figuresView.hidden = true;
  els.thesisView.hidden = true;
  els.inboxView.hidden = true;
  els.ledgerView.hidden = true;
  els.breakdownsView.hidden = true;
  els.changesView.hidden = false;
  document.body.classList.add("has-run");

  const company = record.company ?? {};
  els.changesHead.replaceChildren(
    h(
      "div",
      { class: "run-head-main" },
      state.sample ? h("span", { class: "page-tag inline", text: "Sample record" }) : "",
      companyTitle(company),
      h("p", { class: "run-meta", text: "What changed between two of the company's filings, Item by Item. No run was started and no claim was tested." }),
      sampleNote ? h("p", { class: "run-meta", text: `Sample: ${sampleNote}` }) : "",
    ),
  );

  const later = record.later;
  const earlier = record.earlier;
  const t = record.totals ?? {};
  const total = (field) => h("span", { class: "count-value", "data-chg-total": field, text: num(t[field]) });
  const parts = [
    h("p", { class: "changes-lead" }, "This compares the later filing, ", filingLink(later), ", against the earlier one, ", filingLink(earlier), "."),
    h(
      "p",
      { class: "changes-explain" },
      "Each paragraph is matched with the other filing's paragraphs in the same Item; a paragraph here is a longer line of text that is not a table row. The five counts are of paragraphs. Unchanged: the same text, perhaps moved within its Item. ",
      changeMark("numbers_only"),
      ": the same once numbers, dates and amounts are set aside. ",
      changeMark("reworded"),
      ": a paragraph in the later filing that mostly matches one in the earlier. ",
      changeMark("added"),
      " and ",
      changeMark("removed"),
      ": a paragraph with no counterpart in the other filing. Shorter lines and table rows are counted apart, in the same classes, and never listed. Every line of each filing is in exactly one count. A sub-heading is not a line: the sub-headings found in only one filing are named under their Item.",
    ),
    h(
      "p",
      { class: "changes-unknown" },
      h("strong", { text: "What this does not know: " }),
      "it compares the text this tool extracted from each filing, not the filing as printed; it does not know why anything changed; and a paragraph split in two reads as one reworded paragraph and one added.",
    ),
  ];
  if (Number.isFinite(later.item_coverage) && Number.isFinite(earlier.item_coverage)) {
    parts.push(h("p", { class: "hint", text: `Share of each filing's text that sits under a numbered Item, as the record gives it: later ${later.item_coverage}, earlier ${earlier.item_coverage}.` }));
  }
  const notes = list(record.notes);
  if (notes.length) {
    const notesList = h("ul", { class: "mark-list", id: "changes-notes" });
    fillList(notesList, notes, "", true);
    parts.push(h("section", { class: "block", "aria-label": "Notes on this comparison" }, h("h3", { class: "block-title", text: "Notes on this comparison" }), notesList));
  }
  parts.push(
    h(
      "section",
      { class: "block", "aria-labelledby": "chg-totals-title" },
      h("h3", { class: "block-title", id: "chg-totals-title", text: "All Items" }),
      h(
        "p",
        { class: "rule-note", "data-rule": "totals" },
        ruleMark(),
        " These classes come from a fixed rule, a word-overlap threshold with numbers set aside, that no person has checked against these filings.",
      ),
      h(
        "ul",
        { class: "chg-totals" },
        h("li", null, total("unchanged"), " unchanged"),
        ["numbers_only", "reworded", "added", "removed"].map((kind) => h("li", null, total(kind), " ", changeMark(kind))),
        h("li", { class: "chg-minor" }, minorLine((field) => total(field))),
      ),
    ),
  );
  const items = record.items;
  // Item 1A starts open (the Item people read first); without it, the first Item that lists anything.
  const riskFactors = items.findIndex((item) => str(item.item).startsWith("Item 1A"));
  const firstOpen = riskFactors >= 0 ? riskFactors : items.findIndex(hasListed);
  parts.push(
    h(
      "section",
      { class: "block", "aria-labelledby": "chg-items-title" },
      h("h3", { class: "block-title", id: "chg-items-title", text: "By Item" }),
      h("p", { class: "rule-note", "data-rule": "items" }, ruleMark(), " The same rule sorts each Item's counts and lists."),
      h("p", { class: "hint", text: "Open an Item to read its sub-headings found in one filing only, and the paragraphs added, removed, reworded or changed only in their numbers." }),
      h(
        "div",
        { class: "chg-grid chg-header", "aria-hidden": "true" },
        h("span", { text: "Item" }),
        h("span", { class: "chg-num", text: "Unchanged" }),
        ["numbers_only", "reworded", "added", "removed"].map((kind) => h("span", { class: "chg-num" }, changeGlyph(kind), ` ${CHANGE_MARK[kind][1]}`)),
      ),
      items.length ? items.map((item, index) => renderChangeItem(item, index, index === firstOpen)) : h("p", { class: "muted", text: "The record lists no Item." }),
    ),
  );
  els.changesBody.replaceChildren(...parts);
}

/** One Item: its five paragraph counts and four short-line counts as a row, opening to its lists. */
function renderChangeItem(item, index, open = false) {
  const presence = { later: "Only in the later filing", earlier: "Only in the earlier filing" }[item.present_in] ?? "";
  const word = (field) => (field === "unchanged" ? "unchanged" : CHANGE_MARK[field][1].toLowerCase());
  const cell = (field) =>
    h(
      "span",
      { class: "chg-num" },
      field === "unchanged" ? "" : changeGlyph(field),
      h("span", { class: "chg-count count-value", "data-chg-field": field, text: num(item[field]) }),
      h("span", { class: "visually-hidden", text: ` ${word(field)}` }),
    );
  const summary = h(
    "summary",
    { class: "chg-grid" },
    h(
      "span",
      { class: "chg-name" },
      h("span", { class: "chg-item-title", text: str(item.item) }),
      presence ? h("span", { class: "chg-presence", "data-present-in": item.present_in, text: presence }) : "",
      h("span", { class: "chg-minor" }, minorLine((field) => h("span", { "data-chg-field": field, text: num(item[field]) }))),
    ),
    CHANGE_COUNTS.map(cell),
  );
  return h("details", { class: "chg-item", "data-item-index": index, "data-item": str(item.item), open }, summary, renderChangeLists(item));
}

/** "Short lines and table rows: A unchanged, B numbers only, C added, D removed"; `count` draws each number. */
function minorLine(count) {
  return [
    "Short lines and table rows: ",
    count("minor_unchanged"),
    " unchanged, ",
    count("minor_numbers_only"),
    " numbers only, ",
    count("minor_added"),
    " added, ",
    count("minor_removed"),
    " removed",
  ];
}

/** Whether an Item lists anything: a paragraph, a pair, or a sub-heading in only one filing. */
function hasListed(item) {
  return ["added_paragraphs", "removed_paragraphs", "reworded_paragraphs", "numbers_only_paragraphs", "subheadings_added", "subheadings_removed"].some(
    (key) => list(item[key]).length > 0,
  );
}

/**
 * The words on a link into one of the two filings, by the record's `link_kind`: at the
 * paragraph, at its first line, or the filing only. A record without `link_kind` keeps
 * "at this paragraph". The run view says the same of a quote (`LINK_WORDS`).
 */
function changeLinkWords(paragraph, side) {
  const kind = str(paragraph?.link_kind);
  if (kind === "first-line") return `Open in the ${side} filing, at its first line`;
  if (kind === "document") return `Open the ${side} filing (the link opens the filing only: this text cannot be located in it)`;
  return `Open in the ${side} filing, at this paragraph`;
}

/** An Item's sub-headings found in one filing only, then its four lists, each with its truncation as the record states it. */
function renderChangeLists(item) {
  const body = h("div", { class: "chg-lists" });
  if (!hasListed(item)) {
    body.append(h("p", { class: "muted", text: "No paragraph or sub-heading was added, removed, reworded or changed in its numbers in this Item." }));
    return body;
  }
  const subheadings = (kind, side, title, names) =>
    h(
      "section",
      { class: "chg-list chg-subs", "data-subheadings": side },
      h("h4", { class: "chg-list-title" }, changeMark(kind), ` ${title}`),
      h("ul", { class: "chg-sub-list" }, names.map((name) => h("li", { text: String(name) }))),
    );
  const subsAdded = list(item.subheadings_added);
  const subsRemoved = list(item.subheadings_removed);
  if (subsAdded.length) body.append(subheadings("added", "later", "Sub-headings only in the later filing", subsAdded));
  if (subsRemoved.length) body.append(subheadings("removed", "earlier", "Sub-headings only in the earlier filing", subsRemoved));
  const added = list(item.added_paragraphs);
  const removed = list(item.removed_paragraphs);
  const reworded = list(item.reworded_paragraphs);
  const numbersOnly = list(item.numbers_only_paragraphs);
  const cut = item.truncated ?? {};
  if (added.length) body.append(changeList("added", "Added in the later filing", added, item.added, cut.added, (p) => paragraphEntry(p, "later")));
  if (removed.length) body.append(changeList("removed", "Removed from the earlier filing", removed, item.removed, cut.removed, (p) => paragraphEntry(p, "earlier")));
  if (reworded.length) body.append(changeList("reworded", "Reworded: the later paragraph, with the words it added and dropped", reworded, item.reworded, cut.reworded, (pair) => pairEntry(pair, true)));
  if (numbersOnly.length) body.append(changeList("numbers_only", "Numbers only: the same words, the figures that moved", numbersOnly, item.numbers_only, cut.numbers_only, (pair) => pairEntry(pair, false)));
  return body;
}

function changeList(kind, title, entries, count, truncated, draw) {
  return h(
    "section",
    { class: `chg-list l-${kind}`, "data-list": kind },
    h(
      "h4",
      { class: "chg-list-title" },
      changeMark(kind),
      ` ${title}`,
      truncated ? h("span", { class: "chg-trunc", "data-truncated": kind, text: ` · showing the first ${num(entries.length)} of ${num(count)}` }) : "",
    ),
    h("ol", { class: "chg-paras" }, entries.map(draw)),
  );
}

/**
 * An added or removed paragraph: its text, where it sits, and a link into its filing ("later"
 * or "earlier"). `head` (optional) goes first: the run view puts the mark and shared words there.
 */
function paragraphEntry(paragraph, side, head = null) {
  return h(
    "li",
    null,
    head,
    h("p", { class: "chg-text", text: str(paragraph.text) }),
    h(
      "p",
      { class: "chg-where" },
      h("span", { class: "label", text: "Located under: " }),
      str(paragraph.locator) || "location not recorded",
      " · ",
      externalLink(paragraph.link, changeLinkWords(paragraph, side)),
    ),
  );
}

/**
 * A reworded or numbers-only pair: the later paragraph drawn from `segments`, in reading
 * order, then (for a reworded pair) the record's similarity, and links into both filings.
 */
function pairEntry(pair, withSimilarity, head = null) {
  const quote = h("blockquote", { class: "chg-reworded" });
  list(pair.segments).forEach((segment, position) => {
    if (position > 0) quote.append(" ");
    const words = str(segment.text);
    if (segment.kind === "added") quote.append(h("ins", { class: "seg seg-add" }, h("span", { class: "visually-hidden", text: "[added] " }), words));
    else if (segment.kind === "removed") quote.append(h("del", { class: "seg seg-del" }, h("span", { class: "visually-hidden", text: "[removed] " }), words));
    else quote.append(words);
  });
  return h(
    "li",
    null,
    head,
    quote,
    h(
      "p",
      { class: "chg-where" },
      withSimilarity
        ? [
            h("span", { class: "label", text: "Word overlap with the earlier paragraph (Jaccard similarity of the word sets, common words and figures left out, so 1 does not mean identical; 0 to 1): " }),
            h("span", { "data-similarity": "", text: Number.isFinite(pair.similarity) ? String(pair.similarity) : "not recorded" }),
            " · ",
          ]
        : "",
      h("span", { class: "label", text: "Located under: " }),
      str(pair.after?.locator) || "location not recorded",
      " · ",
      externalLink(pair.after?.link, changeLinkWords(pair.after, "later")),
      " · ",
      externalLink(pair.before?.link, changeLinkWords(pair.before, "earlier")),
    ),
  );
}

// ---------------------------------------------------------------- tagged breakdowns

/** "Segments and customers (tagged facts)": GET /api/companies/{ticker}/breakdowns?form=. Starts no run. */
async function onBreakdowns() {
  if (state.sample || !state.meta) return;
  const ticker = els.ticker.value.trim();
  const form = els.breakdownsForm.value;
  if (!ticker) {
    showProblems([{ field: "ticker", message: "Enter a ticker, such as NVDA." }], "Check this field before reading the tagged facts:");
    return;
  }
  clearFieldErrors();
  stopWatching();
  const seq = ++state.viewSeq;
  state.runId = null;
  state.run = null;
  state.thesisId = null;
  markRecent();
  history.replaceState(null, "", `${location.pathname}${location.search}`);
  hideRunView();
  els.loading.textContent = `Reading the tagged facts in the latest ${form} of ${ticker.toUpperCase()}…`;
  els.loading.hidden = false;
  els.breakdowns.disabled = true;
  try {
    const report = await api(`/api/companies/${encodeURIComponent(ticker.toUpperCase())}/breakdowns?form=${encodeURIComponent(form)}`);
    if (seq !== state.viewSeq) return;
    renderBreakdowns(report, "");
    focusResults();
  } catch (error) {
    if (seq !== state.viewSeq) return;
    els.loading.hidden = true;
    if (error.status === 422 && error.details.length) {
      // The server names the form choice "form"; on this page it is the "breakdowns_form" select.
      const details = error.details.map((d) => ({ ...d, field: rootField(d.field) === "form" ? "breakdowns_form" : d.field }));
      showProblems(details, "The server refused the request:");
    } else {
      // 503: EDGAR could not list or deliver the filing; the server says which.
      showLoadError(`The tagged facts could not be read: ${error.message}.`, onBreakdowns);
    }
  } finally {
    els.breakdowns.disabled = state.sample;
  }
}

/** The key that places a value in its column: the period's start and end dates, as the record gives them. */
function periodKey(item) {
  return `${str(item?.period_start)}|${str(item?.period_end)}`;
}

/** Draw a BreakdownReport as the server wrote it: message first, notes, the facts read, then one table per breakdown. */
function renderBreakdowns(report, sampleNote) {
  if (!report || typeof report !== "object" || !Array.isArray(report.breakdowns) || !report.filing) {
    showLoadError("The tagged facts could not be shown: the record names no filing or breakdowns.", null);
    return;
  }
  renderCommandBar(null);
  els.loading.hidden = true;
  els.loadError.hidden = true;
  els.empty.hidden = true;
  els.runView.hidden = true;
  els.figuresView.hidden = true;
  els.thesisView.hidden = true;
  els.inboxView.hidden = true;
  els.ledgerView.hidden = true;
  els.changesView.hidden = true;
  els.breakdownsView.hidden = false;
  document.body.classList.add("has-run");

  const company = report.company ?? {};
  const filing = report.filing;
  els.breakdownsHead.replaceChildren(
    h(
      "div",
      { class: "run-head-main" },
      state.sample ? h("span", { class: "page-tag inline", text: "Sample record" }) : "",
      companyTitle(company),
      h("p", { class: "run-meta", text: "The company's latest filing of the form chosen, read when asked for the segments, products, geographies and customers it tags. Not tied to any run: no run was started and no claim was tested." }),
      sampleNote ? h("p", { class: "run-meta", text: `Sample: ${sampleNote}` }) : "",
    ),
  );

  const parts = [
    h(
      "p",
      { class: "changes-lead bd-lead" },
      "These are the numbers that ",
      filingLink(filing),
      " tags for the periods shown, split by segment, product, geography or customer.",
    ),
    h(
      "p",
      { class: "changes-explain bd-not" },
      ruleMark(),
      " What this is not: the row labels are derived from tag names and are not the company's own, and nothing here was checked against the filing's printed tables by a person.",
    ),
  ];
  const notes = list(report.notes);
  if (notes.length) {
    const notesList = h("ul", { class: "mark-list", id: "breakdowns-notes" });
    fillList(notesList, notes, "", true);
    parts.push(notesList);
  }
  parts.push(
    h(
      "p",
      { class: "bd-facts" },
      h("span", { "data-bd-field": "facts_read", text: num(report.facts_read) }),
      ` tagged ${unit(report.facts_read, "fact", "facts")} read, `,
      h("span", { "data-bd-field": "facts_unparsed", text: num(report.facts_unparsed) }),
      " could not be read.",
    ),
  );
  const breakdowns = list(report.breakdowns);
  if (breakdowns.length === 0) parts.push(h("p", { class: "muted", text: "This filing tags no breakdown this tool reads." }));
  breakdowns.forEach((breakdown) => parts.push(breakdownBlock(breakdown)));
  els.breakdownsBody.replaceChildren(...parts);
}

/** One breakdown: its title, concept and axis in small print, the table with the unit once, whether it adds up, its notes. */
function breakdownBlock(breakdown) {
  const id = str(breakdown.id);
  const periods = list(breakdown.periods);
  const total = list(breakdown.total);
  const row = (header, values, attrs) => {
    const byPeriod = new Map(list(values).map((value) => [periodKey(value), value]));
    return h("tr", attrs, header, periods.map((period) => breakdownCell(byPeriod.get(periodKey(period)), period)));
  };
  const table = h(
    "table",
    { class: "bd-table", "aria-label": str(breakdown.title) },
    h(
      "thead",
      null,
      h(
        "tr",
        null,
        h("th", { scope: "col", class: "bd-unit", text: str(breakdown.unit_label) || "Unit not recorded" }),
        periods.map((period) => h("th", { scope: "col", class: "bd-period", "data-period": periodKey(period), text: str(period.label) || str(period.period_end) })),
      ),
    ),
    h("tbody", null, list(breakdown.rows).map((r) => row(h("th", { scope: "row", class: "bd-label", text: str(r.label) || str(r.member) }), r.values, { "data-member": str(r.member) }))),
    total.length ? h("tfoot", null, row(h("th", { scope: "row", class: "bd-label", text: "Total, as tagged" }), total, { class: "bd-total" })) : "",
  );
  return h(
    "section",
    { class: "block bd-block", "data-breakdown-id": id, "aria-labelledby": `bd-title-${id}` },
    h("h3", { class: "block-title bd-title", id: `bd-title-${id}`, text: str(breakdown.title) }),
    h(
      "p",
      { class: "bd-meta" },
      "Tag ",
      h("code", { text: str(breakdown.concept) }),
      " along ",
      h("code", { text: str(breakdown.axis) }),
      str(breakdown.period_kind) ? ` · ${breakdown.period_kind}` : "",
    ),
    h("div", { class: "bd-scroll" }, table),
    addsUpLine(breakdown.adds_up),
    list(breakdown.notes).length ? h("ul", { class: "bd-notes" }, breakdown.notes.map((note) => h("li", { text: String(note) }))) : "",
  );
}

/** One cell: the record's `display`, and its `change_display` opening onto `change_formula`; empty when nothing is tagged. */
function breakdownCell(value, period) {
  const key = periodKey(period);
  if (!value) return h("td", { class: "bd-cell bd-empty", "data-period": key }, h("span", { class: "visually-hidden", text: "No value tagged" }));
  const formula = str(value.change_formula);
  const change = str(value.change_display);
  let changePart = "";
  if (formula) {
    changePart = h(
      "details",
      { class: "bd-change" },
      h("summary", null, change ? h("span", { class: `bd-change-display${signClass(change)}`, text: change }) : h("span", { class: "bd-no-change" }, h("span", { "aria-hidden": "true", text: "—" }), h("span", { class: "visually-hidden", text: "no change stated; open to read why" }))),
      h("span", { class: "bd-formula", text: formula }),
    );
  } else if (change) {
    changePart = h("span", { class: `bd-change-display${signClass(change)}`, text: change });
  }
  return h("td", { class: "bd-cell", "data-period": key }, h("span", { class: `bd-display${signClass(str(value.display))}`, text: str(value.display) }), changePart);
}

/** " num-neg" for a display string the record writes with a leading minus sign; "" otherwise. Reads the sign, computes nothing. */
function signClass(display) {
  return /^\s*[-−(]/.test(str(display)) ? " num-neg" : "";
}

/** Whether the rows add up to the tagged total: yes, no (a limit) or not checked, each drawn differently. */
function addsUpLine(addsUp) {
  if (addsUp === true) {
    return h("p", { class: "bd-adds bd-adds-yes", "data-adds-up": "yes" }, h("span", { class: "glyph g-adds", "aria-hidden": "true", text: "=" }), " Adds up: the rows add up to the tagged total in every period checked.");
  }
  if (addsUp === false) {
    return h("p", { class: "bd-adds bd-adds-no", "data-adds-up": "no" }, limitGlyph(), " Does not add up: in at least one period the rows do not add up to the tagged total. Read the filing's own table.");
  }
  return h("p", { class: "bd-adds bd-adds-unchecked", "data-adds-up": "unchecked" }, "Not checked: nothing here could be checked against a tagged total; the notes below say why.");
}

// ---------------------------------------------------------------- recent runs

async function refreshRecent() {
  if (state.sample) return;
  const seq = ++state.recentSeq;
  try {
    const payload = await api("/api/runs");
    if (seq !== state.recentSeq) return;
    renderRecent(list(payload.runs));
  } catch (error) {
    if (seq !== state.recentSeq) return;
    els.recent.replaceChildren(h("li", { class: "muted", text: `Recent runs could not be loaded: ${error.message}.` }));
  }
}

function renderRecent(runs) {
  els.recent.replaceChildren();
  if (runs.length === 0) {
    els.recent.append(h("li", { class: "muted", text: "No runs yet." }));
    return;
  }
  for (const run of runs) {
    const status = token(run.status, STATUS_GLYPH);
    const button = h(
      "button",
      {
        type: "button",
        class: "recent-item",
        "data-run": run.id,
        "aria-current": run.id === state.runId ? "true" : null,
        onclick: () => watchRun(run.id),
      },
      h("span", { class: "recent-name" }, h("strong", { text: run.ticker ?? "" }), run.company ? ` · ${run.company}` : ""),
      h(
        "span",
        { class: "recent-meta" },
        h("span", { class: `status-word st-${status}` }, statusMark(run.status), ` ${capitalize(run.status)}`),
        ` · ${plural(run.claims, "claim", "claims")} · started ${utc(run.started_at)}`,
      ),
    );
    els.recent.append(h("li", null, button));
  }
}

function markRecent() {
  for (const button of els.recent.querySelectorAll(".recent-item")) {
    if (button.dataset.run === state.runId) button.setAttribute("aria-current", "true");
    else button.removeAttribute("aria-current");
  }
  for (const button of els.theses.querySelectorAll(".recent-item")) {
    if (button.dataset.thesis === state.thesisId) button.setAttribute("aria-current", "true");
    else button.removeAttribute("aria-current");
  }
}

// ---------------------------------------------------------------- saved theses

/** Load the saved theses. A 404 means the server has no theses route: the feature stays hidden. */
async function refreshTheses() {
  if (state.sample) return;
  const seq = ++state.thesesSeq;
  try {
    const payload = await api("/api/theses");
    if (seq !== state.thesesSeq) return;
    const theses = list(payload.theses);
    state.theses = new Map(theses.map((t) => [t.id, t]));
    els.thesesBlock.hidden = false;
    els.saveThesis.hidden = false;
    renderTheses(theses);
    if (state.run?.thesis_id && !els.runView.hidden) renderHead(state.run);
  } catch (error) {
    if (seq !== state.thesesSeq) return;
    if (error.status === 404) {
      els.thesesBlock.hidden = true;
      els.saveThesis.hidden = true;
      els.savePanel.hidden = true;
      return;
    }
    els.thesesBlock.hidden = false;
    els.theses.replaceChildren(h("li", { class: "muted", text: `Saved theses could not be loaded: ${error.message}.` }));
  }
}

function renderTheses(theses) {
  els.theses.replaceChildren();
  if (theses.length === 0) {
    els.theses.append(h("li", { class: "muted", text: 'None yet. Fill in the form and choose "Save this thesis".' }));
    return;
  }
  for (const thesis of theses) {
    const last = thesis.last_status
      ? [" · last run ", h("span", { class: `status-word st-${token(thesis.last_status, STATUS_GLYPH)}` }, statusMark(thesis.last_status), ` ${capitalize(thesis.last_status)}`)]
      : " · not run yet";
    const button = h(
      "button",
      {
        type: "button",
        class: "recent-item",
        "data-thesis": thesis.id,
        "aria-current": thesis.id === state.thesisId ? "true" : null,
        onclick: () => openThesis(thesis.id),
      },
      h("span", { class: "recent-name" }, h("strong", { text: str(thesis.name) }), str(thesis.ticker) ? ` · ${thesis.ticker}` : ""),
      h("span", { class: "recent-meta" }, `${plural(thesis.claims, "claim", "claims")} · ${plural(thesis.runs, "run", "runs")}`, last),
      watchTag(thesis.watch),
    );
    els.theses.append(h("li", null, button));
  }
}

/** On a saved thesis in the list: on watch, its policy, and its unread items, as GET /api/theses gives them with the thesis. */
function watchTag(watch) {
  if (!watch) return "";
  return h(
    "span",
    { class: "watch-tag", "data-watch-tag": str(watch.policy) },
    h("span", { class: "glyph", "aria-hidden": "true", text: "◉" }),
    ` On watch · ${str(watch.policy_label)}`,
    Number.isFinite(watch.unread) && watch.unread > 0 ? ` · ${num(watch.unread)} unread` : "",
  );
}

function toggleSavePanel(open) {
  els.savePanel.hidden = !open;
  els.saveThesis.setAttribute("aria-expanded", String(open));
  if (open) els.thesisName.focus();
  else setFieldError("thesis_name", []);
}

/** Save the form's request under a name. The server validates both; its 422 is shown by field. */
async function onSaveThesis() {
  if (state.sample || !state.meta) return;
  const request = readForm();
  const limits = state.meta.limits;
  const problems = validate(request, limits);
  const name = els.thesisName.value.split(/\s+/).filter(Boolean).join(" ");
  if (!name) problems.push({ field: "thesis_name", message: "Give the thesis a name." });
  else if (Number.isInteger(limits.MAX_THESIS_NAME_CHARS) && name.length > limits.MAX_THESIS_NAME_CHARS) {
    problems.push({ field: "thesis_name", message: `At most ${limits.MAX_THESIS_NAME_CHARS} characters; it has ${name.length}.` });
  }
  if (problems.length) {
    showProblems(problems, "Check these fields before the thesis can be saved:");
    return;
  }
  clearFieldErrors();
  els.saveConfirm.disabled = true;
  try {
    const thesis = await api("/api/theses", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name, request }),
    });
    if (typeof thesis.id !== "string" || !thesis.id) throw new ApiError("the server did not return a thesis id", 0);
    toggleSavePanel(false);
    els.thesisName.value = "";
    els.formNote.textContent = `Saved as "${str(thesis.name) || name}". Run it from the thesis page.`;
    els.formNote.hidden = false;
    refreshTheses();
    openThesis(thesis.id);
  } catch (error) {
    if (error.status === 422 && error.details.length) {
      const details = error.details.map((d) => ({ ...d, field: rootField(d.field) === "name" ? "thesis_name" : d.field }));
      showProblems(details, "The server refused to save the thesis:");
    } else if (error.status === 404) {
      toggleSavePanel(false);
      els.saveThesis.hidden = true;
    } else {
      showFormMessage(`The thesis could not be saved: ${error.message}.`);
    }
  } finally {
    els.saveConfirm.disabled = false;
  }
}

/** Show one saved thesis: its request, its runs, and what moved between its last two runs. */
async function openThesis(thesisId) {
  stopWatching();
  const seq = ++state.viewSeq;
  state.runId = null;
  state.run = null;
  state.thesisId = thesisId;
  markRecent();
  history.replaceState(null, "", `#thesis=${encodeURIComponent(thesisId)}`);
  hideRunView();
  els.loading.textContent = "Loading the saved thesis…";
  els.loading.hidden = false;
  try {
    const payload = await api(`/api/theses/${encodeURIComponent(thesisId)}`);
    if (seq !== state.viewSeq) return;
    if (payload.thesis?.id !== thesisId) throw new ApiError("the server returned a different thesis than the one requested", 0);
    renderThesis(payload.thesis, list(payload.runs));
    loadThesisChanges(thesisId, seq);
    focusResults();
  } catch (error) {
    if (seq !== state.viewSeq) return;
    const reason = error.status === 404 ? "no saved thesis with that id exists" : error.message;
    showLoadError(`The saved thesis could not be loaded: ${reason}.`, () => openThesis(thesisId));
  }
}

function renderThesis(thesis, runs) {
  renderCommandBar(null);
  els.loading.hidden = true;
  els.loadError.hidden = true;
  els.empty.hidden = true;
  els.runView.hidden = true;
  els.figuresView.hidden = true;
  els.changesView.hidden = true;
  els.breakdownsView.hidden = true;
  els.ledgerView.hidden = true;
  els.thesisView.hidden = false;
  document.body.classList.add("has-run");
  const request = thesis.request ?? {};
  const claims = list(request.claims);
  els.thesisHead.replaceChildren(
    h(
      "div",
      { class: "run-head-main" },
      h("p", { class: "company-name" }, str(thesis.name)),
      h("p", { class: "company-line company" }, h("span", { class: "label", text: "Saved thesis" }), str(request.ticker) ? h("strong", { class: "ticker-chip", text: str(request.ticker) }) : ""),
      h("p", { class: "decision" }, h("span", { class: "label", text: "Decision: " }), str(request.decision)),
      h("p", { class: "run-meta", text: `${str(request.ticker)} · ${plural(claims.length, "claim", "claims")} · ${plural(request.filings, "filing", "filings")} per run · saved ${utc(thesis.created_at)}` }),
      h("ol", { class: "thesis-claims" }, claims.map((claim) => h("li", { text: String(claim) }))),
    ),
  );
  renderThesisWatch(thesis.id);
  els.runAgain.textContent = runs.length ? "Run again on the latest filings" : "Run it on the latest filings";
  els.runAgain.disabled = false;
  els.runAgainMessage.hidden = true;
  els.thesisRuns.replaceChildren();
  if (runs.length === 0) els.thesisRuns.append(h("li", { class: "muted", text: "No run yet." }));
  for (const run of runs) {
    const status = token(run.status, STATUS_GLYPH);
    els.thesisRuns.append(
      h(
        "li",
        null,
        h(
          "button",
          { type: "button", class: "recent-item", "data-run": run.id, onclick: () => watchRun(run.id) },
          h("span", { class: "recent-name", text: `Run ${run.id}` }),
          h(
            "span",
            { class: "recent-meta" },
            h("span", { class: `status-word st-${status}` }, statusMark(run.status), ` ${capitalize(run.status)}`),
            ` · started ${utc(run.started_at)}`,
            run.finished_at ? ` · finished ${utc(run.finished_at)}` : "",
          ),
        ),
      ),
    );
  }
  els.thesisChangesSection.hidden = false;
  els.thesisChanges.replaceChildren(h("p", { class: "muted", text: "Loading what moved…" }));
}

/**
 * What moved between the thesis's last two finished runs. A 409 (fewer than two)
 * is guidance, not an error; a 404 (no such route) hides the section.
 */
async function loadThesisChanges(thesisId, seq) {
  try {
    const comparison = await api(`/api/theses/${encodeURIComponent(thesisId)}/changes`);
    if (seq !== state.viewSeq) return;
    renderComparison(els.thesisChanges, comparison, null);
  } catch (error) {
    if (seq !== state.viewSeq) return;
    if (error.status === 404) els.thesisChangesSection.hidden = true;
    else if (error.status === 409) els.thesisChanges.replaceChildren(h("p", { class: "guidance", text: error.message }));
    else els.thesisChanges.replaceChildren(h("p", { class: "muted", text: `What moved could not be loaded: ${error.message}.` }));
  }
}

async function onRunAgain() {
  const thesisId = state.thesisId;
  if (state.sample || !thesisId) return;
  els.runAgain.disabled = true;
  els.runAgainMessage.hidden = true;
  try {
    const started = await api(`/api/theses/${encodeURIComponent(thesisId)}/runs`, { method: "POST" });
    if (typeof started.id !== "string" || !started.id) throw new ApiError("the server did not return a run id", 0);
    watchRun(started.id);
    refreshRecent();
    refreshTheses();
  } catch (error) {
    if (state.thesisId !== thesisId) return;
    els.runAgainMessage.textContent = `The run could not be started: ${error.message}.`;
    els.runAgainMessage.hidden = false;
    els.runAgain.disabled = false;
  }
}

// ---------------------------------------------------------------- what moved

/** A run id: a link to that run when it can be opened here, else plain text. */
function runRef(runId, currentRunId) {
  if (state.sample || !runId || runId === currentRunId) {
    return h("span", null, h("code", { text: runId || "—" }), runId && runId === currentRunId ? " (this run)" : "");
  }
  return h("a", { href: `#run=${encodeURIComponent(runId)}`, onclick: (event) => { event.preventDefault(); watchRun(runId); }, text: runId });
}

/** One side of a comparison row: the verdict, and the verdict after review when there is one. */
function comparisonVerdict(verdict, reviewed, side, missingText) {
  const cell = h("td", { class: `cmp-${side}`, "data-verdict": verdict ?? "none" });
  cell.append(verdict ? verdictPill(verdict) : h("span", { class: "muted", text: missingText }));
  if (reviewed) {
    cell.append(h("span", { class: "cmp-reviewed", "data-reviewed-verdict": reviewed }, h("span", { class: "slot-label", text: "After your review" }), verdictPill(reviewed)));
  }
  return cell;
}

/** Draw a RunComparison exactly as the server computed it. */
function renderComparison(container, comparison, currentRunId) {
  const claims = list(comparison.claims);
  container.replaceChildren();
  // A RunComparison has `note` and counts; an inbox item's `moved` has `comparison_note` and no counts.
  const note = str(comparison.note) || str(comparison.comparison_note);
  if (note) container.append(h("p", { class: "changes-note", text: note }));
  const counted = Number.isFinite(comparison.verdicts_moved) && Number.isFinite(comparison.claims_total);
  container.append(
    h(
      "p",
      { class: "changes-runs" },
      counted
        ? [
            h("span", { class: "count-value", "data-cmp": "verdicts_moved", text: num(comparison.verdicts_moved) }),
            " of ",
            h("span", { class: "count-value", "data-cmp": "claims_total", text: num(comparison.claims_total) }),
            ` ${unit(comparison.claims_total, "verdict", "verdicts")} moved. `,
          ]
        : "",
      "Earlier run ",
      comparison.earlier_run_id ? runRef(comparison.earlier_run_id, currentRunId) : "none (the thesis's first run)",
      comparison.earlier_finished_at ? `, finished ${utc(comparison.earlier_finished_at)}` : "",
      "; later run ",
      runRef(comparison.later_run_id, currentRunId),
      comparison.later_finished_at ? `, finished ${utc(comparison.later_finished_at)}` : "",
      ".",
    ),
  );
  const rows = claims.map((change, index) => {
    // A claim with no earlier verdict was not in the earlier run: "moved" or "unchanged" would not apply.
    const newClaim = change.before === null || change.before === undefined;
    const word = newClaim ? "new in the later run" : change.moved ? "moved" : "unchanged";
    return h(
      "tr",
      { "data-change": index, class: change.moved ? "is-moved" : null },
      h("th", { scope: "row", class: "cmp-claim", text: str(change.claim) }),
      comparisonVerdict(change.before, change.reviewed_before, "before", "not in the earlier run"),
      comparisonVerdict(change.after, change.reviewed_after, "after", "not in the later run"),
      h("td", { class: "cmp-move" }, h("span", { class: `move-word ${newClaim ? "is-new" : change.moved ? "is-moved" : "is-same"}`, text: word })),
      h(
        "td",
        { class: "cmp-excerpts" },
        h("span", { class: "cmp-count" }, h("span", { "data-cmp-field": "excerpts_added", text: num(change.excerpts_added) }), ` ${unit(change.excerpts_added, "excerpt", "excerpts")} added`),
        h("span", { class: "cmp-count" }, h("span", { "data-cmp-field": "excerpts_dropped", text: num(change.excerpts_dropped) }), ` ${unit(change.excerpts_dropped, "excerpt", "excerpts")} dropped`),
      ),
    );
  });
  container.append(
    h(
      "div",
      { class: "table-wrap", tabindex: "0", role: "region", "aria-label": "Verdicts by claim, earlier run and later run" },
      h(
        "table",
        { class: "changes" },
        h("thead", null, h("tr", null, ["Claim", "Earlier run", "Later run", "Change", "Excerpts"].map((t) => h("th", { scope: "col", text: t })))),
        h("tbody", null, rows.length ? rows : h("tr", null, h("td", { colspan: "5", class: "muted", text: "The comparison lists no claims." }))),
      ),
    ),
  );
  const filings = (title, titles, cls) =>
    h(
      "div",
      { class: `changes-filings ${cls}` },
      h("p", { class: "label", text: title }),
      list(titles).length ? h("ul", { class: "plain-list" }, list(titles).map((t) => h("li", { text: String(t) }))) : h("p", { class: "muted", text: "None." }),
    );
  container.append(
    h(
      "div",
      { class: "changes-filings-wrap" },
      filings("New filings in the later run", comparison.sources_added, "added"),
      Array.isArray(comparison.sources_dropped) ? filings("Filings the later run no longer read", comparison.sources_dropped, "dropped") : "",
    ),
  );
}

/** In the run view: what moved, when the comparison's later run is this run. */
function renderRunChanges(run) {
  // The thesis's latest comparison, else the comparison of the inbox item that opened this run.
  const fromItem = state.itemComparison?.later_run_id === run.id ? state.itemComparison : null;
  const comparison = state.comparison?.later_run_id === run.id ? state.comparison : fromItem;
  const show = Boolean(comparison) && comparison.later_run_id === run.id;
  els.changesSection.hidden = !show;
  if (show) renderComparison(els.changes, comparison, run.id);
  else els.changes.replaceChildren();
}

/** For a finished run that belongs to a thesis, fetch what moved; any failure hides the section quietly. */
async function loadRunChanges(run, seq) {
  if (!run.thesis_id || run.status === "running") return;
  try {
    const comparison = await api(`/api/theses/${encodeURIComponent(run.thesis_id)}/changes`);
    if (seq !== state.viewSeq) return;
    state.comparison = comparison;
    renderRunChanges(run);
  } catch {
    // 404 (no route), 409 (fewer than two finished runs) or unreachable: the thesis page says why.
  }
}

// ---------------------------------------------------------------- review

/** The Review on file for this run, or null. */
function currentReview(run) {
  return state.review && run && state.review.run_id === run.id ? state.review : null;
}

/** Fetch the reader's decisions for a finished run. A 404 hides review quietly. */
async function loadReview(runId, seq) {
  try {
    const review = await api(`/api/runs/${encodeURIComponent(runId)}/review`);
    if (seq !== state.viewSeq) return;
    if (review.run_id !== runId) throw new ApiError("the server returned the review of a different run", 0);
    applyReview(review, null);
  } catch (error) {
    if (seq !== state.viewSeq || error.status === 404) return;
    els.reviewLine.replaceChildren(h("p", { class: "muted", text: `Your review could not be loaded: ${error.message}.` }));
    els.reviewLine.hidden = false;
  }
}

/** Show a Review from the server everywhere it appears. `force` names a finding whose note is reset to the server's. */
function applyReview(review, force) {
  state.review = review;
  const run = state.run;
  if (!run || !review || review.run_id !== run.id) return;
  renderReviewLine(run);
  renderScorecard(run);
  renderVerdictViews(run);
  renderReviewSlots(run, force);
  applySelection();
}

function renderReviewLine(run) {
  const review = currentReview(run);
  els.reviewLine.hidden = !review;
  if (!review) {
    els.reviewLine.replaceChildren();
    return;
  }
  const count = h(
    "p",
    { class: "review-count" },
    "You have decided ",
    h("span", { class: "count-value", "data-review-field": "decided", text: num(review.decided) }),
    " of ",
    h("span", { class: "count-value", "data-review-field": "findings_total", text: num(review.findings_total) }),
    ` ${unit(review.findings_total, "finding", "findings")}.`,
    state.sample ? h("span", { class: "page-tag inline-tag", text: "sample: decisions are not saved" }) : "",
  );
  const parts = [count];
  if (str(state.meta?.review_note)) parts.push(h("p", { class: "review-note", text: state.meta.review_note }));
  if (review.complete) {
    parts.push(
      state.sample
        ? h("p", { class: "muted small", text: "The reviewed brief is not available for the sample record." })
        : h("p", null, h("a", { class: "download", href: briefHref(run.id, true), download: `evidence-desk-${run.id}-reviewed.md`, text: "Download reviewed brief" })),
    );
  }
  els.reviewLine.replaceChildren(...parts);
}

/** The "After your review" cell of a scorecard row, from the Review's claim entry. */
function reviewedSlot(entry) {
  const verdict = entry?.reviewed_verdict ?? null;
  const slot = h("span", { class: "verdict-slot slot-reviewed", "data-reviewed-verdict": verdict ?? "none" }, h("span", { class: "slot-label", text: "After your review" }));
  if (!verdict) {
    slot.append(h("span", { class: "pill review-pending", text: "not reviewed yet" }));
    return slot;
  }
  slot.append(
    verdictPill(verdict),
    h(
      "span",
      { class: "review-tally" },
      h("span", { "data-review-field": "accepted", text: num(entry.accepted) }),
      " accepted · ",
      h("span", { "data-review-field": "rejected", text: num(entry.rejected) }),
      " rejected",
    ),
  );
  if (Number.isFinite(entry.undecided) && entry.undecided > 0) {
    slot.append(h("span", { class: "undecided" }, h("span", { "data-review-field": "undecided", text: num(entry.undecided) }), " undecided"));
  }
  return slot;
}

/** Fill the review controls under each verified finding from the Review. */
function renderReviewSlots(run, force) {
  const review = currentReview(run);
  const decisions = new Map(list(review?.decisions).map((d) => [d.finding_id, d]));
  for (const slot of els.claimList.querySelectorAll("[data-review-finding]")) {
    if (!review) {
      slot.replaceChildren();
      slot.hidden = true;
      continue;
    }
    if (!slot.firstChild) buildReviewSlot(slot);
    slot.hidden = false;
    const id = slot.dataset.reviewFinding;
    updateReviewSlot(slot, decisions.get(id) ?? null, force === id);
  }
}

function buildReviewSlot(slot) {
  const findingId = slot.dataset.reviewFinding;
  const maxNote = state.meta?.limits?.MAX_NOTE_CHARS;
  const button = (value, text) =>
    h("button", {
      type: "button",
      class: "secondary small decide",
      "data-value": value,
      "aria-pressed": "false",
      text,
      onclick: () => {
        const current = slot.dataset.value || null;
        sendDecision(slot, current === value ? null : value);
      },
    });
  const note = h("input", {
    type: "text",
    class: "decision-note",
    maxlength: Number.isInteger(maxNote) ? maxNote : null,
    placeholder: "Optional note, saved with your decision",
    "aria-label": `Your note on finding ${findingId}`,
    onkeydown: (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        if (slot.dataset.value) sendDecision(slot, slot.dataset.value);
      }
    },
  });
  slot.append(
    h("p", { class: "decision-status" }, h("span", { class: "label", text: "Your decision: " }), h("span", { class: "decision-now" })),
    h(
      "div",
      { class: "decision-controls" },
      button("accepted", "Accept"),
      button("rejected", "Reject"),
      note,
      h("button", { type: "button", class: "secondary small save-note", text: "Save note", onclick: () => slot.dataset.value && sendDecision(slot, slot.dataset.value) }),
      state.sample ? h("span", { class: "page-tag", text: "sample: decisions are not saved" }) : "",
    ),
    h("p", { class: "review-message", role: "status", hidden: true }),
  );
}

/** Show the server's decision on one finding. The note is replaced only if untouched, or when forced. */
function updateReviewSlot(slot, decision, force) {
  const value = decision?.value === "accepted" || decision?.value === "rejected" ? decision.value : "";
  slot.dataset.value = value;
  slot.querySelector(".decision-now").replaceChildren(
    decisionMark(value || "undecided"),
    decision?.decided_at ? h("span", { class: "muted", text: ` · ${utc(decision.decided_at)}` }) : "",
  );
  for (const btn of slot.querySelectorAll(".decide")) {
    const pressed = btn.dataset.value === value;
    btn.setAttribute("aria-pressed", String(pressed));
    btn.title = pressed ? "Press again to clear your decision" : "";
  }
  const note = slot.querySelector(".decision-note");
  const saved = str(decision?.note);
  const dirty = note.value !== note.defaultValue;
  note.defaultValue = saved;
  if (force || !dirty) note.value = saved;
  setSlotBusy(slot, slot.dataset.busy === "1");
}

function setSlotBusy(slot, busy) {
  slot.dataset.busy = busy ? "1" : "";
  const locked = busy || state.sample;
  for (const btn of slot.querySelectorAll(".decide")) btn.disabled = locked;
  slot.querySelector(".decision-note").disabled = locked;
  slot.querySelector(".save-note").disabled = locked || !slot.dataset.value;
}

/** PUT one decision; show the Review the server returns, or its message and its last state. */
async function sendDecision(slot, value) {
  const run = state.run;
  if (state.sample || !run || slot.dataset.busy === "1") return;
  const findingId = slot.dataset.reviewFinding;
  const note = slot.querySelector(".decision-note").value.trim();
  const message = slot.querySelector(".review-message");
  const seq = state.viewSeq;
  message.hidden = true;
  message.className = "review-message";
  setSlotBusy(slot, true);
  try {
    const review = await api(`/api/runs/${encodeURIComponent(run.id)}/findings/${encodeURIComponent(findingId)}/decision`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ value, note }),
    });
    if (seq !== state.viewSeq) return;
    if (review.run_id !== run.id) throw new ApiError("the server returned the review of a different run", 0);
    setSlotBusy(slot, false);
    applyReview(review, findingId);
  } catch (error) {
    if (seq !== state.viewSeq) return;
    setSlotBusy(slot, false);
    applyReview(state.review, findingId); // back to what the server last said
    if (error.status === 422) {
      const lines = error.details.length ? error.details.map((d) => String(d.message)).join(" ") : error.message;
      message.replaceChildren(rejectGlyph(), ` Not saved: ${lines}`);
      message.className = "review-message reject";
    } else {
      message.textContent = `Not saved: ${error.message}.`;
    }
    message.hidden = false;
  }
}

// ---------------------------------------------------------------- run loading

function stopWatching() {
  if (state.timer) clearTimeout(state.timer);
  state.timer = null;
  if (state.controller) state.controller.abort();
  state.controller = null;
}

/** Show one run and poll it while it runs. A newer selection cancels this one. */
function watchRun(runId) {
  stopWatching();
  const seq = ++state.viewSeq;
  const controller = new AbortController();
  state.controller = controller;
  state.runId = runId;
  state.thesisId = null;
  state.run = null;
  state.review = null;
  state.comparison = null;
  state.bannerKey = "";
  history.replaceState(null, "", `#run=${encodeURIComponent(runId)}`);
  markRecent();
  hideRunView();
  els.loading.textContent = `Loading run ${runId}…`;
  els.loading.hidden = false;

  const tick = async () => {
    try {
      const run = await api(`/api/runs/${encodeURIComponent(runId)}`, { signal: controller.signal });
      if (seq !== state.viewSeq) return;
      if (run.id !== runId) throw new ApiError("the server returned a different run than the one requested", 0);
      renderRun(run);
      if (run.status === "running") {
        state.timer = setTimeout(tick, POLL_MS);
      } else {
        refreshRecent();
        loadReview(run.id, seq);
        if (run.thesis_id) {
          refreshTheses();
          loadRunChanges(run, seq);
        }
      }
    } catch (error) {
      if (seq !== state.viewSeq || error.name === "AbortError") return;
      const reason = error.status === 404 ? "no run with that id exists" : error.message;
      showLoadError(`Run ${runId} could not be loaded: ${reason}. The results shown before were cleared so they cannot be mistaken for this run.`, () => watchRun(runId));
    }
  };
  tick();
}

function hideRunView() {
  els.runView.hidden = true;
  els.figuresView.hidden = true;
  els.changesView.hidden = true;
  els.breakdownsView.hidden = true;
  els.thesisView.hidden = true;
  els.inboxView.hidden = true;
  els.ledgerView.hidden = true;
  els.loadError.hidden = true;
  els.empty.hidden = true;
  document.body.classList.remove("has-run");
  els.inboxButton?.setAttribute("aria-expanded", "false");
  renderCommandBar(null);
  state.timelineRun = null;
  state.totRun = null;
  state.run = null;
  state.ctx = null;
  state.picked = null;
  if (els.runInfo) els.runInfo.hidden = true;
  document.body.classList.remove("as-of-run");
}

function showLoadError(message, retry) {
  hideRunView();
  els.loading.hidden = true;
  state.bannerKey = "";
  showAlert(els.loadError, message, retry ? "Try again" : null, retry);
}

function showAlert(container, message, actionText, action) {
  container.replaceChildren(h("p", { text: message }));
  if (actionText && action) {
    container.append(h("button", { type: "button", class: "secondary small", onclick: action, text: actionText }));
  }
  container.hidden = false;
}

/** `?sample` loads /sample-run.json; `?sample=<name>` loads /sample-<name>.json. */
async function loadSample(name) {
  state.sampleName = name;
  els.sampleTag.hidden = false;
  els.formNote.textContent = "Sample mode: this page shows a stored record and does not start runs. Open the page without ?sample to test a thesis.";
  els.formNote.hidden = false;
  els.recent.replaceChildren(h("li", { class: "muted", text: "Recent runs are not loaded in sample mode." }));
  els.thesesBlock.hidden = false;
  els.theses.replaceChildren(h("li", { class: "muted", text: "Saved theses are not loaded in sample mode." }));
  els.saveThesis.hidden = false;
  // The way out of sample mode sits in the command bar; the sample links are not offered inside one.
  $("sample-link").hidden = true;
  if (els.leaveSample) {
    els.leaveSample.href = location.pathname;
    els.leaveSample.hidden = false;
  }
  $("synthetic-link").hidden = true;
  $("changes-link").hidden = true;
  $("breakdowns-link").hidden = true;
  $("tagged-link").hidden = true;
  $("events-link").hidden = true;
  $("inbox-link").hidden = true;
  for (const id of ["live-link", "costco-link", "shapes-link", "computed-link", "readers-link", "as-of-link", "ledger-link"]) if ($(id)) $(id).hidden = true;
  hideRunView();
  if (!SAMPLE_NAME.test(name)) {
    showLoadError("That sample name is not valid: use lower-case letters, digits and hyphens.", null);
    return;
  }
  try {
    if (Object.hasOwn(INBOX_SAMPLES, name)) {
      await loadInboxSample(name);
      return;
    }
    const payload = await api(`sample-${name}.json`, { cache: "no-store" });
    // A bare run, copied unedited from a run's record: its note is the page's, its wording /api/meta's.
    if (!payload.run && typeof payload.id === "string" && Array.isArray(payload.claims)) {
      const note = BARE_SAMPLE_NOTES[name];
      if (!note) throw new ApiError("the file is a bare run that this page has no note for", 0);
      applyMeta(await api("/api/meta"), { sample: true });
      state.sampleNote = note;
      els.formNote.textContent = `Sample mode: ${note} This page does not start runs; open it without ?sample to test a thesis.`;
      state.runId = payload.id;
      state.review = null;
      state.comparison = null;
      renderRun(payload);
      return;
    }
    // A bare restatement ledger: no run, no /api/meta; its note is the page's.
    if (Array.isArray(payload.entries) && Object.hasOwn(payload, "periods_checked")) {
      const note = LEDGER_SAMPLE_NOTES[name];
      if (!note) throw new ApiError("the file is a restatement ledger that this page has no note for", 0);
      els.formNote.textContent = `Sample mode: ${note} This page does not look anything up; open it without ?sample to read a company's ledger.`;
      renderLedgerView(payload, note);
      return;
    }
    // A recorded filing comparison ({note, changes}) has no run and needs no wording from /api/meta.
    if (payload.changes && !payload.run) {
      if (str(payload.note)) els.formNote.textContent = `Sample mode: ${payload.note} This page does not look anything up; open it without ?sample to compare a company's filings.`;
      renderChanges(payload.changes, str(payload.note));
      return;
    }
    // A recorded reading of one filing's tagged facts ({note, report}): no run, no /api/meta.
    if (payload.report && !payload.run) {
      if (str(payload.note)) els.formNote.textContent = `Sample mode: ${payload.note} This page does not look anything up; open it without ?sample to read a company's tagged facts.`;
      renderBreakdowns(payload.report, str(payload.note));
      return;
    }
    if (!payload.meta || !payload.run) throw new ApiError("the file has no meta or run", 0);
    applyMeta(payload.meta, { sample: true });
    foldEngineLine(payload.run.engine_detail);
    if (str(payload.note)) els.formNote.textContent = `Sample mode: ${payload.note} This page does not start runs; open it without ?sample to test a thesis.`;
    state.sampleNote = str(payload.note);
    state.runId = payload.run.id;
    // Sample mode only: the reader's decisions and the comparison are stored in the file.
    const review = payload.review;
    state.review = review && typeof review === "object" && review.run_id === payload.run.id ? review : null;
    const comparison = payload.comparison;
    state.comparison = comparison && typeof comparison === "object" ? comparison : null;
    renderRun(payload.run);
  } catch (error) {
    showLoadError(`The sample record could not be loaded: ${error.message}.`, null);
  }
}

// ---------------------------------------------------------------- run rendering

function renderRun(run) {
  const claims = list(run.claims);
  const ctx = {
    run,
    sources: new Map(list(run.sources).map((x) => [x.id, x])),
    evidence: new Map(list(run.evidence).map((x) => [x.id, x])),
    findings: new Map([...list(run.findings), ...list(run.unsupported_findings)].map((x) => [x.id, x])),
    claims: new Map(claims.map((x) => [x.id, x])),
    metrics: new Map(list(run.metrics).map((x) => [x.id, x])),
  };
  indexAnalysis(ctx, run);

  els.loading.hidden = true;
  els.loadError.hidden = true;
  els.empty.hidden = true;
  els.figuresView.hidden = true;
  els.changesView.hidden = true;
  els.breakdownsView.hidden = true;
  els.thesisView.hidden = true;
  els.inboxView.hidden = true;
  els.ledgerView.hidden = true;
  els.runView.hidden = false;
  document.body.classList.add("has-run");
  // Another run starts on the whole thesis, its first tab, and nothing picked; a redraw of the same run keeps them.
  if (state.run?.id !== run.id) {
    state.selected = "";
    state.tab = "";
    state.picked = null;
    readSelectionFromAddress(run);
  }
  state.run = run;
  state.ctx = ctx;
  if (els.runInfo) els.runInfo.hidden = false;

  renderAsOfBanner(run);
  renderCommandBar(run);
  renderBanner(run);
  renderStages(run);
  renderRailHead(run);
  renderHead(run);
  renderTape(run);
  renderTimeline(run);
  renderThesisOverTime(run);
  renderReviewLine(run);
  renderScorecard(run);
  renderVerdictViews(run);
  renderDistinction(run);
  renderRunChanges(run);
  renderSummary(run);
  renderEvents(run);
  renderRunFigures(run);
  renderAnalysis(run);
  renderMethod(run);
  renderClaims(run, ctx);
  // A link to a claim's computed test (#claim-<id>-test) opens it once, when the run is first drawn.
  if (state.testHashRun !== run.id && /^#claim-.+-test$/.test(location.hash)) {
    state.testHashRun = run.id;
    openClaimChangesFromHash();
  }
  renderClaimChanges(run);
  renderReviewSlots(run, null);
  renderWithheld(run, ctx);
  renderBriefLists(run);
  renderSources(run);
  const finished = run.status !== "running";
  fillList(els.limits, run.coverage_limits, finished ? "None recorded." : "Listed when the run finishes.", true);
  renderErrors(run, finished);
  // The run's own note (it names any page the user added); a record without one uses /api/meta's.
  els.provenance.textContent = str(run.brief?.provenance_note) || str(state.meta?.provenance_note);
  applySelection();
}

/** Status, its note from /api/meta, and the coverage counts exactly as the API gives them. */
function renderBanner(run) {
  const status = token(run.status, STATUS_GLYPH);
  const c = run.coverage ?? {};
  const key = JSON.stringify([run.id, run.status, run.stage, run.stage_detail, c, state.sample]);
  if (key === state.bannerKey) return; // unchanged: do not re-announce to screen readers
  state.bannerKey = key;
  els.banner.className = `banner st-${status}`;

  const head = h(
    "p",
    { class: "banner-head" },
    state.sample ? h("span", { class: "page-tag inline", text: "Sample record" }) : "",
    statusMark(run.status),
    h("strong", { text: ` ${capitalize(run.status)}` }),
    h("span", { class: "banner-note", text: ` ${state.meta?.status_notes?.[run.status] ?? ""}` }),
  );
  const parts = [head];
  if (run.status === "running") {
    const stage = STAGES.find(([id]) => id === run.stage);
    parts.push(h("p", { class: "banner-line", text: `Now: ${stage ? stage[1] : run.stage}${run.stage_detail ? ` — ${run.stage_detail}` : ""}` }));
  } else {
    // Counts kept since a review found the banner claimed more than the record backed. A record
    // from before them lacks them (or, read back through the API, holds 0): it renders as before.
    // `quotes_found` counts every quote located word for word; a record holding 0 for it while
    // it kept excerpts predates the field, so the excerpts count stands in, as it used to.
    const asked = Number.isFinite(c.filings_asked) && c.filings_asked > 0 && c.filings_asked !== c.sources_requested;
    const foundField = Number.isFinite(c.quotes_found) && (c.quotes_found > 0 || !(c.excerpts_verified > 0)) ? "quotes_found" : "excerpts_verified";
    const positive = (field) => Number.isFinite(c[field]) && c[field] > 0;
    const facts = [
      h(
        "li",
        null,
        cov(c, "sources_read"),
        " of ",
        cov(c, "sources_requested"),
        ` ${unit(c.sources_requested, "source", "sources")} read`,
        asked ? [" (", cov(c, "filings_asked"), ` ${unit(c.filings_asked, "filing", "filings")} asked for)`] : "",
      ),
      h("li", null, cov(c, "passages_indexed"), ` ${unit(c.passages_indexed, "passage", "passages")} indexed`),
      h("li", null, cov(c, "claims_with_evidence"), " of ", cov(c, "claims_total"), ` ${unit(c.claims_total, "claim", "claims")} with verified excerpts or figures`),
    ];
    const hasProposed = Number.isFinite(c.findings_proposed) && (c.findings_proposed > 0 || list(run.findings).length === 0);
    facts.push(
      hasProposed
        ? h("li", null, cov(c, "findings_verified"), " of ", cov(c, "findings_proposed"), ` proposed ${unit(c.findings_proposed, "finding", "findings")} verified, `, cov(c, "findings_withheld"), " withheld")
        : h("li", null, cov(c, "findings_verified"), ` ${unit(c.findings_verified, "finding", "findings")} verified, `, cov(c, "findings_withheld"), " withheld"),
    );
    if (positive("findings_without_quote")) {
      facts.push(h("li", null, cov(c, "findings_without_quote"), ` verified ${unit(c.findings_without_quote, "finding rests", "findings rest")} on reported figures only, with no quote`));
    }
    facts.push(
      h(
        "li",
        null,
        cov(c, foundField),
        " of ",
        cov(c, "quotes_offered"),
        ` ${unit(c.quotes_offered, "quote", "quotes")} offered found word for word, `,
        cov(c, "quotes_rejected"),
        " did not pass the check",
        foundField === "quotes_found" ? ["; ", cov(c, "excerpts_verified"), " kept as evidence of verified findings"] : "",
      ),
    );
    if (Number.isFinite(c.metrics_computed)) {
      facts.push(h("li", null, cov(c, "metrics_computed"), ` reported ${unit(c.metrics_computed, "figure", "figures")} computed`));
    }
    if (Number.isFinite(c.figures_offered)) {
      // Two counts, never added up here: the record keeps them apart.
      const tagged = Number.isFinite(c.tagged_figures_offered) && (c.tagged_figures_offered > 0 || run.inputs?.tagged_figures === true);
      facts.push(
        h(
          "li",
          { "data-figures-offered": "" },
          cov(c, "figures_offered"),
          ` reported ${unit(c.figures_offered, "figure", "figures")}`,
          tagged ? [" and ", cov(c, "tagged_figures_offered"), ` tagged ${unit(c.tagged_figures_offered, "figure", "figures")}`] : "",
          " offered to the engine",
          Number.isFinite(c.figures_cited) ? ["; ", cov(c, "figures_cited"), ` ${unit(c.figures_cited, "citation", "citations")} of them in verified findings`] : "",
        ),
      );
    }
    if (Number.isFinite(c.numbers_checked)) {
      facts.push(h("li", null, cov(c, "numbers_checked"), ` ${unit(c.numbers_checked, "number", "numbers")} in findings checked, `, cov(c, "numbers_unmatched"), " unmatched"));
    }
    if (Number.isFinite(c.periods_checked)) {
      // The period check reports; it withholds nothing. Its three counts, as the record gives them.
      facts.push(
        h(
          "li",
          { "data-periods-line": "" },
          cov(c, "periods_checked"),
          ` ${unit(c.periods_checked, "year", "years")} named in verified findings checked against their evidence, `,
          cov(c, "periods_unverified"),
          " not found",
          Number.isFinite(c.periods_unverified) && c.periods_unverified > 0 && Number.isFinite(c.periods_comparative)
            ? [" (", cov(c, "periods_comparative"), ` of them ${unit(c.periods_comparative, "a comparison year", "comparison years")})`]
            : "",
        ),
      );
    }
    if (Number.isFinite(c.claims_compiled)) {
      // Version 14: the claims that compiled to a computed test and how the tests came out, as the record counts them.
      facts.push(
        h(
          "li",
          { "data-computed-line": "" },
          cov(c, "claims_compiled"),
          " of ",
          cov(c, "claims_total"),
          ` ${unit(c.claims_total, "claim", "claims")} compiled to a computed test`,
          c.claims_compiled > 0
            ? [
                ": ",
                h("span", { class: "ct-count o-holds" }, h("span", { class: "glyph", "aria-hidden": "true", text: "⊨ " }), "holds ", cov(c, "computed_holds")),
                ", ",
                h("span", { class: "ct-count o-fails" }, h("span", { class: "glyph", "aria-hidden": "true", text: "⊭ " }), "fails ", cov(c, "computed_fails")),
                ", ",
                h("span", { class: "ct-count o-cannot_compute" }, h("span", { class: "glyph", "aria-hidden": "true", text: "⊘ " }), "cannot be computed ", cov(c, "computed_cannot")),
              ]
            : "",
        ),
      );
    }
    if (positive("reasons_withheld")) {
      facts.push(h("li", null, cov(c, "reasons_withheld"), ` ${unit(c.reasons_withheld, "reason", "reasons")} withheld by the number check`));
    }
    if (Number.isFinite(c.findings_checked) && c.findings_checked > 0) {
      facts.push(
        h(
          "li",
          null,
          cov(c, "findings_checked"),
          ` ${unit(c.findings_checked, "finding", "findings")} checked for meaning, `,
          cov(c, "findings_partly"),
          " agreed only in part, ",
          cov(c, "findings_failed_meaning"),
          " withheld",
        ),
      );
    }
    parts.push(h("ul", { class: "coverage-facts", "aria-label": "Coverage" }, facts));
    if (Number.isFinite(c.engine_fallbacks) && c.engine_fallbacks > 0) {
      parts.push(
        limitLine(
          "p",
          "The model engine failed for ",
          cov(c, "engine_fallbacks"),
          ` of its ${unit(c.engine_fallbacks, "step", "steps")}; the deterministic engine answered ${unit(c.engine_fallbacks, "that step", "those")}.`,
        ),
      );
    }
    if (list(run.coverage_limits).length) {
      parts.push(h("p", { class: "banner-line" }, h("a", { href: "#coverage-limits", onclick: jumpTo("coverage-limits"), text: "Read the coverage limits" })));
    }
    // One line under the head, the full counts one click away: every count stays in the record's words.
    const wasOpen = els.banner.querySelector("details.banner-fold")?.open ?? false;
    const sep = () => h("span", { class: "banner-sep", "aria-hidden": "true", text: " · " });
    const line = h(
      "summary",
      { class: "banner-summary" },
      h("span", { class: `status-word st-${status}` }, statusMark(run.status), ` ${capitalize(run.status)}`),
      sep(),
      h("span", null, cov(c, "sources_read"), " of ", cov(c, "sources_requested"), ` ${unit(c.sources_requested, "source", "sources")}`),
      sep(),
      hasProposed
        ? h("span", null, cov(c, "findings_verified"), " of ", cov(c, "findings_proposed"), ` ${unit(c.findings_proposed, "finding", "findings")} verified`)
        : h("span", null, cov(c, "findings_verified"), ` ${unit(c.findings_verified, "finding", "findings")} verified`),
      sep(),
      h("span", null, cov(c, "findings_withheld"), " withheld"),
      list(run.coverage_limits).length ? [sep(), h("span", { class: "banner-limits" }, limitGlyph(), " limits")] : "",
      h("span", { class: "banner-open", text: "all counts" }),
    );
    els.banner.replaceChildren(h("details", { class: "banner-fold", open: wasOpen }, line, h("div", { class: "banner-full" }, ...parts)));
    return;
  }
  els.banner.replaceChildren(...parts);
}

/** A click handler that brings a part of the run into view: its claim and tab first, then its place in the pane. */
function jumpTo(id) {
  return (event) => {
    event.preventDefault();
    const target = $(id);
    if (!target) return;
    closeRunDrawer(false);
    reveal(target);
    // An item that can be read at the side (an 8-K a finding predates) is read there too.
    const item = workspaceOn() && inspectorOn() ? parsePick(target.dataset.pick) : null;
    if (item) pick(item);
    target.focus({ preventScroll: true });
  };
}

function renderStages(run) {
  const running = run.status === "running";
  els.stagesWrap.hidden = !running;
  if (!running) return;
  const current = STAGES.findIndex(([id]) => id === run.stage);
  els.stages.replaceChildren(
    ...STAGES.map(([, label], index) => {
      const phase = current < 0 || index > current ? "todo" : index < current ? "done" : "now";
      return h(
        "li",
        { class: `stage ${phase}`, "aria-current": phase === "now" ? "step" : null },
        label,
        phase === "done" ? h("span", { class: "visually-hidden", text: " (finished)" }) : "",
      );
    }),
  );
}

/**
 * The note's title: the company's name large, then its ticker and CIK, as the record names
 * them. Used by every view that is about one company.
 */
function companyTitle(company, fallbackTicker = "") {
  const ticker = str(company?.ticker) || fallbackTicker;
  return [
    h("p", { class: "company-name", text: str(company?.name) || ticker || "Company" }),
    h(
      "p",
      { class: "company-line company" },
      ticker ? h("strong", { class: "ticker-chip", text: ticker }) : "",
      Number.isFinite(company?.cik) ? h("span", null, h("abbr", { title: "The SEC's numeric identifier for this company", text: "CIK" }), ` ${company.cik}`) : "",
    ),
  ];
}

/** Where a sample record came from, in the head of the view that shows it. */
function sampleNoteLine() {
  if (!state.sample || !state.sampleNote) return "";
  // Its first sentence in view; the whole note one click away (the same note, not a shorter one).
  const note = state.sampleNote;
  const cut = note.indexOf(". ");
  const first = cut > 0 ? note.slice(0, cut + 1) : note;
  return h(
    "div",
    { class: "sample-note", "data-sample-note": "" },
    cut > 0
      ? h("details", { class: "prov-more" }, h("summary", null, h("span", { class: "label", text: "Sample: " }), first), h("p", { class: "prov-full", text: note }))
      : h("p", null, h("span", { class: "label", text: "Sample: " }), note),
  );
}

/**
 * The command bar's two chips for the run on screen: its status, which opens the Run drawer
 * (who did the work: the engine, the checker, the readers, the run's id and times), and its
 * as-of line, each the record's own words. Hidden for any other view.
 */
function renderCommandBar(run) {
  if (!els.cmdRun) return;
  if (!run) {
    if (els.statusbarRun) els.statusbarRun.textContent = "";
    els.cmdRun.hidden = true;
    els.cmdStatus.replaceChildren();
    els.cmdVerdicts?.replaceChildren();
    els.cmdAsof.replaceChildren();
    els.cmdAsof.removeAttribute("title");
    return;
  }
  const status = token(run.status, STATUS_GLYPH);
  els.cmdRun.hidden = false;
  els.cmdStatus.replaceChildren(h("span", { class: `status-word st-${status}` }, statusMark(run.status), ` ${capitalize(run.status)}`));
  if (els.statusbarRun) els.statusbarRun.textContent = `${str(run.id)} · ${str(run.status)}`;
  // A chip, not a sentence: the date and form of the newest filing read, from the record's as-of
  // block. The record's whole line is the chip's title and opens the 8-Ks, where it is written out.
  const asOf = run.as_of ?? {};
  const line = str(asOf.line);
  const requested = str(asOf.requested);
  const newest = str(asOf.newest_filed);
  els.cmdAsof.onclick = jumpTo("events-section");
  if (line) els.cmdAsof.title = `${line} Select for the 8-Ks since the annual report.`;
  else els.cmdAsof.removeAttribute("title");
  els.cmdAsof.replaceChildren();
  appendAll(els.cmdAsof, [
    requested ? h("strong", { class: "cmd-asof-past", "data-cmd-as-of-requested": requested, text: `Run as of ${dateLabel(requested)}` }) : "",
    line
      ? h(
          "span",
          { class: "cmd-asof-line", "data-cmd-as-of": line },
          h("span", { class: "cmd-key", text: requested ? "evidence to " : "As of " }),
          newest ? `${dateLabel(newest)}${str(asOf.newest_form) ? ` (${asOf.newest_form})` : ""}` : line,
          h("span", { class: "visually-hidden", text: `. ${line}` }),
        )
      : h("span", { class: "muted cmd-asof-line", text: "As of: not recorded" }),
  ]);
  if (els.statusbarRun && requested) els.statusbarRun.textContent = `${str(run.id)} · ${str(run.status)} · as of ${requested}`;
}

/** The rail's head: the company and the decision the thesis informs, the question the claims below answer. */
function renderRailHead(run) {
  if (!els.railHead) return;
  const inputs = run.inputs ?? {};
  els.railHead.replaceChildren(
    ...companyTitle(run.company, str(inputs.ticker)),
    h("p", { class: "decision" }, h("span", { class: "label", text: "Decision: " }), inputs.decision ?? ""),
  );
  appendAll(els.railHead, [verdictStrip(run)]);
}

/**
 * How the run was made, in the Run drawer: the engine that read the filings, who checked
 * meaning, who read the claims into tests and the counting rule, the run's id and times, how old
 * the evidence is, the saved thesis it belongs to and a sample's provenance.
 */
function renderHead(run) {
  const inputs = run.inputs ?? {};
  const engine = str(run.engine);
  const engineLine = h(
    "p",
    { class: "run-engine" },
    h("span", { class: "label", text: "Engine that did the work: " }),
    h("span", { class: "engine-used", text: engine || "not recorded" }),
    str(run.engine_detail) ? h("span", { class: "engine-detail" }, " — ", provenanceDetail(run.engine_detail)) : "",
  );
  const checkerLine = runMeaningChecked(run)
    ? h("p", { class: "run-engine run-checker" }, h("span", { class: "label", text: "Meaning checked by: " }), h("span", { class: "checker-used" }, provenanceDetail(str(run.checker_detail) || str(run.checker))))
    : h("p", { class: "run-engine run-checker" }, h("span", { class: "label", text: "Meaning not checked" }));
  // Version 14: who read each claim's test ("grammar", or "grammar and model" with the model parser on).
  const readersLine = str(run.claim_readers)
    ? h(
        "p",
        { class: "run-engine run-readers", "data-claim-readers": run.claim_readers },
        h("span", { class: "label", text: "Claims read into tests by: " }),
        run.claim_readers,
        str(run.claim_reader_detail) ? h("span", { class: "engine-detail" }, " — ", provenanceDetail(run.claim_reader_detail)) : "",
        str(run.claim_reading_rule) ? h("span", { class: "run-rule", "data-claim-reading-rule": "", text: ` ${run.claim_reading_rule}` }) : "",
      )
    : "";
  renderHowtoRule(run);
  const details = h(
    "p",
    { class: "run-meta" },
    `Run ${run.id} · started ${utc(run.started_at)}`,
    run.finished_at ? ` · finished ${utc(run.finished_at)}` : "",
    ` · ${plural(inputs.filings, "filing", "filings")} requested`,
  );
  els.runHead.replaceChildren(
    h(
      "div",
      { class: "run-head-main" },
      h("div", { class: "run-provenance" }, engineLine, checkerLine, readersLine, details, asOfLine(run)),
      thesisLine(run),
      sampleNoteLine(),
    ),
  );
}

/** The Markdown brief of the run, or why there is none yet; shown in the centre pane's head for the whole thesis. */
function briefActions(run) {
  let download;
  if (state.sample) {
    download = h("span", { class: "muted small", text: "The Markdown brief is not available for the sample record." });
  } else if (run.status === "running") {
    download = h("span", { class: "muted small", text: "The Markdown brief can be downloaded when the run finishes." });
  } else {
    download = h("a", { class: "download", href: briefHref(run.id, false), download: `evidence-desk-${run.id}.md`, text: "Download Markdown brief" });
  }
  return h("span", { class: "run-head-actions" }, download, run.status !== "running" && !state.sample ? h("span", { class: "muted", text: "Print this page for a paper copy of the note." }) : "");
}

/** "How to read this" names the counting rule of the run on show, in the record's words (`claim_reading_rule`). */
function renderHowtoRule(run) {
  const slot = $("howto-reading-rule");
  if (!slot) return;
  const rule = str(run?.claim_reading_rule);
  slot.hidden = !rule;
  slot.replaceChildren(rule ? h("span", null, h("strong", { text: "This run's rule: " }), rule) : "");
}

/**
 * How old the evidence is, as the record's as-of block words it, with a way to the 8-Ks.
 * Nothing for a run recorded before version 12, which has no as-of block.
 */
function asOfLine(run) {
  const line = str(run.as_of?.line);
  if (!line) return "";
  return h(
    "p",
    { class: "as-of", "data-as-of": "" },
    h("span", { class: "label", text: "As of: " }),
    line,
    " ",
    h("a", { href: "#events-section", onclick: jumpTo("events-section"), text: "See the 8-Ks since the annual report" }),
  );
}

/**
 * The Markdown brief of a run, with the changed paragraphs listed for each claim
 * (`changes=true`); `reviewed` adds the reader's decisions.
 */
function briefHref(runId, reviewed) {
  const query = new URLSearchParams();
  if (reviewed) query.set("reviewed", "true");
  query.set("changes", "true");
  return `/api/runs/${encodeURIComponent(runId)}/export.md?${query}`;
}

/** "Part of the saved thesis ..." with a way back, for a run started from a saved thesis. */
function thesisLine(run) {
  const thesisId = str(run.thesis_id);
  if (!thesisId) return "";
  const thesis = state.theses.get(thesisId);
  const name = thesis ? h("strong", { text: `"${str(thesis.name)}"` }) : h("code", { text: thesisId });
  let back;
  if (state.sample) {
    back = state.comparison?.later_run_id === run.id ? h("a", { href: "#changes-section", onclick: jumpTo("changes-section"), text: "See what moved since its earlier run" }) : "";
  } else {
    back = h("a", { href: `#thesis=${encodeURIComponent(thesisId)}`, onclick: (event) => { event.preventDefault(); openThesis(thesisId); }, text: "Open the thesis" });
  }
  return h("p", { class: "run-thesis" }, "Part of the saved thesis ", name, ". ", back);
}

/** Who assessed a claim, in words. */
function assessedText(claim) {
  const by = str(claim.assessed_by);
  if (!by) return "";
  return by === EXTRACTIVE ? "Assessed by: extractive (no model)" : `Assessed by: ${by} (a model)`;
}

/** A claim's verdict stamp, or with a review both stamps: the engine's, then the one after the reader's review. */
function claimStamps(claim, review) {
  if (!review) return verdictPill(claim.verdict);
  const entry = list(review.claims).find((item) => item.claim_id === claim.id);
  return h(
    "span",
    { class: "score-verdicts" },
    h("span", { class: "verdict-slot slot-engine" }, h("span", { class: "slot-label", text: "Engine" }), verdictPill(claim.verdict)),
    reviewedSlot(entry),
  );
}

/** The flags a claim carries beside its verdict: a caution, or a note on the 8-Ks. The record's own fields. */
function claimFlags(claim) {
  if (str(claim.caution)) return h("span", { class: "docket-flag score-flag", "data-flag": "caution" }, limitGlyph(), " Caution");
  if (str(claim.event_note)) return h("span", { class: "docket-flag score-flag", "data-flag": "event-note", title: "Note on the 8-Ks since the annual report", text: "8-K note" });
  return "";
}

/**
 * The rail: the claims, listed once. One row per claim: its id, its verdict (with a review, the
 * verdict after it too), the claim, the computed part of the verdict, then the counts the API
 * lists. Selecting a row shows that claim in the centre pane.
 */
function renderScorecard(run) {
  const claims = list(run.claims);
  const c = run.coverage ?? {};
  els.scorecard.replaceChildren();
  if (claims.length === 0) {
    els.scorecard.append(h("li", { class: "muted score-none", text: run.status === "running" ? "Claims appear once the run has planned them." : "This run recorded no claims." }));
    return;
  }
  const review = currentReview(run);
  // With a review each row holds two stamps, labelled; the head over them is for the eye only.
  if (els.boardHead) els.boardHead.hidden = true;
  els.scorecard.classList.toggle("has-review", Boolean(review));
  claims.forEach((claim, index) => {
    const passages = Number.isFinite(c.passages_indexed)
      ? [h("span", { "data-claim-field": "passages_considered", text: num(claim.passages_considered ?? 0) }), " of ", cov(c, "passages_indexed"), " passages considered"]
      : [h("span", { "data-claim-field": "passages_considered", text: num(claim.passages_considered ?? 0) }), " passages considered"];
    const row = h(
      "a",
      {
        class: review ? "score-row has-review" : "score-row",
        href: `#claim-${index}`,
        "data-select": claim.id,
        "aria-current": "false",
        title: claim.text,
        onclick: (event) => {
          event.preventDefault();
          select(claim.id);
        },
        onkeydown: (event) => {
          // Enter on the claim already selected goes on to what is shown for it.
          if (event.key !== "Enter" || state.selected !== claim.id) return;
          event.preventDefault();
          focusCentre();
        },
      },
      h("span", { class: "score-top" }, h("span", { class: "claim-id", text: claim.id }), claimStamps(claim, review), claimFlags(claim)),
      h("span", { class: "score-claim", text: claim.text }),
      // Who read the findings and what the computed test says, under the claim.
      h("span", { class: "score-sub" }, assessedText(claim) ? h("span", { class: "assessed", text: assessedText(claim) }) : "", boardComputed(claim)),
      h("span", { class: "score-counts" }, `${plural(list(claim.finding_ids).length, "finding", "findings")} · `, ...passages),
    );
    els.scorecard.append(h("li", { "data-claim-id": claim.id }, row));
  });
}

/** The note under the verdicts as index.html writes it: the wording for a run no second model read. */
const DISTINCTION_DEFAULT = els.distinction ? els.distinction.cloneNode(true) : null;

/** The note under the verdicts: what was checked, and by whom, for this run. */
function renderDistinction(run) {
  if (!els.distinction) return;
  // Version 14: a claim that compiled has a part of its verdict that no engine read.
  const computed = compiledClaims(run).length
    ? [
        " ",
        h("strong", { text: "Computed by code:" }),
        " a claim read into a test (marked ⊨ holds, ⊭ fails, ⊘ cannot be computed) is computed from the company's XBRL facts by code, and no model does the arithmetic. ",
        h(
          "span",
          { "data-distinction-readers": runModelReaders(run) ? "models" : "grammar" },
          runModelReaders(run)
            ? `The reading may be a model's: this run's claims were read into tests by ${str(run.claim_readers)}, and each test names who read it.`
            : "This run's claims were read into tests by the grammar alone, a fixed rule: no model read them.",
        ),
        " A test that holds counts as one piece of support, one that fails as a challenge, one that cannot be computed as nothing.",
      ]
    : [];
  if (!runMeaningChecked(run)) {
    els.distinction.replaceChildren(...DISTINCTION_DEFAULT.cloneNode(true).childNodes, ...computed);
    return;
  }
  els.distinction.replaceChildren(
    "Each verdict follows by a fixed rule from the findings that passed their checks. ",
    h("strong", { text: "Checked:" }),
    " every quote was found word for word in the stored filing, and numbers were matched to quotes and reported figures. ",
    h("strong", { text: "Read by a second model, not checked by a person:" }),
    " whether a quote supports or challenges the claim is the engine's reading of it; then a second model, which was not shown the first one's reasoning, read each finding's evidence and judged whether it supports the statement and its stance. That is still a model's reading, which your accept or reject is there to test. Read the quotes before you rely on a verdict.",
    ...computed,
  );
}

function renderSummary(run) {
  const brief = run.brief;
  els.summarySection.hidden = !brief;
  if (!brief) return;
  const origin = str(brief.summary_origin);
  const model = origin === MODEL_ORIGIN;
  els.summaryBox.className = model ? "mw is-model" : "mw";
  els.summaryOrigin.replaceChildren(
    model
      ? h("span", null, modelBadge(), " Check it against the verdicts and quotes below.")
      : h("span", { class: "origin-tag", text: `Written by: ${origin || "not stated"}${origin === "template" ? " (fixed wording filled in from the record)" : ""}` }),
  );
  els.summary.textContent = str(brief.summary);
  // Version 14.1: after a model's summary, a line written by code naming the verdicts the computed tests set or changed.
  // Outside the model's box, so the model's mark does not cover it.
  els.summarySection.querySelector("[data-verdicts-after-summary]")?.remove();
  const after = str(brief.verdicts_after_summary);
  if (after) {
    els.summaryBox.after(
      h("div", { class: "after-summary", "data-verdicts-after-summary": "" }, h("p", { class: "after-kicker" }, ruleMark("Written by code after the summary, not by the model")), h("p", { class: "after-text", text: after })),
    );
  }
}

/**
 * One docket per claim. Its body has two parts: why the verdict (the rule, who assessed, the
 * caution, the engine's commentary, the computed test), which the Overview tab shows, and the
 * findings with their quotes and the changed paragraphs, which the Evidence tab shows in full
 * and the Overview tab in short. On paper every docket prints whole, under its own heading.
 */
function renderClaims(run, ctx) {
  const open = new Set([...els.claimList.querySelectorAll("details[open]")].map((d) => d.id));
  els.claimList.replaceChildren();
  const readers = readerDetails(run);
  list(run.claims).forEach((claim, position) => {
    const id = `claim-${position}`;
    const model = modelAssessed(claim);
    const body = h("div", { class: "claim-part part-why", "data-part": "overview" });
    const evidencePart = h("div", { class: "claim-part part-findings", "data-part": "evidence" });
    const note = verdictNote(claim.verdict);
    if (note) body.append(h("p", { class: "verdict-note" }, h("span", { class: "label", text: "Verdict rule: " }), note));
    if (assessedText(claim)) body.append(h("p", { class: "assessed-line", text: assessedText(claim) }));
    if (str(claim.caution)) {
      body.append(h("div", { class: "claim-caution", "data-claim-caution": claim.id }, limitLine("p", h("strong", { text: "Caution: " }), claim.caution)));
    }
    if (str(claim.event_note)) {
      body.append(h("p", { class: "event-note", "data-claim-event-note": claim.id }, h("span", { class: "label", text: "8-Ks since the annual report: " }), claim.event_note));
    }
    if (claim.rationale) {
      body.append(
        writtenField(
          "div",
          `claim:${claim.id}:commentary`,
          model,
          [
            h("p", { class: "label", text: `Engine's commentary (${str(claim.assessed_by) || str(run.engine) || "engine"}), not a verified excerpt` }),
            h("p", { text: claim.rationale }),
          ],
        ),
      );
    }
    // Version 14: the computed part of the verdict, before the findings (the reading of the filings).
    if (claim.computed && typeof claim.computed === "object") body.append(computedTest(claim, run.company?.cik, readers));
    else if (str(claim.compile_note)) body.append(compileNote(claim, readers));
    const ids = list(claim.finding_ids);
    evidencePart.append(h("h4", { class: "block-title part-title", "data-code": "FND", text: "Findings" }));
    if (list(claim.queries).length) {
      evidencePart.append(h("p", { class: "queries" }, h("span", { class: "label", text: "Searched with: " }), claim.queries.join(" · ")));
    }
    if (ids.length === 0) {
      evidencePart.append(h("p", { class: "muted", text: run.status === "running" ? "Findings appear when this claim has been assessed." : "No verified finding is recorded for this claim." }));
    }
    ids.forEach((findingId) => {
      const finding = ctx.findings.get(findingId);
      if (!finding) evidencePart.append(h("p", { class: "muted", text: `Finding ${findingId} is listed but missing from the record.` }));
      else if (finding.verified === false) evidencePart.append(h("p", { class: "muted", text: `Finding ${findingId} was withheld; it is listed with the withheld findings, under the whole thesis's evidence.` }));
      else evidencePart.append(renderFinding(finding, ctx));
    });
    // Filled by drawClaimChanges once the finished run's changed paragraphs have loaded.
    evidencePart.append(h("div", { class: "cc-slot", "data-cc-slot": claim.id }));
    const details = h(
      "details",
      { class: "claim", id, open: open.has(id), "data-docket": claim.id },
      // The docket's own heading: on screen the centre pane's head says the same, so this prints only.
      h(
        "summary",
        null,
        verdictPill(claim.verdict),
        h("span", { class: "claim-id", text: claim.id }),
        h("span", { class: "claim-text", text: claim.text }),
        docketMeta(claim, run),
      ),
      h("div", { class: "claim-body" }, body, evidencePart),
    );
    els.claimList.append(details);
  });
}

/**
 * The line under a claim on its docket: how many findings the record lists for it and how many
 * passages it considered, then a flag for a caution or an 8-K note the claim carries.
 */
function docketMeta(claim, run) {
  const c = run.coverage ?? {};
  const parts = [
    plural(list(claim.finding_ids).length, "finding", "findings"),
    ` · ${num(claim.passages_considered ?? 0)}`,
    Number.isFinite(c.passages_indexed) ? ` of ${num(c.passages_indexed)}` : "",
    " passages considered",
  ];
  const test = claim.computed && typeof claim.computed === "object" ? claim.computed : null;
  if (test) {
    parts.push(" · ", h("span", { class: "docket-flag docket-computed", "data-docket-computed": token(test.outcome, TEST_MARK) }, h("span", { class: "glyph", "aria-hidden": "true", text: `${TEST_MARK[token(test.outcome, TEST_MARK)] ?? "·"} ` }), `Computed: ${str(test.outcome_label) || TEST_FALLBACK[test.outcome] || ""}`));
    if (readingsDiffer(claim)) parts.push(" · ", h("span", { class: "docket-flag" }, limitGlyph(), ` ${READINGS_DIFFER}`));
  }
  if (str(claim.caution)) parts.push(" · ", h("span", { class: "docket-flag" }, limitGlyph(), " Caution"));
  else if (str(claim.event_note)) parts.push(" · ", h("span", { class: "docket-flag", text: "Note on the 8-Ks since the annual report" }));
  return h("span", { class: "docket-meta" }, ...parts);
}

// ---------------------------------------------------------------- changed paragraphs, by claim

/** What was compared: the newest report of each form the run read, with the one filed before it. */
const CC_EARLIER = "The newest annual report and the newest quarterly report this run read are each compared with the filing of the same form filed before it. An older quarterly report this run read is not compared. The earlier filing of each pair was fetched for the comparison, and this run may not have read it.";

/** Why these paragraphs are listed, said wherever they are. */
const CC_WHY = "These paragraphs are listed because they share words with the claim or the search queries the run wrote for it: no model chose or judged them, they are not findings, and none counts toward the verdict.";

/**
 * For a finished run, which paragraphs changed in the filings it read (each against the filing
 * of its form before it) and share words with each claim: GET /api/runs/{id}/changes, once per
 * run, or the sample's recorded file. Nothing is shown, or asked for, while the run is running
 * or for a sample without such a file.
 */
function renderClaimChanges(run) {
  const wanted = run.status !== "running" && (!state.sample || Object.hasOwn(SAMPLE_RUN_CHANGES, state.sampleName));
  if (!wanted) {
    els.runFilingChanges.hidden = true;
    els.runFilingChanges.replaceChildren();
    return;
  }
  if (state.claimChanges?.runId === run.id) drawClaimChanges();
  else loadClaimChanges(run.id);
}

async function loadClaimChanges(runId) {
  state.claimChanges = { runId, status: "loading", record: null, error: "" };
  drawClaimChanges();
  let next;
  try {
    const url = state.sample ? SAMPLE_RUN_CHANGES[state.sampleName] : `/api/runs/${encodeURIComponent(runId)}/changes`;
    const payload = await api(url, { cache: "no-store" });
    const record = state.sample ? payload.changes : payload;
    if (!record || typeof record !== "object" || !Array.isArray(record.claims)) throw new ApiError("the record lists no claims", 0);
    if (str(record.run_id) !== runId) throw new ApiError("the record is for another run", 0);
    next = { runId, status: "ready", record, error: "" };
  } catch (error) {
    next = { runId, status: "failed", record: null, error: error.message };
  }
  if (state.claimChanges?.runId !== runId) return; // another run is on screen now
  state.claimChanges = next;
  drawClaimChanges();
}

/** Fill the block above the claims and each claim's slot from `state.claimChanges`. */
function drawClaimChanges() {
  const loaded = state.claimChanges;
  if (!loaded || state.run?.id !== loaded.runId) return;
  const top = els.runFilingChanges;
  const slots = [...els.claimList.querySelectorAll("[data-cc-slot]")];
  top.hidden = false;
  if (loaded.status !== "ready") {
    top.replaceChildren(
      loaded.status === "loading"
        ? h("p", { class: "muted", text: "Looking up which paragraphs changed in the filings since the ones before…" })
        : h(
            "p",
            { class: "cc-error", "data-cc-error": "" },
            limitGlyph(),
            ` The changed paragraphs could not be loaded: ${loaded.error}. The rest of the run is shown. `,
            h("button", { type: "button", class: "secondary small", onclick: () => loadClaimChanges(loaded.runId), text: "Try again" }),
          ),
    );
    slots.forEach((slot) => slot.replaceChildren());
    return;
  }
  const record = loaded.record;
  top.replaceChildren(comparedBlock(record));
  const byClaim = new Map(list(record.claims).map((entry) => [entry.claim_id, entry]));
  slots.forEach((slot) => slot.replaceChildren(claimChangesBlock(slot.dataset.ccSlot, byClaim.get(slot.dataset.ccSlot))));
  // The browser's own jump to #claim-<id>-changes happened before these nodes existed: do it now, once per load.
  if (!loaded.jumped) {
    loaded.jumped = true;
    openClaimChangesFromHash();
  }
}

/** The id of a claim's "Changed in the filings" block: the target of a link such as #claim-c4-changes. */
function claimChangesId(claimId) {
  return `claim-${claimId}-changes`;
}

/**
 * Open the claim and the block that `location.hash` names (#claim-<claim id>-changes) and
 * scroll it into view. A hash that names no block on screen does nothing.
 */
function openClaimChangesFromHash() {
  if (!/^#claim-.+-(changes|test)$/.test(location.hash)) return;
  let id;
  try {
    id = decodeURIComponent(location.hash.slice(1));
  } catch {
    return;
  }
  const target = document.getElementById(id);
  if (!target || !els.claimList.contains(target)) return;
  const claim = target.closest("details.claim");
  if (claim) claim.open = true;
  if (target.tagName === "DETAILS") {
    target.open = true;
    state.claimChangesOpen.add(target.dataset.claimChanges);
  }
  // Its claim and its tab first; then, after the next frame, its place in the pane (the layout must settle).
  reveal(target, { scroll: false });
  requestAnimationFrame(() => target.scrollIntoView({ block: "start" }));
}

/** Which filings were compared (form, both period ends, each a link) and the record's notes. */
function comparedBlock(record) {
  const compared = list(record.compared);
  const notes = h("ul", { class: "mark-list cc-notes" });
  fillList(notes, list(record.notes), "", true);
  return h(
    "div",
    { "data-cc-compared": "" },
    h("p", { class: "cc-title" }, h("strong", { text: "Changed since the previous annual and quarterly report" }), " ", ruleMark()),
    h("p", { class: "cc-earlier", text: CC_EARLIER }),
    compared.length
      ? h(
          "ul",
          { class: "cc-pairs" },
          compared.map((pair) =>
            h("li", { "data-form": str(pair.form) }, h("strong", { text: `${str(pair.form) || "Form not recorded"}: ` }), filingLink(pair.later), ", against ", filingLink(pair.earlier)),
          ),
        )
      : h("p", { class: "muted", text: "No pair of filings was compared." }),
    list(record.notes).length ? notes : "",
    h("p", { class: "cc-why", text: `Under each claim, after its findings. ${CC_WHY}` }),
  );
}

/** One claim's changed paragraphs: collapsed, its counts as the record states them, then each entry, best first. */
function claimChangesBlock(claimId, entry) {
  if (!entry) {
    return h("p", { class: "cc-none", id: claimChangesId(claimId), "data-claim-changes": claimId }, ruleMark(), " No list of changed paragraphs was recorded for this claim.");
  }
  const changes = list(entry.changes);
  const field = (name, value) => h("span", { "data-cc-field": name, text: num(value) });
  if (changes.length === 0) {
    return h(
      "p",
      { class: "cc-none", id: claimChangesId(claimId), "data-claim-changes": claimId },
      ruleMark(),
      " Changed since the previous annual and quarterly report: no paragraph shares at least two words with this claim or the search queries the run wrote for it, among ",
      field("considered", entry.considered),
      ` changed ${unit(entry.considered, "paragraph", "paragraphs")} searched.`,
    );
  }
  return h(
    "details",
    {
      class: "claim-changes",
      id: claimChangesId(claimId),
      "data-claim-changes": claimId,
      open: state.claimChangesOpen.has(claimId),
      ontoggle: (event) => {
        if (event.currentTarget.open) state.claimChangesOpen.add(claimId);
        else state.claimChangesOpen.delete(claimId);
      },
    },
    h(
      "summary",
      null,
      h("span", { class: "cc-summary-text" }, `Changed since the previous annual and quarterly report: ${plural(changes.length, "paragraph", "paragraphs")} that share words with this claim or the search queries the run wrote for it`),
      " ",
      ruleMark(),
    ),
    h(
      "div",
      { class: "cc-body" },
      h(
        "p",
        { class: "cc-counts" },
        field("listed", changes.length),
        " listed of ",
        field("distinct_matched", entry.distinct_matched),
        ` distinct ${unit(entry.distinct_matched, "change", "changes")} that share at least two words with this claim or the search queries the run wrote for it, among `,
        field("considered", entry.considered),
        ` changed ${unit(entry.considered, "paragraph", "paragraphs")}.`,
      ),
      h("p", { class: "cc-why", text: `${CC_EARLIER} ${CC_WHY}` }),
      h("ol", { class: "chg-paras cc-list" }, changes.map(changeEntry)),
    ),
  );
}

/** One listed change: its mark, form and Item (and the other Items it repeats under), the shared words, the text and links. */
function changeEntry(change) {
  const kind = Object.hasOwn(CHANGE_MARK, change?.kind) ? change.kind : "";
  const also = list(change?.also_under).map(String);
  const terms = list(change?.matched_terms).map(String);
  const head = h(
    "div",
    { class: "cc-head" },
    h(
      "p",
      { class: "cc-where" },
      kind ? changeMark(kind) : h("span", { class: "muted", text: "Kind not recorded" }),
      " ",
      h("span", { class: "cc-form", text: str(change?.form) || "form not recorded" }),
      " · ",
      h("span", { class: "cc-item", text: str(change?.item) || "Item not recorded" }),
      also.length ? h("span", { class: "cc-also", "data-also-under": also.join("\n") }, ` · also under ${also.join("; ")}`) : "",
    ),
    h(
      "p",
      { class: "cc-terms" },
      h("span", { class: "label", text: "Shared words, as the matcher stems them: " }),
      terms.flatMap((term, position) => [position ? ", " : "", h("span", { class: "cc-term", text: term })]),
    ),
  );
  let entry;
  if ((kind === "added" || kind === "removed") && change.paragraph) entry = paragraphEntry(change.paragraph, kind === "added" ? "later" : "earlier", head);
  else if ((kind === "reworded" || kind === "numbers_only") && change.pair) entry = pairEntry(change.pair, kind === "reworded", head);
  else entry = h("li", null, head, h("p", { class: "muted", text: "The changed text is missing from the record." }));
  entry.classList.add("cc-entry");
  entry.dataset.changeKind = kind || "unknown";
  return entry;
}

/** One finding: stance, statement, the engine's reason, its checks, cited figures and quotes. */
function renderFinding(finding, ctx, withheld = false) {
  const stance = token(finding.stance, STANCE_MARK);
  const model = modelAssessed(ctx.claims.get(finding.claim_id));
  const badge = meaningRead(finding) ? MODEL_BADGE_READ : MODEL_BADGE;
  // The finding in the main column; its quotes in the margin beside it (inline on a narrow note).
  const main = h("div", { class: "finding-main" });
  const margin = h("div", { class: "finding-margin" });
  const pickable = list(finding.evidence_ids).length > 0 || list(finding.metric_ids).length > 0;
  const article = h("article", { class: `finding s-${stance}${withheld ? " is-withheld" : ""}`, "data-finding-id": finding.id, "data-pick": pickable ? `finding:${finding.id}` : null }, main, margin);
  main.append(
    h(
      "header",
      { class: "finding-head" },
      stancePill(finding.stance),
      !withheld && finding.verified !== false && list(finding.evidence_ids).length === 0 && list(finding.metric_ids).length > 0
        ? h("span", { class: "figures-only-tag", "data-figures-only": "" }, "rests on reported figures only: no excerpt")
        : "",
      writtenField("div", `finding:${finding.id}:statement`, model, h("h4", { class: "finding-statement", text: finding.statement }), badge),
    ),
    h(
      "p",
      { class: "finding-meta" },
      h("span", { class: "muted", text: `${finding.id} · ` }),
      h("span", { title: "The engine's own qualitative estimate, not a measured probability", text: `Engine's confidence: ${finding.confidence}` }),
      ` · ${plural(finding.filings_cited, "filing", "filings")} cited`,
    ),
  );
  const counted = countedAsLine(finding);
  if (counted) main.append(counted);
  for (const mark of list(finding.predated_by)) main.append(predatedLine(mark));
  if (withheld) {
    // A finding the second model rejected keeps that model's own words, tagged for the browser test.
    const reason = str(finding.withheld_reason) || "no quote was found in the filing text.";
    const byMeaning = str(finding.checks?.support) === "failed";
    main.append(limitLine("p", h("strong", { text: "Withheld: " }), byMeaning ? h("span", { "data-withheld-reason": "", text: reason }) : reason));
  }
  if (finding.rationale) {
    main.append(writtenField("p", `finding:${finding.id}:reason`, model, [h("span", { class: "label", text: "Engine's reason: " }), finding.rationale], badge));
  }
  const checks = renderChecks(finding.checks);
  if (checks) main.append(checks);
  const cited = renderCitedFigures(finding.metric_ids, ctx.metrics);
  if (cited) main.append(cited);
  for (const evidenceId of list(finding.evidence_ids)) {
    const item = ctx.evidence.get(evidenceId);
    if (!item) {
      margin.append(h("p", { class: "muted", text: `Excerpt ${evidenceId} is listed but missing from the record.` }));
      continue;
    }
    margin.append(renderEvidence(item, ctx.sources.get(item.source_id)));
  }
  if (!withheld && finding.verified !== false) {
    main.append(h("div", { class: "review-slot", "data-review-finding": finding.id, hidden: true }));
  }
  // After the quotes: the way to read them in the text around them (or, with no quote, the figures cited).
  if (pickable) article.append(pickButton(list(finding.evidence_ids).length ? "Read the quote in its context" : "Read the figures it cites"));
  return article;
}

/** "Predates the 8-K of 12 Nov 2026, Item 5.02", the record's words, linking to that 8-K above. */
function predatedLine(mark) {
  const target = eventAnchor(str(mark.event_id));
  const label = str(mark.label) || "Predates a later 8-K";
  return limitLine(
    "p",
    h("span", { class: "predated", "data-predated-by": str(mark.event_id) }, target ? h("a", { href: `#${target}`, onclick: jumpTo(target), text: label }) : label),
  );
}

/**
 * When the verdict rule counted a finding as another stance than the engine's (`counted_as`,
 * set by the backend), that stance's mark and the record's reason. Nothing for a finding
 * counted as its own stance, a withheld one, or a record from before `counted_as` was kept.
 */
function countedAsLine(finding) {
  const counted = str(finding.counted_as);
  if (!counted || counted === str(finding.stance)) return null;
  return h(
    "p",
    { class: "counted-as", "data-counted-as": counted },
    h("span", { class: "label", text: "Counted toward the verdict as: " }),
    stancePill(counted),
    str(finding.count_note) ? h("span", { class: "count-note", "data-count-note": "", text: finding.count_note }) : "",
  );
}

/** The checks a finding went through, as the record states them. A check that did not run says so. */
function renderChecks(checks) {
  if (!checks || typeof checks !== "object") return null;
  const items = [];
  const quotes = str(checks.quotes);
  if (quotes === "passed") items.push(h("li", { text: "Quote: found in the filing" }));
  else if (quotes === "none") items.push(h("li", { text: "No quote cited" }));
  else if (quotes === "failed") items.push(limitLine("li", "Quote: not found in the filing"));
  else if (quotes) items.push(h("li", { text: `Quote check: ${quotes}` }));

  const numbers = str(checks.numbers);
  const detail = list(checks.numbers_detail);
  let numbersItem = null;
  if (numbers === "passed") numbersItem = h("li", { text: "Numbers: all matched" });
  else if (numbers === "none") numbersItem = h("li", { text: "No number to check" });
  else if (numbers === "failed") numbersItem = limitLine("li", "A number did not match");
  else if (numbers) numbersItem = h("li", { text: `Number check: ${numbers}` });
  if (numbersItem && detail.length) {
    numbersItem.append(
      h("details", { class: "check-detail" }, h("summary", { text: "Number check details" }), h("ul", null, detail.map((line) => h("li", { text: String(line) })))),
    );
  }
  if (numbersItem) items.push(numbersItem);

  // The period check, as the record states it. It reports and withholds nothing, so a year it
  // could not place is a caution under the checks, never a failed check. A record without the
  // field (older than the check) says nothing about it.
  // Listed after the meaning check, so that a caution on its own line ends the list.
  let periodItem = null;
  const periods = str(checks.periods);
  const periodLines = list(checks.periods_detail).map(String);
  const periodDetail = periodLines.length
    ? h("details", { class: "check-detail" }, h("summary", { text: "Period check details" }), h("ul", { "data-periods-detail": "" }, periodLines.map((line) => h("li", { text: line }))))
    : "";
  if (periods === "passed") {
    periodItem = h("li", { "data-periods": periods }, "Years named: all in its evidence", periodDetail);
  } else if (periods === "none") {
    periodItem = h("li", { "data-periods": periods, text: "No year checked" });
  } else if (periods === "unverified") {
    const unplaced = list(checks.periods_unverified);
    periodItem = h(
      "li",
      { class: "period-caution", "data-periods": periods },
      h("span", { class: "mark-limit" }, limitGlyph(), " ", h("span", { class: "period-caution-title", text: "Period not found in its evidence:" })),
      h(
        "ul",
        { class: "period-unplaced" },
        unplaced.map((entry) => h("li", { "data-period-mention": str(entry?.mention), "data-comparative": entry?.comparative === true ? "true" : "false", text: str(entry?.detail) || str(entry?.mention) })),
      ),
      periodDetail,
    );
  } else if (periods) {
    periodItem = h("li", { "data-periods": periods, text: `Period check: ${periods}` });
  }

  // The meaning check, as the record states it. A record from before the check reads as not checked.
  const support = str(checks.support) || "unchecked";
  const reason = str(checks.support_detail);
  let supportItem;
  if (support === "passed" || support === "partly") {
    supportItem = h("li", { "data-support": support }, meaningMark(support));
    if (support === "passed" && reason) {
      supportItem.append(h("details", { class: "check-detail" }, h("summary", { text: "Its reason" }), checkerReason(reason, "data-support-detail")));
    }
  } else if (support === "failed") {
    supportItem = limitLine("li", h("span", { class: "meaning-words", text: MEANING_WORDS.failed }));
    supportItem.dataset.support = support;
  } else if (support === "unchecked") {
    supportItem = h("li", { "data-support": support }, h("span", { class: "meaning-words", text: MEANING_WORDS.unchecked }));
  } else {
    supportItem = h("li", { "data-support": support, text: `Meaning check: ${support}` });
  }
  items.push(supportItem);
  if (periodItem) items.push(periodItem);

  // Agreeing only in part is a result the reader must weigh, so its reason is shown in the open.
  const partly = support === "partly" ? checkerReason(reason || "no reason was recorded.", "data-support-detail") : "";
  return h("div", { class: "checks" }, h("span", { class: "label", text: "Checks: " }), h("ul", { class: "check-list" }, items), partly);
}

/** The reported figures a finding cites, resolved against `run.metrics`. */

function renderCitedFigures(ids, metrics) {
  const cited = list(ids);
  if (cited.length === 0) return null;
  return h(
    "div",
    { class: "cited" },
    h("span", { class: "label", text: "Reported figures cited: " }),
    h(
      "ul",
      { class: "cited-list" },
      cited.map((id) => {
        const metric = metrics.get(id);
        if (!metric) return h("li", { class: "muted", text: `Figure ${id} is listed but missing from the record.` });
        const row = document.getElementById(figureDomId(id));
        return h(
          "li",
          { "data-cited-metric": id },
          `${metric.label} · ${metric.period_label} · `,
          h("span", { class: "fig-value", text: metric.display }),
          row ? [" · ", h("a", { class: "fig-open", href: `#${encodeURIComponent(figureDomId(id))}`, "data-opens-figure": id, onclick: openFigure(id), text: "see its arithmetic and inputs" })] : "",
        );
      }),
    ),
  );
}

/** The verified excerpt in its surrounding text, where it sits, and the filing it came from. */
function renderEvidence(item, source, inspected = false) {
  const quote = h(
    "blockquote",
    { class: "excerpt" },
    item.context_before ? h("span", { class: "context" }, "…", item.context_before) : "",
    h("mark", { text: item.excerpt }),
    item.context_after ? h("span", { class: "context" }, item.context_after, "…") : "",
  );
  const caption = h(
    "figcaption",
    { class: "evidence-caption" },
    h("span", { class: "locator", title: ITEM_GLOSS }, h("span", { class: "label", text: "Located under: " }), item.locator || "location not recorded"),
    h("span", { class: "source-line" }, sourceLine(source, item.source_id)),
    externalLink(item.link || source?.url, evidenceLinkWords(item, source)),
  );
  return h("figure", { class: "evidence", [inspected ? "data-inspected-evidence" : "data-evidence-id"]: item.id }, h("span", { class: "evidence-id" }, `${item.id} · quote found word for word`, h("span", { class: "evidence-hl", text: ", highlighted" })), quote, caption);
}

/** The words on an evidence link: what the record's `link_kind` says the link opens. */
function evidenceLinkWords(item, source) {
  const page = source?.kind === "public_html";
  const words = Object.hasOwn(LINK_WORDS, str(item.link_kind)) ? LINK_WORDS[item.link_kind] : null;
  if (!words) return page ? "Open the page" : "Open in filing";
  return words[page ? 1 : 0];
}

function sourceLine(source, sourceId) {
  if (!source) return `${sourceId} (not in the source list)`;
  if (source.kind === "public_html") {
    return [`${source.id} · Web page: ${source.title || source.url}`, source.published_date ? ` · published ${source.published_date}` : ""];
  }
  const gloss = formGloss(source.form);
  return [
    `${source.id} · `,
    h("abbr", { title: source.accession ? `${ACCESSION_GLOSS}: ${source.accession}` : null, text: source.form ?? "Filing" }),
    gloss ? ` (${gloss})` : "",
    source.period_end ? ` · period ended ${source.period_end}` : "",
    source.published_date ? ` · filed ${source.published_date}` : "",
  ];
}

/**
 * Withheld findings. Those the second model rejected (`checks.support` "failed") get
 * their own group; with none of them, the list is drawn as it was before the check.
 */
function renderWithheld(run, ctx) {
  const withheld = list(run.unsupported_findings);
  els.withheldSection.hidden = withheld.length === 0;
  const item = (finding) => {
    const claim = ctx.claims.get(finding.claim_id);
    return h(
      "li",
      { class: "withheld-item" },
      h("p", { class: "withheld-for muted", text: `Proposed for ${finding.claim_id}${claim ? `: ${claim.text}` : ""}` }),
      renderFinding(finding, ctx, true),
    );
  };
  const byMeaning = withheld.filter((finding) => str(finding.checks?.support) === "failed");
  const byChecks = withheld.filter((finding) => str(finding.checks?.support) !== "failed");
  // Collapsed behind one line: the record's count, then the kinds of reason present.
  const c = run.coverage ?? {};
  const kinds = [];
  if (byMeaning.length) kinds.push(Number.isFinite(c.findings_failed_meaning) ? [cov(c, "findings_failed_meaning"), " by the meaning check"] : "by the meaning check");
  if (byChecks.length) kinds.push(byMeaning.length ? "the others for a quote or a number" : "for a quote or a number");
  const fold = (...content) =>
    h(
      "details",
      { class: "withheld-fold" },
      h(
        "summary",
        null,
        Number.isFinite(c.findings_withheld) ? [cov(c, "findings_withheld"), ` ${unit(c.findings_withheld, "finding", "findings")} withheld: `] : "Findings withheld: ",
        ...kinds.flatMap((kind, i) => (i ? ["; ", kind] : [kind])),
        h("span", { class: "fold-hint", text: ". None counts toward a verdict." }),
      ),
      h("p", { class: "hint", text: "The engine proposed these findings, but each failed a check. They count toward no verdict." }),
      ...content,
    );
  if (byMeaning.length === 0) {
    els.withheld.replaceChildren(fold(h("ul", { class: "withheld-list" }, byChecks.map(item))));
    return;
  }
  const group = (key, title, hint, findings) =>
    h(
      "div",
      { class: "withheld-group", "data-withheld-group": key },
      h("h4", { class: "withheld-subtitle", text: title }),
      h("p", { class: "hint", text: hint }),
      h("ul", { class: "withheld-list" }, findings.map(item)),
    );
  els.withheld.replaceChildren(fold(
    byChecks.length ? group("checks", "Withheld for a quote or a number", "A quote was not found in the filing, a number did not match, or nothing could be checked.", byChecks) : "",
    group("meaning", "Withheld by the meaning check", "A second model read the quoted evidence and judged that it does not support the statement. That too is a model's reading: read the quote before you dismiss the finding.", byMeaning),
  ));
}

function renderBriefLists(run) {
  const brief = run.brief;
  els.unknownsSection.hidden = !brief;
  els.nextSection.hidden = !brief;
  if (!brief) return;
  fillList(els.unknowns, brief.unknowns, "None recorded.");
  fillList(els.nextSteps, brief.next_steps, "None recorded.");
}

/** The first three errors in full; every error inside a closed disclosure. */
function renderErrors(run, finished) {
  const errors = list(run.errors);
  fillList(els.errors, errors.slice(0, 3), finished ? "None recorded." : "None so far.", true);
  els.errorsMore.replaceChildren();
  if (errors.length > 3) {
    const all = h("ul", { class: "mark-list" });
    fillList(all, errors, "", true);
    els.errorsMore.append(h("details", { id: "errors-all", class: "errors-all" }, h("summary", { text: `All ${errors.length} errors` }), all));
  }
}

function renderSources(run) {
  const sources = list(run.sources);
  els.sourcesBody.replaceChildren();
  if (sources.length === 0) {
    els.sourcesBody.append(h("tr", null, h("td", { colspan: "9", class: "muted", text: run.status === "running" ? "Sources appear as they are retrieved." : "No source was recorded." })));
    return;
  }
  for (const source of sources) {
    const filing = source.kind === "sec_filing";
    const gloss = formGloss(source.form);
    let formCell;
    if (filing) {
      formCell = h("td", null, h("abbr", { title: source.accession ? `${ACCESSION_GLOSS}: ${source.accession}` : null, text: source.form ?? "Filing" }), gloss ? h("span", { class: "gloss", text: ` ${gloss}` }) : "");
    } else if (source.kind === "sec_xbrl") {
      formCell = h("td", null, "XBRL data", h("span", { class: "gloss", text: " reported figures" }));
    } else {
      formCell = h("td", null, "Web page", h("span", { class: "gloss", text: ` ${source.title || ""}` }));
    }
    const read = source.extraction_status === "extracted";
    const statusCell = read
      ? h("td", { class: "ok-read", text: "Read" })
      : h("td", { class: "not-read" }, limitGlyph(), " Not read", source.error ? `: ${source.error}` : "");
    els.sourcesBody.append(
      h(
        "tr",
        null,
        h("th", { scope: "row", text: source.id }),
        formCell,
        h("td", { text: source.period_end ?? "—" }),
        h("td", { text: source.published_date ? `${source.published_date}${filing ? "" : " (published)"}` : "—" }),
        h("td", { text: utc(source.retrieved_at) }),
        h("td", { class: "num", text: read && filing ? num(source.sections ?? 0) : "—" }),
        h("td", { class: "num", text: read ? num(source.characters ?? 0) : "—" }),
        statusCell,
        h("td", null, externalLink(source.url, "Open")),
      ),
    );
  }
}

// ---------------------------------------------------------------- reported figures

// ---------------------------------------------------------------- 8-Ks since the annual report

const EVENT_ID = /^[A-Za-z0-9-]{1,80}$/;

/** The element id of an 8-K in the panel; "" for an id from the record that could not be one. */
function eventAnchor(eventId) {
  return EVENT_ID.test(eventId) ? `event-${eventId}` : "";
}

/**
 * The 8-Ks the record lists after the annual report the run read, newest first, as the record
 * orders and words them: each with its date, form, link, kind and what became of it, then each
 * item with its SEC title, its category and, for an 8-K read, its opening sentences and the
 * roles a 5.02 names. Nothing for a run recorded before version 12.
 */
function renderEvents(run) {
  const asOf = run.as_of;
  els.eventsSection.hidden = !asOf;
  if (!asOf) {
    els.events.replaceChildren();
    return;
  }
  const words = state.meta?.events ?? {};
  els.eventsTitle.textContent = str(words.heading) || "Since the annual report";
  const parts = [];
  // How old the evidence is, in the record's own line: the bar's chip is this line cut to a date.
  if (str(asOf.line)) parts.push(h("p", { class: "event-asof", "data-events-as-of": "", text: asOf.line }));
  if (str(words.note)) parts.push(h("p", { class: "hint", text: words.note }));
  const counts = str(asOf.counts?.line);
  if (counts) {
    parts.push(
      str(asOf.index_error)
        ? limitLine("p", h("span", { class: "event-counts", "data-event-counts": "", text: counts }))
        : h("p", { class: "event-counts", "data-event-counts": "", text: counts }),
    );
  }
  const events = list(run.timeline);
  if (events.length) parts.push(h("ol", { class: "events" }, ...events.map((event) => renderEvent(event, words))));
  else if (!counts) parts.push(h("p", { class: "muted", text: "The record lists no 8-K since the annual report." }));
  els.events.replaceChildren(...parts);
}

function renderEvent(event, words, inspected = false) {
  const substantive = event.substantive === true;
  const kind = substantive ? "substantive" : "routine";
  const kindLabel = str(words.kind_labels?.[kind]) || kind;
  const status = str(event.status);
  const statusLabel = str(words.status_labels?.[status]) || status;
  const anchor = eventAnchor(str(event.id));
  const head = h(
    "p",
    { class: "event-head" },
    h("strong", { class: "event-date", text: str(event.filed_label) || str(event.filed_date) }),
    h(
      "span",
      { class: "event-headline" },
      externalLink(event.url, `${str(event.form)} ${str(event.accession)}`),
      " · ",
      h("span", { class: `event-kind is-${kind}`, "data-event-kind": kind, text: kindLabel }),
      " · ",
      h("span", { class: "event-status", "data-event-status": status, text: statusLabel }),
    ),
  );
  const entry = inspected
    ? h("div", { class: `event ev-${kind}`, "data-inspected-event": str(event.id) }, head)
    : h("li", { class: `event ev-${kind}`, id: anchor || null, tabindex: anchor ? "-1" : null, "data-event-id": str(event.id), "data-pick": `event:${str(event.id)}` }, head);
  if (str(event.reason)) entry.append(limitLine("p", h("span", { "data-event-reason": "", text: event.reason })));
  const items = h("ul", { class: "event-items" });
  for (const item of list(event.items)) {
    const number = str(item.number);
    const category = str(item.category);
    const row = h(
      "li",
      { class: "event-item", "data-item": number },
      h("span", { class: "event-item-title", text: `Item ${number}. ${str(item.title)}` }),
      " ",
      h("span", { class: "event-category", "data-category": category, text: str(words.category_labels?.[category]) || category }),
    );
    const roles = list(item.roles);
    if (roles.length) {
      row.append(h("p", { class: "event-roles", "data-event-roles": "" }, ruleMark("Found by a fixed rule"), " ", h("span", { class: "label", text: "Roles named: " }), roles.join(", ")));
    }
    const opening = list(item.opening);
    if (opening.length) {
      row.append(h("blockquote", { class: "event-opening", "data-event-opening": number }, ...opening.map((sentence) => h("p", { text: sentence }))));
      row.append(h("p", { class: "event-link" }, externalLink(event.url, `Read Item ${number} in the ${str(event.form)}`)));
    }
    items.append(row);
  }
  entry.append(items);
  if (!inspected) entry.append(pickButton("Read its items"));
  return entry;
}

// ---------------------------------------------------------------- the tape

/** The figures on the tape, in order: the run's own metrics of these keys, never computed here. */
const TAPE_KEYS = ["revenue", "revenue_yoy", "gross_margin", "operating_margin", "fcf_margin", "eps_diluted"];

/**
 * The tape: the newest period's key figures in one dense row under the company's name. Each
 * cell is a metric the record sends (its label, display string and period label) with the
 * sparkline of its series; the quarter's metric when the record has one, else the year's.
 * Selecting a cell opens that figure, with its arithmetic, among the reported figures.
 */
function renderTape(run) {
  if (!els.tape) return;
  // A record with an analysis names its own headline figures (`Run.analysis.headline`): those, not a fixed set.
  const headline = hasAnalysis(run) ? headlineTable(run) : "";
  if (els.tapeTitle) els.tapeTitle.textContent = headline ? "Headline figures" : "Newest figures";
  if (headline) {
    els.tapeSection.hidden = false;
    els.tape.dataset.source = "headline";
    els.tape.replaceChildren(headline, str(run.analysis.headline_note) ? h("p", { class: "hint", "data-headline-note": "", text: run.analysis.headline_note }) : "");
    return;
  }
  els.tape.dataset.source = "metrics";
  const metrics = list(run.metrics);
  const series = list(run.series);
  const pick = (key) => metrics.find((m) => m.key === key && m.period === "quarter") ?? metrics.find((m) => m.key === key && m.period === "annual");
  const chosen = TAPE_KEYS.map(pick).filter(Boolean);
  els.tapeSection.hidden = chosen.length === 0;
  if (chosen.length === 0) {
    els.tape.replaceChildren();
    return;
  }
  const period = str(chosen[0].period_label);
  const cells = chosen.map((metric) =>
    h(
      "a",
      { class: "tape-cell", href: `#figures-section`, "data-tape-metric": metric.id, "data-pick": `figure:${metric.id}`, onclick: openFigure(metric.id) },
      h("span", { class: "tape-label", text: metric.label }),
      h("span", { class: `tape-value ${valueClass(metric)} dec` }, ...decimalParts(metric.display)),
      sparkline(metric, series),
      str(metric.period_label) !== period ? h("span", { class: "tape-period", text: metric.period_label }) : "",
    ),
  );
  els.tape.replaceChildren(h("p", { class: "tape-head", text: period }), h("div", { class: "tape-row" }, cells));
}

/**
 * Read one reported figure: in the inspector where there is one (its formula and the values
 * behind it), else by opening its row among the reported figures and bringing it into view.
 */
function openFigure(metricId) {
  return (event) => {
    if (inspectorOn() && state.ctx?.metrics.has(metricId)) {
      event.preventDefault();
      pick({ kind: "figure", id: metricId });
      return;
    }
    const row = document.querySelector(`#figures details.fig-row[data-metric-id="${CSS.escape(metricId)}"]`);
    if (!row) return;
    event.preventDefault();
    const fold = row.closest("details.fig-untied");
    if (fold) fold.open = true;
    row.open = true;
    reveal(row, { scroll: false });
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    row.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
    row.querySelector("summary")?.focus({ preventScroll: true });
  };
}

// ---------------------------------------------------------------- the time line

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAY_MS = 86400000;

/** A record date ("YYYY-MM-DD", or an ISO timestamp) as milliseconds at UTC midnight; NaN when it is not one. */
function dayOf(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(str(value));
  return match ? Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : Number.NaN;
}

/** "2026-11-12" as "12 Nov 2026", the way the record's own labels write a date. Presentation only. */
function dateLabel(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(str(value));
  if (!match) return str(value) || "date not recorded";
  return `${Number(match[3])} ${MONTHS[Number(match[2]) - 1]} ${match[1]}`;
}

/**
 * What the time line draws, read from the run: the annual and quarterly reports it read, the
 * 8-Ks its record lists, which of those its quotes come from, the run's own date and the
 * newest filing read. Selection and lookup only.
 */
function timelineData(run) {
  const sources = list(run.sources).filter((x) => x.kind === "sec_filing" && Number.isFinite(dayOf(x.published_date)));
  const quotedSources = new Set(list(run.evidence).map((e) => e.source_id));
  const quotedAccessions = new Set(sources.filter((x) => quotedSources.has(x.id)).map((x) => str(x.accession)));
  const periodic = sources
    .filter((x) => !str(x.form).toUpperCase().startsWith("8-K"))
    .map((x) => ({ source: x, day: dayOf(x.published_date), quoted: quotedSources.has(x.id) }));
  const events = list(run.timeline)
    .filter((e) => Number.isFinite(dayOf(e.filed_date)))
    .map((e) => ({ event: e, day: dayOf(e.filed_date), quoted: quotedAccessions.has(str(e.accession)) }));
  // A run as of a past date ends its time line at that date, not at the day it ran (version 14).
  const asOf = str(run.as_of?.requested);
  const runDay = asOf && Number.isFinite(dayOf(asOf)) ? dayOf(asOf) : dayOf(run.started_at);
  const newest = dayOf(run.as_of?.newest_filed);
  return { periodic, events, runDay, newest, asOf };
}

/** The categories of an 8-K's items that the record's wording calls substantive, as labels. */
function eventCategories(event) {
  const words = state.meta?.events ?? {};
  const substantive = new Set(list(words.substantive));
  const seen = [];
  for (const item of list(event.items)) {
    const category = str(item.category);
    if (event.substantive === true && substantive.size && !substantive.has(category)) continue;
    const label = str(words.category_labels?.[category]) || category;
    if (label && !seen.includes(label)) seen.push(label);
  }
  return seen;
}

/** Show the time line for a run whose record has dated filings; hide it otherwise. */
function renderTimeline(run) {
  if (!els.timeline) return;
  const data = timelineData(run);
  const show = Number.isFinite(data.runDay) && (data.periodic.length > 0 || data.events.length > 0);
  els.timelineSection.hidden = !show;
  state.timelineRun = show ? run : null;
  if (!show) {
    els.timeline.replaceChildren();
    return;
  }
  drawTimeline(els.timeline, run);
}

/**
 * One horizontal date axis in SVG, drawn at the container's own width so its text keeps its
 * size: reports above the axis, 8-Ks below, the run as a rule, the time between the newest
 * filing read and the run hatched. Each mark is a link to its filing with a tooltip on hover
 * or focus.
 */
function drawTimeline(container, run) {
  const data = timelineData(run);
  const width = Math.max(Math.round(container.clientWidth || 880), 300);
  const narrow = width < 560;
  // Without 8-Ks the space below the axis holds only the gap's label and the months.
  const H = data.events.length ? 184 : Number.isFinite(data.newest) ? 176 : 132;
  const axisY = 84;
  const left = 10;
  const right = 14;
  const days = [...data.periodic.map((x) => x.day), ...data.events.map((x) => x.day), data.runDay];
  if (Number.isFinite(data.newest)) days.push(data.newest);
  let lo = Math.min(...days);
  let hi = Math.max(...days);
  const span = Math.max(hi - lo, 30 * DAY_MS);
  lo -= span * 0.03;
  hi += span * 0.04;
  const xAt = (day) => left + ((day - lo) / (hi - lo)) * (width - left - right);

  const svg = s(
    "svg",
    { viewBox: `0 0 ${width} ${H}`, width, height: H, role: "group", "aria-labelledby": "timeline-title", "data-timeline": "" },
    s("defs", null, s("pattern", { id: "tl-hatch", width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, s("line", { x1: 0, y1: 0, x2: 0, y2: 6, class: "tl-hatch-line" }))),
  );

  // The time between the newest filing read and the run: what the record cannot know.
  if (Number.isFinite(data.newest) && data.runDay > data.newest) {
    const x0 = xAt(data.newest);
    const x1 = xAt(data.runDay);
    const daysWord = Number.isFinite(run.as_of?.days_since_newest) ? plural(run.as_of.days_since_newest, "day", "days") : "";
    svg.append(
      s(
        "g",
        { "data-tl": "gap" },
        s("title", { text: `Between the newest filing read (${dateLabel(run.as_of.newest_filed)}) and ${data.asOf ? "the date this run is as of" : "this run"}${daysWord ? `: ${daysWord}` : ""}. Nothing filed in this time is in the record.` }),
        // A band on the axis, not a block over the chart: the days the record cannot know.
        s("rect", { x: x0, y: axisY - 7, width: Math.max(x1 - x0, 2), height: 14, class: "tl-gap" }),
      ),
    );
    if (daysWord) {
      // Under the 8-K labels, ending at the run's line: how long the record cannot see.
      const text = `${daysWord} between the newest filing read and ${data.asOf ? "the date the run is as of" : "the run"}`;
      svg.append(s("text", { x: x1, y: axisY + 92, class: "tl-gap-label", "text-anchor": "end", text }));
    }
  }

  // Month ticks along the axis, a year label on each January and on the first tick.
  const first = new Date(lo);
  let tick = Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 1);
  let firstTick = true;
  const ticks = s("g", { class: "tl-ticks", "aria-hidden": "true" });
  let lastLabel = -Infinity;
  while (tick <= hi) {
    const d = new Date(tick);
    const x = xAt(tick);
    ticks.append(s("line", { x1: x, x2: x, y1: axisY, y2: axisY + 5, class: "tl-tick" }));
    const month = d.getUTCMonth();
    if (x - lastLabel > (narrow ? 34 : 30)) {
      const yearLabel = month === 0 || firstTick;
      ticks.append(s("text", { x: x + 2, y: axisY + 16, class: yearLabel ? "tl-year" : "tl-tick-label", text: yearLabel ? `${MONTHS[month]} ${d.getUTCFullYear()}` : MONTHS[month] }));
      lastLabel = x + (yearLabel ? 30 : 0);
      firstTick = false;
    }
    tick = Date.UTC(d.getUTCFullYear(), month + 1, 1);
  }
  svg.append(ticks, s("line", { x1: left - 6, x2: width - 4, y1: axisY, y2: axisY, class: "tl-axis" }));

  // The annual and quarterly reports: bars above the axis, a dot on top when quoted.
  let lastFormX = -Infinity;
  let formRow = 0;
  for (const item of data.periodic.sort((a, b) => a.day - b.day)) {
    const x = xAt(item.day);
    const source = item.source;
    const annual = str(source.form).toUpperCase().startsWith("10-K");
    formRow = x - lastFormX < 46 ? 1 - formRow : 0;
    lastFormX = x;
    const tip = [
      `${str(source.form)} · filed ${dateLabel(source.published_date)}`,
      source.period_end ? `For the period ended ${dateLabel(source.period_end)}` : "",
      item.quoted ? "Quoted in this run's findings" : "Read by this run; not quoted in a verified finding",
    ];
    const shape = [
      s("rect", { x: x - 7, y: 22, width: 14, height: axisY - 22, class: "tl-hit" }),
      s("rect", { x: x - 1.5, y: 40, width: 3, height: axisY - 40, class: `tl-filing ${annual ? "is-annual" : "is-quarterly"}` }),
      item.quoted ? s("circle", { cx: x, cy: 40, r: 4.5, class: "tl-quoted-dot" }) : "",
      s("text", { x, y: 33 - formRow * 12, "text-anchor": "middle", class: "tl-label is-form", text: str(source.form) }),
    ];
    svg.append(timelineMark("filing", { "data-source-id": source.id, "data-quoted": item.quoted ? "true" : "false" }, source.url, tip, shape, container));
  }

  // The 8-Ks: below the axis; substantive ones a filled diamond with their category, routine ones a small circle.
  const labelRows = [-Infinity, -Infinity];
  for (const item of data.events.sort((a, b) => a.day - b.day)) {
    const event = item.event;
    const x = xAt(item.day);
    const y = axisY + 34;
    const substantive = event.substantive === true;
    const categories = eventCategories(event);
    const words = state.meta?.events ?? {};
    const kind = substantive ? "substantive" : "routine";
    const tip = [
      `${str(event.form)} · filed ${str(event.filed_label) || dateLabel(event.filed_date)} · ${str(words.kind_labels?.[kind]) || kind}`,
      list(event.items).map((it) => `Item ${str(it.number)}${str(it.title) ? ` ${str(it.title)}` : ""}`).join("; "),
      str(words.status_labels?.[str(event.status)]) || str(event.status),
      item.quoted ? "Quoted in this run's findings" : "",
    ];
    const shape = [
      s("rect", { x: x - 8, y: axisY + 20, width: 16, height: 28, class: "tl-hit" }),
      substantive
        ? s("path", { d: `M ${x} ${y - 7} L ${x + 6} ${y} L ${x} ${y + 7} L ${x - 6} ${y} Z`, class: "tl-8k is-substantive" })
        : s("circle", { cx: x, cy: y, r: 3.6, class: "tl-8k is-routine" }),
      item.quoted ? s("circle", { cx: x, cy: axisY + 23, r: 3, class: "tl-quoted-dot" }) : "",
    ];
    // A category is written under its mark on one of two rows, and only where a row has room: a
    // mark without a written label still says its categories on hover, on focus and to a screen reader.
    const row = x - labelRows[0] > 120 ? 0 : x - labelRows[1] > 120 ? 1 : -1;
    if (substantive && categories.length && !narrow && row >= 0) {
      labelRows[row] = x;
      const labelX = Math.min(Math.max(x, left + 40), width - 50);
      shape.push(s("text", { x: labelX, y: axisY + 56 + row * 15, "text-anchor": "middle", class: "tl-label is-cat", text: categories.join(", ") }));
    }
    svg.append(timelineMark("8k", { "data-event-id": str(event.id), "data-kind": kind, "data-quoted": item.quoted ? "true" : "false" }, event.url, tip, shape, container));
  }

  // The run itself.
  const rx = xAt(data.runDay);
  const runEnd = rx > width - 110;
  svg.append(
    s(
      "g",
      { "data-tl": "run", class: "tl-run-mark" },
      s("title", { text: data.asOf ? `This run is as of ${dateLabel(data.asOf)} (it ran ${utc(run.started_at)})` : `This run, started ${utc(run.started_at)}` }),
      s("line", { x1: rx, x2: rx, y1: 12, y2: axisY + 46, class: "tl-run" }),
      s("path", { d: `M ${rx - 4} 12 L ${rx + 4} 12 L ${rx} 18 Z`, class: "tl-run-head" }),
      s("text", { x: runEnd ? rx - 7 : rx + 7, y: 16, "text-anchor": runEnd ? "end" : "start", class: "tl-label is-run", text: data.asOf ? `As of ${dateLabel(data.asOf)}` : `Run ${dateLabel(run.started_at)}` }),
    ),
  );

  const tipBox = h("div", { class: "tl-tip", role: "tooltip", id: "tl-tip", hidden: true });
  container.replaceChildren(svg, tipBox);
  container.dataset.width = String(width);
}

/** One mark of the time line: a link to its filing (or a focusable group without one), its title and tooltip. */
function timelineMark(kind, attrs, url, tipLines, shape, container) {
  const lines = tipLines.filter(Boolean);
  const href = safeUrl(url);
  const props = { class: "tl-mark", "data-tl": kind, ...attrs, "aria-label": `${lines.join(". ")}.${href ? " Opens the filing in a new tab." : ""}`, "aria-describedby": "tl-tip" };
  const node = href ? s("a", { ...props, href, target: "_blank", rel: "noopener noreferrer" }) : s("g", { ...props, tabindex: 0 });
  node.append(s("title", { text: lines.join("\n") }), ...shape.filter(Boolean));
  const show = () => {
    const tip = container.querySelector(".tl-tip");
    if (!tip) return;
    tip.replaceChildren(
      h("p", { class: "tl-tip-head", text: lines[0] ?? "" }),
      ...lines.slice(1).map((line) => h("p", { class: "tl-tip-items", text: line })),
      href ? h("p", { class: "tl-tip-open", text: "Select to open the filing ↗" }) : "",
    );
    tip.hidden = false;
    const box = node.getBoundingClientRect();
    const frame = container.getBoundingClientRect();
    const x = box.left + box.width / 2 - frame.left;
    tip.style.left = `${Math.max(0, Math.min(x - 120, frame.width - 260))}px`;
    tip.style.top = `${box.bottom - frame.top + 6}px`;
  };
  const hide = () => {
    const tip = container.querySelector(".tl-tip");
    if (tip) tip.hidden = true;
  };
  node.addEventListener("mouseenter", show);
  node.addEventListener("focus", show);
  node.addEventListener("mouseleave", hide);
  node.addEventListener("blur", hide);
  return node;
}

function renderRunFigures(run) {
  const metrics = list(run.metrics);
  const notes = list(run.metrics_notes);
  const claim = workspaceOn() && state.run === run ? selectedClaim() : null;
  state.figuresFor = claim ? claim.id : "";
  els.figuresSection.hidden = metrics.length === 0 && notes.length === 0;
  if (els.figuresSection.hidden) {
    els.figures.replaceChildren();
    return;
  }
  renderFigures(els.figures, { metrics, series: run.series, notes, tie: figureTie(run, claim) });
}

/**
 * Which reported figures the record's analysis ties to the selection: for a claim, the figures
 * of the measures it is tied to (`Claim.analysis.relevant`); for the whole thesis, every figure
 * some claim is tied to (all but `Run.analysis.untied_metric_ids`). Null for a record with no
 * analysis, which lists every figure as before. Selection by the record's ids, nothing more.
 */
function figureTie(run, claim) {
  if (!hasAnalysis(run)) return null;
  if (claim) {
    const relevant = list(claim.analysis?.relevant);
    const ids = new Set(relevant.flatMap((item) => list(item?.metric_ids).map(String)));
    return {
      isTied: (metric) => ids.has(metric.id),
      earlier: true,
      head: `Tied to claim ${claim.id}`,
      why: relevant.map((item) => `${str(item?.label)} (${list(item?.reasons).join(", ")})`).join("; "),
      none: str(claim.analysis?.relevance_note) || "The record ties no reported figure to this claim.",
      rest: "Reported figures not tied to this claim",
    };
  }
  const untied = new Set(list(run.analysis.untied_metric_ids).map(String));
  return {
    isTied: (metric) => !untied.has(metric.id),
    head: "Tied to a claim of this thesis",
    why: "",
    none: "The record ties no reported figure to a claim.",
    rest: str(run.analysis.untied_note) || "Reported figures no claim is tied to",
  };
}

/** The latest period end of one kind; ISO dates compare as strings. Selection, not a result. */
function latestEnd(metrics, kind) {
  let latest = "";
  for (const metric of metrics) {
    if (metric.period === kind && str(metric.period_end) > latest) latest = metric.period_end;
  }
  return latest;
}

/** The newest quarter and newest fiscal year side by side, then notes and charts. */
function renderFigures(container, data) {
  const metrics = list(data.metrics);
  const notes = list(data.notes);
  const series = list(data.series);
  const row = (metric) => figureRow(metric, series);
  container.replaceChildren();
  if (str(state.meta?.figures_note)) container.append(h("p", { class: "hint", text: state.meta.figures_note }));
  // The newest quarter and the newest fiscal year of the whole record, whichever figures are listed.
  const columns = [
    ["quarter", "Newest quarter in the record"],
    ["annual", "Newest fiscal year in the record"],
  ];
  const allFacts = metrics.filter((m) => !isTagged(m));
  const ends = columns.map(([kind]) => latestEnd(allFacts, kind));
  const figureGrid = (chosen) => {
    const grid = h("div", { class: "fig-grid" });
    columns.forEach(([kind, heading], index) => {
      const end = ends[index];
      if (!end) return;
      const rows = chosen.filter((m) => (m.period === kind || m.period === "instant") && m.period_end === end);
      if (!rows.length) return;
      const periodLabel = allFacts.find((m) => m.period === kind && m.period_end === end)?.period_label ?? end;
      grid.append(
        h(
          "section",
          { class: "fig-col", "aria-label": `${heading}: ${periodLabel}` },
          h("h4", { class: "fig-head" }, periodLabel, h("span", { class: "muted small", text: ` · ${heading.toLowerCase()}` })),
          h("ul", { class: "fig-list" }, rows.map(row)),
        ),
      );
    });
    return grid.childElementCount ? grid : "";
  };
  const hint = h("p", { class: "hint", text: "Open a figure to see its arithmetic and the reported values it used. The line beside each value is its series in the record, oldest to newest, with this period circled." });
  const tie = data.tie ?? null;
  if (metrics.length === 0) {
    container.append(h("p", { class: "muted", text: "The record holds no reported figures." }));
  } else if (!tie) {
    container.append(figureGrid(allFacts), hint);
    const tagged = metrics.filter(isTagged);
    if (tagged.length) container.append(taggedGroup(tagged));
  } else {
    // Tied to the selection first; the rest of the record behind a labelled control. As before, the
    // lists are of the newest quarter and the newest fiscal year (and the tagged figures); a tied
    // figure of an earlier period is listed after them with its period, so none tied is left out.
    const newest = (m) => columns.some(([kind], index) => ends[index] && (m.period === kind || m.period === "instant") && m.period_end === ends[index]);
    const tied = metrics.filter(tie.isTied);
    const tiedFacts = tied.filter((m) => !isTagged(m) && newest(m));
    const tiedTagged = tied.filter(isTagged);
    // For a claim the record names each figure; for the whole thesis it names every period of a tied measure, and the newest are listed.
    const tiedEarlier = tie.earlier ? tied.filter((m) => !isTagged(m) && !newest(m)) : [];
    const tiedCount = tiedFacts.length + tiedTagged.length + tiedEarlier.length;
    const rest = metrics.filter((m) => !tie.isTied(m));
    const restFacts = rest.filter((m) => !isTagged(m) && newest(m));
    const restTagged = rest.filter(isTagged);
    const restCount = restFacts.length + restTagged.length;
    container.append(h("p", { class: "fig-tie", "data-fig-tied": String(tiedCount) }, h("span", { class: "label", text: tie.head }), tie.why ? h("span", { class: "muted", text: ` ${tie.why}` }) : ""));
    if (tiedCount) {
      container.append(figureGrid(tiedFacts));
      if (tiedEarlier.length) container.append(h("ul", { class: "fig-list fig-tied-earlier" }, tiedEarlier.map((metric) => figureRow(metric, series, true))));
      container.append(hint);
      if (tiedTagged.length) container.append(taggedGroup(tiedTagged));
    } else {
      container.append(h("p", { class: "muted fig-tie-none", "data-fig-none": "", text: tie.none }));
    }
    if (restCount) {
      container.append(
        h(
          "details",
          { class: "fig-untied", "data-fig-untied": String(restCount) },
          h("summary", null, h("span", { class: "fig-untied-label", text: tie.rest }), h("span", { class: "muted", text: ` (${num(restCount)} of the newest quarter and fiscal year)` })),
          figureGrid(restFacts),
          restTagged.length ? taggedGroup(restTagged, tiedTagged.length ? "fig-tagged-title-rest" : "fig-tagged-title") : "",
        ),
      );
    }
  }
  if (notes.length) {
    const notesList = h("ul", { class: "mark-list" });
    fillList(notesList, notes, "", true);
    container.append(h("div", { class: "fig-notes" }, h("p", { class: "label", text: "Notes on the figures" }), notesList));
  }
  const charts = renderCharts(list(data.series));
  if (charts) container.append(charts);
}

/** A figure read from a filing's own inline XBRL tags: the backend gives it an id starting "tagged:". */
function isTagged(metric) {
  return str(metric?.id).startsWith("tagged:");
}

/** The DOM id of a figure's row. Metric ids hold colons and "+": fine in an id, encoded in a link. */
function figureDomId(metricId) {
  return `fig-${metricId}`;
}

/** The tagged figures offered to the engine, in the record's order, after the company-facts figures. */
function taggedGroup(tagged, titleId = "fig-tagged-title") {
  return h(
    "section",
    { class: "fig-tagged", "aria-labelledby": titleId, "data-figure-group": "tagged" },
    h("h4", { class: "fig-head", id: titleId }, "Figures tagged in the filings ", ruleMark()),
    h(
      "p",
      { class: "fig-tagged-source" },
      "Read from the filings' own inline XBRL tags, in the newest annual and the newest quarterly report the run read, and offered to the engine because the run asked for them.",
    ),
    h(
      "p",
      { class: "fig-tagged-caution", "data-tagged-caution": "" },
      "The row labels are made from tag names, not taken from the company's own tables, and no person has compared them with the printed tables.",
    ),
    h("ul", { class: "fig-list" }, tagged.map((metric) => figureRow(metric, []))),
  );
}

/**
 * A sparkline of the series the record sends for this figure's key and period: the values
 * placed in a small box, oldest to newest, the figure's own period circled. Drawing only; the
 * values and the period are the record's. Nothing when the record has no such series.
 */
function sparkline(metric, series) {
  const match = series.find((x) => x.key === metric.key && x.period === metric.period);
  const points = list(match?.points);
  const values = points.map((p) => p.value).filter((v) => Number.isFinite(v));
  // Fewer than three points draw as fragments, not a line: none is drawn.
  if (values.length < 3) return h("span", { class: "spark-empty", "aria-hidden": "true" });
  const W = 88;
  const H = 20;
  const pad = 2.5;
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  if (!(hi > lo)) {
    hi += 1;
    lo -= 1;
  }
  const xAt = (i) => pad + (i * (W - 2 * pad)) / Math.max(points.length - 1, 1);
  const yAt = (v) => pad + ((hi - v) / (hi - lo)) * (H - 2 * pad);
  let path = "";
  let pen = false;
  points.forEach((point, i) => {
    if (!Number.isFinite(point.value)) {
      pen = false;
      return;
    }
    path += `${pen ? "L" : "M"}${xAt(i).toFixed(1)} ${yAt(point.value).toFixed(1)} `;
    pen = true;
  });
  const svg = s("svg", { class: "spark", viewBox: `0 0 ${W} ${H}`, "aria-hidden": "true", focusable: "false", "data-spark": metric.key });
  if (lo < 0 && hi > 0) svg.append(s("line", { x1: 0, x2: W, y1: yAt(0), y2: yAt(0), class: "spark-zero" }));
  svg.append(s("path", { d: path.trim(), class: "spark-line" }));
  const here = points.findIndex((p) => p.period_end === metric.period_end);
  if (here >= 0 && Number.isFinite(points[here].value)) svg.append(s("circle", { cx: xAt(here), cy: yAt(points[here].value), r: 2.6, class: "spark-now" }));
  return svg;
}

/** The class of a value cell: missing, negative (by the sign of the record's value) or plain. */
/**
 * A display string split at its decimal point, so a column of values lines up on it. The
 * characters are the record's own, in order; nothing is rounded or reformatted.
 */
function decimalParts(display) {
  // Three columns: up to the decimal point, the decimals, then the unit ("B", "%", " points"), so
  // a column of values lines up on the point whatever each one's unit is.
  const text = str(display);
  const match = /^(.*?\d)((?:\.\d+)?)(\D*)$/.exec(text);
  if (!match) return [h("span", { class: "dec-int", text }), h("span", { class: "dec-frac" }), h("span", { class: "dec-unit" })];
  return [h("span", { class: "dec-int", text: match[1] }), h("span", { class: "dec-frac", text: match[2] }), h("span", { class: "dec-unit", text: match[3] })];
}

function valueClass(metric) {
  if (metric.value === null || metric.value === undefined) return "fig-value is-missing";
  return Number.isFinite(metric.value) && metric.value < 0 ? "fig-value is-neg" : "fig-value";
}

/** What is behind a figure: its formula, its note and every reported value it used. */
function figureBody(metric) {
  const body = h("div", { class: "fig-body" });
  body.append(
    h("p", null, h("span", { class: "label", text: "Formula: " }), str(metric.formula) ? h("code", { text: metric.formula }) : "none; the value was read directly from one reported fact."),
  );
  if (str(metric.note)) body.append(h("p", null, h("span", { class: "label", text: "Note: " }), metric.note));
  const inputs = list(metric.inputs);
  if (inputs.length) {
    body.append(
      h(
        "div",
        { class: "table-wrap", tabindex: "0", role: "region", "aria-label": `Reported values behind ${metric.label}` },
        h(
          "table",
          { class: "inputs" },
          h(
            "thead",
            null,
            h("tr", null, ["Concept", "Period", "Value as given", "Form", "Filed", "Accession", "Flags"].map((t) => h("th", { scope: "col", text: t }))),
          ),
          h("tbody", null, inputs.map(inputRow)),
        ),
      ),
    );
  } else {
    body.append(h("p", { class: "muted", text: "No reported value was used." }));
  }
  return body;
}

/**
 * One figure: its label, the line of its series and its value. Selecting the row reads the
 * figure in the inspector; where there is no inspector (a phone, paper) the row opens in place.
 */
function figureRow(metric, series = [], withPeriod = false) {
  const body = figureBody(metric);
  return h(
    "li",
    null,
    h(
      "details",
      { class: "fig-row", id: figureDomId(metric.id), "data-metric-id": metric.id, "data-pick": `figure:${metric.id}` },
      h(
        "summary",
        {
          onclick: (event) => {
            if (!inspectorOn() || !state.ctx?.metrics.has(metric.id)) return;
            event.preventDefault();
            pick({ kind: "figure", id: metric.id });
          },
        },
        h("span", { class: "fig-label" }, h("span", { class: "fig-name", text: metric.label }), metric.period === "instant" || withPeriod ? h("span", { class: "fig-asof muted small" }, h("span", { class: "sep", text: " · " }), metric.period_label) : ""),
        sparkline(metric, series),
        h("span", { class: `${valueClass(metric)} dec` }, ...decimalParts(metric.display)),
      ),
      body,
    ),
  );
}

function inputRow(ref) {
  const flags = [];
  if (ref.derived) flags.push("derived");
  if (ref.restated) flags.push("restated");
  const period = ref.start ? `${ref.start} to ${ref.end}` : `as of ${ref.end}`;
  const value = Number.isFinite(ref.value) ? `${ref.value.toLocaleString("en-US", { maximumFractionDigits: 20 })} ${str(ref.unit)}` : "—";
  // `data-th` names each cell where the table is stacked instead of ruled (the inspector).
  return h(
    "tr",
    null,
    h("td", { "data-th": "Concept" }, h("code", { text: ref.concept })),
    h("td", { "data-th": "Period", text: period }),
    h("td", { class: "num", "data-th": "Value as given", text: value }),
    h("td", { "data-th": "Form", text: ref.form ?? "—" }),
    h("td", { "data-th": "Filed", text: ref.filed ?? "—" }),
    h("td", { "data-th": "Accession" }, h("code", { text: ref.accession ?? "—" })),
    h("td", { "data-th": "Flags" }, flags.length ? flags.join(", ") : "—", str(ref.note) ? h("span", { class: "muted", text: ` — ${ref.note}` }) : ""),
  );
}

// ---------------------------------------------------------------- charts

function findSeries(series, key) {
  return series.find((x) => x.key === key && x.period === "quarter") ?? series.find((x) => x.key === key && x.period === "annual") ?? null;
}

function renderCharts(series) {
  const blocks = [];
  for (const spec of CHARTS) {
    const chosen = spec.keys.map((key) => findSeries(series, key)).filter((x) => x && list(x.points).length);
    if (chosen.length === 0) continue;
    blocks.push(renderChart(spec, chosen));
  }
  if (blocks.length === 0) return null;
  return h("div", { class: "charts" }, h("p", { class: "label", text: "Over time" }), h("div", { class: "chart-grid" }, blocks));
}

const CH = { width: 520, height: 250, left: 14, right: 144, top: 30, bottom: 48 };

/** One chart as inline SVG, with its title, unit, period ends, and a table alternative. */
function renderChart(spec, seriesList) {
  const id = `chart-${++state.chartSeq}`;
  const periodWord = seriesList[0].period === "annual" ? "fiscal year" : "quarter";
  const title = `${spec.title}, by ${periodWord}`;
  const right = spec.kind === "bars" ? 14 : seriesList.length > 1 ? CH.right : 64;
  const plotW = CH.width - CH.left - right;
  const plotH = CH.height - CH.top - CH.bottom;
  const ends = seriesList[0].points.map((p) => p.period_end);
  const slot = plotW / Math.max(ends.length, 1);
  const xAt = (i) => CH.left + slot * (i + 0.5);

  const values = seriesList.flatMap((x) => x.points.map((p) => p.value)).filter((v) => Number.isFinite(v));
  let lo = values.length ? Math.min(...values) : 0;
  let hi = values.length ? Math.max(...values) : 1;
  if (spec.kind === "bars") {
    lo = Math.min(lo, 0);
    hi = Math.max(hi, 0);
  } else {
    const pad = (hi - lo || Math.abs(hi) || 1) * 0.12;
    lo -= pad;
    hi += pad;
  }
  if (!(hi > lo)) hi = lo + 1;
  const yAt = (v) => CH.top + ((hi - v) / (hi - lo)) * plotH;

  const svg = s(
    "svg",
    { viewBox: `0 0 ${CH.width} ${CH.height}`, role: "img", "aria-labelledby": `${id}-title`, class: "chart", preserveAspectRatio: "xMidYMid meet" },
    s("title", { id: `${id}-title`, text: `${title}. Each point shows its reported value on hover or focus; the same values are in the table below.` }),
    s("text", { x: CH.left, y: 14, class: "axis-title", text: spec.axis }),
    s("line", { x1: CH.left, x2: CH.left + plotW, y1: CH.top + plotH, y2: CH.top + plotH, class: "axis" }),
  );
  if (lo < 0 && hi > 0) {
    svg.append(
      s("line", { x1: CH.left, x2: CH.left + plotW, y1: yAt(0), y2: yAt(0), class: "zero" }),
      s("text", { x: CH.left + plotW + 4, y: yAt(0) + 4, class: "tick", text: "0" }),
    );
  }
  ends.forEach((end, i) => {
    const [year, rest] = [String(end).slice(0, 4), String(end).slice(5)];
    svg.append(
      s(
        "text",
        { x: xAt(i), y: CH.top + plotH + 16, class: "tick", "text-anchor": "middle" },
        s("tspan", { x: xAt(i), text: rest }),
        s("tspan", { x: xAt(i), dy: 13, text: year }),
      ),
    );
  });
  svg.append(s("text", { x: CH.left + plotW, y: CH.height - 2, class: "tick", "text-anchor": "end", text: `${capitalize(periodWord)} end` }));

  if (spec.kind === "bars") drawBars(svg, seriesList[0], { xAt, yAt, slot });
  else drawLines(svg, seriesList, { xAt, yAt, right: CH.left + plotW });

  return h(
    "figure",
    { class: "chart-block" },
    h("figcaption", { class: "chart-title", text: title }),
    svg,
    chartTable(title, seriesList),
  );
}

function pointTitle(seriesItem, point) {
  return `${seriesItem.label}, ${seriesItem.period === "annual" ? "fiscal year" : "quarter"} ended ${point.period_end}: ${point.display}`;
}

/** Bars; a missing value is a gap labelled with its display string, never a zero bar. */
function drawBars(svg, seriesItem, { xAt, yAt, slot }) {
  const width = Math.min(slot * 0.62, 46);
  seriesItem.points.forEach((point, i) => {
    const group = s("g", { class: "pt", tabindex: 0 }, s("title", { text: pointTitle(seriesItem, point) }));
    if (Number.isFinite(point.value)) {
      const top = Math.min(yAt(point.value), yAt(0));
      const bottom = Math.max(yAt(point.value), yAt(0));
      group.append(
        s("rect", { x: xAt(i) - width / 2, y: top, width, height: Math.max(bottom - top, 1), class: "bar" }),
        s("text", { x: xAt(i), y: top - 5, class: "bar-label", "text-anchor": "middle", text: point.display }),
      );
    } else {
      group.append(s("text", { x: xAt(i), y: yAt(0) - 6, class: "gap-label", "text-anchor": "middle", text: point.display }));
    }
    svg.append(group);
  });
}

function marker(kind, x, y) {
  if (kind === "square") return s("rect", { x: x - 3.5, y: y - 3.5, width: 7, height: 7, class: "marker" });
  if (kind === "triangle") return s("path", { d: `M ${x} ${y - 4.5} L ${x + 4.5} ${y + 3.5} L ${x - 4.5} ${y + 3.5} Z`, class: "marker" });
  return s("circle", { cx: x, cy: y, r: 3.8, class: "marker" });
}

/** Lines broken at missing values, a distinct dash and marker per series, labelled at the end. */
function drawLines(svg, seriesList, { xAt, yAt, right }) {
  const labels = [];
  seriesList.forEach((seriesItem, index) => {
    const style = LINE_STYLES[index % LINE_STYLES.length];
    const group = s("g", { class: `series series-${index}` });
    let path = "";
    let pen = false;
    seriesItem.points.forEach((point, i) => {
      if (!Number.isFinite(point.value)) {
        pen = false;
        return;
      }
      path += `${pen ? "L" : "M"} ${xAt(i).toFixed(1)} ${yAt(point.value).toFixed(1)} `;
      pen = true;
    });
    if (path) group.append(s("path", { d: path.trim(), class: "line", "stroke-dasharray": style.dash || null }));
    let last = null;
    const points = seriesItem.points;
    points.forEach((point, i) => {
      if (!Number.isFinite(point.value)) {
        // The gap's label sits on its own series, between the neighbouring points' heights.
        const near = [points[i - 1], points[i + 1]].filter((p) => p && Number.isFinite(p.value)).map((p) => yAt(p.value));
        const y = near.length ? near.reduce((a, b) => a + b, 0) / near.length : CH.top + 10;
        group.append(s("g", { class: "pt gap", tabindex: 0 }, s("title", { text: pointTitle(seriesItem, point) }), s("text", { x: xAt(i), y: y + 4, class: "gap-label", "text-anchor": "middle", text: point.display })));
        return;
      }
      last = { point, y: yAt(point.value) };
      const x = xAt(i);
      const y = yAt(point.value);
      group.append(
        s(
          "g",
          { class: "pt", tabindex: 0 },
          s("title", { text: pointTitle(seriesItem, point) }),
          marker(style.marker, x, y),
          s("text", { x, y: y - 9, class: "pt-label", "text-anchor": "middle", text: point.display }),
        ),
      );
    });
    svg.append(group);
    if (last) labels.push({ y: last.y, name: seriesList.length > 1 ? seriesItem.label : "", display: last.point.display, index });
  });
  // Direct labels at the right edge (name, then the newest value), nudged apart so they never overlap.
  const step = seriesList.length > 1 ? 30 : 16;
  labels.sort((a, b) => a.y - b.y);
  for (let i = 1; i < labels.length; i += 1) {
    if (labels[i].y - labels[i - 1].y < step) labels[i].y = labels[i - 1].y + step;
  }
  for (const label of labels) {
    const style = LINE_STYLES[label.index % LINE_STYLES.length];
    const text = s("text", { x: right + 22, y: label.y + 4, class: "direct-label" });
    if (label.name) {
      text.append(s("tspan", { x: right + 22, text: label.name }), s("tspan", { x: right + 22, dy: 13, class: "direct-value", text: label.display }));
    } else {
      text.append(s("tspan", { class: "direct-value", text: label.display }));
    }
    svg.append(
      s(
        "g",
        { class: `series series-${label.index} direct` },
        s("line", { x1: right + 4, x2: right + 18, y1: label.y, y2: label.y, class: "line", "stroke-dasharray": style.dash || null }),
        text,
      ),
    );
  }
}

/** The chart's values as a table, in a disclosure: the text alternative. */
function chartTable(title, seriesList) {
  const ends = [];
  for (const seriesItem of seriesList) for (const point of seriesItem.points) if (!ends.includes(point.period_end)) ends.push(point.period_end);
  const lookup = seriesList.map((seriesItem) => new Map(seriesItem.points.map((p) => [p.period_end, p])));
  return h(
    "details",
    { class: "chart-table" },
    h("summary", { text: "Show these figures as a table" }),
    h(
      "div",
      { class: "table-wrap", tabindex: "0", role: "region", "aria-label": title },
      h(
        "table",
        { class: "inputs" },
        h("caption", { class: "visually-hidden", text: title }),
        h("thead", null, h("tr", null, h("th", { scope: "col", text: "Period end" }), seriesList.map((x) => h("th", { scope: "col", text: x.label })))),
        h(
          "tbody",
          null,
          ends.map((end) =>
            h(
              "tr",
              null,
              h("th", { scope: "row", text: end }),
              lookup.map((points, index) => {
                const point = points.get(end);
                return point
                  ? h("td", { class: "num", "data-series": seriesList[index].key, "data-period-end": end, text: point.display })
                  : h("td", { class: "num muted", text: "—" });
              }),
            ),
          ),
        ),
      ),
    ),
  );
}

// ---------------------------------------------------------------- start

/** The run or saved thesis named in the hash: {kind: "run" | "thesis", id}, or null. */
function hashTarget() {
  if (location.hash === "#inbox") return { kind: "inbox", id: "" };
  const match = /^#(run|thesis)=(.+)$/.exec(location.hash);
  if (!match) return null;
  try {
    return { kind: match[1], id: decodeURIComponent(match[2]) };
  } catch {
    return null;
  }
}

function openHashTarget() {
  const target = hashTarget();
  if (!target) return;
  if (target.kind === "run" && target.id !== state.runId) watchRun(target.id);
  if (target.kind === "thesis" && target.id !== state.thesisId) openThesis(target.id);
  if (target.kind === "inbox" && els.inboxView.hidden) openInbox();
}

// ---------------------------------------------------------------- version 14: computed claims, dates, restatements
//
// Drawn from the backend's own fields (docs/examples/v14/README.md is the contract). The page
// computes nothing: outcomes, the bound test, operands, arithmetic, margins, what counted,
// each history point and whether it flipped, and every restated value and change are the
// record's. It places dates on an axis and maps the outcome tokens to their glyphs and words.
// Every field is read defensively: a missing one is left out, an added one is ignored.

/** A computed test's outcome: its own glyphs (⊨ holds, ⊭ fails, ⊘ cannot be computed), never a verdict's. */
const TEST_MARK = { holds: "⊨", fails: "⊭", cannot_compute: "⊘" };
/** The outcome tokens in words, as the backend's `outcome_label` writes them; for a history point, which has no label. */
const TEST_FALLBACK = { holds: "Holds", fails: "Fails", cannot_compute: "Cannot be computed" };
/** `counted_as`, the stance the verdict rule counts, in words. */
const COUNTED_WORDS = { supports: "Counted as support", challenges: "Counted as a challenge" };
/** The line the page shows when the readers of a claim did not read the same test (docs/claim-tests.md). */
const READINGS_DIFFER = "Readings differ: not counted";
/** A reader that read no test answers this canonical (app.core.policy.NO_TEST). */
const NO_TEST = "none";
/** `ComputedTest.agreement` when no two readers reached the same test (app.core.policy.NOT_AGREED). */
const NOT_AGREED = "not_agreed";
/** The agreements under which the test counts and `read_by` names the readers who agreed (app.core.policy). */
const AGREED = new Set(["agreed", "agreed_with_dissent"]);
const READER_WORDS = { grammar: "The grammar (a fixed rule, no model)", model: "The first model reader", model_2: "The second model reader" };
const READER_SHORT = { grammar: "Grammar", model: "Model 1", model_2: "Model 2" };
/** One mark per reader: read the test shown, read another test (a dissent when the test still counts), read no test. */
const READER_MARK = { same: "●", dissent: "≠", other: "≠", refused: "○" };
const ACCESSION_ID = /^\d{10}-\d{2}-\d{6}$/;

function testOutcome(outcome, label) {
  const key = token(outcome, TEST_MARK);
  return h(
    "span",
    { class: `ct-outcome o-${key}`, "data-outcome": key },
    h("span", { class: "glyph", "aria-hidden": "true", text: TEST_MARK[key] ?? "·" }),
    h("span", { text: str(label) || TEST_FALLBACK[key] || String(outcome ?? "") }),
  );
}

/**
 * EDGAR's index page of one filing, from the company's CIK and the accession number the record
 * names. A link only: the page sends no request with it. Empty when either is not in its form.
 */
function filingIndexUrl(cik, accession) {
  const id = str(accession);
  if (!Number.isInteger(cik) || !ACCESSION_ID.test(id)) return "";
  return `https://www.sec.gov/Archives/edgar/data/${cik}/${id.replaceAll("-", "")}/${id}-index.htm`;
}

/** "10-Q filed 26 Aug 2026", linked to the filing when the record names its accession. */
function filingRef(ref, cik) {
  const words = `${str(ref?.form) || "Filing"} filed ${dateLabel(ref?.filed)}`;
  const url = filingIndexUrl(cik, ref?.accession);
  return url ? externalLink(url, words) : h("span", { text: words });
}

function testOf(claim) {
  return claim?.computed && typeof claim.computed === "object" ? claim.computed : null;
}

/** The record's conclusion that no two readers agreed (`ComputedTest.agreement`); the page works nothing out. */
function readingsDiffer(claim) {
  return str(testOf(claim)?.agreement) === NOT_AGREED;
}

/** What the verdict rule made of the test, in words: counted as support or a challenge, not counted, or the readings differ. */
function countedTag(claim) {
  const test = testOf(claim);
  if (readingsDiffer(claim)) {
    return h("span", { class: "ct-counted c-differ", "data-counted": "differ" }, limitGlyph(), ` ${READINGS_DIFFER}`);
  }
  const key = str(test?.counted_as);
  if (key) return h("span", { class: `ct-counted c-${token(key, COUNTED_WORDS)}`, "data-counted": key, text: COUNTED_WORDS[key] ?? `Counted: ${key}` });
  return h("span", { class: "ct-counted c-none", "data-counted": "none", text: "Not counted" });
}

/**
 * Each model reader's own detail (model, and the API or a recording), from `claim_reader_detail`,
 * which the record writes one model reader after another, separated by "; ". When the parts do not
 * line up with the model readers, every model reader gets the whole line.
 */
function readerDetails(run) {
  const readers = str(run?.claim_readers).split(/, | and /).map((name) => name.trim()).filter(Boolean);
  const models = readers.filter((name) => name !== "grammar");
  const detail = str(run?.claim_reader_detail);
  const parts = detail.split("; ").map((part) => part.trim()).filter(Boolean);
  const out = { grammar: "a fixed rule, no model" };
  models.forEach((name, index) => {
    out[name] = parts.length === models.length ? parts[index] : detail;
  });
  return out;
}

/** True when a model reader read this claim (any reading by a reader other than the grammar). */
function modelRead(claim) {
  return list(claim?.readings).some((reading) => str(reading?.reader) && reading.reader !== "grammar");
}

/** True when the run's claim readers include a model (`claim_readers`, "grammar, model and model_2"). */
function runModelReaders(run) {
  return str(run?.claim_readers).split(/, | and /).some((name) => name.trim() && name.trim() !== "grammar");
}

/** The readers of the test shown, in short words: "the grammar", "Model 1 and Model 2". */
function readByWords(test) {
  const names = list(test?.read_by).map((reader) => (reader === "grammar" ? "the grammar" : READER_SHORT[reader] ?? str(reader))).filter(Boolean);
  if (names.length === 0) return "";
  return names.length === 1 ? names[0] : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/**
 * Who did what for a computed test, as the record says: the arithmetic is always code; the reading
 * into a test is the grammar's alone (then no model read the claim) or included a model reader
 * (then who read the test shown, from `read_by`). Never "no model" when a model read the claim.
 */
function computedByWords(claim) {
  const test = testOf(claim);
  if (!modelRead(claim)) return { board: "Computed by code, no model: ", kicker: "Read into a test by the grammar and computed by code from the XBRL facts: no model read the claim", model: false };
  const who = readByWords(test) || "its readers";
  return { board: `Read by ${who}; computed by code: `, kicker: `Read into a test by ${who}; the arithmetic is done by code from the XBRL facts`, model: true };
}

/** How one reader's reading stands to the test shown, from the record's own lists (`read_by`, `dissent`). */
function readingKind(reading, test) {
  const reader = str(reading?.reader);
  if (!str(reading?.canonical) || reading.canonical === NO_TEST) return "refused";
  if (test && list(test.read_by).includes(reader)) return "same";
  if (test && list(test.dissent).some((other) => str(other?.reader) === reader)) return "dissent";
  return "other";
}

/** One reader's mark: what it read, in words on hover or focus (and to a screen reader), with who the reader is. */
function readerMark(reading, test, details = {}) {
  const reader = str(reading?.reader);
  const kind = readingKind(reading, test);
  const name = READER_SHORT[reader] ?? (reader || "A reader");
  let said;
  if (kind === "same") said = test ? `read this test: ${str(reading.canonical)}` : `read ${str(reading.canonical)}`;
  else if (kind === "dissent") said = `read another test, a dissent: ${str(reading.canonical)}`;
  else if (kind === "other") said = `read another test: ${str(reading.canonical)}`;
  else said = `read no test${str(reading?.reason) ? `: ${reading.reason}` : ""}`;
  const who = str(details[reader]);
  const why = `${name}${who && who !== name ? ` (${who})` : ""} ${said}`;
  return h(
    "span",
    { class: `reader-mark rm-${kind}`, "data-reader-mark": reader, "data-mark": kind, "data-why": why, tabindex: "0" },
    h("span", { class: "glyph", "aria-hidden": "true", text: READER_MARK[kind] }),
    h("span", { class: "reader-short", text: name }),
    h("span", { class: "visually-hidden", text: `: ${why}` }),
  );
}

/**
 * Who read the claim and whether they agreed, in one row: a mark per reader, the record's
 * agreement label, and each dissenting reading. Nothing is compared here: the marks come from
 * the test's `read_by` and `dissent`, the agreement from `agreement` and `agreement_label`.
 */
function readersRow(claim, details = {}) {
  const readings = list(claim?.readings);
  if (readings.length === 0) return "";
  const test = testOf(claim);
  const agreement = str(test?.agreement);
  const dissent = list(test?.dissent);
  return h(
    "div",
    { class: "ct-readers", "data-readers": str(claim.id), "data-agreement": agreement || "none" },
    h("span", { class: "label", text: "Read by " }),
    h("span", { class: "reader-marks" }, ...readings.map((reading) => readerMark(reading, test, details))),
    test && str(test.agreement_label) ? h("span", { class: `ct-agreement a-${agreement === NOT_AGREED ? "differ" : agreement === "agreed_with_dissent" ? "dissent" : "agreed"}`, "data-agreement-label": agreement, text: test.agreement_label }) : "",
    dissent.length
      ? h(
          "p",
          { class: "ct-dissent", "data-dissent": dissent.map((reading) => str(reading?.reader)).join(" ") },
          h("span", { class: "glyph", "aria-hidden": "true", text: "≠ " }),
          h("span", { class: "label", text: "Dissent: " }),
          ...dissent.flatMap((reading, index) => [index ? "; " : "", `${READER_SHORT[reading?.reader] ?? str(reading?.reader)} read `, h("code", { text: str(reading?.canonical) })]),
        )
      : "",
  );
}

/** Every reading in full: each reader's test, or "no test" and why, as the record lists them (one or more). */
function readingsBlock(claim, { folded = true } = {}) {
  const readings = list(claim?.readings);
  if (readings.length === 0) return "";
  const readBy = list(testOf(claim)?.read_by);
  const items = h(
    "ul",
    { class: "readings" },
    readings.map((reading) => {
      const read = str(reading.canonical) && reading.canonical !== NO_TEST;
      return h(
        "li",
        { "data-reader": str(reading.reader), "data-canonical": str(reading.canonical) },
        h("span", { class: "reader-name", text: READER_WORDS[reading.reader] ?? (str(reading.reader) || "a reader") }),
        ": ",
        read ? h("code", { text: reading.canonical }) : h("span", { class: "muted", text: "no test" }),
        str(reading.reason) ? h("span", { class: "muted", text: ` (${reading.reason})` }) : "",
        read && str(reading.normal_form) && reading.normal_form !== reading.canonical ? h("span", { class: "muted", "data-normal-form": reading.normal_form }, " · compared as ", h("code", { text: reading.normal_form })) : "",
      );
    }),
  );
  const by = readBy.length ? h("span", { class: "muted", "data-read-by": readBy.join(" "), text: ` · the test above is the reading of: ${readBy.join(" and ")}` }) : "";
  if (!folded) return h("div", { class: "ct-readings", "data-readings": claim.id }, items);
  return h("details", { class: "ct-readings", "data-readings": claim.id }, h("summary", null, "Every reading", by), items);
}

/** One fact a value was read from: concept, period, value, the filing (linked) and its flags. */
function factLine(ref, cik) {
  const flags = [];
  if (ref?.derived === true) flags.push("derived");
  if (ref?.restated === true) flags.push("restated by a later filing");
  const period = str(ref?.start) ? `${ref.start} to ${str(ref.end)}` : `at ${str(ref?.end) || "—"}`;
  const value = Number.isFinite(ref?.value) ? `${ref.value.toLocaleString("en-US", { maximumFractionDigits: 20 })} ${str(ref.unit)}` : "no value";
  return h(
    "li",
    { class: "ct-fact", "data-fact-accession": str(ref?.accession) },
    // One span per field, each named: in a row they read as a line, in the inspector as a grid.
    h("span", { class: "cf", "data-th": "Concept" }, h("code", { text: str(ref?.concept) || "concept not recorded" })),
    h("span", { class: "sep", text: " · " }),
    h("span", { class: "cf", "data-th": "Period", text: period }),
    h("span", { class: "sep", text: " · " }),
    h("span", { class: "cf", "data-th": "Value", text: value }),
    h("span", { class: "sep", text: " · " }),
    h("span", { class: "cf", "data-th": "Filing" }, filingRef(ref, cik), str(ref?.accession) ? h("span", { class: "muted" }, " ", h("abbr", { title: ACCESSION_GLOSS, text: ref.accession })) : ""),
    flags.length ? h("span", { class: "cf ct-flag", "data-th": "Flags", text: ` · ${flags.join(", ")}` }) : "",
    str(ref?.note) ? h("span", { class: "cf muted", "data-th": "Note", text: ` — ${ref.note}` }) : "",
  );
}

/** One operand: its term, what it is, its value, the arithmetic with the numbers used, and the facts read. */
function operandRow(operand, cik) {
  const value = str(operand?.display) || "—";
  return h(
    "tr",
    { "data-operand": str(operand?.term) },
    h("th", { scope: "row" }, h("code", { text: str(operand?.term) }), str(operand?.label) ? h("span", { class: "ct-label", text: operand.label }) : ""),
    h("td", { class: `num${signClass(value)}`, "data-operand-value": "" }, value, str(operand?.note) ? h("span", { class: "ct-label muted", text: operand.note }) : ""),
    h("td", null, str(operand?.formula) ? h("code", { class: "ct-formula", text: operand.formula }) : h("span", { class: "muted", text: "read from one fact" })),
    h("td", null, list(operand?.inputs).length ? h("ul", { class: "ct-facts" }, list(operand.inputs).map((ref) => factLine(ref, cik))) : h("span", { class: "muted", text: "no fact" })),
  );
}

/** "left {comparison} right", each side as the record words it. */
function sidesLine(test) {
  // A constant (a threshold) is its own display: "70%", not "70% = 70%".
  const side = (operand) => {
    if (!operand || typeof operand !== "object") return [h("span", { class: "muted", text: "not recorded" })];
    if (str(operand.term) && str(operand.term) === str(operand.display)) return [h("strong", { text: operand.display })];
    return [h("code", { text: str(operand.term) }), " = ", h("strong", { text: str(operand.display) || "—" })];
  };
  return h("p", { class: "ct-sides", "data-sides": "" }, h("span", { class: "label", text: "Compared: " }), ...side(test.left), ` ${str(test.comparison)} `, ...side(test.right));
}

/**
 * The two sides of a test as a graphic: the value as a bar from zero, what it is compared with as
 * a tick, on one scale, with both display strings beside it. Placing the record's two numbers on
 * a line is drawing; the outcome and the margin are the record's. Nothing without both numbers.
 */
function marginBar(test) {
  const value = test?.left?.value;
  const against = test?.right?.value;
  if (!Number.isFinite(value) || !Number.isFinite(against)) return "";
  const lo = Math.min(0, value, against);
  const hi = Math.max(0, value, against);
  if (!(hi > lo)) return "";
  const W = 160;
  const xAt = (v) => 1 + ((v - lo) / (hi - lo)) * (W - 2);
  return h(
    "p",
    { class: `ct-bar o-${token(test.outcome, TEST_MARK)}`, "data-margin-bar": "" },
    s(
      "svg",
      { class: "ct-bar-svg", viewBox: `0 0 ${W} 14`, width: W, height: 14, "aria-hidden": "true", focusable: "false" },
      s("line", { x1: xAt(lo), x2: xAt(hi), y1: 7, y2: 7, class: "ct-bar-rail" }),
      s("rect", { x: Math.min(xAt(0), xAt(value)), y: 4, width: Math.max(Math.abs(xAt(value) - xAt(0)), 1), height: 6, class: "ct-bar-value" }),
      s("line", { x1: xAt(against), x2: xAt(against), y1: 0, y2: 14, class: "ct-bar-mark" }),
    ),
    h("span", { class: "ct-bar-words", "aria-hidden": "true" }, h("strong", { text: str(test.left.display) || "—" }), ` ${str(test.comparison)} ${str(test.right.display) || "—"}`),
  );
}

/** How a test of several parts is put together, in words: the rule of app.core.claim_eval._combined, not a result. */
const COMBINE_WORDS = {
  each: "A test held in each of several periods: it holds when every period's test holds, fails when any one fails, and otherwise cannot be computed.",
  and: "Two tests joined by \u201cand\u201d: it holds when both hold, fails when either fails, and otherwise cannot be computed.",
};

function isCombined(test) {
  return Boolean(str(test?.combines)) && list(test?.parts).length > 0;
}

/** The table of every value a test read: term, what it is, its value, how it was computed and the facts. */
function operandTable(operands, cik, label) {
  if (!operands.length) return "";
  return h(
    "div",
    { class: "table-wrap", tabindex: "0", role: "region", "aria-label": label },
    h(
      "table",
      { class: "ct-table" },
      h("thead", null, h("tr", null, ["Value", "Is", "How", "Read from"].map((t, i) => h("th", { scope: "col", class: i === 1 ? "num" : null, text: t })))),
      h("tbody", null, operands.map((operand) => operandRow(operand, cik))),
    ),
  );
}

function arithmeticList(lines) {
  return lines.length ? h("ol", { class: "ct-arith" }, lines.map((line) => h("li", { text: str(line) }))) : "";
}

/**
 * The parts of an "each" or an "and" test, every one drawn: its bound expression, its outcome
 * and margin, its two sides, its arithmetic and, for a part that could not be computed, why.
 * Then the record's own last line of arithmetic, which says how the parts came out together.
 * The operands of every part are in the one table above (the record lists each once).
 */
function partsBlock(claim, test) {
  const parts = list(test.parts);
  const combines = str(test.combines);
  const lines = list(test.arithmetic);
  const tally = lines.length ? str(lines[lines.length - 1]) : "";
  return h(
    "div",
    { class: "ct-parts-block", "data-combines": combines },
    h("p", { class: "ct-combine" }, h("span", { class: "label", text: combines === "each" ? `Each of ${parts.length} periods. ` : `Both of ${parts.length} tests. ` }), COMBINE_WORDS[combines] ?? `The parts combine as "${combines}".`),
    h(
      "ol",
      { class: "ct-parts" },
      parts.map((part, index) => {
        const key = token(part?.outcome, TEST_MARK);
        return h(
          "li",
          { class: `ct-part o-${key}`, "data-part": String(index), "data-outcome": key },
          h(
            "p",
            { class: "ct-part-head" },
            h("code", { "data-part-bound": "", text: str(part?.bound) || str(part?.canonical) }),
            " ",
            testOutcome(part?.outcome, part?.outcome_label),
            str(part?.margin_display) ? h("span", { class: `ct-margin${signClass(part.margin_display)}`, "data-part-margin": "", text: ` ${part.margin_display}` }) : "",
          ),
          str(part?.reason) ? h("p", { class: "ct-reason", "data-part-reason": "" }, h("span", { class: "label", text: "Why it could not be computed: " }), part.reason) : "",
          part && typeof part === "object" ? [marginBar(part), sidesLine(part)] : "",
          h("div", { "data-part-arith": "" }, arithmeticList(list(part?.arithmetic))),
          str(part?.note) ? h("p", { class: "ct-note muted", "data-part-note": "", text: part.note }) : "",
        );
      }),
    ),
    tally ? h("p", { class: "ct-tally", "data-combine-tally": "" }, h("span", { class: "label", text: "Together: " }), tally) : "",
  );
}

/**
 * A claim's computed test: the canonical expression, the outcome (with why it could not be
 * computed), what the verdict rule counted, who read it and whether they agreed, the bound test,
 * the operands with each value's filing and date, the arithmetic and the margin. A test of
 * several parts ("each", "and") draws every part.
 */
function computedTest(claim, cik, details = {}) {
  const test = claim.computed;
  const outcome = token(test.outcome, TEST_MARK);
  const combined = isCombined(test);
  return h(
    "section",
    { class: `ct o-${outcome}${combined ? " is-combined" : ""}`, id: `claim-${claim.id}-test`, "data-computed-test": claim.id, "data-pick": `test:${claim.id}`, "aria-label": `Computed test of claim ${claim.id}` },
    h(
      "div",
      { class: "ct-head" },
      h("p", { class: "ct-kicker", "data-computed-by": computedByWords(claim).model ? "models" : "grammar" }, ruleMark(computedByWords(claim).kicker), str(test.form) ? h("span", { class: "muted", text: ` · form: ${test.form}${combined ? `, ${test.combines}` : ""}` }) : ""),
      h("p", { class: "ct-expr" }, h("code", { "data-canonical": "", text: str(test.canonical) })),
      h("p", { class: "ct-result" }, testOutcome(test.outcome, test.outcome_label), countedTag(claim)),
      readersRow(claim, details),
    ),
    str(test.reason) ? h("p", { class: "ct-reason", "data-reason": "" }, h("span", { class: "label", text: "Why it could not be computed: " }), test.reason) : "",
    h("p", { class: "ct-bound" }, h("span", { class: "label", text: "Computed for: " }), str(test.bound) ? h("code", { "data-bound": "", text: test.bound }) : h("span", { class: "muted", text: "no period could be placed" })),
    str(test.as_of) ? h("p", { class: "ct-asof", "data-test-as-of": test.as_of }, h("span", { class: "label", text: "Facts read up to: " }), dateLabel(test.as_of)) : "",
    combined ? "" : [marginBar(test), sidesLine(test)],
    // A test of several parts shows every part here: each part's outcome is the substance of the whole.
    combined ? partsBlock(claim, test) : "",
    combined && !str(test.margin_display)
      ? h("p", { class: "ct-margin-line" }, h("span", { class: "label", text: "Margin: " }), h("span", { class: "ct-margin muted", "data-margin": "", text: "each part has its own" }))
      : h("p", { class: "ct-margin-line" }, h("span", { class: "label", text: "Margin: " }), h("span", { class: `ct-margin${signClass(str(test.margin_display))}`, "data-margin": "", text: str(test.margin_display) || "none: not computed" })),
    str(test.note) ? h("p", { class: "ct-note", "data-test-note": "" }, h("span", { class: "label", text: "Note: " }), test.note) : "",
    h("p", { class: "ct-pick" }, pickButton("Read the operands and the arithmetic")),
    // Every value read, the arithmetic and each reading: beside the test in the inspector; in place on a phone and on paper.
    h("div", { class: "ct-detail" }, ...computedDetail(claim, cik)),
  );
}

/** What is behind a computed test: every value it read with its facts, its arithmetic (a test of several parts shows each part's with the part) and every reading. */
function computedDetail(claim, cik) {
  const test = claim.computed;
  return [
    operandTable(list(test.operands), cik, `Values read for claim ${claim.id}`),
    !isCombined(test) && list(test.arithmetic).length ? h("div", { class: "ct-arith-block" }, h("p", { class: "label", text: "The arithmetic" }), arithmeticList(list(test.arithmetic))) : "",
    readingsBlock(claim),
  ].filter(Boolean);
}

/**
 * A claim that did not compile: the backend's words for what was not understood, said quietly,
 * then each reader's mark and, with more than one reader, each reader's reason.
 */
function compileNote(claim, details = {}) {
  const several = list(claim.readings).length > 1;
  return h(
    "div",
    { class: "ct-not", "data-compile-note": claim.id },
    h("p", { class: "muted" }, h("span", { class: "glyph", "aria-hidden": "true", text: "⊘ " }), h("span", { class: "label", text: "No computed test. " }), str(claim.compile_note)),
    several ? readersRow(claim, details) : "",
    readingsBlock(claim, { folded: !several }),
  );
}

/**
 * How many readers read the test the board shows, from the record: `read_by` against every reading,
 * when the counting rule says they agreed; the record's label otherwise (one reader, or none agreeing).
 */
function boardReaders(claim) {
  const test = testOf(claim);
  const agreement = str(test?.agreement);
  if (!agreement || agreement === NOT_AGREED) return "";
  const total = list(claim.readings).length;
  const agreeing = list(test.read_by).length;
  const words = AGREED.has(agreement) && total > 1 ? `${agreeing} of ${total} readers${list(test.dissent).length ? ", one dissenting" : ""}` : str(test.agreement_label);
  if (!words) return "";
  return h("span", { class: "score-readers", "data-board-readers": agreement, "data-read-by-count": String(agreeing), "data-readers-total": String(total), text: words });
}

/** On the verdict board: the computed part of the verdict, apart from the model's or the engine's reading of the findings. */
function boardComputed(claim) {
  const test = testOf(claim);
  if (!test) {
    if (!str(claim.compile_note)) return "";
    return h("span", { class: "score-computed is-none", "data-board-computed": "none", text: "No computed test: the verdict rests on the findings" });
  }
  const readers = boardReaders(claim);
  return h("span", { class: "score-computed", "data-board-computed": token(test.outcome, TEST_MARK) }, h("span", { class: "label", "data-computed-by": computedByWords(claim).model ? "models" : "grammar", text: computedByWords(claim).board }), testOutcome(test.outcome, test.outcome_label), " ", countedTag(claim), readers ? [h("span", { class: "sep", "aria-hidden": "true", text: " · " }), readers] : "");
}

// ---- the thesis over time

const TOT_LEVEL = { holds: 0, cannot_compute: 1, fails: 2 };
const TOT_SHORT = { holds: "holds", cannot_compute: "cannot", fails: "fails" };

function compiledClaims(run) {
  return list(run?.claims).filter((claim) => claim && claim.computed && typeof claim.computed === "object");
}

/** The section near the time line: each compiled claim's history, or why it has none. */
function renderThesisOverTime(run) {
  if (!els.totSection) return;
  const compiled = compiledClaims(run);
  els.totSection.hidden = compiled.length === 0;
  state.totRun = compiled.length ? run : null;
  if (compiled.length === 0) {
    els.tot.replaceChildren();
    return;
  }
  drawThesisOverTime(els.tot, run);
}

function drawThesisOverTime(container, run) {
  const width = Math.max(Math.round(container.clientWidth || 880), 300);
  container.dataset.width = String(width);
  const compiled = compiledClaims(run);
  const days = compiled.flatMap((claim) => list(claim.computed.history).map((point) => dayOf(point?.filed))).filter(Number.isFinite);
  const scale = days.length ? { lo: Math.min(...days), hi: Math.max(...days), width } : null;
  const cik = run.company?.cik;
  const compiledIds = new Set(compiled.map((claim) => claim.id));
  const notCompiled = list(run.claims).filter((claim) => claim && !compiledIds.has(claim.id)).map((claim) => str(claim.id));
  container.replaceChildren(
    // The verdicts over the lanes, drawn as they are everywhere (only for a run: each claim has one).
    list(run.claims).length && list(run.claims).every((claim) => str(claim?.verdict)) ? verdictStrip(run, { ids: true }) : "",
    h(
      "p",
      { class: "hint tot-lead" },
      "Each compiled claim's test as of each 10-K and 10-Q filing date, from the facts filed by that date: ",
      h("span", { class: "tot-key o-holds", text: "⊨ holds" }),
      " above, ",
      h("span", { class: "tot-key o-cannot_compute", text: "⊘ cannot be computed" }),
      " between, ",
      h("span", { class: "tot-key o-fails", text: "⊭ fails" }),
      " below; a ring marks a filing where the outcome flipped. The outcomes and the flips are the record's.",
    ),
    ...compiled.map((claim) => totClaim(claim, scale, cik)),
    notCompiled.length ? h("p", { class: "muted tot-none", "data-tot-not-compiled": notCompiled.join(" ") }, `Not compiled, so not drawn: ${notCompiled.join(", ")}.`) : "",
  );
}

/** One claim's lane: its test, the step line over the filing dates, its flips in words and every point as a table. */
function totClaim(claim, scale, cik) {
  const test = claim.computed;
  const points = list(test.history).filter((point) => point && Number.isFinite(dayOf(point.filed)));
  const head = h(
    "div",
    { class: "tot-head" },
    h("p", { class: "tot-title" }, h("span", { class: "claim-id", text: str(claim.id) }), h("span", { class: "tot-claim-text", text: str(claim.text) })),
    h("p", { class: "tot-now" }, h("span", { class: "muted", text: "Now: " }), testOutcome(test.outcome, test.outcome_label), " ", h("code", { class: "tot-expr", text: str(test.canonical) })),
  );
  const note = str(test.history_note) ? h("p", { class: "hint tot-note", "data-history-note": str(claim.id), text: test.history_note }) : "";
  // A test of several parts has one line for the whole test; each point's two sides are its first part's.
  const combined = isCombined(test);
  const firstPart = combined ? str(list(test.parts)[0]?.canonical) : "";
  const partsNote = combined
    ? h("p", { class: "hint tot-parts-note", "data-history-parts": str(test.combines) }, `One line for the whole test of ${list(test.parts).length} parts. At each point the record gives the whole test's outcome and the two sides of its first part`, firstPart ? [" (", h("code", { text: firstPart }), ")"] : "", "; it does not give the other parts' values at each point.")
    : "";
  const sides = (point) => (str(point.left_display) || str(point.right_display) ? ` (${combined ? "first part " : ""}${str(point.left_display) || "n/a"} against ${str(point.right_display) || "n/a"})` : "");
  if (points.length === 0 || !scale) {
    return h("div", { class: "tot-claim no-history", "data-tot-claim": str(claim.id), "data-points": "0" }, head, note);
  }
  const flips = points.filter((point) => point.flipped === true);
  return h(
    "div",
    { class: "tot-claim", "data-tot-claim": str(claim.id), "data-points": String(points.length) },
    head,
    totSvg(claim, points, scale),
    note,
    partsNote,
    flips.length
      ? h(
          "ul",
          { class: "tot-flips", "aria-label": `Where claim ${str(claim.id)} flipped` },
          flips.map((point) =>
            h(
              "li",
              { "data-flip": str(point.filed), "data-flip-to": token(point.outcome, TEST_MARK) },
              h("span", { class: "glyph", "aria-hidden": "true", text: "◯ " }),
              `Flipped to ${TEST_FALLBACK[point.outcome] ?? str(point.outcome)} with the `,
              filingRef(point, cik),
              str(point.bound) && !combined ? [": ", h("code", { text: point.bound })] : "",
              sides(point),
            ),
          ),
        )
      : "",
    h(
      "details",
      { class: "tot-table" },
      h("summary", null, "Every point, as a table"),
      h(
        "div",
        { class: "table-wrap", tabindex: "0", role: "region", "aria-label": `The history of claim ${str(claim.id)}` },
        h(
          "table",
          null,
          h("thead", null, h("tr", null, ["Filed", "Form", "Outcome", "Test", combined ? "First part's left" : "Left", combined ? "First part's right" : "Right", "Flipped", "Why not"].map((t) => h("th", { scope: "col", text: t })))),
          h(
            "tbody",
            null,
            points.map((point) =>
              h(
                "tr",
                { "data-point": str(point.filed), "data-outcome": token(point.outcome, TEST_MARK), "data-flipped": String(point.flipped === true) },
                h("td", { text: str(point.filed) }),
                h("td", { text: str(point.form) }),
                h("td", null, testOutcome(point.outcome, "")),
                h("td", null, h("code", { text: str(point.bound) })),
                h("td", { class: "num", text: str(point.left_display) || "—" }),
                h("td", { class: "num", text: str(point.right_display) || "—" }),
                h("td", { text: point.flipped === true ? "flipped" : "" }),
                h("td", { class: "muted", text: str(point.reason) }),
              ),
            ),
          ),
        ),
      ),
    ),
  );
}

/** The step line: holds above, cannot be computed between, fails below; each point a dot, each flip ringed and labelled with its filing. */
function totSvg(claim, points, { lo, hi, width }) {
  const W = width;
  const roomy = W >= 560;
  const plotL = roomy ? 70 : 52;
  const plotR = W - 14;
  // Room above the line for a flip's label, so the line never runs through one.
  const top = roomy ? 36 : 10;
  const gap = 16;
  const yAt = (outcome) => top + (TOT_LEVEL[outcome] ?? 1) * gap;
  const span = Math.max(hi - lo, DAY_MS);
  const xAt = (day) => (hi === lo ? (plotL + plotR) / 2 : plotL + ((day - lo) / span) * (plotR - plotL));
  const axisY = top + 2 * gap + 14;
  const H = axisY + 16;
  const svg = s("svg", { class: "tot-svg", viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": `Claim ${str(claim.id)}: its test's outcome at each filing date; the list and the table below give every point` });
  for (const [outcome, level] of Object.entries(TOT_LEVEL)) {
    const y = top + level * gap;
    svg.append(s("line", { x1: plotL - 4, x2: plotR, y1: y, y2: y, class: "tot-rail" }), s("text", { x: plotL - 8, y: y + 4, "text-anchor": "end", class: `tot-state o-${outcome}`, text: TOT_SHORT[outcome] }));
  }
  const firstYear = new Date(lo).getUTCFullYear();
  const lastYear = new Date(hi).getUTCFullYear();
  for (let year = firstYear; year <= lastYear + 1; year += 1) {
    const day = Date.UTC(year, 0, 1);
    if (day < lo || day > hi) continue;
    const x = xAt(day);
    svg.append(s("line", { x1: x, x2: x, y1: top - 4, y2: axisY - 8, class: "tot-grid" }), s("text", { x, y: axisY + 4, "text-anchor": "middle", class: "tot-date", text: String(year) }));
  }
  let d = "";
  points.forEach((point, index) => {
    const x = xAt(dayOf(point.filed));
    const y = yAt(point.outcome);
    d += index === 0 ? `M ${x} ${y}` : ` H ${x} V ${y}`;
  });
  svg.append(s("path", { d, class: "tot-step" }));
  // A flip is labelled on one of two rows, and only where the row has room: every flip is in the list under the line.
  const flipRows = [-Infinity, -Infinity];
  for (const point of points) {
    const key = token(point.outcome, TEST_MARK);
    const x = xAt(dayOf(point.filed));
    const y = yAt(point.outcome);
    const first = isCombined(claim.computed) ? "first part " : "";
    const words = `${str(point.form)} filed ${dateLabel(point.filed)}: ${TEST_FALLBACK[key] ?? str(point.outcome)}${str(point.bound) ? `, ${point.bound}` : ""}${str(point.left_display) ? ` (${first}${point.left_display} against ${str(point.right_display) || "n/a"})` : ""}${str(point.reason) ? `. ${point.reason}` : ""}`;
    svg.append(s("circle", { cx: x, cy: y, r: 3.2, class: `tot-pt o-${key}`, "data-point": str(point.filed) }, s("title", { text: words })));
    if (point.flipped === true) {
      svg.append(s("circle", { cx: x, cy: y, r: 7, class: "tot-flip", "data-flip": str(point.filed) }, s("title", { text: `Flipped: ${words}` })));
      const row = x - flipRows[0] > 150 ? 0 : x - flipRows[1] > 150 ? 1 : -1;
      if (roomy && row >= 0) {
        flipRows[row] = x;
        const anchor = x > plotR - 50 ? "end" : x < plotL + 50 ? "start" : "middle";
        svg.append(s("text", { x, y: row === 0 ? 10 : 22, "text-anchor": anchor, class: "tot-flip-label", text: `${str(point.form)} ${str(point.filed)}` }));
      }
    }
  }
  return svg;
}

// ---- as of a past date

/** The banner on a run made as of a past date: the date large, and the record's sentence on what it read. */
function asOfBanner(asOf) {
  const requested = str(asOf?.requested);
  return h(
    "div",
    { class: "asof-inner", "data-as-of-requested": requested },
    h("p", { class: "asof-kicker" }, h("span", { class: "glyph", "aria-hidden": "true", text: "◷ " }), "A run as of a past date"),
    h("p", { class: "asof-date" }, h("time", { datetime: requested, text: dateLabel(requested) })),
    h("p", { class: "asof-note", "data-as-of-note": "", text: str(asOf?.requested_note) || `This run read only what was filed by ${dateLabel(requested)}.` }),
  );
}

/** Show the banner when the record says the run was made as of a date (`as_of.requested`); hide it otherwise. */
function renderAsOfBanner(run) {
  if (!els.asofBanner) return;
  const requested = str(run?.as_of?.requested);
  document.body.classList.toggle("as-of-run", Boolean(requested));
  els.asofBanner.hidden = !requested;
  if (!requested) {
    els.asofBanner.replaceChildren();
    delete els.runView.dataset.asOf;
    return;
  }
  els.runView.dataset.asOf = requested;
  els.asofBanner.replaceChildren(asOfBanner(run.as_of));
}

// ---- the restatement ledger

/** One value of a restated period: the value, the filing that reported it and, after the first, the change. */
function ledgerValue(value, cik, first) {
  return h(
    "li",
    { class: first ? "ledger-value is-first" : "ledger-value", "data-ledger-value": str(value?.accession) },
    h("span", { class: `num-val${signClass(str(value?.display))}`, text: str(value?.display) || "—" }),
    " ",
    h("span", { class: "ledger-filing" }, filingRef(value, cik)),
    !first && (str(value?.change_display) || str(value?.change_percent_display))
      ? h("span", { class: `ledger-change${signClass(str(value.change_display))}`, "data-change": "" }, ` ${str(value.change_display)}${str(value.change_percent_display) ? ` (${value.change_percent_display})` : ""}`)
      : "",
    value?.returns_to_earlier === true ? h("span", { class: "ledger-flag", "data-returns": "", text: " · back to an earlier value" }) : "",
    str(value?.concept) ? h("span", { class: "muted ledger-concept" }, " ", h("code", { text: value.concept })) : "",
  );
}

/** The ledger as a table: each restated period, its first value, every later value that differed, and the change. */
function restatementLedger(ledger) {
  const cik = ledger?.cik;
  const entries = list(ledger?.entries);
  if (entries.length === 0) return h("p", { class: "muted", "data-ledger-empty": "", text: "No period changed value in a later filing." });
  return h(
    "div",
    { class: "table-wrap", tabindex: "0", role: "region", "aria-label": "Restatement ledger" },
    h(
      "table",
      { class: "ledger", "data-ledger": "" },
      h("thead", null, h("tr", null, ["Metric", "Period", "First reported", "Reported later", "Reports"].map((t, i) => h("th", { scope: "col", class: i === 4 ? "num" : null, text: t })))),
      h(
        "tbody",
        null,
        entries.map((entry) => {
          const values = list(entry?.values);
          return h(
            "tr",
            { "data-ledger-entry": `${str(entry?.key)}:${str(entry?.start)}:${str(entry?.end)}` },
            h("th", { scope: "row" }, str(entry?.label) || str(entry?.key), entry?.concept_changed === true ? h("span", { class: "ledger-flag", "data-concept-changed": "", text: " · tagged with another concept later" }) : ""),
            h("td", null, str(entry?.period_label) || `${str(entry?.start)} to ${str(entry?.end)}`),
            h("td", { class: "ledger-first" }, values.length ? h("ul", { class: "ledger-values" }, ledgerValue(values[0], cik, true)) : "—"),
            h("td", { class: "ledger-later" }, values.length > 1 ? h("ul", { class: "ledger-values" }, values.slice(1).map((value) => ledgerValue(value, cik, false))) : "—"),
            h("td", { class: "num", text: Number.isFinite(entry?.reports) ? num(entry.reports) : "—" }),
          );
        }),
      ),
    ),
  );
}

/**
 * (Not built.) The peer strip: the company's value as a dot on its industry's distribution.
 * The backend has no peers route (docs/examples/v14/README.md): drawn on the specimen only,
 * from made-up data, and never on the page.
 */
function peerStrip(record) {
  const rows = list(record.metrics).map((metric) => {
    const W = 520;
    const H = 40;
    const lo = metric.min?.value;
    const hi = metric.max?.value;
    const ok = Number.isFinite(lo) && Number.isFinite(hi) && hi > lo;
    const xAt = (v) => 8 + ((v - lo) / (hi - lo)) * (W - 16);
    const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", "aria-hidden": "true", focusable: "false" });
    if (ok) {
      for (const v of list(metric.peers)) if (Number.isFinite(v)) svg.append(s("circle", { cx: xAt(v), cy: 14 + ((v * 7919) % 7) - 3, r: 1.6, class: "peer-dot" }));
      svg.append(s("line", { x1: xAt(lo), x2: xAt(hi), y1: 14, y2: 14, class: "peer-range" }));
      if (Number.isFinite(metric.q1?.value) && Number.isFinite(metric.q3?.value)) {
        svg.append(s("rect", { x: xAt(metric.q1.value), y: 8, width: Math.max(xAt(metric.q3.value) - xAt(metric.q1.value), 1), height: 12, class: "peer-iqr" }));
      }
      if (Number.isFinite(metric.median?.value)) svg.append(s("line", { x1: xAt(metric.median.value), x2: xAt(metric.median.value), y1: 5, y2: 23, class: "peer-median" }));
      if (Number.isFinite(metric.company?.value)) svg.append(s("circle", { cx: xAt(metric.company.value), cy: 14, r: 6, class: "peer-you" }));
      svg.append(
        s("text", { x: 8, y: H - 2, class: "peer-tick", text: str(metric.min?.display) }),
        s("text", { x: W - 8, y: H - 2, "text-anchor": "end", class: "peer-tick", text: str(metric.max?.display) }),
        Number.isFinite(metric.median?.value) ? s("text", { x: xAt(metric.median.value), y: H - 2, "text-anchor": "middle", class: "peer-tick", text: `median ${str(metric.median.display)}` }) : "",
      );
    }
    return h(
      "div",
      { class: "peer", "data-peer-metric": str(metric.metric_label) },
      h("p", { class: "peer-metric" }, str(metric.metric_label), h("span", { class: "muted", text: str(metric.unit_label) })),
      svg,
      h("p", { class: "peer-read" }, h("strong", { class: signClass(str(metric.company?.display)).trim() || null, text: `${str(metric.company?.ticker)} ${str(metric.company?.display)}`.trim() }), str(metric.percentile_label)),
    );
  });
  return h("div", { class: "peers", "data-peer-strip": "" }, h("p", { class: "hint", text: str(record.industry_label) }), rows);
}

/** Look up a company's restatement ledger without starting a run, as of the drawer's date when one is set. */
async function onRestatements() {
  if (state.sample || !state.meta) return;
  const ticker = els.ticker.value.trim();
  if (!ticker) {
    showProblems([{ field: "ticker", message: "Enter a ticker, such as NVDA." }], "Check this field before looking up restatements:");
    return;
  }
  const asOf = els.asOf?.value.trim() ?? "";
  clearFieldErrors();
  stopWatching();
  const seq = ++state.viewSeq;
  state.runId = null;
  state.run = null;
  state.thesisId = null;
  markRecent();
  history.replaceState(null, "", `${location.pathname}${location.search}`);
  hideRunView();
  els.loading.textContent = `Reading every value ${ticker.toUpperCase()} reported for each period${asOf ? ` up to ${asOf}` : ""}…`;
  els.loading.hidden = false;
  els.restatements.disabled = true;
  try {
    const query = asOf ? `?as_of=${encodeURIComponent(asOf)}` : "";
    const ledger = await api(`/api/companies/${encodeURIComponent(ticker.toUpperCase())}/restatements${query}`);
    if (seq !== state.viewSeq) return;
    if (!Array.isArray(ledger.entries)) throw new ApiError("the answer has no list of restated periods", 0);
    renderLedgerView(ledger, "");
    focusResults();
  } catch (error) {
    if (seq !== state.viewSeq) return;
    els.loading.hidden = true;
    if (error.status === 422 && error.details.length) {
      showProblems(error.details, "The server refused the lookup:");
    } else if (error.status === 503) {
      showFormMessage(`The service is unavailable: ${error.message}`);
    } else {
      showLoadError(`The restatement ledger could not be loaded: ${error.message}.`, onRestatements);
    }
  } finally {
    els.restatements.disabled = state.sample;
  }
}

/** The ledger's own view: whose it is, as of when, the denominator, the tolerance and notes, then the table. */
function renderLedgerView(ledger, sampleNote) {
  renderCommandBar(null);
  els.loading.hidden = true;
  els.loadError.hidden = true;
  els.empty.hidden = true;
  els.runView.hidden = true;
  els.thesisView.hidden = true;
  els.inboxView.hidden = true;
  els.changesView.hidden = true;
  els.breakdownsView.hidden = true;
  els.figuresView.hidden = true;
  els.ledgerView.hidden = false;
  document.body.classList.add("has-run");
  const asOf = str(ledger.as_of);
  els.ledgerHead.replaceChildren(
    h(
      "div",
      { class: "run-head-main" },
      companyTitle({ name: str(ledger.company), cik: ledger.cik }, str(ledger.ticker)),
      h("p", { class: "run-meta", text: "Every period whose value differs between the company's filings, read from its XBRL facts with the date each became known. No run was started, no claim was tested and no model was asked." }),
      asOf
        ? h("p", { class: "as-of ledger-as-of", "data-ledger-as-of": asOf }, h("span", { class: "label", text: "As of: " }), `${dateLabel(asOf)}: only the facts filed by then were read.`)
        : h("p", { class: "as-of ledger-as-of", "data-ledger-as-of": "" }, h("span", { class: "label", text: "As of: " }), "no date asked: every fact the record holds was read."),
      sampleNote ? h("div", { class: "sample-note", "data-sample-note": "" }, h("p", null, h("span", { class: "label", text: "Sample: " }), sampleNote)) : "",
    ),
  );
  const metrics = list(ledger.metrics_checked);
  els.ledgerBody.replaceChildren(
    h(
      "section",
      { class: "block", "aria-labelledby": "ledger-title" },
      h("h3", { id: "ledger-title", class: "block-title", "data-code": "RST", text: "Restated values" }),
      h(
        "p",
        { class: "ledger-count", "data-ledger-count": "" },
        h("strong", { "data-ledger-field": "periods_restated", text: num(ledger.periods_restated) }),
        " of ",
        h("strong", { "data-ledger-field": "periods_checked", text: num(ledger.periods_checked) }),
        " periods reported by at least two filings changed value in a later filing.",
      ),
      metrics.length ? h("p", { class: "hint", "data-ledger-metrics": "" }, h("span", { class: "label", text: "Metrics compared: " }), metrics.join(", ")) : "",
      str(ledger.tolerance_note) ? h("p", { class: "hint", "data-ledger-tolerance": "" }, h("span", { class: "label", text: "Same value: " }), ledger.tolerance_note) : "",
      list(ledger.notes).length ? h("ul", { class: "plain-list ledger-notes" }, list(ledger.notes).map((note) => h("li", { text: str(note) }))) : "",
      restatementLedger(ledger),
    ),
  );
}
// ---------------------------------------------------------------- the specimen page

/** The specimen: the design system on made-up data, every component once, both themes by the toggle. */
function initSpecimen() {
  initTheme();
  document.addEventListener("keydown", onKey);
  els.keysButton?.addEventListener("click", openKeys);
  let data;
  try {
    data = JSON.parse(document.getElementById("specimen-data")?.textContent ?? "");
  } catch (error) {
    document.getElementById("specimen-root")?.replaceChildren(h("p", { class: "alert", text: `The specimen data could not be read: ${error.message}.` }));
    return;
  }
  // The note is the page's own run view, drawn by the same code from the made-up record.
  // ?only=<part> shows one part of the specimen (a capture is limited in height).
  const only = new URLSearchParams(location.search).get("only");
  if (only && /^[a-z0-9]{1,20}$/.test(only)) {
    for (const part of document.querySelectorAll(".spec-section[data-part]")) part.hidden = part.dataset.part !== only;
  }
  state.sample = true;
  state.sampleName = "specimen";
  state.meta = data.meta;
  state.sampleNote = str(data.note);
  state.runId = data.run.id;
  state.review = data.review && data.review.run_id === data.run.id ? data.review : null;
  state.comparison = data.comparison ?? null;
  renderRun(data.run);
  // Open the first claims, so the specimen shows findings with their quotes in the margin.
  for (const docket of [...document.querySelectorAll("#claim-list details.claim")].slice(0, 3)) docket.open = true;
  watchTimelineWidth();
  // The frame's own parts, drawn by the page's code from the same record: the centre pane's head for
  // the first claim, the tabs (the first one shown as selected), and the inspector reading its first finding.
  const shown = list(data.run.claims)[0];
  if (shown) document.getElementById("spec-sel-head")?.replaceChildren(...selectionHead(data.run, shown));
  const specTabs = TABS.map(tabButton);
  specTabs.forEach((tab, index) => {
    tab.removeAttribute("id");
    tab.setAttribute("aria-selected", String(index === 0));
    tab.disabled = index !== 0;
  });
  document.getElementById("spec-tabs")?.replaceChildren(...specTabs);
  const read = firstFinding(shown);
  document.getElementById("spec-inspector")?.replaceChildren(...((read && inspectFinding(read.id)) ?? [h("p", { class: "ins-none muted", text: "The made-up record's first claim has no finding to read." })]));

  const v14 = data.v14;
  // Version 14's parts are excerpts of the backend's example payloads (docs/examples/v14), in their real shapes.
  const v14run = v14.run ?? { claims: [] };
  document.getElementById("spec-compiled")?.replaceChildren(
    ...list(v14run.claims).map((claim) => (claim.computed ? computedTest(claim, v14run.company?.cik, readerDetails(v14run)) : compileNote(claim, readerDetails(v14run)))),
  );
  const tot = document.getElementById("spec-tot");
  if (tot) drawThesisOverTime(tot, v14.tot ?? v14run);
  document.getElementById("spec-asof-banner")?.replaceChildren(asOfBanner(v14.as_of));
  document.getElementById("spec-ledger")?.replaceChildren(restatementLedger(v14.restatements));
  document.getElementById("spec-peers")?.replaceChildren(peerStrip(v14.peers));

  const marks = document.getElementById("spec-marks");
  if (marks) {
    marks.replaceChildren(
      h("span", { class: "spec-label", text: "Verdict stamps" }),
      h("div", { class: "spec-row" }, Object.keys(VERDICT_GLYPH).map(verdictPill), h("span", { class: "pill review-pending", text: "not reviewed yet" })),
      h("span", { class: "spec-label", text: "Stances, decisions, the second model" }),
      h("div", { class: "spec-row" }, Object.keys(STANCE_MARK).map(stancePill), ["accepted", "rejected", "undecided"].map(decisionMark), meaningMark("passed"), meaningMark("partly")),
      h("span", { class: "spec-label", text: "Provenance and limits" }),
      h("div", { class: "spec-row" }, modelBadge(), ruleMark(), limitLine("span", "A limit of the record"), h("span", { class: "mark-reject" }, rejectGlyph(), " Refused"), h("span", { class: "page-tag", text: "Sample record" })),
      h("span", { class: "spec-label", text: "What changed between two filings" }),
      h("div", { class: "spec-row" }, Object.keys(CHANGE_MARK).map(changeMark), h("ins", { class: "seg seg-add", text: "added words" }), h("del", { class: "seg seg-del", text: "removed words" })),
      h("span", { class: "spec-label", text: "Run status (never a filled tag)" }),
      h("div", { class: "spec-row" }, ["complete", "running", "partial", "failed"].map((st) => h("span", { class: `status-word st-${st}` }, statusMark(st), ` ${capitalize(st)}`))),
      h("span", { class: "spec-label", text: "Test outcomes (version 14)" }),
      h("div", { class: "spec-row" }, Object.keys(TEST_MARK).map((k) => testOutcome(k, ""))),
      h("span", { class: "spec-label", text: "Numbers" }),
      h("div", { class: "spec-row" }, h("span", { class: "fig-value", text: "$96.22B" }), h("span", { class: "fig-value is-neg", text: "−$1.40B" }), h("span", { class: "fig-value is-missing", text: "not reported" }), h("code", { text: "0001045810-26-000082" })),
      h("span", { class: "spec-label", text: "Controls" }),
      h(
        "div",
        { class: "spec-row" },
        h("button", { type: "button", class: "primary", text: "Test the thesis" }),
        h("button", { type: "button", class: "secondary", text: "Load example" }),
        h("button", { type: "button", class: "secondary small", text: "Accept" }),
        h("button", { type: "button", class: "primary", disabled: true, text: "Disabled" }),
        h("a", { href: "#spec-marks", text: "A link" }),
        h("kbd", { text: "j" }),
      ),
    );
  }
  const swatches = document.getElementById("spec-swatches");
  if (swatches) {
    const tokens = ["--bg", "--surface", "--surface-2", "--ink", "--ink-2", "--line", "--accent", "--support", "--challenge", "--neutral", "--limit", "--model", "--reject", "--rule", "--change", "--neg", "--mark-bg"];
    const paint = () => {
      const styles = getComputedStyle(document.documentElement);
      swatches.replaceChildren(
        ...tokens.map((name) =>
          h("div", { class: "swatch" }, h("div", { class: "swatch-chip", style: `background: var(${name})` }), h("p", null, h("strong", { text: name })), h("p", { class: "muted", text: styles.getPropertyValue(name).trim() })),
        ),
      );
    };
    paint();
    els.themeToggle?.addEventListener("click", () => requestAnimationFrame(paint));
    document.addEventListener("keydown", (event) => {
      if (event.key === "t") requestAnimationFrame(paint);
    });
  }
}

// ---------------------------------------------------------------- the standing watch (version 13)
//
// Watches, the inbox and the watcher's health, drawn from /api/watch, /api/inbox and
// /api/watch/health, with the words of /api/watch/meta. Every headline, count, label and
// reason is the backend's; the page orders nothing (the inbox comes unread first, as the
// API sends it) and counts nothing but the folded items it draws on one line.

/** The recorded inbox (?sample=inbox): the watch's example payloads, copied unedited by `make sample-inbox`. */
const INBOX_SAMPLES = { inbox: "sample-inbox.json", "inbox-page-2": "sample-inbox-page-2.json" };
const INBOX_SAMPLE_NOTE =
  "The standing watch's example payloads (docs/examples/v13), written by `make watch-examples` from an offline scenario: a made-up EDGAR index of NVIDIA filings, a fake clock that starts at 18 Nov 2026 09:00 UTC, and scripted verdicts (no model, no cassette). They are copied unedited. In sample mode the page sends nothing: no watch changes, no run starts, nothing is marked read.";
const INBOX_KIND = { not_relevant: "○", waiting: "◇", running: "◌", moved: "◆", nothing_moved: "·", failed: "▲" };
const WATCH_POLL_MS = 60000;

function kindLabel(kind) {
  return str(state.watchMeta?.kind_labels?.[kind]) || String(kind ?? "");
}

function policyLabels() {
  const labels = state.watchMeta?.policy_labels;
  return labels && typeof labels === "object" ? labels : { ask: "Ask before running", auto: "Run at once" };
}

/** A refusal in the server's words: the 422's fields, else its one sentence. */
function refusal(error) {
  if (error.status === 422 && error.details.length) {
    return `${error.message}: ${error.details.map((d) => `${str(d.field) || "request"}: ${str(d.message)}`).join("; ")}`;
  }
  return error.message;
}

function setMessage(node, text, kind = "error") {
  if (!node) return;
  node.textContent = text;
  node.className = `watch-message ${kind === "error" ? "is-error" : "is-ok"}`;
  node.hidden = !text;
}

// ---- health

/** The watcher's health, in the bar: alive or not, its last cycle, the queue and the runs waiting. */
function renderHealth() {
  const node = els.watchHealth;
  const health = state.health;
  if (!node) return;
  const inboxSample = state.sample && Object.hasOwn(INBOX_SAMPLES, state.sampleName);
  if (!health || (state.sample && !inboxSample)) {
    node.hidden = true;
    return;
  }
  const alive = health.alive === true;
  node.hidden = false;
  node.className = `watch-health ${alive ? "is-alive" : "is-down"}`;
  node.dataset.alive = String(alive);
  node.title = [str(health.note), health.last_cycle_at ? `Last cycle ${utc(health.last_cycle_at)}.` : ""].filter(Boolean).join(" ");
  node.replaceChildren(
    h("span", { class: "glyph health-dot", "aria-hidden": "true", text: alive ? "●" : "○" }),
    h("span", { class: "health-word", text: alive ? "Watch alive" : "Watch not running" }),
    h(
      "span",
      { class: "health-detail" },
      // The time of day only; the whole date and time are in the title, with the watcher's note.
      health.last_cycle_at ? ` · last cycle ${utc(health.last_cycle_at).slice(11)}` : "",
      " · queue ",
      h("span", { "data-health": "queue_depth", text: num(health.queue_depth) }),
      " · ",
      h("span", { "data-health": "waiting_runs", text: num(health.waiting_runs) }),
      " waiting",
    ),
  );
  renderWatchDown();
}

/** Near every watch control: when the watcher is not alive, nothing new will be noticed until it runs. */
function watchDownLine() {
  const health = state.health;
  if (!health || health.alive === true) return null;
  return limitLine(
    "p",
    h("strong", { text: "The watcher is not running." }),
    " No new filing will be noticed, and no watched thesis run, until it runs. ",
    str(health.note),
  );
}

function renderWatchDown() {
  const line = watchDownLine();
  if (els.watchDown) {
    els.watchDown.hidden = !line;
    els.watchDown.replaceChildren(...(line ? [line] : []));
  }
  const card = els.thesisWatch?.querySelector(".watch-down-slot");
  if (card) card.replaceChildren(...(line ? [line] : []));
}

// ---- the unread count

function renderInboxCount() {
  const node = els.inboxCount;
  if (!node) return;
  const unread = state.inboxUnread;
  node.hidden = !Number.isFinite(unread);
  node.textContent = Number.isFinite(unread) ? num(unread) : "";
  node.dataset.unread = Number.isFinite(unread) ? String(unread) : "";
  els.inboxButton?.setAttribute("aria-label", Number.isFinite(unread) ? `Inbox, ${num(unread)} unread` : "Inbox");
}

/** Health, watches, the words and the unread count, from the server. A 404 means a server without the watch: it stays hidden. */
async function refreshWatchState() {
  if (state.sample) return;
  try {
    if (!state.watchMeta) state.watchMeta = await api("/api/watch/meta");
  } catch (error) {
    if (error.status === 404) {
      els.inboxButton.hidden = true;
      return;
    }
  }
  const [health, watches, inbox] = await Promise.allSettled([api("/api/watch/health"), api("/api/watch"), api("/api/inbox?limit=1")]);
  state.health = health.status === "fulfilled" ? health.value : null;
  if (watches.status === "fulfilled") {
    state.watches = new Map(list(watches.value.watches).map((w) => [w.thesis_id, w]));
    state.watchesLoaded = true;
  }
  if (inbox.status === "fulfilled" && Number.isFinite(inbox.value.unread)) state.inboxUnread = inbox.value.unread;
  renderHealth();
  renderInboxCount();
  // Each saved thesis carries its own watch (GET /api/theses): the list is read again, not joined here.
  if (state.theses.size) refreshTheses();
  if (state.thesisId && !els.thesisView.hidden) renderThesisWatch(state.thesisId);
}

function startWatchPolling() {
  refreshWatchState();
  setInterval(() => {
    if (!document.hidden) refreshWatchState();
  }, WATCH_POLL_MS);
}

// ---- a watch: put on, policy, take off

/**
 * The watch of one saved thesis: its policy (changeable), the last and next check, the last
 * errors and its unread items; or, when it is not watched, a control to put it on watch.
 */
function watchCard(thesisId, watch, sample = state.sample) {
  const labels = policyLabels();
  const current = watch ? str(watch.policy) : str(state.watchMeta?.default_policy) || "ask";
  const message = h("p", { class: "watch-message", role: "status", hidden: true });
  const name = `policy-${thesisId}`;
  const choice = h(
    "fieldset",
    { class: "watch-policy" },
    h("legend", { text: watch ? "When a new filing bears on a claim" : "Put it on watch: when a new filing bears on a claim" }),
    ...Object.entries(labels).map(([value, label]) =>
      h(
        "label",
        { class: "watch-choice" },
        h("input", {
          type: "radio",
          name,
          value,
          checked: value === current,
          disabled: sample,
          "data-policy": value,
          onchange: watch ? () => putWatch(thesisId, value, message) : null,
        }),
        ` ${label}`,
        value === "auto" ? h("span", { class: "hint", text: " (each run uses the model, within the daily cap)" }) : "",
      ),
    ),
  );
  const parts = [h("div", { class: "watch-down-slot" }, ...(watchDownLine() ? [watchDownLine()] : []))];
  if (watch) {
    const check = (iso) => (iso ? utc(iso) : str(watch.next_check_note) || "—");
    parts.push(
      h(
        "p",
        { class: "watch-state" },
        h("span", { class: "watch-on", text: "On watch" }),
        ` since ${utc(watch.watching_since)} · `,
        h("strong", { "data-watch": "policy_label", text: str(watch.policy_label) || labels[watch.policy] || "" }),
      ),
      h(
        "dl",
        { class: "watch-facts" },
        h("div", null, h("dt", { text: "Last check" }), h("dd", { "data-watch": "last_check_at", text: check(watch.last_check_at) })),
        h("div", null, h("dt", { text: "Next check" }), h("dd", { "data-watch": "next_check_at", text: check(watch.next_check_at) })),
        h("div", null, h("dt", { text: "Last error" }), h("dd", { "data-watch": "last_error", class: watch.last_error ? "is-error" : null, text: str(watch.last_error) || "None" })),
        str(watch.last_job_error) ? h("div", null, h("dt", { text: "Last failed job" }), h("dd", { "data-watch": "last_job_error", class: "is-error", text: watch.last_job_error })) : "",
        h(
          "div",
          null,
          h("dt", { text: "Inbox" }),
          h(
            "dd",
            null,
            h("span", { "data-watch": "unread", text: num(watch.unread) }),
            " unread · ",
            h("span", { "data-watch": "waiting_runs", text: num(watch.waiting_runs) }),
            ` ${unit(watch.waiting_runs, "run", "runs")} waiting · `,
            h("a", { href: "#inbox", onclick: (event) => { event.preventDefault(); openInbox({ thesisId }); }, text: "open its inbox" }),
          ),
        ),
      ),
      choice,
      h(
        "div",
        { class: "watch-actions" },
        h("button", { type: "button", class: "secondary small", "data-unwatch": thesisId, disabled: sample, onclick: () => deleteWatch(thesisId, message), text: "Take it off watch" }),
      ),
    );
  } else {
    parts.push(
      h("p", { class: "watch-state muted", text: "Not on watch. On watch, the watcher reads the company's filing index every few minutes and says here and in the inbox what each new filing means for these claims." }),
      choice,
      h(
        "div",
        { class: "watch-actions" },
        h("button", {
          type: "button",
          class: "primary small",
          "data-watch-put": thesisId,
          disabled: sample,
          onclick: () => putWatch(thesisId, choice.querySelector("input:checked")?.value ?? current, message),
          text: "Put it on watch",
        }),
      ),
    );
  }
  if (sample) parts.push(h("span", { class: "page-tag inline-tag", text: "sample: nothing is saved" }));
  parts.push(message);
  return h("div", { class: watch ? "watch-card is-on" : "watch-card", "data-watch-thesis": thesisId }, ...parts);
}

/** Put a thesis on watch, or change its policy. 201 or 200 answer with the watch. */
async function putWatch(thesisId, policy, message) {
  if (state.sample) return;
  setMessage(message, "Saving…", "ok");
  try {
    const answer = await api(`/api/theses/${encodeURIComponent(thesisId)}/watch`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ policy }),
    });
    if (!answer.watch || answer.watch.thesis_id !== thesisId) throw new ApiError("the server did not return this thesis's watch", 0);
    state.watches.set(thesisId, answer.watch);
    rerenderWatch(thesisId, answer.created ? `On watch: ${str(answer.watch.policy_label)}.` : `Policy changed: ${str(answer.watch.policy_label)}.`);
  } catch (error) {
    const reason =
      error.status === 404 ? "no saved thesis with that id exists" : error.status === 503 ? `${error.message}. Nothing was saved` : refusal(error);
    setMessage(message, `The watch could not be saved: ${reason}.`);
    resetPolicy(thesisId);
  }
}

async function deleteWatch(thesisId, message) {
  if (state.sample) return;
  try {
    const answer = await api(`/api/theses/${encodeURIComponent(thesisId)}/watch`, { method: "DELETE" });
    if (answer.watching !== false) throw new ApiError("the server did not say the watch ended", 0);
    state.watches.delete(thesisId);
    rerenderWatch(thesisId, "Taken off watch. Its inbox items stay.");
  } catch (error) {
    if (error.status === 409) {
      // Not watched any more (taken off elsewhere): show it as the server has it.
      state.watches.delete(thesisId);
      rerenderWatch(thesisId, `${error.message}.`);
      return;
    }
    setMessage(message, `The watch could not be ended: ${error.status === 404 ? "no saved thesis with that id exists" : refusal(error)}.`);
  }
}

/** A refused policy change leaves the radio on the policy the server has. */
function resetPolicy(thesisId) {
  const watch = state.watches.get(thesisId);
  if (!watch) return;
  for (const card of document.querySelectorAll(`[data-watch-thesis="${CSS.escape(thesisId)}"]`)) {
    for (const input of card.querySelectorAll("input[data-policy]")) input.checked = input.value === watch.policy;
  }
}

/** Draw a thesis's watch again wherever it is on screen, with a message under it. */
function rerenderWatch(thesisId, note) {
  if (state.thesisId === thesisId && !els.thesisView.hidden) renderThesisWatch(thesisId, note);
  if (!els.inboxView.hidden) renderWatches(note, thesisId);
  refreshWatchState();
}

function renderThesisWatch(thesisId, note = "") {
  if (!els.thesisWatchSection) return;
  if (!state.watchMeta || !state.watchesLoaded) {
    els.thesisWatchSection.hidden = true;
    return;
  }
  els.thesisWatchSection.hidden = false;
  const card = watchCard(thesisId, state.watches.get(thesisId) ?? null);
  els.thesisWatch.replaceChildren(card);
  if (note) setMessage(card.querySelector(".watch-message"), note, "ok");
}

/** Every watch, oldest first as the API lists them, in the inbox view. */
function renderWatches(note = "", noteThesis = "") {
  const watches = [...state.watches.values()];
  // A note about a watch no longer listed (taken off) goes above the list.
  if (note && noteThesis && !state.watches.has(noteThesis)) setMessage(els.inboxMessage, note, "ok");
  if (watches.length === 0) {
    els.watches.replaceChildren(
      h("p", { class: "muted", "data-empty": "watches", text: "No thesis is on watch. Open a saved thesis and put it on watch; its new filings then arrive here." }),
    );
    return;
  }
  els.watches.replaceChildren(
    h(
      "ul",
      { class: "watch-list" },
      watches.map((watch) =>
        h(
          "li",
          { "data-watch-id": watch.thesis_id },
          h(
            "p",
            { class: "watch-name" },
            h("strong", { text: str(watch.thesis_name) }),
            " · ",
            h("span", { class: "ticker-chip", text: str(watch.ticker) }),
            ` ${str(watch.company_name)}`,
          ),
          watchCard(watch.thesis_id, watch),
        ),
      ),
    ),
  );
  if (note && noteThesis) {
    const card = els.watches.querySelector(`[data-watch-thesis="${CSS.escape(noteThesis)}"] .watch-message`);
    setMessage(card, note, "ok");
  }
}

// ---- the inbox

/** Open the inbox view: from the bar, the `i` key, #inbox, or a thesis's "open its inbox". */
function openInbox({ thesisId = null, offset = 0 } = {}) {
  closeDrawer(false);
  if (state.sample) {
    if (Object.hasOwn(INBOX_SAMPLES, state.sampleName)) {
      showInboxView();
      els.inboxItems.querySelector("article")?.focus?.({ preventScroll: true });
      return;
    }
    showInboxView();
    renderInboxHead(null);
    els.watchesSection.hidden = true;
    els.inboxItems.replaceChildren();
    els.inboxCollapsed.replaceChildren();
    els.inboxPaging.replaceChildren();
    setMessage(els.inboxMessage, "", "ok");
    els.inboxItems.append(
      h("li", { class: "muted", "data-empty": "sample" }, "This sample holds no inbox. ", h("a", { href: "?sample=inbox", text: "See the recorded inbox of the standing watch" }), "."),
    );
    return;
  }
  state.inboxThesis = thesisId;
  state.inboxOffsets = [];
  loadInbox(offset);
}

function showInboxView() {
  stopWatching();
  state.viewSeq += 1;
  hideRunView();
  els.loading.hidden = true;
  els.inboxView.hidden = false;
  document.body.classList.add("has-run");
  els.watchesSection.hidden = false;
  els.inboxButton?.setAttribute("aria-expanded", "true");
  if (!state.sample) history.replaceState(null, "", "#inbox");
}

async function loadInbox(offset) {
  showInboxView();
  const seq = ++state.inboxSeq;
  setMessage(els.inboxMessage, "Loading the inbox…", "ok");
  const query = new URLSearchParams({ offset: String(offset) });
  if (state.inboxThesis) query.set("thesis_id", state.inboxThesis);
  try {
    if (!state.watchMeta) state.watchMeta = await api("/api/watch/meta");
    const [page, watches, health] = await Promise.all([api(`/api/inbox?${query}`), api("/api/watch"), api("/api/watch/health").catch(() => null)]);
    if (seq !== state.inboxSeq) return;
    state.watches = new Map(list(watches.watches).map((w) => [w.thesis_id, w]));
    state.watchesLoaded = true;
    state.health = health;
    renderHealth();
    setMessage(els.inboxMessage, "", "ok");
    renderInbox(page);
  } catch (error) {
    if (seq !== state.inboxSeq) return;
    renderInboxHead(null);
    els.inboxItems.replaceChildren();
    els.inboxCollapsed.replaceChildren();
    els.inboxPaging.replaceChildren(h("button", { type: "button", class: "secondary small", onclick: () => loadInbox(offset), text: "Try again" }));
    const reason = error.status === 404 ? "this server has no inbox (it is older than version 13)" : refusal(error);
    setMessage(els.inboxMessage, `The inbox could not be loaded: ${reason}.`);
  }
}

function renderInboxHead(page) {
  const thesis = state.inboxThesis ? state.watches.get(state.inboxThesis) : null;
  els.inboxHead.replaceChildren(
    h(
      "div",
      { class: "run-head-main" },
      h("p", { class: "company-name", text: "Inbox" }),
      h(
        "p",
        { class: "run-meta" },
        page
          ? [
              h("span", { class: "count-value", "data-inbox": "unread", text: num(page.unread) }),
              " unread of ",
              h("span", { class: "count-value", "data-inbox": "total", text: num(page.total) }),
              ` ${unit(page.total, "item", "items")}`,
              thesis ? ` for “${str(thesis.thesis_name)}”` : state.inboxThesis ? " for one thesis" : "",
              ". Unread first, then newest first.",
            ]
          : "The standing watch's new filings, each with what it means for the watched theses.",
        state.inboxThesis && !state.sample ? [" ", h("a", { href: "#inbox", onclick: (event) => { event.preventDefault(); openInbox(); }, text: "Show every thesis" })] : "",
      ),
      sampleNoteLine(),
    ),
  );
}

/** One page of the inbox exactly as the API ordered it; the folded kinds go on one line under it. */
function renderInbox(page) {
  if (!page || !Array.isArray(page.items)) throw new ApiError("the inbox page has no items", 0);
  state.inboxPage = page;
  if (Number.isFinite(page.unread) && !state.inboxThesis) state.inboxUnread = page.unread;
  renderInboxCount();
  renderInboxHead(page);
  renderWatches();
  renderWatchDown();
  const open = page.items.filter((item) => item.collapsed !== true);
  const folded = page.items.filter((item) => item.collapsed === true);
  els.inboxItems.replaceChildren(...open.map((item) => h("li", null, inboxItem(item))));
  if (page.items.length === 0) {
    els.inboxItems.append(h("li", { class: "muted", "data-empty": "inbox", text: page.offset > 0 ? "No items on this page." : "The inbox is empty: no watched thesis has a new filing yet." }));
  }
  renderFolded(folded, page);
  renderPaging(page);
}

/**
 * The folded items ("seen, not relevant"): one line with how many the inbox holds, as the backend
 * counts them (`folded`, of the whole inbox or of the thesis, whichever page is drawn), opening to
 * the headline and filing of each one on this page. A page that draws none says so.
 */
function renderFolded(folded, page) {
  const count = Number.isFinite(page?.folded) ? page.folded : null;
  if (folded.length === 0 && !(count > 0)) {
    els.inboxCollapsed.replaceChildren();
    return;
  }
  const label = kindLabel("not_relevant");
  const summary = [
    h("span", { class: "glyph", "aria-hidden": "true", text: INBOX_KIND.not_relevant }),
    ` ${label}: `,
    count === null ? "" : [h("span", { class: "count-value", "data-folded": "count", text: num(count) }), ` ${unit(count, "filing", "filings")} in ${state.inboxThesis ? "this thesis's" : "the"} inbox`],
    folded.length ? (count === null ? "on this page" : ", these on this page") : count === null ? "" : ", none on this page",
    h("span", { class: "fold-hint", text: ". No run was needed." }),
  ];
  if (folded.length === 0) {
    els.inboxCollapsed.replaceChildren(h("p", { class: "inbox-folded is-empty", "data-folded-count": String(count) }, ...summary));
    return;
  }
  els.inboxCollapsed.replaceChildren(
    h(
      "details",
      { class: "inbox-folded", "data-folded-count": count === null ? "" : String(count) },
      h("summary", null, ...summary),
      h("ol", { class: "inbox-items is-folded" }, folded.map((item) => h("li", null, inboxItem(item)))),
    ),
  );
}

function renderPaging(page) {
  const parts = [];
  if (state.sample) {
    if (page.offset > 0) parts.push(h("a", { class: "tool", href: "?sample=inbox", "data-page": "first", text: "First page" }));
  } else {
    if (state.inboxOffsets.length) {
      parts.push(
        h("button", {
          type: "button",
          class: "secondary small",
          "data-page": "newer",
          onclick: () => loadInbox(state.inboxOffsets.pop()),
          text: "Newer items",
        }),
      );
    }
    if (Number.isInteger(page.next_offset)) {
      parts.push(
        h("button", {
          type: "button",
          class: "secondary small",
          "data-page": "older",
          onclick: () => {
            state.inboxOffsets.push(page.offset);
            loadInbox(page.next_offset);
          },
          text: "Older items",
        }),
      );
    }
    const unreadIds = page.items.filter((item) => !item.read_at).map((item) => item.id);
    if (unreadIds.length) parts.push(h("button", { type: "button", class: "secondary small", "data-mark-page": "", onclick: () => markRead(unreadIds, true), text: "Mark this page read" }));
  }
  if (Number.isInteger(page.next_offset)) parts.push(h("span", { class: "hint", "data-next-offset": String(page.next_offset), text: "More items are on the next page." }));
  els.inboxPaging.replaceChildren(...parts);
}

/** One inbox item: its kind, headline, the filing, the triage per claim, the run and what moved. */
function inboxItem(item) {
  const kind = token(item.kind, INBOX_KIND);
  const unread = !item.read_at;
  const message = h("p", { class: "watch-message", role: "status", hidden: true });
  const node = h(
    "article",
    { class: `inbox-item k-${kind}${unread ? " is-unread" : ""}`, "data-item-id": str(item.id), "data-kind": kind, "data-unread": String(unread), tabindex: "-1" },
    h(
      "header",
      { class: "inbox-item-head" },
      h("span", { class: `kind-tag k-${kind}`, "data-kind-label": "" }, h("span", { class: "glyph", "aria-hidden": "true", text: INBOX_KIND[kind] ?? "·" }), ` ${kindLabel(item.kind)}`),
      unread ? h("span", { class: "unread-mark", text: "Unread" }) : h("span", { class: "read-mark", text: `Read ${utc(item.read_at)}` }),
      h("span", { class: "inbox-when", text: `${str(item.ticker)} · ${str(item.thesis_name)} · ${utc(item.updated_at)}` }),
    ),
    h("p", { class: "inbox-headline", text: str(item.headline) }),
    item.collapsed ? "" : inboxFiling(item.filing),
    item.collapsed ? h("p", { class: "inbox-filing-line" }, externalLink(item.filing?.url, str(item.filing?.label) || "the filing")) : inboxTriage(item.triage),
    inboxRun(item, message),
    inboxMoved(item.moved),
    h(
      "div",
      { class: "inbox-actions" },
      h("button", {
        type: "button",
        class: "linklike",
        "data-mark": unread ? "read" : "unread",
        disabled: state.sample,
        onclick: () => markRead([item.id], unread),
        text: unread ? "Mark read" : "Mark unread",
      }),
    ),
    message,
  );
  return node;
}

/** The filing that arrived: form and accession linked to sec.gov, its dates and, for an 8-K, its items. */
function inboxFiling(filing) {
  if (!filing) return "";
  const items = list(filing.items);
  return h(
    "div",
    { class: "inbox-filing" },
    h(
      "p",
      null,
      externalLink(filing.url, [h("strong", { text: str(filing.form) }), ` ${str(filing.accession)}`]),
      ` · filed ${str(filing.filed_date)}`,
      str(filing.report_date) ? ` · report date ${filing.report_date}` : "",
    ),
    items.length
      ? h(
          "ul",
          { class: "inbox-filing-items" },
          items.map((it) => h("li", { "data-item-number": str(it.number) }, h("strong", { text: `Item ${str(it.number)}` }), ` ${str(it.title)}`, str(it.category) ? h("span", { class: "event-cat", text: ` (${it.category})` }) : "")),
        )
      : "",
  );
}

/** Does it bear on the thesis, and why: the rules, then each claim with its reasons and paragraphs. */
function inboxTriage(triage) {
  if (!triage) return "";
  const rules = list(triage.rules);
  const ruleLabels = state.watchMeta?.rule_labels ?? {};
  return h(
    "div",
    { class: "inbox-triage" },
    h(
      "p",
      { class: "triage-summary" },
      ruleMark("By rule, no model"),
      " ",
      str(triage.summary),
      rules.length ? h("span", { class: "triage-rules" }, " · ", rules.map((r) => str(ruleLabels[r]) || r).join(", ")) : "",
    ),
    h(
      "ul",
      { class: "triage-claims" },
      list(triage.claims).map((claim) =>
        h(
          "li",
          { "data-claim-id": str(claim.claim_id), "data-bears": String(claim.bears === true) },
          h(
            "p",
            { class: "triage-claim" },
            h("span", { class: "claim-id", text: str(claim.claim_id) }),
            " ",
            str(claim.claim),
            h("span", { class: claim.bears ? "bears is-yes" : "bears is-no", text: claim.bears ? " bears on it" : " does not bear on it" }),
          ),
          list(claim.reasons).length ? h("ul", { class: "triage-reasons" }, list(claim.reasons).map((r) => h("li", { text: String(r) }))) : "",
          list(claim.paragraphs).length
            ? h(
                "ul",
                { class: "triage-paragraphs" },
                list(claim.paragraphs).map((p) =>
                  h(
                    "li",
                    null,
                    // The record's own kind; "changed" has no mark of its own, so it keeps its word.
                    Object.hasOwn(CHANGE_MARK, p.kind) ? changeMark(p.kind) : h("span", { class: "chg-mark c-reworded" }, h("span", { class: "chg-label", text: capitalize(str(p.kind)) })),
                    ` ${str(p.item)}`,
                    h("blockquote", { class: "triage-paragraph", text: str(p.text) }),
                    list(p.matched_terms).length ? h("span", { class: "hint", text: `Shared words: ${list(p.matched_terms).join(", ")} · ` }) : "",
                    externalLink(p.link, "Open in the filing, at this paragraph"),
                  ),
                ),
              )
            : "",
        ),
      ),
    ),
    list(triage.notes).length ? h("ul", { class: "triage-notes" }, list(triage.notes).map((n) => h("li", { text: String(n) }))) : "",
  );
}

/** The run the filing caused: waiting (with the button), under way, finished or failed. */
function inboxRun(item, message) {
  const run = item.run;
  if (!run) return item.error ? limitLine("p", str(item.error)) : "";
  const openRun = run.run_id
    ? h("button", { type: "button", class: "secondary small", "data-open-run": run.run_id, onclick: () => openItemRun(item, message), text: run.state === "running" ? "Open the run under way" : "Open the run in the note" })
    : "";
  const parts = [];
  if (run.state === "waiting") {
    parts.push(
      h("p", { class: "waiting-reason", text: str(run.waiting_reason) }),
      h("button", { type: "button", class: "primary small", "data-run-now": str(item.id), onclick: (event) => runNow(item, event.currentTarget, message), text: "Run now (uses the model)" }),
    );
  } else {
    parts.push(
      h(
        "p",
        { class: "inbox-run-line" },
        "Run ",
        h("code", { text: str(run.run_id) || "—" }),
        run.status ? [" · ", h("span", { class: `status-word st-${token(run.status, STATUS_GLYPH)}` }, statusMark(run.status), ` ${capitalize(run.status)}`)] : run.state === "running" ? " · under way" : "",
        str(run.started_by) ? ` · started by ${run.started_by === "owner" ? "you, from the inbox" : "the watch"}` : "",
        " ",
        openRun,
      ),
    );
  }
  if (item.error) parts.push(limitLine("p", str(item.error)));
  return h("div", { class: `inbox-run r-${token(run.state, { waiting: 1, running: 1, finished: 1, failed: 1 })}` }, ...parts);
}

/** What the run changed: the record's line, the verdicts that moved, new cautions, notes and 8-Ks; the comparison one click away. */
function inboxMoved(moved) {
  if (!moved) return "";
  const parts = [h("p", { class: "moved-line", "data-moved": String(moved.moved === true), text: str(moved.line) })];
  // Version 14: how many claims moved, in the backend's words ("" for a thesis's first run).
  if (str(moved.claims_line)) parts.push(h("p", { class: "moved-claims-line", "data-claims-line": "", text: moved.claims_line }));
  // Version 14: each computed test, the same in both runs, whose outcome changed with the facts the later run read.
  const computed = list(moved.computed);
  if (computed.length) {
    parts.push(
      h(
        "ul",
        { class: "moved-computed", "aria-label": "Computed tests whose outcome changed" },
        computed.map((change) =>
          h(
            "li",
            { "data-moved-computed": str(change.claim) },
            h("span", { class: "moved-claim", text: str(change.claim) }),
            " ",
            str(change.canonical) ? h("code", { text: change.canonical }) : "",
            " ",
            testOutcome(change.before, change.before_label),
            h("span", { class: "moved-arrow", "aria-label": "became", text: " → " }),
            testOutcome(change.after, change.after_label),
          ),
        ),
      ),
    );
  }
  const verdicts = list(moved.verdicts);
  if (verdicts.length) {
    parts.push(h("ul", { class: "moved-verdicts" }, verdicts.map((v) => h("li", null, h("span", { class: "moved-claim", text: str(v.claim) }), " ", verdictPill(v.before), h("span", { class: "moved-arrow", "aria-label": "became", text: " → " }), verdictPill(v.after)))));
  }
  for (const caution of list(moved.new_cautions)) parts.push(limitLine("p", h("strong", { text: "New caution: " }), `${str(caution.claim)} `, str(caution.text)));
  for (const note of list(moved.new_notes)) parts.push(h("p", { class: "moved-note" }, h("strong", { text: "New note on the 8-Ks: " }), `${str(note.claim)} `, str(note.text)));
  if (list(moved.new_events).length) {
    parts.push(h("p", { class: "moved-events" }, h("strong", { text: "New on the time line: " }), ...list(moved.new_events).flatMap((e, i) => [i ? "; " : "", externalLink(e.url, str(e.label) || str(e.accession)), list(e.items).length ? ` (Items ${list(e.items).join(", ")})` : ""])));
  }
  if (list(moved.claims).length) {
    const body = h("div", { class: "moved-compare-body" });
    parts.push(
      h(
        "details",
        { class: "moved-compare", ontoggle: (event) => event.currentTarget.open && !body.childElementCount && renderComparison(body, moved, null) },
        h("summary", { text: "Compare with the previous run, claim by claim" }),
        body,
      ),
    );
  }
  return h("div", { class: "inbox-moved" }, ...parts);
}

/** Open the run an item made in the note, with its comparison (the item's own) under the head. */
function openItemRun(item, message) {
  const runId = item.run?.run_id;
  if (!runId) return;
  if (state.sample) {
    setMessage(message, `Run ${runId} is not part of this sample: the scenario's runs are not recorded beside it.`);
    return;
  }
  state.itemComparison = item.moved && item.moved.later_run_id === runId ? item.moved : null;
  watchRun(runId);
}

/** Start a waiting run (it uses the model). 202: the run; 409: nothing waits any more, so the item is read again. */
async function runNow(item, button, message) {
  if (state.sample) {
    setMessage(message, "Sample: nothing is started. On a live inbox this starts the run, which uses the model.");
    return;
  }
  button.disabled = true;
  setMessage(message, "Starting the run…", "ok");
  try {
    const started = await api(`/api/inbox/${encodeURIComponent(item.id)}/run`, { method: "POST" });
    if (typeof started.id !== "string" || !started.id) throw new ApiError("the server did not return a run id", 0);
    await reloadItem(item.id, `Run ${started.id} started.`);
  } catch (error) {
    if (error.status === 409) {
      await reloadItem(item.id, `The run was not started: ${error.message}.`, true);
      return;
    }
    button.disabled = false;
    setMessage(message, `The run could not be started: ${error.status === 404 ? "this inbox item no longer exists" : refusal(error)}.`);
  }
}

/** Read one item again (after its run started, or after a 409) and draw it in its place. */
async function reloadItem(itemId, note, isError = false) {
  const slot = [...document.querySelectorAll("article.inbox-item")].find((node) => node.dataset.itemId === itemId);
  try {
    const fresh = await api(`/api/inbox/${encodeURIComponent(itemId)}`);
    const node = inboxItem(fresh);
    slot?.replaceWith(node);
    setMessage(node.querySelector(".watch-message"), note, isError ? "error" : "ok");
  } catch (error) {
    setMessage(slot?.querySelector(".watch-message"), `${note} The item could not be read again: ${refusal(error)}.`);
  }
  refreshWatchState();
}

/** Mark items read (or unread again); the answer carries the inbox's unread count. */
async function markRead(ids, read) {
  if (state.sample || ids.length === 0) return;
  try {
    const answer = await api("/api/inbox/read", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ids, read }) });
    if (Number.isFinite(answer.unread)) state.inboxUnread = answer.unread;
    renderInboxCount();
    loadInbox(state.inboxPage?.offset ?? 0);
  } catch (error) {
    setMessage(els.inboxMessage, `Could not mark ${ids.length === 1 ? "the item" : "the items"} ${read ? "read" : "unread"}: ${refusal(error)}.`);
  }
}

/** ?sample=inbox: the example payloads, drawn as a live inbox would be, with nothing sent. */
async function loadInboxSample(name) {
  const [page, watches, health, watchMeta] = await Promise.all([
    api(INBOX_SAMPLES[name], { cache: "no-store" }),
    api("sample-inbox-watches.json", { cache: "no-store" }),
    api("sample-inbox-health.json", { cache: "no-store" }),
    api("sample-inbox-meta.json", { cache: "no-store" }),
  ]);
  applyMeta(await api("/api/meta"), { sample: true });
  state.watchMeta = watchMeta;
  state.watches = new Map(list(watches.watches).map((w) => [w.thesis_id, w]));
  state.watchesLoaded = true;
  state.health = health;
  state.sampleNote = INBOX_SAMPLE_NOTE;
  els.formNote.textContent = `Sample mode: ${INBOX_SAMPLE_NOTE}`;
  showInboxView();
  renderHealth();
  renderInbox(page);
}

// ---------------------------------------------------------------- the workspace: the rail's selection, the tabs, the inspector
//
// A run fills the window: the claims are listed once, in the rail; what the rail has selected
// (the whole thesis, or one claim) is shown in the centre pane under tabs; and whatever is
// picked there (a finding, a computed test, an 8-K, a figure) is read in the inspector. All of
// it is navigation: which of the record's items are on screen. Nothing here computes a result.
// The specimen page shows every part at once and has no selection.

/**
 * The centre pane's tabs, in order; the first is where a run opens. A new tab is one entry here
 * and one `.tabpanel[data-tab]` in index.html (with `data-scope`: "thesis", "claim" or "both").
 */
const TABS = [
  // The analysis leads when the record has one; a record made before runs kept one opens on the Overview.
  { id: "analysis", label: "Analysis", when: (run) => hasAnalysis(run) },
  { id: "overview", label: "Overview" },
  { id: "evidence", label: "Evidence" },
  { id: "time", label: "Over time" },
  { id: "events", label: "Events" },
  { id: "figures", label: "Figures" },
  { id: "method", label: "Method" },
  { id: "limits", label: "Limits" },
];

/** The tabs this run has, in order. */
function tabsOn(run = state.run) {
  return TABS.filter((tab) => !tab.when || tab.when(run));
}

/** The specimen page lays every part out at once: no selection, no tabs, no inspector. */
const FLAT = document.body.dataset.page === "specimen";

function workspaceOn() {
  return Boolean(els.workspace) && !FLAT;
}

/** Whether a picked item is read in the inspector: not at phone width, where it is read in place. */
function inspectorOn() {
  return workspaceOn() && Boolean(els.inspector) && Boolean(window.matchMedia?.("(min-width: 641px)").matches);
}

/** Whether the inspector is a pane of its own (a wide window) and not a sheet over the page. */
function inspectorDocked() {
  return Boolean(window.matchMedia?.("(min-width: 1100px)").matches);
}

function reducedMotion() {
  return Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
}

/** The claim the rail has selected, or null for the whole thesis. */
function selectedClaim() {
  if (!state.selected) return null;
  return list(state.run?.claims).find((claim) => claim.id === state.selected) ?? null;
}

/** `?claim=c2&tab=evidence` opens the page on that claim and tab: for a shared link and the screenshots. Read once. */
function readSelectionFromAddress(run) {
  if (state.addressRead || FLAT) return;
  state.addressRead = true;
  const params = new URLSearchParams(location.search);
  const claim = params.get("claim");
  if (claim && list(run.claims).some((item) => item.id === claim)) state.selected = claim;
  const tab = params.get("tab");
  if (tab && TABS.some((item) => item.id === tab)) state.tab = tab;
}

/** Select the whole thesis ("") or a claim in the rail; the centre pane and the inspector follow. */
function select(claimId, { focus = false } = {}) {
  if (!workspaceOn() || !state.run) return;
  const changed = state.selected !== claimId;
  state.selected = claimId;
  if (changed) state.picked = null;
  applySelection();
  if (changed && els.centreScroll) els.centreScroll.scrollTop = 0;
  const row = claimId ? els.scorecard.querySelector(`a.score-row[data-select="${CSS.escape(claimId)}"]`) : els.railThesis;
  if (!row) return;
  if (focus) row.focus({ preventScroll: true });
  row.scrollIntoView({ block: "nearest" });
  // At phone width the rail is above the centre pane: go on to what was selected.
  if (!focus && changed && !window.matchMedia?.("(min-width: 641px)").matches) els.centre?.scrollIntoView({ block: "start", behavior: reducedMotion() ? "auto" : "smooth" });
}

/** Show one tab of the selection. */
function setTab(tabId, { focus = false } = {}) {
  if (!workspaceOn() || !tabsOn().some((tab) => tab.id === tabId)) return;
  const changed = state.tab !== tabId;
  state.tab = tabId;
  // The inspector follows the tab: what was picked on another tab is let go.
  if (changed) state.picked = null;
  applySelection();
  if (changed && els.centreScroll) els.centreScroll.scrollTop = 0;
  if (focus) $(`tab-${tabId}`)?.focus({ preventScroll: true });
}

/** Move the focus from the rail to what is shown for the selection: its tab, from where Tab goes into the pane. */
function focusCentre() {
  $(`tab-${state.tab}`)?.focus({ preventScroll: true });
}

/**
 * Draw the selection: the rail's current row, the centre pane's head, the tab and its panels,
 * the selected claim's docket (every other docket is off and inert, so neither the keyboard nor
 * a screen reader reaches it), the lanes of the thesis over time, and the inspector.
 */
function applySelection() {
  if (!workspaceOn() || !state.run) return;
  const run = state.run;
  if (state.selected && !list(run.claims).some((claim) => claim.id === state.selected)) state.selected = "";
  const tabs = tabsOn(run);
  if (!tabs.some((tab) => tab.id === state.tab)) state.tab = tabs[0].id;
  const claim = selectedClaim();
  const scope = claim ? "claim" : "thesis";
  // The tab row is this run's: drawn again only when the set of tabs changes.
  const tabSet = tabs.map((tab) => tab.id).join(" ");
  if (els.tabs.dataset.set !== tabSet) {
    els.tabs.dataset.set = tabSet;
    els.tabs.replaceChildren(...tabs.map(tabButton));
  }

  els.railThesis?.setAttribute("aria-current", String(!claim));
  for (const row of els.scorecard.querySelectorAll("a.score-row")) row.setAttribute("aria-current", String(Boolean(claim) && row.dataset.select === claim.id));
  drawSelectionHead(run, claim);

  for (const tab of els.tabs.querySelectorAll('[role="tab"]')) {
    const on = tab.dataset.tab === state.tab;
    tab.setAttribute("aria-selected", String(on));
    tab.tabIndex = on ? 0 : -1;
  }
  els.workspace.dataset.tab = state.tab;
  els.workspace.dataset.scope = scope;
  for (const panel of els.centreScroll.querySelectorAll(".tabpanel")) {
    const on = panel.dataset.tab.split(" ").includes(state.tab) && (panel.dataset.scope === "both" || panel.dataset.scope === scope);
    panel.classList.toggle("is-off", !on);
    panel.toggleAttribute("inert", !on);
    if (on) panel.setAttribute("aria-labelledby", `tab-${state.tab}`);
    else panel.removeAttribute("aria-labelledby");
  }
  for (const docket of els.claimList.querySelectorAll("details.claim")) {
    const on = Boolean(claim) && docket.dataset.docket === claim.id;
    docket.classList.toggle("is-off", !on);
    docket.toggleAttribute("inert", !on);
    if (on) docket.open = true;
  }
  // The analysis: the whole thesis's, or the selected claim's; the others are off and inert.
  for (const part of els.analysis?.querySelectorAll(":scope > .an-scope") ?? []) {
    const on = part.dataset.anScope === (claim ? claim.id : "");
    part.classList.toggle("is-off", !on);
    part.toggleAttribute("inert", !on);
  }
  // The reported figures put those tied to the selection first.
  if (state.figuresFor !== (claim ? claim.id : "")) renderRunFigures(run);
  // The thesis over time: every lane for the whole thesis, one claim's own lane for that claim.
  for (const lane of els.tot?.querySelectorAll("[data-tot-claim]") ?? []) {
    const off = Boolean(claim) && lane.dataset.totClaim !== claim.id;
    lane.classList.toggle("is-off", off);
    lane.toggleAttribute("inert", off);
  }
  drawInspector();
}

/** The centre pane's head: what the rail has selected. A claim's id, stamps, counts and flags are the record's. */
function selectionHead(run, claim) {
  if (!claim) {
    // The whole thesis is headed by the decision it is about, in the record's words.
    return [h("div", { class: "sel-line" }, h("span", { class: "sel-id sel-id-thesis", text: "The whole thesis" }), briefActions(run)), h("h3", { id: "sel-title", class: "sel-title", "data-sel-thesis": "", text: str(run.inputs?.decision) || "The whole thesis" })];
  }
  const lean = claim.analysis?.argument?.lean;
  return [
    h("div", { class: "sel-line" }, h("span", { class: "claim-id sel-id", text: claim.id }), claimStamps(claim, currentReview(run)), str(lean) ? h("span", { class: "sel-lean", "data-sel-lean": lean }, "argument ", leanPill(lean)) : "", docketMeta(claim, run)),
    h("h3", { id: "sel-title", class: "sel-title", text: claim.text }),
  ];
}

function drawSelectionHead(run, claim) {
  if (els.selHead) els.selHead.replaceChildren(...selectionHead(run, claim));
}

/** One tab: its number key, then its name. */
function tabButton(tab, index) {
  return h(
    "button",
    { type: "button", role: "tab", id: `tab-${tab.id}`, class: "tab", "data-tab": tab.id, "aria-selected": "false", tabindex: "-1", "aria-keyshortcuts": String(index + 1), onclick: () => setTab(tab.id) },
    h("kbd", { class: "tab-key", "aria-hidden": "true", text: String(index + 1) }),
    h("span", { class: "tab-label", text: tab.label }),
  );
}

/**
 * Bring a part of the run into view: select the claim whose docket holds it (or the whole
 * thesis), switch to a tab that shows it, then scroll its pane to it.
 */
function reveal(target, { scroll = true } = {}) {
  if (workspaceOn() && state.run && els.workspace.contains(target)) {
    const docket = target.closest("details.claim");
    const panel = target.closest(".tabpanel");
    if (docket) state.selected = docket.dataset.docket;
    else if (panel?.dataset.scope === "thesis") state.selected = "";
    if (panel) {
      // Inside a docket the findings show in both tabs, the rest of the body in one.
      const part = docket ? target.closest("[data-part]")?.dataset.part : "";
      const tabs = part === "overview" ? ["overview"] : part === "evidence" ? ["evidence", "overview"] : panel.dataset.tab.split(" ");
      if (part === "evidence" && target.closest(".cc-slot")) state.tab = "evidence";
      else if (!tabs.includes(state.tab)) state.tab = tabs[0];
    }
    applySelection();
  }
  if (scroll) target.scrollIntoView({ block: "start", behavior: reducedMotion() ? "auto" : "smooth" });
}

// ---- the verdicts, drawn one way everywhere

/**
 * One cell per claim in the record's order, filled in its verdict's colour and carrying its
 * glyph: the thesis's result at a glance, in the bar, over the rail, at the head of the Overview
 * and over the thesis over time. A cell selects its claim. With `ids` each cell also names its claim.
 */
function verdictStrip(run, { ids = false } = {}) {
  const claims = list(run?.claims);
  if (claims.length === 0) return "";
  return h(
    "span",
    { class: ids ? "vstrip has-ids" : "vstrip", role: "group", "aria-label": "Verdicts, one cell per claim" },
    claims.map((claim) =>
      h(
        "button",
        { type: "button", class: `vcell v-${claim.verdict ? token(claim.verdict, VERDICT_GLYPH) : "pending"}`, "data-vcell": claim.id, title: `${claim.id}: ${verdictLabel(claim.verdict)}`, onclick: () => select(claim.id) },
        ids ? h("span", { class: "vcell-id", text: claim.id }) : "",
        h("span", { class: "glyph", "aria-hidden": "true", text: VERDICT_GLYPH[claim.verdict] ?? "…" }),
        h("span", { class: "visually-hidden", text: `${ids ? "" : ` ${claim.id}`} ${verdictLabel(claim.verdict)}` }),
      ),
    ),
  );
}

/**
 * The verdicts as a table, one row per claim by its id (the claim's words are in the rail, once):
 * the verdict, and for a run with computed tests the test's outcome, its margin and how many
 * readers agreed, then the number of findings. Every cell is the record's; a row's id selects the claim.
 */
function verdictTable(run) {
  const claims = list(run.claims);
  if (claims.length === 0) return h("p", { class: "muted", text: run.status === "running" ? "Claims appear once the run has planned them." : "This run recorded no claims." });
  const review = currentReview(run);
  const tested = claims.some((claim) => testOf(claim));
  const heads = ["Claim", "Verdict", ...(tested ? ["Test", "Margin", "Readers"] : []), "Findings"];
  return h(
    "table",
    { class: "vtable" },
    h("thead", null, h("tr", null, heads.map((text) => h("th", { scope: "col", class: text === "Margin" || text === "Findings" ? "num" : null, text })))),
    h(
      "tbody",
      null,
      claims.map((claim) => {
        const test = testOf(claim);
        const readers = test ? boardReaders(claim) : "";
        return h(
          "tr",
          { "data-vrow": claim.id },
          h("th", { scope: "row" }, h("button", { type: "button", class: "linklike vrow-id", onclick: () => select(claim.id), text: claim.id }), str(claim.caution) ? [" ", limitGlyph()] : ""),
          h("td", null, claimStamps(claim, review)),
          tested ? h("td", null, test ? testOutcome(test.outcome, test.outcome_label) : h("span", { class: "muted", text: "none" })) : "",
          tested ? h("td", { class: `num${test ? signClass(str(test.margin_display)) : ""}`, text: (test && str(test.margin_display)) || "—" }) : "",
          tested ? h("td", { text: readers ? readers.textContent : "—" }) : "",
          h("td", { class: "num", text: num(list(claim.finding_ids).length) }),
        );
      }),
    ),
  );
}

/** Draw the verdict strip where it stands apart from the rail, and the Overview's masthead and table. */
function renderVerdictViews(run) {
  if (els.cmdVerdicts) {
    els.cmdVerdicts.replaceChildren();
    appendAll(els.cmdVerdicts, [verdictStrip(run)]);
  }
  if (els.overviewMast) {
    const c = run.coverage ?? {};
    els.overviewMast.replaceChildren();
    appendAll(els.overviewMast, [
      // When the run was made and how old its evidence is, in the record's words; then the result.
      h("p", { class: "mast-line" }, `Run of ${dateLabel(run.started_at)}`, str(run.as_of?.line) ? ` · ${run.as_of.line}` : ""),
      verdictStrip(run, { ids: true }),
      Number.isFinite(c.claims_total) && Number.isFinite(c.claims_with_evidence)
        ? h("p", { class: "mast-tally", text: `${num(c.claims_with_evidence)} of ${plural(c.claims_total, "claim", "claims")} with verified excerpts or figures` })
        : "",
    ]);
  }
  els.verdictTable?.replaceChildren(verdictTable(run));
}

// ---- codes: the letters before a title, typed to go there

/**
 * Go to the panel whose title carries this code (`data-code`): typed in the ticker field after a
 * full stop, then Enter (".fig"). Three codes are not panels: RUN and GDE open the Run drawer on
 * who did the work and on the guide, INS puts the focus in the inspector. False when nothing on
 * this screen has the code.
 */
function runCode(text) {
  const code = text.trim().toUpperCase();
  if (!/^[A-Z]{2,4}$/.test(code)) return false;
  if (code === "RUN" || code === "GDE") {
    if (onFirstScreen()) return false;
    openRunDrawer(code === "RUN" ? "run" : "guide");
    return true;
  }
  if (code === "INS") {
    if (!inspectorOn() || els.runView.hidden) return false;
    els.inspectBody.focus({ preventScroll: true });
    return true;
  }
  const titled = [...document.querySelectorAll("#result-panel [data-code]")].filter((node) => node.dataset.code === code && !node.closest("[hidden]"));
  if (titled.length === 0) return false;
  // A code inside every claim's docket (FND) means the selected claim's, else the first claim's.
  const claim = selectedClaim();
  const target = titled.find((node) => !node.closest("details.claim")) ?? titled.find((node) => claim && node.closest("details.claim")?.dataset.docket === claim.id) ?? titled[0];
  reveal(target);
  return true;
}

/** Enter in the ticker field on ".code": go there, and give the field back what it held. */
function onTickerKey(event) {
  const typed = els.ticker.value.trim();
  if (event.key !== "Enter" || !typed.startsWith(".")) return;
  event.preventDefault();
  if (runCode(typed.slice(1))) {
    els.ticker.value = state.tickerOnFocus ?? "";
    setFieldError("ticker", []);
    els.ticker.blur();
  } else {
    setFieldError("ticker", [`Nothing on this screen has the code ${typed.slice(1).toUpperCase()}. The codes are listed under Keys.`]);
  }
}

// ---- the other views in the same frame

/**
 * A view that is not a run (a filing comparison, tagged breakdowns, the restatement ledger, the
 * inbox, a saved thesis, figures only) is laid out in the same three panes: its sections or
 * items in a rail, its tables and lists in the centre, and what explains it (its head, its
 * legend, a watch's settings) at the side. `aside` names the nodes that go to the side; the rest
 * is the centre; `entries` selects what the rail lists.
 */
const VIEW_FRAMES = [
  { id: "changes-view", aside: ["changes-head", "changes-legend"], entries: ".block-title, .chg-item-title" },
  { id: "breakdowns-view", aside: ["breakdowns-head", "breakdowns-legend"], entries: ".bd-title" },
  { id: "ledger-view", aside: ["ledger-head", "ledger-legend"], entries: ".block-title, .ledger tbody th[scope='row']" },
  { id: "inbox-view", aside: ["inbox-head", "watch-down", "watches-section"], entries: ".inbox-headline" },
  { id: "thesis-view", aside: ["thesis-head", "thesis-watch-section"], entries: ".block-title" },
  { id: "figures-view", aside: ["figures-head"], entries: ".fig-head" },
];

function frameViews() {
  for (const frame of VIEW_FRAMES) {
    const view = $(frame.id);
    if (!view) continue;
    const side = frame.aside.map($).filter(Boolean);
    const rest = [...view.children].filter((node) => !side.includes(node));
    const entries = h("ol", { class: "view-entries" });
    const scroll = h("div", { class: "pane-scroll" }, ...rest);
    view.classList.add("view-frame");
    view.replaceChildren(
      h("nav", { class: "pane rail view-rail", "aria-label": "The sections of this view" }, h("h3", { class: "pane-label", text: "Sections" }), entries),
      // Before the centre in the markup: a phone and paper read what the view is, then the view.
      h("aside", { class: "pane view-aside", "aria-label": "About this view" }, h("div", { class: "pane-scroll" }, ...side)),
      h("div", { class: "pane centre view-centre" }, scroll),
    );
    // Once after a burst of changes (a timer, not a frame: a page that is not painting still gets its rail).
    let pending = 0;
    const sync = () => {
      clearTimeout(pending);
      pending = setTimeout(() => drawViewEntries(entries, scroll, frame.entries), 30);
    };
    new MutationObserver(sync).observe(scroll, { childList: true, subtree: true });
    sync();
  }
}

/** The rail of such a view: one entry per section or item now in its centre pane; selecting one scrolls to it, opening what holds it. */
function drawViewEntries(entries, scroll, selector) {
  // One entry per name: a ledger lists a metric once however many of its periods changed (the entry goes to the first).
  const seen = new Set();
  const nodes = [...scroll.querySelectorAll(selector)].filter((node) => {
    const name = node.textContent.replace(/\s+/g, " ").trim();
    if (!name || seen.has(name) || node.closest("[hidden]")) return false;
    seen.add(name);
    return true;
  });
  entries.replaceChildren(
    ...nodes.map((node) =>
      h(
        "li",
        { class: node.closest(".is-unread") ? "is-unread" : null },
        h("button", {
          type: "button",
          class: "view-entry",
          title: node.textContent.replace(/\s+/g, " ").trim(),
          onclick: () => {
            for (let fold = node.closest("details"); fold; fold = fold.parentElement?.closest("details")) fold.open = true;
            node.scrollIntoView({ block: "start", behavior: reducedMotion() ? "auto" : "smooth" });
          },
          text: node.textContent.replace(/\s+/g, " ").trim(),
        }),
      ),
    ),
  );
}

// ---- the inspector

/** A button that reads its item in the inspector: for the keyboard, and for the eye. Selecting the item itself does the same. */
function pickButton(label) {
  return h("button", { type: "button", class: "pick", "data-pick-button": "", text: label });
}

/** "finding:f3" as {kind, id}; ids may hold colons (a tagged figure's does). */
function parsePick(value) {
  const text = str(value);
  const cut = text.indexOf(":");
  return cut > 0 ? { kind: text.slice(0, cut), id: text.slice(cut + 1) } : null;
}

/** Read something in the inspector, or with null put it back to the tab's own first item. */
function pick(target) {
  if (!workspaceOn()) return;
  state.picked = target;
  drawInspector();
  // A sheet covers part of the page: the focus goes with it, and Close or Esc brings the page back.
  if (target && !inspectorDocked()) els.inspectBody?.focus({ preventScroll: true });
}

/** A click on a pickable item of the centre pane, or on its button, reads it in the inspector. */
function onCentreClick(event) {
  if (!(event.target instanceof Element)) return;
  const host = event.target.closest("[data-pick]");
  if (!host || !els.centreScroll.contains(host)) return;
  // A phone has no inspector pane: only what the analysis cites is read in a sheet; the rest is read in place.
  if (!inspectorOn() && !(workspaceOn() && els.analysis?.contains(host))) return;
  const button = event.target.closest("[data-pick-button]");
  // A link, a control or a disclosure inside the item keeps its own meaning, and so does selecting its text.
  if (!button && event.target.closest("a, button, input, textarea, select, label, summary, table")) return;
  if (!button && String(window.getSelection?.() ?? "")) return;
  const target = parsePick(host.dataset.pick);
  if (target) pick(target);
}

/** The first verified finding of a claim that cites a quote or a figure. */
function firstFinding(claim) {
  for (const id of list(claim?.finding_ids)) {
    const finding = state.ctx?.findings.get(id);
    if (finding && finding.verified !== false && (list(finding.evidence_ids).length || list(finding.metric_ids).length)) return { kind: "finding", id };
  }
  return null;
}

/** With nothing picked, a docked inspector reads the first item of the tab on show, so the pane is not empty. */
function firstPick(run, claim) {
  const test = claim && claim.computed && typeof claim.computed === "object" ? { kind: "test", id: claim.id } : null;
  if (state.tab === "analysis") {
    // The first sentence of the argument, so the pane shows what a sentence rests on; with no argument, the first analytic.
    const sentence = state.ctx?.firstSentence?.get(claim ? claim.id : "");
    if (sentence) return { kind: "sentence", id: sentence };
    const first = els.analysis?.querySelector(`.an-scope[data-an-scope="${CSS.escape(claim ? claim.id : "")}"] [data-pick]`);
    return first ? parsePick(first.dataset.pick) : null;
  }
  if (state.tab === "method") {
    const node = els.method?.querySelector("[data-pick]");
    return node ? parsePick(node.dataset.pick) : null;
  }
  if (state.tab === "overview") {
    if (claim) return test ?? firstFinding(claim);
    const cell = els.tape?.querySelector("[data-pick]");
    return cell ? parsePick(cell.dataset.pick) : null;
  }
  const newestEvent = () => {
    const first = list(run.timeline)[0];
    return first && str(first.id) ? { kind: "event", id: str(first.id) } : null;
  };
  // The whole thesis's evidence is its sources and what was withheld, behind a fold: nothing is read at the side until one is picked.
  if (state.tab === "evidence") return claim ? firstFinding(claim) : null;
  if (state.tab === "time") return test ?? newestEvent();
  if (state.tab === "events") return newestEvent();
  if (state.tab === "figures") {
    const row = els.figures?.querySelector("details.fig-row[data-metric-id]");
    return row ? { kind: "figure", id: row.dataset.metricId } : null;
  }
  return null;
}

function inspectHead(kind, about, ...marks) {
  return h("header", { class: "ins-head" }, h("p", { class: "ins-kicker" }, h("span", { class: "ins-kind", text: kind }), about ? h("span", { class: "ins-about", text: about }) : ""), marks.length ? h("p", { class: "ins-marks" }, ...marks) : "");
}

/** A finding's quotes, each in the text around it, with where it sits and the link to the filing; then the figures it cites. */
function inspectFinding(id) {
  const ctx = state.ctx;
  const finding = ctx.findings.get(id);
  if (!finding) return null;
  const quotes = list(finding.evidence_ids).map((evidenceId) => {
    const item = ctx.evidence.get(evidenceId);
    return item ? renderEvidence(item, ctx.sources.get(item.source_id), true) : h("p", { class: "muted", text: `Excerpt ${evidenceId} is listed but missing from the record.` });
  });
  const figures = list(finding.metric_ids).map((metricId) => ctx.metrics.get(metricId)).filter(Boolean);
  return [
    inspectHead(`Finding ${finding.id}`, `of claim ${str(finding.claim_id)}`, stancePill(finding.stance)),
    quotes.length ? h("div", { class: "ins-quotes" }, quotes) : h("p", { class: "muted", text: "This finding cites no quote: it rests on reported figures only." }),
    figures.length
      ? h(
          "div",
          { class: "ins-cited" },
          h("p", { class: "label", text: "Reported figures it cites" }),
          h(
            "ul",
            { class: "ins-list" },
            figures.map((metric) =>
              h("li", null, h("button", { type: "button", class: "linklike", onclick: () => pick({ kind: "figure", id: metric.id }), text: `${metric.label} · ${metric.period_label}` }), " ", h("span", { class: valueClass(metric), text: metric.display })),
            ),
          ),
        )
      : "",
  ];
}

/** A computed test's operands, each with the facts it was read from, its arithmetic and every reading. */
function inspectTest(id) {
  const claim = state.ctx.claims.get(id);
  const test = claim && claim.computed && typeof claim.computed === "object" ? claim.computed : null;
  if (!test) return null;
  // The centre pane has the expression and the outcome: here, only what is behind them.
  return [inspectHead("Operands and arithmetic", `of claim ${claim.id}'s test`), h("div", { class: "ct-inspected" }, ...computedDetail(claim, state.run.company?.cik))];
}

/** One 8-K whole: its items, the roles a 5.02 names, its opening sentences and the link to it. */
function inspectEvent(id) {
  const event = list(state.run.timeline).find((item) => str(item.id) === id);
  if (!event) return null;
  return [inspectHead(str(event.form) || "8-K", `filed ${str(event.filed_label) || str(event.filed_date)}`), renderEvent(event, state.meta?.events ?? {}, true)];
}

/** One reported figure: its value, the line of its series, its formula and the reported values behind it. */
function inspectFigure(id) {
  const metric = state.ctx.metrics.get(id);
  if (!metric) return null;
  return [
    inspectHead("Reported figure", str(metric.period_label)),
    h("p", { class: "ins-figure" }, h("span", { class: "ins-figure-label", text: str(metric.label) }), h("span", { class: `${valueClass(metric)} ins-figure-value`, text: str(metric.display) })),
    sparkline(metric, list(state.run.series)),
    figureBody(metric),
  ];
}

/**
 * With nothing picked and nothing on the tab to pick: the run's own facts, each the record's
 * (its status, the counts of the status line, the sources, the coverage limits).
 */
function inspectRunFacts() {
  const run = state.run;
  const c = run.coverage ?? {};
  const fact = (label, ...value) => h("div", null, h("dt", { text: label }), h("dd", null, ...value));
  const sources = list(run.sources);
  const limits = list(run.coverage_limits);
  const kind = (source) => (source.kind === "sec_filing" ? `${str(source.form) || "Filing"}${source.published_date ? `, filed ${source.published_date}` : ""}` : source.kind === "sec_xbrl" ? "XBRL data" : "Web page");
  return [
    inspectHead("The run", str(run.id)),
    h(
      "dl",
      { class: "ins-grid" },
      fact("Status", statusMark(run.status), ` ${capitalize(run.status)}`),
      Number.isFinite(c.sources_requested) ? fact("Sources read", `${num(c.sources_read)} of ${num(c.sources_requested)}`) : "",
      Number.isFinite(c.passages_indexed) ? fact("Passages indexed", num(c.passages_indexed)) : "",
      Number.isFinite(c.findings_verified) ? fact("Findings verified", Number.isFinite(c.findings_proposed) && c.findings_proposed > 0 ? `${num(c.findings_verified)} of ${num(c.findings_proposed)}` : num(c.findings_verified)) : "",
      Number.isFinite(c.findings_withheld) ? fact("Withheld", num(c.findings_withheld)) : "",
      str(run.as_of?.line) ? fact("As of", run.as_of.line) : "",
    ),
    // Not what the tab on show already lists: the sources on the whole thesis's Evidence, the limits on Limits.
    sources.length && state.tab !== "evidence"
      ? h(
          "div",
          { class: "ins-block" },
          h("p", { class: "label", text: "Sources" }),
          h("ul", { class: "ins-list" }, sources.map((source) => h("li", null, h("span", null, h("strong", { text: `${str(source.id)} ` }), kind(source)), h("span", { class: "muted", text: source.extraction_status === "extracted" ? "Read" : "Not read" })))),
        )
      : "",
    state.tab !== "limits"
      ? h(
          "div",
          { class: "ins-block" },
          h("p", { class: "label", text: "Coverage limits" }),
          limits.length ? h("ul", { class: "mark-list" }, limits.map((line) => limitLine("li", String(line)))) : h("p", { class: "muted", text: run.status === "running" ? "Listed when the run finishes." : "None recorded." }),
        )
      : "",
    h("p", { class: "ins-none muted", text: "Select a finding, a computed test, an 8-K or a figure in the centre pane to read it here." }),
  ];
}

const INSPECT = { finding: inspectFinding, test: inspectTest, event: inspectEvent, figure: inspectFigure, sentence: inspectSentence, analytic: inspectAnalytic, corollary: inspectCorollary, odds: inspectOdds, stage: inspectStage };

/** Fill the inspector from what was picked, else from the tab's first item, and mark that item in the centre pane. */
function drawInspector() {
  if (!els.inspectBody || !state.run || !state.ctx) return;
  const explicit = state.picked;
  const target = explicit ?? (inspectorDocked() && inspectorOn() ? firstPick(state.run, selectedClaim()) : null);
  // At phone width there is no pane: only something picked is read, in a sheet.
  const phone = workspaceOn() && !inspectorOn();
  const content = target && (inspectorOn() || (phone && explicit)) && Object.hasOwn(INSPECT, target.kind) ? INSPECT[target.kind](target.id) : null;
  const key = content ? `${target.kind}:${target.id}` : "";
  for (const node of els.centreScroll.querySelectorAll("[data-pick]")) node.classList.toggle("is-picked", Boolean(key) && node.dataset.pick === key);
  els.inspector.dataset.inspecting = key;
  els.inspector.classList.toggle("is-sheet-open", Boolean(explicit) && Boolean(content));
  els.inspector.classList.toggle("is-phone-sheet", phone && Boolean(explicit) && Boolean(content));
  // The inspector is always there: with nothing to read from the tab it shows the run's own facts.
  els.inspectBody.replaceChildren(...(content ?? inspectRunFacts()));
  els.inspectBody.scrollTop = 0;
}

function onTabKey(event) {
  const tabs = [...els.tabs.querySelectorAll('[role="tab"]')];
  const at = tabs.indexOf(document.activeElement);
  if (at < 0) return;
  const to = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: tabs.length - 1 }[event.key];
  if (to === undefined) return;
  event.preventDefault();
  setTab(tabs[(to + tabs.length) % tabs.length].dataset.tab, { focus: true });
}

function initWorkspace() {
  if (!els.tabs || FLAT) return;
  els.tabs.replaceChildren(...TABS.filter((tab) => !tab.when).map(tabButton));
  for (const panel of els.centreScroll.querySelectorAll(".tabpanel")) panel.setAttribute("role", "tabpanel");
  els.tabs.addEventListener("keydown", onTabKey);
  els.railThesis?.addEventListener("click", (event) => {
    event.preventDefault();
    select("");
  });
  els.centreScroll.addEventListener("click", onCentreClick);
  els.inspectClose?.addEventListener("click", () => pick(null));
  // Crossing a width where the inspector docks, becomes a sheet or goes: draw it for the new width.
  for (const query of ["(min-width: 641px)", "(min-width: 1100px)"]) window.matchMedia?.(query).addEventListener?.("change", () => drawInspector());
}

// ---------------------------------------------------------------- the analysis (docs/analysis.md)
//
// Run.analysis and Claim.analysis drawn as a note: the argument first, each sentence with what
// it cites; then what code computed, grouped by where its data came from. Every sentence,
// figure, reading, count and state below is the record's own text or number. The page chooses
// where each goes and what it opens; it computes none of them.

/** The analytics providers in the order they are shown: id, the block's code, its title, and what it is. */
const AN_PROVIDERS = [
  ["facts", "OWN", "The company's own filings", "from the XBRL facts the company filed with the SEC"],
  ["outside_view", "OUT", "The outside view: base rates and peers", "from SEC's frames of every filer: how often such a test held for comparable companies, and where this one ranks among them"],
  ["market_view", "MKT", "The market view: what the price implies", "valuation arithmetic at a recorded price, under assumptions each figure states"],
];
/** A request's state in words (`argument_step`, `thesis_step`, `corollaries_step`). */
const AN_STEP = { answered: "answered", partial: "answered in part", failed: "asked and failed", not_asked: "not asked" };
/** Which way a claim's argument leans: glyph and words. Outlined, never filled: a filled stamp is a verdict. */
const LEAN_MARK = { supports: ["✓", "supports"], challenges: ["✕", "challenges"], mixed: ["±", "mixed"], unclear: ["?", "unclear"] };
/** A corollary's status in words. */
const COR_STATUS = {
  agreed: "Both readers read the same test",
  proposer_only: "Read by the proposing model only",
  grammar_only: "Read by the grammar only",
  not_agreed: "The two readers read different tests",
  not_computable: "Read into a test that could not be computed",
  no_test: "No reader could make a test of it",
};
const COR_RESULT = { as_expected: "✓", against: "✕", cannot_tell: "?" };

function hasAnalysis(run) {
  return Boolean(run?.analysis) && typeof run.analysis === "object";
}

/**
 * Index what a citation can name: the analytics (each with a short reference, A1 onward, in the
 * record's order), the corollaries, the persistence odds and the 8-Ks. The sentences are
 * numbered as they are drawn, in the record's order, so a redraw of the same run gives the same keys.
 */
function indexAnalysis(ctx, run) {
  const analysis = hasAnalysis(run) ? run.analysis : {};
  ctx.analytics = new Map();
  ctx.analyticRef = new Map();
  list(analysis.analytics).forEach((item, index) => {
    if (!str(item?.id)) return;
    ctx.analytics.set(item.id, item);
    ctx.analyticRef.set(item.id, `A${index + 1}`);
  });
  ctx.corollaries = new Map();
  ctx.odds = new Map();
  for (const claim of list(run.claims)) {
    for (const cor of list(claim.analysis?.corollaries)) if (str(cor?.id)) ctx.corollaries.set(cor.id, cor);
    const odds = claim.analysis?.persistence;
    if (odds && typeof odds === "object" && str(odds.id)) ctx.odds.set(odds.id, odds);
  }
  ctx.events = new Map(
    list(run.timeline)
      .filter((event) => str(event?.id))
      .map((event) => [event.id, event]),
  );
  ctx.sentences = new Map();
  ctx.firstSentence = new Map();
}

/** What a cited id names in this record: the inspector's kind and id for it, a short label and a line of words. Null when the record holds nothing under it. */
function citeTarget(id) {
  const ctx = state.ctx;
  const text = str(id);
  if (!ctx || !text) return null;
  if (ctx.findings.has(text)) {
    const finding = ctx.findings.get(text);
    return { kind: "finding", id: text, label: text, what: "Finding", title: `Finding ${text} of claim ${str(finding.claim_id)}`, line: str(finding.statement) || str(finding.text) };
  }
  if (ctx.analytics?.has(text)) {
    const item = ctx.analytics.get(text);
    const kind = str(item.kind).replaceAll("_", " ");
    return { kind: "analytic", id: text, label: `${ctx.analyticRef.get(text)}${kind ? ` ${kind}` : ""}`, what: "Analytic", title: `${str(item.label)}: ${str(item.display)}`, line: `${str(item.label)}: ${str(item.display) || "n/a"}` };
  }
  if (text.startsWith("test:")) {
    const claim = ctx.claims.get(text.slice(5));
    const test = claim?.computed && typeof claim.computed === "object" ? claim.computed : null;
    if (test) return { kind: "test", id: claim.id, label: `test ${claim.id}`, what: "Computed test", title: `The computed test of claim ${claim.id}: ${str(test.canonical)}`, line: `${str(test.canonical)}: ${str(test.outcome_label) || TEST_FALLBACK[test.outcome] || ""}` };
  }
  if (ctx.corollaries?.has(text)) {
    const cor = ctx.corollaries.get(text);
    return { kind: "corollary", id: text, label: text.replace(/^cor:/, "cor ").replace(":", "."), what: "Corollary", title: `Corollary of claim ${str(cor.claim_id)}: ${str(cor.sentence)}`, line: `${str(cor.sentence)} It ${str(cor.result_label) || "has no result"}.` };
  }
  if (ctx.odds?.has(text)) {
    const odds = ctx.odds.get(text);
    return { kind: "odds", id: text, label: text.replace(":", " "), what: "Persistence odds", title: `The odds that the test of claim ${str(odds.claim_id)} keeps holding`, line: str(odds.note) };
  }
  if (ctx.events?.has(text)) {
    const event = ctx.events.get(text);
    const filed = str(event.filed_label) || str(event.filed_date);
    return { kind: "event", id: text, label: `${str(event.form) || "8-K"} ${filed}`, what: str(event.form) || "8-K", title: `${str(event.form) || "8-K"} filed ${filed}`, line: list(event.items).map((item) => `Item ${str(item?.number)} ${str(item?.title)}`).join("; ") };
  }
  if (ctx.metrics.has(text)) {
    const metric = ctx.metrics.get(text);
    return { kind: "figure", id: text, label: str(metric.label), what: "Reported figure", title: `${str(metric.label)}, ${str(metric.period_label)}: ${str(metric.display)}`, line: `${str(metric.label)}, ${str(metric.period_label)}: ${str(metric.display)}` };
  }
  return null;
}

/** One citation as a chip: its short label; selecting it reads what it names in the inspector. An id the record holds nothing under is shown, and says so. */
function citeChip(id) {
  const target = citeTarget(id);
  if (!target) return h("span", { class: "chip chip-missing", "data-cite": String(id), title: "The record lists this id and holds nothing under it.", text: String(id) });
  return h("button", { type: "button", class: `chip chip-${target.kind}`, "data-cite": String(id), "data-pick": `${target.kind}:${target.id}`, "data-pick-button": "", title: target.title, text: target.label });
}

/**
 * One sentence of the argument: its text, a chip for each thing it cites, and, when the audit
 * did not verify it, that it did not and why, in place. Selecting the sentence reads what it
 * rests on in the inspector.
 */
function anSentence(sentence, where, scope) {
  const ctx = state.ctx;
  const key = `s${ctx.sentences.size + 1}`;
  ctx.sentences.set(key, { sentence, where, scope });
  if (!ctx.firstSentence.has(scope)) ctx.firstSentence.set(scope, key);
  const verified = sentence?.verified === true;
  const problems = list(sentence?.problems).map(String).filter(Boolean);
  const cites = list(sentence?.cites);
  const thresholds = sentenceThresholds(sentence);
  return h(
    "span",
    { class: `an-s${verified ? "" : " is-unverified"}${thresholds.length ? " has-thresholds" : ""}`, "data-an-sentence": key, "data-verified": String(verified), "data-pick": `sentence:${key}` },
    h("span", { class: "an-text", text: str(sentence?.text) }),
    "\u00a0",
    cites.length ? h("span", { class: "an-cites" }, cites.map(citeChip)) : h("span", { class: "an-cites an-nocite", "data-no-cite": "", text: "cites nothing" }),
    // A number that only restates a threshold was not checked as a fact: said on the sentence, quietly, and never as a failure.
    thresholds.map((item) => h("span", { class: "an-threshold", "data-threshold": str(item.raw), "data-threshold-of": str(item.of), title: thresholdWords(item) }, `restates a threshold: ${str(item.raw)}`)),
    verified ? "" : h("span", { class: "an-unverified", "data-unverified": "" }, limitGlyph(), ` Not verified: ${problems.join("; ") || "the audit recorded no reason"}`),
  );
}

/** The thresholds a sentence restates (`thresholds: [{raw, of, note}]`); none on a record made before the audit listed them. */
function sentenceThresholds(sentence) {
  return list(sentence?.thresholds).filter((item) => item && typeof item === "object" && str(item.raw));
}

/** A restated threshold in words: the number, whose threshold it is, and that it was not checked as a fact. */
function thresholdWords(item) {
  const of = str(item?.of);
  const test = /^test:(.+)$/.exec(of);
  const cor = /^cor:([^:]+):(.+)$/.exec(of);
  const whose = test ? `the test of ${test[1]}` : cor ? `corollary ${cor[1]}.${cor[2]}` : of || "its own condition";
  return `Restates a threshold: ${str(item?.raw)} (${whose}). Not checked as a fact.`;
}

/** Sentences set as one paragraph, in the record's order. */
function anPara(sentences, where, scope, cls = "an-p") {
  const items = list(sentences);
  if (!items.length) return "";
  const out = [];
  items.forEach((item, index) => {
    if (index) out.push(" ");
    out.push(anSentence(item, where, scope));
  });
  return h("p", { class: cls }, out);
}

/** A leading paragraph: its first sentence stands alone, larger, and the rest follow as a paragraph. The order is the record's. */
function anLead(sentences, where, scope) {
  const items = list(sentences);
  if (!items.length) return "";
  return [h("p", { class: "an-p an-lead" }, anSentence(items[0], where, scope)), ...anParas(items.slice(1), where, scope)];
}

/** Each of the record's sentences as a short paragraph of its own, in the record's order: the argument's steps, one after another. */
function anParas(sentences, where, scope) {
  return list(sentences).map((item) => h("p", { class: "an-p" }, anSentence(item, where, scope)));
}

/** A part of the argument under a plain heading: the second level, under the ruled titles. */
function anPart(title, name, ...children) {
  return h("section", { class: `an-block an-part an-${name}`, "data-an-block": name }, h("h4", { class: "an-h", text: title }), ...children);
}

/** Sentences set as separate points, in the record's order. */
function anPoints(sentences, where, scope, tag = "ul", cls = "an-points") {
  const items = list(sentences);
  if (!items.length) return h("p", { class: "muted an-none", text: "The argument gives none." });
  return h(
    tag,
    { class: cls },
    items.map((item) => h("li", null, anSentence(item, where, scope))),
  );
}

/** A titled part of the note. */
function anBlock(code, title, name, ...children) {
  return h("section", { class: `an-block an-${name}`, "data-an-block": name }, h("h3", { class: "block-title", "data-code": code, text: title }), ...children);
}

/** Who made a part, in words: a model (which one, and through the API or from a cassette, as the record says), or code. */
function anBy(kind, words) {
  return h("p", { class: "an-by", "data-by": kind }, kind === "model" ? modelBadge(words) : ruleMark(words));
}

/** Who wrote the argument: the record's own words for the model and where its answers came from. */
function argumentBy(analysis) {
  const who = str(analysis.argument_detail) || (str(analysis.argument_by) && analysis.argument_by !== "none" ? analysis.argument_by : "a model");
  return `Written by ${who}. Audited by code, sentence by sentence.`;
}

function leanPill(lean) {
  const key = token(lean, LEAN_MARK);
  const [glyph, label] = LEAN_MARK[lean] ?? ["·", str(lean) || "not given"];
  return h("span", { class: `lean l-${key}`, "data-lean": str(lean) }, h("span", { class: "glyph", "aria-hidden": "true", text: glyph }), h("span", { class: "lean-label", text: ` ${label}` }));
}

/**
 * The argument's state when it is not whole. Never asked (no model on this run) is said plainly
 * and without a warning: it is how the run was made. Asked and failed, or answered in part, is a limit.
 */
function argumentState(analysis) {
  const step = str(analysis.argument_step);
  if (step === "answered" || step === "") return "";
  const asked = analysis.argument_claims_asked;
  const answered = analysis.argument_claims_answered;
  const note = str(analysis.argument_note);
  if (step === "not_asked") {
    return h(
      "div",
      { class: "an-state an-state-none", "data-argument-step": step },
      h("p", { class: "an-state-lead", text: "Computed analysis only: no model wrote an argument on this run." }),
      note ? h("p", { class: "an-state-note", "data-argument-note": "", text: note }) : "",
    );
  }
  const counted = Number.isFinite(asked) && Number.isFinite(answered);
  const thesis = str(analysis.thesis_step);
  return h(
    "div",
    { class: "an-state an-state-limit", "data-argument-step": step },
    limitLine(
      "p",
      step === "partial" ? "The argument was answered in part" : step === "failed" ? "The argument was asked for and failed" : `The argument's state is "${step}"`,
      counted ? [": ", h("span", { "data-argued": "", text: `${num(answered)} of ${num(asked)}` }), " claims argued"] : "",
      thesis ? [`; the request for the whole thesis was `, h("span", { "data-thesis-step": thesis, text: AN_STEP[thesis] ?? thesis })] : "",
      ".",
    ),
    note ? h("p", { class: "an-state-note", "data-argument-note": "", text: note }) : "",
  );
}

/** A count from `run.coverage`, as the record gives it. */
function anCount(run, field) {
  return cov(run.coverage ?? {}, field);
}

/** The audit's own counts of the argument's sentences. */
function auditLine(run) {
  if (!Number.isFinite(run.coverage?.analysis_sentences_written)) return "";
  return h(
    "p",
    { class: "an-audit", "data-an-audit": "" },
    ruleMark("Audit, by code"),
    " ",
    anCount(run, "analysis_sentences_verified"),
    " of ",
    anCount(run, "analysis_sentences_written"),
    " sentences verified",
    Number.isFinite(run.coverage?.analysis_sentences_restating) ? [" (", anCount(run, "analysis_sentences_restating"), " of them restating a threshold, which is not checked as a fact)"] : "",
    "; ",
    anCount(run, "analysis_sentences_unverified"),
    " shown as not verified; ",
    anCount(run, "analysis_sentences_cut"),
    " cut.",
  );
}

/** A link that selects a claim in the rail. */
function claimLink(id, text = id) {
  return h("a", {
    class: "claim-id an-claim-link",
    href: "#workspace",
    title: str(state.ctx?.claims.get(id)?.text) || null,
    "data-goto-claim": id,
    onclick: (event) => {
      if (!workspaceOn()) return;
      event.preventDefault();
      select(id);
    },
    text,
  });
}

/** The headline figures of the record (`Run.analysis.headline`), one cell each; a cell reads its figure or its test in the inspector. */
function headlineCells(run) {
  const series = list(run.series);
  return list(run.analysis?.headline).map((item) => {
    const id = str(item?.id);
    const metric = item?.source === "metric" ? state.ctx?.metrics.get(id) : null;
    const target = item?.source === "computed_test" ? citeTarget(id) : null;
    const pickId = metric ? `figure:${id}` : target ? `${target.kind}:${target.id}` : "";
    const claims = list(item?.claim_ids).map(String);
    const label = str(item?.label);
    return h(
      "tr",
      { class: "hl-row", "data-headline": id, "data-headline-source": str(item?.source), "data-tape-metric": metric ? id : null, "data-pick": pickId || null },
      h(
        "th",
        { scope: "row" },
        pickId ? h("button", { type: "button", class: "linklike hl-open", "data-pick-button": "", text: label }) : h("span", { class: "hl-open", text: label }),
        str(item?.period_label) ? h("span", { class: "hl-period", text: item.period_label }) : "",
      ),
      h("td", { class: "hl-spark" }, metric ? sparkline(metric, series) : item?.source === "computed_test" ? h("span", { class: "hl-src", text: "computed test" }) : ""),
      h("td", { class: `num hl-value fig-value${signClass(str(item?.display))}`, "data-headline-value": "", text: str(item?.display) }),
      h("td", { class: "hl-claims", "data-th": "Claims", text: claims.join(" ") }),
    );
  });
}

/** The headline figures as a small ledger: the figure and its period, its series, its value, and the claims that turn on it. */
function headlineTable(run) {
  const rows = headlineCells(run);
  if (!rows.length) return "";
  return h("table", { class: "an-table hl-table" }, h("thead", { class: "visually-hidden" }, h("tr", null, ["Figure", "Series", "Value", "Claims"].map((text) => h("th", { scope: "col", text })))), h("tbody", null, rows));
}

/** One analytic: the question it answers, its value and its reading in a sentence; a note when the record has one (for an unavailable one, why). */
function analyticRow(item) {
  const off = item?.available === false;
  const question = str(item?.question);
  const display = str(item?.display) || "n/a";
  return h(
    "li",
    { class: `an-row${off ? " is-na" : ""}`, "data-analytic": str(item?.id), "data-available": String(!off), "data-pick": `analytic:${str(item?.id)}` },
    h("button", { type: "button", class: "chip chip-analytic an-ref", "data-pick-button": "", title: "Read its formula and inputs", text: state.ctx.analyticRef.get(item?.id) ?? "" }),
    h("div", { class: "an-q" }, h("p", { class: "an-question", text: question || str(item?.label) }), question ? h("p", { class: "an-label", text: str(item?.label) }) : ""),
    h("p", { class: `an-value${signClass(display)}`, "data-analytic-value": "", text: display }),
    str(item?.reading) ? h("p", { class: "an-reading", "data-analytic-reading": "", text: item.reading }) : "",
    str(item?.note) ? h("p", { class: `an-note${off ? " an-why" : ""}`, "data-analytic-note": "", text: item.note }) : "",
  );
}

/**
 * Analytics grouped by where their data came from, in the providers' order. A provider that
 * gave nothing on this run is named with the record's reason, not left out.
 */
function analyticGroups(run, items) {
  const analysis = run.analysis;
  const failed = list(analysis.providers_failed).map(String);
  const known = AN_PROVIDERS.map(([id]) => id);
  const others = [...new Set([...items.map((item) => str(item?.provider)), ...failed])].filter((id) => id && !known.includes(id));
  const out = [];
  for (const [id, code, title, what] of [...AN_PROVIDERS, ...others.map((id) => [id, "ANL", id, ""])]) {
    const mine = items.filter((item) => str(item?.provider) === id);
    const isFailed = failed.includes(id);
    if (!mine.length && !isFailed) continue;
    out.push(
      h(
        "section",
        { class: `an-block an-group${isFailed ? " is-failed" : ""}`, "data-an-block": "analytics", "data-provider": id },
        h("h3", { class: "block-title", "data-code": code, text: title }),
        h("p", { class: "an-by", "data-by": "code" }, ruleMark("Computed by code"), what ? h("span", { class: "an-what", text: ` ${what}` }) : ""),
        isFailed ? h("p", { class: "an-failed", "data-provider-failed": id }, limitGlyph(), " Not available on this run: ", str(analysis.provider_reasons?.[id]) || "the record gives no reason.") : "",
        mine.length ? h("ul", { class: "an-rows" }, mine.map(analyticRow)) : "",
      ),
    );
  }
  return out;
}

/** A threshold as the record gives it, with its unit's sign. Formatting only. */
function thresholdText(item) {
  const comparison = str(item?.comparison);
  if (!comparison || comparison === "none" || !Number.isFinite(item?.threshold)) return "";
  const value = item.threshold.toLocaleString("en-US", { maximumFractionDigits: 20 });
  const unitName = str(item.unit);
  const shown = unitName === "percent" ? `${value}%` : unitName === "USD" ? `$${value}` : unitName && unitName !== "none" ? `${value} ${unitName}` : value;
  return `${comparison} ${shown}`;
}

/** What would change the verdict: each observable with its measure, comparison and threshold, or the category of 8-K. */
function wouldChangeTable(items, scope) {
  const rows = list(items);
  if (!rows.length) return h("p", { class: "muted an-none", text: "The argument names nothing that would change the verdict." });
  return h(
    "div",
    { class: "table-wrap", tabindex: "0", role: "region", "aria-label": "What would change the verdict" },
    h(
      "table",
      { class: "an-table an-change" },
      h("thead", null, h("tr", null, ["What to watch for", "Measure", "Threshold", "or an 8-K about"].map((text) => h("th", { scope: "col", text })))),
      h(
        "tbody",
        null,
        rows.map((item) =>
          h(
            "tr",
            { "data-would-change": "" },
            h("td", { class: "an-change-text" }, anSentence(item, "what would change the verdict", scope)),
            h("td", { "data-th": "Measure" }, str(item?.measure) ? h("code", { text: item.measure }) : h("span", { class: "muted", text: "—" })),
            h("td", { class: "num", "data-th": "Threshold", text: thresholdText(item) || "—" }),
            h("td", { "data-th": "or an 8-K about", text: str(item?.event_category) || "—" }),
          ),
        ),
      ),
    ),
  );
}

/** A claim's corollaries: what else would be true, what was expected, how it came out, who read it, and its status in words. */
function corollariesBlock(run, claim, ca) {
  const analysis = run.analysis;
  const items = list(ca.corollaries);
  const step = str(analysis.corollaries_step);
  const by = str(analysis.corollaries_by);
  const head = [
    h("p", { class: "an-by", "data-by": by ? "model" : "code" }, by ? modelBadge(`Proposed by ${by}`) : "", by ? " " : "", ruleMark("each computed by code from the facts")),
    str(ca.corollary_flag) ? h("p", { class: "an-flag", "data-corollary-flag": "" }, limitGlyph(), ` ${ca.corollary_flag}`) : "",
  ];
  if (!items.length) {
    const why = str(analysis.corollaries_note) || (step && step !== "answered" ? `The request for corollaries was ${AN_STEP[step] ?? step}.` : "None was proposed for this claim.");
    return anBlock("COR", "Corollaries: what else would be true", "corollaries", h("p", { class: "an-none muted", "data-corollaries-note": "", text: why }));
  }
  return anBlock(
    "COR",
    "Corollaries: what else would be true",
    "corollaries",
    ...head,
    h(
      "div",
      { class: "table-wrap", tabindex: "0", role: "region", "aria-label": `Corollaries of claim ${claim.id}` },
      h(
        "table",
        { class: "an-table an-cor" },
        h("thead", null, h("tr", null, ["If the claim is true", "Expected", "Result", "Who read it", "Status"].map((text) => h("th", { scope: "col", text })))),
        h(
          "tbody",
          null,
          items.map((cor) => {
            const test = cor?.computed && typeof cor.computed === "object" ? cor.computed : null;
            const result = token(cor?.result, COR_RESULT);
            return h(
              "tr",
              { "data-corollary": str(cor?.id), "data-result": str(cor?.result), "data-pick": `corollary:${str(cor?.id)}` },
              h("td", { class: "an-cor-text" }, citeChip(cor?.id), " ", h("span", { class: "an-cor-sentence", text: str(cor?.sentence) }), str(cor?.why) ? h("span", { class: "an-cor-why", text: ` ${cor.why}` }) : ""),
              h("td", { "data-th": "Expected", text: str(cor?.expect) ? `to ${cor.expect === "holds" ? "hold" : cor.expect === "fails" ? "fail" : cor.expect}` : "—" }),
              h(
                "td",
                { class: `an-cor-result r-${result}`, "data-th": "Result" },
                test ? h("span", { class: "an-cor-sides" }, h("strong", { text: str(test.left?.display) || "—" }), ` ${str(test.comparison)} ${str(test.right?.display)} `, testOutcome(test.outcome, test.outcome_label)) : h("span", { class: "muted", text: "not computed" }),
                h("span", { class: "an-cor-label", "data-result-label": "" }, h("span", { class: "glyph", "aria-hidden": "true", text: `${COR_RESULT[result] ?? "·"} ` }), str(cor?.result_label) || "no result"),
              ),
              h("td", { "data-th": "Who read it", text: str(cor?.read_by) || "—" }),
              h("td", { "data-th": "Status", "data-status": str(cor?.status), text: COR_STATUS[cor?.status] ?? (str(cor?.status).replaceAll("_", " ") || "—") }),
            );
          }),
        ),
      ),
    ),
    str(analysis.corollary_rule) ? h("p", { class: "hint an-rule", text: analysis.corollary_rule }) : "",
  );
}

/** The odds that a claim's test keeps holding, with the record's caveat always beside it; or why there are none. */
function persistenceBlock(ca) {
  const odds = ca.persistence;
  if (!odds || typeof odds !== "object") return "";
  const on = odds.applicable === true;
  return h(
    "section",
    { class: `an-block an-odds${on ? "" : " is-na"}`, "data-an-block": "odds", "data-odds-id": str(odds.id), "data-pick": on ? `odds:${str(odds.id)}` : null },
    h("h3", { class: "block-title", "data-code": "ODD", text: "Will it keep holding? The test's own history, resampled" }),
    on
      ? [
          h("p", { class: "an-by", "data-by": "code" }, ruleMark("Resampled by code from the measure's own past changes")),
          h("p", { class: "an-odds-line" }, h("span", { class: "an-odds-value", "data-odds": "", text: str(odds.display) }), h("span", { class: "an-odds-note", text: ` ${str(odds.note)}` })),
          str(odds.warning) ? h("p", { class: "an-flag", "data-odds-warning": "" }, limitGlyph(), ` ${odds.warning}`) : "",
          h("p", { class: "an-caveat", "data-odds-caveat": "" }, limitGlyph(), ` ${str(odds.caveat) || "A description of the measure's history; not a forecast."}`),
          h("p", { class: "an-pick" }, pickButton("How the odds were made")),
        ]
      : h("p", { class: "an-none muted", "data-odds-none": "", text: str(odds.note) || "No odds were computed for this claim." }),
  );
}

/** The whole thesis's analysis: the bottom line first, then what it leans on, the cases, the scenarios, the figures and what the price implies. */
function analysisThesis(run) {
  const analysis = run.analysis;
  const scope = "";
  const th = analysis.thesis && typeof analysis.thesis === "object" ? analysis.thesis : null;
  const stateNote = argumentState(analysis);
  const out = [];
  const table = headlineTable(run);
  const keyFigures = table
    ? h(
        "section",
        { class: "an-block an-key", "data-an-block": "headline" },
        h("h3", { class: "block-title", "data-code": "KEY", text: "Headline figures" }),
        table,
        str(analysis.headline_note) ? h("p", { class: "hint", "data-headline-note": "", text: analysis.headline_note }) : "",
      )
    : str(analysis.headline_note)
      ? h("p", { class: "hint", "data-headline-note": "", text: analysis.headline_note })
      : "";
  if (stateNote) out.push(stateNote);
  if (th) {
    const weakest = str(th.weakest_link);
    const leans = list(th.leans_on).map(String);
    out.push(
      h(
        "div",
        { class: "an-top" },
        anBlock("BTM", "Bottom line", "bottom", anBy("model", argumentBy(analysis)), anLead(th.bottom_line, "the bottom line", scope) || h("p", { class: "muted an-none", text: "The argument gives no bottom line." })),
        keyFigures,
      ),
      anPart(
        "What the thesis leans on",
        "leans",
        leans.length
          ? h(
              "ol",
              { class: "lean-list" },
              leans.map((id) => {
                const claim = state.ctx.claims.get(id);
                return h(
                  "li",
                  { class: `lean-row${id === weakest ? " is-weakest" : ""}`, "data-lean-claim": id },
                  claimLink(id),
                  claim ? verdictPill(claim.verdict) : "",
                  claim?.analysis?.argument ? h("span", { class: "lean-arg" }, "argument ", leanPill(claim.analysis.argument.lean)) : "",
                  claim ? "" : h("span", { class: "lean-text muted", text: "not a claim of this run" }),
                  id === weakest ? h("span", { class: "lean-weakest", "data-weakest": "", text: "Weakest link" }) : "",
                );
              }),
            )
          : h("p", { class: "muted an-none", text: "The argument does not order the claims." }),
        weakest ? h("h4", { class: "an-sub", text: `Why ${weakest} is the weakest link` }) : "",
        ...anParas(th.weakest_why, "why it is the weakest link", scope),
      ),
      h(
        "div",
        { class: "an-versus" },
        anPart("The strongest case for", "for", anPoints(th.strongest_for, "the strongest case for", scope)),
        anPart("The strongest case against", "against", anPoints(th.strongest_against, "the strongest case against", scope)),
      ),
      anPart(
        "Scenarios, as conditions you can observe",
        "scenarios",
        list(th.scenarios).length
          ? h(
              "div",
              { class: "an-scn-grid" },
              list(th.scenarios).map((scenario) => h("article", { class: "an-scenario", "data-scenario": str(scenario?.name) }, h("h4", { class: "an-sub", text: str(scenario?.name) || "Scenario" }), anPoints(scenario?.conditions, `the scenario "${str(scenario?.name)}"`, scope, "ol", "an-conds"))),
            )
          : h("p", { class: "muted an-none", text: "The argument gives no scenario." }),
      ),
    );
  } else {
    out.push(keyFigures);
  }
  out.push(...analyticGroups(run, list(analysis.analytics).filter((item) => item?.scope === "company")));
  const flags = list(analysis.flags).map(String);
  if (flags.length)
    out.push(
      anBlock(
        "FLG",
        "Flags",
        "flags",
        h(
          "ul",
          { class: "mark-list" },
          flags.map((flag) => limitLine("li", flag)),
        ),
      ),
    );
  out.push(analysisMade(run));
  return out;
}

/** How the analysis was made, in words: who wrote the argument, who proposed the corollaries, what code computed, and the audit's counts. */
function analysisMade(run) {
  const analysis = run.analysis;
  const c = run.coverage ?? {};
  const fact = (label, ...value) => h("div", null, h("dt", { text: label }), h("dd", null, ...value));
  const step = (value) => AN_STEP[value] ?? (str(value) || "not recorded");
  const asked = list(analysis.providers).map(String);
  const failed = list(analysis.providers_failed).map(String);
  const name = (id) => AN_PROVIDERS.find(([key]) => key === id)?.[2] ?? id;
  const notAsked = AN_PROVIDERS.map(([id]) => id).filter((id) => !asked.includes(id));
  return anBlock(
    "HOW",
    "How this analysis was made",
    "made",
    h(
      "dl",
      { class: "an-made-grid" },
      fact(
        "The argument",
        h("span", { "data-made": "argument" }, str(analysis.argument_step) === "not_asked" ? "No model was asked." : `${capitalize(step(analysis.argument_step))}${str(analysis.argument_detail) ? `, by ${analysis.argument_detail}` : ""}.`),
        Number.isFinite(analysis.argument_claims_asked) && str(analysis.argument_step) !== "not_asked" ? [" ", h("span", { "data-made": "argued" }, `${num(analysis.argument_claims_answered)} of ${num(analysis.argument_claims_asked)} claims argued; the whole thesis ${step(analysis.thesis_step)}.`)] : "",
      ),
      Number.isFinite(c.analysis_sentences_written) && str(analysis.argument_step) !== "not_asked" ? fact("Its sentences", auditLine(run)) : "",
      // What "verified" means is the record's own rule, word for word.
      str(analysis.audit_rule) && str(analysis.argument_step) !== "not_asked" ? fact("The audit's rule", h("span", { "data-audit-rule": "", text: analysis.audit_rule })) : "",
      fact(
        "The corollaries",
        str(analysis.corollaries_step) === "not_asked" ? str(analysis.corollaries_note) || "No model was asked to propose any." : `${capitalize(step(analysis.corollaries_step))}${str(analysis.corollaries_by) ? `: proposed by ${analysis.corollaries_by}` : ""}; each computed by code.`,
        Number.isFinite(c.corollaries_proposed) && str(analysis.corollaries_step) !== "not_asked" ? [" ", anCount(run, "corollaries_computed"), " of ", anCount(run, "corollaries_proposed"), " computed: ", anCount(run, "corollaries_as_expected"), " as the claim implies, ", anCount(run, "corollaries_against"), " against."] : "",
      ),
      fact(
        "The analytics",
        `Computed by ${str(analysis.analytics_by) || "code"}`,
        Number.isFinite(c.analytics_computed) ? [": ", anCount(run, "analytics_computed"), " computed, ", anCount(run, "analytics_unavailable"), " not available."] : ".",
        asked.length ? ` Asked: ${asked.map(name).join("; ")}.` : "",
        failed.length ? h("span", { class: "an-failed", "data-providers-failed": failed.join(" ") }, " ", limitGlyph(), ` Gave nothing: ${failed.map((id) => `${name(id)} (${str(analysis.provider_reasons?.[id]) || "no reason recorded"})`).join("; ")}.`) : "",
        notAsked.length ? h("span", { class: "muted", "data-providers-not-asked": notAsked.join(" ") }, ` Not asked on this run: ${notAsked.map(name).join("; ")}.`) : "",
      ),
      str(analysis.breakdowns_note) ? fact("Parts of the business", analysis.breakdowns_note) : "",
    ),
    h("p", { class: "an-pick an-to-method" }, h("button", { type: "button", class: "linklike", "data-goto-tab": "method", onclick: () => setTab("method", { focus: true }), text: "See the run's pipeline, stage by stage, on the Method tab" })),
  );
}

/** One claim's analysis: how it bears on the decision, the cases, what decides it, what would change the verdict, then what code computed. */
function analysisClaim(run, claim) {
  const analysis = run.analysis;
  const ca = claim.analysis && typeof claim.analysis === "object" ? claim.analysis : {};
  const arg = ca.argument && typeof ca.argument === "object" ? ca.argument : null;
  const scope = claim.id;
  // On a screen the centre pane's head names the claim, its verdict and its lean; on paper and on the specimen this heading does.
  const out = [
    h(
      "div",
      { class: "an-claim-head" },
      h("h3", { class: "an-claim-title" }, h("span", { class: "claim-id", text: claim.id }), " ", str(claim.text)),
      arg ? h("p", { class: "an-leanline", "data-lean-line": "" }, verdictPill(claim.verdict), h("span", { class: "an-leanline-arg", text: "the argument" }), leanPill(arg.lean)) : "",
    ),
  ];
  if (arg) {
    out.push(
      anBlock(
        "ASM",
        "How it bears on the decision",
        "assessment",
        anBy("model", argumentBy(analysis)),
        str(arg.lean_flag) ? h("p", { class: "an-flag", "data-lean-flag": "" }, limitGlyph(), ` ${arg.lean_flag}`) : "",
        anLead(arg.assessment, "the assessment", scope),
      ),
      h("div", { class: "an-versus" }, anPart("The case for", "for", anPoints(arg.case_for, "the case for", scope)), anPart("The case against", "against", anPoints(arg.case_against, "the case against", scope))),
      // A part the argument left empty is not printed as a blank.
      list(arg.decides).length ? anPart("What decides it", "decides", anPoints(arg.decides, "what decides it", scope)) : "",
      anBlock("CHG", "What would change the verdict", "change", wouldChangeTable(arg.would_change, scope)),
    );
  } else {
    const step = str(analysis.argument_step);
    const why = str(ca.argument_note) || str(analysis.argument_note) || "The record gives no reason.";
    out.push(
      step === "not_asked"
        ? h("div", { class: "an-state an-state-none", "data-argument-step": step }, h("p", { class: "an-state-lead", text: "Computed analysis only: no model argued this claim." }), h("p", { class: "an-state-note", "data-argument-note": "", text: why }))
        : h("div", { class: "an-state an-state-limit", "data-argument-step": step, "data-claim-unargued": claim.id }, limitLine("p", "This claim has no argument."), h("p", { class: "an-state-note", "data-argument-note": "", text: why })),
    );
  }
  const mine = list(ca.analytic_ids)
    .map((id) => state.ctx.analytics.get(id))
    .filter(Boolean);
  out.push(...analyticGroups(run, mine));
  if (!mine.length && !list(analysis.providers_failed).length) out.push(h("p", { class: "an-none muted", "data-relevance-note": "", text: str(ca.relevance_note) || "No analytic is tied to this claim." }));
  out.push(corollariesBlock(run, claim, ca), persistenceBlock(ca));
  return out;
}

/** Draw the analysis of the whole thesis and of every claim; the selection shows one of them (`applySelection`). */
function renderAnalysis(run) {
  if (!els.analysis) return;
  if (!hasAnalysis(run)) {
    els.analysis.replaceChildren();
    return;
  }
  state.ctx.sentences.clear();
  state.ctx.firstSentence.clear();
  els.analysis.replaceChildren(
    h("div", { class: "an-scope", "data-an-scope": "" }, ...analysisThesis(run)),
    ...list(run.claims).map((claim) => h("div", { class: "an-scope", "data-an-scope": claim.id }, ...analysisClaim(run, claim))),
  );
}

// ---- the analysis in the inspector

/** A sentence and what it rests on: the audit's word on it, then each thing it cites, in brief, each opening in full. */
function inspectSentence(key) {
  const entry = state.ctx.sentences?.get(key);
  if (!entry) return null;
  const { sentence, where, scope } = entry;
  const verified = sentence?.verified === true;
  const problems = list(sentence?.problems).map(String).filter(Boolean);
  const cites = list(sentence?.cites);
  const thresholds = sentenceThresholds(sentence);
  const rule = str(state.run.analysis?.audit_rule);
  return [
    inspectHead("Sentence", `of ${where}${scope ? `, claim ${scope}` : ""}`),
    h("blockquote", { class: "ins-sentence", text: str(sentence?.text) }),
    verified
      ? h("p", { class: "ins-audit", "data-audit": thresholds.length ? "verified-restating" : "verified" }, ruleMark("Verified by code"), thresholds.length ? ", with a threshold restated." : ".")
      : h("div", { class: "ins-audit is-unverified", "data-audit": "unverified" }, limitLine("p", "Not verified by the audit. It is shown, not hidden; read it as unchecked."), problems.length ? h("ul", { class: "mark-list" }, problems.map((line) => limitLine("li", line))) : ""),
    thresholds.length
      ? h(
          "ul",
          { class: "ins-thresholds", "data-ins-thresholds": "" },
          thresholds.map((item) => h("li", { "data-threshold": str(item.raw), "data-threshold-of": str(item.of), text: thresholdWords(item) })),
        )
      : "",
    h("p", { class: "label", text: cites.length ? "What it rests on" : "It cites nothing" }),
    h(
      "ul",
      { class: "ins-rests" },
      cites.map((id) => {
        const target = citeTarget(id);
        if (!target) return h("li", { class: "ins-rest is-missing" }, h("code", { text: String(id) }), h("span", { class: "muted", text: " The record holds nothing under this id." }));
        return h(
          "li",
          { class: "ins-rest", "data-rest": String(id) },
          h("p", { class: "ins-rest-head" }, h("span", { class: "ins-rest-kind", text: target.what }), " ", h("button", { type: "button", class: "linklike", onclick: () => pick({ kind: target.kind, id: target.id }), text: `Open ${target.label}` })),
          str(target.line) ? h("p", { class: "ins-rest-line", text: target.line }) : "",
        );
      }),
    ),
    // What the audit checks, and what it does not, in the record's own words: the page writes no rule of its own.
    h(
      "div",
      { class: "ins-block ins-rule" },
      h("p", { class: "label", text: "What the audit checks" }),
      rule ? h("p", { class: "ins-note", "data-audit-rule": "", text: rule }) : h("p", { class: "ins-note muted", "data-audit-rule-missing": "", text: "This record does not carry the audit's rule: it was made before runs recorded it." }),
    ),
  ];
}

/** One analytic whole: its value and reading, its formula, every input with the filing it came from, and its note. */
function inspectAnalytic(id) {
  const item = state.ctx.analytics?.get(id);
  if (!item) return null;
  const cik = state.run.company?.cik;
  const provider = AN_PROVIDERS.find(([key]) => key === str(item.provider));
  const inputs = list(item.inputs);
  const fact = (label, ...value) => h("div", null, h("dt", { text: label }), h("dd", null, ...value));
  const origin = { sec_xbrl_facts: "SEC XBRL facts of the company", sec_frames: "SEC frames (every filer), from the reference pack", market_prices: "A recorded price, with the company's facts" }[item.data_origin] ?? str(item.data_origin);
  return [
    inspectHead(`Analytic ${state.ctx.analyticRef.get(id) ?? ""}`, provider ? provider[2] : str(item.provider), ruleMark("Computed by code")),
    h("p", { class: "ins-figure" }, h("span", { class: "ins-figure-label", text: str(item.label) }), h("span", { class: `fig-value ins-figure-value${signClass(str(item.display))}`, text: str(item.display) || "n/a" })),
    str(item.question) ? h("p", { class: "ins-question", text: item.question }) : "",
    str(item.reading) ? h("p", { class: "ins-reading", text: item.reading }) : "",
    h(
      "dl",
      { class: "ins-grid" },
      str(item.formula) ? fact("Formula", h("code", { class: "ins-formula", text: item.formula })) : "",
      str(item.period) ? fact("Period", item.period) : "",
      str(item.measure) ? fact("Measure", h("code", { text: item.measure })) : "",
      origin ? fact("Data", origin) : "",
      list(item.claim_ids).length ? fact("Bears on", list(item.claim_ids).join(", ")) : "",
    ),
    inputs.length
      ? h(
          "div",
          { class: "ins-block" },
          h("p", { class: "label", text: "What it was computed from" }),
          h(
            "ul",
            { class: "ins-inputs" },
            inputs.map((ref) =>
              h(
                "li",
                null,
                h("span", { class: "ins-input-label", text: str(ref?.label) || str(ref?.id) }),
                h("span", { class: "ins-input-value", text: str(ref?.display) }),
                h(
                  "span",
                  { class: "ins-input-src" },
                  str(ref?.accession) ? filingRef(ref, cik) : ref?.ref_kind === "frame" ? h("code", { text: str(ref?.id) }) : str(ref?.filed) ? `${str(ref?.form) || "filed"} ${dateLabel(ref.filed)}` : ref?.ref_kind === "computed_test" ? "from the claim's computed test" : str(ref?.ref_kind).replaceAll("_", " "),
                ),
              ),
            ),
          ),
        )
      : "",
    str(item.note) ? h("div", { class: "ins-block" }, h("p", { class: "label", text: item.available === false ? "Why it is not available" : "Note" }), h("p", { class: "ins-note", text: item.note })) : "",
  ];
}

/** One corollary whole: the implication and why it follows, how each reader read it, and the test code computed with its values and arithmetic. */
function inspectCorollary(id) {
  const cor = state.ctx.corollaries?.get(id);
  if (!cor) return null;
  const test = cor.computed && typeof cor.computed === "object" ? cor.computed : null;
  const fact = (label, ...value) => h("div", null, h("dt", { text: label }), h("dd", null, ...value));
  const expr = (text, reason) => (str(text) ? h("code", { text }) : h("span", { class: "muted", text: str(reason) || "read no test" }));
  return [
    inspectHead("Corollary", `of claim ${str(cor.claim_id)}`, modelBadge("Proposed by a model"), ruleMark("computed by code")),
    h("blockquote", { class: "ins-sentence", text: str(cor.sentence) }),
    str(cor.why) ? h("p", { class: "ins-reading", text: cor.why }) : "",
    h(
      "dl",
      { class: "ins-grid" },
      fact("Expected", str(cor.expect) || "—"),
      fact("Result", str(cor.result_label) || "—"),
      fact("The grammar read", expr(cor.grammar, cor.grammar_reason)),
      fact("The model read", expr(cor.proposer, cor.proposer_reason)),
      fact("Who read it", str(cor.read_by) || "—"),
    ),
    test
      ? h(
          "div",
          { class: "ct-inspected" },
          h("p", { class: "ct-result" }, testOutcome(test.outcome, test.outcome_label), str(test.margin_display) ? h("span", { class: "muted", text: ` margin ${test.margin_display}` }) : ""),
          str(test.reason) ? h("p", { class: "ct-reason" }, h("span", { class: "label", text: "Why it could not be computed: " }), test.reason) : "",
          operandTable(list(test.operands), state.run.company?.cik, `Values read for the corollary`),
          list(test.arithmetic).length ? h("div", { class: "ct-arith-block" }, h("p", { class: "label", text: "The arithmetic" }), arithmeticList(list(test.arithmetic))) : "",
        )
      : h("p", { class: "muted", text: "No test was computed for this corollary." }),
  ];
}

/** The persistence odds whole: the number, what it is of, the caveat, and the method with its settings. */
function inspectOdds(id) {
  const odds = state.ctx.odds?.get(id);
  if (!odds) return null;
  const fact = (label, ...value) => h("div", null, h("dt", { text: label }), h("dd", null, ...value));
  return [
    inspectHead("Persistence odds", `of claim ${str(odds.claim_id)}'s test`, ruleMark("Resampled by code")),
    h("p", { class: "ins-figure" }, h("span", { class: "ins-figure-label", text: "Share of resampled paths in which the test kept holding" }), h("span", { class: "fig-value ins-figure-value", text: str(odds.display) || "n/a" })),
    str(odds.note) ? h("p", { class: "ins-reading", text: odds.note }) : "",
    str(odds.caveat) ? limitLine("p", odds.caveat) : "",
    h(
      "dl",
      { class: "ins-grid" },
      str(odds.test) ? fact("The test", h("code", { text: odds.test })) : "",
      str(odds.start_display) ? fact("Starts from", odds.start_display) : "",
      Number.isFinite(odds.horizon) ? fact("Quarters ahead", num(odds.horizon)) : "",
      Number.isFinite(odds.changes) ? fact("Past changes drawn from", num(odds.changes)) : "",
      Number.isFinite(odds.paths) ? fact("Paths", num(odds.paths)) : "",
      Number.isFinite(odds.seed) ? fact("Seed", String(odds.seed)) : "",
    ),
    str(odds.method) || str(state.run.analysis?.persistence_method) ? h("div", { class: "ins-block" }, h("p", { class: "label", text: "Method" }), h("p", { class: "ins-note", text: str(odds.method) || state.run.analysis.persistence_method })) : "",
  ];
}

// ---------------------------------------------------------------- the method: this run's pipeline
//
// The stages a run goes through, drawn as a diagram: each marked as code or as a model (which
// depends on how this run was made), with this run's own counts from `run.coverage` and, when
// the record has them, each stage's wall time from `run.timings`. Drawing only.

/** One count of the record on a stage. */
function mCount(run, field) {
  return Number.isFinite(run.coverage?.[field]) ? cov(run.coverage, field) : null;
}

/** Words and counts joined into a line; a part whose count the record lacks is left out. */
function mLine(...parts) {
  const out = [];
  for (const part of parts) {
    if (!part || part.some((piece) => piece === null)) continue;
    if (out.length) out.push(" · ");
    out.push(...part);
  }
  return out;
}

/** The stages of a run, in four phases. `stage` is the name `run.timings` gives the stage. */
function methodPhases(run) {
  const analysis = hasAnalysis(run) ? run.analysis : null;
  const modelEngine = str(run.engine) !== "" && run.engine !== EXTRACTIVE;
  const engine = modelEngine ? ["model", str(run.engine_detail) || str(run.engine)] : ["code", str(run.engine_detail) || "sentence matching, no model"];
  const checker = str(run.checker) && run.checker !== "none" ? str(run.checker_detail) || run.checker : "";
  const modelReaders = /model/.test(str(run.claim_readers));
  const events = list(run.timeline).length;
  const phases = [
    {
      name: "Read",
      what: "what the company filed",
      nodes: [
        { stage: "company", name: "Company", does: "The ticker is matched to SEC's registrant.", by: ["code", ""], line: [[`${str(run.company?.name) || "the company"}${str(run.company?.ticker) ? ` (${run.company.ticker})` : ""}`]] },
        { stage: "filings", name: "Filings", does: "The newest annual and quarterly reports are fetched and cut into passages.", by: ["code", ""], line: [[mCount(run, "sources_read"), " of ", mCount(run, "sources_requested"), " sources read"], [mCount(run, "passages_indexed"), " passages"]] },
        { stage: "events", name: "Current reports", does: "The 8-Ks filed since the annual report are listed and split into items.", by: ["code", ""], line: [[h("span", { "data-method-events": "", text: num(events) }), " 8-Ks listed"]] },
        { stage: "numbers", name: "Reported figures", does: "Figures are computed from the XBRL facts, each with its formula and inputs.", by: ["code", ""], line: [[mCount(run, "metrics_computed"), " figures"], [mCount(run, "periods_checked"), " periods checked"]] },
      ],
    },
    {
      name: "Test",
      what: "each claim against the facts",
      nodes: [
        {
          stage: "computed tests and claim readers",
          name: "Claim readers and computed tests",
          does: "A fixed grammar and, when the run has them, model readers turn each claim into a test; code computes it from the facts.",
          by: [modelReaders ? "both" : "code", modelReaders ? str(run.claim_reader_detail) : "the grammar only"],
          line: [
            [mCount(run, "claims_compiled"), " of ", mCount(run, "claims_total"), " claims became a test"],
            [mCount(run, "computed_holds"), " hold, ", mCount(run, "computed_fails"), " fail, ", mCount(run, "computed_cannot"), " cannot be computed"],
          ],
        },
      ],
    },
    {
      name: "Find",
      what: "passages for and against",
      nodes: [
        { stage: "planning", name: "Planning", does: "Search queries are written for each claim.", by: engine, line: [] },
        { stage: "retrieving", name: "Retrieving", does: "Passages are ranked against the queries by keyword.", by: ["code", ""], line: [[mCount(run, "passages_indexed"), " passages searched"]] },
        { stage: "assessing", name: "Assessing", does: "Findings are drafted, each with a stance and the quotes it rests on.", by: engine, line: [[mCount(run, "findings_proposed"), " findings proposed"], [mCount(run, "quotes_offered"), " quotes offered"]] },
        {
          stage: "verifying",
          name: "Verifying",
          does: "Each quote is searched for word for word in its filing, each number checked against the figures. What fails is withheld.",
          by: [checker ? "both" : "code", checker ? `meaning checked by ${checker}` : ""],
          line: [
            [mCount(run, "quotes_found"), " of ", mCount(run, "quotes_offered"), " quotes found"],
            [mCount(run, "findings_verified"), " findings verified, ", mCount(run, "findings_withheld"), " withheld"],
            [mCount(run, "numbers_checked"), " numbers checked"],
          ],
        },
        { stage: "summary", name: "Summary", does: "The summary is written from the verified findings.", by: engine, line: [] },
      ],
    },
  ];
  if (!analysis) {
    phases.push({ name: "Analyse", what: "what follows from it", nodes: [], none: "This record has no analysis: it was made before the run kept one." });
    return phases;
  }
  const asked = list(analysis.providers).map(String);
  const failed = list(analysis.providers_failed).map(String);
  const provider = (id, name, does) => {
    const stateOf = failed.includes(id) ? "failed" : asked.includes(id) ? "ran" : "skipped";
    return {
      stage: `analytics: ${id}`,
      name,
      does,
      by: ["code", ""],
      state: stateOf,
      line: stateOf === "failed" ? [[`gave nothing: ${str(analysis.provider_reasons?.[id]) || "no reason recorded"}`]] : stateOf === "skipped" ? [["not asked on this run"]] : [[h("span", { "data-method-analytics": id, text: num(list(analysis.analytics).filter((item) => item?.provider === id).length) }), " analytics"]],
    };
  };
  const stepState = (step) => (step === "not_asked" ? "skipped" : step === "failed" ? "failed" : "ran");
  const stepWords = (step) => (step === "not_asked" ? [["not asked on this run"]] : step === "failed" ? [["asked and failed"]] : null);
  phases.push({
    name: "Analyse",
    what: "what follows from it",
    nodes: [
      provider("facts", "Analytics: own filings", "Trends, bridges, earnings quality and the room of each test, from the company's facts."),
      provider("outside_view", "Analytics: outside view", "Base rates of each test and the company's rank among its industry, from SEC's frames."),
      provider("market_view", "Analytics: market view", "What a recorded price implies: earnings multiple, cash yield, reverse DCF."),
      {
        stage: "corollaries: proposed by the model",
        name: "Corollaries proposed",
        does: "For each claim, what else would be true if it were.",
        by: ["model", str(analysis.corollaries_by)],
        state: stepState(str(analysis.corollaries_step)),
        line: stepWords(str(analysis.corollaries_step)) ?? [[mCount(run, "corollaries_proposed"), " proposed"]],
      },
      {
        stage: "corollaries: computed",
        name: "Corollaries computed",
        does: "Each corollary is read into a test and computed from the facts.",
        by: ["code", ""],
        state: stepState(str(analysis.corollaries_step)),
        line: stepWords(str(analysis.corollaries_step)) ?? [
          [mCount(run, "corollaries_computed"), " computed"],
          [mCount(run, "corollaries_as_expected"), " as implied, ", mCount(run, "corollaries_against"), " against"],
        ],
      },
      {
        stage: "argument: the claims",
        name: "Argument: each claim",
        does: "One request per claim: how it bears on the decision, the cases, what decides it.",
        by: ["model", str(analysis.argument_detail)],
        state: stepState(str(analysis.argument_step)),
        line: stepWords(str(analysis.argument_step)) ?? [[mCount(run, "analysis_claims_answered"), " of ", mCount(run, "analysis_claims_asked"), " claims argued"]],
      },
      {
        stage: "argument: the thesis",
        name: "Argument: the thesis",
        does: "One request for the whole: bottom line, weakest link, scenarios.",
        by: ["model", str(analysis.argument_detail)],
        state: stepState(str(analysis.thesis_step) || str(analysis.argument_step)),
        line: stepWords(str(analysis.thesis_step) || str(analysis.argument_step)) ?? [[`the request was ${AN_STEP[analysis.thesis_step] ?? "answered"}`]],
      },
      {
        stage: "",
        name: "Audit of the sentences",
        does: str(analysis.audit_rule) || "Each sentence of the argument is audited by code.",
        by: ["code", ""],
        state: stepState(str(analysis.argument_step)),
        line: stepWords(str(analysis.argument_step)) ?? [
          [mCount(run, "analysis_sentences_verified"), " of ", mCount(run, "analysis_sentences_written"), " sentences verified"],
          [mCount(run, "analysis_sentences_restating"), " restating a threshold"],
          [mCount(run, "analysis_sentences_unverified"), " shown as not verified, ", mCount(run, "analysis_sentences_cut"), " cut"],
        ],
      },
    ],
  });
  return phases;
}

/** The record's wall times by stage name. Entries the page cannot read are skipped. */
function timingsOf(run) {
  const out = new Map();
  for (const item of list(run.timings)) {
    const stage = str(item?.stage) || str(item?.name) || str(item?.id);
    const seconds = Number.isFinite(item?.seconds) ? item.seconds : Number.isFinite(item?.ms) ? item.ms / 1000 : null;
    if (stage && seconds !== null) out.set(stage, { stage, seconds, background: item.background === true, note: str(item.note) });
  }
  return out;
}

/** Seconds as the record gives them. */
function secondsText(seconds) {
  // A time under a millisecond is not written as "0 s".
  if (seconds > 0 && seconds < 0.001) return "<0.001 s";
  return `${seconds.toLocaleString("en-US", { maximumFractionDigits: 3 })} s`;
}

/** One stage of the run whole: what it does, whether code or a model did it and which, this run's counts, and its time. */
function inspectStage(key) {
  const entry = state.ctx.stages?.get(key);
  if (!entry) return null;
  const { item, time } = entry;
  const [by, who] = item.by;
  const fact = (label, ...value) => h("div", null, h("dt", { text: label }), h("dd", null, ...value));
  // The counts are drawn in the stage's box: here they are copies, so the box keeps its own.
  const counts = mLine(...list(item.line)).map((part) => (part instanceof Node ? part.cloneNode(true) : part));
  const stateWords = { ran: "Ran on this run", skipped: "Not asked for on this run", failed: "Asked for, and failed" }[item.state ?? "ran"];
  return [
    inspectHead("Stage", item.name, byTag(by)),
    h("p", { class: "ins-reading", text: item.does }),
    h(
      "dl",
      { class: "ins-grid" },
      fact("State", stateWords),
      who ? fact(by === "code" ? "How" : "Answered by", who) : "",
      counts.length ? fact("This run", ...counts) : "",
      time ? fact("Wall time", secondsText(time.seconds), time.background ? " (in the background, overlapping other stages)" : "") : "",
      time && time.note ? fact("Note", time.note) : "",
    ),
    h("p", { class: "ins-note", text: by === "code" ? "Code: a fixed rule. The same record gives the same result, and the result can be recomputed." : by === "model" ? "A model: a language model's answer, which code then checks before it is shown." : "Code and a model: the fixed rule runs on every run; the model's part is checked by code." }),
  ];
}

/** A stage's time as a bar on the scale of the run's longest stage. Drawing only. */
function timeBar(seconds, longest) {
  const W = 60;
  const width = longest > 0 ? Math.max((seconds / longest) * W, 0.75) : 0;
  return s("svg", { class: "mth-bar", viewBox: `0 0 ${W} 4`, preserveAspectRatio: "none", "aria-hidden": "true", focusable: "false" }, s("rect", { x: 0, y: 0, width: W, height: 4, class: "mth-bar-bg" }), s("rect", { x: 0, y: 0, width: width.toFixed(2), height: 4, class: "mth-bar-fill" }));
}

const BY_WORDS = { code: "Code", model: "Model", both: "Code and model" };

/** Whether a stage is code, a model, or both: the fixed rule's mark, the model's mark, and the word. */
function byTag(by) {
  return h(
    "span",
    { class: `mth-by by-${by}` },
    by !== "model" ? h("span", { class: "glyph g-rule", "aria-hidden": "true", text: "ƒ" }) : "",
    by !== "code" ? h("span", { class: "glyph g-model", "aria-hidden": "true", text: "✎" }) : "",
    ` ${BY_WORDS[by]}`,
  );
}

function renderMethod(run) {
  if (!els.method) return;
  const timings = timingsOf(run);
  const phases = methodPhases(run);
  state.ctx.stages = new Map();
  const drawn = new Set(phases.flatMap((phase) => phase.nodes.map((node) => node.stage)));
  const longest = Math.max(0, ...[...timings.values()].filter((item) => drawn.has(item.stage)).map((item) => item.seconds));
  const node = (item) => {
    const [by, who] = item.by;
    const time = timings.get(item.stage);
    const line = mLine(...list(item.line));
    const key = item.stage || item.name;
    state.ctx.stages.set(key, { item, time });
    return h(
      "li",
      { class: `mth-node by-${by} is-${item.state ?? "ran"}${time?.background ? " is-bg" : ""}`, "data-stage": key, "data-by": by, "data-state": item.state ?? "ran", "data-pick": `stage:${key}` },
      h("p", { class: "mth-head" }, h("button", { type: "button", class: "mth-name", "data-pick-button": "", text: item.name }), byTag(by)),
      h("p", { class: "mth-does", text: item.does }),
      who ? h("p", { class: "mth-who", "data-method-who": "", text: who }) : "",
      line.length ? h("p", { class: "mth-counts" }, line) : "",
      time ? h("p", { class: "mth-time", "data-method-seconds": String(time.seconds) }, timeBar(time.seconds, longest), h("span", { class: "mth-secs", text: secondsText(time.seconds) }), time.background ? h("span", { class: "mth-bg", text: " in the background" }) : "") : "",
    );
  };
  els.method.replaceChildren(
    h(
      "p",
      { class: "mth-lede" },
      "This run, stage by stage. ",
      byTag("code"),
      " is a fixed rule whose result can be recomputed; ",
      byTag("model"),
      " is a language model's answer, which code then checks. The counts are this run's own.",
    ),
    h(
      "ol",
      { class: "mth-flow", "aria-label": "The pipeline of this run" },
      phases.map((phase, index) =>
        h(
          "li",
          { class: "mth-phase", "data-phase": phase.name },
          h("p", { class: "mth-phase-head" }, h("span", { class: "mth-phase-n", text: String(index + 1) }), h("span", { class: "mth-phase-name", text: phase.name }), h("span", { class: "mth-phase-what", text: phase.what })),
          phase.nodes.length ? h("ol", { class: "mth-nodes" }, phase.nodes.map(node)) : h("p", { class: "muted mth-none", text: str(phase.none) }),
        ),
      ),
    ),
    timings.size
      ? h(
          "section",
          { class: "block mth-times" },
          h("h3", { class: "block-title", "data-code": "TIM", text: "Wall times, as the run recorded them" }),
          h(
            "div",
            { class: "table-wrap", tabindex: "0", role: "region", "aria-label": "Wall times of this run" },
            h(
              "table",
              { class: "an-table mth-table" },
              h("thead", null, h("tr", null, h("th", { scope: "col", text: "Stage" }), h("th", { scope: "col", class: "num", text: "Seconds" }), h("th", { scope: "col", text: "Note" }))),
              h(
                "tbody",
                null,
                [...timings.values()].map((item) => h("tr", { "data-timing": item.stage }, h("td", { text: item.stage }), h("td", { class: "num", text: secondsText(item.seconds) }), h("td", { class: "muted", text: [item.background ? "in the background" : "", item.note].filter(Boolean).join("; ") }))),
              ),
            ),
          ),
          [...timings.values()].some((item) => item.background) ? h("p", { class: "hint", text: "Stages that ran in the background overlap the others, so the times do not add up to the run's length." }) : "",
        )
      : h("p", { class: "muted mth-none", "data-no-timings": "", text: "This record holds no stage times: it was made before runs recorded them." }),
  );
}

// ---------------------------------------------------------------- the first screen, the two drawers, the guide

/** Whether the first screen is showing: no run or other record, so the form is the page. */
function onFirstScreen() {
  return Boolean(els.empty) && !els.empty.hidden;
}

/** Lay the page out for the first screen or for a result, when the empty state appears or goes. */
function syncFirstScreen() {
  const first = onFirstScreen();
  document.body.classList.toggle("is-first", first);
  if (els.thesisButton) els.thesisButton.hidden = first;
  if (els.howtoButton) els.howtoButton.hidden = first;
  // The guide (what this is, the samples, how a run is read) is the first screen's lead; beside a
  // result it is in the Run drawer, after who did the work.
  const home = first ? els.leadSlot : els.guideSlot;
  if (els.howto && home && els.howto.parentElement !== home) home.append(els.howto);
  if (first) {
    closeDrawer(false);
    closeRunDrawer(false);
  }
}

function drawerOpen() {
  return document.body.classList.contains("drawer-open");
}

function openDrawer() {
  if (onFirstScreen() || !els.formPanel) return;
  closeRunDrawer(false);
  document.body.classList.add("drawer-open");
  els.thesisButton?.setAttribute("aria-expanded", "true");
  if (els.drawerScrim) els.drawerScrim.hidden = false;
  els.decision?.focus({ preventScroll: true });
}

function closeDrawer(returnFocus = true) {
  if (!drawerOpen()) return;
  document.body.classList.remove("drawer-open");
  els.thesisButton?.setAttribute("aria-expanded", "false");
  if (els.drawerScrim) els.drawerScrim.hidden = true;
  if (returnFocus) els.thesisButton?.focus({ preventScroll: true });
}

function toggleDrawer() {
  if (drawerOpen()) closeDrawer();
  else openDrawer();
}

function runDrawerOpen() {
  return document.body.classList.contains("run-drawer-open");
}

/**
 * The Run drawer, from the right: who did the work on the run on screen (opened by the status
 * chip or r), then how to read the page, its marks and its terms (opened there by "How to read this").
 */
function openRunDrawer(part = "run", opener = null) {
  if (onFirstScreen() || !els.runDrawer) return;
  closeDrawer(false);
  state.drawerOpener = opener ?? (els.cmdRun?.hidden ? els.howtoButton : els.runButton);
  document.body.classList.add("run-drawer-open");
  els.runDrawer.removeAttribute("inert");
  els.runButton?.setAttribute("aria-expanded", "true");
  els.howtoButton?.setAttribute("aria-expanded", "true");
  if (els.drawerScrim) els.drawerScrim.hidden = false;
  els.runDrawer.scrollTop = 0;
  if (part === "guide" && els.howto && els.runInfo && !els.runInfo.hidden) els.howto.scrollIntoView({ block: "start" });
  els.runDrawerClose?.focus({ preventScroll: true });
}

function closeRunDrawer(returnFocus = true) {
  if (!runDrawerOpen()) return;
  document.body.classList.remove("run-drawer-open");
  els.runDrawer.setAttribute("inert", "");
  els.runButton?.setAttribute("aria-expanded", "false");
  els.howtoButton?.setAttribute("aria-expanded", "false");
  if (els.drawerScrim) els.drawerScrim.hidden = true;
  if (returnFocus) state.drawerOpener?.focus?.({ preventScroll: true });
}

function toggleRunDrawer(part, opener) {
  if (runDrawerOpen()) closeRunDrawer();
  else openRunDrawer(part, opener);
}

function initLayout() {
  if (!els.empty) return;
  new MutationObserver(syncFirstScreen).observe(els.empty, { attributes: true, attributeFilter: ["hidden"] });
  syncFirstScreen();
  els.thesisButton?.addEventListener("click", toggleDrawer);
  els.drawerClose?.addEventListener("click", () => closeDrawer());
  els.drawerScrim?.addEventListener("click", () => {
    closeDrawer();
    closeRunDrawer();
  });
  els.runButton?.addEventListener("click", () => toggleRunDrawer("run", els.runButton));
  els.runDrawerClose?.addEventListener("click", () => closeRunDrawer());
  els.howtoButton?.addEventListener("click", () => toggleRunDrawer("guide", els.howtoButton));
  els.inboxButton?.addEventListener("click", () => openInbox());
  // The menu shuts when one of its items is used and when the reader clicks anywhere else.
  els.barMenu?.addEventListener("click", (event) => {
    if (event.target instanceof Element && event.target.closest(".menu-item")) els.barMenu.open = false;
  });
  document.addEventListener("click", (event) => {
    if (els.barMenu?.open && event.target instanceof Node && !els.barMenu.contains(event.target)) els.barMenu.open = false;
  });
  els.keysHowto?.addEventListener("click", () => {
    els.keysDialog?.close?.();
    if (onFirstScreen()) return;
    openRunDrawer("guide", els.keysButton);
  });
  // A refused field opens the drawer, so the reader sees what to fix.
  if (els.formErrors) new MutationObserver(() => !els.formErrors.hidden && openDrawer()).observe(els.formErrors, { attributes: true, attributeFilter: ["hidden"] });
}

// ---------------------------------------------------------------- theme, keys, print

/** The reader's stored theme, or "" when none is stored or the browser refuses storage. */
function storedTheme() {
  try {
    const value = window.localStorage.getItem(THEME_KEY);
    return THEMES.includes(value) ? value : "";
  } catch {
    return "";
  }
}

function systemTheme() {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "terminal" : "paper";
}

/** ?theme=paper|terminal for this page load only (screenshots, a shared link); never stored. */
function urlTheme() {
  const value = new URLSearchParams(location.search).get("theme");
  return THEMES.includes(value) ? value : "";
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  if (!els.themeToggle) return;
  const other = theme === "paper" ? "terminal" : "paper";
  els.themeToggle.setAttribute("aria-label", `Theme: ${THEME_NAMES[theme]}. Switch to ${THEME_NAMES[other]}`);
  els.themeToggle.dataset.theme = theme;
  if (state.timelineRun) drawTimeline(els.timeline, state.timelineRun);
}

/** Switch theme and remember the choice when the browser lets the page store it. */
function toggleTheme() {
  const now = document.documentElement.getAttribute("data-theme") === "terminal" ? "terminal" : "paper";
  const next = now === "paper" ? "terminal" : "paper";
  try {
    window.localStorage.setItem(THEME_KEY, next);
  } catch {
    // Storage refused (a private window, a sandbox): the switch still holds for this page.
  }
  applyTheme(next);
}

function initTheme() {
  applyTheme(urlTheme() || storedTheme() || systemTheme());
  els.themeToggle?.addEventListener("click", toggleTheme);
  // With no stored choice, follow the system when it changes.
  window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", () => {
    if (!urlTheme() && !storedTheme()) applyTheme(systemTheme());
  });
}

/** Whether a key press belongs to a field the reader is typing in. */
function typing(target) {
  if (!(target instanceof Element)) return false;
  return Boolean(target.closest("input, textarea, select, [contenteditable=''], [contenteditable='true']"));
}

/**
 * Move the rail's selection to the next (+1) or previous (-1) entry: the whole thesis, then each
 * claim in the record's order. It stops at the ends, and the focus goes to the row selected.
 */
function moveClaim(step) {
  if (!workspaceOn() || !state.run || els.runView.hidden) return;
  const order = ["", ...list(state.run.claims).map((claim) => claim.id)];
  const at = Math.max(0, order.indexOf(state.selected));
  select(order[Math.max(0, Math.min(order.length - 1, at + step))], { focus: true });
}

function openKeys() {
  if (!els.keysDialog) return;
  if (typeof els.keysDialog.showModal === "function") {
    if (!els.keysDialog.open) els.keysDialog.showModal();
  } else {
    els.keysDialog.setAttribute("open", "");
  }
}

/** The page's keys: / ticker, j and k claims, 1 to 9 tabs, e thesis, r run, i inbox, t theme, ? the list. Ignored while typing or with a modifier. */
function onKey(event) {
  if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.key === "Escape" && drawerOpen()) {
    event.preventDefault();
    closeDrawer();
    return;
  }
  if (event.key === "Escape" && els.barMenu?.open) {
    event.preventDefault();
    els.barMenu.open = false;
    return;
  }
  if (event.key === "Escape" && runDrawerOpen()) {
    event.preventDefault();
    closeRunDrawer();
    return;
  }
  // The inspector as a sheet over the page: Esc puts it away.
  if (event.key === "Escape" && state.picked && workspaceOn() && !inspectorDocked() && !els.keysDialog?.open) {
    event.preventDefault();
    pick(null);
    return;
  }
  if (typing(event.target)) {
    if (event.key === "Escape" && event.target === els.ticker) els.ticker.blur();
    return;
  }
  if (els.keysDialog?.open && event.key !== "Escape") return;
  switch (event.key) {
    case "/":
      event.preventDefault();
      els.ticker?.focus();
      els.ticker?.select();
      break;
    case "j":
      event.preventDefault();
      moveClaim(1);
      break;
    case "k":
      event.preventDefault();
      moveClaim(-1);
      break;
    case "t":
      event.preventDefault();
      toggleTheme();
      break;
    case "i":
      event.preventDefault();
      openInbox();
      break;
    case "e":
      if (onFirstScreen()) break;
      event.preventDefault();
      toggleDrawer();
      break;
    case "r":
      if (onFirstScreen()) break;
      event.preventDefault();
      toggleRunDrawer("run");
      break;
    case "1":
    case "2":
    case "3":
    case "4":
    case "5":
    case "6":
    case "7":
    case "8":
    case "9": {
      const tab = tabsOn()[Number(event.key) - 1];
      if (!tab || !workspaceOn() || !state.run || els.runView.hidden) break;
      event.preventDefault();
      setTab(tab.id);
      break;
    }
    case "?":
      event.preventDefault();
      openKeys();
      break;
    default:
      break;
  }
}

/**
 * Printing lays the note out as a document (the stylesheet shows every tab's panel and every
 * claim's docket, one after another) and opens every closed disclosure so it prints whole; they
 * are closed again after.
 */
const printOpened = [];
function beforePrint() {
  for (const node of document.querySelectorAll("#result-panel details:not([open])")) {
    node.open = true;
    printOpened.push(node);
  }
  // How the run was made lives in the Run drawer on screen; on paper it follows the verdicts.
  if (els.runInfo && els.rail && !els.runInfo.hidden && !els.runView.hidden) els.rail.after(els.runInfo);
  // Paper is Paper: the Terminal theme's own rules (its black boards, its amber cells) are not for a printer.
  const theme = document.documentElement.getAttribute("data-theme");
  if (theme && theme !== "paper") {
    state.themeBeforePrint = theme;
    applyTheme("paper");
  }
}
function afterPrint() {
  while (printOpened.length) printOpened.pop().open = false;
  if (els.runInfo && els.guideSlot && els.runInfo.parentElement !== els.runDrawer) els.guideSlot.before(els.runInfo);
  if (state.themeBeforePrint) applyTheme(state.themeBeforePrint);
  state.themeBeforePrint = "";
}

/** Redraw the time line when the note changes width (a resized window, a rotated phone). */
function watchTimelineWidth() {
  if (!els.timeline || typeof ResizeObserver !== "function") return;
  let frame = 0;
  new ResizeObserver(() => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      if (!state.timelineRun || els.timelineSection.hidden) return;
      const width = Math.round(els.timeline.clientWidth);
      if (Math.abs(width - Number(els.timeline.dataset.width || 0)) > 4) drawTimeline(els.timeline, state.timelineRun);
    });
  }).observe(els.timeline);
  if (!els.tot) return;
  let totFrame = 0;
  new ResizeObserver(() => {
    cancelAnimationFrame(totFrame);
    totFrame = requestAnimationFrame(() => {
      if (!state.totRun || els.totSection.hidden) return;
      const width = Math.round(els.tot.clientWidth);
      if (Math.abs(width - Number(els.tot.dataset.width || 0)) > 4) drawThesisOverTime(els.tot, state.totRun);
    });
  }).observe(els.tot);
}

function initChrome() {
  initTheme();
  initWorkspace();
  initLayout();
  document.addEventListener("keydown", onKey);
  els.keysButton?.addEventListener("click", openKeys);
  window.addEventListener("beforeprint", beforePrint);
  window.addEventListener("afterprint", afterPrint);
  watchTimelineWidth();
}

function init() {
  if (document.body.dataset.page === "specimen") {
    initSpecimen();
    return;
  }
  frameViews();
  initChrome();
  els.ticker.addEventListener("focus", () => {
    state.tickerOnFocus = els.ticker.value;
  });
  els.ticker.addEventListener("keydown", onTickerKey);
  els.form.addEventListener("submit", onSubmit);
  els.figuresOnly.addEventListener("click", onFiguresOnly);
  els.filingChanges.addEventListener("click", onFilingChanges);
  els.breakdowns.addEventListener("click", onBreakdowns);
  els.restatements?.addEventListener("click", onRestatements);
  els.example.addEventListener("click", loadExample);
  els.saveThesis.addEventListener("click", () => toggleSavePanel(els.savePanel.hidden));
  els.saveConfirm.addEventListener("click", onSaveThesis);
  els.saveCancel.addEventListener("click", () => toggleSavePanel(false));
  els.thesisName.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      onSaveThesis();
    }
  });
  els.runAgain.addEventListener("click", onRunAgain);
  els.claims.addEventListener("input", updateCounts);
  els.decision.addEventListener("input", updateCounts);
  for (const field of Object.keys(FIELD_NAMES)) {
    $(field).addEventListener("input", () => setFieldError(field, []));
  }
  window.addEventListener("hashchange", openClaimChangesFromHash);
  const params = new URLSearchParams(location.search);
  state.sample = params.has("sample");
  if (state.sample) {
    setFormEnabled(false);
    loadSample(params.get("sample") || "run");
    return;
  }
  window.addEventListener("hashchange", openHashTarget);
  loadMeta();
  refreshRecent();
  refreshTheses();
  startWatchPolling();
  openHashTarget();
}

init();
