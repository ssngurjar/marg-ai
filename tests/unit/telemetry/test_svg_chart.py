"""SvgChart: server-drawn charts with every label escaped (s13 §4.7)."""

import pytest

from app.telemetry.svg_chart import BarRow, StackedColumn, SvgChart

pytestmark = pytest.mark.unit


def test_bars_scale_to_the_largest_value_and_show_each_value() -> None:
    svg = SvgChart.bars([BarRow("earth sky", 10), BarRow("art music", 5)], "Domains", 5)
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    track = SvgChart.WIDTH - SvgChart.LABEL_WIDTH - SvgChart.VALUE_WIDTH
    assert f'width="{track}"' in svg
    assert f'width="{round(track / 2)}"' in svg
    assert ">10<" in svg
    assert ">5<" in svg


def test_a_hidden_value_is_a_note_never_a_bar_or_a_number() -> None:
    svg = SvgChart.bars([BarRow("nature living", None)], "Domains", 5)
    assert "fewer than 5" in svg
    assert "<rect" not in svg


def test_labels_and_titles_are_escaped() -> None:
    svg = SvgChart.bars([BarRow("<script>alert(1)</script>", 1)], '"><img onerror=x>', 5)
    assert "<script>" not in svg
    assert "<img" not in svg
    assert "&lt;script&gt;" in svg


def test_stacked_columns_split_their_height_by_share() -> None:
    svg = SvgChart.stacked([StackedColumn("2026-W44", [0.5, 0.25, 0.25, 0.0])], "Engagement")
    height = SvgChart.COLUMN_HEIGHT
    assert f'height="{height * 0.5:.1f}" class="level-0"' in svg
    assert f'height="{height * 0.25:.1f}" class="level-1"' in svg
    assert ">2026-W44<" in svg


def test_no_rows_still_draws_an_empty_chart() -> None:
    assert SvgChart.bars([], "Domains", 5).endswith("</svg>")
    assert SvgChart.stacked([], "Engagement").endswith("</svg>")
