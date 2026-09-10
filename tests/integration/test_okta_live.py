"""Integration tests against a live Okta developer tenant.

Requires environment variables:
  OKTA_DOMAIN    (e.g., dev-123456.okta.com)
  OKTA_API_TOKEN (SSWS token from Security > API > Tokens)

Run with:
  pytest tests/integration/test_okta_live.py -v

If Module 3 tests fail with 403:
  Your API token lacks Group Admin rights. In Okta Admin Console,
  go to Security > Administrators and assign Super Admin to the
  user who owns this token.
"""

import os
import uuid
from datetime import date
from typing import Generator

import pytest
from dotenv import load_dotenv

from jml.models import EventType
from jml.parsers import HRCSVParser
from jml.validators import HRValidator
from jml.okta_client import OktaClient, AuthenticationError
from jml.group_manager import GroupManager
from jml.group_mappings import resolve_groups
from jml.group_diff import diff_groups

load_dotenv()

pytestmark = pytest.mark.integration

TEST_KNOWN_ROLES = {
    "Software Engineer", "Senior Software Engineer", "Staff Engineer",
    "Engineering Manager", "Product Manager", "Designer",
    "Sales Representative", "Account Executive", "Sales Manager",
    "HR Generalist", "HR Manager", "Finance Analyst", "CFO",
    "DevOps Engineer", "Security Engineer", "Data Scientist",
    "Intern", "Contractor",
}
TEST_KNOWN_DEPARTMENTS = {
    "Engineering", "Product", "Design", "Sales", "Marketing",
    "HR", "Finance", "Legal", "IT", "Security", "Operations",
}


def _skip_if_no_creds():
    domain = os.getenv("OKTA_DOMAIN", "").strip()
    token = os.getenv("OKTA_API_TOKEN", "").strip()
    if not domain or not token:
        pytest.skip(
            "OKTA_DOMAIN and OKTA_API_TOKEN not set in environment",
            allow_module_level=True,
        )


_skip_if_no_creds()


@pytest.fixture(scope="module")
def okta_domain():
    return os.getenv("OKTA_DOMAIN", "").strip()


@pytest.fixture(scope="module")
def api_token():
    return os.getenv("OKTA_API_TOKEN", "").strip()


@pytest.fixture(scope="module")
def okta_client(okta_domain, api_token):
    return OktaClient(domain=okta_domain, api_token=api_token)


@pytest.fixture(scope="module")
def group_manager(okta_domain, api_token):
    return GroupManager(domain=okta_domain, api_token=api_token)


@pytest.fixture
def unique_email():
    return f"jml-test-{uuid.uuid4().hex[:8]}@example.com"


@pytest.fixture(autouse=True)
def cleanup_users(okta_client) -> Generator[list, None, None]:
    created = []
    yield created
    for user_id in created:
        try:
            okta_client.deactivate_user(user_id)
        except Exception:
            pass
        try:
            okta_client.delete_user(user_id)
        except Exception:
            pass


# ═════════════════════════════════════════════════════════════════════════════
# TOKEN & PERMISSION HEALTH CHECKS
# ═════════════════════════════════════════════════════════════════════════════

class TestTokenHealth:
    def test_api_token_can_authenticate(self, okta_client):
        try:
            user = okta_client.find_user_by_login("nonexistent-user@example.com")
            assert user is None
        except AuthenticationError as exc:
            pytest.fail(f"Okta API token is invalid or expired. Regenerate it. Detail: {exc}")


@pytest.fixture(scope="module")
def _group_permissions_ok(group_manager):
    """Skip Module 3 entirely if token lacks group admin rights."""
    try:
        group_manager.find_group_by_name("Everyone")
    except AuthenticationError:
        pytest.skip(
            "Okta API token lacks Group Admin permissions. "
            "In Okta Admin Console: Security > Administrators > "
            "assign Super Admin to the token owner.",
            allow_module_level=True,
        )


# ═════════════════════════════════════════════════════════════════════════════
# MODULE 1 — Data Layer
# ═════════════════════════════════════════════════════════════════════════════

class TestModule1DataLayer:
    def test_parse_valid_hire_csv(self, tmp_path):
        csv_content = """employee_id,email,event_type,department,role,first_name,last_name,manager_email,start_date,end_date,old_department,old_role,employee_type,cost_center,location,phone,notes
EMP-10001,jml-hire-1@example.com,HIRE,Engineering,Software Engineer,Alice,Chen,manager@example.com,2026-09-01,,,,Full-Time,CC-001,SF,+1-555-0001,Integration test
EMP-10002,jml-move-1@example.com,MOVE,Product,Product Manager,Bob,Smith,manager@example.com,,,Engineering,Software Engineer,Full-Time,CC-002,SF,+1-555-0002,Role change
EMP-10003,jml-term-1@example.com,TERMINATE,Engineering,Software Engineer,Charlie,Davis,,,2026-08-27,,,Full-Time,CC-003,SF,+1-555-0003,Leaving"""
        csv_file = tmp_path / "hr_integration.csv"
        csv_file.write_text(csv_content)

        parser = HRCSVParser(
            validator=HRValidator(
                known_roles=TEST_KNOWN_ROLES,
                known_departments=TEST_KNOWN_DEPARTMENTS,
            )
        )
        result = parser.parse(str(csv_file))

        assert result.valid_count == 3
        assert result.error_count == 0

        hires = result.get_event_by_type(EventType.HIRE)
        assert len(hires) == 1
        assert hires[0].email == "jml-hire-1@example.com"
        assert hires[0].first_name == "Alice"
        assert hires[0].last_name == "Chen"

        moves = result.get_event_by_type(EventType.MOVE)
        assert len(moves) == 1
        assert moves[0].old_department == "Engineering"

    def test_parse_invalid_row_produces_error(self, tmp_path):
        csv_content = """employee_id,email,event_type,department,role,first_name,last_name,manager_email,start_date
EMP-99999,not-an-email,HIRE,Engineering,Software Engineer,Test,User,,2026-09-01"""
        csv_file = tmp_path / "hr_bad.csv"
        csv_file.write_text(csv_content)

        parser = HRCSVParser(
            validator=HRValidator(
                known_roles=TEST_KNOWN_ROLES,
                known_departments=TEST_KNOWN_DEPARTMENTS,
            )
        )
        result = parser.parse(str(csv_file))

        assert result.valid_count == 0
        assert result.error_count >= 1
        assert any(err.field == "email" for err in result.errors)


# ═════════════════════════════════════════════════════════════════════════════
# MODULE 2 — User Lifecycle
# ═════════════════════════════════════════════════════════════════════════════

class TestModule2UserCreation:
    def test_create_user_minimal(self, okta_client, unique_email, cleanup_users):
        profile = {
            "firstName": "Integration",
            "lastName": "Test",
            "email": unique_email,
            "login": unique_email,
        }
        user = okta_client.create_user(profile=profile, activate=True)
        cleanup_users.append(user["id"])

        assert user["status"] == "PROVISIONED"
        assert user["profile"]["login"] == unique_email
        assert user["id"].startswith("00u")

    def test_create_user_full_profile(self, okta_client, unique_email, cleanup_users):
        profile = {
            "firstName": "Alice",
            "lastName": "Integration",
            "email": unique_email,
            "login": unique_email,
            "department": "Engineering",
            "title": "Software Engineer",
            "costCenter": "CC-INT-001",
            "mobilePhone": "+1-555-9999",
        }
        user = okta_client.create_user(profile=profile, activate=True)
        cleanup_users.append(user["id"])

        assert user["profile"]["department"] == "Engineering"
        assert user["profile"]["title"] == "Software Engineer"

    def test_create_user_staged_future_date(self, okta_client, unique_email, cleanup_users):
        profile = {
            "firstName": "Future",
            "lastName": "Hire",
            "email": unique_email,
            "login": unique_email,
        }
        user = okta_client.create_user(profile=profile, activate=False)
        cleanup_users.append(user["id"])

        assert user["status"] == "STAGED"

    def test_find_user_by_login_found(self, okta_client, unique_email, cleanup_users):
        profile = {
            "firstName": "Findable",
            "lastName": "User",
            "email": unique_email,
            "login": unique_email,
        }
        created = okta_client.create_user(profile=profile, activate=True)
        cleanup_users.append(created["id"])

        found = okta_client.find_user_by_login(unique_email)
        assert found is not None
        assert found["id"] == created["id"]
        assert found["status"] == "PROVISIONED"

    def test_find_user_by_login_not_found(self, okta_client):
        ghost_email = f"ghost-{uuid.uuid4().hex}@example.com"
        found = okta_client.find_user_by_login(ghost_email)
        assert found is None

    def test_deactivate_user(self, okta_client, unique_email, cleanup_users):
        profile = {
            "firstName": "Leaver",
            "lastName": "Test",
            "email": unique_email,
            "login": unique_email,
        }
        user = okta_client.create_user(profile=profile, activate=True)
        cleanup_users.append(user["id"])

        deactivated = okta_client.deactivate_user(user["id"])
        assert deactivated["status"] == "DEPROVISIONED"

        again = okta_client.deactivate_user(user["id"])
        assert again["status"] == "DEPROVISIONED"

    def test_reactivate_user(self, okta_client, unique_email, cleanup_users):
        profile = {
            "firstName": "Boomerang",
            "lastName": "Test",
            "email": unique_email,
            "login": unique_email,
        }
        user = okta_client.create_user(profile=profile, activate=True)
        cleanup_users.append(user["id"])

        okta_client.deactivate_user(user["id"])
        reactivated = okta_client.activate_user(user["id"])
        assert reactivated["status"] in ("ACTIVE", "PROVISIONED")

    def test_create_duplicate_raises_409(self, okta_client, unique_email, cleanup_users):
        from jml.okta_client import UserAlreadyExistsError

        profile = {
            "firstName": "Dup",
            "lastName": "Test",
            "email": unique_email,
            "login": unique_email,
        }
        user = okta_client.create_user(profile=profile, activate=True)
        cleanup_users.append(user["id"])

        with pytest.raises(UserAlreadyExistsError):
            okta_client.create_user(profile=profile, activate=True)


class TestModule2LookupByEmployeeId:
    def test_find_by_employee_id(self, okta_client, unique_email, cleanup_users):
        emp_id = f"EMP-{uuid.uuid4().hex[:6].upper()}"
        profile = {
            "firstName": "Searchable",
            "lastName": "ByEmpId",
            "email": unique_email,
            "login": unique_email,
            "employeeNumber": emp_id,
        }
        try:
            user = okta_client.create_user(profile=profile, activate=True)
            cleanup_users.append(user["id"])
            found = okta_client.find_user_by_employee_id(emp_id)
            assert found is not None
            assert found["id"] == user["id"]
        except Exception as exc:
            pytest.skip(f"employeeNumber search not configured in Okta schema: {exc}")


# ═════════════════════════════════════════════════════════════════════════════
# MODULE 3 — Group Management
# ═════════════════════════════════════════════════════════════════════════════

class TestModule3GroupManagement:
    pytestmark = pytest.mark.usefixtures("_group_permissions_ok")

    def test_find_group_by_name(self, group_manager):
        group = group_manager.find_group_by_name("Everyone")
        assert group is not None
        assert group["profile"]["name"] == "Everyone"

    def test_find_group_not_found(self, group_manager):
        group = group_manager.find_group_by_name("This-Group-Does-Not-Exist-12345")
        assert group is None

    def test_create_and_find_group(self, group_manager, okta_client):
        group_name = f"JML-Test-Group-{uuid.uuid4().hex[:8]}"

        created = group_manager.create_group(group_name, "Created by integration test")
        assert created["id"].startswith("00g")
        assert created["profile"]["name"] == group_name

        found = group_manager.find_group_by_name(group_name)
        assert found is not None
        assert found["id"] == created["id"]

    def test_get_or_create_group_idempotent(self, group_manager):
        group_name = f"JML-Idempotent-{uuid.uuid4().hex[:8]}"

        first = group_manager.get_or_create_group(group_name)
        second = group_manager.get_or_create_group(group_name)

        assert first["id"] == second["id"]

    def test_add_and_remove_user_from_group(self, okta_client, group_manager, unique_email, cleanup_users):
        profile = {
            "firstName": "Groupie",
            "lastName": "Test",
            "email": unique_email,
            "login": unique_email,
        }
        user = okta_client.create_user(profile=profile, activate=True)
        cleanup_users.append(user["id"])

        group_name = f"JML-Membership-{uuid.uuid4().hex[:8]}"
        group = group_manager.create_group(group_name)
        group_id = group["id"]

        group_manager.add_user_to_group(user["id"], group_id)

        resp = group_manager.session.get(
            f"{group_manager.base_url}/groups/{group_id}/users"
        )
        resp.raise_for_status()
        member_ids = [m["id"] for m in resp.json()]
        assert user["id"] in member_ids

        group_manager.remove_user_from_group(user["id"], group_id)

        resp = group_manager.session.get(
            f"{group_manager.base_url}/groups/{group_id}/users"
        )
        resp.raise_for_status()
        member_ids = [m["id"] for m in resp.json()]
        assert user["id"] not in member_ids

    def test_group_diff_end_to_end(self, okta_client, group_manager, unique_email, cleanup_users):
        profile = {
            "firstName": "Mover",
            "lastName": "Test",
            "email": unique_email,
            "login": unique_email,
        }
        user = okta_client.create_user(profile=profile, activate=True)
        cleanup_users.append(user["id"])

        old_groups = resolve_groups("Engineering", "Software Engineer")
        new_groups = resolve_groups("Engineering", "Senior Software Engineer")

        to_remove, to_add, preserved = diff_groups(old_groups, new_groups)

        group_id_map = {}
        for g_name in old_groups | new_groups:
            g = group_manager.get_or_create_group(g_name, "JML test group")
            group_id_map[g_name] = g["id"]

        for g_name in old_groups:
            group_manager.add_user_to_group(user["id"], group_id_map[g_name])

        for g_name in to_remove:
            group_manager.remove_user_from_group(user["id"], group_id_map[g_name])
        for g_name in to_add:
            group_manager.add_user_to_group(user["id"], group_id_map[g_name])

        for g_name in new_groups:
            gid = group_id_map[g_name]
            resp = group_manager.session.get(f"{group_manager.base_url}/groups/{gid}/users")
            resp.raise_for_status()
            ids = [m["id"] for m in resp.json()]
            assert user["id"] in ids, f"User should be in {g_name}"

        for g_name in to_remove:
            gid = group_id_map[g_name]
            resp = group_manager.session.get(f"{group_manager.base_url}/groups/{gid}/users")
            resp.raise_for_status()
            ids = [m["id"] for m in resp.json()]
            assert user["id"] not in ids, f"User should NOT be in {g_name}"

        for g_name in preserved:
            gid = group_id_map[g_name]
            resp = group_manager.session.get(f"{group_manager.base_url}/groups/{gid}/users")
            resp.raise_for_status()
            ids = [m["id"] for m in resp.json()]
            assert user["id"] in ids, f"User should still be in preserved group {g_name}"


# ═════════════════════════════════════════════════════════════════════════════
# END-TO-END
# ═════════════════════════════════════════════════════════════════════════════

class TestEndToEndPipeline:
    pytestmark = pytest.mark.usefixtures("_group_permissions_ok")

    def test_full_hire_pipeline(self, tmp_path, okta_client, group_manager, cleanup_users):
        unique = uuid.uuid4().hex[:8]
        email = f"jml-e2e-{unique}@example.com"

        csv_content = f"""employee_id,email,event_type,department,role,first_name,last_name,manager_email,start_date
EMP-12345,{email},HIRE,Engineering,Software Engineer,End,ToEnd,manager@example.com,2026-09-01"""
        csv_file = tmp_path / "e2e_hire.csv"
        csv_file.write_text(csv_content)

        parser = HRCSVParser(
            validator=HRValidator(
                known_roles=TEST_KNOWN_ROLES,
                known_departments=TEST_KNOWN_DEPARTMENTS,
            )
        )
        result = parser.parse(str(csv_file))
        assert result.valid_count == 1
        event = result.valid_events[0]

        # Ensure firstName/lastName are in the profile
        profile = event.to_okta_profile()
        profile.setdefault("firstName", event.first_name or "Unknown")
        profile.setdefault("lastName", event.last_name or "Unknown")

        user = okta_client.create_user(profile=profile, activate=True)
        cleanup_users.append(user["id"])
        assert user["status"] == "PROVISIONED"

        groups = resolve_groups(event.department, event.role)
        group_id_map = {}
        for g_name in groups:
            g = group_manager.get_or_create_group(g_name, "JML auto-group")
            group_id_map[g_name] = g["id"]

        for g_name in groups:
            group_manager.add_user_to_group(user["id"], group_id_map[g_name])

        eng_gid = group_id_map["Engineering"]
        resp = group_manager.session.get(f"{group_manager.base_url}/groups/{eng_gid}/users")
        resp.raise_for_status()
        ids = [m["id"] for m in resp.json()]
        assert user["id"] in ids