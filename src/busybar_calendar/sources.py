"""
Configured sources, each turned into a list of events for a time window.

A CalDAV source is one account with several calendars; an ICS source is a
single published feed and counts as one calendar named after the source.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, tzinfo

import httpx

from . import events
from .caldav import CalDAVClient, RemoteCalendar
from .config import SourceConfig

logger = logging.getLogger(__name__)

USER_AGENT = "busybar-calendar"
# An ICS feed is the whole calendar, history included; refuse the absurd.
MAX_FEED_BYTES = 32 * 1024 * 1024
# Calendars are listed again after this many refreshes, to pick up new ones.
REDISCOVER_EVERY = 12


def http_client(source: SourceConfig) -> httpx.AsyncClient:
    auth: httpx.Auth | None = None
    password = source.password.resolve()
    if source.username is not None and password is not None:
        auth = (
            httpx.DigestAuth(source.username, password)
            if source.auth == "digest"
            else httpx.BasicAuth(source.username, password)
        )
    return httpx.AsyncClient(
        auth=auth,
        follow_redirects=True,
        timeout=httpx.Timeout(30.0),
        headers={"User-Agent": USER_AGENT},
    )


class Source:
    def __init__(self, config: SourceConfig, index: int, floating_tz: tzinfo, skip_free: bool):
        self.config = config
        self.name = config.name
        self._index = index
        self._floating_tz = floating_tz
        self._skip_free = skip_free

    def _ref(self, calendar: str, position: int) -> events.CalendarRef:
        return events.CalendarRef(self.name, calendar, self._index * 1000 + position)

    def _parse(self, data, ref, start, end) -> list[events.Event]:
        return events.parse(
            data,
            ref,
            start,
            end,
            floating_tz=self._floating_tz,
            skip_free=self._skip_free,
            emails=self.config.emails,
        )

    async def fetch(self, start: datetime, end: datetime) -> list[events.Event]:
        raise NotImplementedError

    async def aclose(self) -> None:
        pass


class ICSSource(Source):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._http = http_client(self.config)
        self._etag: str | None = None
        self._body: bytes | None = None

    async def fetch(self, start: datetime, end: datetime) -> list[events.Event]:
        headers = {"If-None-Match": self._etag} if self._etag and self._body else {}
        response = await self._http.get(self.config.url, headers=headers)
        if response.status_code != 304:
            response.raise_for_status()
            if len(response.content) > MAX_FEED_BYTES:
                raise ValueError(f"{self.name}: feed is over {MAX_FEED_BYTES} bytes")
            self._body = response.content
            self._etag = response.headers.get("ETag")
        assert self._body is not None
        return self._parse(self._body, self._ref(self.name, 0), start, end)

    async def aclose(self) -> None:
        await self._http.aclose()


class CalDAVSource(Source):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._http = http_client(self.config)
        self._client = CalDAVClient(self._http, self.config.url)
        self._calendars: list[RemoteCalendar] = []
        self._refreshes = 0

    async def calendars(self) -> list[RemoteCalendar]:
        """Every event calendar on the account, before `include` is applied."""
        return await self._client.discover()

    async def _selected(self) -> list[tuple[int, RemoteCalendar]]:
        if not self._calendars or self._refreshes % REDISCOVER_EVERY == 0:
            self._calendars = await self.calendars()
        self._refreshes += 1
        include = self.config.include
        if not include:
            return list(enumerate(self._calendars))
        by_name = {calendar.name: calendar for calendar in self._calendars}
        missing = [name for name in include if name not in by_name]
        if missing:
            logger.warning("%s: no calendar named %s", self.name, ", ".join(missing))
        # Ordered as listed, so the last one listed wins an overlap.
        return [(i, by_name[name]) for i, name in enumerate(include) if name in by_name]

    async def fetch(self, start: datetime, end: datetime) -> list[events.Event]:
        selected = await self._selected()

        async def one(position: int, calendar: RemoteCalendar) -> list[events.Event]:
            documents = await self._client.events(calendar, start, end)
            return self._parse(documents, self._ref(calendar.name, position), start, end)

        results = await asyncio.gather(*(one(i, c) for i, c in selected))
        return [event for result in results for event in result]

    async def aclose(self) -> None:
        await self._http.aclose()


def build(config: SourceConfig, index: int, floating_tz: tzinfo, skip_free: bool) -> Source:
    kind = CalDAVSource if config.type == "caldav" else ICSSource
    return kind(config, index, floating_tz, skip_free)
