"""Vercel deployment — deploy static sites and serverless functions."""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

import httpx

from ..sse import emit_event

logger = logging.getLogger(__name__)

VERCEL_API = "https://api.vercel.com"


async def deploy_to_vercel(
    *,
    project_dir: str,
    project_name: str,
    token: str,
    team_id: Optional[str] = None,
    framework: str = "vite",
    production: bool = False,
) -> Dict[str, Any]:
    """Deploy a project to Vercel.

    Steps:
    1. Create or find the project
    2. Upload files via Vercel API
    3. Create deployment
    4. Return deployment URL
    """
    if not token:
        return {"ok": False, "error": "VERCEL_TOKEN not configured"}

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    params = {"teamId": team_id} if team_id else {}

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            await emit_event("deploy:start", {
                "platform": "vercel", "project": project_name,
            })

            project = await _ensure_project(client, headers, params, project_name, framework)
            if not project.get("ok"):
                return project

            files = _collect_files(project_dir)
            if not files:
                return {"ok": False, "error": "No files to deploy"}

            file_uploads = []
            for rel_path, content in files.items():
                file_uploads.append({
                    "file": rel_path,
                    "data": content,
                })

            deploy_body = {
                "name": project_name,
                "files": file_uploads,
                "projectSettings": {
                    "framework": framework,
                },
                "target": "production" if production else "preview",
            }

            resp = await client.post(
                f"{VERCEL_API}/v13/deployments",
                headers=headers,
                params=params,
                json=deploy_body,
            )

            if resp.status_code not in (200, 201):
                return {"ok": False, "error": resp.text[:1000], "status": resp.status_code}

            data = resp.json()
            url = data.get("url", "")
            deploy_url = f"https://{url}" if url else ""

            await emit_event("deploy:complete", {
                "platform": "vercel",
                "project": project_name,
                "url": deploy_url,
                "deploymentId": data.get("id", ""),
            })

            return {
                "ok": True,
                "platform": "vercel",
                "url": deploy_url,
                "deploymentId": data.get("id", ""),
                "readyState": data.get("readyState", ""),
                "target": "production" if production else "preview",
            }

    except Exception as e:
        logger.error(f"Vercel deploy failed: {e}")
        return {"ok": False, "error": str(e)}


async def _ensure_project(
    client: httpx.AsyncClient,
    headers: dict,
    params: dict,
    name: str,
    framework: str,
) -> Dict[str, Any]:
    """Create project if it doesn't exist."""
    resp = await client.get(
        f"{VERCEL_API}/v9/projects/{name}",
        headers=headers,
        params=params,
    )
    if resp.status_code == 200:
        return {"ok": True, "project": resp.json()}

    resp = await client.post(
        f"{VERCEL_API}/v10/projects",
        headers=headers,
        params=params,
        json={"name": name, "framework": framework},
    )
    if resp.status_code in (200, 201):
        return {"ok": True, "project": resp.json()}

    return {"ok": False, "error": f"Failed to create project: {resp.text[:500]}"}


def _collect_files(directory: str, max_size: int = 5 * 1024 * 1024) -> Dict[str, str]:
    """Collect all files from a directory for upload."""
    files: Dict[str, str] = {}
    skip_dirs = {"node_modules", ".git", "__pycache__", ".next", "dist"}

    for root, dirs, filenames in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fname in filenames:
            full_path = os.path.join(root, fname)
            rel_path = os.path.relpath(full_path, directory)
            size = os.path.getsize(full_path)
            if size > max_size:
                continue
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    files[rel_path] = f.read()
            except (UnicodeDecodeError, PermissionError):
                pass

    return files


async def get_deployment_status(
    deployment_id: str,
    token: str,
    team_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Check status of a Vercel deployment."""
    headers = {"Authorization": f"Bearer {token}"}
    params = {"teamId": team_id} if team_id else {}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{VERCEL_API}/v13/deployments/{deployment_id}",
            headers=headers,
            params=params,
        )
        if resp.status_code != 200:
            return {"ok": False, "error": resp.text[:500]}

        data = resp.json()
        return {
            "ok": True,
            "state": data.get("readyState", ""),
            "url": f"https://{data.get('url', '')}",
            "createdAt": data.get("createdAt"),
        }
