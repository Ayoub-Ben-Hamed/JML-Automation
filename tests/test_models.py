"""Quick validation that HREvent serializes correctly"""

from datetime import date
from jml.models import HREvent, EventType, ParseResult


def test_hr_event_to_okta_profile():
    """An HREvent with all fields should map cleanly to an Okta profile."""
    evt = HREvent(
        employee_id="EMP-10001",
        email="alice@company.com",
        event_type=EventType.HIRE,
        department="Engineering",
        role="Software Engineer",
        manager_email="bob@company.com",
        employee_type="Full-Time",
        cost_center="CC-001",
        location="SF",
        phone="+1-555-0101",
    )

    profile = evt.to_okta_profile()
    assert profile["login"] == "alice@company.com"
    assert profile["department"] == "Engineering"
    assert profile["title"] == "Software Engineer"
    assert profile["manager"] == "bob@company.com"
    assert profile["employeeType"] == "Full-Time"
    assert profile["costCenter"] == "CC-001"
    assert profile["mobilePhone"] == "+1-555-0101"
    assert profile["employeeNumber"] == "EMP-10001"


def test_parse_result_summary():
    result = ParseResult()
    result.stats["total_rows"] = 100
    result.valid_events = [
        HREvent(employee_id="E1", email="a@b.com", event_type=EventType.HIRE)
    ]
    result.errors = []
    result.warnings = []

    text = result.summary()
    assert "Total rows: 100" in text
    assert "Valid: 1" in text
    assert "Errors: 0" in text
    assert "Warnings: 0" in text