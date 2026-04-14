"""Deploy API — deploy projects to Vercel, Cloudflare, WeChat, app stores."""
from __future__ import annotations

import os
from typing import Annotated, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models.user import User
from ..security import get_pipeline_auth

router = APIRouter(prefix="/deploy", tags=["deploy"])


# ── Vercel ──────────────────────────────────────────────────────────

class VercelDeployRequest(BaseModel):
    task_id: str
    project_dir: str
    project_name: str
    framework: str = "vite"
    production: bool = False


@router.post("/vercel")
async def deploy_vercel(
    body: VercelDeployRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
):
    token = getattr(settings, "vercel_token", "") or os.environ.get("VERCEL_TOKEN", "")
    if not token:
        raise HTTPException(status_code=400, detail="VERCEL_TOKEN not configured")

    from ..services.deploy.vercel import deploy_to_vercel
    from ..services.deploy.deploy_tracker import deploy_tracker

    result = await deploy_to_vercel(
        project_dir=body.project_dir,
        project_name=body.project_name,
        token=token,
        framework=body.framework,
        production=body.production,
    )

    if result.get("ok") and result.get("deploymentId"):
        deploy_tracker.register(
            body.task_id, "vercel", result["deploymentId"], result.get("url", ""),
        )
        background_tasks.add_task(
            deploy_tracker.poll_vercel_status,
            body.task_id, result["deploymentId"], token,
        )

    return result


# ── Cloudflare ──────────────────────────────────────────────────────

class CloudflareDeployRequest(BaseModel):
    task_id: str
    project_dir: str
    project_name: str
    production: bool = False


@router.post("/cloudflare")
async def deploy_cloudflare(
    body: CloudflareDeployRequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
):
    token = getattr(settings, "cloudflare_api_token", "") or os.environ.get("CLOUDFLARE_API_TOKEN", "")
    account_id = getattr(settings, "cloudflare_account_id", "") or os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    if not token or not account_id:
        raise HTTPException(status_code=400, detail="CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID required")

    from ..services.deploy.cloudflare import deploy_to_cloudflare

    return await deploy_to_cloudflare(
        project_dir=body.project_dir,
        project_name=body.project_name,
        api_token=token,
        account_id=account_id,
        production=body.production,
    )


# ── WeChat Mini Program ────────────────────────────────────────────

class MiniProgramDeployRequest(BaseModel):
    task_id: str
    project_dir: str
    app_id: str
    private_key_path: str
    version: str = "1.0.0"
    description: str = "Agent Hub auto deploy"


@router.post("/miniprogram")
async def deploy_miniprogram_endpoint(
    body: MiniProgramDeployRequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
):
    from ..services.deploy.miniprogram import deploy_miniprogram

    return await deploy_miniprogram(
        project_dir=body.project_dir,
        app_id=body.app_id,
        private_key_path=body.private_key_path,
        version=body.version,
        description=body.description,
    )


class MiniProgramPreviewRequest(BaseModel):
    project_dir: str
    app_id: str
    private_key_path: str


@router.post("/miniprogram/preview")
async def preview_miniprogram_endpoint(
    body: MiniProgramPreviewRequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
):
    from ..services.deploy.miniprogram import preview_miniprogram

    return await preview_miniprogram(
        project_dir=body.project_dir,
        app_id=body.app_id,
        private_key_path=body.private_key_path,
    )


# ── WeChat Audit ────────────────────────────────────────────────────

class SubmitAuditRequest(BaseModel):
    task_id: str
    app_id: str
    app_secret: str


@router.post("/miniprogram/submit-audit")
async def submit_wechat_audit(
    body: SubmitAuditRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
):
    from ..services.deploy.wechat_platform import WeChatPlatformAPI
    from ..services.deploy.deploy_tracker import deploy_tracker

    api = WeChatPlatformAPI(body.app_id, body.app_secret)
    result = await api.submit_audit()

    if result.get("errcode") == 0:
        audit_id = result.get("auditid")
        background_tasks.add_task(
            deploy_tracker.poll_wechat_audit,
            body.task_id, audit_id, body.app_id, body.app_secret,
        )
        return {"ok": True, "auditId": audit_id}

    return {"ok": False, "error": result}


class AuditStatusRequest(BaseModel):
    app_id: str
    app_secret: str
    audit_id: int


@router.post("/miniprogram/audit-status")
async def check_audit_status(
    body: AuditStatusRequest,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
):
    from ..services.deploy.wechat_platform import WeChatPlatformAPI

    api = WeChatPlatformAPI(body.app_id, body.app_secret)
    return await api.get_audit_status(body.audit_id)


# ── Deploy Status ───────────────────────────────────────────────────

@router.get("/status/{task_id}")
async def get_deploy_status(
    task_id: str,
    user: Annotated[Optional[User], Depends(get_pipeline_auth)],
):
    from ..services.deploy.deploy_tracker import deploy_tracker

    records = deploy_tracker.get_all_for_task(task_id)
    return {
        "taskId": task_id,
        "deployments": [r.to_dict() for r in records],
    }
