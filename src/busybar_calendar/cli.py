"""Command line: run the service, list calendars, preview events, try the drawing."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys
from datetime import UTC, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

from busylib.client import AsyncBusyBar

from . import config as config_module
from . import render, schedule, sources
from .caldav import CalDAVError
from .config import Config, ConfigError
from .events import CalendarRef, Event
from .runner import Runner

logger = logging.getLogger("busybar_calendar")


def _floating_tz(config: Config) -> tzinfo:
    if config.sync.timezone:
        return ZoneInfo(config.sync.timezone)
    local = datetime.now().astimezone().tzinfo
    assert local is not None
    return local


def _sources(config: Config) -> list[sources.Source]:
    tz = _floating_tz(config)
    return [
        sources.build(source, index, tz, config.sync.skip_free)
        for index, source in enumerate(config.sources)
    ]


def _bar(config: Config) -> AsyncBusyBar:
    token = config.bar.token.resolve()
    if config.bar.address:
        return AsyncBusyBar(addr=config.bar.address, token=token)
    if not token:
        raise ConfigError("give bar.address, or a bar-scope cloud token as bar.token")
    return AsyncBusyBar(token=token)


async def _close(items: list[sources.Source]) -> None:
    for item in items:
        await item.aclose()


async def cmd_run(config: Config, _args: argparse.Namespace) -> int:
    items = _sources(config)
    bar = _bar(config)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    try:
        await Runner(config, bar, items).run(stop)
    finally:
        await _close(items)
        await bar.aclose()
    return 0


async def cmd_calendars(config: Config, _args: argparse.Namespace) -> int:
    items = _sources(config)
    try:
        for item in items:
            if isinstance(item, sources.CalDAVSource):
                found = await item.calendars()
                used, unmatched = sources.select(found, item.config.include, item.config.exclude)
                print(f"{item.name} (caldav): {len(found)} calendars, {len(used)} used")
                width = max((len(calendar.id) for calendar in found), default=0)
                for calendar in found:
                    mark = "*" if calendar in used else " "
                    print(f"  {mark} {calendar.id:<{width}}  {calendar.name}")
                for pattern in unmatched:
                    print(f"  ! no calendar matches {pattern!r}")
            else:
                print(f"{item.name} (ics): one calendar, {item.config.url}")
    finally:
        await _close(items)
    print("\n* = used. Filter with include/exclude by id, name or URL; * and ? are wildcards.")
    return 0


async def cmd_upcoming(config: Config, args: argparse.Namespace) -> int:
    items = _sources(config)
    runner = Runner(config, bar=None, sources=items)  # type: ignore[arg-type]
    now = datetime.now(UTC)
    try:
        await runner.refresh(now)
    finally:
        await _close(items)
    tz = _floating_tz(config)
    horizon = now + timedelta(hours=args.hours)
    shown = [e for e in runner.events if e.end > now and e.start < horizon]
    for event in sorted(shown, key=lambda e: e.start):
        reminder, status = runner.settings_for(event)
        start = event.start.astimezone(tz)
        end = event.end.astimezone(tz)
        notes = []
        if reminder.enabled:
            notes.append(f"reminder {reminder.minutes_before}m")
        if status.enabled:
            notes.append(f"status {status.show}")
        print(
            f"{start:%a %d %b %H:%M}-{end:%H:%M}  [{event.calendar.source}/"
            f"{event.calendar.name}]  {event.title}  ({', '.join(notes) or 'hidden'})"
        )
    screen = schedule.choose(now, runner.events, runner.settings_for)
    print(f"\nNow on the bar: {screen.kind + ': ' + screen.event.title if screen else 'nothing'}")
    return 0


async def cmd_demo(config: Config, args: argparse.Namespace) -> int:
    """Draw a made-up event, to see the layout on the bar."""
    now = datetime.now(UTC)
    start = now + timedelta(minutes=args.minutes)
    if args.status:
        start = now - timedelta(minutes=1)
    event = Event(
        "demo", args.title, start, start + timedelta(minutes=30), CalendarRef("demo", "demo", 0)
    )
    reminder, status = config.settings_for(config.sources[0].name, config.sources[0].name)
    if args.show:
        status = status.model_copy(update={"show": args.show})
    screen = schedule.Screen("status" if args.status else "reminder", event, reminder, status)
    if args.font:
        config.display.title_font = args.font
    drawing = render.drawing(
        screen, config.display, config.bar.application_name, config.bar.priority
    )
    print(drawing.model_dump_json(indent=2, exclude_none=True))
    bar = _bar(config)
    try:
        await bar.display_draw(drawing)
        if args.sound and (sound := render.sound(screen, config.display)):
            await bar.audio_play(stock_path=sound, application_name=config.bar.application_name)
        await asyncio.sleep(args.seconds)
        await bar.display_clear(application_name=config.bar.application_name)
    finally:
        await bar.aclose()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="busybar-calendar", description=__doc__)
    parser.add_argument("-c", "--config", default="config.toml", help="TOML configuration")
    parser.add_argument("-v", "--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run", help="keep the bar in step with the calendars")
    commands.add_parser("calendars", help="list the calendars each CalDAV source has")
    upcoming = commands.add_parser("upcoming", help="list the events the bar will show")
    upcoming.add_argument("--hours", type=int, default=24)
    demo = commands.add_parser("demo", help="draw a sample event on the bar")
    demo.add_argument("--title", default="Weekly sync with the team")
    demo.add_argument("--minutes", type=int, default=5, help="reminder: minutes to the start")
    demo.add_argument("--status", action="store_true", help="draw the in-event status instead")
    demo.add_argument("--show", help="status to draw: name, meeting, on_call, ...")
    demo.add_argument("--font", choices=["tiny", "small", "global"])
    demo.add_argument("--sound", action="store_true")
    demo.add_argument("--seconds", type=int, default=20, help="how long to leave it up")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not args.verbose:
        logging.getLogger("busylib").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
    # Its bounds check ignores anchors, so a bottom-anchored line at y=16 -
    # busylib's own calibrated two-line layout - is reported as off-screen.
    logging.getLogger("busylib.client.display").setLevel(logging.ERROR)

    handlers = {
        "run": cmd_run,
        "calendars": cmd_calendars,
        "upcoming": cmd_upcoming,
        "demo": cmd_demo,
    }
    try:
        config = config_module.load(args.config)
        return asyncio.run(handlers[args.command](config, args))
    except (ConfigError, CalDAVError, OSError, ValueError) as error:
        print(f"busybar-calendar: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
