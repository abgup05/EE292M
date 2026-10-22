"""Check the live container over real HTTP without touching the public internet.

Covers startup, static assets, boundary validation, the 404 path, a run that
fails honestly when it has nothing to fetch, and its Markdown export.
"""

import json
import time
import urllib.error
import urllib.request

ROOT = "http://127.0.0.1:8000"
QUESTION = (
    "What opportunities and risks should an organization examine before using "
    "generative AI in internal workflows?"
)
DECISION = "Whether to investigate a limited internal pilot"


def request(path: str, body: dict | None = None) -> tuple[int, bytes, str]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"content-type": "application/json"} if body is not None else {}
    req = urllib.request.Request(ROOT + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, response.read(), response.headers.get("content-type", "")
    except urllib.error.HTTPError as error:
        return error.code, error.read(), error.headers.get("content-type", "")


def wait_for_startup() -> None:
    for attempt in range(40):
        try:
            urllib.request.urlopen(ROOT + "/", timeout=5)
            return
        except urllib.error.URLError:
            if attempt == 39:
                raise
            time.sleep(0.25)


wait_for_startup()

status, body, _ = request("/")
assert status == 200 and b"Evidence Desk" in body
for asset in ("/app.js", "/styles.css"):
    status, body, _ = request(asset)
    assert status == 200 and body, asset

status, body, _ = request("/api/research/run-does-not-exist")
assert status == 404

status, body, _ = request(
    "/api/research",
    {"question": QUESTION, "decision": DECISION, "seed_urls": ["http://127.0.0.1/secret"]},
)
assert status == 422, (status, body)
payload = json.loads(body)
assert payload["error"] and any(d["field"].startswith("seed_urls") for d in payload["details"])

status, body, _ = request(
    "/api/research", {"question": QUESTION, "decision": DECISION, "source_budget": 99}
)
assert status == 422 and any(d["field"] == "source_budget" for d in json.loads(body)["details"])

# A run with nothing to fetch must fail with a useful error, never a synthetic answer.
status, body, _ = request("/api/research", {"question": QUESTION, "decision": DECISION})
assert status == 202, (status, body)
run_id = json.loads(body)["id"]
for _ in range(80):
    status, body, _ = request(f"/api/research/{run_id}")
    assert status == 200
    run = json.loads(body)
    if run["status"] != "running":
        break
    time.sleep(0.25)
assert run["status"] == "failed", run["status"]
assert run["brief"] is None and run["findings"] == []
assert any("nothing to retrieve" in error for error in run["errors"])
assert run["finished_at"].endswith("+00:00") or run["finished_at"].endswith("Z")

status, body, content_type = request(f"/api/research/{run_id}/export.md")
assert status == 200 and content_type.startswith("text/markdown")
assert b"FAILED" in body and QUESTION.encode() in body

status, body, _ = request("/api/research")
assert run_id in [r["id"] for r in json.loads(body)["runs"]]
print("smoke: ok")
