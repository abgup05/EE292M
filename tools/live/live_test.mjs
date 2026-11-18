// End-to-end test of the live versions against the function as Vercel runs it (make site-live-test).
//
//   node tools/live/live_test.mjs FIRST_SERVER FRESH_SERVER [VERSION ...]
//
// Two processes of the same function run with no key and no route to the internet (so EDGAR
// never answers and every filing comes from the seed). For each version this loads its page,
// its script and the shim the page carries; then, through that shim exactly as the page calls
// it, starts a no-key run of the version's own example (NVIDIA for versions 2 and later, the
// two example pages for version 1) on the first server and polls until the run has finished.
// It then loads the shim again, as a new page in the same browser session, against the second
// server, which has never seen the run: the server answers 404, and the shim answers with the
// finished run (and, from version 4 on, its review). Prints one line per version; exits 1 on
// any failure.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const [first, fresh, ...only] = process.argv.slice(2);
const V1_EXAMPLE = JSON.parse(readFileSync(new URL("../snapshots/v1-example.json", import.meta.url), "utf8"));
const RUN_SECONDS = 280;

function session() {
  const values = new Map();
  return {
    get length() { return values.size; },
    key: (i) => [...values.keys()][i] ?? null,
    getItem: (k) => (values.has(k) ? values.get(k) : null),
    setItem: (k, v) => values.set(k, String(v)),
    removeItem: (k) => values.delete(k),
  };
}

async function text(url) {
  const response = await fetch(url);
  assert.equal(response.status, 200, `GET ${url} answered ${response.status}`);
  return response.text();
}

/** The page's own fetch, as the shim leaves it, on a page at SERVER/vN/. */
function page(server, n, shim, storage) {
  const sandbox = {
    URL, Request, Response, Headers, JSON, TextDecoder, TextEncoder, Blob, ReadableStream,
    location: new URL(`${server}/v${n}/`),
    document: { addEventListener() {}, querySelector: () => null },
    sessionStorage: storage,
    fetch: (input, init) => fetch(input, init),
    setTimeout,
  };
  sandbox.window = sandbox;
  vm.runInNewContext(shim, sandbox);
  return sandbox.window.fetch;
}

async function one(n) {
  const html = await text(`${first}/v${n}/`);
  assert.ok(html.includes(`data-live-version="${n}"`), "no live banner");
  assert.ok(html.indexOf('src="live-shim.js"') < html.indexOf('src="app.js"'), "the shim is not loaded first");
  await text(`${first}/v${n}/app.js`);
  const shim = await text(`${first}/v${n}/live-shim.js`);
  const storage = session();
  const api = page(first, n, shim, storage);
  const research = html.includes("/api/research") || shim.includes('"/api/research"');
  let body;
  if (research) {
    body = V1_EXAMPLE;
  } else {
    const meta = await (await api("/api/meta")).json();
    body = { ...meta.example, extra_urls: [] };
  }
  const started = await api(research ? "/api/research" : "/api/runs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const answer = await started.json();
  assert.equal(started.status, 202, `the run did not start: ${JSON.stringify(answer)}`);
  const runPath = `${research ? "/api/research" : "/api/runs"}/${encodeURIComponent(answer.id)}`;
  const began = Date.now();
  let run;
  for (;;) {
    run = await (await api(runPath)).json();
    if (run.status !== "running" && run.status !== "queued") break;
    assert.ok(Date.now() - began < RUN_SECONDS * 1000, `still ${run.status} after ${RUN_SECONDS} s`);
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
  const seconds = Math.round((Date.now() - began) / 1000);
  assert.ok(["complete", "partial"].includes(run.status), `the run ended ${run.status}: ${JSON.stringify(run.errors ?? run.notes ?? "").slice(0, 300)}`);

  // A new page in the same session, on a process that never saw the run.
  const direct = await fetch(`${fresh}/v${n}${runPath}`);
  assert.equal(direct.status, 404, `the fresh process answered ${direct.status} for the run`);
  const again = page(fresh, n, await text(`${fresh}/v${n}/live-shim.js`), storage);
  const kept = await again(runPath);
  assert.equal(kept.status, 200);
  const keptRun = await kept.json();
  assert.equal(keptRun.id, answer.id);
  assert.equal(keptRun.status, run.status);
  let review = "";
  if (!research && n >= 4) {
    const reviewed = await again(`${runPath}/review`);
    assert.equal(reviewed.status, 200, "the kept review was not answered");
    review = ", its review too";
  }
  return `run ${answer.id} ${run.status} in ${seconds} s; fresh process: server 404, shim 200 (${keptRun.status})${review}`;
}

const status = await (await fetch(`${first}/live/status`)).json();
const versions = only.length ? only.map(Number) : Object.keys(status.versions).map(Number);
let failed = 0;
for (const n of versions) {
  try {
    console.log(`ok    v${String(n).padEnd(3)} ${await one(n)}`);
  } catch (error) {
    failed += 1;
    console.log(`FAIL  v${String(n).padEnd(3)} ${error.message}`);
  }
}
const after = await (await fetch(`${first}/live/status`)).json();
console.log(
  `/live/status: key_present ${after.key_present}, sec_user_agent_present ${after.sec_user_agent_present}, ` +
    `model_engine ${after.model_engine}, runs_today ${after.counts.runs_today}, ` +
    `seed answers: ${after.seed.served_without_asking_edgar} without asking EDGAR, ` +
    `${after.seed.served_because_edgar_did_not_answer} because EDGAR did not answer; ` +
    `imports ok: ${Object.values(after.versions).filter((v) => v.import_ok).length} of ${Object.keys(after.versions).length}`,
);
console.log(failed ? `${failed} of ${versions.length} versions failed.` : `Every one of ${versions.length} versions passed.`);
process.exit(failed ? 1 : 0);
