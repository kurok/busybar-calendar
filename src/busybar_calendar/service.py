"""
Run the service in the background: a launchd agent on macOS, a systemd user
unit on Linux.

The service is started as `<this python> -m busybar_calendar run`, so it runs
from the same environment `install` was run from - a `uv tool` or a virtualenv
- and with $BUSYBAR_CALENDAR_CONFIG set to the config `install` found, so it
does not depend on a working directory. Restarts are throttled: a calendar
that refuses the password stops the service, and it must not then hammer the
server every few seconds.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import CONFIG_ENV

LABEL = "app.busybar.calendar"
UNIT = "busybar-calendar.service"
RESTART_AFTER = 300  # seconds between restarts after the service stops


@dataclass(frozen=True)
class Plan:
    """What install writes and runs, so it can be shown before it is done."""

    path: Path
    content: bytes
    commands: list[list[str]]  # must succeed
    cleanup: tuple[tuple[str, ...], ...] = ()  # run first, may fail: nothing to stop is fine
    log: Path | None = None


def program() -> list[str]:
    return [sys.executable, "-m", "busybar_calendar", "run"]


def launchd_plist(command: list[str], config: Path, log: Path) -> bytes:
    return plistlib.dumps(
        {
            "Label": LABEL,
            "ProgramArguments": command,
            "EnvironmentVariables": {CONFIG_ENV: str(config)},
            "RunAtLoad": True,
            "KeepAlive": True,
            "ThrottleInterval": RESTART_AFTER,
            "StandardOutPath": str(log),
            "StandardErrorPath": str(log),
        }
    )


def _systemd_quote(value: str) -> str:
    """systemd's own quoting: double quotes, with backslash escapes inside."""
    if value and not any(c.isspace() or c in '"\\' for c in value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def systemd_unit(command: list[str], config: Path) -> bytes:
    return (
        "[Unit]\n"
        "Description=BUSY Bar calendar reminders\n"
        "After=network-online.target\n\n"
        "[Service]\n"
        f"Environment={_systemd_quote(f'{CONFIG_ENV}={config}')}\n"
        f"ExecStart={' '.join(_systemd_quote(arg) for arg in command)}\n"
        "Restart=on-failure\n"
        f"RestartSec={RESTART_AFTER}\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    ).encode()


def _home() -> Path:
    return Path.home()


def install_plan(config: Path, platform: str = sys.platform) -> Plan:
    config = config.resolve()
    if platform == "darwin":
        path = _home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        log = _home() / "Library" / "Logs" / "busybar-calendar.log"
        domain = f"gui/{os.getuid()}"
        return Plan(
            path,
            launchd_plist(program(), config, log),
            [["launchctl", "bootstrap", domain, str(path)]],
            cleanup=(("launchctl", "bootout", f"{domain}/{LABEL}"),),  # an older one
            log=log,
        )
    if platform.startswith("linux"):
        path = _home() / ".config" / "systemd" / "user" / UNIT
        return Plan(
            path,
            systemd_unit(program(), config),
            [
                ["systemctl", "--user", "daemon-reload"],
                ["systemctl", "--user", "enable", "--now", UNIT],
            ],
        )
    raise OSError(f"install supports macOS and Linux, not {platform}; see docs/setup.md")


def uninstall_plan(platform: str = sys.platform) -> Plan:
    if platform == "darwin":
        path = _home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        return Plan(
            path, b"", [], cleanup=(("launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"),)
        )
    if platform.startswith("linux"):
        path = _home() / ".config" / "systemd" / "user" / UNIT
        return Plan(
            path,
            b"",
            [["systemctl", "--user", "daemon-reload"]],
            cleanup=(("systemctl", "--user", "disable", "--now", UNIT),),
        )
    raise OSError(f"uninstall supports macOS and Linux, not {platform}")


def _cleanup(plan: Plan) -> None:
    for command in plan.cleanup:
        subprocess.run(list(command), capture_output=True, check=False)


def install(plan: Plan) -> None:
    plan.path.parent.mkdir(parents=True, exist_ok=True)
    if plan.log is not None:
        plan.log.parent.mkdir(parents=True, exist_ok=True)
    _cleanup(plan)
    plan.path.write_bytes(plan.content)
    for command in plan.commands:
        subprocess.run(command, check=True)


def uninstall(plan: Plan) -> bool:
    """Stop and remove the service; False if there was none."""
    if not plan.path.exists():
        return False
    _cleanup(plan)
    plan.path.unlink()
    for command in plan.commands:
        subprocess.run(command, check=True)
    return True
