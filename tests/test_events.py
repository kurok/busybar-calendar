from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from busybar_calendar.events import CalendarRef, parse

REF = CalendarRef("src", "cal", 0)
KYIV = ZoneInfo("Europe/Kyiv")
WINDOW = (datetime(2026, 10, 12, tzinfo=UTC), datetime(2026, 10, 20, tzinfo=UTC))


def ics(*events: str) -> str:
    body = "\n".join(f"BEGIN:VEVENT\n{e.strip()}\nEND:VEVENT" for e in events)
    return f"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:test\n{body}\nEND:VCALENDAR\n".replace(
        "\n", "\r\n"
    )


def run(data, **kwargs):
    kwargs.setdefault("floating_tz", KYIV)
    return parse(data, REF, *WINDOW, **kwargs)


def test_timed_event_in_utc():
    [event] = run(ics("UID:a\nSUMMARY:Standup\nDTSTART:20261013T090000Z\nDTEND:20261013T091500Z"))
    assert event.title == "Standup"
    assert event.start == datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
    assert event.end == datetime(2026, 10, 13, 9, 15, tzinfo=UTC)


def test_tzid_and_floating_times():
    data = ics(
        "UID:a\nSUMMARY:Zoned\nDTSTART;TZID=America/New_York:20261013T090000\n"
        "DTEND;TZID=America/New_York:20261013T100000",
        "UID:b\nSUMMARY:Floating\nDTSTART:20261013T090000\nDTEND:20261013T100000",
    )
    zoned, floating = sorted(run(data), key=lambda e: e.title, reverse=True)
    assert zoned.start == datetime(2026, 10, 13, 13, 0, tzinfo=UTC)
    # Kyiv is UTC+3 in October.
    assert floating.start == datetime(2026, 10, 13, 6, 0, tzinfo=UTC)


def test_duration_and_no_end():
    data = ics(
        "UID:a\nSUMMARY:Dur\nDTSTART:20261013T090000Z\nDURATION:PT45M",
        "UID:b\nSUMMARY:Point\nDTSTART:20261013T120000Z",
    )
    by_title = {e.title: e for e in run(data)}
    assert (by_title["Dur"].end - by_title["Dur"].start).total_seconds() == 45 * 60
    assert by_title["Point"].end == by_title["Point"].start


def test_skips_like_google_and_more():
    data = ics(
        "UID:allday\nSUMMARY:Holiday\nDTSTART;VALUE=DATE:20261014\nDTEND;VALUE=DATE:20261015",
        "UID:long\nSUMMARY:Offsite\nDTSTART:20261014T080000Z\nDTEND:20261015T080000Z",
        "UID:cancel\nSUMMARY:Gone\nSTATUS:CANCELLED\nDTSTART:20261014T090000Z\n"
        "DTEND:20261014T100000Z",
        "UID:free\nSUMMARY:Lunch\nTRANSP:TRANSPARENT\nDTSTART:20261014T110000Z\n"
        "DTEND:20261014T120000Z",
        "UID:declined\nSUMMARY:Nope\nDTSTART:20261014T130000Z\nDTEND:20261014T140000Z\n"
        "ATTENDEE;PARTSTAT=DECLINED:mailto:Me@Example.com\n"
        "ATTENDEE;PARTSTAT=ACCEPTED:mailto:other@example.com",
        "UID:keep\nSUMMARY:Kept\nDTSTART:20261014T150000Z\nDTEND:20261014T160000Z\n"
        "ATTENDEE;PARTSTAT=DECLINED:mailto:other@example.com",
    )
    titles = [e.title for e in run(data, emails=["me@example.com"])]
    assert titles == ["Kept"]
    # Free events are shown when asked for.
    titles = [e.title for e in run(data, emails=["me@example.com"], skip_free=False)]
    assert titles == ["Lunch", "Kept"]


def test_recurrence_with_exdate_and_override():
    data = ics(
        "UID:r\nSUMMARY:Daily\nDTSTART:20261012T080000Z\nDTEND:20261012T081500Z\n"
        "RRULE:FREQ=DAILY;COUNT=5\nEXDATE:20261014T080000Z",
        "UID:r\nRECURRENCE-ID:20261015T080000Z\nSUMMARY:Daily (moved)\n"
        "DTSTART:20261015T100000Z\nDTEND:20261015T101500Z",
    )
    events = run(data)
    assert [(e.title, e.start.day, e.start.hour) for e in events] == [
        ("Daily", 12, 8),
        ("Daily", 13, 8),
        ("Daily (moved)", 15, 10),
        ("Daily", 16, 8),
    ]
    assert len({e.key for e in events}) == 4


def test_several_documents_and_a_broken_one():
    good = ics("UID:a\nSUMMARY:One\nDTSTART:20261013T090000Z\nDTEND:20261013T100000Z")
    other = ics("UID:b\nSUMMARY:Two\nDTSTART:20261013T080000Z\nDTEND:20261013T083000Z")
    events = run([good, "not a calendar", other])
    assert [e.title for e in events] == ["Two", "One"]


def test_untitled_and_whitespace():
    data = ics(
        "UID:a\nDTSTART:20261013T090000Z\nDTEND:20261013T100000Z",
        "UID:b\nSUMMARY:  Sprint\\n  review \nDTSTART:20261013T110000Z\nDTEND:20261013T120000Z",
    )
    assert [e.title for e in run(data)] == ["Busy", "Sprint review"]
