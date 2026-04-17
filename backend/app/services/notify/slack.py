"""Slack outbound adapter.

Two delivery modes (auto-fallback in this order):

1. **chat.postMessage** — uses `slack_bot_token` to send a message to a
   user (`U…`) or channel (`C…`). Supports rich Block Kit blocks.
2. **Incoming webhook** — posts to a fixed channel via the legacy
   webhook URL. Falls back to text-only when blocks aren't supported.

All functions return `{ok, skipped, mode, error}` and never raise.

Inbound interactivity payloads (button clicks) are verified via
`verify_signature()` using `slack_signing_secret` per Slack's
v0 signing scheme: `v0=HMAC-SHA256(secret, "v0:{ts}:{raw_body}")`.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from ...config import settings

logger = logging.getLogger(__name__)

_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"


# ───── Block Kit builders ─────────────────────────────────────────

def task_action_buttons(task_id: str) -> List[Dict[str, Any]]:
    """Approve / reject buttons for preview cards (mirrors Feishu helper)."""
    return [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "通过"},
            "style": "primary",
            "action_id": "task_approve",
            "value": json.dumps({"action": "approve", "task_id": task_id}),
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "需要修改"},
            "style": "danger",
            "action_id": "task_reject",
            "value": json.dumps({"action": "reject", "task_id": task_id}),
        },
    ]


def _plan_buttons(source: str, user_id: str, can_revise: bool) -> List[Dict[str, Any]]:
    btns: List[Dict[str, Any]] = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "🚀 开干", "emoji": True},
            "style": "primary",
            "action_id": "plan_approve",
            "value": json.dumps({"action": "plan_approve", "source": source, "user_id": user_id}),
        },
    ]
    if can_revise:
        btns.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "✎ 修改", "emoji": True},
            "action_id": "plan_revise",
            "value": json.dumps({"action": "plan_revise", "source": source, "user_id": user_id}),
        })
    btns.append({
        "type": "button",
        "text": {"type": "plain_text", "text": "✕ 取消", "emoji": True},
        "style": "danger",
        "action_id": "plan_reject",
        "value": json.dumps({"action": "plan_reject", "source": source, "user_id": user_id}),
    })
    return btns


def build_plan_blocks(
    title: str,
    plan: Dict[str, Any],
    source: str,
    user_id: str,
    rotation_count: int,
    max_rotations: int,
) -> List[Dict[str, Any]]:
    """Render an execution plan as Slack Block Kit blocks."""
    blocks: List[Dict[str, Any]] = []

    blocks.append({
        "type": "header",
        "text": {"type": "plain_text", "text": f"📋 待确认计划 · {title[:60]}"},
    })

    summary_bits: List[str] = []
    if plan.get("estimate_min_total"):
        summary_bits.append(f"*预估*：约 {plan['estimate_min_total']} 分钟")
    if plan.get("confidence"):
        summary_bits.append(f"*信心*：{plan['confidence']}")
    if plan.get("deploy_target"):
        summary_bits.append(f"*部署*：{plan['deploy_target']}")
    if summary_bits:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "  ·  ".join(summary_bits)},
        })

    if plan.get("summary"):
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": str(plan["summary"])[:600]},
        })

    steps = plan.get("steps") or []
    if steps:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*📋 步骤（共 {len(steps)} 步）*"},
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
            body = f"*{no}.* {stitle}"
            if detail:
                body += f"\n{detail}"
            if meta_bits:
                body += f"\n`{'  ·  '.join(meta_bits)}`"
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body[:2900]}})
        if len(steps) > 12:
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"_…还有 {len(steps) - 12} 步未展示_"}],
            })

    risks = plan.get("risks") or []
    if risks:
        blocks.append({"type": "divider"})
        risk_lines = "\n".join(f"⚠ {r}" for r in risks[:5])
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": risk_lines}})

    blocks.append({"type": "divider"})
    rotation_note = (
        f"_已修改 {rotation_count}/{max_rotations} 次_"
        if rotation_count > 0
        else "_首次提交_"
    )
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": rotation_note}]})

    can_revise = rotation_count < max_rotations
    blocks.append({"type": "actions", "elements": _plan_buttons(source, user_id, can_revise)})

    return blocks


# ───── Outbound delivery ──────────────────────────────────────────

async def _send_via_post_message(
    receive_id: str,
    *,
    text: str,
    blocks: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if not settings.slack_bot_token:
        return {"ok": False, "skipped": True, "error": "no_bot_token"}
    channel = receive_id or settings.slack_default_channel
    if not channel:
        return {"ok": False, "skipped": True, "error": "no_receive_id"}

    payload: Dict[str, Any] = {"channel": channel, "text": text[:3000]}
    if blocks:
        payload["blocks"] = blocks

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                _POST_MESSAGE_URL,
                headers={
                    "Authorization": f"Bearer {settings.slack_bot_token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json=payload,
            )
            data = resp.json() if resp.text else {}
            if data.get("ok"):
                return {"ok": True, "mode": "post_message", "ts": data.get("ts")}
            return {
                "ok": False,
                "mode": "post_message",
                "error": data.get("error", "unknown"),
            }
    except Exception as e:
        return {"ok": False, "mode": "post_message", "error": str(e)}


async def _send_via_incoming_webhook(
    *,
    text: str,
    blocks: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    url = settings.slack_incoming_webhook
    if not url:
        return {"ok": False, "skipped": True, "error": "no_incoming_webhook"}
    body: Dict[str, Any] = {"text": text[:3000]}
    if blocks:
        body["blocks"] = blocks
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=body)
            return {
                "ok": resp.status_code == 200,
                "mode": "incoming_webhook",
                "status": resp.status_code,
                "error": "" if resp.status_code == 200 else resp.text[:200],
            }
    except Exception as e:
        return {"ok": False, "mode": "incoming_webhook", "error": str(e)}


async def send_message(
    *,
    receive_id: str,
    text: str,
    blocks: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Send a Block Kit / text message. Tries postMessage first, then webhook."""
    pm = await _send_via_post_message(receive_id, text=text, blocks=blocks)
    if pm.get("ok"):
        return pm
    wb = await _send_via_incoming_webhook(text=text, blocks=blocks)
    if wb.get("ok"):
        wb["post_message_error"] = pm.get("error")
        return wb
    return {
        "ok": False,
        "skipped": pm.get("skipped") and wb.get("skipped"),
        "post_message_error": pm.get("error"),
        "webhook_error": wb.get("error"),
    }


async def send_plan_card(
    *,
    receive_id: str,
    title: str,
    plan: Dict[str, Any],
    source: str,
    user_id: str,
    rotation_count: int = 0,
    max_rotations: int = 3,
) -> Dict[str, Any]:
    """Send the rich plan-approval card (Block Kit) with action buttons."""
    blocks = build_plan_blocks(
        title, plan, source, user_id, rotation_count, max_rotations,
    )
    fallback_text = f"📋 待确认计划：{title}（{len(plan.get('steps') or [])} 步）"
    return await send_message(receive_id=receive_id, text=fallback_text, blocks=blocks)


# ───── Inbound signature verification ─────────────────────────────

def verify_signature(
    *,
    timestamp: str,
    raw_body: bytes,
    signature: str,
    max_skew: int = 60 * 5,
) -> bool:
    """Verify a Slack v0 request signature.

    Per Slack docs: the signature header is `v0=<hex>` where hex is
    HMAC-SHA256(signing_secret, b"v0:{timestamp}:{raw_body}").
    """
    secret = settings.slack_signing_secret
    if not secret or not timestamp or not signature:
        return False
    try:
        ts_int = int(timestamp)
    except ValueError:
        return False
    if abs(time.time() - ts_int) > max_skew:
        return False
    base = b"v0:" + timestamp.encode("ascii") + b":" + raw_body
    expected = "v0=" + hmac.new(
        secret.encode("utf-8"), base, hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def extract_card_action(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize a Slack interactivity payload (block_actions) into the same
    shape as Feishu's `extract_card_action`:
      {action, source, user_id, raw_value}

    Returns None when the payload isn't a button click we care about.
    """
    if (payload.get("type") or "") != "block_actions":
        return None
    actions = payload.get("actions") or []
    if not actions:
        return None
    first = actions[0]
    raw_value = first.get("value") or ""
    try:
        value = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
    except Exception:
        value = {}
    if not isinstance(value, dict):
        return None
    action_name = str(value.get("action") or first.get("action_id") or "")
    if not action_name:
        return None

    user_id = (
        str(value.get("user_id") or "")
        or str((payload.get("user") or {}).get("id") or "")
    )
    return {
        "action": action_name,
        "source": str(value.get("source") or "slack"),
        "user_id": user_id,
        "raw_value": value,
        "response_url": payload.get("response_url") or "",
    }


async def respond_to_action(response_url: str, text: str) -> Dict[str, Any]:
    """Quick reply via the interactivity response_url (no scopes required)."""
    if not response_url:
        return {"ok": False, "skipped": True, "error": "no_response_url"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                response_url,
                json={"text": text[:3000], "response_type": "ephemeral"},
            )
            return {"ok": resp.status_code == 200, "status": resp.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}
