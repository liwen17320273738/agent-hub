from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel


class ProviderModelsOut(BaseModel):
    provider: str
    label: str
    models: List[ModelInfo]


class ModelInfo(BaseModel):
    id: str
    provider: str
    label: str
    owned_by: Optional[str] = None
    description: Optional[str] = None
    context_window: Optional[int] = None
    max_output: Optional[int] = None
    created: Optional[int] = None


class AllModelsOut(BaseModel):
    providers: Dict[str, List[ModelInfo]]
    cached: bool = False


class TokenUsageSummary(BaseModel):
    provider: str
    model: str
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    total_cost_usd: float
    request_count: int


class TokenUsageReport(BaseModel):
    period: str  # day / week / month
    summaries: List[TokenUsageSummary]
    total_cost_usd: float
    total_tokens: int
