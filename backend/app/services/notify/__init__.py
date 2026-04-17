"""Outbound IM notification adapters.

Provides a unified `notify_task_event(task, event, **payload)` that routes
preview/progress/completion messages back to the channel that originated
the task (Feishu / QQ / OpenClaw / web).

Each channel has a thin adapter file. All adapters MUST tolerate missing
credentials and degrade to a no-op (returning `{"ok": False, "skipped": True}`)
so the e2e pipeline never fails because of notification issues.
"""
from __future__ import annotations

from .dispatcher import notify_task_event, notify_user_text, NotifyResult
from . import slack  # noqa: F401  — registered for direct imports

__all__ = ["notify_task_event", "notify_user_text", "NotifyResult", "slack"]
