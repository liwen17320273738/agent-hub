"""QQ outbound adapter via OneBot v11 / NapCat / go-cqhttp HTTP API.

QQ official Bot Open Platform does not allow arbitrary inbound webhooks,
so this adapter targets the OneBot v11 HTTP API exposed by self-hosted
bridges (NapCat, go-cqhttp, Lagrange, etc).

Configuration (in `.env`):
  - `qq_bot_endpoint`  e.g. `http://127.0.0.1:5700`
  - optional `Authorization: Bearer ...` via `qq_bot_access_token`

Sends a private message to `user_id` if provided, else degrades gracefully.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from ...config import settings

logger = logging.getLogger(__name__)


def _format_text(title: str, lines: List[str], task_id: str) -> str:
    body = "\n".join(lines)
    hint = ""
    if task_id:
        hint = f"\n\n回复「通过 {task_id[:8]}」确认上线，或「修改：xxx」反馈"
    return f"【{title}】\n{body}{hint}"


def _endpoint(path: str) -> Optional[str]:
    base = (settings.qq_bot_endpoint or "").rstrip("/")
    if not base:
        return None
    return f"{base}{path}"


def _headers() -> Dict[str, str]:
    h = {"Content-Type": "application/json"}
    token = settings.qq_bot_access_token
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def send_text(
    *,
    user_id: str,
    title: str,
    lines: List[str],
    task_id: str,
) -> Dict[str, Any]:
    """Send a plain-text private message via OneBot HTTP."""
    url = _endpoint("/send_private_msg")
    if not url:
        return {"ok": False, "skipped": True, "error": "qq_bot_endpoint_not_configured"}
    if not user_id:
        return {"ok": False, "skipped": True, "error": "no_user_id"}

    message = _format_text(title, lines, task_id)
    payload_user_id: Any = user_id
    if isinstance(user_id, str) and user_id.isdigit():
        payload_user_id = int(user_id)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                headers=_headers(),
                json={"user_id": payload_user_id, "message": message},
            )
            data = resp.json() if resp.text else {}
            status = data.get("status", "")
            ok = resp.status_code == 200 and status in ("ok", "async")
            return {"ok": ok, "mode": "onebot", "status": resp.status_code, "retcode": data.get("retcode")}
    except Exception as e:
        logger.warning(f"[qq] OneBot send failed: {e}")
        return {"ok": False, "mode": "onebot", "error": str(e)}
