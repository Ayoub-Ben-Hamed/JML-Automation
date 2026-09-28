"""Unit tests for jml.audit_logger."""

import json
import sqlite3
from datetime import datetime
from jml.audit_logger import AuditLogger, LogBackend, AuditEntry


class TestAuditEntry:
    def test_entry_is_immutable(self):
        entry = AuditEntry(
            entry_id="1", timestamp="2024-01-01T00:00:00+00:00",
            event_type="HIRE", employee_id="EMP-1", user_email="a@b.com",
            action="create", status="success", triggered_by="test",
        )
        assert entry.status == "success"

    def test_to_json_line(self):
        entry = AuditEntry(
            entry_id="1", timestamp="2024-01-01T00:00:00+00:00",
            event_type="HIRE", employee_id="EMP-1", user_email="a@b.com",
            action="create", status="success", triggered_by="test",
            groups_added="g1,g2",
        )
        data = json.loads(entry.to_json_line())
        assert data["event_type"] == "HIRE"
        assert data["groups_added"] == "g1,g2"


class TestAuditLoggerCSV:
    def test_creates_file_and_logs(self, tmp_path):
        path = tmp_path / "audit.csv"
        logger = AuditLogger(LogBackend.CSV, path)
        entry = logger.log(
            event_type="HIRE", employee_id="EMP-1", user_email="a@b.com",
            action="create", status="success", triggered_by="test",
            groups_added=["eng", "us-west"],
        )
        assert path.exists()
        content = path.read_text()
        assert "HIRE" in content
        assert "eng,us-west" in content
        assert entry.entry_id


class TestAuditLoggerJSON:
    def test_appends_json_lines(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        logger = AuditLogger(LogBackend.JSON, path)
        logger.log(event_type="TERMINATE", employee_id="EMP-2", user_email="b@c.com",
                   action="deactivate", status="success", triggered_by="test")
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["event_type"] == "TERMINATE"


class TestAuditLoggerSQLite:
    def test_creates_schema_and_inserts(self, tmp_path):
        path = tmp_path / "audit.db"
        logger = AuditLogger(LogBackend.SQLITE, path)
        logger.log(event_type="MOVE", employee_id="EMP-3", user_email="c@d.com",
                   action="diff", status="partial", triggered_by="test",
                   old_role="SWE", new_role="Manager",
                   groups_added=["managers"], groups_removed=["ic"])

        rows = logger.find_by_email("c@d.com")
        assert len(rows) == 1
        assert rows[0]["old_role"] == "SWE"
        assert rows[0]["new_role"] == "Manager"

    def test_find_by_event_type(self, tmp_path):
        path = tmp_path / "audit.db"
        logger = AuditLogger(LogBackend.SQLITE, path)
        logger.log(event_type="HIRE", employee_id="EMP-1", user_email="a@b.com",
                   action="create", status="success", triggered_by="test")
        logger.log(event_type="HIRE", employee_id="EMP-2", user_email="b@c.com",
                   action="create", status="success", triggered_by="test")
        logger.log(event_type="TERMINATE", employee_id="EMP-3", user_email="c@d.com",
                   action="deactivate", status="success", triggered_by="test")

        hires = logger.find_by_event_type("HIRE", "2000-01-01", "2099-12-31")
        assert len(hires) == 2

    def test_find_failures(self, tmp_path):
        path = tmp_path / "audit.db"
        logger = AuditLogger(LogBackend.SQLITE, path)
        logger.log(event_type="HIRE", employee_id="EMP-1", user_email="a@b.com",
                   action="create", status="failure", triggered_by="test", errors=["token expired"])

        fails = logger.find_failures("2000-01-01", "2099-12-31")
        assert len(fails) == 1
        assert "token expired" in fails[0]["errors"]

    def test_find_group_changes(self, tmp_path):
        path = tmp_path / "audit.db"
        logger = AuditLogger(LogBackend.SQLITE, path)
        logger.log(event_type="MOVE", employee_id="EMP-1", user_email="a@b.com",
                   action="diff", status="success", triggered_by="test",
                   groups_added=["okta_admin", "eng"])

        changes = logger.find_group_changes("admin", "2000-01-01", "2099-12-31")
        assert len(changes) == 1