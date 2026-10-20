import pytest

from busybar_calendar import fontmetrics


def test_widths_match_what_the_bar_draws():
    # Summed advances of the baked bitmaps; "Design review" is 65 px / 58 px on the bar.
    assert fontmetrics.text_width("Design review", "normal") == 65
    assert fontmetrics.text_width("Design review", "global") == 58


@pytest.mark.parametrize("table", [fontmetrics.NORMAL, fontmetrics.GLOBAL])
def test_every_printable_ascii_character_has_a_width(table):
    assert len(table) == 0x7E - 0x20 + 1
    assert all(1 <= advance <= 8 for advance in table)


def test_characters_outside_the_table_take_a_typical_width():
    assert fontmetrics.text_width("Привіт", "global") == 6 * 6
    assert fontmetrics.text_width("", "normal") == 0


def test_the_backtick_is_counted_as_a_question_mark():
    assert fontmetrics.text_width("`", "normal") == fontmetrics.text_width("?", "normal")
