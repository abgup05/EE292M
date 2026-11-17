// Evidence Desk frontend (version 2).
//
// Collects a thesis, starts a run, polls it, and draws the record the API
// returns. It computes nothing a reader would call a result: verdicts, counts,
// coverage, excerpt context and all status and verdict wording come from the
// API (`GET /api/runs/{id}` and `GET /api/meta`). Client-side validation is
// immediate feedback only, using the limits from `/api/meta`; the server
// decides. Every string from the API is inserted as text, never as markup.

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

// One mark per meaning. Verdicts sit in square-cornered pills, stances in round
// ones, and no glyph is reused across the three sets.
const VERDICT_GLYPH = {
  supported: "✓",
  challenged: "✕",
  mixed: "◐",
  unjudged: "?",
  not_addressed: "∅",
};
const STANCE_MARK = {
  supports: ["+", "Supports"],
  challenges: ["−", "Challenges"],
  context: ["◇", "Context"],
};
const STATUS_GLYPH = { running: "⋯", complete: "■", partial: "▲", failed: "⊘" };

const FORM_GLOSS = {
  "10-K": "annual report",
  "10-Q": "quarterly report",
  "10-K/A": "amended annual report",
  "10-Q/A": "amended quarterly report",
};
const ENGINE_GLOSS = {
  claude: "a language model drafts findings; the backend checks every quote against the filing",
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

const state = {
  meta: null,
  sample: false,
  runId: null,
  viewSeq: 0, // bumped on every run selection; stale responses are dropped
  recentSeq: 0,
  timer: null,
  controller: null,
  bannerKey: "",
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
  example: $("load-example"),
  formNote: $("form-note"),
  recent: $("recent"),
  resultPanel: $("result-panel"),
  empty: $("empty-state"),
  loading: $("loading"),
  loadError: $("load-error"),
  runView: $("run-view"),
  banner: $("status-banner"),
  stagesWrap: $("stages-wrap"),
  stages: $("stages"),
  runHead: $("run-head"),
  scorecard: $("scorecard"),
  summarySection: $("summary-section"),
  summaryOrigin: $("summary-origin"),
  summary: $("summary"),
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
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : String(child));
  }
  return node;
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
  return h("a", { href, target: "_blank", rel: "noopener noreferrer", class: className }, text, h("span", { class: "visually-hidden", text: " (opens in a new tab)" }), h("span", { "aria-hidden": "true", text: " ↗" }));
}

/** "1 filing" / "3 filings": a count from the API with its unit. */
function plural(count, one, many) {
  const n = Number.isFinite(count) ? count : 0;
  return `${n.toLocaleString("en-US")} ${n === 1 ? one : many}`;
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
    { class: `pill verdict v-${key}`, title: verdictNote(verdict) || null },
    h("span", { class: "glyph", "aria-hidden": "true", text: VERDICT_GLYPH[verdict] ?? "…" }),
    h("span", { class: "pill-label", text: verdictLabel(verdict) }),
  );
}

function stancePill(stance) {
  const key = token(stance, STANCE_MARK);
  const [glyph, label] = STANCE_MARK[stance] ?? ["·", String(stance)];
  return h(
    "span",
    { class: `pill stance s-${key}` },
    h("span", { class: "glyph", "aria-hidden": "true", text: glyph }),
    h("span", { class: "pill-label", text: label }),
  );
}

function statusMark(status) {
  return h("span", { class: "glyph", "aria-hidden": "true", text: STATUS_GLYPH[status] ?? "·" });
}

function fillList(list, items, emptyText) {
  list.replaceChildren();
  if (!Array.isArray(items) || items.length === 0) {
    if (emptyText) list.append(h("li", { class: "muted", text: emptyText }));
    return;
  }
  for (const item of items) list.append(h("li", { text: item }));
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
  const engine = String(meta.engine ?? "");
  els.engineLine.replaceChildren(
    h("span", { class: "engine-name", text: `Engine: ${engine}` }),
    ENGINE_GLOSS[engine] ? ` (${ENGINE_GLOSS[engine]})` : "",
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
  els.example.disabled = !meta.example;
}

function setFormEnabled(enabled) {
  els.submit.disabled = !enabled;
  els.example.disabled = !enabled && !state.sample;
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

/** The form field a server or client error path belongs to: "claims.2" -> "claims". */
function rootField(field) {
  return String(field ?? "").split(/[.[]/)[0];
}

function clearFieldErrors() {
  for (const field of Object.keys(FIELD_NAMES)) setFieldError(field, []);
  els.formErrors.replaceChildren();
  els.formErrors.hidden = true;
}

function setFieldError(field, messages) {
  const input = $(field);
  const slot = $(`err-${field}`);
  if (!input || !slot) return;
  slot.textContent = messages.join(" ");
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
  const list = h("ul");
  for (const { field, message } of problems) {
    const name = FIELD_NAMES[rootField(field)];
    list.append(h("li", null, h("code", { text: String(field ?? "request") }), name ? ` (${name})` : "", `: ${message}`));
  }
  els.formErrors.replaceChildren(h("p", { class: "alert-title", text: heading }), list);
  els.formErrors.hidden = false;
  const first = $(rootField(problems[0].field));
  if (first) first.focus();
}

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
  els.claimsCount.textContent = `${claimCount} of ${limits.MAX_CLAIMS} claims.`;
  els.claimsCount.classList.toggle("over", claimCount > limits.MAX_CLAIMS);
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
    els.resultPanel.focus({ preventScroll: true });
    if (window.matchMedia("(max-width: 900px)").matches) {
      els.resultPanel.scrollIntoView({ block: "start", behavior: "smooth" });
    }
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

function loadExample() {
  const example = state.meta?.example;
  if (!example) return;
  els.ticker.value = example.ticker ?? "";
  els.decision.value = example.decision ?? "";
  els.claims.value = (example.claims ?? []).join("\n");
  els.scope.value = example.scope_notes ?? "";
  els.filings.value = String(example.filings ?? state.meta.limits.DEFAULT_FILINGS);
  els.urls.value = (example.extra_urls ?? []).join("\n");
  els.advanced.open = Boolean(example.scope_notes || (example.extra_urls ?? []).length);
  clearFieldErrors();
  updateCounts();
  els.ticker.focus();
}

// ---------------------------------------------------------------- recent runs

async function refreshRecent() {
  if (state.sample) return;
  const seq = ++state.recentSeq;
  try {
    const payload = await api("/api/runs");
    if (seq !== state.recentSeq) return;
    renderRecent(Array.isArray(payload.runs) ? payload.runs : []);
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

async function loadSample() {
  els.sampleTag.hidden = false;
  els.formNote.textContent = "Sample mode: this page shows an illustrative record and does not start runs. Open the page without ?sample to test a thesis.";
  els.formNote.hidden = false;
  els.recent.replaceChildren(h("li", { class: "muted", text: "Recent runs are not loaded in sample mode." }));
  const link = $("sample-link");
  link.textContent = "Leave the sample";
  link.href = location.pathname;
  hideRunView();
  try {
    const payload = await api("sample-run.json", { cache: "no-store" });
    if (!payload.meta || !payload.run) throw new ApiError("the file has no meta or run", 0);
    applyMeta(payload.meta);
    state.runId = payload.run.id;
    renderRun(payload.run);
  } catch (error) {
    showLoadError(`The sample record could not be loaded: ${error.message}.`, null);
  }
}

// ---------------------------------------------------------------- run rendering

function renderRun(run) {
  const sources = new Map((run.sources ?? []).map((s) => [s.id, s]));
  const evidence = new Map((run.evidence ?? []).map((e) => [e.id, e]));
  const findings = new Map([...(run.findings ?? []), ...(run.unsupported_findings ?? [])].map((f) => [f.id, f]));
  const claims = new Map((run.claims ?? []).map((c) => [c.id, c]));

  els.loading.hidden = true;
  els.loadError.hidden = true;
  els.empty.hidden = true;
  els.runView.hidden = false;
  document.body.classList.add("has-run");

  renderBanner(run);
  renderStages(run);
  renderHead(run);
  renderScorecard(run);
  renderSummary(run);
  renderClaims(run, { sources, evidence, findings });
  renderWithheld(run, claims);
  renderBriefLists(run);
  renderSources(run);
  const finished = run.status !== "running";
  fillList(els.limits, run.coverage_limits, finished ? "None recorded." : "Listed when the run finishes.");
  fillList(els.errors, run.errors, finished ? "None recorded." : "None so far.");
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
    state.sample ? h("span", { class: "sample-tag inline", text: "Sample record" }) : "",
    statusMark(run.status),
    h("strong", { text: ` ${capitalize(run.status)}` }),
    h("span", { class: "banner-note", text: ` ${state.meta?.status_notes?.[run.status] ?? ""}` }),
  );
  const parts = [head];
  if (run.status === "running") {
    const stage = STAGES.find(([id]) => id === run.stage);
    parts.push(h("p", { class: "banner-line", text: `Now: ${stage ? stage[1] : run.stage}${run.stage_detail ? ` — ${run.stage_detail}` : ""}` }));
  } else {
    parts.push(
      h(
        "ul",
        { class: "coverage-facts", "aria-label": "Coverage" },
        h("li", { text: `${c.sources_read ?? 0} of ${plural(c.sources_requested, "source", "sources")} read` }),
        h("li", { text: `${plural(c.passages_indexed, "passage", "passages")} indexed` }),
        h("li", { text: `${c.claims_with_evidence ?? 0} of ${plural(c.claims_total, "claim", "claims")} with verified evidence` }),
        h("li", { text: `${plural(c.findings_verified, "finding", "findings")} verified, ${c.findings_withheld ?? 0} withheld` }),
        h("li", { text: `${plural(c.excerpts_verified, "quote", "quotes")} verified, ${c.quotes_rejected ?? 0} rejected` }),
      ),
    );
    if ((run.coverage_limits ?? []).length) {
      parts.push(
        h("p", { class: "banner-line" }, h("a", { href: "#coverage-limits", onclick: jumpTo("coverage-limits"), text: "Read the coverage limits" })),
      );
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
  const details = h(
    "p",
    { class: "run-meta" },
    `Run ${run.id} · started ${utc(run.started_at)}`,
    run.finished_at ? ` · finished ${utc(run.finished_at)}` : "",
    ` · engine: ${run.engine ?? ""}`,
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
  els.runHead.replaceChildren(h("div", { class: "run-head-main" }, title, decision, details), h("div", { class: "run-head-actions" }, download));
}

/** One row per claim: verdict first, then the claim, then counts the API lists. */
function renderScorecard(run) {
  const claims = run.claims ?? [];
  els.scorecard.replaceChildren();
  if (claims.length === 0) {
    els.scorecard.append(h("li", { class: "muted", text: run.status === "running" ? "Claims appear once the run has planned them." : "This run recorded no claims." }));
    return;
  }
  claims.forEach((claim, index) => {
    const row = h(
      "a",
      { class: "score-row", href: `#claim-${index}`, onclick: openClaim(index) },
      verdictPill(claim.verdict),
      h("span", { class: "score-claim" }, h("span", { class: "claim-id", text: claim.id }), " ", claim.text),
      h("span", { class: "score-counts", text: `${plural((claim.finding_ids ?? []).length, "finding", "findings")} · ${plural(claim.passages_considered, "passage", "passages")} considered` }),
    );
    els.scorecard.append(h("li", null, row));
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
  const origin = String(brief.summary_origin ?? "");
  const modelWritten = /model|claude|llm/i.test(origin);
  els.summaryOrigin.replaceChildren(
    modelWritten
      ? h("span", { class: "origin-tag model" }, h("span", { class: "glyph", "aria-hidden": "true", text: "✎" }), ` Model-written (origin: ${origin}). Check it against the verdicts and excerpts, which the backend computed and verified.`)
      : h("span", { class: "origin-tag" }, `Written by: ${origin || "not stated"}`),
  );
  els.summary.textContent = brief.summary ?? "";
}

function renderClaims(run, index) {
  const open = new Set([...els.claimList.querySelectorAll("details[open]")].map((d) => d.id));
  els.claimList.replaceChildren();
  (run.claims ?? []).forEach((claim, position) => {
    const id = `claim-${position}`;
    const body = h("div", { class: "claim-body" });
    const note = verdictNote(claim.verdict);
    if (note) body.append(h("p", { class: "verdict-note" }, h("span", { class: "label", text: "Verdict rule: " }), note));
    if (claim.rationale) {
      body.append(
        h(
          "div",
          { class: "commentary" },
          h("p", { class: "label", text: `Engine's commentary (${run.engine ?? "engine"}), not a verified excerpt` }),
          h("p", { text: claim.rationale }),
        ),
      );
    }
    if ((claim.queries ?? []).length) {
      body.append(h("p", { class: "queries" }, h("span", { class: "label", text: "Searched with: " }), claim.queries.join(" · ")));
    }
    const ids = claim.finding_ids ?? [];
    if (ids.length === 0) {
      body.append(h("p", { class: "muted", text: run.status === "running" ? "Findings appear when this claim has been assessed." : "No verified finding is recorded for this claim." }));
    }
    ids.forEach((findingId) => {
      const finding = index.findings.get(findingId);
      if (!finding) body.append(h("p", { class: "muted", text: `Finding ${findingId} is listed but missing from the record.` }));
      else if (finding.verified === false) body.append(h("p", { class: "muted", text: `Finding ${findingId} was withheld (no verified quote); it is listed under "Withheld" below.` }));
      else body.append(renderFinding(finding, index));
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

function renderFinding(finding, index) {
  const stance = token(finding.stance, STANCE_MARK);
  const article = h(
    "article",
    { class: `finding s-${stance}` },
    h("header", { class: "finding-head" }, stancePill(finding.stance), h("h4", { class: "finding-statement", text: finding.statement })),
    h(
      "p",
      { class: "finding-meta" },
      h("span", { class: "muted", text: `${finding.id} · ` }),
      h("span", { title: "The engine's own qualitative estimate, not a measured probability", text: `Engine's confidence: ${finding.confidence}` }),
      ` · ${plural(finding.filings_cited, "filing", "filings")} cited`,
    ),
  );
  if (finding.rationale) {
    article.append(h("p", { class: "finding-reason" }, h("span", { class: "label", text: "Engine's reason: " }), finding.rationale));
  }
  for (const evidenceId of finding.evidence_ids ?? []) {
    const item = index.evidence.get(evidenceId);
    if (!item) {
      article.append(h("p", { class: "muted", text: `Excerpt ${evidenceId} is listed but missing from the record.` }));
      continue;
    }
    article.append(renderEvidence(item, index.sources.get(item.source_id)));
  }
  return article;
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
  return h("figure", { class: "evidence" }, h("span", { class: "evidence-id", text: `${item.id} · verified quote, highlighted` }), quote, caption);
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

function renderWithheld(run, claims) {
  const withheld = run.unsupported_findings ?? [];
  els.withheldSection.hidden = withheld.length === 0;
  els.withheld.replaceChildren(
    ...withheld.map((finding) => {
      const claim = claims.get(finding.claim_id);
      return h(
        "li",
        { class: "withheld-item" },
        h("p", { class: "withheld-head" }, stancePill(finding.stance), h("span", { class: "muted", text: ` ${finding.id} · for ${finding.claim_id}${claim ? `: ${claim.text}` : ""}` })),
        h("p", { class: "withheld-statement", text: finding.statement }),
        finding.rationale ? h("p", { class: "muted small" }, h("span", { class: "label", text: "Engine's reason: " }), finding.rationale) : "",
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

function renderSources(run) {
  const sources = run.sources ?? [];
  els.sourcesBody.replaceChildren();
  if (sources.length === 0) {
    els.sourcesBody.append(h("tr", null, h("td", { colspan: "9", class: "muted", text: run.status === "running" ? "Sources appear as they are retrieved." : "No source was recorded." })));
    return;
  }
  for (const source of sources) {
    const filing = source.kind === "sec_filing";
    const gloss = formGloss(source.form);
    const formCell = filing
      ? h("td", null, h("abbr", { title: source.accession ? `${ACCESSION_GLOSS}: ${source.accession}` : null, text: source.form ?? "Filing" }), gloss ? h("span", { class: "gloss", text: ` ${gloss}` }) : "")
      : h("td", null, "Web page", h("span", { class: "gloss", text: ` ${source.title || ""}` }));
    const read = source.extraction_status === "extracted";
    const statusCell = read
      ? h("td", { class: "ok-read", text: "Read" })
      : h("td", { class: "not-read" }, h("span", { class: "glyph", "aria-hidden": "true", text: "⊘ " }), "Not read", source.error ? `: ${source.error}` : "");
    els.sourcesBody.append(
      h(
        "tr",
        null,
        h("th", { scope: "row", text: source.id }),
        formCell,
        h("td", { text: source.period_end ?? "—" }),
        h("td", { text: source.published_date ? `${source.published_date}${filing ? "" : " (published)"}` : "—" }),
        h("td", { text: utc(source.retrieved_at) }),
        h("td", { class: "num", text: read ? (source.sections ?? 0).toLocaleString("en-US") : "—" }),
        h("td", { class: "num", text: read ? (source.characters ?? 0).toLocaleString("en-US") : "—" }),
        statusCell,
        h("td", null, externalLink(source.url, "Open")),
      ),
    );
  }
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
  els.example.addEventListener("click", loadExample);
  els.claims.addEventListener("input", updateCounts);
  els.decision.addEventListener("input", updateCounts);
  for (const field of Object.keys(FIELD_NAMES)) {
    $(field).addEventListener("input", () => setFieldError(field, []));
  }
  state.sample = new URLSearchParams(location.search).has("sample");
  if (state.sample) {
    setFormEnabled(false);
    loadSample();
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
