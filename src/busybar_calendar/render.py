"""
The drawing for a screen, built from the stock calendar assets on the bar.

The front panel is 72x16. A reminder is the 16x16 calendar-reminder
animation with the event's title beside it and a countdown to the start; the
status during an event is the calendar-event animation with the title and a
countdown to the end, or one of the bar's own 72x16 status animations.

Every element carries `display_until`, so the bar takes the drawing down on
time by itself, even if this service has stopped.
"""

from __future__ import annotations

import unicodedata

from anyascii import anyascii
from busylib import types

from .config import DisplayConfig
from .schedule import Screen

WIDTH = 72
ICON = 16
TEXT_X = ICON + 2
REMINDER_ANIMATION = "shared/animations/calendar_reminder_16x16.anim"
EVENT_ANIMATION = "shared/animations/calendar_event_16x16.anim"
HIDDEN_TITLE = "Next event"

# Rough glyph advance per font, only to decide whether a line must scroll.
CHAR_WIDTH = {"tiny": 4, "small": 4, "global": 6}
# The countdown is drawn in the 7px superscript font; room for "1:05:00".
COUNTDOWN_WIDTH = 28
# The title's top_left y, calibrated in busylib: small glyphs land on rows 2-6.
TITLE_TOP_Y = {"tiny": 1, "small": 0}
# The superscript font sits its digits 4px above the bottom of its box, so a
# box anchored at y=16 puts them on rows 7-11, into the title's descenders.
# Anchored at 19 they land on rows 10-14, level with the icon's last row.
# Measured on firmware 1.2.4 from GET /api/screen.
COUNTDOWN_BOTTOM_Y = 19
# Beside an 11px global-font title, centred on the same rows (6-10).
COUNTDOWN_MID_Y = 9
SCROLL_RATE = 1200
SCROLL_START_DELAY = 1500
SCROLL_REPEAT_DELAY = 2500


def _drawable(c: str) -> bool:
    # No font has control characters, emoji or other pictographs; and
    # transliterated, an emoji becomes ":coffee:".
    category = unicodedata.category(c)
    return category[0] != "C" and category != "So" and not "\ufe00" <= c <= "\ufe0f"


def title_text(title: str, display: DisplayConfig) -> str:
    """The title as the chosen font can draw it."""
    title = "".join(" " if c.isspace() else c for c in title if c.isspace() or _drawable(c))
    if display.title_font != "global":
        if display.transliterate:
            title = anyascii(title)
        title = "".join(c for c in title if " " <= c <= "~")
    return " ".join(title.split()) or "Busy"


def _text(
    element_id: str, text: str, font: str, x: int, y: int, align: str, available: int, until: str
) -> types.TextElement:
    scroll = len(text) * CHAR_WIDTH.get(font, 5) > available
    return types.TextElement(
        id=element_id,
        text=text,
        font=font,
        x=x,
        y=y,
        align=align,
        display_until=until,
        width=available if scroll else None,
        scroll_rate=SCROLL_RATE if scroll else None,
        scroll_start_delay=SCROLL_START_DELAY if scroll else None,
        scroll_repeat_delay=SCROLL_REPEAT_DELAY if scroll else None,
    )


def _titled(
    screen: Screen, animation: str, title: str, display: DisplayConfig, until: str
) -> list[types.DisplayElement]:
    """An animated calendar icon, a title, and a countdown to `screen.until`."""
    countdown_to = str(int(screen.until.timestamp()))
    elements: list[types.DisplayElement] = [
        types.AnimationElement(
            id="cal_icon",
            stock_path=animation,
            loop=True,
            x=0,
            y=0,
            align="top_left",
            display_until=until,
        )
    ]
    font = display.title_font
    if font == "global":
        # 11px leaves no second line: title and countdown share one.
        available = WIDTH - TEXT_X - COUNTDOWN_WIDTH - 1
        elements.append(_text("cal_title", title, font, TEXT_X, 8, "mid_left", available, until))
        elements.append(
            types.CountdownElement(
                id="cal_time",
                timestamp=countdown_to,
                direction="time_left",
                show_hours="when_non_zero",
                x=WIDTH - 1,
                y=COUNTDOWN_MID_Y,
                align="mid_right",
                display_until=until,
            )
        )
        return elements
    available = WIDTH - TEXT_X
    top = TITLE_TOP_Y[font]
    elements.append(_text("cal_title", title, font, TEXT_X, top, "top_left", available, until))
    elements.append(
        types.CountdownElement(
            id="cal_time",
            timestamp=countdown_to,
            direction="time_left",
            show_hours="when_non_zero",
            x=TEXT_X,
            y=COUNTDOWN_BOTTOM_Y,
            align="bottom_left",
            display_until=until,
        )
    )
    return elements


def elements(screen: Screen, display: DisplayConfig) -> list[types.DisplayElement]:
    until = str(int(screen.until.timestamp()))
    if screen.kind == "reminder":
        title = (
            title_text(screen.event.title, display) if screen.reminder.show_name else HIDDEN_TITLE
        )
        return _titled(screen, REMINDER_ANIMATION, title, display, until)

    if screen.status.show == "name":
        return _titled(
            screen, EVENT_ANIMATION, title_text(screen.event.title, display), display, until
        )
    return [
        types.AnimationElement(
            id="cal_status",
            stock_path=f"shared/animations/{screen.status.show}_72x16.anim",
            loop=True,
            x=0,
            y=0,
            align="top_left",
            display_until=until,
        )
    ]


def drawing(
    screen: Screen, display: DisplayConfig, application_name: str, priority: int
) -> types.DisplayElements:
    return types.DisplayElements(
        application_name=application_name,
        priority=priority,
        elements=elements(screen, display),
    )


def sound(screen: Screen, display: DisplayConfig) -> str | None:
    """The stock sound for a screen appearing, if its settings want one."""
    if screen.kind == "reminder":
        return display.reminder_sound if screen.reminder.sound else None
    return display.event_sound if screen.status.sound else None
