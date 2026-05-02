"""WeChat Official Account outbound adapter.

Sends customer service messages (客服消息) to users who have interacted
with the Official Account within the last 48 hours (WeChat limitation).

Configuration (in `.env`):
  - `WECHAT_MP_APPID`  — Official Account AppID
  - `WECHAT_MP_SECRET` — Official Account AppSecret

Uses the same access token cache as `deploy/wechat_platform.py`.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from ...config import settings

logger = logging.getLogger(__name__)

WX_API = "https://api.weixin.qq.com"

_token_cache: Dict[str, Any] = {"token": "", "expires_at": 0.0}


async def _get_access_token() -> Optional[str]:
    """Get or refresh WeChat access token (shared with deploy/wechat_platform.py)."""
    if not settings.wechat_mp_appid or not settings.wechat_mp_secret:
        return None

    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] - 300 > now:
        return _token_cache["token"]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{WX_API}/cgi-bin/token",
                params={
                    "grant_type": "client_credential",
                    "appid": settings.wechat_mp_appid,
                    "secret": settings.wechat_mp_secret,
                },
            )
            data = resp.json()
            if "access_token" not in data:
                logger.warning(f"[wechat] access_token failed: {data}")
                return None
            _token_cache["token"] = data["access_token"]
            _token_cache["expires_at"] = now + data.get("expires_in", 7200) - 300
            return _token_cache["token"]
    except Exception as e:
        logger.warning(f"[wechat] access_token error: {e}")
        return None


def _format_text(title: str, lines: List[str], task_id: str) -> str:
    body = "\n".join(lines)
    hint = ""
    if task_id:
        hint = f"\n\n回复「通过 {task_id[:8]}」确认上线，或「修改：xxx」反馈"
    return f"【{title}】\n{body}{hint}"


async def send_text(
    *,
    user_id: str,
    title: str,
    lines: List[str],
    task_id: str,
) -> Dict[str, Any]:
    """Send a customer service text message to a WeChat user.

    WeChat requires the user to have interacted with the Official Account
    within the last 48 hours for this to succeed.
    """
    token = await _get_access_token()
    if not token:
        return {"ok": False, "skipped": True, "error": "no_access_token"}
    if not user_id:
        return {"ok": False, "skipped": True, "error": "no_user_id"}

    message = _format_text(title, lines, task_id)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{WX_API}/cgi-bin/message/custom/send",
                params={"access_token": token},
                json={
                    "touser": user_id,
                    "msgtype": "text",
                    "text": {"content": message},
                },
            )
            data = resp.json()
            ok = data.get("errcode") == 0
            return {
                "ok": ok,
                "mode": "wechat_custom",
                "errcode": data.get("errcode"),
                "errmsg": data.get("errmsg", ""),
            }
    except Exception as e:
        logger.warning(f"[wechat] send failed: {e}")
        return {"ok": False, "mode": "wechat_custom", "error": str(e)}
