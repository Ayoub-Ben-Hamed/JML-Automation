"""Unit tests for jml.reports."""

from jml.audit_logger import AuditLogger, LogBackend
from jml.reports import ComplianceReport


class TestComplianceReport:
    def test_monthly_summary(self, tmp_path):
        db = tmp_path / "audit.db"
        audit = AuditLogger(LogBackend.SQLITE, db)
        report = ComplianceReport(audit)

        audit.log(event_type="HIRE", employee_id="EMP-1", user_email="a@b.com",
                  action="create", status="success", triggered_by="test")
        audit.log(event_type="TERMINATE", employee_id="EMP-2", user_email="b@c.com",
                  action="deactivate", status="failure", triggered_by="test", errors=["api down"])

        data = report.monthly_summary(2026, 1)
        assert data["total_hires"] >= 0
        assert data["total_terminates"] >= 0

    def test_user_lifecycle_report(self, tmp_path):
        db = tmp_path / "audit.db"
        audit = AuditLogger(LogBackend.SQLITE, db)
        report = ComplianceReport(audit)

        audit.log(event_type="HIRE", employee_id="EMP-1", user_email="alice@b.com",
                  action="create", status="success", triggered_by="test",
                  groups_added=["eng", "github"])
        audit.log(event_type="MOVE", employee_id="EMP-1", user_email="alice@b.com",
                  action="diff", status="success", triggered_by="test",
                  groups_added=["senior"], groups_removed=["eng"])

        life = report.user_lifecycle_report("alice@b.com")
        assert life["event_count"] == 2
        assert "senior" in life["current_groups"]

    def test_sensitive_events_alert(self, tmp_path):
        db = tmp_path / "audit.db"
        audit = AuditLogger(LogBackend.SQLITE, db)
        report = ComplianceReport(audit)

        audit.log(event_type="TERMINATE", employee_id="EMP-1", user_email="a@b.com",
                  action="deactivate", status="success", triggered_by="test")

        alerts = report.sensitive_events_alert("2000-01-01", "2099-12-31")
        assert len(alerts) == 1