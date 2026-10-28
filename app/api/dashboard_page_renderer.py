"""DashboardPageRenderer: /status and /dashboard as plain HTML (s13 §4.7).

Built in Python with every value escaped (`html.escape`), so the pages need no template engine
and no JavaScript; charts are SvgChart's inline SVG. Only numbers and fixed labels reach a page:
never text, hashes or names.
"""

from collections.abc import Sequence
from html import escape
from typing import ClassVar, Final

from app.telemetry.dashboard_builder import Bucket, YoungLearnerDashboard
from app.telemetry.status_report_builder import StatusReport
from app.telemetry.svg_chart import BarRow, StackedColumn, SvgChart

DASH: Final = "-"  # no value yet


class DashboardPageRenderer:
    STYLESHEET: ClassVar[str] = "/dashboard/dashboard.css"

    @staticmethod
    def status(report: StatusReport) -> str:
        turns = [
            ("Turns (24 h)", str(report.turns)),
            ("Served well", _percent(report.served_ok_rate)),
            ("Wait for a reply, p50", _seconds(report.p50_user_ms)),
            ("Wait for a reply, p95", _seconds(report.p95_user_ms)),
        ]
        journey = report.journey
        counts = [
            ("Khoj turns", str(journey.journey_turns)),
            ("Daily messages sent", str(journey.nudges_sent)),
            ("Photos checked", str(journey.photos_received)),
            ("Photos refused (a person in them)", str(journey.photos_refused)),
            ("Khoj cards sent", str(journey.cards_sent)),
        ]
        step_rows = [
            [
                step.step,
                str(step.runs),
                f"{step.p50_ms} ms",
                f"{step.p95_ms} ms",
                _percent(step.ok_rate),
                _percent(step.degraded_rate),
            ]
            for step in report.steps
        ]
        sections = [
            _tiles(turns),
            "<h2>The parent journey (24 h)</h2>",
            _tiles(counts),
            "<h2>Every step (24 h)</h2>",
            _table(["Step", "Runs", "p50", "p95", "OK", "Degraded"], step_rows),
        ]
        if report.admin is not None:
            admin = report.admin
            failures = [
                [failure.step, failure.failure_kind, str(failure.turns)]
                for failure in admin.failures
            ]
            sections += [
                "<h2>Admin</h2>",
                _tiles(
                    [
                        ("Cost today (IST)", f"${admin.cost_today_usd:.4f}"),
                        (
                            "Web demo today",
                            f"${admin.web_cost_today_usd:.4f} of ${admin.web_daily_cap_usd:.2f}",
                        ),
                        ("Crisis replies (24 h)", str(admin.crisis_turns)),
                    ]
                ),
                _table(["Step", "Failure", "Times"], failures),
            ]
        generated = report.generated_at.strftime("%Y-%m-%d %H:%M UTC")
        return _page("Marg.ai status", sections, f"Updated {generated}")

    @staticmethod
    def dashboard(board: YoungLearnerDashboard) -> str:
        if not board.enough:
            note = f"<p class='note'>Not enough learners yet (fewer than {board.floor}).</p>"
            return _page("Marg.ai: young learners", [note], _floor_note(board.floor))
        floor = board.floor
        sections = [
            _tiles(
                [
                    ("Children", _count(board.children, floor)),
                    ("Parents", _count(board.parents, floor)),
                    ("Came back for a second day", _percent(board.return_rate)),
                    ("Khojs done (median per child)", _percent(board.median_done_rate)),
                ]
            ),
            "<h2>How many kinds of things each child explored</h2>",
            SvgChart.bars(_bar_rows(board.breadth), "Children by number of domains", floor),
            "<h2>Domains explored (children)</h2>",
            SvgChart.bars(_bar_rows(board.domains), "Children per domain", floor),
            "<h2>Engagement per week (share of reports, level 0 at the bottom)</h2>",
            SvgChart.stacked(
                [StackedColumn(week.week, week.level_shares) for week in board.weeks],
                "Engagement levels per week",
            ),
            _table(
                ["Week", "Reports", "Child asked their own question"],
                [
                    [week.week, str(week.reports), _percent(week.question_rate)]
                    for week in board.weeks
                ],
            ),
        ]
        if board.child_talk is not None:
            talk = board.child_talk
            sections += [
                "<h2>Children talking to Marg themselves</h2>",
                _tiles(
                    [
                        ("Children", _count(talk.children, floor)),
                        ("Sessions", str(talk.sessions)),
                        ("Sessions per child (median)", _number(talk.median_sessions_per_child)),
                        ("Own questions per session", _number(talk.questions_per_session)),
                        ("Domains touched", str(talk.domains_touched)),
                        ("Summaries sent to parents", str(talk.summaries_sent)),
                    ]
                ),
                _table(
                    ["How sessions ended", "Sessions"],
                    [[ending.label, str(ending.sessions)] for ending in talk.endings],
                ),
            ]
        if board.photos is not None:
            photos = board.photos
            sections += [
                "<h2>Photos and khoj cards</h2>",
                _tiles(
                    [
                        ("Reports", str(photos.reports_done)),
                        ("With a checked photo", str(photos.reports_with_photo)),
                        ("Photo with something counted", str(photos.reports_with_counts)),
                        ("Khoj cards sent", str(photos.cards_sent)),
                    ]
                ),
                "<p class='note'>Forwarding can't be measured: WhatsApp doesn't tell a business "
                "when a card is forwarded.</p>",
            ]
        return _page("Marg.ai: young learners", sections, _floor_note(floor))

    @staticmethod
    def link_invalid() -> str:
        message = (
            "<p>This dashboard link has expired or isn't valid. Ask for a new one: "
            "<code>marg admin-link</code>.</p>"
        )
        return _page("Link expired", [message], "")

    @staticmethod
    def unavailable() -> str:
        return _page("Not available right now", ["<p>Please try again in a minute.</p>"], "")


def _page(title: str, sections: Sequence[str], footer: str) -> str:
    body = "\n".join(sections)
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{escape(title)}</title>"
        f"<link rel='stylesheet' href='{DashboardPageRenderer.STYLESHEET}'></head>"
        f"<body><main><h1>{escape(title)}</h1>{body}"
        f"<footer>{escape(footer)}</footer></main></body></html>"
    )


def _tiles(tiles: Sequence[tuple[str, str]]) -> str:
    items = "".join(
        f"<div class='tile'><span class='tile-value'>{escape(value)}</span>"
        f"<span class='tile-label'>{escape(label)}</span></div>"
        for label, value in tiles
    )
    return f"<div class='tiles'>{items}</div>"


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    if not rows:
        return "<p class='note'>Nothing yet.</p>"
    head = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body_rows: list[str] = []
    for row in rows:
        cells = "".join(f"<td>{escape(cell)}</td>" for cell in row)
        body_rows.append(f"<tr>{cells}</tr>")
    table = f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"
    return f"<div class='table'>{table}</div>"


def _bar_rows(buckets: Sequence[Bucket]) -> list[BarRow]:
    return [BarRow(bucket.label.replace("_", " "), bucket.children) for bucket in buckets]


def _count(value: int | None, floor: int) -> str:
    return str(value) if value is not None else f"fewer than {floor}"


def _percent(value: float | None) -> str:
    return f"{value * 100:.0f}%" if value is not None else DASH


def _seconds(value_ms: int | None) -> str:
    return f"{value_ms / 1000:.1f} s" if value_ms is not None else DASH


def _number(value: float | None) -> str:
    return f"{value:.1f}" if value is not None else DASH


def _floor_note(floor: int) -> str:
    return f"Counts from fewer than {floor} children are hidden. No names, numbers or messages."
