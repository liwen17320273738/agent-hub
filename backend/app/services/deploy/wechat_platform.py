"""WeChat Official Account Platform API integration."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

WX_API = "https://api.weixin.qq.com"


class WeChatPlatformAPI:
    """WeChat Official Account / Mini Program management APIs."""

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self._access_token: Optional[str] = None
        self._token_expires: float = 0

    async def _get_access_token(self) -> str:
        """Get or refresh access token."""
        if self._access_token and time.time() < self._token_expires:
            return self._access_token

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{WX_API}/cgi-bin/token",
                params={
                    "grant_type": "client_credential",
                    "appid": self.app_id,
                    "secret": self.app_secret,
                },
            )
            data = resp.json()
            if "access_token" not in data:
                raise RuntimeError(f"WeChat token error: {data}")

            self._access_token = data["access_token"]
            self._token_expires = time.time() + data.get("expires_in", 7200) - 300
            return self._access_token

    async def get_miniprogram_versions(self) -> Dict[str, Any]:
        """Get miniprogram version info (latest, audit status, online version)."""
        token = await self._get_access_token()
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{WX_API}/wxa/getversioninfo",
                params={"access_token": token},
            )
            return resp.json()

    async def submit_audit(
        self,
        item_list: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Submit miniprogram for review."""
        token = await self._get_access_token()
        body: Dict[str, Any] = {}
        if item_list:
            body["item_list"] = item_list

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{WX_API}/wxa/submit_audit",
                params={"access_token": token},
                json=body,
            )
            return resp.json()

    async def get_audit_status(self, auditid: int) -> Dict[str, Any]:
        """Check review status of a submission."""
        token = await self._get_access_token()
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{WX_API}/wxa/get_auditstatus",
                params={"access_token": token},
                json={"auditid": auditid},
            )
            return resp.json()

    async def release(self) -> Dict[str, Any]:
        """Publish the approved version to production."""
        token = await self._get_access_token()
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{WX_API}/wxa/release",
                params={"access_token": token},
                json={},
            )
            return resp.json()

    async def revert_release(self) -> Dict[str, Any]:
        """Rollback to previous online version."""
        token = await self._get_access_token()
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{WX_API}/wxa/revertcoderelease",
                params={"access_token": token},
            )
            return resp.json()

    async def send_template_message(
        self,
        touser: str,
        template_id: str,
        data: Dict[str, Dict[str, str]],
        url: str = "",
        miniprogram: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Send a template message to a user (for notifications)."""
        token = await self._get_access_token()
        body: Dict[str, Any] = {
            "touser": touser,
            "template_id": template_id,
            "data": data,
        }
        if url:
            body["url"] = url
        if miniprogram:
            body["miniprogram"] = miniprogram

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{WX_API}/cgi-bin/message/template/send",
                params={"access_token": token},
                json=body,
            )
            return resp.json()

    async def send_custom_message(
        self,
        touser: str,
        msgtype: str = "text",
        content: str = "",
    ) -> Dict[str, Any]:
        """Send a customer service message."""
        token = await self._get_access_token()
        body: Dict[str, Any] = {
            "touser": touser,
            "msgtype": msgtype,
        }
        if msgtype == "text":
            body["text"] = {"content": content}
        elif msgtype == "image":
            body["image"] = {"media_id": content}

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{WX_API}/cgi-bin/message/custom/send",
                params={"access_token": token},
                json=body,
            )
            return resp.json()
