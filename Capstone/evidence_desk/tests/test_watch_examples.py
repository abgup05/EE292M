"""The version 13 example payloads still match the API, and their README names every field."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from app.core.watch_models import InboxItem, InboxKind
from app.watch.routes import InboxList, Marked, Unwatched, WaitingRunStarted, WatchChanged, meta
from app.watch.views import WatcherHealth, WatchList

EXAMPLES = Path(__file__).parent.parent / "docs" / "examples" / "v13"
MODELS: dict[str, type[BaseModel]] = {
    "health-not-running.json": WatcherHealth,
    "health.json": WatcherHealth,
    "watch-put.json": WatchChanged,
    "watches.json": WatchList,
    "inbox.json": InboxList,
    "inbox-page-2.json": InboxList,
    "inbox-item-after-run.json": InboxItem,
    "waiting-run-started.json": WaitingRunStarted,
    "mark-read.json": Marked,
    "unwatch.json": Unwatched,
}


def _load(name: str) -> Any:
    return json.loads((EXAMPLES / name).read_text())


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for child in value.values() for key in _keys(child)}
    if isinstance(value, list):
        return {key for child in value for key in _keys(child)}
    return set()


@pytest.mark.parametrize("name", sorted(MODELS))
def test_each_example_is_what_its_route_returns(name: str) -> None:
    MODELS[name].model_validate(_load(name))


def test_the_meta_example_is_the_meta_the_app_serves() -> None:
    assert _load("meta.json") == meta()


def test_the_inbox_example_holds_one_item_of_each_kind() -> None:
    kinds = sorted(item["kind"] for item in _load("inbox.json")["items"])

    assert kinds == sorted(kind.value for kind in InboxKind)


def test_the_readme_names_every_field_and_every_file() -> None:
    readme = (EXAMPLES / "README.md").read_text()
    named = set(re.findall(r"`([a-z_0-9]+)`", readme))
    files = sorted(path.name for path in EXAMPLES.glob("*.json"))
    fields = {key for name in files for key in _keys(_load(name))}
    # Keys of label maps are the values they label, named where those values are.
    fields -= {kind.value for kind in InboxKind}

    assert sorted(fields - named) == []
    assert [name for name in files if f"`{name}`" not in readme] == []
