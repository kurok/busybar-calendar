"""Command line: the commands, their options, and which code each one runs."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shlex
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from pydantic import ValidationError

from . import __version__, connect, diagnose, playback, schedule, service, sources, wizard
from . import config as config_module
from .caldav import CalDAVError
from .config import Config, ConfigError
from .runner import Runner

logger = logging.getLogger("busybar_calendar")


async def run_service(config: Config) -> int:
    """Keep the bar in step with the calendars until a signal, or a source that cannot work."""
    items = connect.make_sources(config)
    bar = connect.make_bar(config)
    stop = connect.stop_on_signals()
    # `status` reads this line to tell which version the service runs.
    logger.info(
        "busybar-calendar %s started: %d calendar source(s), bar %s",
        __version__,
        len(items),
        config.bar.address or "via BUSY Cloud",
    )
    try:
        await Runner(config, bar, items).run(stop)
    except sources.FatalSourceError as error:
        print(f"busybar-calendar: {error}", file=sys.stderr)
        return 1
    finally:
        await connect.close_all(items)
        await bar.aclose()
    return 0


async def cmd_run(config: Config, _args: argparse.Namespace) -> int:
    return await run_service(config)


async def cmd_check(config: Config, args: argparse.Namespace) -> int:
    return await diagnose.check(config, as_json=args.json)


async def cmd_status(config: Config | None, args: argparse.Namespace) -> int:
    return await diagnose.status(config, as_json=args.json)


async def cmd_replay(config: Config, args: argparse.Namespace) -> int:
    return await playback.replay(config, args.day, args.seconds, args.quiet)


async def cmd_demo(config: Config, args: argparse.Namespace) -> int:
    return await playback.demo(config, args)


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
        if await diagnose.check(config):
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


def cmd_restart(_args: argparse.Namespace) -> int:
    """Restart the background service, after a password or the config changed."""
    if service.restart():
        print("Restarted. `busybar-calendar status` shows how it is doing.")
        return 0
    print("Not installed: `busybar-calendar install` runs it in the background.")
    return 1


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


async def cmd_calendars(config: Config, _args: argparse.Namespace) -> int:
    items = connect.make_sources(config)
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
        await connect.close_all(items)
    print("\n* = used. Filter with include/exclude by id, name or URL; * and ? are wildcards.")
    return 0


async def cmd_upcoming(config: Config, args: argparse.Namespace) -> int:
    now = datetime.now(UTC)
    runner = await connect.read_calendars(config, now)
    tz = connect.floating_tz(config)
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


FIRST_STEPS = """\
busybar-calendar shows your CalDAV and ICS calendars on a BUSY Bar: a
reminder before each event, then a red BUSY while it runs.

No config yet. To set it up:

  busybar-calendar init       a few questions: how to reach the bar, which calendar
  busybar-calendar check      proves it works, or says what to fix
  busybar-calendar install    runs it in the background from now on

busybar-calendar --help lists every command."""


def _where_you_stand(args: argparse.Namespace) -> int:
    """`busybar-calendar` alone: first steps before a config exists, the status after."""
    try:
        config = config_module.load(config_module.find(args.config))
    except ConfigError:
        print(FIRST_STEPS)
        return 0
    code = asyncio.run(diagnose.status(config))
    print("\nbusybar-calendar --help lists every command.")
    return code


# The failures a user can meet and fix: reported in a line or two, never a traceback.
EXPECTED = (
    ValidationError,
    ConfigError,
    CalDAVError,
    sources.FatalSourceError,
    httpx.HTTPError,
    subprocess.CalledProcessError,
    OSError,
    ValueError,
)


def describe(error: BaseException) -> list[str]:
    """An expected failure in the user's terms: what went wrong, where."""
    if isinstance(error, ValidationError):  # the config: one line per problem
        return [
            f"{'.'.join(str(part) for part in problem['loc']) or 'config'}: "
            f"{problem['msg'].removeprefix('Value error, ')}"
            for problem in error.errors()
        ]
    if isinstance(error, httpx.RequestError):
        return [f"cannot reach {error.request.url}: {error}"]
    if isinstance(error, subprocess.CalledProcessError):  # launchctl, systemctl
        return [f"{shlex.join(error.cmd)} failed (exit {error.returncode})"]
    return [str(error)]


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
    # No command: where you stand, and what to do next (see _where_you_stand).
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("run", help="keep the bar in step with the calendars")
    init = commands.add_parser("init", help="answer a few questions to write the config")
    init.add_argument("--force", action="store_true", help="replace an existing config")
    commands.add_parser("add", help="add another calendar to the config, a few questions")
    check = commands.add_parser("check", help="check the bar, its token and every calendar")
    check.add_argument("--json", action="store_true", help="the findings as JSON")
    status = commands.add_parser(
        "status", help="is it running, and what is on the bar now and next"
    )
    status.add_argument("--json", action="store_true", help="the same, as JSON")
    install = commands.add_parser(
        "install", help="run in the background from now on (launchd / systemd)"
    )
    install.add_argument("--dry-run", action="store_true", help="show what it would do")
    install.add_argument("--force", action="store_true", help="install even if check fails")
    commands.add_parser("restart", help="restart the background service, e.g. after a new password")
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
        if args.command == "restart":
            return cmd_restart(args)
        if args.command is None:
            return _where_you_stand(args)
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
    except EXPECTED as error:
        for line in describe(error):
            print(f"busybar-calendar: {line}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
