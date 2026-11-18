"""The watcher process: its settings, one cycle, its status, and when it counts as alive."""

from __future__ import annotations

import pytest

from app import wiring
from app.core import watch_policy as wording
from app.core.watch_models import WatchPolicy
from app.watch.__main__ import main, status_lines
from app.watch.views import NOT_RUNNING, health
from tests.test_events_run import DEPARTURE_8K, departure_html
from tests.test_watch_service import T0, desk, gain, watch


def test_settings_default_to_fifteen_minutes_and_five_automatic_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(wiring.WATCH_INTERVAL_VARIABLE, raising=False)
    monkeypatch.delenv(wiring.WATCH_AUTO_RUNS_VARIABLE, raising=False)

    settings = wiring.watch_settings_from_env()

    assert (settings.interval_seconds, settings.auto_runs_per_day) == (900, 5)


def test_an_interval_below_the_floor_is_raised_to_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(wiring.WATCH_INTERVAL_VARIABLE, "30")
    monkeypatch.setenv(wiring.WATCH_AUTO_RUNS_VARIABLE, "0")

    settings = wiring.watch_settings_from_env()

    assert settings.interval_seconds == wording.MIN_INTERVAL_SECONDS == 300
    assert settings.auto_runs_per_day == 0


@pytest.mark.parametrize("value", ["-5", "ten", "1.5"])
def test_a_setting_that_is_not_a_whole_number_is_refused(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv(wiring.WATCH_INTERVAL_VARIABLE, value)

    with pytest.raises(wiring.ConfigurationError, match=wiring.WATCH_INTERVAL_VARIABLE):
        wiring.watch_settings_from_env()


def test_once_does_one_cycle_and_prints_its_counts(capsys: pytest.CaptureFixture[str]) -> None:
    d = desk()
    watch(d, WatchPolicy.ask)
    gain(d, DEPARTURE_8K, departure_html())

    assert main(["once"], make=lambda: d.watcher) == 0

    out = capsys.readouterr().out
    assert "1 companies checked, 0 index errors, 1 jobs queued, 1 done" in out


def test_status_says_whether_the_watcher_is_alive_and_lists_each_watch(
    capsys: pytest.CaptureFixture[str],
) -> None:
    d = desk()
    watch(d, WatchPolicy.ask)
    assert main(["status"], make=lambda: d.watcher) == 0
    assert NOT_RUNNING in capsys.readouterr().out

    d.watcher.cycle()
    lines = status_lines(d.store, d.watches, d.status, d.clock(), 900)

    assert lines[0] == "watcher: alive. The watcher finished a cycle 0 seconds ago."
    assert lines[2].startswith(f"{d.thesis_id} NVDA 'Jane Smith is gone' (ask): last check ")


def test_a_watcher_is_alive_for_two_intervals_and_a_minute_after_its_last_cycle() -> None:
    d = desk()
    assert not health(d.watches, d.status, T0, 900).alive

    d.watcher.cycle()

    d.clock.advance(2 * 900 + 60)
    assert health(d.watches, d.status, d.clock(), 900).alive
    d.clock.advance(1)
    stale = health(d.watches, d.status, d.clock(), 900)
    assert not stale.alive and "1861 seconds ago" in stale.note
