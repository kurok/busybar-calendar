import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from busybar_calendar import icons
from busybar_calendar.config import DisplayConfig, ReminderSettings, StatusSettings
from busybar_calendar.events import CalendarRef, Event
from busybar_calendar.render import drawing, sound, title_text
from busybar_calendar.schedule import Screen

START = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
EVENT = Event(
    "u", "Планування спринту ☕", START, START + timedelta(minutes=30), CalendarRef("s", "c", 0)
)


def screen(kind="reminder", reminder=None, status=None, response="accepted"):
    event = dataclasses.replace(EVENT, response=response)
    return Screen(kind, event, reminder or ReminderSettings(), status or StatusSettings())


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
    d = drawing(screen(), DisplayConfig(), "busybar-calendar", 91)
    assert (d.application_name, d.priority) == ("busybar-calendar", 91)
    elements = by_id(d)
    assert elements["cal_xpm"].data == icons.RED_CALENDAR
    assert "cal_busy" not in elements  # BUSY is for the event itself, not before it
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
    end = int(EVENT.end.timestamp())
    assert elements["cal_time"].timestamp == str(end)
    assert {e.display_until for e in d.elements} == {str(end + 60)}


def test_status_has_the_red_calendar_and_busy():
    elements = by_id(drawing(screen("status"), DisplayConfig(), "a", 91))
    assert list(elements) == ["cal_xpm", "cal_title", "cal_time", "cal_busy"]
    icon = elements["cal_xpm"]
    assert (icon.type, icon.data) == ("xpmbitmap", icons.RED_CALENDAR)
    busy = elements["cal_busy"]
    assert (busy.text, busy.color, busy.font) == ("BUSY", "#FF0000FF", "small")
    # Right-aligned on the countdown's line.
    assert (busy.align, busy.x, busy.y) == ("top_right", 72, 8)


def test_icons_and_label_follow_the_config():
    display = DisplayConfig(event_icon="animation", busy_label="", reminder_icon="animation")
    status = by_id(drawing(screen("status"), display, "a", 91))
    assert list(status) == ["cal_icon", "cal_title", "cal_time"]
    assert status["cal_icon"].stock_path == "shared/animations/calendar_event_16x16.anim"
    reminder = by_id(drawing(screen(), display, "a", 91))
    assert reminder["cal_icon"].stock_path == "shared/animations/calendar_reminder_16x16.anim"
    custom = by_id(
        drawing(screen("status"), DisplayConfig(busy_label="IN MTG", busy_color="#FF8800"), "a", 91)
    )
    assert (custom["cal_busy"].text, custom["cal_busy"].color) == ("IN MTG", "#FF8800FF")


def test_no_busy_label_with_the_global_font():
    elements = by_id(drawing(screen("status"), DisplayConfig(title_font="global"), "a", 91))
    assert "cal_busy" not in elements


def test_tentative_event_gets_the_yellow_calendar_and_busy():
    for kind in ("reminder", "status"):
        elements = by_id(drawing(screen(kind, response="tentative"), DisplayConfig(), "a", 91))
        assert "cal_xpm" not in elements
        icon = elements["cal_xpm_maybe"]
        assert (icon.type, icon.data) == ("xpmbitmap", icons.YELLOW_CALENDAR)
        assert icon.data != icons.RED_CALENDAR
        # The same place and size as the red one: only the colours differ.
        red = by_id(drawing(screen(kind), DisplayConfig(), "a", 91))["cal_xpm"]
        assert (icon.x, icon.y, icon.align) == (red.x, red.y, red.align)
        assert list(elements) == (
            ["cal_xpm_maybe", "cal_title", "cal_time", "cal_busy"]
            if kind == "status"
            else ["cal_xpm_maybe", "cal_title", "cal_time"]
        )
    busy = by_id(drawing(screen("status", response="tentative"), DisplayConfig(), "a", 91))
    assert (busy["cal_busy"].text, busy["cal_busy"].color) == ("BUSY", "#FFC800FF")


def test_yellow_is_for_tentative_only():
    # Answered "yes", or not at all: the red calendar and the configured BUSY colour.
    for response in ("accepted", "needs-action"):
        elements = by_id(drawing(screen("status", response=response), DisplayConfig(), "a", 91))
        assert elements["cal_xpm"].data == icons.RED_CALENDAR
        assert elements["cal_busy"].color == "#FF0000FF"
        assert "cal_xpm_maybe" not in elements


def test_yellow_can_be_turned_off():
    display = DisplayConfig(tentative_yellow=False)
    elements = by_id(drawing(screen("status", response="tentative"), display, "a", 91))
    assert elements["cal_xpm"].data == icons.RED_CALENDAR
    assert elements["cal_busy"].color == "#FF0000FF"
    assert "cal_xpm_maybe" not in elements


def test_yellow_busy_keeps_its_place_and_ignores_the_busy_colour():
    display = DisplayConfig(busy_color="#00FF00", busy_label="IN MTG")
    busy = by_id(drawing(screen("status", response="tentative"), display, "a", 91))["cal_busy"]
    assert (busy.text, busy.color, busy.align, busy.x, busy.y) == (
        "IN MTG",
        "#FFC800FF",
        "top_right",
        72,
        8,
    )


def test_the_bars_own_animations_have_no_yellow_version():
    display = DisplayConfig(event_icon="animation", reminder_icon="animation")
    for kind, animation in (("reminder", "reminder"), ("status", "event")):
        elements = by_id(drawing(screen(kind, response="tentative"), display, "a", 91))
        assert (
            elements["cal_icon"].stock_path == f"shared/animations/calendar_{animation}_16x16.anim"
        )
    # The label is still yellow beside the animation.
    assert elements["cal_busy"].color == "#FFC800FF"


def test_stock_status_animation_ignores_tentative():
    status = StatusSettings(show="meeting")
    d = drawing(screen("status", status=status, response="tentative"), DisplayConfig(), "a", 91)
    assert [e.id for e in d.elements] == ["cal_status"]


@pytest.mark.parametrize("calendar", ["RED_CALENDAR", "YELLOW_CALENDAR"])
def test_calendars_are_valid_xpm2(calendar):
    lines = getattr(icons, calendar).splitlines()
    assert lines[0] == "! XPM2"
    width, height, colours, cpp = map(int, lines[1].split())
    assert (width, height, cpp) == (16, 16, 1)
    assert colours <= 32  # the firmware's limit
    palette = {line[0] for line in lines[2 : 2 + colours]}
    rows = lines[2 + colours :]
    assert len(rows) == height
    assert all(len(row) == width and set(row) <= palette for row in rows)


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
    payload = drawing(screen("status"), DisplayConfig(), "a", 91).payload()
    assert {e["type"] for e in payload["elements"]} == {"xpmbitmap", "text", "countdown"}
    for element in payload["elements"]:
        assert "timeout" not in element  # mutually exclusive with display_until
        assert element["display_until"].isdigit()


def test_titles_are_capped():
    from busybar_calendar.render import MAX_TITLE

    long = "Quarterly planning " * 300  # 5700 characters
    for font in ("small", "global"):
        text = title_text(long, DisplayConfig(title_font=font))
        assert len(text) <= MAX_TITLE and text.endswith("...")
    assert title_text("Standup", DisplayConfig()) == "Standup"  # short ones untouched


# ---- the screen designs -------------------------------------------------------------------------
LAYOUTS = ["banner", "bold_title", "words"]
BUSY_RED, YELLOW, WHITE, BLACK = "#FF0000FF", "#FFC800FF", "#FFFFFFFF", "#000000FF"


def design(layout, kind="status", response="accepted", **display):
    config = DisplayConfig(layout=layout, **display)
    return by_id(drawing(screen(kind, response=response), config, "a", 91))


def test_the_default_layout_is_unchanged():
    assert DisplayConfig().layout == "default"
    explicit = by_id(drawing(screen("status"), DisplayConfig(layout="default"), "a", 91))
    implicit = by_id(drawing(screen("status"), DisplayConfig(), "a", 91))
    assert explicit == implicit
    assert list(explicit) == ["cal_xpm", "cal_title", "cal_time", "cal_busy"]


def test_banner_accepted_is_a_red_band_with_a_cut_out_title():
    e = design("banner")
    assert list(e) == ["cal_band", "cal_title", "cal_time", "cal_busy"]
    band = e["cal_band"]
    assert (band.type, band.x, band.y, band.width, band.height) == ("rectangle", 0, 0, 72, 11)
    assert (band.fill, band.fill_colors, band.border_width) == ("solid", [BUSY_RED], 0)
    title = e["cal_title"]
    assert (title.font, title.color, title.x, title.y, title.align) == (
        "normal",
        BLACK,
        2,
        -1,
        "top_left",
    )
    time = e["cal_time"]
    assert (time.x, time.y, time.align, time.color) == (1, 20, "bottom_left", WHITE)
    busy = e["cal_busy"]
    assert (busy.text, busy.font, busy.color) == ("BUSY", "small", BUSY_RED)
    assert (busy.x, busy.y, busy.align) == (72, 9, "top_right")


def test_banner_reminder_is_a_white_band_without_busy():
    e = design("banner", "reminder")
    assert list(e) == ["cal_band_r", "cal_title", "cal_time"]
    assert (e["cal_band_r"].fill, e["cal_band_r"].fill_colors) == ("solid", [WHITE])
    assert e["cal_title"].color == BLACK


def test_banner_tentative_is_a_yellow_outline_with_a_yellow_title():
    for kind, ids in (
        ("reminder", ["cal_band_m", "cal_title_m", "cal_time"]),
        ("status", ["cal_band_m", "cal_title_m", "cal_time", "cal_busy_m"]),
    ):
        e = design("banner", kind, "tentative")
        assert list(e) == ids
        band = e["cal_band_m"]
        assert (band.fill, band.border_width, band.border_color) == ("none", 1, YELLOW)
        assert e["cal_title_m"].color == YELLOW
    assert design("banner", "status", "tentative")["cal_busy_m"].color == YELLOW


def test_bold_title_colours_follow_the_state():
    reminder = design("bold_title", "reminder")
    assert list(reminder) == ["cal_title", "cal_time_r"]
    assert reminder["cal_time_r"].color == WHITE
    accepted = design("bold_title")
    assert list(accepted) == ["cal_title", "cal_time_a", "cal_busy"]
    assert accepted["cal_time_a"].color == BUSY_RED
    assert (accepted["cal_busy"].text, accepted["cal_busy"].color) == ("BUSY", BUSY_RED)
    maybe = design("bold_title", "status", "tentative")
    assert list(maybe) == ["cal_title", "cal_time_m", "cal_busy_m"]
    assert maybe["cal_time_m"].color == YELLOW
    assert (maybe["cal_busy_m"].text, maybe["cal_busy_m"].color) == ("MAYBE", YELLOW)
    title = accepted["cal_title"]
    assert (title.font, title.color, title.x, title.y) == ("normal", WHITE, 1, -1)


def test_words_says_maybe_in_the_reminder_and_the_event():
    for kind in ("reminder", "status"):
        e = design("words", kind, "tentative")
        assert e["cal_xpm_maybe"].data == icons.YELLOW_CALENDAR
        assert (e["cal_busy_m"].text, e["cal_busy_m"].color) == ("MAYBE", YELLOW)
    assert "cal_busy" not in design("words", "reminder")  # an accepted reminder has no label
    assert design("words")["cal_busy"].text == "BUSY"
    # The word does not depend on the BUSY label being on.
    assert design("words", "status", "tentative", busy_label="")["cal_busy_m"].text == "MAYBE"


def test_words_with_the_global_font_has_no_label_as_the_default_has_none():
    e = design("words", "status", "tentative", title_font="global")
    assert not any(key.startswith("cal_busy") for key in e)


@pytest.mark.parametrize("layout", LAYOUTS)
def test_tentative_yellow_off_draws_a_maybe_like_an_accepted_event(layout):
    plain = design(layout, "status", "accepted")
    maybe = design(layout, "status", "tentative", tentative_yellow=False)
    assert maybe == plain
    assert list(maybe) == list(design(layout, "status", "accepted", tentative_yellow=False))


@pytest.mark.parametrize("layout", LAYOUTS)
def test_a_stock_status_is_drawn_the_same_in_every_layout(layout):
    status = StatusSettings(show="meeting")
    config = DisplayConfig(layout=layout)
    [element] = drawing(screen("status", status=status), config, "a", 91).elements
    assert element.stock_path == "shared/animations/meeting_72x16.anim"


@pytest.mark.parametrize("layout", ["banner", "bold_title"])
def test_the_large_layouts_use_the_global_font_when_asked(layout):
    e = design(layout, "reminder", title_font="global")
    assert e["cal_title"].font == "global"
    assert design(layout, "reminder", title_font="small")["cal_title"].font == "normal"
    # Cyrillic is drawn as it is in the global font and transliterated in the others.
    global_title = design(layout, "reminder", title_font="global")["cal_title"]
    assert global_title.text == "Планування спринту"
    assert design(layout, "reminder")["cal_title"].text == "Planuvannya sprintu"


def title_event(title):
    event = dataclasses.replace(EVENT, title=title)
    return Screen("reminder", event, ReminderSettings(), StatusSettings())


def test_a_title_scrolls_only_when_its_true_width_does_not_fit():
    from busybar_calendar.fontmetrics import text_width

    def width(text):
        return text_width(text, "normal")

    for layout, available in (("banner", 68), ("bold_title", 70)):
        config = DisplayConfig(layout=layout)

        def title_of(text, config=config):
            return by_id(drawing(title_event(text), config, "a", 91))["cal_title"]

        # "Design review" is 65 px in the 7px font: it fits both, and does not scroll.
        assert title_of("Design review").scroll_rate is None

        # Narrow letters: many characters, few pixels. A flat 5 px a character would scroll it.
        narrow = "i" * (available // width("i"))
        assert width(narrow) <= available < len(narrow) * 5
        assert title_of(narrow).scroll_rate is None

        # Wide letters: few characters, many pixels. A flat 5 px a character would not scroll it.
        wide = "W" * (available // width("W") + 1)
        assert len(wide) * 5 <= available < width(wide)
        scrolling = title_of(wide)
        assert (scrolling.width, scrolling.scroll_rate) == (available, 1200)

        # The exact edge: filled to the pixel does not scroll, one more letter does.
        text = "Design review"
        while width(text + "i") <= available:
            text += "i"
        assert title_of(text).scroll_rate is None
        assert width(text + "i") > available
        assert title_of(text + "i").scroll_rate is not None


def test_a_long_title_scrolls_inside_its_box():
    long = "Quarterly planning with the design team"
    e = by_id(drawing(title_event(long), DisplayConfig(layout="banner"), "a", 91))
    title = e["cal_title"]
    assert (title.x, title.width) == (2, 68)  # inside the band, two pixels from each end
    assert title.scroll_start_delay == 1500 and title.scroll_repeat_delay == 2500


@pytest.mark.parametrize("layout", LAYOUTS)
@pytest.mark.parametrize("kind", ["reminder", "status"])
@pytest.mark.parametrize("response", ["accepted", "tentative"])
def test_every_design_serialises_for_the_wire(layout, kind, response):
    payload = drawing(
        screen(kind, response=response), DisplayConfig(layout=layout), "a", 91
    ).payload()
    assert payload["priority"] == 91
    ids = [e["id"] for e in payload["elements"]]
    assert len(ids) == len(set(ids))
    for element in payload["elements"]:
        assert "timeout" not in element
        assert element["display_until"].isdigit()
        if element["type"] == "rectangle":
            assert element["fill_colors"] and element["width"] == 72 and element["height"] == 11
