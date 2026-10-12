"""
Configuration, read from a TOML file.

The reminder and status settings are the ones the Google Calendar
integration offers per calendar, so a calendar here behaves the way a Google
calendar does on the same bar. They layer: `[defaults]` applies everywhere, a
source can override it, and a single calendar inside a source can override
that again - which is also the account-level default that BUSY Cloud does not
have yet (busy-app/busybar-firmware#1083).
"""

from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# The 72x16 statuses the firmware ships, under shared/animations/<name>_72x16.anim.
STOCK_STATUSES = (
    "back_soon",
    "booked",
    "chill_time",
    "coding",
    "dnd",
    "flow",
    "keep_out",
    "low_social_battery",
    "lunch",
    "meeting",
    "on_air",
    "on_call",
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReminderSettings(_Strict):
    """A countdown shown before the event starts."""

    enabled: bool = True
    minutes_before: int = Field(default=5, ge=1, le=24 * 60)
    sound: bool = True
    show_name: bool = True


class StatusSettings(_Strict):
    """What the bar shows while the event is on."""

    enabled: bool = True
    # "name" shows the event's title; anything else is one of STOCK_STATUSES.
    show: str = "name"
    sound: bool = True

    @field_validator("show")
    @classmethod
    def _known_status(cls, value: str) -> str:
        if value != "name" and value not in STOCK_STATUSES:
            raise ValueError(f"show must be 'name' or one of {', '.join(STOCK_STATUSES)}")
        return value


class Overrides(_Strict):
    """Partial reminder/status settings; unset fields fall through to the level above."""

    reminder: dict[str, Any] = Field(default_factory=dict)
    status: dict[str, Any] = Field(default_factory=dict)


class Secret(_Strict):
    """
    A credential given inline, by environment variable, or by a command.

    The command form is argv, run without a shell - for example the macOS
    keychain: ["security", "find-generic-password", "-s", "busybar", "-w"].
    """

    value: str | None = None
    env: str | None = None
    command: list[str] | None = None

    def resolve(self) -> str | None:
        if self.value is not None:
            return self.value
        if self.env is not None:
            found = os.environ.get(self.env)
            if found is None:
                raise ConfigError(f"environment variable {self.env} is not set")
            return found
        if self.command:
            result = subprocess.run(self.command, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                raise ConfigError(f"{self.command[0]} exited with {result.returncode}")
            return result.stdout.strip()
        return None


def _secret(data: dict[str, Any], key: str) -> dict[str, Any]:
    """Fold `key`, `key_env` and `key_command` into one Secret."""
    secret = {
        "value": data.pop(key, None),
        "env": data.pop(f"{key}_env", None),
        "command": data.pop(f"{key}_command", None),
    }
    given = [name for name, value in secret.items() if value is not None]
    if len(given) > 1:
        raise ValueError(f"give only one of {key}, {key}_env, {key}_command")
    data[key] = secret
    return data


class BarConfig(_Strict):
    # LAN address of the bar. Leave it out to reach the bar through BUSY Cloud
    # with a bar-scope token instead.
    address: str | None = None
    # The HTTP API password on the LAN (sent as X-API-Token), or the cloud
    # token when there is no address.
    token: Secret = Field(default_factory=Secret)
    # Above an active BUSY session (90), like the Google integration's events.
    priority: int = Field(default=91, ge=1, le=100)
    application_name: str = Field(default="busybar_calendar", max_length=32)

    @model_validator(mode="before")
    @classmethod
    def _fold_token(cls, data: Any) -> Any:
        return _secret(dict(data), "token") if isinstance(data, dict) else data


class DisplayConfig(_Strict):
    # small fits two lines in 16px; global (Lana Pixel) draws Cyrillic, CJK and
    # accents but takes the whole height for one line.
    title_font: Literal["tiny", "small", "global"] = "small"
    # Fold titles to ASCII for the bitmap fonts. Ignored for the global font.
    transliterate: bool = True
    reminder_sound: str = "shared/sounds/calendar_reminder_ends.snd"
    event_sound: str = "shared/sounds/calendar_event_starts.snd"


class SyncConfig(_Strict):
    poll_minutes: int = Field(default=5, ge=1)
    lookahead_hours: int = Field(default=24, ge=1, le=24 * 14)
    # Events marked free (TRANSP:TRANSPARENT) do not make you busy.
    skip_free: bool = True
    # Timezone for floating times. Defaults to this machine's.
    timezone: str | None = None


class SourceConfig(Overrides):
    name: str
    type: Literal["caldav", "ics"]
    url: str
    username: str | None = None
    password: Secret = Field(default_factory=Secret)
    auth: Literal["basic", "digest"] = "basic"
    # Attendee address(es) that are you, so an invitation you declined is
    # skipped. Defaults to the username when that is an email address.
    emails: list[str] = Field(default_factory=list)
    # CalDAV only: calendar display names to use. Empty means all of them.
    include: list[str] = Field(default_factory=list)
    calendars: dict[str, Overrides] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _fold_password(cls, data: Any) -> Any:
        return _secret(dict(data), "password") if isinstance(data, dict) else data

    @model_validator(mode="after")
    def _defaults(self) -> SourceConfig:
        if self.url.startswith("webcal://"):
            self.url = "https://" + self.url.removeprefix("webcal://")
        if not self.emails and self.username and "@" in self.username:
            self.emails = [self.username]
        if self.type == "ics" and (self.include or self.calendars):
            # An ICS feed is one calendar, named after its source.
            raise ValueError(f"source {self.name!r}: include/calendars apply to caldav only")
        return self


class Config(_Strict):
    bar: BarConfig = Field(default_factory=BarConfig)
    sync: SyncConfig = Field(default_factory=SyncConfig)
    display: DisplayConfig = Field(default_factory=DisplayConfig)
    defaults: Overrides = Field(default_factory=Overrides)
    sources: list[SourceConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_names(self) -> Config:
        names = [source.name for source in self.sources]
        if len(names) != len(set(names)):
            raise ValueError("source names must be unique")
        return self

    def settings_for(self, source: str, calendar: str) -> tuple[ReminderSettings, StatusSettings]:
        """The effective settings of one calendar: defaults, then source, then calendar."""
        src = next(s for s in self.sources if s.name == source)
        cal = src.calendars.get(calendar, Overrides())
        layers = (self.defaults, src, cal)
        reminder: dict[str, Any] = {}
        status: dict[str, Any] = {}
        for layer in layers:
            reminder |= layer.reminder
            status |= layer.status
        return ReminderSettings(**reminder), StatusSettings(**status)


class ConfigError(Exception):
    pass


def load(path: str | Path) -> Config:
    with open(path, "rb") as handle:
        data = tomllib.load(handle)
    config = Config.model_validate(data)
    # Validate every calendar's settings up front rather than at the first event.
    for source in config.sources:
        for calendar in [source.name, *source.calendars]:
            config.settings_for(source.name, calendar)
    return config
