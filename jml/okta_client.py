import logging
import time
from typing import Dict,Any, Optional,List
import requests
from urllib.parse import quote

logger = logging.getLogger("jml.okta")


class OktaAPIError(Exception):
    """Base exception for all Okta API failures."""
    def __init__(self, message: str, status_code: int, error_code: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code

class UserNotFoundError(OktaAPIError):
    pass

class UserAlreadyExistsError(OktaAPIError):
    pass

class ValidationFailedError(OktaAPIError):
    """Raised when Okta rejects the payload (bad email, missing field, etc.)."""
    pass

class AuthenticationError(OktaAPIError):
    """Raised when the API token is invalid, expired, or lacks scope."""
    pass

class RateLimitError(OktaAPIError):
    pass

class OktaClient:
    """Thin, JML-focused wrapper around Okta's Users API.

    Uses a persistent requests.Session for connection pooling.
    Translates HTTP errors into typed exceptions so the caller
    can decide whether to retry, skip, or abort the batch.
    """

    def __init__(self, domain: str, api_token: str):
        domain = (domain or "").strip()
        api_token = (api_token or "").strip()

        # Remove protocol if present
        if domain.startswith("https://"):
            domain = domain[len("https://"):]
        if domain.startswith("http://"):
            domain = domain[len("http://"):]
        domain = domain.rstrip("/")

        self.domain = domain
        self.base_url = f"https://{self.domain}/api/v1"
        self.api_token = api_token

        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"SSWS {self.api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "JMLEngine/1.0",
        })

    # internal methods
    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        """Execute one HTTP request and return the raw response."""
        url = f"{self.base_url}{path}"
        response = self._session.request(method, url, **kwargs)
        self._last_response = response
        return response

    def _handle_error(self, response: requests.Response) -> None:
        try:
            data = response.json()
            error_code = data.get("errorCode")
            summary = data.get("errorSummary", "Unknown Okta error")
        except Exception:
            error_code = None
            summary = response.text or f"HTTP {response.status_code}"

        # Okta sometimes returns 400 for duplicates, not 409
        if response.status_code in (400, 409):
            try:
                causes = [c.get("errorSummary", "") for c in data.get("errorCauses", [])]
                if any("already exists" in c.lower() for c in causes):
                    raise UserAlreadyExistsError(summary, response.status_code, error_code)
            except UserAlreadyExistsError:
                raise
            except Exception:
                pass

        if response.status_code == 404:
            raise UserNotFoundError(summary, response.status_code, error_code)
        if response.status_code == 400:
            causes = []
            if isinstance(data, dict) and "errorCauses" in data:
                causes = [c.get("errorSummary", "") for c in data["errorCauses"] if isinstance(c, dict)]
            if causes:
                summary = f"{summary} ({'; '.join(causes)})"
            raise ValidationFailedError(summary, response.status_code, error_code)
        if response.status_code in (401, 403):
            raise AuthenticationError(summary, response.status_code, error_code)
        if response.status_code == 429:
            raise RateLimitError(summary, response.status_code, error_code)

        raise OktaAPIError(summary, response.status_code, error_code)


    # Module 2.A: Creation
    def create_user(self,profile: Dict[str, Any],activate: bool = True,credentials: Optional[Dict[str, Any]] = None,
                    group_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Create a new Okta user.
        Args:
            profile: Must contain firstName, lastName, email, login.
            activate: True → PROVISIONED/ACTIVE; False → STAGED.
            credentials: Optional password dict. Omit for activation email flow.
            group_ids: Optional list of Okta group IDs to assign on creation.
        """
        payload: Dict[str, Any] = {"profile": profile}
        if credentials:
            payload["credentials"] = credentials
        if group_ids:
            payload["groupIds"] = group_ids

        resp = self._request("POST", "/users", json=payload, params={"activate": str(activate).lower()})

        if resp.status_code == 200:
            user = resp.json()
            logger.info(
                "Created user id=%s login=%s status=%s",
                user.get("id"), profile.get("login"), user.get("status"),
            )
            return user

        self._handle_error(resp)
        return {}

    def create_user_with_retry(self,profile: Dict[str, Any],activate: bool = True,credentials: Optional[Dict[str, Any]] = None,
                               group_ids: Optional[List[str]] = None,max_retries: int = 3) -> Dict[str, Any]:
        """Create user with automatic retry on rate limit (429).

        Sleeps until X-Rate-Limit-Reset before each retry.
        Non-retryable errors bubble up immediately.
        """
        for attempt in range(1, max_retries + 1):
            try:
                return self.create_user(profile, activate, credentials, group_ids)
            except RateLimitError:
                reset = self._rate_limit_reset()
                if reset and attempt < max_retries:
                    sleep_for = max(0, reset - int(time.time()) + 1)
                    logger.warning("Rate limited. Retry %d/%d in %ds", attempt, max_retries, sleep_for)
                    time.sleep(sleep_for)
                else:
                    raise
        return {}

    # Module 2.B: Lookup

    def find_user_by_login(self, login: str) -> Optional[Dict[str, Any]]:
        """Fetch a single user by their login (email) identifier.

        Returns None if the user does not exist.
        Raises AuthenticationError if the token is bad.
        """
        resp = self._request("GET", f"/users/{login}")
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 404:
            return None
        self._handle_error(resp)
        return None

    get_user_by_login = find_user_by_login

    def find_user_by_employee_id(self, employee_id: str) -> Optional[Dict[str, Any]]:
        """Search for a user by custom profile attribute employee_id.

        Uses Okta search syntax: profile.employee_id eq "VALUE".
        Returns the first match or None if no matches.
        Raises if the search returns >1 match (data quality issue).
        """
        emp_id = employee_id.replace('"', '\\"')
        query = f'profile.employee_id eq "{emp_id}"'
        resp = self._request("GET", "/users", params={"search": query, "limit": "2"})

        if resp.status_code != 200:
            self._handle_error(resp)

        users = resp.json()
        if not users:
            return None
        if len(users) > 1:
            ids = [u["id"] for u in users]
            raise ValidationFailedError(
                f"Multiple users found for employee_id={employee_id}: {ids}",
                400,
                "JML_DUPLICATE_EMPLOYEE_ID",
            )
        return users[0]

    def get_user_by_id(self, user_id: str) -> Dict[str, Any]:
        """Fetch a user by their Okta ID (00u...)."""
        resp = self._request("GET", f"/users/{user_id}")
        if resp.status_code == 200:
            return resp.json()
        self._handle_error(resp)
        return {}


    def find_user_by_email_or_employee_id(self, email: str, employee_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Try login first, fall back to employee_id search.

        This is the method your orchestrator should call when it
        receives an HREvent — it covers both Okta-native and HR-native IDs.
        """
        user = self.find_user_by_login(email)
        if user:
            return user
        if employee_id:
            return self.find_user_by_employee_id(employee_id)
        return None

    # Module 2.B: Deactivation / Activation

    def deactivate_user(self, user_id: str) -> Dict[str, Any]:
        resp = self._request("POST", f"/users/{user_id}/lifecycle/deactivate")
        if resp.status_code == 200:
            user = resp.json()
            if not user.get("status"):
                user = self.get_user_by_id(user_id)
            logger.info("Deactivated user id=%s status=%s", user_id, user.get("status"))
            return user
        if resp.status_code in (400, 404):
            try:
                data = resp.json()
                causes = [c.get("errorSummary", "") for c in data.get("errorCauses", [])]
                if any("already deactivated" in c.lower() for c in causes):
                    logger.info("User %s already deactivated. Fetching current state.", user_id)
                    try:
                        return self.get_user_by_id(user_id)
                    except Exception:
                        return {"id": user_id, "status": "DEPROVISIONED"}
            except Exception:
                pass
            try:
                user = self.get_user_by_id(user_id)
                if user and user.get("status") == "DEPROVISIONED":
                    logger.info("User %s already deactivated. Returning current state.", user_id)
                    return user
            except Exception:
                pass
        self._handle_error(resp)
        return {}


    def activate_user(self, user_id: str) -> Dict[str, Any]:
        resp = self._request("POST", f"/users/{user_id}/lifecycle/activate")
        if resp.status_code == 200:
            user = resp.json()
            if not user.get("status"):
                user = self.get_user_by_id(user_id)
            logger.info("Reactivated user id=%s status=%s", user_id, user.get("status"))
            return user
        if resp.status_code == 400:
            try:
                data = resp.json()
                causes = [c.get("errorSummary", "") for c in data.get("errorCauses", [])]
                if any("already activated" in c.lower() or "already active" in c.lower() for c in causes):
                    logger.info("User %s already active. Fetching current state.", user_id)
                    try:
                        return self.get_user_by_id(user_id)
                    except Exception:
                        return {"id": user_id, "status": "ACTIVE"}
            except Exception:
                pass
        self._handle_error(resp)
        return {}

    def delete_user(self, user_id: str) -> None:
        """Permanently delete a user from Okta. User must be deprovisioned first (or staged)."""
        resp = self._request("DELETE", f"/users/{user_id}")
        if resp.status_code not in (200, 204, 404):
            self._handle_error(resp)


    def update_user(self, user_id: str, profile: Dict[str, Any]) -> Dict[str, Any]:
        resp = self._request("POST", f"/users/{user_id}", json={"profile": profile})
        resp.raise_for_status()
        return resp.json()


    # Helpers

    def _rate_limit_reset(self) -> Optional[int]:
        """Extract Unix timestamp from the X-Rate-Limit-Reset header."""
        if hasattr(self, "_last_response"):
            val = self._last_response.headers.get("X-Rate-Limit-Reset")
            return int(val) if val else None
        return None
    _get_rate_limit_reset = _rate_limit_reset