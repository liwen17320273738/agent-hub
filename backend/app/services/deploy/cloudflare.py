"""Cloudflare Pages deployment."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx

from ..sse import emit_event

logger = logging.getLogger(__name__)

CF_API = "https://api.cloudflare.com/client/v4"


async def deploy_to_cloudflare(
    *,
    project_dir: str,
    project_name: str,
    api_token: str,
    account_id: str,
    production: bool = False,
) -> Dict[str, Any]:
    """Deploy a project to Cloudflare Pages via Direct Upload API.

    Requires a built project (the dist/ or output directory).
    """
    if not api_token or not account_id:
        return {"ok": False, "error": "CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID required"}

    headers = {"Authorization": f"Bearer {api_token}"}

    dist_dir = _find_dist_dir(project_dir)
    if not dist_dir:
        return {"ok": False, "error": "No build output directory found (dist/, build/, out/)"}

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            await emit_event("deploy:start", {
                "platform": "cloudflare", "project": project_name,
            })

            await _ensure_pages_project(client, headers, account_id, project_name)

            files = _collect_files_for_upload(dist_dir)
            if not files:
                return {"ok": False, "error": "No files in build output"}

            upload_resp = await client.post(
                f"{CF_API}/accounts/{account_id}/pages/projects/{project_name}/deployments",
                headers=headers,
                files=files,
            )

            if upload_resp.status_code not in (200, 201):
                return {"ok": False, "error": upload_resp.text[:1000], "status": upload_resp.status_code}

            data = upload_resp.json().get("result", {})
            url = data.get("url", "")

            await emit_event("deploy:complete", {
                "platform": "cloudflare",
                "project": project_name,
                "url": url,
                "deploymentId": data.get("id", ""),
            })

            return {
                "ok": True,
                "platform": "cloudflare",
                "url": url,
                "deploymentId": data.get("id", ""),
                "environment": data.get("environment", "preview"),
            }

    except Exception as e:
        logger.error(f"Cloudflare deploy failed: {e}")
        return {"ok": False, "error": str(e)}


async def _ensure_pages_project(
    client: httpx.AsyncClient,
    headers: dict,
    account_id: str,
    name: str,
) -> None:
    """Create Cloudflare Pages project if not exists."""
    resp = await client.get(
        f"{CF_API}/accounts/{account_id}/pages/projects/{name}",
        headers=headers,
    )
    if resp.status_code == 200:
        return

    await client.post(
        f"{CF_API}/accounts/{account_id}/pages/projects",
        headers=headers,
        json={
            "name": name,
            "production_branch": "main",
        },
    )


def _find_dist_dir(project_dir: str) -> Optional[str]:
    """Find the built output directory."""
    for candidate in ["dist", "build", "out", ".output", "public"]:
        path = os.path.join(project_dir, candidate)
        if os.path.isdir(path):
            return path
    return None


def _collect_files_for_upload(dist_dir: str) -> list:
    """Collect files in multipart form format for Cloudflare upload."""
    files = []
    for root, _, filenames in os.walk(dist_dir):
        for fname in filenames:
            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, dist_dir)
            try:
                files.append(
                    ("file", (rel_path, open(full_path, "rb")))
                )
            except PermissionError:
                pass
    return files
