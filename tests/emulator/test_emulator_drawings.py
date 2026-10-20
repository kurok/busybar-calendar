"""What the app draws, held to the emulator's idea of what a bar accepts."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta

import pytest
from busylib.client import AsyncBusyBar
from busylib.exceptions import BusyBarAPIError
from emulator_support import Emulator, Feed, vevent

from busybar_calendar import connect, render
from busybar_calendar.config import (
    STOCK_STATUSES,
    Config,
    DisplayConfig,
    ReminderSettings,
    StatusSettings,
)
from busybar_calendar.events import CalendarRef, Event
from busybar_calendar.runner import Runner
from busybar_calendar.schedule import Screen

APP = "busybar-calendar"
PRIORITY = 91
LAYOUTS = ["default", "banner", "bold_title", "words"]
FONTS = ["tiny", "small", "global"]
# A short title, one that has to scroll, and one the bitmap fonts cannot draw.
TITLES = ["Design review", "Quarterly planning with the design team", "Планування спринту"]
RED, YELLOW = "#FF0000FF", render.TENTATIVE_COLOR
REF = CalendarRef("Work", "Work", 0)


def config_for(emulator: Emulator, **display) -> Config:
    return Config.model_validate(
        {
            "bar": {"address": emulator.host},
            "display": display,
            "sources": [{"name": "Work", "type": "ics", "url": "http://127.0.0.1:9/x.ics"}],
        }
    )


@pytest.fixture
async def real_bar(emulator: Emulator) -> AsyncIterator[AsyncBusyBar]:
    """The same client the service uses, pointed at the emulator."""
    bar = connect.make_bar(config_for(emulator))
    yield bar
    await bar.aclose()


def screen(kind: str, title: str = "Design review", response: str = "accepted") -> Screen:
    now = datetime.now(UTC).replace(microsecond=0)
    start = now + timedelta(minutes=5) if kind == "reminder" else now - timedelta(minutes=2)
    event = Event("e", title, start, start + timedelta(minutes=30), REF, response)
    return Screen(kind, event, ReminderSettings(), StatusSettings())


def by_id(elements: list[dict]) -> dict[str, dict]:
    return {element["id"]: element for element in elements}


def accents(elements: list[dict]) -> set[str]:
    """The colours on a drawing other than the white and black lettering."""
    found: set[str] = set()
    for element in elements:
        found |= {element[key] for key in ("color", "border_color") if element.get(key)}
        found |= set(element.get("fill_colors", []))
    return found - {render.WHITE, render.BLACK}


def test_the_emulator_has_the_stock_animations_and_sounds_the_app_draws_with(emulator):
    animations, sounds = emulator.get("/api/_animations"), emulator.get("/api/_sounds")
    assert [s for s in STOCK_STATUSES if f"{s}_72x16" not in animations] == []
    display = DisplayConfig()
    wanted = (display.reminder_sound, display.event_sound)
    assert [s for s in wanted if s.rsplit("/", 1)[-1].removesuffix(".snd") not in sounds] == []


@pytest.mark.parametrize("font", FONTS)
@pytest.mark.parametrize("layout", LAYOUTS)
async def test_every_design_is_one_the_bar_takes_and_holds_as_drawn(
    layout, font, emulator, real_bar
):
    display = DisplayConfig(layout=layout, title_font=font)
    for kind in ("reminder", "status"):
        for response in ("accepted", "tentative"):
            for title in TITLES:
                shown = screen(kind, title, response)
                where = f"{layout}/{font}/{kind}/{response}/{title!r}"
                drawing = render.drawing(shown, display, APP, PRIORITY)

                emulator.reset()  # a draw merges into what is up, by id; start from blank
                await render.send(real_bar, drawing)  # a 400 raises

                frame = emulator.frame()
                assert (frame["application_name"], frame["priority"]) == (APP, PRIORITY), where
                held = by_id(frame["elements"])
                assert held == by_id(drawing.payload()["elements"]), where
                assert len(held) == len(frame["elements"]), f"{where}: an id used twice"
                counts = [e for e in held.values() if e["type"] == "countdown"]
                assert len(counts) == 1, where
                assert counts[0]["direction"] == "time_left", where
                assert counts[0]["timestamp"] == str(int(shown.until.timestamp())), where
                # Yellow means "maybe", red means "yes"; the two never share a screen.
                assert accents(frame["elements"]) <= {YELLOW if response == "tentative" else RED}, (
                    where
                )


@pytest.mark.parametrize("status", STOCK_STATUSES)
async def test_the_bars_own_statuses_are_drawn_as_the_animations_it_has(status, emulator, real_bar):
    shown = screen("status")
    shown = Screen("status", shown.event, shown.reminder, StatusSettings(show=status))
    await render.send(real_bar, render.drawing(shown, DisplayConfig(), APP, PRIORITY))

    [element] = emulator.frame()["elements"]
    assert element["type"] == "animation"
    assert element["stock_path"] == f"shared/animations/{status}_72x16.anim"
    assert f"{status}_72x16" in emulator.get("/api/_animations")


async def test_something_with_a_higher_priority_keeps_the_screen(emulator, real_bar):
    drawing = render.drawing(screen("reminder"), DisplayConfig(), APP, PRIORITY)
    emulator.post("/api/_scenario/steal", priority=95)

    with pytest.raises(BusyBarAPIError) as refused:
        await render.send(real_bar, drawing)

    assert refused.value.status_code == 409
    assert emulator.frame()["application_name"] != APP
    emulator.post("/api/_scenario/reset")
    await render.send(real_bar, drawing)
    assert emulator.frame()["application_name"] == APP


async def test_clearing_takes_down_only_this_apps_drawing(emulator, real_bar):
    ours = render.drawing(screen("status"), DisplayConfig(), APP, PRIORITY)
    runner = Runner(config_for(emulator), real_bar, [])

    await render.send(real_bar, ours)
    await runner.clear()
    assert emulator.frame()["elements"] == []

    await render.send(real_bar, ours)
    emulator.post("/api/_scenario/steal", priority=99)  # another app takes over the canvas
    await runner.clear()
    assert emulator.frame()["application_name"] != APP
    assert emulator.frame()["elements"], "clearing this app must leave the other one up"


@pytest.mark.parametrize("layout", LAYOUTS)
async def test_changing_screens_leaves_nothing_of_the_last_one_on_the_bar(
    layout, emulator, real_bar
):
    """The bar merges a draw into what the app already shows, by id; the runner must clear."""
    config = config_for(emulator, layout=layout)
    runner = Runner(config, real_bar, [])
    walk = [
        screen("reminder"),
        screen("status"),
        screen("reminder", response="tentative"),
        screen("status", response="tentative"),
        screen("status"),
        screen("reminder"),
    ]
    for step, shown in enumerate(walk):
        await runner.show(shown, chime=False)
        wanted = render.drawing(shown, config.display, APP, PRIORITY).payload()["elements"]
        assert by_id(emulator.frame()["elements"]) == by_id(wanted), f"{layout}: step {step}"

    # An edited config can change the design while a screen is up.
    for other in (name for name in LAYOUTS if name != layout):
        edited = config_for(emulator, layout=other)
        runner.reconfigure(edited, [])
        await runner.show(walk[1], chime=False)
        wanted = render.drawing(walk[1], edited.display, APP, PRIORITY).payload()["elements"]
        assert by_id(emulator.frame()["elements"]) == by_id(wanted), f"{layout} -> {other}"


@pytest.fixture
def due_soon(emulator: Emulator, feed: Feed, real_bar: AsyncBusyBar) -> Callable:
    """A runner on a calendar with one event 3 minutes away, and the time it is read at."""
    now = datetime.now(UTC).replace(microsecond=0)
    feed.set(vevent("soon", "Design review", now + timedelta(minutes=3), now + timedelta(hours=1)))
    config = Config.model_validate(
        {
            "bar": {"address": emulator.host},
            "sources": [{"name": "Feed", "type": "ics", "url": feed.url}],
        }
    )
    runner = Runner(config, real_bar, connect.make_sources(config))

    async def prepare() -> tuple[Runner, datetime]:
        await runner.refresh(now)
        return runner, now

    return prepare


async def test_a_screen_the_bar_refused_is_drawn_when_it_can_be(emulator, due_soon):
    runner, now = await due_soon()
    emulator.post("/api/_scenario/steal", priority=99)

    await runner.tick(now)  # 409: swallowed, not raised

    assert emulator.frame()["application_name"] != APP
    emulator.post("/api/_scenario/reset")
    await runner.tick(now)
    assert (emulator.frame()["application_name"], emulator.frame()["priority"]) == (APP, PRIORITY)
    await runner.clear()
    await asyncio.gather(*(source.aclose() for source in runner.sources))


async def test_a_bar_that_drops_off_the_network_is_drawn_when_it_is_back(emulator, due_soon):
    runner, now = await due_soon()
    emulator.post("/api/_scenario/offline", duration_ms=1500)

    await runner.tick(now)  # connection reset: swallowed, not raised

    assert emulator.frame()["elements"] == []
    await asyncio.sleep(1.8)
    await runner.tick(now)
    assert emulator.frame()["application_name"] == APP
    await runner.clear()
    await asyncio.gather(*(source.aclose() for source in runner.sources))
