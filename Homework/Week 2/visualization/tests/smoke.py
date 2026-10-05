"""Check real HTTP responses and their data relationships after startup."""

import csv
import io
import json
import time
import urllib.error
import urllib.request

ROOT = "http://127.0.0.1:8000"


def fetch(path: str) -> bytes:
    """Wait for startup, then fetch a real HTTP response."""
    for attempt in range(40):
        try:
            with urllib.request.urlopen(ROOT + path, timeout=5) as response:
                return response.read()
        except urllib.error.HTTPError:
            raise
        except urllib.error.URLError:
            if attempt == 39:
                raise
            time.sleep(0.25)
    raise RuntimeError("App did not start")


catalog = json.loads(fetch("/api/catalog"))
assert len(catalog["industries"]) == 71 and len(catalog["products"]) == 73
assert catalog["years"] == list(range(1997, 2026))
inputs = json.loads(fetch("/api/flows?mode=inputs&focus=211&selected=211"))
assert inputs["series"][-1]["amount"] == 35807
buyers = json.loads(fetch("/api/flows?mode=buyers&focus=211&selected=211"))
assert buyers["series"][-1]["amount"] == inputs["series"][-1]["amount"]
assert buyers["total"] != inputs["total"]
shifts = json.loads(fetch("/api/flows?mode=buyers&focus=335&sort=share_change"))
assert shifts["rows"][0]["share_change"] >= shifts["rows"][1]["share_change"]
empty = json.loads(fetch("/api/flows?mode=buyers&focus=GFGD"))
assert empty["total"] is None and empty["rows"] == []
for path in [
    "/api/flows?focus=invalid",
    "/api/flows?year=2099",
    "/api/flows?mode=bad",
    "/api/flows?selected=unknown",
]:
    try:
        fetch(path)
        raise AssertionError("Invalid selection was accepted")
    except urllib.error.HTTPError as exc:
        assert exc.code == 422
csv_rows = list(
    csv.reader(
        io.StringIO(
            fetch("/api/export?mode=buyers&focus=335&sort=share_change").decode()
        )
    )
)
assert csv_rows[4][0] == shifts["rows"][0]["id"]
assert b"Who buys what?" in fetch("/")
assert b"function drawTrend" in fetch("/app.js")
assert b".analysis-grid" in fetch("/styles.css")
print(
    "Smoke: both directions, time series, shares, empty data, validation, CSV and page assets passed."
)
print(
    "Example:",
    inputs["focus_name"],
    inputs["total_label"],
    "total intermediate purchases.",
)
