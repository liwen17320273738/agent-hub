"""App Store Connect & Google Play Console integration for app deployment tracking."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class AppStoreConnect:
    """Apple App Store Connect API for iOS app management.

    Uses App Store Connect API v2 with JWT authentication.
    """

    API_BASE = "https://api.appstoreconnect.apple.com/v1"

    def __init__(self, issuer_id: str, key_id: str, private_key: str):
        self.issuer_id = issuer_id
        self.key_id = key_id
        self.private_key = private_key

    def _generate_token(self) -> str:
        """Generate a JWT token for App Store Connect API."""
        try:
            import jwt
        except ImportError:
            raise RuntimeError("PyJWT required: pip install PyJWT")

        now = int(time.time())
        payload = {
            "iss": self.issuer_id,
            "iat": now,
            "exp": now + 1200,
            "aud": "appstoreconnect-v1",
        }
        return jwt.encode(payload, self.private_key, algorithm="ES256", headers={"kid": self.key_id})

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._generate_token()}",
            "Content-Type": "application/json",
        }

    async def list_apps(self) -> Dict[str, Any]:
        """List all apps in the account."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/apps",
                headers=self._headers(),
            )
            if resp.status_code != 200:
                return {"ok": False, "error": resp.text[:500]}
            return {"ok": True, "apps": resp.json().get("data", [])}

    async def get_app_info(self, app_id: str) -> Dict[str, Any]:
        """Get app details."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/apps/{app_id}",
                headers=self._headers(),
            )
            if resp.status_code != 200:
                return {"ok": False, "error": resp.text[:500]}
            return {"ok": True, "app": resp.json().get("data")}

    async def list_builds(self, app_id: str) -> Dict[str, Any]:
        """List recent builds for an app."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/builds",
                headers=self._headers(),
                params={
                    "filter[app]": app_id,
                    "sort": "-uploadedDate",
                    "limit": 10,
                },
            )
            if resp.status_code != 200:
                return {"ok": False, "error": resp.text[:500]}
            return {"ok": True, "builds": resp.json().get("data", [])}

    async def get_review_submission_status(self, app_id: str) -> Dict[str, Any]:
        """Check the latest review submission status."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/reviewSubmissions",
                headers=self._headers(),
                params={
                    "filter[app]": app_id,
                    "sort": "-submittedDate",
                    "limit": 1,
                },
            )
            if resp.status_code != 200:
                return {"ok": False, "error": resp.text[:500]}
            data = resp.json().get("data", [])
            if not data:
                return {"ok": True, "status": "none", "message": "No submissions found"}
            latest = data[0]["attributes"]
            return {
                "ok": True,
                "status": latest.get("state", "unknown"),
                "submittedDate": latest.get("submittedDate"),
            }


class GooglePlayConsole:
    """Google Play Developer API for Android app management.

    Uses service account credentials for authentication.
    """

    API_BASE = "https://androidpublisher.googleapis.com/androidpublisher/v3"

    def __init__(self, service_account_json: str, package_name: str):
        self.service_account_json = service_account_json
        self.package_name = package_name
        self._access_token: Optional[str] = None
        self._token_expires: float = 0

    async def _get_access_token(self) -> str:
        """Get OAuth2 access token from service account."""
        if self._access_token and time.time() < self._token_expires:
            return self._access_token

        try:
            import json as _json
            import jwt
        except ImportError:
            raise RuntimeError("PyJWT required: pip install PyJWT")

        sa = _json.loads(self.service_account_json)
        now = int(time.time())
        payload = {
            "iss": sa["client_email"],
            "scope": "https://www.googleapis.com/auth/androidpublisher",
            "aud": sa["token_uri"],
            "iat": now,
            "exp": now + 3600,
        }
        assertion = jwt.encode(payload, sa["private_key"], algorithm="RS256")

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                sa["token_uri"],
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
            )
            data = resp.json()
            self._access_token = data["access_token"]
            self._token_expires = time.time() + data.get("expires_in", 3600) - 60
            return self._access_token

    def _headers(self, token: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def get_app_details(self) -> Dict[str, Any]:
        """Get app listing details."""
        token = await self._get_access_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/applications/{self.package_name}",
                headers=self._headers(token),
            )
            if resp.status_code != 200:
                return {"ok": False, "error": resp.text[:500]}
            return {"ok": True, "app": resp.json()}

    async def list_tracks(self) -> Dict[str, Any]:
        """List release tracks (production, beta, alpha, internal)."""
        token = await self._get_access_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.API_BASE}/applications/{self.package_name}/edits",
                headers=self._headers(token),
            )
            return {"ok": resp.status_code == 200, "data": resp.json() if resp.status_code == 200 else resp.text[:500]}

    async def get_review_status(self) -> Dict[str, Any]:
        """Check current review/rollout status."""
        token = await self._get_access_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            edit_resp = await client.post(
                f"{self.API_BASE}/applications/{self.package_name}/edits",
                headers=self._headers(token),
            )
            if edit_resp.status_code not in (200, 201):
                return {"ok": False, "error": "Failed to create edit"}

            edit_id = edit_resp.json().get("id")

            track_resp = await client.get(
                f"{self.API_BASE}/applications/{self.package_name}/edits/{edit_id}/tracks/production",
                headers=self._headers(token),
            )
            if track_resp.status_code != 200:
                return {"ok": False, "error": track_resp.text[:500]}

            track_data = track_resp.json()
            releases = track_data.get("releases", [])
            if not releases:
                return {"ok": True, "status": "none"}

            latest = releases[0]
            return {
                "ok": True,
                "status": latest.get("status", "unknown"),
                "versionCodes": latest.get("versionCodes", []),
                "name": latest.get("name", ""),
            }
