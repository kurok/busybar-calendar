import asyncio
from datetime import UTC, datetime, timedelta

from busybar_calendar.config import Config
from busybar_calendar.events import CalendarRef, Event
from busybar_calendar.runner import Runner

T0 = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
REF = CalendarRef("Work", "Work", 0)
CONFIG = Config.model_validate(
    {
        "sources": [{"name": "Work", "type": "ics", "url": "https://x"}],
    }
)


class FakeBar:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.fail = 0

    async def display_draw(self, display_data, **kwargs):
        if self.fail:
            self.fail -= 1
            raise ConnectionError("unreachable")
        self.calls.append(("draw", [e.id for e in display_data.elements]))

    async def display_clear(self, **kwargs):
        self.calls.append(("clear", kwargs.get("application_name")))

    async def audio_play(self, *, stock_path=None, **kwargs):
        self.calls.append(("sound", stock_path.rsplit("/", 1)[-1]))


class FakeSource:
    name = "Work"

    def __init__(self, events) -> None:
        self.events = events
        self.fail = False

    async def fetch(self, start, end):
        if self.fail:
            raise OSError("server down")
        return list(self.events)

    async def aclose(self):
        pass


def make(events, config=CONFIG):
    bar, source = FakeBar(), FakeSource(events)
    return Runner(config, bar, [source]), bar, source


def at(minutes):
    return T0 + timedelta(minutes=minutes)


def meeting(start_min=10, length=30, title="Sync"):
    start = at(start_min)
    return Event("m", title, start, start + timedelta(minutes=length), REF)


async def test_full_life_of_an_event():
    runner, bar, _ = make([meeting()])
    await runner.refresh(at(0))
    await runner.tick(at(0))
    await runner.tick(at(5))
    await runner.tick(at(6))  # unchanged, no redraw
    await runner.tick(at(10))
    await runner.tick(at(40))
    assert bar.calls == [
        ("clear", "busybar_calendar"),  # whatever an earlier run left behind
        ("draw", ["cal_icon", "cal_title", "cal_time"]),
        ("sound", "calendar_reminder_ends.snd"),
        ("draw", ["cal_icon", "cal_title", "cal_time"]),
        ("sound", "calendar_event_starts.snd"),
        ("clear", "busybar_calendar"),
    ]


async def test_restart_mid_meeting_does_not_chime():
    runner, bar, _ = make([meeting()])
    await runner.refresh(at(20))
    await runner.tick(at(20))
    assert bar.calls == [("draw", ["cal_icon", "cal_title", "cal_time"])]


async def test_failed_draw_is_retried():
    runner, bar, _ = make([meeting()])
    bar.fail = 1
    await runner.refresh(at(5))
    await runner.tick(at(5))
    assert bar.calls == []
    await runner.tick(at(5.5))
    assert bar.calls == [
        ("draw", ["cal_icon", "cal_title", "cal_time"]),
        ("sound", "calendar_reminder_ends.snd"),
    ]


async def test_failed_refresh_keeps_events():
    runner, bar, source = make([meeting()])
    await runner.refresh(at(0))
    source.fail = True
    await runner.refresh(at(9))
    await runner.tick(at(12))
    assert bar.calls[0] == ("draw", ["cal_icon", "cal_title", "cal_time"])


async def test_renamed_event_redraws_without_chime():
    runner, bar, source = make([meeting()])
    await runner.refresh(at(10))
    await runner.tick(at(10))
    source.events = [meeting(title="Sync (moved room)")]
    await runner.refresh(at(12))
    await runner.tick(at(12))
    assert [c[0] for c in bar.calls] == ["draw", "sound", "draw"]


async def test_run_wakes_on_time_and_clears_on_stop():
    clock = [at(4.999)]
    runner, bar, _ = make([meeting()])
    runner.now = lambda: clock[0]
    stop = asyncio.Event()
    task = asyncio.create_task(runner.run(stop))
    await asyncio.sleep(0.05)
    clock[0] = at(5)  # the reminder opens; the loop wakes within its 0.2s floor
    await asyncio.sleep(0.4)
    stop.set()
    await task
    kinds = [c[0] for c in bar.calls]
    assert kinds == ["clear", "draw", "sound", "clear"]
