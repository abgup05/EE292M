"""Browser-level checks of the standing watch's page: the inbox, the watches and the watcher's health.

`make uitest` renders the recorded inbox (/?sample=inbox and /?sample=inbox-page-2), which draws
the watch's example payloads (docs/examples/v13, written by `make watch-examples`, copied
unedited by `make sample-inbox`), and runs uitests/watch.html, which drives the page's own code
for each answer of the watch routes. These tests compare what the page drew with the JSON:
the page orders nothing, counts nothing of the record's, and says every refusal in the
server's words.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from bs4 import BeautifulSoup, Tag
from test_dom import require_fresh

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "web"
EXAMPLES = ROOT / "docs" / "examples" / "v13"
RESULTS = ROOT / "results"
COPIES = {
    "sample-inbox.json": "inbox.json",
    "sample-inbox-page-2.json": "inbox-page-2.json",
    "sample-inbox-watches.json": "watches.json",
    "sample-inbox-health.json": "health.json",
    "sample-inbox-meta.json": "meta.json",
}
DUMPS = {"inbox": "dom-inbox.html", "inbox-page-2": "dom-inbox-page-2.html"}
RUN_NOW = "Run now (uses the model)"


def payload(name: str) -> Any:
    return json.loads((WEB / name).read_text(encoding="utf-8"))


@cache
def page(name: str) -> BeautifulSoup:
    dump = RESULTS / DUMPS[name]
    require_fresh(dump, WEB / ("sample-inbox.json" if name == "inbox" else f"sample-{name}.json"))
    soup = BeautifulSoup(dump.read_text(encoding="utf-8"), "html.parser")
    if soup.select_one("#inbox-view") is None or soup.select_one("#inbox-view[hidden]") is not None:
        pytest.fail(f"{dump.name}: the page did not show the inbox")
    return soup


def words(node: Tag | None) -> str:
    assert node is not None
    return " ".join(node.get_text().split())


def utc(iso: str) -> str:
    """The page's way of writing a time: YYYY-MM-DD HH:MM UTC (formatting, not a result)."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M UTC")


def articles(soup: BeautifulSoup) -> list[Tag]:
    return soup.select("#inbox-items > li > article.inbox-item")


def folded(soup: BeautifulSoup) -> list[Tag]:
    return soup.select("#inbox-collapsed article.inbox-item")


# ---------------------------------------------------------------- the copies


@pytest.mark.parametrize(("copy", "source"), sorted(COPIES.items()))
def test_the_samples_are_the_example_payloads_unedited(copy: str, source: str) -> None:
    assert (WEB / copy).read_bytes() == (EXAMPLES / source).read_bytes(), (
        f"src/web/{copy} differs from docs/examples/v13/{source}: run `make sample-inbox`"
    )


def test_the_page_says_where_the_recorded_inbox_comes_from() -> None:
    note = words(page("inbox").select_one("#inbox-head [data-sample-note]"))
    for phrase in ("docs/examples/v13", "make watch-examples", "scripted verdicts", "unedited", "sends nothing"):
        assert phrase in note, phrase


# ---------------------------------------------------------------- the items


@pytest.mark.parametrize("name", sorted(DUMPS))
def test_items_are_in_the_apis_order_and_the_folded_kinds_are_on_one_line(name: str) -> None:
    soup = page(name)
    items = payload(f"sample-{name}.json")["items"]
    assert [a["data-item-id"] for a in articles(soup)] == [i["id"] for i in items if not i["collapsed"]]
    assert [a["data-item-id"] for a in folded(soup)] == [i["id"] for i in items if i["collapsed"]]


def test_every_item_shows_its_kind_and_headline_in_the_records_words() -> None:
    soup = page("inbox")
    labels = payload("sample-inbox-meta.json")["kind_labels"]
    by_id = {i["id"]: i for i in payload("sample-inbox.json")["items"]}
    drawn = articles(soup) + folded(soup)
    assert len(drawn) == len(by_id) == 6
    assert {a["data-kind"] for a in drawn} == set(labels), "the sample holds one item of each of the six kinds"
    for article in drawn:
        item = by_id[article["data-item-id"]]
        assert article["data-kind"] == item["kind"]
        assert words(article.select_one("[data-kind-label]")) == f"{_glyph(article)} {labels[item['kind']]}".strip()
        assert words(article.select_one(".inbox-headline")) == " ".join(item["headline"].split())
        assert article["data-unread"] == str(item["read_at"] is None).lower()


def _glyph(article: Tag) -> str:
    glyph = article.select_one("[data-kind-label] .glyph")
    return glyph.get_text() if glyph else ""


def test_the_folded_line_counts_the_items_folded_on_this_page() -> None:
    soup = page("inbox")
    items = payload("sample-inbox.json")["items"]
    line = soup.select_one("#inbox-collapsed details.inbox-folded")
    assert line is not None and not line.has_attr("open")
    folded_items = [i for i in items if i["collapsed"]]
    assert line.select_one('[data-folded="count"]').get_text() == str(len(folded_items))
    label = payload("sample-inbox-meta.json")["kind_labels"]["not_relevant"]
    assert label in words(line.select_one("summary"))


def test_the_unread_number_is_the_apis() -> None:
    soup = page("inbox")
    inbox = payload("sample-inbox.json")
    assert soup.select_one("#inbox-count")["data-unread"] == str(inbox["unread"])
    assert words(soup.select_one("#inbox-count")) == str(inbox["unread"])
    assert soup.select_one('#inbox-head [data-inbox="unread"]').get_text() == str(inbox["unread"])
    assert soup.select_one('#inbox-head [data-inbox="total"]').get_text() == str(inbox["total"])


def test_only_the_waiting_item_has_the_run_now_button() -> None:
    soup = page("inbox")
    items = payload("sample-inbox.json")["items"]
    waiting = [i["id"] for i in items if i["kind"] == "waiting"]
    buttons = soup.select("[data-run-now]")
    assert [b["data-run-now"] for b in buttons] == waiting
    assert all(words(b) == RUN_NOW for b in buttons)
    item = next(i for i in items if i["kind"] == "waiting")
    article = soup.select_one(f'article[data-item-id="{item["id"]}"]')
    assert words(article.select_one(".waiting-reason")) == item["run"]["waiting_reason"]


def test_each_filing_is_named_and_linked_with_its_items() -> None:
    soup = page("inbox")
    for item in payload("sample-inbox.json")["items"]:
        article = soup.select_one(f'article[data-item-id="{item["id"]}"]')
        assert any(a.get("href") == item["filing"]["url"] for a in article.select("a")), item["id"]
        if item["collapsed"]:
            continue
        numbers = [li["data-item-number"] for li in article.select(".inbox-filing-items li")]
        assert numbers == [it["number"] for it in item["filing"]["items"]]
        assert item["filing"]["accession"] in words(article.select_one(".inbox-filing"))


def test_the_triage_reasons_are_given_per_claim() -> None:
    soup = page("inbox")
    for item in payload("sample-inbox.json")["items"]:
        if item["collapsed"]:
            continue
        article = soup.select_one(f'article[data-item-id="{item["id"]}"]')
        rows = article.select(".triage-claims > li")
        claims = item["triage"]["claims"]
        assert [(r["data-claim-id"], r["data-bears"]) for r in rows] == [(c["claim_id"], str(c["bears"]).lower()) for c in claims]
        for row, claim in zip(rows, claims, strict=True):
            assert [words(li) for li in row.select(".triage-reasons > li")] == claim["reasons"]
            assert [words(q) for q in row.select("blockquote.triage-paragraph")] == [p["text"] for p in claim["paragraphs"]]
        assert item["triage"]["summary"] in words(article.select_one(".triage-summary"))


def test_what_moved_is_the_records_and_the_comparison_is_one_click_away() -> None:
    soup = page("inbox")
    for item in payload("sample-inbox.json")["items"]:
        article = soup.select_one(f'article[data-item-id="{item["id"]}"]')
        moved = item["moved"]
        if moved is None:
            assert article.select_one(".inbox-moved") is None
            continue
        assert words(article.select_one(".moved-line")) == moved["line"]
        pills = article.select(".moved-verdicts .pill.verdict")
        assert [p["data-verdict"] for p in pills] == [v for change in moved["verdicts"] for v in (change["before"], change["after"])]
        compare = article.select_one("details.moved-compare")
        assert compare is not None and not compare.has_attr("open")
        links = [a.get("href") for a in article.select(".moved-events a")]
        assert links == [e["url"] for e in moved["new_events"]]


def test_a_finished_or_failed_items_run_opens_in_the_note() -> None:
    soup = page("inbox")
    for item in payload("sample-inbox.json")["items"]:
        run_id = (item["run"] or {}).get("run_id")
        buttons = soup.select(f'article[data-item-id="{item["id"]}"] [data-open-run]')
        assert [b["data-open-run"] for b in buttons] == ([run_id] if run_id else [])


# ---------------------------------------------------------------- the watches and the health


def test_each_watch_shows_its_policy_checks_and_errors_from_the_payload() -> None:
    soup = page("inbox")
    for watch in payload("sample-inbox-watches.json")["watches"]:
        card = soup.select_one(f'#watches [data-watch-thesis="{watch["thesis_id"]}"]')
        field = lambda name: words(card.select_one(f'[data-watch="{name}"]'))  # noqa: E731
        assert field("policy_label") == watch["policy_label"]
        assert field("last_check_at") == utc(watch["last_check_at"])
        assert field("next_check_at") == utc(watch["next_check_at"])
        assert field("last_error") == (watch["last_error"] or "None")
        assert field("last_job_error") == watch["last_job_error"]
        assert field("unread") == str(watch["unread"]) and field("waiting_runs") == str(watch["waiting_runs"])
        assert card.select_one("input[data-policy]:checked")["value"] == watch["policy"]
        assert card.select_one("[data-unwatch]") is not None


def test_the_watcher_health_is_in_the_bar() -> None:
    soup = page("inbox")
    health = payload("sample-inbox-health.json")
    node = soup.select_one(".cmdbar #watch-health")
    assert node is not None and not node.has_attr("hidden")
    assert node["data-alive"] == str(health["alive"]).lower()
    assert node.select_one('[data-health="queue_depth"]').get_text() == str(health["queue_depth"])
    assert node.select_one('[data-health="waiting_runs"]').get_text() == str(health["waiting_runs"])
    assert f"last cycle {utc(health['last_cycle_at'])[11:]}" in words(node)
    assert node["title"] == f"{health['note']} Last cycle {utc(health['last_cycle_at'])}."
    assert soup.select_one("#watch-down[hidden]") is not None, "an alive watcher gets no warning"


def test_the_last_page_offers_the_first_and_no_next() -> None:
    soup = page("inbox-page-2")
    assert soup.select_one("html")["data-theme"] == "terminal"
    assert [n["data-page"] for n in soup.select("#inbox-paging [data-page]")] == ["first"]
    assert soup.select_one("[data-next-offset]") is None


# ---------------------------------------------------------------- every answer of the routes (uitests/watch.html)


@cache
def steps() -> dict[str, Tag]:
    dump = RESULTS / "dom-watch.html"
    require_fresh(dump, ROOT / "uitests" / "watch.html")
    soup = BeautifulSoup(dump.read_text(encoding="utf-8"), "html.parser")
    done = soup.select_one("#done")
    if done is None or done.get("data-done") != "true":
        pytest.fail(f"the watch harness did not finish: {words(done) if done else 'no #done'}")
    return {li["data-step"]: li for li in soup.select("#steps > li")}


def recorded(step: str, field: str) -> Any:
    return json.loads(steps()[step][f"data-{field}"])


def calls(step: str) -> list[str]:
    return [c["key"] for c in recorded(step, "calls")]


def test_the_harness_ran_every_step_and_made_no_unexpected_call() -> None:
    assert list(steps()) == ["sample", "run-409", "run-202", "watch-422", "watch-503", "watch-200", "unwatch-409", "empty", "unreachable", "page-1", "page-2", "page-back", "mark-read"]
    for step in steps():
        assert recorded(step, "unexpected") == [], step


def test_a_409_on_run_now_says_so_and_reads_the_item_again() -> None:
    waiting = next(i["id"] for i in payload("sample-inbox.json")["items"] if i["kind"] == "waiting")
    assert calls("run-409")[:2] == [f"POST /api/inbox/{waiting}/run", f"GET /api/inbox/{waiting}"]
    assert recorded("run-409", "item-messages") == ["The run was not started: This inbox item has no run waiting."]
    after = json.loads((EXAMPLES / "inbox-item-after-run.json").read_text(encoding="utf-8"))
    assert steps()["run-409"]["data-kind-after"] == after["kind"]


def test_a_202_names_the_run_that_started() -> None:
    started = json.loads((EXAMPLES / "waiting-run-started.json").read_text(encoding="utf-8"))
    assert recorded("run-202", "item-messages") == [f"Run {started['id']} started."]


def test_a_refused_policy_names_the_field_and_the_radio_keeps_the_servers_policy() -> None:
    error = json.loads((EXAMPLES / "error-422.json").read_text(encoding="utf-8"))
    detail = error["details"][0]
    assert recorded("watch-422", "card-messages") == [f"The watch could not be saved: {error['error']}: {detail['field']}: {detail['message']}."]
    assert steps()["watch-422"]["data-policy-checked"] == "ask"
    assert recorded("watch-422", "calls")[0]["body"] == json.dumps({"policy": "auto"}, separators=(",", ":"))


def test_edgar_out_of_reach_says_nothing_was_saved() -> None:
    assert recorded("watch-503", "card-messages")[0].endswith("Nothing was saved.")
    assert steps()["watch-503"]["data-policy-checked"] == "ask"


def test_a_saved_policy_is_shown_as_the_server_answered_it() -> None:
    put = json.loads((EXAMPLES / "watch-put.json").read_text(encoding="utf-8"))
    assert recorded("watch-200", "card-messages") == [f"On watch: {put['watch']['policy_label']}."]
    assert steps()["watch-200"]["data-policy-checked"] == put["watch"]["policy"]


def test_a_watch_already_ended_is_shown_ended() -> None:
    assert steps()["unwatch-409"]["data-inbox-message"] == "This thesis is not on watch."
    assert recorded("unwatch-409", "empty") == ["watches"]


def test_no_watches_an_empty_inbox_and_a_watcher_not_running_are_said_plainly() -> None:
    step = steps()["empty"]
    assert recorded("empty", "empty") == ["watches", "inbox"]
    assert step["data-badge"] == "0"
    assert step["data-health-alive"] == "false"
    note = json.loads((EXAMPLES / "health-not-running.json").read_text(encoding="utf-8"))["note"]
    assert step["data-watch-down"].startswith("▲ The watcher is not running.") and note in step["data-watch-down"]


def test_an_unreachable_server_is_said_and_nothing_stale_is_kept() -> None:
    assert steps()["unreachable"]["data-inbox-message"] == "The inbox could not be loaded: the server could not be reached."
    assert recorded("unreachable", "kinds") == []


def test_paging_follows_the_apis_offsets() -> None:
    assert recorded("page-1", "paging") == ["older"]
    assert calls("page-2")[0] == "GET /api/inbox?offset=4"
    page2 = json.loads((EXAMPLES / "inbox-page-2.json").read_text(encoding="utf-8"))
    assert recorded("page-2", "kinds") == [i["kind"] for i in page2["items"] if not i["collapsed"]]
    assert recorded("page-2", "paging") == ["newer"]
    assert recorded("page-back", "paging") == ["older"]


def test_marking_read_sends_the_items_id_and_reads_the_page_again() -> None:
    target = steps()["mark-read"]["data-target"]
    sent = recorded("mark-read", "calls")
    assert sent[0]["key"] == "POST /api/inbox/read"
    assert json.loads(sent[0]["body"]) == {"ids": [target], "read": True}
    assert sent[1]["key"] == "GET /api/inbox?offset=0"
