"""Real-time model registry: fetches latest models from each provider API with Redis caching."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

from ..config import settings
from ..redis_client import cache_get, cache_set

logger = logging.getLogger(__name__)

PROVIDER_CONFIGS: Dict[str, Any] = {
    "openai": {
        "label": "OpenAI",
        "models_url": "https://api.openai.com/v1/models",
        "chat_url": "https://api.openai.com/v1/chat/completions",
        "auth_header": lambda key: {"Authorization": f"Bearer {key}"},
        "filter": lambda m: any(p in (m.get("id") or "") for p in ("gpt", "o1", "o3", "o4", "chatgpt")),
        "parse": lambda m: {
            "id": m["id"],
            "provider": "openai",
            "label": m["id"],
            "owned_by": m.get("owned_by"),
            "created": m.get("created"),
        },
        "data_key": "data",
    },
    "anthropic": {
        "label": "Anthropic",
        "models_url": "https://api.anthropic.com/v1/models",
        "chat_url": "https://api.anthropic.com/v1/messages",
        "auth_header": lambda key: {"x-api-key": key, "anthropic-version": "2023-06-01"},
        "filter": lambda _: True,
        "parse": lambda m: {
            "id": m["id"],
            "provider": "anthropic",
            "label": m.get("display_name") or m["id"],
            "created": int(
                __import__("datetime").datetime.fromisoformat(m["created_at"]).timestamp()
            ) if m.get("created_at") else None,
        },
        "data_key": "data",
    },
    "deepseek": {
        "label": "DeepSeek",
        "models_url": "https://api.deepseek.com/models",
        "chat_url": "https://api.deepseek.com/v1/chat/completions",
        "auth_header": lambda key: {"Authorization": f"Bearer {key}"},
        "filter": lambda _: True,
        "parse": lambda m: {
            "id": m["id"],
            "provider": "deepseek",
            "label": m["id"],
            "owned_by": m.get("owned_by"),
        },
        "data_key": "data",
    },
    "zhipu": {
        "label": "智谱",
        "models_url": "https://open.bigmodel.cn/api/paas/v4/models",
        "chat_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "auth_header": lambda key: {"Authorization": f"Bearer {key}"},
        "filter": lambda _: True,
        "parse": lambda m: {
            "id": m["id"],
            "provider": "zhipu",
            "label": m["id"],
            "owned_by": m.get("owned_by"),
        },
        "data_key": "data",
    },
    "qwen": {
        "label": "通义千问 (DashScope)",
        "models_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
        "chat_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "auth_header": lambda key: {"Authorization": f"Bearer {key}"},
        "filter": lambda m: bool(m.get("id")),
        "parse": lambda m: {
            "id": m["id"],
            "provider": "qwen",
            "label": m["id"],
            "owned_by": m.get("owned_by"),
        },
        "data_key": "data",
    },
    "google": {
        "label": "Google",
        "models_url": None,  # uses key in URL
        "chat_url": "https://generativelanguage.googleapis.com/v1beta/models",
        "auth_header": lambda _: {},
        "filter": lambda m: "generateContent" in (m.get("supportedGenerationMethods") or []),
        "parse": lambda m: {
            "id": (m.get("name") or "").replace("models/", ""),
            "provider": "google",
            "label": m.get("displayName") or m.get("name", ""),
            "description": m.get("description"),
            "context_window": m.get("inputTokenLimit"),
            "max_output": m.get("outputTokenLimit"),
        },
        "data_key": "models",
    },
}

TTL = settings.model_cache_ttl_seconds


def _google_url(key: str) -> str:
    return f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"


async def fetch_provider_models(provider: str, api_key: str) -> List[Dict[str, Any]]:
    cache_key = f"models:{provider}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    config = PROVIDER_CONFIGS.get(provider)
    if not config:
        return []

    url = config["models_url"]
    if provider == "google":
        url = _google_url(api_key)
    if not url:
        return []

    headers = {"Content-Type": "application/json", **config["auth_header"](api_key)}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                logger.warning(f"[model_registry] {provider} returned {resp.status_code}")
                return []
            data = resp.json()
    except Exception as e:
        logger.warning(f"[model_registry] {provider} fetch error: {e}")
        return []

    raw_list = data.get(config["data_key"]) or []
    models = [config["parse"](m) for m in raw_list if config["filter"](m)]

    if models:
        await cache_set(cache_key, models, TTL)
    return models


async def fetch_all_models(api_keys: Optional[Dict[str, str]] = None) -> Dict[str, List[Dict[str, Any]]]:
    if api_keys is None:
        api_keys = settings.get_provider_keys()

    sorted_providers = sorted(api_keys.keys())
    all_cache_key = "models:all:" + ",".join(sorted_providers)
    cached = await cache_get(all_cache_key)
    if cached is not None:
        return cached

    tasks = [
        fetch_provider_models(provider, key)
        for provider, key in api_keys.items()
        if key
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    provider_results: Dict[str, List[Dict[str, Any]]] = {}
    for (provider, _), result in zip(
        [(p, k) for p, k in api_keys.items() if k], results
    ):
        if isinstance(result, list):
            provider_results[provider] = result
        else:
            logger.warning(f"[model_registry] {provider} error: {result}")
            provider_results[provider] = []

    if provider_results:
        await cache_set(all_cache_key, provider_results, TTL)
    return provider_results


async def clear_model_cache() -> None:
    from ..redis_client import cache_delete_pattern
    await cache_delete_pattern("models:*")
