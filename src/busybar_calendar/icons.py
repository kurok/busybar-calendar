"""
Icons drawn inline, as XPM2, so nothing has to be uploaded to the bar first.

RED_CALENDAR is the "calendar" emoji (U+1F4C5) of Google's Noto Emoji
(https://github.com/googlefonts/noto-emoji, Copyright 2013 Google LLC),
scaled to 16x16 and redrawn pixel by pixel for the LED panel: a solid red
header with the binder holes, a white page and a crisp "17", without the
month lettering that blurs at this size. As a Modified Version of Noto Emoji
it is under the SIL Open Font License 1.1, unlike the rest of this project:
see LICENSES/noto-emoji-OFL.txt.
"""

from __future__ import annotations

# One character per pixel: . clear, R red, P pink divider, W page, G page
# edge, K the digits (black is an unlit LED).
_RED_CALENDAR_PIXELS = (
    ".RRRRRRRRRRRRRR.",
    "RR.RRRRRRRRRR.RR",
    "RRRRRRRRRRRRRRRR",
    "RRRRRRRRRRRRRRRR",
    "RRRRRRRRRRRRRRRR",
    "RRRRRRRRRRRRRRRR",
    "GPPPPPPPPPPPPPPG",
    "GWWWWWWWWWWWWWWG",
    "GWWWWKWWKKKKWWWG",
    "GWWWKKWWWWWKWWWG",
    "GWWWWKWWWWKWWWWG",
    "GWWWWKWWWWKWWWWG",
    "GWWWWKWWWKWWWWWG",
    "GWWWWKWWWKWWWWWG",
    "GWWWWWWWWWWWWWWG",
    ".GGGGGGGGGGGGGG.",
)
_RED_CALENDAR_COLOURS = {
    ".": "none",
    "R": "#F44336",
    "P": "#F8C6C2",
    "W": "#F5F5F5",
    "G": "#B0B0B0",
    "K": "#000000",
}


def xpm(pixels: tuple[str, ...], colours: dict[str, str]) -> str:
    """An XPM2 image, in the form the bar's xpmbitmap element takes."""
    width, height = len(pixels[0]), len(pixels)
    assert all(len(row) == width for row in pixels)
    lines = ["! XPM2", f"{width} {height} {len(colours)} 1"]
    lines += [f"{char} c {value}" for char, value in colours.items()]
    lines += pixels
    return "\n".join(lines) + "\n"


RED_CALENDAR = xpm(_RED_CALENDAR_PIXELS, _RED_CALENDAR_COLOURS)
