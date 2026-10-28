"""SvgChart: the dashboard's charts as inline SVG, drawn on the server (s13 §4.7).

No JavaScript and no chart library. Every label is escaped. Colours come from the page's CSS
classes (`bar`, `hidden`, `level-0`..`level-3`), so light and dark themes both work.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from html import escape
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class BarRow:
    label: str
    value: int | None  # None: fewer than the floor, drawn as a note instead of a bar


@dataclass(frozen=True, slots=True)
class StackedColumn:
    label: str
    shares: Sequence[float]  # one share per level, summing to 1


class SvgChart:
    WIDTH: ClassVar[int] = 560
    ROW_HEIGHT: ClassVar[int] = 26
    LABEL_WIDTH: ClassVar[int] = 170
    VALUE_WIDTH: ClassVar[int] = 110
    COLUMN_HEIGHT: ClassVar[int] = 180
    COLUMN_GAP: ClassVar[int] = 10

    @staticmethod
    def bars(rows: Sequence[BarRow], title: str, floor: int) -> str:
        """Horizontal bars, one per row, scaled to the largest shown value."""
        shown = [row.value for row in rows if row.value is not None]
        largest = max(shown, default=0) or 1
        track = SvgChart.WIDTH - SvgChart.LABEL_WIDTH - SvgChart.VALUE_WIDTH
        height = SvgChart.ROW_HEIGHT * max(len(rows), 1)
        parts = [SvgChart._open(SvgChart.WIDTH, height, title)]
        for position, row in enumerate(rows):
            top = position * SvgChart.ROW_HEIGHT
            middle = top + SvgChart.ROW_HEIGHT // 2 + 4
            parts.append(f'<text x="0" y="{middle}" class="label">{escape(row.label)}</text>')
            if row.value is None:
                note = f"fewer than {floor}"
                parts.append(
                    f'<text x="{SvgChart.LABEL_WIDTH}" y="{middle}" class="hidden">{note}</text>'
                )
            else:
                width = round(track * row.value / largest)
                parts.append(
                    f'<rect x="{SvgChart.LABEL_WIDTH}" y="{top + 5}" width="{width}" '
                    f'height="{SvgChart.ROW_HEIGHT - 10}" rx="3" class="bar"/>'
                )
                parts.append(
                    f'<text x="{SvgChart.LABEL_WIDTH + width + 6}" y="{middle}" '
                    f'class="value">{row.value}</text>'
                )
        parts.append("</svg>")
        return "".join(parts)

    @staticmethod
    def stacked(columns: Sequence[StackedColumn], title: str) -> str:
        """One column per week, its height split by level share (level 0 at the bottom)."""
        column_width = 46
        width = max(len(columns), 1) * (column_width + SvgChart.COLUMN_GAP)
        height = SvgChart.COLUMN_HEIGHT + 22
        parts = [SvgChart._open(width, height, title)]
        for position, column in enumerate(columns):
            left = position * (column_width + SvgChart.COLUMN_GAP)
            bottom = float(SvgChart.COLUMN_HEIGHT)
            for level, share in enumerate(column.shares):
                piece = SvgChart.COLUMN_HEIGHT * share
                bottom -= piece
                parts.append(
                    f'<rect x="{left}" y="{bottom:.1f}" width="{column_width}" '
                    f'height="{piece:.1f}" class="level-{level}"/>'
                )
            parts.append(
                f'<text x="{left}" y="{height - 4}" class="label small">'
                f"{escape(column.label)}</text>"
            )
        parts.append("</svg>")
        return "".join(parts)

    @staticmethod
    def _open(width: int, height: int, title: str) -> str:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            f'width="100%" role="img" aria-label="{escape(title)}"><title>{escape(title)}</title>'
        )
