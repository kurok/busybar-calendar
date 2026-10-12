import asyncio
from datetime import UTC, datetime, timedelta

from busylib.exceptions import BusyBarAPIError

from busybar_calendar.config import Config
from busybar_calendar.events import CalendarRef, Event
from busybar_calendar.runner import Runner

T0 = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
REF = CalendarRef("Work", "Work", 0)
CONFIG = Config.model_validate({"sources": [{"name": "Work", "type": "ics", "url": "https://x"}]})
TITLED = ("draw", ["cal_icon", "cal_title", "cal_time"])  # the reminder
BUSY = ("draw", ["cal_xpm", "cal_title", "cal_time", "cal_busy"])  # the status
CLEAR = ("clear", "busybar_calendar")


class FakeBar:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.fail = 0
        self.someone_else_on_screen = False

    async def api_request(self, method, path, json_payload=None, **kwargs):
        assert (method, path) == ("POST", "/api/display/draw")
        if self.fail:
            self.fail -= 1
            raise ConnectionError("unreachable")
        self.calls.append(("draw", [e["id"] for e in json_payload["elements"]]))

    async def display_clear(self, **kwargs):
        if self.someone_else_on_screen:
            raise BusyBarAPIError("Bad Request", status_code=400, method="DELETE")
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
        CLEAR,  # whatever an earlier run left behind
        TITLED,
        ("sound", "calendar_reminder_ends.snd"),
        CLEAR,  # the status has other elements: the red calendar and BUSY
        BUSY,
        ("sound", "calendar_event_starts.snd"),
        CLEAR,
    ]


async def test_same_elements_update_in_place():
    config = Config.model_validate(
        {
            "display": {"event_icon": "animation", "busy_label": ""},
            "sources": [{"name": "Work", "type": "ics", "url": "https://x"}],
        }
    )
    runner, bar, _ = make([meeting()], config)
    await runner.refresh(at(5))
    await runner.tick(at(5))
    await runner.tick(at(10))
    # Reminder and status share their element ids: no clear, so no flicker.
    assert [c for c in bar.calls if c[0] != "sound"] == [CLEAR, TITLED, TITLED]


async def test_first_draw_after_start_clears_leftovers():
    runner, bar, _ = make([meeting()])
    await runner.refresh(at(20))
    await runner.tick(at(20))
    # Restarted mid-meeting: no chime, and the old run's drawing goes first.
    assert bar.calls == [CLEAR, BUSY]


async def test_layout_change_clears_before_drawing():
    config = Config.model_validate(
        {
            "sources": [
                {
                    "name": "Work",
                    "type": "ics",
                    "url": "https://x",
                    "status": {"show": "meeting", "sound": False},
                    "reminder": {"sound": False},
                }
            ]
        }
    )
    runner, bar, _ = make([meeting()], config)
    await runner.refresh(at(5))
    await runner.tick(at(5))
    await runner.tick(at(10))
    # The meeting animation has other ids than the reminder, which a draw
    # would otherwise leave underneath it.
    assert bar.calls == [CLEAR, TITLED, CLEAR, ("draw", ["cal_status"])]


async def test_clear_when_another_app_owns_the_screen():
    runner, bar, _ = make([meeting()])
    bar.someone_else_on_screen = True
    await runner.refresh(at(0))
    await runner.tick(at(0))
    await runner.tick(at(1))
    assert bar.calls == []  # 400 means nothing of ours is there: done, no retry loop
    bar.someone_else_on_screen = False
    await runner.tick(at(5))
    assert bar.calls[0] == TITLED  # known clear already, so no second clear


async def test_failed_draw_is_retried():
    runner, bar, _ = make([meeting()])
    bar.fail = 1
    await runner.refresh(at(5))
    await runner.tick(at(5))
    assert bar.calls == [CLEAR]
    await runner.tick(at(5.5))
    assert bar.calls == [
        CLEAR,
        CLEAR,  # the failed draw left the screen unknown
        TITLED,
        ("sound", "calendar_reminder_ends.snd"),
    ]


async def test_failed_refresh_keeps_events():
    runner, bar, source = make([meeting()])
    await runner.refresh(at(0))
    source.fail = True
    await runner.refresh(at(9))
    await runner.tick(at(12))
    assert BUSY in bar.calls


async def test_renamed_event_redraws_without_chime():
    runner, bar, source = make([meeting()])
    await runner.refresh(at(10))
    await runner.tick(at(10))
    source.events = [meeting(title="Sync (moved room)")]
    await runner.refresh(at(12))
    await runner.tick(at(12))
    assert [c[0] for c in bar.calls] == ["clear", "draw", "sound", "draw"]


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
    assert [c[0] for c in bar.calls] == ["clear", "draw", "sound", "clear"]
