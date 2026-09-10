"""One-time setup: bind apps to groups in Okta.
Run this after creating your groups and installing apps"""

from jml.group_manager import GroupManager
from jml.app_manager import AppManager
from jml.app_mappings import ROLE_TO_APPS
import logging

def setup_app_group_bindings(app_manager:AppManager,group_manager:GroupManager):
    """Map apps to their logical groups. Run once per environment"""
    bindings=[
        ("Slack", "All-Employees"),
        ("Slack","Engineering"),
        ("Slack", "Product"),
        ("Slack", "Sales"),
        ("GitHub Enterprise", "Engineering"),
        ("GitHub Enterprise", "Engineering-Individual-Contributors"),
        ("Jira", "Engineering"),
        ("Jira", "Product"),
        ("Jira", "Interns-2026"),
        ("AWS Console", "Engineering"),
        ("AWS Console", "Engineering-Managers"),
        ("Confluence", "Engineering-Managers"),
        ("Confluence", "Product"),
        ("BambooHR", "HR"),
        ("BambooHR", "Engineering-Managers"),
        ("Salesforce", "Sales"),
        ("Salesforce", "Sales-Managers")
    ]
    for app_label,group_name in bindings:
        app=app_manager.find_app_by_label(app_label)
        if not app:
            logging.warning("App with label ' %s ' not fount !", app_label)
            continue
        group=GroupManager.find_group_by_name(group_name)
        if not group:
            logging.warning("Group ' %s ' not fount !", group_name)
            continue
        app_manager.assign_app_to_group(app["id"],group["id"])
        logger.info("Bound %s -> %s", app_label, group_name)