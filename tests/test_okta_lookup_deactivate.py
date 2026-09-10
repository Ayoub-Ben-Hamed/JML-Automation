"""Unit tests for Module 2.B — user lookup and deactivation."""

import pytest
from unittest.mock import MagicMock, patch
from jml.okta_client import (
    OktaClient,
    UserNotFoundError,
    ValidationFailedError,
    AuthenticationError,
)


@pytest.fixture
def mock_session():
    """Patch requests.Session BEFORE the client is created."""
    with patch("jml.okta_client.requests.Session") as mock_cls:
        session = MagicMock()
        mock_cls.return_value = session
        yield session


@pytest.fixture
def client(mock_session):
    """Client is created while the patch is active."""
    return OktaClient(domain="dev-123456.okta.com", api_token="fake-token")


class TestFindUserByLogin:

    def test_find_by_login_found(self, client, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "00uFOUND",
            "status": "ACTIVE",
            "profile": {"login": "alice@company.com"},
        }
        mock_session.request.return_value = mock_resp

        user = client.find_user_by_login("alice@company.com")
        assert user["id"] == "00uFOUND"
        assert user["status"] == "ACTIVE"

    def test_find_by_login_not_found(self, client, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_session.request.return_value = mock_resp

        user = client.find_user_by_login("ghost@company.com")
        assert user is None

    def test_find_by_login_auth_error(self, client, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {
            "errorCode": "E0000011",
            "errorSummary": "Invalid token",
        }
        mock_session.request.return_value = mock_resp

        with pytest.raises(AuthenticationError):
            client.find_user_by_login("any@company.com")


class TestFindUserByEmployeeId:

    def test_search_found_one(self, client, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"id": "00uBYEMPID", "profile": {"login": "bob@company.com"}}
        ]
        mock_session.request.return_value = mock_resp

        user = client.find_user_by_employee_id("EMP-20002")
        assert user["id"] == "00uBYEMPID"

        # Correct way to inspect the call
        args, kwargs = mock_session.request.call_args
        assert kwargs["params"]["search"] == 'profile.employee_id eq "EMP-20002"'

    def test_search_not_found(self, client, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_session.request.return_value = mock_resp

        user = client.find_user_by_employee_id("EMP-NONEXISTENT")
        assert user is None

    def test_search_multiple_matches_raises(self, client, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"id": "00uDUP1"},
            {"id": "00uDUP2"},
        ]
        mock_session.request.return_value = mock_resp

        with pytest.raises(ValidationFailedError) as exc:
            client.find_user_by_employee_id("EMP-DUP")
        assert "Multiple users found" in str(exc.value)


class TestDeactivateUser:

    def test_deactivate_success(self, client, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "00uDEAC",
            "status": "DEPROVISIONED",
        }
        mock_session.request.return_value = mock_resp

        user = client.deactivate_user("00uDEAC")
        assert user["status"] == "DEPROVISIONED"

    def test_deactivate_already_deactivated_is_idempotent(self, client, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {
            "errorCode": "E0000001",
            "errorSummary": "Api validation failed",
            "errorCauses": [{"errorSummary": "This user is already deactivated"}],
        }
        mock_session.request.return_value = mock_resp

        user = client.deactivate_user("00uALREADY")
        assert user["status"] == "DEPROVISIONED"

    def test_deactivate_user_not_found(self, client, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.json.return_value = {
            "errorCode": "E0000007",
            "errorSummary": "Not found",
        }
        mock_session.request.return_value = mock_resp

        with pytest.raises(UserNotFoundError):
            client.deactivate_user("00uGHOST")


class TestActivateUser:

    def test_reactivate_success(self, client, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "00uREHIRE",
            "status": "ACTIVE",
        }
        mock_session.request.return_value = mock_resp

        user = client.activate_user("00uREHIRE")
        assert user["status"] == "ACTIVE"

    def test_reactivate_not_found(self, client, mock_session):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_session.request.return_value = mock_resp

        with pytest.raises(UserNotFoundError):
            client.activate_user("00uDELETED")