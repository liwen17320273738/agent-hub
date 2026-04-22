"""Channel-aware dispatcher for outbound task notifications.

Maps `task.source` ∈ {feishu, qq, openclaw, web, api, ...} to the right
adapter and sends a structured event message.

Usage:
    await notify_task_event(
        task,
        event="started",      # started | progress | preview | completed | failed | feedback_ack
        message="设计阶段完成",
        url="https://...",
    )

All adapters are best-effort: failures are logged, never raised.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ...models.pipeline import PipelineTask
from . import feishu_im, qq_onebot, slack as slack_im

logger = logging.getLogger(__name__)


_EVENT_LABELS: Dict[str, Dict[str, str]] = {
    "started":              {"title": "任务已接收",         "emoji": "🚀", "template": "blue"},
    "progress":             {"title": "进度更新",           "emoji": "⏳", "template": "blue"},
    "preview":              {"title": "预览就绪",           "emoji": "🎉", "template": "green"},
    "awaiting_acceptance":  {"title": "等待最终验收",        "emoji": "🏁", "template": "orange"},
    "completed":            {"title": "已完成上线",         "emoji": "✅", "template": "green"},
    "failed":               {"title": "任务失败",           "emoji": "❌", "template": "red"},
    "feedback_ack":         {"title": "已收到反馈",         "emoji": "📝", "template": "wathet"},
    "iterating":            {"title": "重新处理中",         "emoji": "🔄", "template": "wathet"},
}


@dataclass
class NotifyResult:
    ok: bool
    channel: str
    mode: str = ""
    error: str = ""
    skipped: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "channel": self.channel, "mode": self.mode,
                "error": self.error, "skipped": self.skipped}


def _build_lines(
    task_title: str,
    message: str,
    url: str = "",
    extras: Optional[Dict[str, Any]] = None,
) -> List[str]:
    lines = [f"**项目**：{task_title}"]
    if message:
        lines.append(f"**说明**：{message}")
    if url:
        lines.append(f"**链接**：[{url}]({url})")
    if extras:
        for k, v in extras.items():
            if v is None or v == "":
                continue
            lines.append(f"**{k}**：{v}")
    return lines


async def notify_task_event(
    task: PipelineTask,
    *,
    event: str,
    message: str = "",
    url: str = "",
    extras: Optional[Dict[str, Any]] = None,
) -> NotifyResult:
    """Send a structured event to the channel that originated the task."""
    cfg = _EVENT_LABELS.get(event, {"title": event, "emoji": "ℹ️", "template": "grey"})
    title = f"{cfg['emoji']} {cfg['title']}"
    lines = _build_lines(task.title or "", message, url, extras)
    task_id = str(task.id)
    source = (task.source or "").lower()

    if source == "feishu":
        buttons = None
        if event == "preview":
            buttons = feishu_im.task_action_buttons(task_id)
        elif event == "awaiting_acceptance":
            buttons = feishu_im.final_acceptance_buttons(task_id)
        # When parking at the acceptance terminus, append a tiny prompt so
        # users who *do* type a reply (instead of clicking) know the verbs.
        extra_lines = list(lines)
        if event == "awaiting_acceptance":
            extra_lines.append("回复 **通过 / 上线** 接受，**重做：原因** 打回")
        result = await feishu_im.send_card(
            open_id=task.source_user_id or "",
            title=title,
            lines=extra_lines + [f"`task:{task_id}`"],
            buttons=buttons,
            template=cfg["template"],
        )
        return NotifyResult(
            ok=bool(result.get("ok")),
            channel="feishu",
            mode=result.get("mode", ""),
            error=str(result.get("error", "")),
            skipped=bool(result.get("skipped")),
        )

    if source == "qq":
        qq_lines = list(lines)
        if event == "awaiting_acceptance":
            qq_lines.append("回复「通过」或「上线」接受；回复「重做：原因」打回。")
        result = await qq_onebot.send_text(
            user_id=task.source_user_id or "",
            title=title,
            lines=qq_lines,
            task_id=task_id,
        )
        return NotifyResult(
            ok=bool(result.get("ok")),
            channel="qq",
            mode=result.get("mode", ""),
            error=str(result.get("error", "")),
            skipped=bool(result.get("skipped")),
        )

    if source == "slack":
        slack_blocks = None
        text_lines = "\n".join(lines + [f"`task:{task_id}`"])
        if event == "preview":
            # Render a tiny block-kit card with approve / reject buttons.
            slack_blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": title[:60]}},
                {"type": "section", "text": {"type": "mrkdwn", "text": text_lines[:2900]}},
                {"type": "actions", "elements": slack_im.task_action_buttons(task_id)},
            ]
        elif event == "awaiting_acceptance":
            slack_blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": title[:60]}},
                {"type": "section", "text": {"type": "mrkdwn", "text": text_lines[:2900]}},
                {"type": "actions", "elements": slack_im.final_acceptance_buttons(task_id)},
            ]
        result = await slack_im.send_message(
            receive_id=task.source_user_id or "",
            text=f"{title}\n{text_lines}",
            blocks=slack_blocks,
        )
        return NotifyResult(
            ok=bool(result.get("ok")),
            channel="slack",
            mode=result.get("mode", ""),
            error=str(result.get("error", "")),
            skipped=bool(result.get("skipped")),
        )

    return NotifyResult(ok=False, channel=source or "web", skipped=True, error="no_outbound_channel")


async def notify_user_text(
    source: str,
    user_id: str,
    title: str,
    body: str,
) -> NotifyResult:
    """Send a free-form text message to a user *without* a task context.

    Used by the clarifier to ask follow-up questions before a task exists.
    Best-effort: returns skipped result if channel/credentials are missing.
    """
    src = (source or "").lower()
    if not user_id:
        return NotifyResult(ok=False, channel=src or "web", skipped=True, error="no_user_id")
    lines = body.splitlines() if body else [""]

    if src == "feishu":
        result = await feishu_im.send_card(
            open_id=user_id,
            title=title,
            lines=lines,
            buttons=None,
            template="wathet",
        )
        return NotifyResult(
            ok=bool(result.get("ok")),
            channel="feishu",
            mode=result.get("mode", ""),
            error=str(result.get("error", "")),
            skipped=bool(result.get("skipped")),
        )

    if src == "qq":
        result = await qq_onebot.send_text(
            user_id=user_id,
            title=title,
            lines=lines,
            task_id="",
        )
        return NotifyResult(
            ok=bool(result.get("ok")),
            channel="qq",
            mode=result.get("mode", ""),
            error=str(result.get("error", "")),
            skipped=bool(result.get("skipped")),
        )

    if src == "slack":
        result = await slack_im.send_message(
            receive_id=user_id,
            text=f"*{title}*\n" + "\n".join(lines),
        )
        return NotifyResult(
            ok=bool(result.get("ok")),
            channel="slack",
            mode=result.get("mode", ""),
            error=str(result.get("error", "")),
            skipped=bool(result.get("skipped")),
        )

    return NotifyResult(ok=False, channel=src or "web", skipped=True, error="no_outbound_channel")
