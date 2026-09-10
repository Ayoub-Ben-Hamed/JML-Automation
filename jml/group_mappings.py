from dataclasses import dataclass
from typing import List,Set

@dataclass(frozen=True)
class RoleKey:
    department: str
    role: str
    location: str = "Any"

ROLE_TO_GROUPS:dict[RoleKey,List[str]]={
    RoleKey("Engineering","Software Engineer","Any"):[
        "All-Employees",
        "Engineering",
        "Engineering-Individual-Contributors",
        "GitHub-Users",
        "Slack-Engineering",
        "Jira-Users",
        "AWS-Dev-Access"
    ],
    RoleKey("Engineering", "Senior Software Engineer", "Any"): [
        "All-Employees",
        "Engineering",
        "Engineering-Individual-Contributors",
        "GitHub-Users",
        "Slack-Engineering",
        "Jira-Users",
        "AWS-Dev-Access",
        "Senior-IC-Perks"
    ],
    RoleKey("Engineering", "Engineering Manager", "Any"): [
        "All-Employees",
        "Engineering",
        "Engineering-Managers",
        "GitHub-Users",
        "Slack-Engineering",
        "Jira-Users",
        "AWS-Dev-Access",
        "Manager-Tools",
        "Bonusly-Admins"
    ],
    RoleKey("Engineering", "Staff Engineer", "Any"): [
        "All-Employees",
        "Engineering",
        "Engineering-Individual-Contributors",
        "GitHub-Users",
        "Slack-Engineering",
        "Jira-Users",
        "AWS-Prod-Access",
        "Senior-IC-Perks",
        "Architecture-Review"
    ],
    RoleKey("Product", "Product Manager", "Any"): [
        "All-Employees",
        "Product",
        "Slack-Product",
        "Jira-Users",
        "Figma-Users",
        "Amplitude-Users"
    ],
    RoleKey("Sales", "Account Executive", "Any"): [
        "All-Employees",
        "Sales",
        "Slack-Sales",
        "Salesforce-Users",
        "Outreach-Users",
        "Gong-Users"
    ],
    RoleKey("Sales", "Sales Manager", "Any"): [
        "All-Employees",
        "Sales",
        "Sales-Managers",
        "Slack-Sales",
        "Salesforce-Users",
        "Outreach-Users",
        "Gong-Users",
        "Manager-Tools"
    ],
    RoleKey("HR", "HR Generalist", "Any"): [
        "All-Employees",
        "HR",
        "Slack-HR",
        "BambooHR-Users",
        "Manager-Tools"
    ],
    RoleKey("Security", "Security Engineer", "Any"): [
        "All-Employees",
        "Security",
        "Engineering",
        "GitHub-Users",
        "Slack-Security",
        "AWS-Prod-Access",
        "Splunk-Users",
        "PagerDuty-Users"
    ],
    RoleKey("Engineering", "Intern", "Any"): [
        "All-Employees",
        "Engineering",
        "GitHub-Users",
        "Slack-Engineering",
        "Interns-2026"
    ]
}

def resolve_groups(department:str,role:str,location:str="None")->Set[str]:
    key=RoleKey(department,role,location)
    groups=set(ROLE_TO_GROUPS.get(key,[]))
    if not groups:
        fallback=RoleKey(department,role,"Any")
        groups=set(ROLE_TO_GROUPS.get(fallback,[]))
    return groups