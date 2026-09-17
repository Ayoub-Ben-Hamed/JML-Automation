from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Any, List, Optional
from jml.models import HREvent,EventType
from jml.okta_client import (
    OktaClient,
    UserAlreadyExistsError,
    UserNotFoundError,
    OktaAPIError
)
from jml.group_manager import GroupManager
from jml.group_mappings import resolve_groups
from jml.group_diff import diff_groups
from jml.app_manager import AppManager
from jml.app_mappings import ROLE_TO_APPS

@dataclass
class JMLResult:
    status:str
    event_type: str
    employee_id: str
    email: str
    details: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def is_success(self)->bool:
        return self.status=="success"

    @property
    def is_failure(self)->bool:
        return self.status=="failure"

def handle_hire(event:HREvent,okta_client:OktaClient,group_manager:GroupManager,app_manager:AppManager)-> JMLResult:
    result=JMLResult(
        status="success",
        event_type=event.event_type.value,
        employee_id=event.employee_id,
        email=event.email
    )
    user_id=Optional[str]=None

    # Step 1: Check existing user
    try:
        existing=okta_client.find_user_by_login(event.email)
        if existing:
            status=existing.get("status")
            user_id=existing.get("id")
            if status=="DEPROVISIONED":
                result.status="failure"
                result.errors.append("User is DEPROVISIONED; use REHIRE instead of HIRE")
                return result
            result.warnings.append(f"User already exists ({status}), continuing idempotently")
            result.details["user_id"]=user_id
            result.details["user_status"]=status
    except Exception as exc:
        result.status="failure"
        result.errors.append(f"User lookup failed: {exc}")
        return result

    # Step 2: Create user if not found
    if not user_id:
        try:
            profile=event.to_okta_profile()
            profile.setdefault("firstName",event.first_name or "UNKNOWN")
            profile.setdefault("lastName",event.last_name or "UNKNOWN")
            activate=event.start_date is None or event.start_date<=date.today()
            user=okta_client.create_user(profile=profile,activate=activate)
            user_id = user["id"]
            result.details["user_id"] = user_id
            result.details["user_status"] = user.get("status")
        except UserAlreadyExistsError:
            result.status="failure"
            result.errors.append("User already exists (race condition)")
        except Exception as exc:
            result.status = "failure"
            result.errors.append(f"User creation failed: {exc}")
            return result

    # Step 3: Assign groups
    groups_ok=[]
    try:
        target_groups=resolve_groups(event.department,event.role)
        for g_name in target_groups:
            try:
                group=group_manager.get_or_create_group(g_name)
                group_manager.add_user_to_group(user_id,group["id"])
                groups_ok.append(g_name)
            except Exception as exc:
                result.warnings.append(f"Group {g_name} failed: {exc}")
                result.status="partial"
        result.details["groups_added"]=groups_ok
    except Exception as exc:
        result.warnings.append(f"Group resolution failed: {exc}")
        result.status = "partial"

    # Step 4: Provision apps
    apps_ok=[]
    if app_manager:
        try:
            for app_ref in ROLE_TO_APPS.get(event.role,[]):
                try:
                    app=app_manager.find_app_by_label(app_ref.get("okta_label"))
                    if app:
                        app_manager.assign_app_to_user(app["id"],user_id)
                        apps_ok.append(app_ref.okta_label)
                except Exception as exc:
                    result.status="partial"
                    result.warnings.append(f"App {app_ref.okta_label} failed: {exc}")
            result.details["apps_added"]=apps_ok
        except Exception as exc:
            result.warnings.append(f"App provisioning failed: {exc}")
            result.status = "partial"

    if result.errors and not result.details.get("user_id"):
        result.status="failure"
    elif result.warnings:
        result.status="partial"
    else:
        result.status="success"

    return result

def handle_move(event:HREvent,okta_client:OktaClient,group_manager:GroupManager,app_manager:AppManager)->JMLResult:
    result = JMLResult(
        status="success",
        event_type=event.event_type.value,
        employee_id=event.employee_id,
        email=event.email,
    )
    user_id: Optional[str] = None
    
    # Step 1: Find user
    try:
        user = okta_client.find_user_by_login(event.email)
        if not user:
            result.status = "failure"
            result.errors.append("User not found")
            return result
        user_id = user["id"]
        result.details["user_id"] = user_id
    except Exception as exc:
        result.status = "failure"
        result.errors.append(f"User lookup failed: {exc}")
        return result

    # Stzp 2:Diff groups
    try:
        old_groups=resolve_groups(event.old_department,event.old_role)
        new_groups=resolve_groups(event.department,event.role)
        to_remove,to_add,preserved=diff_groups(old_groups,new_groups)
        result.details["groups_removed"]=list(to_remove)
        result.details["groups_added"]=list(to_add)
        result.details["groups_preserved"]=list(preserved)
    except Exception as exc:
        result.status = "failure"
        result.errors.append(f"Group diff failed: {exc}")
        return result

    # Step 3: Remove old groups
    removed_ok=[]
    for g_name in to_remove:
        try:
            group=group_manager.find_group_by_name(g_name)
            if group:
                group_manager.delete_user_from_group(user_id,group["id"])
                removed_ok.append(g_name)
        except Exception:
            pass
        result.details["groups_removed_ok"]=removed_ok

    # Step 4: Add new groups
    added_ok = []
    for g_name in to_add:
        try:
            group = group_manager.get_or_create_group(g_name)
            group_manager.add_user_to_group(user_id, group["id"])
            added_ok.append(g_name)
        except Exception as exc:
            result.warnings.append(f"Add group {g_name} failed: {exc}")
            result.status = "partial"
    result.details["groups_added_ok"] = added_ok

    # Step 5: Update profile
    try:
        profile=event.to_okta_profile()
        profile.setdefault("firstName",event.first_name or user.get("profile",{}).get("firstName","UNKNOWN"))
        profile.setdefault("lastName",event.last_name or user.get("profile",{}).get("lastName","UNKNOWN"))
        okta_client.update_user(user["id"],profile)
        result.details["profile_updated"] = True
    except Exception as exc:
        result.warnings.append(f"Profile update failed: {exc}")
        result.status = "partial"
        result.details["profile_updated"] = False

    # Step 6: App diff (optional direct assignment)
    if app_manager:
        try:
            old_apps = {a.okta_label for a in ROLE_TO_APPS.get(event.old_role, [])}
            new_apps = {a.okta_label for a in ROLE_TO_APPS.get(event.role, [])}
            apps_to_add = new_apps - old_apps
            apps_added = []
            for app_label in apps_to_add:
                try:
                    app = app_manager.find_app_by_label(app_label)
                    if app:
                        app_manager.assign_app_to_user(app["id"], user_id)
                        apps_added.append(app_label)
                except Exception as aexc:
                    result.warnings.append(f"App {app_label} failed: {aexc}")
                    result.status = "partial"
            result.details["apps_added"] = apps_added
        except Exception as exc:
            result.warnings.append(f"App diff failed: {exc}")
            result.status = "partial"

    if result.errors:
        result.status = "failure"
    elif result.warnings:
        result.status = "partial"
    else:
        result.status = "success"

    return result

def _get_user_groups(okta_client:OktaClient,user_id:str)->List[Dict[str,Any]]:
    resp=okta_client._session.get(f"{okta_client.base_url}/users/{user_id}/groups")
    if resp.status_code==200:
        return resp.json()
    return []

def _get_direct_apps(okta_client:OktaClient,user_id:str)->List[dict[str,Any]]:
    url=f"{okta_client.base_url}/apps"
    resp=okta_client._session.get(url,params={"filter":f'user.id eq "{user_id}"'})
    if resp.status_code==200:
        return resp.json()
    return []

def handle_terminate(event:HREvent,okta_client:OktaClient,group_manager:GroupManager,app_manager:AppManager)->JMLResult:
    result=JMLResult(
        status="SUCCESS",
        event_type=event.event_type.value,
        employee_id=event.employee_id,
        email=event.email
    )
    user_id:Optional[str]=None

    # find user by login
    try:
        user=okta_client.find_user_by_login(event.email)
        if not user:
            result.status="failure"
            result.errors.append(f"User {event.employee_id} not found")
            return result
        user_id=user["id"]
        result.details["user_id"]=user_id
        result.details["status_before"]=user.get("status","")
    except Exception as exc:
        result.status = "failure"
        result.errors.append(f"Lookup failed: {exc}")
        return result

    # Desactivate user (should be before removing groups or revoking apps)
    try:
        desactivated=okta_client.deactivate_user(user_id)
        result.details["status_after"]=desactivated.get("status")
    except Exception as exc:
        result.errors.append(f"Desactivation failed : {exc}")
        result.status="partial"

# Remove groups
    groups_removed = []
    try:
        for group in _get_user_groups(okta_client, user_id):
            if group.get("type") == "BUILT_IN":
                continue
            gid = group["id"]
            gname = group.get("profile", {}).get("name", gid)
            try:
                group_manager.remove_user_from_group(user_id, gid)
                groups_removed.append(gname)
            except Exception as gexc:
                result.warnings.append(f"Remove group {gname}: {gexc}")
                result.status = "partial"
        result.details["groups_removed"] = groups_removed
    except Exception as exc:
        result.warnings.append(f"Group cleanup: {exc}")
        result.status = "partial"

    # Revoke apps
    apps_revoked = []
    if app_manager:
        try:
            for app in _get_direct_apps(okta_client, user_id):
                aid = app["id"]
                aname = app.get("label", aid)
                try:
                    app_manager.remove_app_from_user(aid, user_id)
                    apps_revoked.append(aname)
                except Exception as aexc:
                    result.warnings.append(f"Revoke app {aname}: {aexc}")
                    result.status = "partial"
            result.details["apps_revoked"] = apps_revoked
        except Exception as exc:
            result.warnings.append(f"App cleanup: {exc}")
            result.status = "partial"

    if result.errors:
        result.status = "failure"
    elif result.warnings:
        result.status = "partial"

    return result

class JMLEngine:
    def __init__(self,okta_client: OktaClient,group_manager: GroupManager,app_manager: Optional[AppManager] = None):
        self.okta = okta_client
        self.groups = group_manager
        self.apps = app_manager

    def process_event(self,event:HREvent)->JMLResult:
        if event.event_type==EventType.HIRE:
            return handle_hire(event,self.okta,self.groups,self.apps)
        if event.event_type==EventType.MOVE:
            return handle_move(event,self.okta,self.groups,self.apps)
        if event.event_type==EventType.TERMINATE:
            return handle_terminate(event,self.okta,self.groups,self.apps)
        return JMLResult(
            status="failure",
            event_type=event.event_type.value,
            employee_id=event.employee_id,
            email=event.email,
            errors=[f"Unsupported event type: {event.event_type.value}"]
        )

    def process_csv(self, events: List[HREvent]) -> Dict[str, Any]:
        results: List[JMLResult] = []
        for event in events:
            results.append(self.process_event(event))

        return {
            "total": len(results),
            "success": sum(1 for r in results if r.status == "success"),
            "partial": sum(1 for r in results if r.status == "partial"),
            "failure": sum(1 for r in results if r.status == "failure"),
            "results": results,
        }
