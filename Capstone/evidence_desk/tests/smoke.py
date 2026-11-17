"""Check the live container over real HTTP without touching the internet.

Covers startup, health, the wording and limits in /api/meta, the static page
and its assets (including the sample record), refusals with field details,
and the 404 path. It never starts a run: every POST is refused before the
ticker is looked up on EDGAR.
"""

import json
import time
import urllib.error
import urllib.request

ROOT = "http://127.0.0.1:8000"
DECISION = "Whether to keep an overweight position in NVIDIA into the next earnings report"
CLAIM = "Data center revenue is still growing year over year."


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
    for attempt in range(80):
        try:
            urllib.request.urlopen(ROOT + "/api/health", timeout=5)
            return
        except urllib.error.URLError, ConnectionError:
            if attempt == 79:
                raise
            time.sleep(0.25)


def refused_fields(body: dict) -> list[str]:
    status, payload, _ = request("/api/runs", body)
    assert status == 422, (status, payload)
    parsed = json.loads(payload)
    assert parsed["error"] == "Invalid request"
    assert all(detail["message"] for detail in parsed["details"]), parsed
    return [detail["field"] for detail in parsed["details"]]


wait_for_startup()

status, body, _ = request("/api/health")
health = json.loads(body)
assert status == 200 and health["status"] == "ok" and health["version"] == "0.7.0", health
assert health["engine"] in ("claude", "extractive"), health

status, body, _ = request("/api/meta")
meta = json.loads(body)
assert status == 200
assert meta["limits"]["MAX_CLAIMS"] == 6 and meta["limits"]["RUN_TIME_LIMIT_SECONDS"] == 300
assert set(meta["status_notes"]) == {"running", "complete", "partial", "failed"}
assert set(meta["verdict_labels"]) == set(meta["verdict_notes"])
assert meta["example"]["ticker"] == "NVDA" and len(meta["example"]["claims"]) == 5
assert meta["engine"] == health["engine"]

status, body, content_type = request("/")
assert status == 200 and content_type.startswith("text/html") and b"Evidence Desk" in body
for asset, media_type in (
    ("/app.js", "text/javascript"),
    ("/styles.css", "text/css"),
    ("/sample-run.json", "application/json"),
    ("/sample-changes.json", "application/json"),
):
    status, body, content_type = request(asset)
    assert status == 200 and body and content_type.startswith(media_type), asset
sample = json.loads(request("/sample-run.json")[1])
assert {"note", "meta", "run"} <= set(sample)
recorded_changes = json.loads(request("/sample-changes.json")[1])
assert {"note", "changes"} <= set(recorded_changes)
assert {"earlier", "later", "items", "totals"} <= set(recorded_changes["changes"])

# The filing comparison is mounted; another form is refused before any filing is asked for.
status, body, _ = request("/api/companies/NVDA/changes?form=8-K")
assert status == 422 and [p["field"] for p in json.loads(body)["details"]] == ["form"]

valid = {"ticker": "NVDA", "decision": DECISION, "claims": [CLAIM]}
assert refused_fields(valid | {"ticker": "nv da$"}) == ["ticker"]
assert refused_fields(valid | {"claims": []}) == ["claims"]
assert refused_fields(valid | {"filings": 6}) == ["filings"]
assert refused_fields(valid | {"extra_urls": ["http://127.0.0.1/secret"]}) == ["extra_urls.0"]

for path in ("/api/runs/run-does-not-exist", "/api/runs/run-does-not-exist/export.md"):
    status, body, _ = request(path)
    assert status == 404 and json.loads(body) == {"detail": "Run not found"}, path

status, body, _ = request("/api/runs")
assert status == 200 and isinstance(json.loads(body)["runs"], list)
print("smoke: ok")
