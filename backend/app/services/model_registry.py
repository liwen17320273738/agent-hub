"""Real-time model registry: fetches latest models from each provider API with Redis caching."""
from __future__ import annotations

import asyncio
import hashlib
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


def _llm_models_list_url(chat_url: str) -> str:
    """Derive OpenAI-style ``/v1/models`` URL from a chat/completions base."""
    u = chat_url.strip().rstrip("/")
    if "/v1/chat/completions" in u:
        return u.replace("/v1/chat/completions", "/v1/models")
    if u.endswith("/chat/completions"):
        return u[: -len("chat/completions")] + "models"
    if "/v1/" in u:
        return u.split("/v1/")[0].rstrip("/") + "/v1/models"
    return f"{u}/v1/models"


def _gateway_models_fallback() -> List[Dict[str, Any]]:
    mid = (settings.llm_model or "").strip()
    if not mid:
        return []
    return [{"id": mid, "provider": "gateway", "label": mid, "owned_by": "gateway"}]


async def fetch_gateway_llm_models() -> List[Dict[str, Any]]:
    """List models from the configured ``LLM_API_URL`` OpenAI-compatible gateway.

    The chat UI calls ``GET /models/live`` which only queried hard-coded cloud
    providers; company/LAN gateways keyed as ``local`` had no registry entry.
    This probes ``/v1/models`` and falls back to ``LLM_MODEL`` as a single choice.
    """
    chat_url = (settings.llm_api_url or "").strip()
    api_key = (settings.llm_api_key or "").strip()
    if not chat_url or not api_key:
        return []

    models_url = _llm_models_list_url(chat_url)
    digest = hashlib.sha256(models_url.encode("utf-8")).hexdigest()[:16]
    cache_key = f"models:gateway:{digest}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(
                models_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code != 200:
                logger.debug("[model_registry] gateway GET %s -> %s", models_url, resp.status_code)
                fb = _gateway_models_fallback()
                if fb:
                    await cache_set(cache_key, fb, min(TTL, 120))
                return fb

            data = resp.json()
            raw = data.get("data") if isinstance(data, dict) else None
            if not isinstance(raw, list):
                fb = _gateway_models_fallback()
                if fb:
                    await cache_set(cache_key, fb, min(TTL, 120))
                return fb

            out: List[Dict[str, Any]] = []
            for m in raw:
                if not isinstance(m, dict):
                    continue
                mid = (m.get("id") or "").strip()
                if not mid:
                    continue
                out.append({
                    "id": mid,
                    "provider": "gateway",
                    "label": mid,
                    "owned_by": m.get("owned_by") or "gateway",
                })
            if not out:
                out = _gateway_models_fallback()
            if out:
                await cache_set(cache_key, out, TTL)
            return out
    except Exception as e:
        logger.debug("[model_registry] gateway models error: %s", e)
        fb = _gateway_models_fallback()
        return fb


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
    gw_fingerprint = hashlib.sha256(
        ((settings.llm_api_url or "") + "|" + (settings.llm_api_key or "")[:12]).encode("utf-8"),
    ).hexdigest()[:12]
    all_cache_key = "models:all:" + ",".join(sorted_providers) + ":gw:" + gw_fingerprint
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

    gw_models = await fetch_gateway_llm_models()
    if gw_models:
        provider_results["gateway"] = gw_models

    if provider_results:
        await cache_set(all_cache_key, provider_results, TTL)
    return provider_results


async def clear_model_cache() -> None:
    from ..redis_client import cache_delete_pattern
    await cache_delete_pattern("models:*")
