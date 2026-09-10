"""Unit tests for the per-row validation engine."""

import pytest
from jml.models import EventType, ValidationSeverity
from jml.validators import HRValidator


@pytest.fixture
def validator():
    """Validator with a small known-role set for deterministic tests."""
    return HRValidator(
        known_roles={"Software Engineer", "Manager"},
        known_departments={"Engineering", "Sales"},
        strict_mode=False,
    )


def test_valid_hire_passes(validator):
    """A clean HIRE row with all required fields should produce zero errors."""
    row = {
        "employee_id": "EMP-10001",
        "email": "alice@company.com",
        "event_type": "HIRE",
        "department": "Engineering",
        "role": "Software Engineer",
        "start_date": "2026-09-01",
    }
    event, issues = validator.validate(row, line_number=2)
    assert event is not None
    assert event.event_type == EventType.HIRE
    assert len([i for i in issues if i.severity == ValidationSeverity.ERROR]) == 0


def test_missing_required_field_fails(validator):
    """A HIRE without start_date should be rejected."""
    row = {
        "employee_id": "EMP-10002",
        "email": "bob@company.com",
        "event_type": "HIRE",
        "department": "Engineering",
        "role": "Software Engineer",
        "start_date": "",
    }
    event, issues = validator.validate(row, line_number=3)
    assert event is None
    assert any(i.field == "start_date" for i in issues)


def test_invalid_email_fails(validator):
    """A malformed email should be caught before hitting Okta."""
    row = {
        "employee_id": "EMP-10003",
        "email": "not-an-email",
        "event_type": "HIRE",
        "department": "Engineering",
        "role": "Software Engineer",
        "start_date": "2026-09-01",
    }
    event, issues = validator.validate(row, line_number=4)
    assert event is None
    assert any("Invalid format" in i.message for i in issues)


def test_move_with_no_change_warns(validator):
    """A MOVE where old and new values are identical should warn, not error."""
    row = {
        "employee_id": "EMP-10004",
        "email": "charlie@company.com",
        "event_type": "MOVE",
        "department": "Engineering",
        "role": "Software Engineer",
        "old_department": "Engineering",
        "old_role": "Software Engineer",
    }
    event, issues = validator.validate(row, line_number=5)
    assert event is not None  # Not fatal
    assert any("no change" in i.message.lower() for i in issues)