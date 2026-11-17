// Evidence Desk frontend (version 3).
//
// Collects a thesis, starts a run, polls it, and draws the record the API
// returns. It computes nothing a reader would call a result: verdicts, counts,
// coverage, reported figures and their display strings, excerpt context and all
// status and verdict wording come from the API (`GET /api/runs/{id}`,
// `GET /api/companies/{ticker}/metrics` and `GET /api/meta`). Chart geometry
// maps given values to pixels; every number a reader sees is a record field.
// Client-side validation is immediate feedback only, using the limits from
// `/api/meta`; the server decides. Every string from the API is inserted as
// text, never as markup, and only http(s) links from the API become hrefs.
//
// One meaning per mark (see the legend in index.html):
//   ▲ amber   something limits this record
//   ✎ violet  written by a model and not checked for meaning
//   ! red     your input was rejected
//   verdicts  ✓ supported, ✕ challenged, ± mixed, ? unjudged, ∅ not addressed
//   stances   reuse ✓ and ✕; context is •

"use strict";

const POLL_MS = 1500;

/** Pipeline stages in order, with the words shown on the progress line. */
const STAGES = [
  ["queued", "Queued"],
  ["company", "Company"],
  ["filings", "Filings"],
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
const STATUS_GLYPH = { running: "⋯", complete: "■", partial: "▲", failed: "▲" };
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
const ACCESSION_GLOSS = "Accession number (the SEC's identifier for this filing)";
const FIELD_NAMES = {
  ticker: "Ticker",
  decision: "Decision",
  claims: "Claims",
  scope_notes: "Scope notes",
  filings: "Number of filings",
  extra_urls: "Extra public pages",
};

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
};

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
  advanced: $("advanced"),
  decisionCount: $("decision-count"),
  claimsCount: $("claims-count"),
  scopeHint: $("scope-hint"),
  filingsHint: $("filings-hint"),
  urlsHint: $("urls-hint"),
  formErrors: $("form-errors"),
  submit: $("submit"),
  figuresOnly: $("figures-only"),
  example: $("load-example"),
  formNote: $("form-note"),
  recent: $("recent"),
  resultPanel: $("result-panel"),
  empty: $("empty-state"),
  loading: $("loading"),
  loadError: $("load-error"),
  figuresView: $("figures-view"),
  figuresHead: $("figures-head"),
  figuresStandalone: $("figures-standalone"),
  runView: $("run-view"),
  banner: $("status-banner"),
  stagesWrap: $("stages-wrap"),
  stages: $("stages"),
  runHead: $("run-head"),
  scorecard: $("scorecard"),
  summarySection: $("summary-section"),
  summaryBox: $("summary-box"),
  summaryOrigin: $("summary-origin"),
  summary: $("summary"),
  figuresSection: $("figures-section"),
  figures: $("figures"),
  claimList: $("claim-list"),
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

/** ✎ violet: written by a model and not checked for meaning. */
function modelBadge() {
  return h(
    "span",
    { class: "badge-model" },
    h("span", { class: "glyph g-model", "aria-hidden": "true", text: "✎" }),
    " Model-written, not checked for meaning",
  );
}

/** ! red: your input was rejected. */
function rejectGlyph() {
  return h("span", { class: "glyph g-reject", "aria-hidden": "true", text: "!" });
}

/**
 * A field that may have been written by a model. `id` names it for the browser
 * test; when `model` is true it carries the violet badge and border.
 */
function writtenField(tag, id, model, ...content) {
  return h(tag, { class: model ? "mw is-model" : "mw", "data-mw": id }, ...content, model ? modelBadge() : "");
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

function statusMark(status) {
  const glyph = STATUS_GLYPH[status] ?? "·";
  return h("span", { class: LIMITING_STATUS.has(status) ? "glyph g-limit" : "glyph", "aria-hidden": "true", text: glyph });
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
    const message = typeof payload?.error === "string" ? payload.error : `the server answered HTTP ${response.status}`;
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

function applyMeta(meta) {
  if (!meta || typeof meta !== "object" || !meta.limits) throw new ApiError("the wording and limits are missing", 0);
  state.meta = meta;
  const limits = meta.limits;
  const engine = str(meta.engine);
  els.engineLine.replaceChildren(
    h("span", { class: "engine-name", text: `Configured engine: ${engine || "not stated"}` }),
    ENGINE_GLOSS[engine] ? ` (${ENGINE_GLOSS[engine]}). Each result names the engine that actually did the work.` : "",
  );
  if (Number.isInteger(limits.MAX_DECISION_CHARS)) els.decision.maxLength = limits.MAX_DECISION_CHARS;
  if (Number.isInteger(limits.MAX_SCOPE_CHARS)) els.scope.maxLength = limits.MAX_SCOPE_CHARS;
  els.filings.min = "1";
  els.filings.max = String(limits.MAX_FILINGS);
  if (!els.filings.value) els.filings.value = String(limits.DEFAULT_FILINGS);
  els.scopeHint.textContent = `Definitions and exclusions the engine should respect. Up to ${plural(limits.MAX_SCOPE_CHARS, "character", "characters")}.`;
  els.filingsHint.textContent = `1 to ${limits.MAX_FILINGS}; default ${limits.DEFAULT_FILINGS}. The latest annual report (10-K), then the quarterly reports (10-Q) filed after it, newest first.`;
  els.urlsHint.textContent = `A press release or investor-relations page, one http(s) address per line, up to ${limits.MAX_EXTRA_URLS}.`;
  updateCounts();
  setFormEnabled(!state.sample);
  els.example.disabled = state.sample || !meta.example;
}

function setFormEnabled(enabled) {
  els.submit.disabled = !enabled;
  els.figuresOnly.disabled = !enabled;
  els.example.disabled = !enabled;
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

/** The form field a server or client error path belongs to: "claims.2" -> "claims", "path.ticker" -> "ticker". */
function rootField(field) {
  return String(field ?? "")
    .replace(/^(path|query)\./, "")
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
  els.advanced.open = Boolean(example.scope_notes || list(example.extra_urls).length);
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
  els.loading.hidden = true;
  els.loadError.hidden = true;
  els.empty.hidden = true;
  els.runView.hidden = true;
  els.figuresView.hidden = false;
  document.body.classList.add("has-run");
  els.figuresHead.replaceChildren(
    h(
      "div",
      { class: "run-head-main" },
      h(
        "p",
        { class: "company" },
        h("strong", { text: str(report.company) || "Company" }),
        Number.isFinite(report.cik) ? h("span", { class: "muted small" }, " · ", h("abbr", { title: "The SEC's numeric identifier for this company", text: "CIK" }), ` ${report.cik}`) : "",
      ),
      h("p", { class: "run-meta", text: "Reported figures read from the company's XBRL data. No run was started and no claim was tested." }),
    ),
  );
  renderFigures(els.figuresStandalone, { metrics: report.metrics, series: report.series, notes: report.notes });
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
      if (run.status === "running") state.timer = setTimeout(tick, POLL_MS);
      else refreshRecent();
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
  els.loadError.hidden = true;
  els.empty.hidden = true;
  document.body.classList.remove("has-run");
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
  els.sampleTag.hidden = false;
  els.formNote.textContent = "Sample mode: this page shows a stored record and does not start runs. Open the page without ?sample to test a thesis.";
  els.formNote.hidden = false;
  els.recent.replaceChildren(h("li", { class: "muted", text: "Recent runs are not loaded in sample mode." }));
  const link = $("sample-link");
  link.textContent = "Leave the sample";
  link.href = location.pathname;
  $("synthetic-link").hidden = true;
  hideRunView();
  if (!SAMPLE_NAME.test(name)) {
    showLoadError("That sample name is not valid: use lower-case letters, digits and hyphens.", null);
    return;
  }
  try {
    const payload = await api(`sample-${name}.json`, { cache: "no-store" });
    if (!payload.meta || !payload.run) throw new ApiError("the file has no meta or run", 0);
    applyMeta(payload.meta);
    if (str(payload.note)) els.formNote.textContent = `Sample mode: ${payload.note} This page does not start runs; open it without ?sample to test a thesis.`;
    state.runId = payload.run.id;
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

  els.loading.hidden = true;
  els.loadError.hidden = true;
  els.empty.hidden = true;
  els.figuresView.hidden = true;
  els.runView.hidden = false;
  document.body.classList.add("has-run");

  renderBanner(run);
  renderStages(run);
  renderHead(run);
  renderScorecard(run);
  renderSummary(run);
  renderRunFigures(run);
  renderClaims(run, ctx);
  renderWithheld(run, ctx);
  renderBriefLists(run);
  renderSources(run);
  const finished = run.status !== "running";
  fillList(els.limits, run.coverage_limits, finished ? "None recorded." : "Listed when the run finishes.", true);
  renderErrors(run, finished);
  els.provenance.textContent = state.meta?.provenance_note ?? "";
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
    const facts = [
      h("li", null, cov(c, "sources_read"), " of ", cov(c, "sources_requested"), ` ${unit(c.sources_requested, "source", "sources")} read`),
      h("li", null, cov(c, "passages_indexed"), ` ${unit(c.passages_indexed, "passage", "passages")} indexed`),
      h("li", null, cov(c, "claims_with_evidence"), " of ", cov(c, "claims_total"), ` ${unit(c.claims_total, "claim", "claims")} with verified excerpts or figures`),
    ];
    const hasProposed = Number.isFinite(c.findings_proposed) && (c.findings_proposed > 0 || list(run.findings).length === 0);
    facts.push(
      hasProposed
        ? h("li", null, cov(c, "findings_verified"), " of ", cov(c, "findings_proposed"), ` proposed ${unit(c.findings_proposed, "finding", "findings")} verified, `, cov(c, "findings_withheld"), " withheld")
        : h("li", null, cov(c, "findings_verified"), ` ${unit(c.findings_verified, "finding", "findings")} verified, `, cov(c, "findings_withheld"), " withheld"),
    );
    facts.push(h("li", null, cov(c, "excerpts_verified"), " of ", cov(c, "quotes_offered"), ` ${unit(c.quotes_offered, "quote", "quotes")} offered found word for word, `, cov(c, "quotes_rejected"), " rejected"));
    if (Number.isFinite(c.metrics_computed)) {
      facts.push(h("li", null, cov(c, "metrics_computed"), ` reported ${unit(c.metrics_computed, "figure", "figures")} computed`));
    }
    if (Number.isFinite(c.numbers_checked)) {
      facts.push(h("li", null, cov(c, "numbers_checked"), ` ${unit(c.numbers_checked, "number", "numbers")} in findings checked, `, cov(c, "numbers_unmatched"), " unmatched"));
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
  }
  els.banner.replaceChildren(...parts);
}

function jumpTo(id) {
  return (event) => {
    event.preventDefault();
    const target = $(id);
    if (!target) return;
    target.scrollIntoView({ block: "start", behavior: "smooth" });
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

function renderHead(run) {
  const company = run.company;
  const inputs = run.inputs ?? {};
  const title = h(
    "p",
    { class: "company" },
    h("strong", { text: company?.ticker ?? inputs.ticker ?? "" }),
    company ? ` · ${company.name}` : "",
    company ? h("span", { class: "muted small" }, " · ", h("abbr", { title: "The SEC's numeric identifier for this company", text: "CIK" }), ` ${company.cik}`) : "",
  );
  const decision = h("p", { class: "decision" }, h("span", { class: "label", text: "Decision: " }), inputs.decision ?? "");
  const engine = str(run.engine);
  const engineLine = h(
    "p",
    { class: "run-engine" },
    h("span", { class: "label", text: "Engine that did the work: " }),
    h("span", { class: "engine-used", text: engine || "not recorded" }),
    str(run.engine_detail) ? h("span", { class: "engine-detail", text: ` — ${run.engine_detail}` }) : "",
  );
  const details = h(
    "p",
    { class: "run-meta" },
    `Run ${run.id} · started ${utc(run.started_at)}`,
    run.finished_at ? ` · finished ${utc(run.finished_at)}` : "",
    ` · ${plural(inputs.filings, "filing", "filings")} requested`,
  );
  let download;
  if (state.sample) {
    download = h("span", { class: "muted small", text: "The Markdown brief is not available for the sample record." });
  } else if (run.status === "running") {
    download = h("span", { class: "muted small", text: "The Markdown brief can be downloaded when the run finishes." });
  } else {
    download = h("a", { class: "download", href: `/api/runs/${encodeURIComponent(run.id)}/export.md`, download: `evidence-desk-${run.id}.md`, text: "Download Markdown brief" });
  }
  els.runHead.replaceChildren(h("div", { class: "run-head-main" }, title, decision, engineLine, details), h("div", { class: "run-head-actions" }, download));
}

/** Who assessed a claim, in words. */
function assessedText(claim) {
  const by = str(claim.assessed_by);
  if (!by) return "";
  return by === EXTRACTIVE ? "Assessed by: extractive (no model)" : `Assessed by: ${by} (a model)`;
}

/** One row per claim: verdict first, then the claim, then counts the API lists. */
function renderScorecard(run) {
  const claims = list(run.claims);
  const c = run.coverage ?? {};
  els.scorecard.replaceChildren();
  if (claims.length === 0) {
    els.scorecard.append(h("li", { class: "muted", text: run.status === "running" ? "Claims appear once the run has planned them." : "This run recorded no claims." }));
    return;
  }
  claims.forEach((claim, index) => {
    const passages = Number.isFinite(c.passages_indexed)
      ? [h("span", { "data-claim-field": "passages_considered", text: num(claim.passages_considered ?? 0) }), " of ", cov(c, "passages_indexed"), " passages considered"]
      : [h("span", { "data-claim-field": "passages_considered", text: num(claim.passages_considered ?? 0) }), " passages considered"];
    const row = h(
      "a",
      { class: "score-row", href: `#claim-${index}`, onclick: openClaim(index) },
      verdictPill(claim.verdict),
      h(
        "span",
        { class: "score-claim" },
        h("span", { class: "claim-id", text: claim.id }),
        " ",
        claim.text,
        assessedText(claim) ? h("span", { class: "assessed", text: assessedText(claim) }) : "",
      ),
      h("span", { class: "score-counts" }, `${plural(list(claim.finding_ids).length, "finding", "findings")} · `, ...passages),
    );
    els.scorecard.append(h("li", { "data-claim-id": claim.id }, row));
  });
}

function openClaim(index) {
  return (event) => {
    event.preventDefault();
    const section = $(`claim-${index}`);
    if (!section) return;
    section.open = true;
    section.scrollIntoView({ block: "start", behavior: "smooth" });
    section.querySelector("summary")?.focus({ preventScroll: true });
  };
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
}

function renderClaims(run, ctx) {
  const open = new Set([...els.claimList.querySelectorAll("details[open]")].map((d) => d.id));
  els.claimList.replaceChildren();
  list(run.claims).forEach((claim, position) => {
    const id = `claim-${position}`;
    const model = modelAssessed(claim);
    const body = h("div", { class: "claim-body" });
    const note = verdictNote(claim.verdict);
    if (note) body.append(h("p", { class: "verdict-note" }, h("span", { class: "label", text: "Verdict rule: " }), note));
    if (assessedText(claim)) body.append(h("p", { class: "assessed-line", text: assessedText(claim) }));
    if (claim.rationale) {
      body.append(
        writtenField(
          "div",
          `claim:${claim.id}:commentary`,
          model,
          h("p", { class: "label", text: `Engine's commentary (${str(claim.assessed_by) || str(run.engine) || "engine"}), not a verified excerpt` }),
          h("p", { text: claim.rationale }),
        ),
      );
    }
    if (list(claim.queries).length) {
      body.append(h("p", { class: "queries" }, h("span", { class: "label", text: "Searched with: " }), claim.queries.join(" · ")));
    }
    const ids = list(claim.finding_ids);
    if (ids.length === 0) {
      body.append(h("p", { class: "muted", text: run.status === "running" ? "Findings appear when this claim has been assessed." : "No verified finding is recorded for this claim." }));
    }
    ids.forEach((findingId) => {
      const finding = ctx.findings.get(findingId);
      if (!finding) body.append(h("p", { class: "muted", text: `Finding ${findingId} is listed but missing from the record.` }));
      else if (finding.verified === false) body.append(h("p", { class: "muted", text: `Finding ${findingId} was withheld; it is listed under "Withheld findings" below.` }));
      else body.append(renderFinding(finding, ctx));
    });
    const details = h(
      "details",
      { class: "claim", id, open: open.has(id) },
      h("summary", null, verdictPill(claim.verdict), h("span", { class: "claim-id", text: claim.id }), h("span", { class: "claim-text", text: claim.text })),
      body,
    );
    els.claimList.append(details);
  });
}

/** One finding: stance, statement, the engine's reason, its checks, cited figures and quotes. */
function renderFinding(finding, ctx, withheld = false) {
  const stance = token(finding.stance, STANCE_MARK);
  const model = modelAssessed(ctx.claims.get(finding.claim_id));
  const article = h(
    "article",
    { class: `finding s-${stance}${withheld ? " is-withheld" : ""}`, "data-finding-id": finding.id },
    h(
      "header",
      { class: "finding-head" },
      stancePill(finding.stance),
      writtenField("div", `finding:${finding.id}:statement`, model, h("h4", { class: "finding-statement", text: finding.statement })),
    ),
    h(
      "p",
      { class: "finding-meta" },
      h("span", { class: "muted", text: `${finding.id} · ` }),
      h("span", { title: "The engine's own qualitative estimate, not a measured probability", text: `Engine's confidence: ${finding.confidence}` }),
      ` · ${plural(finding.filings_cited, "filing", "filings")} cited`,
    ),
  );
  if (withheld) {
    article.append(limitLine("p", h("strong", { text: "Withheld: " }), str(finding.withheld_reason) || "no quote was found in the filing text."));
  }
  if (finding.rationale) {
    article.append(writtenField("p", `finding:${finding.id}:reason`, model, h("span", { class: "label", text: "Engine's reason: " }), finding.rationale));
  }
  const checks = renderChecks(finding.checks);
  if (checks) article.append(checks);
  const cited = renderCitedFigures(finding.metric_ids, ctx.metrics);
  if (cited) article.append(cited);
  for (const evidenceId of list(finding.evidence_ids)) {
    const item = ctx.evidence.get(evidenceId);
    if (!item) {
      article.append(h("p", { class: "muted", text: `Excerpt ${evidenceId} is listed but missing from the record.` }));
      continue;
    }
    article.append(renderEvidence(item, ctx.sources.get(item.source_id)));
  }
  return article;
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

  const support = str(checks.support);
  let supportItem = null;
  if (support === "unchecked") supportItem = h("li", { text: "Meaning: not checked by a second model" });
  else if (support === "passed") supportItem = h("li", { text: "Meaning: checked by a second model" });
  else if (support === "failed") supportItem = limitLine("li", "Meaning: failed the second-model check");
  else if (support) supportItem = h("li", { text: `Meaning check: ${support}` });
  if (supportItem && str(checks.support_detail)) supportItem.append(h("span", { class: "muted", text: ` — ${checks.support_detail}` }));
  if (supportItem) items.push(supportItem);

  if (items.length === 0) return null;
  return h("div", { class: "checks" }, h("span", { class: "label", text: "Checks: " }), h("ul", { class: "check-list" }, items));
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
        return h(
          "li",
          { "data-cited-metric": id },
          `${metric.label} · ${metric.period_label} · `,
          h("span", { class: "fig-value", text: metric.display }),
        );
      }),
    ),
  );
}

/** The verified excerpt in its surrounding text, where it sits, and the filing it came from. */
function renderEvidence(item, source) {
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
    externalLink(item.link || source?.url, source?.kind === "public_html" ? "Open the page" : "Open in filing"),
  );
  return h("figure", { class: "evidence" }, h("span", { class: "evidence-id", text: `${item.id} · quote found word for word, highlighted` }), quote, caption);
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

function renderWithheld(run, ctx) {
  const withheld = list(run.unsupported_findings);
  els.withheldSection.hidden = withheld.length === 0;
  els.withheld.replaceChildren(
    ...withheld.map((finding) => {
      const claim = ctx.claims.get(finding.claim_id);
      return h(
        "li",
        { class: "withheld-item" },
        h("p", { class: "withheld-for muted", text: `Proposed for ${finding.claim_id}${claim ? `: ${claim.text}` : ""}` }),
        renderFinding(finding, ctx, true),
      );
    }),
  );
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

function renderRunFigures(run) {
  const metrics = list(run.metrics);
  const notes = list(run.metrics_notes);
  els.figuresSection.hidden = metrics.length === 0 && notes.length === 0;
  if (els.figuresSection.hidden) {
    els.figures.replaceChildren();
    return;
  }
  renderFigures(els.figures, { metrics, series: run.series, notes });
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
  container.replaceChildren();
  if (str(state.meta?.figures_note)) container.append(h("p", { class: "hint", text: state.meta.figures_note }));
  if (metrics.length === 0) {
    container.append(h("p", { class: "muted", text: "The record holds no reported figures." }));
  } else {
    const columns = [
      ["quarter", "Newest quarter in the record"],
      ["annual", "Newest fiscal year in the record"],
    ];
    const grid = h("div", { class: "fig-grid" });
    for (const [kind, heading] of columns) {
      const end = latestEnd(metrics, kind);
      if (!end) continue;
      const rows = metrics.filter((m) => (m.period === kind || m.period === "instant") && m.period_end === end);
      const periodLabel = rows.find((m) => m.period === kind)?.period_label ?? end;
      grid.append(
        h(
          "section",
          { class: "fig-col", "aria-label": `${heading}: ${periodLabel}` },
          h("h4", { class: "fig-head" }, periodLabel, h("span", { class: "muted small", text: ` · ${heading.toLowerCase()}` })),
          h("ul", { class: "fig-list" }, rows.map(figureRow)),
        ),
      );
    }
    container.append(grid, h("p", { class: "hint", text: "Open a figure to see its arithmetic and the reported values it used." }));
  }
  if (notes.length) {
    const notesList = h("ul", { class: "mark-list" });
    fillList(notesList, notes, "", true);
    container.append(h("div", { class: "fig-notes" }, h("p", { class: "label", text: "Notes on the figures" }), notesList));
  }
  const charts = renderCharts(list(data.series));
  if (charts) container.append(charts);
}

function figureRow(metric) {
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
  return h(
    "li",
    null,
    h(
      "details",
      { class: "fig-row", "data-metric-id": metric.id },
      h(
        "summary",
        null,
        h("span", { class: "fig-label" }, metric.label, metric.period === "instant" ? h("span", { class: "muted small", text: ` · ${metric.period_label}` }) : ""),
        h("span", { class: metric.value === null ? "fig-value is-missing" : "fig-value", text: metric.display }),
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
  return h(
    "tr",
    null,
    h("td", null, h("code", { text: ref.concept })),
    h("td", { text: period }),
    h("td", { class: "num", text: value }),
    h("td", { text: ref.form ?? "—" }),
    h("td", { text: ref.filed ?? "—" }),
    h("td", null, h("code", { text: ref.accession ?? "—" })),
    h("td", null, flags.length ? flags.join(", ") : "—", str(ref.note) ? h("span", { class: "muted", text: ` — ${ref.note}` }) : ""),
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

function runIdFromHash() {
  const match = /^#run=(.+)$/.exec(location.hash);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return null;
  }
}

function init() {
  els.form.addEventListener("submit", onSubmit);
  els.figuresOnly.addEventListener("click", onFiguresOnly);
  els.example.addEventListener("click", loadExample);
  els.claims.addEventListener("input", updateCounts);
  els.decision.addEventListener("input", updateCounts);
  for (const field of Object.keys(FIELD_NAMES)) {
    $(field).addEventListener("input", () => setFieldError(field, []));
  }
  const params = new URLSearchParams(location.search);
  state.sample = params.has("sample");
  if (state.sample) {
    setFormEnabled(false);
    loadSample(params.get("sample") || "run");
    return;
  }
  window.addEventListener("hashchange", () => {
    const id = runIdFromHash();
    if (id && id !== state.runId) watchRun(id);
  });
  loadMeta();
  refreshRecent();
  const id = runIdFromHash();
  if (id) watchRun(id);
}

init();
