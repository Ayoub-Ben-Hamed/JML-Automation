"""JML HIRE processor — bridges the data layer to the Okta API."""

from typing import Dict,Any
import logging
from datetime import date
from jml.models import HREvent, EventType
from jml.okta_client import OktaClient, UserAlreadyExistsError


logger=logging.getLogger("jml.hire")
class HireProcessor:
    """Converts validated HREvent objects into Okta user records."""

    def __init__(self, okta_client: OktaClient):
        self.okta = okta_client

    def process(self, event: HREvent) -> Dict[str, Any]:
        """Process a single HIRE event.

        1. Check if user already exists (duplicate email).
        2. If deprovisioned → this should have been a REHIRE, log warning.
        3. If active → skip, log warning.
        4. Otherwise → create user with appropriate activation strategy.
        """
        if event.event_type != EventType.HIRE:
            raise ValueError(f"Expected HIRE, got {event.event_type.value}")

        existing = self.okta.get_user_by_login(event.email)

        if existing:
            status = existing.get("status")
            if status == "DEPROVISIONED":
                logger.warning(
                    "HIRE for deprovisioned user %s. Consider REHIRE instead.",
                    event.email,
                )
                raise UserAlreadyExistsError(
                    f"User {event.email} exists but is DEPROVISIONED. "
                    "Convert event to REHIRE.",
                    409,
                    "JML_DUPLICATE_DEPROVISIONED",
                )
            if status in ("ACTIVE", "PROVISIONED", "STAGED"):
                logger.warning(
                    "HIRE skipped: user %s already exists with status %s",
                    event.email, status,
                )
                raise UserAlreadyExistsError(
                    f"User {event.email} already exists with status {status}.",
                    409,
                    "JML_DUPLICATE_ACTIVE",
                )

        profile = event.to_okta_profile()

        # Ensure Okta-required fields are present
        for required in ("firstName", "lastName", "email", "login"):
            if not profile.get(required):
                raise ValueError(
                    f"HIRE event missing required profile field: {required}"
                )

        # Decide activation strategy based on start date
        activate = True
        if event.start_date and event.start_date > date.today():
            activate = False
            logger.info(
                "Future-dated hire %s (starts %s). Creating as STAGED.",
                event.email, event.start_date,
            )

        return self.okta.create_user_with_retry(profile=profile, activate=activate)