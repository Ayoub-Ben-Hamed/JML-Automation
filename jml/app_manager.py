import logging
import requests
from typing import Dict,List,Any,Optional
from jml.okta_client import AuthenticationError

logger=logging.getLogger("jml.apps")
class AppManager:
    """Manages Okta app assignments. Used for setup and exceptions,
    not for the core JML runtime path (which uses groups only)."""
    def __init__(self,domain:str,api_token:str):
        self.base_url=f"https://{domain.rstrip("/")}/api/v1"
        self.api_token=api_token
        self.session=requests.Session()
        self.session.headers.update({
            "Authorization": f"SSWS {self.api_token}",
            "Content": "application/json",
            "Accept" : "application/json"
        })
    def list_apps(self,limit:int=200)->List[Dict[str,Any]]:
        res=self.session.get(f"{self.base_url}/apps/",params={"limit":limit})
        if res.status_code in (401,403):
            raise AuthenticationError("Invalid token or insufficient permissions",res.status_code)
        res.raise_for_status()
        return res.json()
    def find_app_by_label(self,label:str)->Optional[Dict[str,Any]]:
        apps=self.list_apps()
        for app in apps:
            if app.get("okta_label","")==label:
                return app
        return None

    def assign_app_to_group(self,app_id:str,group_id:str)->None:
        payload={"id": group_id}
        resp=self.session.post(f"{self.base_url}/apps/{app_id}/groups",json=payload)
        if resp.status_code==204:
            logger.info("assigned App : %s to Group : %s",app_id,group_id)
            return
        if resp.status_code == 200:
            logger.info("Assigned app=%s to group=%s", app_id, group_id)
            return
        resp.raise_for_status()

    def remove_app_from_group(self,app_id:str,group_id:str)->None:
        resp=self.session.delete(f"{self.base_url}/apps/{app_id}/groups/{group_id}/")
        if resp.status_code==204:
            logger.info("Removed app=%s from group=%s", app_id, group_id)
            return
        resp.raise_for_status()

    def get_user_app_links(self,user_id:str)->Dict[str,Any]:
        resp=self.session.get(f"{self.base_url}/users/{user_id}/appLinks/")
        resp.raise_for_status()
        return resp.json()

    # Direct User assignment (Exceptions only)
    def assign_app_to_user(self,app_id:str,user_id:str)->Dict[str,Any]:
        payload={"id":user_id, "scope":"USER"}
        resp=self.session.post(f"{self.base_url}/apps/{app_id}/users",json=payload)
        resp.raise_for_status()
        return resp.json()

    def remove_app_from_user(self,app_id:str,user_id:str)->None:
        resp=self.session.delete(f"{self.base_url}/apps/{app_id}/users/{user_id}/")
        if resp.status_code == 204:
            logger.info("Removed app=%s from user=%s", app_id, user_id)
            return
        resp.raise_for_status()
