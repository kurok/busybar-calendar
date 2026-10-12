from datetime import UTC, datetime, timedelta

from busybar_calendar.config import DisplayConfig, ReminderSettings, StatusSettings
from busybar_calendar.events import CalendarRef, Event
from busybar_calendar.render import drawing, sound, title_text
from busybar_calendar.schedule import Screen

START = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
EVENT = Event(
    "u", "Планування спринту ☕", START, START + timedelta(minutes=30), CalendarRef("s", "c", 0)
)


def screen(kind="reminder", reminder=None, status=None):
    return Screen(kind, EVENT, reminder or ReminderSettings(), status or StatusSettings())


def by_id(d):
    return {e.id: e for e in d.elements}


def test_title_text():
    assert title_text("Café ☕️ sync 🚀", DisplayConfig()) == "Cafe sync"
    assert title_text("Планування", DisplayConfig()) == "Planuvannya"
    assert title_text("Планування", DisplayConfig(transliterate=False)) == "Busy"
    assert title_text("Планування\tспринту", DisplayConfig(title_font="global")) == (
        "Планування спринту"
    )


def test_reminder_two_lines():
    d = drawing(screen(), DisplayConfig(), "busybar_calendar", 91)
    assert (d.application_name, d.priority) == ("busybar_calendar", 91)
    elements = by_id(d)
    assert elements["cal_icon"].stock_path == "shared/animations/calendar_reminder_16x16.anim"
    title = elements["cal_title"]
    assert title.text == "Planuvannya sprintu"
    assert (title.font, title.align, title.x, title.y) == ("small", "top_left", 18, 0)
    assert title.scroll_rate  # 19 characters do not fit beside the icon
    countdown = elements["cal_time"]
    assert countdown.timestamp == str(int(START.timestamp()))
    assert (countdown.direction, countdown.align, countdown.y) == ("time_left", "bottom_left", 19)
    # The bar takes the reminder down by itself, a grace minute after the start.
    assert {e.display_until for e in d.elements} == {str(int(START.timestamp()) + 60)}


def test_short_title_does_not_scroll_and_hidden_name():
    short = Screen(
        "reminder",
        Event("u", "1:1", START, START, CalendarRef("s", "c", 0)),
        ReminderSettings(),
        StatusSettings(),
    )
    assert by_id(drawing(short, DisplayConfig(), "a", 91))["cal_title"].scroll_rate is None
    hidden = drawing(screen(reminder=ReminderSettings(show_name=False)), DisplayConfig(), "a", 91)
    assert by_id(hidden)["cal_title"].text == "Next event"


def test_global_font_shares_one_line():
    elements = by_id(drawing(screen(), DisplayConfig(title_font="global"), "a", 91))
    assert elements["cal_title"].text == "Планування спринту"
    assert (elements["cal_title"].align, elements["cal_title"].y) == ("mid_left", 8)
    assert (elements["cal_time"].align, elements["cal_time"].x, elements["cal_time"].y) == (
        "mid_right",
        71,
        9,
    )


def test_status_name_counts_to_the_end():
    d = drawing(screen("status"), DisplayConfig(), "a", 91)
    elements = by_id(d)
    assert elements["cal_icon"].stock_path == "shared/animations/calendar_event_16x16.anim"
    end = int(EVENT.end.timestamp())
    assert elements["cal_time"].timestamp == str(end)
    assert {e.display_until for e in d.elements} == {str(end + 60)}


def test_status_stock_animation():
    d = drawing(screen("status", status=StatusSettings(show="meeting")), DisplayConfig(), "a", 91)
    [element] = d.elements
    assert element.stock_path == "shared/animations/meeting_72x16.anim"
    assert element.loop


def test_sounds_follow_settings():
    display = DisplayConfig()
    assert sound(screen(), display) == "shared/sounds/calendar_reminder_ends.snd"
    assert sound(screen("status"), display) == "shared/sounds/calendar_event_starts.snd"
    assert sound(screen(reminder=ReminderSettings(sound=False)), display) is None
    assert sound(screen("status", status=StatusSettings(sound=False)), display) is None


def test_payload_matches_the_wire_format():
    payload = drawing(screen(), DisplayConfig(), "a", 91).model_dump(mode="json", exclude_none=True)
    for element in payload["elements"]:
        assert "timeout" not in element  # mutually exclusive with display_until
        assert element["display_until"].isdigit()
