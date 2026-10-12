"""
The loop: refresh the sources, decide the screen, draw it when it changes.

The loop sleeps until the next moment the screen can change - a reminder
opening, an event starting or ending - or the next refresh, whichever is
first, so a reminder appears on the second rather than on the next poll.

A source that fails keeps its last good events, so a calendar server
hiccup does not take a running meeting off the bar. A bar that refuses a
drawing (unreachable, or something above our priority on screen) is tried
again shortly.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from busylib import types

from . import render, schedule
from .config import Config, ReminderSettings, StatusSettings
from .events import Event
from .sources import Source

logger = logging.getLogger(__name__)

# Upper bound on a sleep, so a laptop waking up catches up within a minute.
MAX_SLEEP = timedelta(seconds=60)
RETRY = timedelta(seconds=15)
# A sound plays only for a screen that has just opened: restarting this
# service in the middle of a meeting must not chime again.
SOUND_GRACE = timedelta(seconds=60)
# Events still running were in the past when they started; look back far
# enough to see any of them (longer ones count as all-day and are skipped).
LOOKBACK = timedelta(hours=24)

_UNKNOWN = object()


class Bar(Protocol):
    async def display_draw(
        self, display_data: types.DisplayElements, **kwargs: Any
    ) -> types.SuccessResponse: ...

    async def display_clear(self, **kwargs: Any) -> types.SuccessResponse: ...

    async def audio_play(self, *, stock_path: str | None = None, **kwargs: Any) -> Any: ...


class Runner:
    def __init__(
        self,
        config: Config,
        bar: Bar,
        sources: Sequence[Source],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.config = config
        self.bar = bar
        self.sources = list(sources)
        self.now = now
        self._events: dict[str, list[Event]] = {}
        self._settings: dict[tuple[str, str], tuple[ReminderSettings, StatusSettings]] = {}
        self._shown: object = _UNKNOWN
        self._sounded: set[tuple[str, str]] = set()
        self._next_refresh = datetime.min.replace(tzinfo=UTC)

    @property
    def app(self) -> str:
        return self.config.bar.application_name

    @property
    def events(self) -> list[Event]:
        return [event for events in self._events.values() for event in events]

    def settings_for(self, event: Event) -> tuple[ReminderSettings, StatusSettings]:
        key = (event.calendar.source, event.calendar.name)
        if key not in self._settings:
            self._settings[key] = self.config.settings_for(*key)
        return self._settings[key]

    async def refresh(self, now: datetime) -> None:
        start = now - LOOKBACK
        end = now + timedelta(hours=self.config.sync.lookahead_hours)
        results = await asyncio.gather(
            *(source.fetch(start, end) for source in self.sources), return_exceptions=True
        )
        for source, result in zip(self.sources, results, strict=True):
            if isinstance(result, BaseException):
                kept = len(self._events.get(source.name, []))
                logger.warning(
                    "%s: refresh failed (%s); keeping %d events", source.name, result, kept
                )
                continue
            self._events[source.name] = result
            logger.debug("%s: %d events", source.name, len(result))

    def _opened_at(self, screen: schedule.Screen) -> datetime:
        if screen.kind == "status":
            return screen.event.start
        return screen.event.start - timedelta(minutes=screen.reminder.minutes_before)

    async def tick(self, now: datetime) -> None:
        screen = schedule.choose(now, self.events, self.settings_for)
        key = screen.key if screen is not None else None
        if key == self._shown:
            return
        try:
            if screen is None:
                await self.bar.display_clear(application_name=self.app)
                logger.info("cleared")
            else:
                drawing = render.drawing(
                    screen, self.config.display, self.app, self.config.bar.priority
                )
                await self.bar.display_draw(drawing)
                logger.info(
                    "%s: %s (%s) until %s",
                    screen.kind,
                    screen.event.title,
                    screen.event.calendar.name,
                    screen.until.isoformat(),
                )
                await self._chime(screen, now)
            self._shown = key
        except Exception as error:
            logger.warning("bar refused the update (%s); retrying", error)
            self._shown = _UNKNOWN

    async def _chime(self, screen: schedule.Screen, now: datetime) -> None:
        moment = (screen.kind, screen.event.key)
        if moment in self._sounded:
            return
        self._sounded.add(moment)
        sound = render.sound(screen, self.config.display)
        if sound is None or now - self._opened_at(screen) > SOUND_GRACE:
            return
        try:
            await self.bar.audio_play(stock_path=sound, application_name=self.app)
        except Exception as error:  # a missing sound is not worth a redraw
            logger.warning("could not play %s: %s", sound, error)

    async def run(self, stop: asyncio.Event) -> None:
        try:
            while not stop.is_set():
                now = self.now()
                if now >= self._next_refresh:
                    await self.refresh(now)
                    self._next_refresh = now + timedelta(minutes=self.config.sync.poll_minutes)
                await self.tick(now)

                wake = min(now + MAX_SLEEP, self._next_refresh)
                change = schedule.next_change(now, self.events, self.settings_for)
                if change is not None:
                    wake = min(wake, change)
                if self._shown is _UNKNOWN:
                    wake = min(wake, now + RETRY)
                timeout = max(0.2, (wake - self.now()).total_seconds())
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout)
        finally:
            try:
                await self.bar.display_clear(application_name=self.app)
            except Exception as error:
                logger.warning("could not clear the bar on exit: %s", error)
