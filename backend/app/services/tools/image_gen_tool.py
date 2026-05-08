"""OpenAI Images API — used by designer AgentRuntime (`generate_image_asset`)."""

from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict

import httpx

from ...config import settings
from ..task_workspace import find_task_root

logger = logging.getLogger(__name__)


def _fallback_generated_dir() -> Path:
    if settings.workspace_root:
        return Path(settings.workspace_root) / "_generated_images"
    return Path(__file__).resolve().parents[4] / "data" / "workspace" / "_generated_images"

_OPENAI_IMAGE_URL = "https://api.openai.com/v1/images/generations"

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")


async def generate_image_asset(params: Dict[str, Any]) -> str:
    """Generate a PNG via OpenAI Images and save under task screenshots/generated/."""
    prompt = (params.get("prompt") or "").strip()
    if not prompt:
        return json.dumps({"ok": False, "error": "prompt is required"}, ensure_ascii=False)

    api_key = (settings.openai_api_key or "").strip()
    if not api_key:
        return json.dumps(
            {"ok": False, "error": "OPENAI_API_KEY is not configured"},
            ensure_ascii=False,
        )

    task_id = str(params.get("pipeline_task_id") or params.get("task_id") or "").strip()
    raw_name = (params.get("filename") or "ui-mockup.png").strip()
    base = _SAFE_NAME.sub("-", raw_name) or "ui-mockup.png"
    if not base.lower().endswith(".png"):
        base += ".png"

    size = (params.get("size") or "1024x1024").strip()
    if size not in ("1024x1024", "1792x1024", "1024x1792"):
        size = "1024x1024"

    model = (settings.openai_image_model or "dall-e-3").strip()
    timeout = float(settings.openai_image_timeout_seconds or 120.0)

    out_dir: Path
    if task_id:
        root = find_task_root(task_id)
        if root is None:
            return json.dumps(
                {"ok": False, "error": f"task workspace not found for task_id={task_id}"},
                ensure_ascii=False,
            )
        out_dir = root / "screenshots" / "generated"
    else:
        out_dir = _fallback_generated_dir()

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / base

    payload = {
        "model": model,
        "prompt": prompt[:4000],
        "n": 1,
        "size": size,
        "response_format": "b64_json",
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(_OPENAI_IMAGE_URL, headers=headers, json=payload)
    except httpx.TimeoutException:
        return json.dumps({"ok": False, "error": "OpenAI Images request timed out"}, ensure_ascii=False)
    except Exception as e:
        logger.warning("[image_gen] request failed: %s", e)
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    if resp.status_code >= 400:
        detail = resp.text[:800]
        try:
            body = resp.json()
            detail = str(body.get("error", body))[:800]
        except Exception:
            pass
        return json.dumps(
            {"ok": False, "error": f"HTTP {resp.status_code}: {detail}"},
            ensure_ascii=False,
        )

    try:
        body = resp.json()
        data = (body.get("data") or [{}])[0]
        b64 = data.get("b64_json")
        if not b64:
            return json.dumps(
                {"ok": False, "error": "OpenAI response missing b64_json"},
                ensure_ascii=False,
            )
        raw = base64.b64decode(b64)
        out_path.write_bytes(raw)
    except Exception as e:
        logger.warning("[image_gen] decode/write failed: %s", e)
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    rel = str(out_path)
    try:
        wr = settings.workspace_root
        if wr:
            prefix = str(Path(wr).resolve())
            if rel.startswith(prefix):
                rel = rel[len(prefix) :].lstrip("/")
    except Exception:
        pass

    snippet = f"![generated mockup]({base})"
    return json.dumps(
        {
            "ok": True,
            "path": rel,
            "relative_path": f"screenshots/generated/{base}" if task_id else str(out_path.name),
            "markdown": snippet,
            "model": model,
            "size": size,
        },
        ensure_ascii=False,
    )
