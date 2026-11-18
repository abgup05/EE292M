// Tests of tools/snapshots/shim.js in Node (make site-test): it answers a recorded GET from its
// file, refuses a POST and an unrecorded GET with {"error": ...}, and leaves the page's own
// files and other origins alone.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

const template = readFileSync(new URL("./shim.js", import.meta.url), "utf8");
const config = { version: 3, openRun: null, routes: { "/api/meta": "api/meta.json", "/api/runs/r1/export.md?reviewed=true": "api/runs/r1/export__reviewed-true.md" } };

function load() {
  const calls = [];
  const sandbox = {
    URL, Request, Response, JSON,
    location: new URL("https://site.test/v3/?sample"),
    document: { currentScript: { src: "https://site.test/v3/snapshot.js" }, addEventListener() {}, querySelector: () => null },
    fetch: async (input, init) => { calls.push(String(input instanceof Request ? input.url : input)); return new Response("recorded"); },
    addEventListener() {},
  };
  sandbox.window = sandbox;
  vm.runInNewContext(template.replace("/*SNAPSHOT*/null", JSON.stringify(config)), sandbox);
  return { fetch: sandbox.window.fetch, calls };
}

test("a recorded GET is answered from its file under the snapshot", async () => {
  const { fetch, calls } = load();
  const response = await fetch("/api/meta", { headers: { accept: "application/json" } });
  assert.equal(await response.text(), "recorded");
  assert.deepEqual(calls, ["https://site.test/v3/api/meta.json"]);
});

test("the query string is part of the key", async () => {
  const { fetch, calls } = load();
  await fetch("/api/runs/r1/export.md?reviewed=true");
  assert.deepEqual(calls, ["https://site.test/v3/api/runs/r1/export__reviewed-true.md"]);
  const missing = await fetch("/api/runs/r1/export.md");
  assert.equal(missing.status, 404);
});

test("a POST is refused with an error the page shows, and nothing is fetched", async () => {
  const { fetch, calls } = load();
  const response = await fetch("/api/runs", { method: "POST", body: "{}" });
  assert.equal(response.status, 405);
  const payload = await response.json();
  assert.match(payload.error, /recorded snapshot of Evidence Desk version 3: it cannot start a run/);
  assert.deepEqual(calls, []);
});

test("an unrecorded GET is refused and named", async () => {
  const { fetch, calls } = load();
  const response = await fetch("/api/runs/unknown");
  assert.equal(response.status, 404);
  assert.match((await response.json()).error, /no answer for GET \/api\/runs\/unknown/);
  assert.deepEqual(calls, []);
});

test("the page's own files and other origins pass through", async () => {
  const { fetch, calls } = load();
  await fetch("sample-run.json", { cache: "no-store" });
  await fetch("https://www.sec.gov/x");
  assert.deepEqual(calls, ["sample-run.json", "https://www.sec.gov/x"]);
});
