"""The service and the commands, started the way a user starts them, against the emulator."""

from __future__ import annotations

import json
import signal
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from emulator_support import Emulator, Running, vevent, wait_for

from busybar_calendar import render
from busybar_calendar.config import DisplayConfig, ReminderSettings, StatusSettings
from busybar_calendar.events import CalendarRef, Event
from busybar_calendar.schedule import Screen

APP = "busybar-calendar"
APP_PY = Path(__file__).resolve().parents[2] / "app.py"
RED, YELLOW = "#FF0000FF", render.TENTATIVE_COLOR
DRAW = ("POST", "/api/display/draw")
AUDIO = ("POST", "/api/audio/play")
LAYOUTS = ["default", "banner", "bold_title", "words"]


def now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def drawn(bar: Emulator, running: Running, what: str) -> dict:
    """Wait until the service has put something on the bar; fail early if it died."""

    def frame() -> dict | None:
        if running.process.poll() is not None:
            pytest.fail(
                f"exited with {running.process.returncode}:\n{running.text()}", pytrace=False
            )
        found = bar.frame()
        return found if found["application_name"] == APP and found["elements"] else None

    return wait_for(frame, f"the service to draw {what}\n{running.text()}")  # type: ignore[return-value]


def texts(frame: dict) -> dict[str, str]:
    """The colour of each text on the display, by its words (None: the default, white)."""
    return {e["text"]: e.get("color") for e in frame["elements"] if e["type"] == "text"}


def has_text(frame: dict, words: str) -> bool:
    return any(words in e["text"] for e in frame["elements"] if e["type"] == "text")


def audio(bar: Emulator, since: float) -> list[str]:
    return [note for method, path, note in bar.calls(since) if (method, path) == AUDIO]


def run_service(start, config) -> Running:
    return start("-m", "busybar_calendar", "-v", "-c", str(config), "run")


def test_a_reminder_is_drawn_with_its_chime_and_the_bar_is_cleared_on_stop(
    emulator, feed, write_config, start
):
    opens = now() + timedelta(minutes=4, seconds=40)  # the 5-minute reminder opened 20s ago
    feed.set(vevent("a", "Design review", opens, opens + timedelta(minutes=30)))
    since = time.time()

    service = run_service(start, write_config(sound=True))
    frame = drawn(emulator, service, "the reminder")

    assert frame["priority"] == 91
    assert has_text(frame, "Design review")
    [countdown] = [e for e in frame["elements"] if e["type"] == "countdown"]
    assert countdown["timestamp"] == str(int(opens.timestamp()))
    assert "BUSY" not in texts(frame)

    assert service.stop() == 0
    assert audio(emulator, since) == ["shared/sounds/calendar_reminder_ends.snd"]
    assert emulator.frame()["elements"] == [], "the service must clear the bar when it stops"


def test_an_event_in_progress_is_busy_in_red_and_a_restart_does_not_chime_again(
    emulator, feed, write_config, start
):
    began = now() - timedelta(minutes=2)
    ends = began + timedelta(minutes=30)
    feed.set(vevent("a", "Design review", began, ends))
    since = time.time()

    service = run_service(start, write_config(sound=True))
    frame = drawn(emulator, service, "the status")

    assert texts(frame)["BUSY"] == RED
    [countdown] = [e for e in frame["elements"] if e["type"] == "countdown"]
    assert countdown["timestamp"] == str(int(ends.timestamp()))
    assert service.stop() == 0
    assert audio(emulator, since) == []  # it started two minutes ago: no chime now
    assert emulator.frame()["elements"] == []


@pytest.mark.parametrize(
    ("extra", "colour"),
    [("", YELLOW), ("[display]\ntentative_yellow = false\n", RED)],
    ids=["yellow", "tentative_yellow-off"],
)
def test_an_event_you_marked_maybe_is_busy_in_yellow(
    extra, colour, emulator, feed, write_config, start
):
    began = now() - timedelta(minutes=2)
    feed.set(vevent("a", "Design review", began, began + timedelta(minutes=30), "TENTATIVE"))

    service = run_service(start, write_config(extra))
    frame = drawn(emulator, service, "the status")

    assert texts(frame)["BUSY"] == colour
    assert service.stop() == 0


def test_what_you_accepted_wins_over_a_newer_maybe(emulator, feed, write_config, start):
    when = now()
    feed.set(
        vevent(
            "maybe",
            "Maybe talk",
            when - timedelta(minutes=1),
            when + timedelta(minutes=30),
            "TENTATIVE",
        ),
        vevent("yes", "Sure thing", when - timedelta(minutes=3), when + timedelta(minutes=30)),
    )

    service = run_service(start, write_config())
    frame = drawn(emulator, service, "the status")

    assert has_text(frame, "Sure thing") and not has_text(frame, "Maybe talk")
    assert texts(frame)["BUSY"] == RED
    assert service.stop() == 0


def test_nothing_is_drawn_while_nothing_is_due(emulator, feed, write_config, start):
    later = now() + timedelta(hours=3)
    feed.set(vevent("a", "Design review", later, later + timedelta(minutes=30)))
    since = time.time()

    service = run_service(start, write_config())
    wait_for(lambda: "Feed: 1 events" in service.text(), "the feed to be read", timeout=20)
    time.sleep(0.5)

    assert emulator.frame()["elements"] == []
    assert [call for call in emulator.calls(since) if call[:2] == DRAW] == []
    assert service.stop() == 0


@pytest.mark.parametrize("layout", LAYOUTS)
def test_the_layout_in_the_config_is_the_one_drawn(layout, emulator, feed, write_config, start):
    began = now() - timedelta(minutes=2)
    feed.set(vevent("a", "Design review", began, began + timedelta(minutes=30)))
    event = Event(
        "a", "Design review", began, began + timedelta(minutes=30), CalendarRef("Feed", "Feed", 0)
    )
    wanted = render.elements(
        Screen("status", event, ReminderSettings(), StatusSettings()), DisplayConfig(layout=layout)
    )

    service = run_service(start, write_config(f'[display]\nlayout = "{layout}"\n'))
    frame = drawn(emulator, service, f"the {layout} design")

    assert sorted(e["id"] for e in frame["elements"]) == sorted(e.id for e in wanted)
    assert service.stop() == 0


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="the emulator answers /api/status/firmware with target 'emu'; the bar, and busylib's "
    "model of it, have an integer, so `check` calls the emulator unreachable. Reported as "
    "maxswinkels/busybar-emulator#1: when the pinned emulator has the fix this passes, strict "
    "makes it fail, and the mark goes",
)
def test_check_finds_the_emulator_and_the_calendar(emulator, feed, write_config, start):
    later = now() + timedelta(hours=2)
    feed.set(vevent("a", "Design review", later, later + timedelta(minutes=30)))
    check = start("-m", "busybar_calendar", "-c", str(write_config()), "check", "--json")

    code = check.wait()
    report = json.loads(check.text())

    assert (code, report["ok"]) == (0, True), check.text()
    [bar] = [f for f in report["findings"] if f.get("area") == "bar"]
    assert (bar["ok"], bar["api"]) == (True, "25.0.0")
    assert bar["where"] == emulator.host


def test_demo_draws_the_event_and_takes_it_down_again(emulator, write_config, start):
    since = time.time()

    demo = start(
        "-m", "busybar_calendar", "-c", str(write_config()), "demo", "--status", "--seconds", "1"
    )

    assert demo.wait() == 0, demo.text()
    calls = [
        call[:2] + ((call[2],) if call[0] == "DELETE" else ()) for call in emulator.calls(since)
    ]
    assert DRAW in [call[:2] for call in calls]
    assert ("DELETE", "/api/display/draw", APP) in calls
    assert emulator.frame()["elements"] == []


def test_the_gallery_entry_point_draws_a_test_frame(emulator, start):
    test = start(str(APP_PY), "--test", "--host", emulator.host)

    assert test.wait() == 0, test.text()
    frame = emulator.frame()
    assert (frame["application_name"], frame["priority"]) == (APP, 91)
    assert texts(frame)["BUSY"] == RED


def test_the_gallery_entry_point_plays_the_demo_until_interrupted(emulator, start):
    demo = start(str(APP_PY), "--demo", "--host", emulator.host)

    frame = drawn(emulator, demo, "the demo")

    assert has_text(frame, "Design review")
    assert demo.stop(signal.SIGINT) == 0, demo.text()
    assert emulator.frame()["elements"] == []


def test_a_subprocess_here_can_find_no_config_of_the_person_running_the_tests(start):
    """What keeps these tests off the real bar of whoever runs them."""
    lookup = start("-m", "busybar_calendar", "check")

    assert lookup.wait() != 0
    assert "config" in lookup.text().lower(), lookup.text()
