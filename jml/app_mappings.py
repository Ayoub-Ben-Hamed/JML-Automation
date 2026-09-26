from dataclasses import dataclass
from typing import Dict,List,Any

@dataclass
class AppRef:
    """Reference to an Okta app. ID is resolved at runtime."""
    name:str
    okta_label:str
    app_id:str = ""
    scim_enabled:bool = True

ROLE_TO_APPS:Dict[str:List[AppRef]]={
    "Software Engineer":[
        AppRef("Slack", "Slack"),
        AppRef("GitHub Enterprise", "GitHub Enterprise"),
        AppRef("Jira", "Jira"),
        AppRef("AWS Console", "AWS Console"),
        AppRef("Google Workspace", "Google Workspace")
    ],
    "Engineering Manager": [
        AppRef("Slack", "Slack"),
        AppRef("Jira", "Jira"),
        AppRef("Confluence", "Confluence"),
        AppRef("BambooHR", "BambooHR"),
        AppRef("GitHub Enterprise", "GitHub Enterprise"),
        AppRef("1Password", "1Password")
    ],
    "Intern": [
        AppRef("Slack", "Slack"),
        AppRef("Jira", "Jira"),
        AppRef("LinkedIn Learning", "LinkedIn Learning"),
        AppRef("GitHub Enterprise", "GitHub Enterprise")
    ],
    "Product Manager": [
        AppRef("Slack", "Slack"),
        AppRef("Jira", "Jira"),
        AppRef("Figma", "Figma"),
        AppRef("Amplitude", "Amplitude"),
        AppRef("Confluence", "Confluence")
    ],
    "Sales Representative": [
        AppRef("Slack", "Slack"),
        AppRef("Salesforce", "Salesforce"),
        AppRef("Outreach", "Outreach"),
        AppRef("Gong", "Gong")
    ]
}