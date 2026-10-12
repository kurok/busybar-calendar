"""
Calendar events, reduced to what the bar needs, from iCalendar data.

CalDAV and ICS feeds both end up here: CalDAV returns one VCALENDAR per
event resource, an ICS feed returns one for the whole calendar, and either
way recurring events arrive as a master with RRULE/EXDATE and overrides.
Expansion happens here rather than on the server, because servers differ in
how well they implement CalDAV's `expand`.

The filtering follows the Google Calendar integration: events of 24 hours or
more are not shown, and neither are cancelled ones. Free events and
invitations you declined are skipped too, since neither makes you busy.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo

import icalendar
import recurring_ical_events

logger = logging.getLogger(__name__)

ALL_DAY = timedelta(hours=24)
UNTITLED = "Busy"


@dataclass(frozen=True)
class CalendarRef:
    source: str
    name: str
    # Position in the configuration: a calendar added later wins an overlap.
    order: int
    # The CalDAV calendar's id (its URL's last segment); empty for an ICS feed.
    id: str = ""


@dataclass(frozen=True)
class Event:
    uid: str
    title: str
    start: datetime
    end: datetime
    calendar: CalendarRef

    @property
    def key(self) -> str:
        """One occurrence of one event; a recurring event has one per start."""
        return f"{self.calendar.source}/{self.calendar.name}/{self.uid}@{self.start.isoformat()}"


def _aware(value: datetime, floating_tz: tzinfo) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=floating_tz)
    return value.astimezone(UTC)


def _declined(component: icalendar.Event, emails: Iterable[str]) -> bool:
    mine = {email.lower() for email in emails}
    if not mine:
        return False
    attendees = component.get("ATTENDEE", [])
    if not isinstance(attendees, list):
        attendees = [attendees]
    for attendee in attendees:
        address = str(attendee).lower().removeprefix("mailto:")
        if address in mine:
            return str(attendee.params.get("PARTSTAT", "")).upper() == "DECLINED"
    return False


def parse(
    data: str | bytes | Iterable[str | bytes],
    calendar: CalendarRef,
    window_start: datetime,
    window_end: datetime,
    *,
    floating_tz: tzinfo,
    skip_free: bool = True,
    emails: Iterable[str] = (),
) -> list[Event]:
    """Every occurrence that overlaps the window and is worth showing."""
    documents = [data] if isinstance(data, str | bytes) else list(data)
    emails = list(emails)
    events: list[Event] = []
    for document in documents:
        try:
            parsed = icalendar.Calendar.from_ical(document)
            occurrences = recurring_ical_events.of(parsed).between(window_start, window_end)
        except Exception as error:  # one broken resource must not hide the rest
            logger.warning(
                "%s/%s: skipping unparsable calendar data: %s",
                calendar.source,
                calendar.name,
                error,
            )
            continue
        for component in occurrences:
            if component.name != "VEVENT":
                continue
            event = _event(component, calendar, floating_tz, skip_free, emails)
            if event is not None:
                events.append(event)
    events.sort(key=lambda e: (e.start, e.calendar.order))
    return events


def _event(
    component: icalendar.Event,
    calendar: CalendarRef,
    floating_tz: tzinfo,
    skip_free: bool,
    emails: list[str],
) -> Event | None:
    start_value = component.get("DTSTART")
    if start_value is None:
        return None
    start_raw = start_value.dt
    if isinstance(start_raw, date) and not isinstance(start_raw, datetime):
        return None  # an all-day event
    start = _aware(start_raw, floating_tz)

    if component.get("DTEND") is not None:
        end = _aware(component["DTEND"].dt, floating_tz)
    elif component.get("DURATION") is not None:
        end = start + component["DURATION"].dt
    else:
        end = start

    if end - start >= ALL_DAY:
        return None
    if str(component.get("STATUS", "")).upper() == "CANCELLED":
        return None
    if skip_free and str(component.get("TRANSP", "")).upper() == "TRANSPARENT":
        return None
    if _declined(component, emails):
        return None

    title = " ".join(str(component.get("SUMMARY", "")).split()) or UNTITLED
    return Event(
        uid=str(component.get("UID", title)),
        title=title,
        start=start,
        end=end,
        calendar=calendar,
    )
