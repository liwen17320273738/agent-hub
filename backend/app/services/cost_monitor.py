"""
Cost Monitor - Real-time cost tracking and budget alerts.

Tracks token consumption per agent/task/model and provides
multi-level budget warnings with auto-downgrade strategies.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CostMonitor:
    """
    Real-time cost monitoring and budget alert system.
    
    Features:
    - Real-time token consumption tracking
    - Multi-level budget alerts (60%/80%/95%)
    - Per-agent and per-task cost breakdown
    - Auto-downgrade strategies
    - Historical spending analytics
    """
    
    def __init__(self):
        # {(task_id, agent_id, model): accumulated_cost}
        self._costs: Dict[tuple, float] = {}
        # {task_id: budget}
        self._budgets: Dict[str, float] = {}
        # {task_id: spending_history}
        self._history: Dict[str, List[Dict]] = {}
        # Alert thresholds
        self._alert_thresholds = [0.6, 0.8, 0.95]
        # Downgrade model tiers (expensive → cheap)
        self._downgrade_tiers = [
            ["gpt-4o", "claude-opus-4", "gemini-2.5-pro"],
            ["gpt-4o-mini", "claude-sonnet-4", "gemini-2.5-flash"],
            ["gpt-3.5-turbo", "claude-haiku-3.5", "deepseek-chat"],
        ]
    
    def set_budget(self, task_id: str, budget_usd: float) -> None:
        """Set budget for a task"""
        self._budgets[task_id] = budget_usd
        logger.info(f"Task {task_id[:8]} budget: ${budget_usd:.2f}")
    
    def record_usage(
        self,
        task_id: str,
        agent_id: str,
        model: str,
        cost_usd: float,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> Dict[str, Any]:
        """
        Record token usage and check budget status.
        
        Returns:
            Dict with budget status and any alerts
        """
        key = (task_id, agent_id, model)
        self._costs[key] = self._costs.get(key, 0.0) + cost_usd
        
        # Record to history
        if task_id not in self._history:
            self._history[task_id] = []
        
        self._history[task_id].append({
            "timestamp": datetime.utcnow().isoformat(),
            "agent": agent_id,
            "model": model,
            "cost": cost_usd,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        })
        
        # Check budget
        budget = self._budgets.get(task_id)
        if budget is None:
            return {"status": "unlimited", "total_cost": self._get_task_cost(task_id)}
        
        total_cost = self._get_task_cost(task_id)
        ratio = total_cost / budget
        
        result = {
            "status": "ok" if ratio < 0.6 else ("warning" if ratio < 0.8 else ("critical" if ratio < 0.95 else "blocked")),
            "total_cost": round(total_cost, 4),
            "budget": budget,
            "ratio": round(ratio * 100, 1),
        }
        
        # Generate alerts
        alerts = []
        for threshold in self._alert_thresholds:
            if ratio >= threshold:
                prev_threshold = self._alert_thresholds[self._alert_thresholds.index(threshold) - 1] if self._alert_thresholds.index(threshold) > 0 else 0
                if ratio - cost_usd / budget < threshold:  # Just crossed this threshold
                    alerts.append(self._generate_alert(task_id, budget, total_cost, threshold))
        
        if alerts:
            result["alerts"] = alerts
        
        return result
    
    def _get_task_cost(self, task_id: str) -> float:
        """Get total cost for a task across all agents/models"""
        return sum(cost for (tid, _, _), cost in self._costs.items() if tid == task_id)
    
    def _generate_alert(
        self, task_id: str, budget: float, total_cost: float, threshold: float
    ) -> Dict[str, Any]:
        """Generate a budget alert"""
        level = "info" if threshold == 0.6 else ("warning" if threshold == 0.8 else "critical")
        
        return {
            "level": level,
            "task_id": task_id,
            "threshold_pct": int(threshold * 100),
            "total_spent": round(total_cost, 4),
            "budget": budget,
            "remaining": round(budget - total_cost, 4),
            "message": self._alert_message(level, task_id, threshold, total_cost, budget),
        }
    
    def _alert_message(
        self, level: str, task_id: str, threshold: float, total_cost: float, budget: float
    ) -> str:
        """Generate human-readable alert message"""
        pct = int(threshold * 100)
        remaining = budget - total_cost
        
        if level == "critical":
            return f"🚨 CRITICAL: Task {task_id[:8]} has used {pct}% of budget (${total_cost:.2f}/{budget:.2f}). Only ${remaining:.2f} remaining."
        elif level == "warning":
            return f"⚠️ WARNING: Task {task_id[:8]} has reached {pct}% of budget (${total_cost:.2f}/{budget:.2f})."
        else:
            return f"ℹ️ INFO: Task {task_id[:8]} has reached {pct}% of budget (${total_cost:.2f}/{budget:.2f})."
    
    def get_downgrade_model(self, current_model: str) -> Optional[str]:
        """
        Get a downgrade model suggestion.
        
        Returns:
            Suggested cheaper model, or None if already at lowest tier
        """
        for i, tier in enumerate(self._downgrade_tiers):
            if current_model in tier:
                if i + 1 < len(self._downgrade_tiers):
                    return self._downgrade_tiers[i + 1][0]
        return None
    
    def get_task_cost_breakdown(self, task_id: str) -> Dict[str, Any]:
        """Get detailed cost breakdown for a task"""
        costs = {}
        
        for (tid, agent_id, model), cost in self._costs.items():
            if tid != task_id:
                continue
            
            if agent_id not in costs:
                costs[agent_id] = {"total": 0, "models": {}}
            
            costs[agent_id]["total"] += cost
            costs[agent_id]["models"][model] = costs[agent_id]["models"].get(model, 0) + cost
        
        return {
            "task_id": task_id,
            "budget": self._budgets.get(task_id),
            "total_cost": sum(c["total"] for c in costs.values()),
            "by_agent": costs,
            "history": self._history.get(task_id, [])[-50:],  # Last 50 entries
        }
    
    def get_dashboard_stats(self) -> Dict[str, Any]:
        """Get cost dashboard statistics"""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        total_today = 0.0
        total_all = sum(self._costs.values())
        
        for task_id in self._history:
            for entry in self._history[task_id]:
                ts = datetime.fromisoformat(entry["timestamp"])
                if ts >= today_start:
                    total_today += entry["cost"]
        
        # Per-agent stats
        agent_costs = {}
        for (_, agent_id, _), cost in self._costs.items():
            agent_costs[agent_id] = agent_costs.get(agent_id, 0) + cost
        
        # Per-model stats
        model_costs = {}
        for (_, _, model), cost in self._costs.items():
            model_costs[model] = model_costs.get(model, 0) + cost
        
        return {
            "total_cost": round(total_all, 4),
            "cost_today": round(total_today, 4),
            "active_tasks": len(self._budgets),
            "alert_count": sum(
                1 for tid in self._budgets
                if self._get_task_cost(tid) / self._budgets[tid] >= 0.6
            ),
            "by_agent": {k: round(v, 4) for k, v in sorted(agent_costs.items(), key=lambda x: x[1], reverse=True)},
            "by_model": {k: round(v, 4) for k, v in sorted(model_costs.items(), key=lambda x: x[1], reverse=True)},
        }
    
    def reset_task(self, task_id: str) -> None:
        """Reset cost tracking for a task"""
        keys_to_delete = [k for k in self._costs if k[0] == task_id]
        for k in keys_to_delete:
            del self._costs[k]
        self._history.pop(task_id, None)
        self._budgets.pop(task_id, None)


# Singleton
_cost_monitor: Optional[CostMonitor] = None


def get_cost_monitor() -> CostMonitor:
    """Get or create the cost monitor singleton"""
    global _cost_monitor
    if _cost_monitor is None:
        _cost_monitor = CostMonitor()
    return _cost_monitor
