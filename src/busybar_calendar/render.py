"""
The drawing for a screen.

The front panel is 72x16. A reminder is a 16x16 calendar icon with the
event's title beside it and a countdown to the start. The status during an
event is the same with a countdown to the end and a red BUSY beside it, or
one of the bar's own 72x16 status animations. The icon is the bar's own
calendar animation or a red calendar drawn inline, per `[display]`. An event
you marked tentative gets a yellow calendar and a yellow BUSY instead.

Every element carries `display_until`, so the bar takes the drawing down by
itself even if this service has stopped - a minute after the screen ends
rather than on the second, because this service redraws or clears the same
elements right then, and a redraw that lands as the old element expires
loses its animation on firmware 1.2.4 (measured: 0 of 256 icon pixels lit;
with the expiry a few seconds later, the icon stays).
"""

from __future__ import annotations

import unicodedata
from typing import Annotated, Any, Literal, Protocol

from anyascii import anyascii
from busylib import types
from pydantic import BaseModel, Field

from . import icons
from .config import DisplayConfig
from .events import UNTITLED
from .fontmetrics import text_width
from .schedule import Screen

WIDTH = 72
ICON = 16
TEXT_X = ICON + 2
REMINDER_ANIMATION = "shared/animations/calendar_reminder_16x16.anim"
EVENT_ANIMATION = "shared/animations/calendar_event_16x16.anim"
HIDDEN_TITLE = "Next event"
MAYBE_LABEL = "MAYBE"
# What an event you marked tentative is drawn in; see `[display] tentative_yellow`.
TENTATIVE_COLOR = "#FFC800FF"
WHITE = "#FFFFFFFF"
BLACK = "#000000FF"
# How long a drawing outlives its screen if nothing replaces it; see above.
EXPIRY_GRACE = 60
DRAW_PATH = "/api/display/draw"

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
# The BUSY label, in the small font on the countdown's rows (10-14): 8px
# below the title's anchor, whose glyphs start 2px down.
LABEL_TOP_Y = 8
SCROLL_RATE = 1200
SCROLL_START_DELAY = 1500
SCROLL_REPEAT_DELAY = 2500

# The banner and bold-title designs: the title takes the top eleven rows in the 7px
# font, the countdown and the label the last five. y=-1 puts the font's glyphs on
# rows 1-9 (0-9 in the global font), which leaves a row between them and the digits.
BAND_HEIGHT = 11
BIG_TITLE_Y = -1
LOW_COUNTDOWN_Y = 20  # bottom_left: the superscript digits land on rows 11-15
LOW_LABEL_Y = 9  # small font, top_right: rows 11-15
BAND_TITLE_X = 2


class XpmBitmapElement(types.DisplayElementBase):
    """An inline XPM2 image: in the bar's API, but not yet among busylib's models."""

    type: Literal["xpmbitmap"] = "xpmbitmap"
    data: str
    opacity: int = Field(default=100, ge=0, le=100)


Element = Annotated[
    types.TextElement
    | types.AnimationElement
    | types.CountdownElement
    | types.RectangleElement
    | XpmBitmapElement,
    Field(discriminator="type"),
]


class Drawing(BaseModel):
    """The body of POST /api/display/draw."""

    application_name: str = Field(min_length=1, max_length=32)
    priority: int = Field(ge=1, le=100)
    elements: list[Element] = Field(min_length=1)

    def payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class Poster(Protocol):
    async def api_request(self, method: str, path: str, **kwargs: Any) -> Any: ...


async def send(bar: Poster, drawing: Drawing) -> None:
    """Draw on the bar - on the LAN or through BUSY Cloud, whichever `bar` reaches."""
    await bar.api_request("POST", DRAW_PATH, json_payload=drawing.payload())


def _drawable(c: str) -> bool:
    # No font has control characters, emoji or other pictographs; and
    # transliterated, an emoji becomes ":coffee:".
    category = unicodedata.category(c)
    return category[0] != "C" and category != "So" and not "︀" <= c <= "️"


# A longer title only scrolls longer; and a draw request carrying a title of
# thousands of characters left a bar's HTTP API hanging (firmware 1.2.4,
# reached on the LAN and through BUSY Cloud alike) until it was power-cycled.
MAX_TITLE = 120


def title_text(title: str, display: DisplayConfig) -> str:
    """The title as the chosen font can draw it, and no longer than MAX_TITLE."""
    title = "".join(" " if c.isspace() else c for c in title if c.isspace() or _drawable(c))
    if display.title_font != "global":
        if display.transliterate:
            title = anyascii(title)
        title = "".join(c for c in title if " " <= c <= "~")
    title = " ".join(title.split()) or UNTITLED
    if len(title) > MAX_TITLE:
        title = title[: MAX_TITLE - 3].rstrip() + "..."
    return title


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


def _tentative(screen: Screen, display: DisplayConfig) -> bool:
    return display.tentative_yellow and screen.event.response == "tentative"


def _icon(choice: str, animation: str, until: str, tentative: bool) -> Element:
    # Different ids for the two kinds: a draw updates elements by id, and an
    # element is not turned from one kind into the other. The yellow calendar
    # has an id of its own so that going from one colour to the other redraws
    # the bitmap rather than relying on the bar to swap an element's pixels.
    if choice == "red_calendar":
        return XpmBitmapElement(
            id="cal_xpm_maybe" if tentative else "cal_xpm",
            data=icons.YELLOW_CALENDAR if tentative else icons.RED_CALENDAR,
            x=0,
            y=0,
            align="top_left",
            display_until=until,
        )
    return types.AnimationElement(
        id="cal_icon",
        stock_path=animation,
        loop=True,
        x=0,
        y=0,
        align="top_left",
        display_until=until,
    )


def _titled(
    screen: Screen,
    icon: Element,
    title: str,
    display: DisplayConfig,
    until: str,
    words: bool = False,
) -> list[Element]:
    """
    A calendar icon, a title, a countdown to `screen.until` and, during an event, BUSY.

    With `words`, an event you marked tentative says MAYBE in that place - also in its
    reminder - so the response shows in a word as well as in the colour.
    """
    font = display.title_font
    if font == "global":
        # 11px leaves no second line: title and countdown share one.
        available = WIDTH - TEXT_X - COUNTDOWN_WIDTH - 1
        title_at = (TEXT_X, 8, "mid_left")
        countdown_at = (WIDTH - 1, COUNTDOWN_MID_Y, "mid_right")
    else:
        available = WIDTH - TEXT_X
        title_at = (TEXT_X, TITLE_TOP_Y[font], "top_left")
        countdown_at = (TEXT_X, COUNTDOWN_BOTTOM_Y, "bottom_left")
    elements: list[Element] = [
        icon,
        _text("cal_title", title, font, *title_at, available, until),
        types.CountdownElement(
            id="cal_time",
            timestamp=str(int(screen.until.timestamp())),
            direction="time_left",
            show_hours="when_non_zero",
            x=countdown_at[0],
            y=countdown_at[1],
            align=countdown_at[2],
            display_until=until,
        ),
    ]
    tentative = _tentative(screen, display)
    label = display.busy_label if screen.kind == "status" else ""
    if words and tentative:
        label = MAYBE_LABEL
    # Beside a global-font title there is no room left for the label.
    if label and font != "global":
        elements.append(
            types.TextElement(
                id="cal_busy_m" if words and tentative else "cal_busy",
                text=label,
                font="small",
                color=TENTATIVE_COLOR if tentative else display.busy_color,
                x=WIDTH,
                y=LABEL_TOP_Y,
                align="top_right",
                display_until=until,
            )
        )
    return elements


def _wide_title(
    element_id: str, text: str, font: str, x: int, available: int, color: str, until: str
) -> types.TextElement:
    """The title in the 7px (or global) font, scrolling when its true width does not fit."""
    scroll = text_width(text, font) > available
    return types.TextElement(
        id=element_id,
        text=text,
        font=font,
        color=color,
        x=x,
        y=BIG_TITLE_Y,
        align="top_left",
        display_until=until,
        width=available if scroll else None,
        scroll_rate=SCROLL_RATE if scroll else None,
        scroll_start_delay=SCROLL_START_DELAY if scroll else None,
        scroll_repeat_delay=SCROLL_REPEAT_DELAY if scroll else None,
    )


def _low_countdown(
    element_id: str, screen: Screen, color: str, until: str
) -> types.CountdownElement:
    return types.CountdownElement(
        id=element_id,
        timestamp=str(int(screen.until.timestamp())),
        direction="time_left",
        show_hours="when_non_zero",
        color=color,
        x=1,
        y=LOW_COUNTDOWN_Y,
        align="bottom_left",
        display_until=until,
    )


def _low_label(element_id: str, text: str, color: str, until: str) -> types.TextElement:
    return types.TextElement(
        id=element_id,
        text=text,
        font="small",
        color=color,
        x=WIDTH,
        y=LOW_LABEL_Y,
        align="top_right",
        display_until=until,
    )


def _large_font(display: DisplayConfig) -> str:
    return "global" if display.title_font == "global" else "normal"


def _banner(screen: Screen, display: DisplayConfig, title: str, until: str) -> list[Element]:
    """
    The title on a band: red (the BUSY colour) during an event you accepted, white before
    it starts, and for a tentative one a yellow outline with a yellow title. The
    countdown and BUSY sit below. The ids differ with the band's look, so a change of
    look clears the screen first rather than recolouring a rectangle in place.
    """
    status = screen.kind == "status"
    font = _large_font(display)
    if _tentative(screen, display):
        band = types.RectangleElement(
            id="cal_band_m",
            x=0,
            y=0,
            width=WIDTH,
            height=BAND_HEIGHT,
            fill="none",
            fill_colors=[TENTATIVE_COLOR],
            border_width=1,
            border_color=TENTATIVE_COLOR,
            display_until=until,
        )
        title_color, label_color, suffix = TENTATIVE_COLOR, TENTATIVE_COLOR, "_m"
    else:
        fill = display.busy_color if status else WHITE
        band = types.RectangleElement(
            id="cal_band" if status else "cal_band_r",
            x=0,
            y=0,
            width=WIDTH,
            height=BAND_HEIGHT,
            fill="solid",
            fill_colors=[fill],
            border_width=0,
            display_until=until,
        )
        title_color, label_color, suffix = BLACK, display.busy_color, ""
    elements: list[Element] = [
        band,
        _wide_title(
            "cal_title" + suffix,
            title,
            font,
            BAND_TITLE_X,
            WIDTH - 2 * BAND_TITLE_X,
            title_color,
            until,
        ),
        _low_countdown("cal_time", screen, WHITE, until),
    ]
    if status and display.busy_label:
        elements.append(_low_label("cal_busy" + suffix, display.busy_label, label_color, until))
    return elements


def _bold_title(screen: Screen, display: DisplayConfig, title: str, until: str) -> list[Element]:
    """
    The title in the larger font across the top, the countdown and the label in the state
    colour below it: red when accepted, yellow when tentative - which says MAYBE - and
    white in a reminder. The ids differ with the look, so a change of look clears first.
    """
    status = screen.kind == "status"
    tentative = _tentative(screen, display)
    if not status:
        color, time_id = WHITE, "cal_time_r"
    elif tentative:
        color, time_id = TENTATIVE_COLOR, "cal_time_m"
    else:
        color, time_id = display.busy_color, "cal_time_a"
    elements: list[Element] = [
        _wide_title("cal_title", title, _large_font(display), 1, WIDTH - 2, WHITE, until),
        _low_countdown(time_id, screen, color, until),
    ]
    label = MAYBE_LABEL if tentative else display.busy_label
    if status and label:
        elements.append(_low_label("cal_busy_m" if tentative else "cal_busy", label, color, until))
    return elements


def elements(screen: Screen, display: DisplayConfig) -> list[Element]:
    until = str(int(screen.until.timestamp()) + EXPIRY_GRACE)
    if screen.kind == "status" and screen.status.show != "name":
        # One of the bar's own statuses, whatever the layout.
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
    if screen.kind == "reminder":
        title = (
            title_text(screen.event.title, display) if screen.reminder.show_name else HIDDEN_TITLE
        )
        choice, animation = display.reminder_icon, REMINDER_ANIMATION
    else:
        title = title_text(screen.event.title, display)
        choice, animation = display.event_icon, EVENT_ANIMATION
    if display.layout == "banner":
        return _banner(screen, display, title, until)
    if display.layout == "bold_title":
        return _bold_title(screen, display, title, until)
    icon = _icon(choice, animation, until, _tentative(screen, display))
    return _titled(screen, icon, title, display, until, words=display.layout == "words")


def drawing(
    screen: Screen, display: DisplayConfig, application_name: str, priority: int
) -> Drawing:
    return Drawing(
        application_name=application_name,
        priority=priority,
        elements=elements(screen, display),
    )


def sound(screen: Screen, display: DisplayConfig) -> str | None:
    """The stock sound for a screen appearing, if its settings want one."""
    if screen.kind == "reminder":
        return display.reminder_sound if screen.reminder.sound else None
    return display.event_sound if screen.status.sound else None
