from datetime import UTC, datetime, timedelta

from busybar_calendar.config import ReminderSettings, StatusSettings
from busybar_calendar.events import CalendarRef, Event
from busybar_calendar.schedule import choose, next_change

T0 = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
WORK = CalendarRef("icloud", "Work", 0)
HOME = CalendarRef("icloud", "Home", 1)


def event(title, start_min, length_min=30, calendar=WORK):
    start = T0 + timedelta(minutes=start_min)
    return Event(title, title, start, start + timedelta(minutes=length_min), calendar)


def settings(reminder=None, status=None):
    reminder = reminder or ReminderSettings()
    status = status or StatusSettings()
    return lambda _event: (reminder, status)


def at(minutes):
    return T0 + timedelta(minutes=minutes)


def test_reminder_then_status_then_nothing():
    events = [event("Sync", 10)]
    s = settings()
    assert choose(at(0), events, s) is None
    assert choose(at(5), events, s).kind == "reminder"
    assert choose(at(9.99), events, s).kind == "reminder"
    assert choose(at(10), events, s).kind == "status"
    assert choose(at(39.99), events, s).kind == "status"
    assert choose(at(40), events, s) is None


def test_disabled_settings():
    events = [event("Sync", 10)]
    assert choose(at(6), events, settings(ReminderSettings(enabled=False))) is None
    assert choose(at(12), events, settings(status=StatusSettings(enabled=False))) is None


def test_next_reminder_replaces_running_status():
    # The newest event wins: the reminder for 09:30 over the 09:00 meeting.
    events = [event("Long", 0, 90), event("Next", 30)]
    screen = choose(at(26), events, settings())
    assert (screen.kind, screen.event.title) == ("reminder", "Next")
    screen = choose(at(31), events, settings())
    assert (screen.kind, screen.event.title) == ("status", "Next")
    screen = choose(at(70), events, settings())
    assert (screen.kind, screen.event.title) == ("status", "Long")


def test_same_start_later_calendar_wins():
    events = [event("Home thing", 0, calendar=HOME), event("Work thing", 0, calendar=WORK)]
    assert choose(at(1), events, settings()).event.title == "Home thing"


def test_screen_keys_change_with_what_is_drawn():
    events = [event("Sync", 10)]
    s = settings()
    assert choose(at(5), events, s).key == choose(at(6), events, s).key
    assert choose(at(5), events, s).key != choose(at(10), events, s).key
    renamed = [Event("Sync", "Renamed", events[0].start, events[0].end, WORK)]
    assert choose(at(5), events, s).key != choose(at(5), renamed, s).key


def test_next_change():
    events = [event("Sync", 10), event("Later", 120)]
    s = settings(ReminderSettings(minutes_before=10))
    assert next_change(at(-30), events, s) == at(0)
    assert next_change(at(0), events, s) == at(10)
    assert next_change(at(10), events, s) == at(40)
    assert next_change(at(40), events, s) == at(110)
    assert next_change(at(200), events, s) is None
