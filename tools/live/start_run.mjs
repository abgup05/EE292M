// Start one no-key run of each version's own example on a running function and print
// "VERSION RUN_ID" once it has finished (make site-live-shots reads these lines).
//
//   node tools/live/start_run.mjs SERVER [VERSION ...]
import { readFileSync } from "node:fs";

const [server, ...only] = process.argv.slice(2);
const V1_EXAMPLE = JSON.parse(readFileSync(new URL("../snapshots/v1-example.json", import.meta.url), "utf8"));

async function ready() {
  for (let i = 0; ; i += 1) {
    try {
      const response = await fetch(`${server}/live/status`);
      if (response.ok) return response.json();
    } catch (error) {
      if (i >= 60) throw error;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
}

const status = await ready();
const versions = only.length ? only.map(Number) : Object.keys(status.versions).map(Number);
for (const n of versions) {
  const research = n === 1;
  const body = research
    ? V1_EXAMPLE
    : { ...(await (await fetch(`${server}/v${n}/api/meta`)).json()).example, extra_urls: [] };
  // Without the shim's header the answer is the version's own, sent once the run has finished.
  const response = await fetch(`${server}/v${n}/api/${research ? "research" : "runs"}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const answer = await response.json();
  if (response.status !== 202) {
    console.error(`v${n}: the run did not start: ${JSON.stringify(answer).slice(0, 300)}`);
    process.exitCode = 1;
    continue;
  }
  console.log(`${n} ${answer.id}`);
}
