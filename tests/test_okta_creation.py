"""
Unit tests for Module 2.A — Okta user creation.

Mocks the HTTP layer so these tests run without a live Okta tenant.
Verifies correct payloads, headers, and error translation.
"""

import json
import pytest
import time
from unittest.mock import MagicMock, patch
from jml.okta_client import (
    OktaClient,
    OktaAPIError,
    UserAlreadyExistsError,
    ValidationFailedError,
    AuthenticationError,
    RateLimitError,
)


@pytest.fixture
def client(mock_session):
    """Return an OktaClient wired to a fake dev org."""
    return OktaClient(domain="dev-123456.okta.com", api_token="fake-token-123")

@pytest.fixture
def mock_session():
    """Patch requests.Session so no real HTTP leaves the box."""
    with patch("jml.okta_client.requests.Session") as mock_cls:
        session = MagicMock()
        mock_cls.return_value = session
        yield session

class TestCreateUser:
    """Covers the happy path and every failure mode for POST /api/v1/users."""

    def test_create_user_success_provisioned(self, client, mock_session):
        """A basic HIRE with activate=True should return the user object."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "00uNEWUSER123",
            "status": "PROVISIONED",
            "profile": {
                "login": "alice@company.com",
                "email": "alice@company.com",
                "firstName": "Alice",
                "lastName": "Chen",
            },
        }
        mock_session.request.return_value = mock_response

        result = client.create_user(
            profile={
                "firstName": "Alice",
                "lastName": "Chen",
                "email": "alice@company.com",
                "login": "alice@company.com",
            },
            activate=True,
        )

        assert result["id"] == "00uNEWUSER123"
        assert result["status"] == "PROVISIONED"

        call_args = mock_session.request.call_args
        assert call_args[0][0] == "POST"
        assert "users" in call_args[0][1]
        assert call_args[1]["params"]["activate"] == "true"
        payload = call_args[1]["json"]
        assert payload["profile"]["login"] == "alice@company.com"

    def test_create_user_success_staged_future_hire(self, client, mock_session):
        """A future-dated HIRE with activate=False lands in STAGED."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "00uSTAGED456",
            "status": "STAGED",
            "profile": {"login": "bob@company.com"},
        }
        mock_session.request.return_value = mock_response

        result = client.create_user(
            profile={
                "firstName": "Bob",
                "lastName": "Smith",
                "email": "bob@company.com",
                "login": "bob@company.com",
            },
            activate=False,
        )

        assert result["status"] == "STAGED"
        call_args = mock_session.request.call_args
        assert call_args[0][0] == "POST"
        args, kwargs = call_args
        assert kwargs.get("params", {}).get("activate") == "false"

    def test_create_user_with_groups(self, client, mock_session):
        """Passing group_ids should embed them in the JSON payload."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "00uGROUPS", "status": "ACTIVE"}
        mock_session.request.return_value = mock_response

        client.create_user(
            profile={"firstName": "X", "lastName": "Y", "email": "x@y.com", "login": "x@y.com"},
            group_ids=["00gEngineering", "00gAllUsers"],
        )

        payload = mock_session.request.call_args[1]["json"]
        assert payload["groupIds"] == ["00gEngineering", "00gAllUsers"]

    def test_create_user_already_exists_409(self, client, mock_session):
        """Duplicate login must raise UserAlreadyExistsError so the orchestrator
        can decide whether to REHIRE or skip."""
        mock_response = MagicMock()
        mock_response.status_code = 409
        mock_response.json.return_value = {
            "errorCode": "E0000001",
            "errorSummary": "An object with this field already exists",
            "errorCauses": [{"errorSummary": "login: already exists"}],
        }
        mock_session.request.return_value = mock_response

        with pytest.raises(UserAlreadyExistsError) as exc:
            client.create_user(profile={"login": "dup@company.com"})

        assert exc.value.status_code == 409
        assert "already exists" in str(exc.value)

    def test_create_user_invalid_email_400(self, client, mock_session):
        """Malformed email should raise ValidationFailedError."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "errorCode": "E0000001",
            "errorSummary": "Api validation failed: login",
            "errorCauses": [{"errorSummary": "login: valid email format required"}],
        }
        mock_session.request.return_value = mock_response

        with pytest.raises(ValidationFailedError) as exc:
            client.create_user(profile={"login": "not-an-email"})

        assert exc.value.status_code == 400

    def test_create_user_auth_error_401(self, client, mock_session):
        """Bad token should raise AuthenticationError to halt the batch."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {
            "errorCode": "E0000011",
            "errorSummary": "Invalid token provided",
        }
        mock_session.request.return_value = mock_response

        with pytest.raises(AuthenticationError):
            client.create_user(profile={"login": "x@y.com"})

    def test_create_user_rate_limit_429(self, client, mock_session):
        """429 should raise RateLimitError so the retry wrapper can catch it."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"X-Rate-Limit-Reset": str(int(time.time()) + 5)}
        mock_response.json.return_value = {
            "errorCode": "E0000047",
            "errorSummary": "API call exceeded rate limit",
        }
        mock_session.request.return_value = mock_response

        with pytest.raises(RateLimitError):
            client.create_user(profile={"login": "x@y.com"})

    def test_create_user_with_retry_succeeds_on_second_attempt(self, client, mock_session):
        """Retry wrapper should sleep on 429 then succeed."""
        fail = MagicMock()
        fail.status_code = 429
        fail.headers = {"X-Rate-Limit-Reset": str(int(time.time()) - 1)}  # already expired
        fail.json.return_value = {"errorCode": "E0000047", "errorSummary": "rate limit"}

        success = MagicMock()
        success.status_code = 200
        success.json.return_value = {"id": "00uRETRY", "status": "PROVISIONED"}

        mock_session.request.side_effect = [fail, success]

        with patch("jml.okta_client.time.sleep"):
            # Also patch the helper so it returns a past timestamp
            with patch.object(client, "_get_rate_limit_reset", return_value=int(time.time()) - 1):
                result = client.create_user_with_retry(
                    profile={"firstName": "A", "lastName": "B", "email": "a@b.com", "login": "a@b.com"}
                )

        assert result["id"] == "00uRETRY"
        assert mock_session.request.call_count == 2


class TestGetUserByLogin:
    """Covers the pre-flight lookup used to avoid duplicate creation."""

    def test_get_user_found(self, client, mock_session):
        """Existing user should return the full user dict."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "00uEXIST",
            "status": "ACTIVE",
            "profile": {"login": "alice@company.com"},
        }
        mock_session.request.return_value = mock_response

        user = client.get_user_by_login("alice@company.com")
        assert user["id"] == "00uEXIST"
        assert user["status"] == "ACTIVE"

    def test_get_user_not_found(self, client, mock_session):
        """Missing user should return None, not raise."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_session.request.return_value = mock_response

        user = client.get_user_by_login("ghost@company.com")
        assert user is None