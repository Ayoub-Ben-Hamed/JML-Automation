import requests

def trigger_workflow(webhook_url: str, user_id: str, role: str):
    """Trigger an Okta Workflow via webhook."""
    resp = requests.post(
        webhook_url,
        json={"user_id": user_id, "role": role},
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()