import logging
from typing import Dict,Any,Optional
from jml.okta_client import AuthenticationError
import requests

logger=logging.getLogger("jml.groups")

class GroupManager:
    def __init__(self,domain:str,api_token:str):
        self.base_url=f"https://{domain.rstrip('/')}/api/v1"
        self.session=requests.Session()
        self.session.headers.update({
            "Authorization": f"ssws {api_token}",
            "Content": "application/json",
            "Accept": "application/json"
        })

    def find_group_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        resp = self.session.get(f"{self.base_url}/groups", params={"q": name, "limit": "10"})
        if resp.status_code in (401, 403):
            raise AuthenticationError(
                f"Okta token invalid or lacks group permissions (HTTP {resp.status_code}). "
                f"Ensure token owner has Group Admin or Super Admin role.",
                resp.status_code,
            )
        if resp.status_code != 200:
            resp.raise_for_status()
        for group in resp.json():
            if group.get("profile", {}).get("name") == name:
                return group
        return None

    def create_group(self, name: str, description: str = "") -> Dict[str, Any]:
        payload = {"profile": {"name": name, "description": description}}
        resp = self.session.post(f"{self.base_url}/groups", json=payload)
        if resp.status_code in (401, 403):
            raise AuthenticationError(
                f"Okta token invalid or lacks group permissions (HTTP {resp.status_code}). "
                f"Ensure token owner has Group Admin or Super Admin role.",
                resp.status_code,
            )
        resp.raise_for_status()
        group = resp.json()
        logger.info("Created group id=%s name=%s", group.get("id"), name)
        return group


    def get_or_create_group(self,name:str,description:str="")->Dict[str,Any]:
        group=self.find_group_by_name(name)
        if group:
            return group
        return self.create_group(name,description)

    def add_user_to_group(self,user_id:str,group_id:str)->None:
        resp=self.session.put(f"{self.base_url}/groups/{group_id}/users/{user_id}")
        if resp.status_code==204 or resp.status_code==200:
            logger.info("Added user=%s to group=%s", user_id, group_id)
            return
        resp.raise_for_status()

    def delete_user_from_group(self,user_id:str,group_id:str)->None:
        resp=self.session.delete(f"{self.base_url}/groups/{group_id}/users/{user_id}")
        if resp.status_code==200:
            logger.info("Removed user=%s from group=%s", user_id, group_id)
            return
        resp.raise_for_status()

