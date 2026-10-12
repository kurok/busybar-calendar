"""Command line: run the service, list calendars, preview events, try the drawing."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import json
import logging
import os
import shlex
import signal
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo

from busylib.client import AsyncBusyBar
from busylib.exceptions import BusyBarAPIError

from . import __version__, render, schedule, service, sources, wizard
from . import config as config_module
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


def _stop_on_signals() -> asyncio.Event:
    """An event that SIGINT or SIGTERM sets, so every mode can stop cleanly."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    return stop


async def run_service(config: Config) -> int:
    """Keep the bar in step with the calendars until a signal, or a source that cannot work."""
    items = _sources(config)
    bar = _bar(config)
    stop = _stop_on_signals()
    try:
        await Runner(config, bar, items).run(stop)
    except sources.FatalSourceError as error:
        print(f"busybar-calendar: {error}", file=sys.stderr)
        return 1
    finally:
        await _close(items)
        await bar.aclose()
    return 0


async def cmd_run(config: Config, _args: argparse.Namespace) -> int:
    return await run_service(config)


LAN_TOKEN_LIMIT = 32  # the firmware refuses longer X-API-Token values


async def _check_bar(config: Config, report: Callable[[bool, str], None]) -> None:
    where = config.bar.address or "BUSY Cloud"
    bar = _bar(config)
    try:
        try:
            version = await bar.version()
        except Exception as error:
            report(False, f"{where}: unreachable ({error})")
            return
        try:
            firmware = await bar.status_firmware()
        except BusyBarAPIError as error:
            report(
                False,
                f"{where}: {error.status_code} on an authenticated call. "
                f"{await _access_hint(bar, config, error)}",
            )
            return
        report(
            True, f"{where}: firmware {firmware.version}, API {version.api_semver}, token accepted"
        )
    finally:
        await bar.aclose()


async def _access_hint(bar: AsyncBusyBar, config: Config, error: BusyBarAPIError) -> str:
    """Why an authenticated call was refused, in the words of the fix."""
    if not config.bar.address:
        return "The cloud token is wrong, revoked, or lacks the BUSY Bar access scope."
    try:
        access = await bar.access()  # answered without a token
    except Exception:
        access = None
    if access is not None and access.mode == "disabled":
        return (
            "The bar's HTTP API over Wi-Fi is disabled: enable it at http://10.0.4.20 "
            "(USB) -> Network -> HTTP API, or use a BUSY Cloud token without an address."
        )
    token = config.bar.token.resolve()
    if not token:
        return "The bar wants its HTTP API password: set bar.token / token_env / token_command."
    if len(token) > LAN_TOKEN_LIMIT:
        return (
            f"The token is {len(token)} characters; the bar takes at most "
            f"{LAN_TOKEN_LIMIT}. Is it a cloud token? Then leave bar.address out."
        )
    return "The bar did not accept the password."


async def _check_source(item: sources.Source, report: Callable[[bool, str], None], tz) -> None:
    now = datetime.now(UTC)
    try:
        if isinstance(item, sources.CalDAVSource):
            found = await item.calendars()
            used, unmatched = sources.select(found, item.config.include, item.config.exclude)
            names = ", ".join(c.name for c in used) or "none"
            report(
                bool(used),
                f"{item.name}: signed in; {len(used)} of {len(found)} calendars used: {names}",
            )
            for pattern in unmatched:
                report(False, f"{item.name}: no calendar matches {pattern!r}")
        events = await item.fetch(now - timedelta(hours=24), now + timedelta(days=7))
    except Exception as error:
        report(False, f"{item.name}: {error}")
        return
    ahead = sorted((e for e in events if e.end > now), key=lambda e: e.start)
    if not ahead:
        report(True, f"{item.name}: no events in the next 7 days")
        return
    first = ahead[0]
    report(
        True,
        f"{item.name}: {len(ahead)} events in the next 7 days; next "
        f"{first.start.astimezone(tz):%a %d %b %H:%M} {first.title}",
    )


async def cmd_check(config: Config, _args: argparse.Namespace) -> int:
    """Check the setup end to end: the bar, its token, every calendar."""
    problems = 0

    def report(good: bool, text: str) -> None:
        nonlocal problems
        problems += not good
        print(f"  {'ok ' if good else 'FAIL'} {text}")

    print(f"busybar-calendar {__version__}\nBar")
    await _check_bar(config, report)
    print("Calendars")
    items = _sources(config)
    try:
        for item in items:
            await _check_source(item, report, _floating_tz(config))
    finally:
        await _close(items)
    print("\nAll good." if not problems else f"\n{problems} problem(s) above.")
    return 0 if not problems else 1


async def cmd_install(config: Config, args: argparse.Namespace) -> int:
    """Run the service in the background from now on: at login, restarted if it stops."""
    plan = service.install_plan(args.config_path)
    if args.dry_run:
        print(f"Would write {plan.path}:\n")
        print(plan.content.decode())
        print("Would run:")
        for command in [*plan.cleanup, *plan.commands]:
            print("  " + shlex.join(command))
        return 0
    if not args.force:
        print("Checking the setup first.\n")
        if await cmd_check(config, args):
            print("Fix the problems above, or install anyway with --force.")
            return 1
        print()
    service.install(plan)
    print(f"Installed {plan.path}.")
    print("It runs at login, comes back if it stops, and reads", args.config_path.resolve())
    if plan.log:
        print(f"Log: {plan.log}")
    print("Remove it with: busybar-calendar uninstall")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    plan = service.uninstall_plan()
    if args.dry_run:
        print(f"Would remove {plan.path} and run:")
        for command in [*plan.cleanup, *plan.commands]:
            print("  " + shlex.join(command))
        return 0
    if service.uninstall(plan):
        print(f"Stopped and removed {plan.path}.")
    else:
        print("Not installed.")
    return 0


def _when(moment: datetime, now: datetime, tz: tzinfo) -> str:
    minutes = max(0, int((moment - now).total_seconds() // 60))
    hours, minutes = divmod(minutes, 60)
    delta = f"in {hours}h {minutes:02d}m" if hours else f"in {minutes}m"
    return f"{moment.astimezone(tz):%a %d %b %H:%M} ({delta})"


async def cmd_status(config: Config | None, _args: argparse.Namespace) -> int:
    """Is it running, what did it last do, and what is on the bar now and next."""
    print(f"busybar-calendar {__version__}")
    state = service.status()
    if state.running:
        print(f"Service   running{f', pid {state.pid}' if state.pid else ''}")
    elif state.installed:
        print(f"Service   stopped{f' ({state.detail})' if state.detail else ''}; the log says why")
    else:
        print("Service   not installed: `busybar-calendar install` runs it in the background")
    if state.log and state.log.exists():
        print(f"          log {state.log}")
    for line in service.recent_log(state):
        print(f"            {line}")

    if config is None:
        print("Calendar  no config yet: `busybar-calendar init` writes one")
        return 0
    items = _sources(config)
    runner = Runner(config, bar=None, sources=items)  # type: ignore[arg-type]
    now = datetime.now(UTC)
    try:
        await runner.refresh(now)
    finally:
        await _close(items)
    tz = _floating_tz(config)
    screen = schedule.choose(now, runner.events, runner.settings_for)
    if screen is None:
        print("Calendar  nothing on the bar now")
    else:
        print(
            f"Calendar  now {screen.kind}: {screen.event.title}, "
            f"until {_when(screen.until, now, tz)}"
        )
    following = schedule.upcoming(now, runner.events, runner.settings_for)
    if following is None:
        print(f"          nothing more in the next {config.sync.lookahead_hours} hours")
    else:
        moment, nxt = following
        print(f"          next {nxt.kind}: {nxt.event.title}, at {_when(moment, now, tz)}")
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
        if event.response != "accepted":
            notes.append(event.response)
        print(
            f"{start:%a %d %b %H:%M}-{end:%H:%M}  [{event.calendar.source}/"
            f"{event.calendar.name}]  {event.title}  ({', '.join(notes) or 'hidden'})"
        )
    screen = schedule.choose(now, runner.events, runner.settings_for)
    print(f"\nNow on the bar: {screen.kind + ': ' + screen.event.title if screen else 'nothing'}")
    return 0


def _day(text: str, tz: tzinfo) -> date:
    today = datetime.now(tz).date()
    named = {"today": today, "tomorrow": today + timedelta(days=1)}
    return named.get(text) or date.fromisoformat(text)


async def _wait(stop: asyncio.Event, moment: datetime) -> bool:
    """Sleep until `moment`; True if `stop` was set first."""
    delay = max(0.0, (moment - datetime.now(UTC)).total_seconds())
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), delay)
    return stop.is_set()


async def _show(runner: Runner, screen: schedule.Screen | None, *, chime: bool) -> None:
    """Draw (or, with no screen, clear) and carry on if the bar refuses: a 409 means
    something above our priority holds the screen - a menu, a button press."""
    try:
        if screen is None:
            await runner.clear()
        else:
            await runner.show(screen, chime=chime)
    except Exception as error:
        logger.warning("bar refused the update (%s); carrying on", error)


async def play(
    runner: Runner,
    events: list[Event],
    seconds: int,
    stop: asyncio.Event,
    *,
    chime: bool,
    tz: tzinfo | None = None,
) -> None:
    """
    Show events one after another, each in a slot of `seconds`.

    A third of the slot is the reminder, counting down to a start moved to
    its end; the rest is the status. Titles, settings and drawings are the
    events' own; only the times are not.
    """
    reminder_part = timedelta(seconds=max(5, seconds // 3))
    status_part = timedelta(seconds=seconds) - reminder_part
    for number, event in enumerate(events, 1):
        reminder, status = runner.settings_for(event)
        start = datetime.now(UTC).replace(microsecond=0) + reminder_part
        moved = dataclasses.replace(event, start=start, end=start + status_part)
        if tz is not None:
            print(
                f"{number:>2}/{len(events)}  {event.start.astimezone(tz):%H:%M}-"
                f"{event.end.astimezone(tz):%H:%M}  {event.title}  [{event.response}]",
                flush=True,
            )
        if reminder.enabled:
            await _show(runner, schedule.Screen("reminder", moved, reminder, status), chime=chime)
        if await _wait(stop, moved.start):
            return
        shown = schedule.shows_status(moved, status)
        await _show(
            runner,
            schedule.Screen("status", moved, reminder, status) if shown else None,
            chime=chime,
        )
        if await _wait(stop, moved.end):
            return


async def cmd_replay(config: Config, args: argparse.Namespace) -> int:
    """Play a day's real events on the bar, one after another, in short slots."""
    tz = _floating_tz(config)
    day = _day(args.day, tz)
    day_start = datetime.combine(day, time.min, tzinfo=tz)
    day_end = day_start + timedelta(days=1)
    items = _sources(config)
    try:
        found = await asyncio.gather(*(item.fetch(day_start, day_end) for item in items))
    finally:
        await _close(items)
    events = sorted(
        (e for events in found for e in events if day_start <= e.start < day_end),
        key=lambda e: (e.start, e.calendar.order),
    )
    if not events:
        print(f"No events on {day:%a %d %b}.")
        return 0
    print(f"Replaying {len(events)} events of {day:%a %d %b}, {args.seconds}s each.")
    bar = _bar(config)
    runner = Runner(config, bar, [])
    stop = _stop_on_signals()
    try:
        await play(runner, events, args.seconds, stop, chime=not args.quiet, tz=tz)
    finally:
        with contextlib.suppress(Exception):
            await runner.clear()
        await bar.aclose()
    return 0


DEMO_EVENTS = (
    ("Design review", "accepted"),
    ("1:1 with Alex", "accepted"),
    ("Quarterly planning with the design team", "tentative"),
)


def _demo_events() -> list[Event]:
    ref = CalendarRef("demo", "demo", 0)
    now = datetime.now(UTC)
    return [
        Event(f"demo-{i}", title, now, now + timedelta(minutes=30), ref, response)
        for i, (title, response) in enumerate(DEMO_EVENTS)
    ]


async def run_demo(config: Config, seconds: int = 20) -> int:
    """Loop a made-up schedule on the bar until a signal: reminders, then BUSY."""
    bar = _bar(config)
    runner = Runner(config, bar, [])
    stop = _stop_on_signals()
    try:
        while not stop.is_set():
            await play(runner, _demo_events(), seconds, stop, chime=False)
    finally:
        with contextlib.suppress(Exception):
            await runner.clear()
        await bar.aclose()
    return 0


async def draw_test_frame(config: Config) -> int:
    """Draw one made-up event in progress - the red calendar and BUSY - and exit."""
    event = dataclasses.replace(_demo_events()[0], start=datetime.now(UTC) - timedelta(minutes=2))
    reminder, status = config.settings_for("demo", "demo")
    screen = schedule.Screen("status", event, reminder, status)
    bar = _bar(config)
    try:
        drawing = render.drawing(
            screen, config.display, config.bar.application_name, config.bar.priority
        )
        await render.send(bar, drawing)
    finally:
        await bar.aclose()
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
    print(json.dumps(drawing.payload(), indent=2, ensure_ascii=False))
    bar = _bar(config)
    try:
        with contextlib.suppress(Exception):  # 400 when nothing of ours is up
            await bar.display_clear(application_name=config.bar.application_name)
        await render.send(bar, drawing)
        if args.sound and (sound := render.sound(screen, config.display)):
            await bar.audio_play(stock_path=sound, application_name=config.bar.application_name)
        await asyncio.sleep(args.seconds)
        with contextlib.suppress(Exception):
            await bar.display_clear(application_name=config.bar.application_name)
    finally:
        await bar.aclose()
    return 0


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not verbose:
        logging.getLogger("busylib").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpx2").setLevel(logging.WARNING)
    # Its bounds check ignores anchors, so a bottom-anchored line at y=16 -
    # busylib's own calibrated two-line layout - is reported as off-screen.
    logging.getLogger("busylib.client.display").setLevel(logging.ERROR)
    # "Device API minor version is behind Busy Lib": busylib's own nag, on every
    # bar that runs released firmware; `check` prints both versions instead.
    logging.getLogger("busylib.client.firmware").setLevel(logging.ERROR)
    # It logs every refused call; this service reports those itself, with what to do.
    logging.getLogger("busylib.client.base").setLevel(logging.CRITICAL)


def _restart_after(code: int) -> int:
    """After the config changed: a running background service reads it only when it starts."""
    if code == 0 and service.restart():
        print("Restarted the background service, so it reads the new config.")
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="busybar-calendar", description=__doc__)
    parser.add_argument(
        "-c",
        "--config",
        help="TOML configuration (default: $BUSYBAR_CALENDAR_CONFIG, ./config.toml, "
        "then ~/.config/busybar-calendar/config.toml)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run", help="keep the bar in step with the calendars")
    init = commands.add_parser("init", help="answer a few questions to write the config")
    init.add_argument("--force", action="store_true", help="replace an existing config")
    commands.add_parser("add", help="add another calendar to the config, a few questions")
    commands.add_parser("check", help="check the bar, its token and every calendar")
    commands.add_parser("status", help="is it running, and what is on the bar now and next")
    install = commands.add_parser(
        "install", help="run in the background from now on (launchd / systemd)"
    )
    install.add_argument("--dry-run", action="store_true", help="show what it would do")
    install.add_argument("--force", action="store_true", help="install even if check fails")
    uninstall = commands.add_parser("uninstall", help="stop and remove the background service")
    uninstall.add_argument("--dry-run", action="store_true", help="show what it would do")
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
    replay = commands.add_parser(
        "replay", help="play a day's events on the bar one after another, in short slots"
    )
    replay.add_argument("--day", default="tomorrow", help="today, tomorrow or YYYY-MM-DD")
    replay.add_argument("--seconds", type=int, default=60, help="slot per event")
    replay.add_argument("--quiet", action="store_true", help="no sounds")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)

    handlers = {
        "run": cmd_run,
        "check": cmd_check,
        "install": cmd_install,
        "calendars": cmd_calendars,
        "upcoming": cmd_upcoming,
        "demo": cmd_demo,
        "replay": cmd_replay,
    }
    try:
        if args.command == "uninstall":  # needs no config: there may be none left
            return cmd_uninstall(args)
        if args.command == "status":  # the service part needs no config
            try:
                config = config_module.load(config_module.find(args.config))
            except ConfigError:
                config = None
            return asyncio.run(cmd_status(config, args))
        if args.command == "init":  # writes the config
            path = Path(
                args.config
                or os.environ.get(config_module.CONFIG_ENV)
                or config_module.search_paths()[-1]
            )
            return _restart_after(wizard.run(path, overwrite=args.force))
        if args.command == "add":  # appends to the config
            return _restart_after(wizard.add(config_module.find(args.config)))
        args.config_path = config_module.find(args.config)
        config = config_module.load(args.config_path)
        return asyncio.run(handlers[args.command](config, args))
    except (ConfigError, CalDAVError, sources.FatalSourceError, OSError, ValueError) as error:
        print(f"busybar-calendar: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
