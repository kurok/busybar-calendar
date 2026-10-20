"""
How wide the bar's fonts draw text, so a title is scrolled only when it has to be.

The advance, in LED pixels, of each printable ASCII character (0x20-0x7E) in the
7px `normal` font and the 11px `global` font, read from the bitmap fonts the
BUSY Bar firmware bakes (busy-app/busybar-firmware, assets/shared/fonts) as the
community emulator publishes them (maxswinkels/busybar-emulator, MIT). Summed,
they give the widths the bar draws: "Design review" is 65 px in `normal` and 58 px
in `global`. The backtick has no glyph in the `normal` font's bitmap; it is
counted as a "?", which is how the emulator draws it.
"""

from __future__ import annotations

FIRST = 0x20

# fmt: off
NORMAL = (
    5, 3, 4, 6, 6, 8, 7, 2, 3, 3, 4, 6, 3, 4, 4, 5, 6, 6, 6,
    6, 6, 6, 6, 6, 6, 6, 2, 3, 4, 6, 4, 6, 8, 6, 6, 6, 6, 6,
    6, 6, 6, 4, 5, 6, 5, 8, 6, 6, 6, 6, 6, 6, 6, 6, 6, 8, 6,
    6, 6, 3, 5, 3, 6, 5, 6, 5, 5, 5, 5, 5, 5, 5, 5, 4, 4, 5,
    4, 6, 5, 5, 5, 5, 4, 5, 5, 5, 6, 6, 6, 5, 5, 4, 3, 4, 6,
)

GLOBAL = (
    3, 2, 4, 7, 6, 6, 6, 2, 3, 3, 4, 6, 2, 5, 2, 5, 6, 4, 6,
    6, 5, 6, 6, 5, 6, 6, 2, 2, 4, 5, 4, 5, 7, 6, 6, 6, 6, 5,
    5, 6, 6, 2, 5, 6, 5, 8, 6, 6, 5, 6, 5, 6, 6, 6, 6, 8, 6,
    5, 6, 3, 5, 3, 4, 5, 3, 6, 5, 5, 5, 5, 4, 5, 5, 2, 3, 5,
    2, 8, 5, 5, 5, 5, 5, 5, 4, 5, 4, 6, 5, 5, 5, 4, 2, 4, 6,
)
# fmt: on

_TABLES = {"normal": NORMAL, "global": GLOBAL}
# What a character outside the tables takes: the global font draws Cyrillic and
# accents at about this width, and a wrong guess only scrolls a title early.
UNKNOWN = 6


def text_width(text: str, font: str) -> int:
    """The pixels `text` takes in `font` (`normal` or `global`)."""
    table = _TABLES[font]
    return sum(
        table[ord(c) - FIRST] if FIRST <= ord(c) < FIRST + len(table) else UNKNOWN for c in text
    )
