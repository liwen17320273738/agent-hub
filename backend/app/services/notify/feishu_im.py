"""Feishu (Lark) outbound adapter.

Two delivery modes (auto-fallback in this order):

1. **IM API** — uses `feishu_app_id` + `feishu_app_secret` to obtain a
   `tenant_access_token` and calls `/im/v1/messages?receive_id_type=open_id`
   to send a private message to the original sender (`open_id`).
2. **Group webhook** — falls back to a custom robot webhook
   (`feishu_group_webhook`) which posts an interactive card into a group.

Returns `{ok, skipped, mode, error}`. Never raises on credential issues.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from ...config import settings

logger = logging.getLogger(__name__)

_TENANT_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
_IM_SEND_URL = "https://open.feishu.cn/open-apis/im/v1/messages"

_token_cache: Dict[str, Any] = {"token": "", "expires_at": 0.0}


async def _get_tenant_token() -> Optional[str]:
    """Fetch and cache tenant_access_token; refresh ~5 min before expiry."""
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        return None

    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] - 300 > now:
        return _token_cache["token"]

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _TENANT_TOKEN_URL,
                json={
                    "app_id": settings.feishu_app_id,
                    "app_secret": settings.feishu_app_secret,
                },
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.warning(f"[feishu] tenant_access_token failed: {data}")
                return None
            _token_cache["token"] = data["tenant_access_token"]
            _token_cache["expires_at"] = now + int(data.get("expire", 7200))
            return _token_cache["token"]
    except Exception as e:
        logger.warning(f"[feishu] tenant_access_token error: {e}")
        return None


def _build_card(title: str, lines: List[str], buttons: Optional[List[Dict[str, Any]]] = None,
                template: str = "blue") -> Dict[str, Any]:
    elements: List[Dict[str, Any]] = []
    body = "\n".join(lines)
    if body:
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": body}})
    if buttons:
        elements.append({"tag": "action", "actions": buttons})
    return {
        "header": {"title": {"tag": "plain_text", "content": title[:80]}, "template": template},
        "elements": elements,
    }


async def _send_via_im_api(receive_id: str, card: Dict[str, Any]) -> Dict[str, Any]:
    token = await _get_tenant_token()
    if not token:
        return {"ok": False, "skipped": True, "error": "no_tenant_token"}
    if not receive_id:
        return {"ok": False, "skipped": True, "error": "no_open_id"}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{_IM_SEND_URL}?receive_id_type=open_id",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json={
                    "receive_id": receive_id,
                    "msg_type": "interactive",
                    "content": json.dumps(card, ensure_ascii=False),
                },
            )
            data = resp.json()
            if data.get("code") == 0:
                return {"ok": True, "mode": "im_api", "message_id": data.get("data", {}).get("message_id")}
            return {"ok": False, "mode": "im_api", "error": data.get("msg", "unknown"), "code": data.get("code")}
    except Exception as e:
        return {"ok": False, "mode": "im_api", "error": str(e)}


async def _send_via_group_webhook(card: Dict[str, Any]) -> Dict[str, Any]:
    webhook_url = settings.feishu_group_webhook
    if not webhook_url:
        return {"ok": False, "skipped": True, "error": "no_group_webhook"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                webhook_url,
                json={"msg_type": "interactive", "card": card},
            )
            data = resp.json() if resp.text else {}
            ok = (resp.status_code == 200) and (data.get("code", 0) in (0, None))
            return {"ok": ok, "mode": "group_webhook", "status": resp.status_code, "error": data.get("msg", "")}
    except Exception as e:
        return {"ok": False, "mode": "group_webhook", "error": str(e)}


async def send_card(
    *,
    open_id: str,
    title: str,
    lines: List[str],
    buttons: Optional[List[Dict[str, Any]]] = None,
    template: str = "blue",
) -> Dict[str, Any]:
    """Send an interactive card. Tries IM API first, falls back to group webhook."""
    card = _build_card(title, lines, buttons, template)

    im_result = await _send_via_im_api(open_id, card)
    if im_result.get("ok"):
        return im_result

    fallback = await _send_via_group_webhook(card)
    if fallback.get("ok"):
        fallback["im_api_error"] = im_result.get("error")
        return fallback

    return {
        "ok": False,
        "skipped": im_result.get("skipped") and fallback.get("skipped"),
        "im_api_error": im_result.get("error"),
        "webhook_error": fallback.get("error"),
    }


def task_action_buttons(task_id: str) -> List[Dict[str, Any]]:
    """Standard approve / reject buttons for preview cards."""
    return [
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "通过"},
            "type": "primary",
            "value": {"action": "approve", "task_id": task_id},
        },
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "需要修改"},
            "type": "danger",
            "value": {"action": "reject", "task_id": task_id},
        },
    ]


def final_acceptance_buttons(task_id: str) -> List[Dict[str, Any]]:
    """Wave 5 / G3 — interactive buttons for the final-acceptance terminus.

    These pump back through the Feishu webhook → ``_handle_final_acceptance_card_action``
    in the gateway. The action ids match the public API verbs so the gateway
    handler is a thin keyword router.
    """
    return [
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "✅ 接受交付"},
            "type": "primary",
            "value": {"action": "final_accept", "task_id": task_id},
        },
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "↩ 打回重做"},
            "type": "danger",
            "value": {"action": "final_reject", "task_id": task_id},
        },
    ]


# ───── Plan approval card ─────────────────────────────────────────
#
# Schema for the button `value` payload (round-trips through Feishu's
# card.action event back to /gateway/feishu/webhook):
#
#   {"action": "plan_approve" | "plan_revise" | "plan_reject",
#    "source": "feishu", "user_id": "ou_xxx"}

def _plan_buttons(source: str, user_id: str, can_revise: bool) -> List[Dict[str, Any]]:
    btns: List[Dict[str, Any]] = [
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "🚀 开干"},
            "type": "primary",
            "value": {"action": "plan_approve", "source": source, "user_id": user_id},
        },
    ]
    if can_revise:
        btns.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "✎ 修改"},
            "type": "default",
            "value": {"action": "plan_revise", "source": source, "user_id": user_id},
        })
    btns.append({
        "tag": "button",
        "text": {"tag": "plain_text", "content": "✕ 取消"},
        "type": "danger",
        "value": {"action": "plan_reject", "source": source, "user_id": user_id},
    })
    return btns


def _build_plan_card(
    title: str,
    plan: Dict[str, Any],
    source: str,
    user_id: str,
    rotation_count: int,
    max_rotations: int,
) -> Dict[str, Any]:
    """Build a richly-formatted Feishu interactive card representing an
    execution plan, with approve / revise / cancel buttons whose `value`
    payload routes through the card.action webhook.

    Layout:
      ┌────────────────────────────────┐
      │ 📋 待确认计划                  │ header (blue)
      ├────────────────────────────────┤
      │ **项目**：{title}              │
      │ **预估**：N 分钟  信心：medium │ summary line
      ├────────────────────────────────┤
      │ {plan.summary}                 │ optional summary
      ├────────────────────────────────┤
      │ ① **step1.title**              │ one block per step
      │    detail line                 │
      │    👤 role  · ⏱ 10min          │
      │ ─                              │
      │ ② **step2.title** ...          │
      ├────────────────────────────────┤
      │ ⚠ 风险：...                    │ optional risks block
      ├────────────────────────────────┤
      │ [ 🚀 开干 ] [ ✎ 修改 ] [ ✕ ] │ action buttons
      └────────────────────────────────┘
    """
    elements: List[Dict[str, Any]] = []

    summary_bits: List[str] = [f"**项目**：{title}"]
    est = plan.get("estimate_min_total")
    if est:
        summary_bits.append(f"**预估**：约 {est} 分钟")
    conf = plan.get("confidence")
    if conf:
        summary_bits.append(f"**信心**：{conf}")
    deploy = plan.get("deploy_target")
    if deploy:
        summary_bits.append(f"**部署**：{deploy}")
    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": "  ·  ".join(summary_bits)},
    })

    if plan.get("summary"):
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": str(plan["summary"])[:400]},
        })

    steps = plan.get("steps") or []
    if steps:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**📋 步骤（共 {len(steps)} 步）**"},
        })
        for s in steps[:12]:
            no = s.get("no") or "•"
            stitle = str(s.get("title") or "").strip() or "(untitled)"
            detail = str(s.get("detail") or "").strip()
            role = str(s.get("role") or "").strip()
            est_m = s.get("estimate_min")
            meta_bits = []
            if role:
                meta_bits.append(f"👤 {role}")
            if est_m:
                meta_bits.append(f"⏱ {est_m} 分钟")
            body_lines = [f"**{no}.** {stitle}"]
            if detail:
                body_lines.append(detail)
            if meta_bits:
                body_lines.append("`" + "  ·  ".join(meta_bits) + "`")
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": "\n".join(body_lines)},
            })
        if len(steps) > 12:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"_…还有 {len(steps) - 12} 步未展示_"},
            })

    risks = plan.get("risks") or []
    if risks:
        elements.append({"tag": "hr"})
        risk_lines = [f"⚠ {r}" for r in risks[:5]]
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "\n".join(risk_lines)},
        })

    elements.append({"tag": "hr"})
    rotation_note = (
        f"_已修改 {rotation_count}/{max_rotations} 次_"
        if rotation_count > 0
        else "_首次提交_"
    )
    elements.append({
        "tag": "note",
        "elements": [{"tag": "plain_text", "content": rotation_note}],
    })

    can_revise = rotation_count < max_rotations
    elements.append({
        "tag": "action",
        "actions": _plan_buttons(source, user_id, can_revise),
    })

    return {
        "header": {
            "title": {"tag": "plain_text", "content": "📋 待确认计划"[:80]},
            "template": "blue",
        },
        "elements": elements,
    }


async def send_plan_card(
    *,
    open_id: str,
    title: str,
    plan: Dict[str, Any],
    source: str,
    user_id: str,
    rotation_count: int = 0,
    max_rotations: int = 3,
) -> Dict[str, Any]:
    """Build & send the rich plan-approval card. Falls back like send_card."""
    card = _build_plan_card(
        title, plan, source, user_id, rotation_count, max_rotations,
    )

    im_result = await _send_via_im_api(open_id, card)
    if im_result.get("ok"):
        return im_result
    fallback = await _send_via_group_webhook(card)
    if fallback.get("ok"):
        fallback["im_api_error"] = im_result.get("error")
        return fallback
    return {
        "ok": False,
        "skipped": im_result.get("skipped") and fallback.get("skipped"),
        "im_api_error": im_result.get("error"),
        "webhook_error": fallback.get("error"),
    }
