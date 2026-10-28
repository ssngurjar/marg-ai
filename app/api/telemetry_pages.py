"""TelemetryPages: what the /status and /dashboard routes need, built once in wiring."""

from dataclasses import dataclass

from app.telemetry.dashboard_builder import DashboardBuilder
from app.telemetry.dashboard_link_codec import DashboardLinkCodec
from app.telemetry.status_report_builder import StatusReportBuilder
from app.telemetry.student_dashboard_builder import StudentDashboardBuilder


@dataclass(frozen=True, slots=True)
class TelemetryPages:
    status: StatusReportBuilder
    dashboard: DashboardBuilder
    students: StudentDashboardBuilder
    links: DashboardLinkCodec
    admin_floor: int  # K_ANONYMITY_FLOOR_ADMIN (owner, 2026-10-28)
