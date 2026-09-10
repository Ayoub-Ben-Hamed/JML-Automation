from jml.models import HREvent, EventType
from jml.okta_client import OktaClient
from jml.group_manager import GroupManager
from jml.app_manager import AppManager
from jml.group_mappings import resolve_groups
from jml.group_diff import diff_groups


class JMLProcessor:
    """Orchestrates HIRE, MOVE, and TERMINATE through groups only.
    App provisioning is a side effect of group membership."""
    
    def __init__(
        self,
        okta_client: OktaClient,
        group_manager: GroupManager,
        app_manager: AppManager,
    ):
        self.okta = okta_client
        self.groups = group_manager
        self.apps = app_manager
    
    def process_hire(self, event: HREvent):
        """Create user, add to role groups, let Okta provision apps."""
        existing = self.okta.find_user_by_login(event.email)
        if existing:
            raise ValueError(f"User {event.email} already exists")
        
        user = self.okta.create_user(
            profile=event.to_okta_profile(),
            activate=event.start_date is None or event.start_date <= date.today(),
        )
        
        target_groups = resolve_groups(event.department, event.role)
        for g_name in target_groups:
            group = self.groups.get_or_create_group(g_name)
            self.groups.add_user_to_group(user["id"], group["id"])
        
        return user
    
    def process_move(self, event: HREvent):
        """Diff old vs new groups, apply changes, apps follow automatically."""
        user = self.okta.find_user_by_login(event.email)
        if not user:
            raise ValueError(f"User {event.email} not found")
        
        old_groups = resolve_groups(event.old_department, event.old_role)
        new_groups = resolve_groups(event.department, event.role)
        to_remove, to_add, _ = diff_groups(old_groups, new_groups)
        
        for g_name in to_remove:
            g = self.groups.find_group_by_name(g_name)
            if g:
                self.groups.remove_user_from_group(user["id"], g["id"])
        
        for g_name in to_add:
            g = self.groups.get_or_create_group(g_name)
            self.groups.add_user_to_group(user["id"], g["id"])
        
        # Update profile attributes
        self.okta.update_user(user["id"], event.to_okta_profile())
        
        return user
    
    def process_terminate(self, event: HREvent):
        """Deactivate user. Okta revokes all app access automatically."""
        user = self.okta.find_user_by_login(event.email)
        if not user:
            raise ValueError(f"User {event.email} not found")
        
        self.okta.deactivate_user(user["id"])
        return user