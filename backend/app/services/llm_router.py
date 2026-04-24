"""Multi-provider LLM router: routes requests to the correct provider API.

Supports both blocking and streaming modes for all providers.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import time
from ipaddress import ip_address
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

# Fallback chain when the primary provider returns a retriable error
# (rate-limit, insufficient balance, transient 5xx). Order = preference.
# We pick the first whose API key is configured AND that we haven't already
# attempted on the same call. Lives here (not cost_governor) to avoid an
# import cycle between llm_router ↔ cost_governor.
PROVIDER_FALLBACK_CHAIN: List[Dict[str, str]] = [
    {"provider": "local",     "model": settings.llm_model or "default"},
    {"provider": "zhipu",     "model": "glm-4-flash"},
    {"provider": "deepseek",  "model": "deepseek-chat"},
    {"provider": "openai",    "model": "gpt-4o-mini"},
    {"provider": "anthropic", "model": "claude-3-5-haiku-20241022"},
    {"provider": "qwen",      "model": "qwen-turbo"},
    {"provider": "google",    "model": "gemini-2.5-flash"},
]

# Status codes the caller probably wants us to retry on a different provider.
# 401/403 are excluded — those mean "your key is wrong", not "this provider
# is overloaded"; falling back hides a config bug.
_RETRIABLE_HTTP_STATUSES = {402, 408, 429, 500, 502, 503, 504}

# Substrings (case-insensitive) found in upstream error bodies that indicate
# a transient / quota issue rather than a request-shape problem.
_RETRIABLE_ERROR_SUBSTRINGS = (
    "insufficient balance",
    "insufficient_balance",
    "rate limit",
    "rate_limit",
    "ratelimit",
    "您的账户已达到速率限制",
    "quota",
    "1302",            # Zhipu rate-limit
    "1303",            # Zhipu concurrency limit
    "billing_hard_limit",
    "context_length_exceeded",  # not really transient, but useful: degrade to longer-context model
    "overloaded",
    "service unavailable",
    "上游请求超时",
    "上游请求失败",
)


def _is_retriable_failure(result: Dict[str, Any]) -> bool:
    """Return True if the LLM result looks like a transient/quota error.

    Used to decide whether to fall through to the next provider in
    ``chat_completion_with_fallback``.
    """
    status = result.get("status")
    if isinstance(status, int) and status in _RETRIABLE_HTTP_STATUSES:
        return True
    err = (result.get("error") or "")
    if not err:
        return False
    err_low = str(err).lower()
    return any(s in err_low for s in _RETRIABLE_ERROR_SUBSTRINGS)

PROVIDER_ENDPOINTS: Dict[str, str] = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "deepseek": "https://api.deepseek.com/v1/chat/completions",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    "google": "https://generativelanguage.googleapis.com/v1beta/models",
    "local": settings.llm_api_url or "",
}

_ALLOWED_API_HOSTS = {
    "api.openai.com",
    "api.anthropic.com",
    "api.deepseek.com",
    "open.bigmodel.cn",
    "dashscope.aliyuncs.com",
    "generativelanguage.googleapis.com",
}


def _validate_api_url(url: str) -> str:
    """Validate user-supplied api_url against an allowlist to prevent SSRF."""
    if not url:
        return url

    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")

    hostname = parsed.hostname or ""
    if not hostname:
        raise ValueError("Invalid URL: missing hostname")

    extra_hosts_env = (getattr(settings, "llm_allowed_hosts", None) or "").strip()
    extra = {h.strip().lower() for h in extra_hosts_env.split(",") if h.strip()}
    allowed = _ALLOWED_API_HOSTS | extra

    # Explicit allow (public providers + LLM_ALLOWED_HOSTS for local Ollama, etc.).
    if hostname.lower() in allowed:
        return url

    try:
        addr = ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
            raise ValueError(f"Blocked private/internal address: {hostname}")
    except ValueError as e:
        if "does not appear to be" not in str(e):
            raise

    raise ValueError(
        f"URL host '{hostname}' is not in the allowed list. "
        f"Allowed: {', '.join(sorted(allowed))}"
    )


def infer_provider(model: str, api_url: str = "") -> str:
    url = api_url.lower()
    if "anthropic" in url or model.startswith("claude"):
        return "anthropic"
    if "gemini" in url or "googleapis" in url or model.startswith("gemini"):
        return "google"
    if "deepseek" in url or model.startswith("deepseek"):
        return "deepseek"
    if "bigmodel.cn" in url or model.startswith("glm"):
        return "zhipu"
    if "dashscope" in url or model.startswith("qwen"):
        return "qwen"
    if "openai" in url or model.startswith(("gpt", "o1", "o3", "o4")):
        return "openai"
    return "openai"  # default to OpenAI-compatible


def _get_api_key(provider: str) -> str:
    keys = settings.get_provider_keys()
    return keys.get(provider, settings.llm_api_key)


def _first_user_index_in_conversation(conversation: List[Dict[str, Any]]) -> int:
    for idx, m in enumerate(conversation):
        if m.get("role") == "user":
            return idx
    return -1


def _first_user_index_in_messages(messages: List[Dict[str, Any]]) -> int:
    for idx, m in enumerate(messages):
        if m.get("role") == "user":
            return idx
    return -1


def _messages_openai_multimodal(
    messages: List[Dict[str, Any]],
    image_attachments: List[Tuple[str, str]],
) -> List[Dict[str, Any]]:
    """OpenAI-compatible vision: merge images into the first user message (main task; data URLs)."""
    out = copy.deepcopy(messages)
    li = _first_user_index_in_messages(out)
    if li < 0:
        return out
    u = out[li]
    raw = u.get("content", "")
    if isinstance(raw, list):
        return out
    parts: List[Dict[str, Any]] = [{"type": "text", "text": str(raw)}]
    for mime, b64 in image_attachments:
        parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "auto"},
        })
    u["content"] = parts
    return out


def _stringify_message_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif item.get("type") == "image_url":
                    parts.append("[image omitted]")
            else:
                parts.append(str(item))
        return "\n".join(p for p in parts if p)
    return str(content or "")


def _flatten_openai_tool_history(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert tool-call conversation into plain text-only messages.

    Some third-party OpenAI-compatible gateways accept basic chat completions
    but reject OpenAI tool-call history (`role=tool`, `tool_calls`) inside the
    `messages` array. For those endpoints we degrade the history into ordinary
    system/user/assistant turns and retry once.
    """
    flat: List[Dict[str, Any]] = []
    for msg in messages:
        role = str(msg.get("role") or "")
        if role not in ("system", "user", "assistant", "tool"):
            continue

        content = _stringify_message_content(msg.get("content", ""))
        if role == "assistant" and msg.get("tool_calls"):
            tool_lines: List[str] = []
            for tc in msg.get("tool_calls") or []:
                fn = ((tc or {}).get("function") or {}).get("name", "tool")
                args = ((tc or {}).get("function") or {}).get("arguments", "{}")
                tool_lines.append(f"[tool call] {fn}({args})")
            merged = "\n".join(p for p in [content.strip(), *tool_lines] if p).strip()
            flat.append({"role": "assistant", "content": merged or "[tool call requested]"})
            continue

        if role == "tool":
            tool_id = str(msg.get("tool_call_id") or "").strip()
            prefix = f"[tool result {tool_id}]" if tool_id else "[tool result]"
            merged = "\n".join(p for p in [prefix, content.strip()] if p).strip()
            flat.append({"role": "user", "content": merged})
            continue

        flat.append({"role": role, "content": content})
    return flat


def _is_custom_openai_compat(provider: str, api_url: str) -> bool:
    if provider != "openai" or not api_url:
        return False
    try:
        host = (urlparse(api_url).hostname or "").lower()
    except Exception:
        return False
    return bool(host) and host not in _ALLOWED_API_HOSTS


def _extract_system_and_messages(messages: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    system = "\n\n".join(system_parts).strip()
    # 保留 user/assistant/tool 角色，tool_calls 字段也透传
    conversation = []
    for m in messages:
        role = m.get("role")
        if role not in ("user", "assistant", "tool"):
            continue
        entry: Dict[str, Any] = {"role": role, "content": m.get("content") or ""}
        if m.get("tool_calls"):
            entry["tool_calls"] = m["tool_calls"]
        if m.get("tool_call_id"):
            entry["tool_call_id"] = m["tool_call_id"]
        conversation.append(entry)
    return system, conversation


def _build_anthropic_body(
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float,
    max_tokens: int,
    user_images: Optional[List[Tuple[str, str]]] = None,
) -> Dict[str, Any]:
    system, conversation = _extract_system_and_messages(messages)
    anthropic_messages = []
    for m in conversation:
        role = m["role"]
        if role == "tool":
            # tool 结果 → Anthropic 的 user 消息，包含 tool_result block
            anthropic_messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": m.get("tool_call_id", ""),
                    "content": str(m.get("content", "")),
                }],
            })
        elif role == "assistant" and m.get("tool_calls"):
            # assistant 发起工具调用 → tool_use blocks
            content_blocks = []
            if m.get("content"):
                content_blocks.append({"type": "text", "text": str(m["content"])})
            for tc in m["tool_calls"]:
                try:
                    inp = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    inp = {}
                content_blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id", ""),
                    "name": tc["function"]["name"],
                    "input": inp,
                })
            anthropic_messages.append({"role": "assistant", "content": content_blocks})
        else:
            anthropic_messages.append({
                "role": role,
                "content": [{"type": "text", "text": str(m.get("content", ""))}],
            })
    if user_images:
        merged = False
        for m in anthropic_messages:
            if m["role"] != "user" or merged:
                continue
            content = m.get("content")
            if not isinstance(content, list):
                continue
            img_blocks = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": b64,
                    },
                }
                for mime, b64 in user_images
            ]
            m["content"] = img_blocks + content
            merged = True
            break
    body: Dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": anthropic_messages,
    }
    if system:
        body["system"] = system
    return body


def _build_gemini_body(
    messages: List[Dict[str, Any]],
    temperature: float,
    max_tokens: int,
    user_images: Optional[List[Tuple[str, str]]] = None,
) -> Dict[str, Any]:
    system, conversation = _extract_system_and_messages(messages)
    idx_user = _first_user_index_in_conversation(conversation)
    contents: List[Dict[str, Any]] = []
    for i, m in enumerate(conversation):
        role_g = "model" if m["role"] == "assistant" else "user"
        text = str(m.get("content", ""))
        if role_g == "user" and user_images and i == idx_user:
            parts: List[Dict[str, Any]] = [{"text": text}]
            for mime, b64 in user_images:
                mt = "image/jpeg" if mime == "image/jpg" else mime
                parts.append({"inlineData": {"mimeType": mt, "data": b64}})
            contents.append({"role": role_g, "parts": parts})
        else:
            contents.append({"role": role_g, "parts": [{"text": text}]})
    body: Dict[str, Any] = {
        "contents": contents,
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    return body


def _parse_anthropic_response(data: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
    content = ""
    if isinstance(data.get("content"), list):
        content = "".join(item.get("text", "") for item in data["content"] if item.get("type") == "text")
    usage = None
    if data.get("usage"):
        u = data["usage"]
        usage = {
            "prompt_tokens": u.get("input_tokens", 0),
            "completion_tokens": u.get("output_tokens", 0),
            "total_tokens": u.get("input_tokens", 0) + u.get("output_tokens", 0),
        }
    return content, usage


def _parse_gemini_response(data: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
    parts = (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    content = "".join(p.get("text", "") for p in parts)
    usage = None
    if data.get("usageMetadata"):
        u = data["usageMetadata"]
        usage = {
            "prompt_tokens": u.get("promptTokenCount", 0),
            "completion_tokens": u.get("candidatesTokenCount", 0),
            "total_tokens": u.get("totalTokenCount", 0),
        }
    return content, usage


def _extract_openai_message_text(message: Dict[str, Any]) -> str:
    """Extract the most useful text from an OpenAI-compatible message.

    Some third-party compatible gateways return an empty `content` but include
    text inside non-standard fields like `reasoning` / `reasoning_content`.
    """
    content = message.get("content", "")
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        merged = "\n".join(p for p in parts if p).strip()
        if merged:
            return merged

    reasoning = message.get("reasoning")
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning
    if isinstance(reasoning, list):
        parts = []
        for item in reasoning:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        merged = "\n".join(p for p in parts if p).strip()
        if merged:
            return merged

    reasoning_content = message.get("reasoning_content")
    if isinstance(reasoning_content, str) and reasoning_content.strip():
        return reasoning_content
    return ""


async def chat_completion(
    *,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: int = 4096,
    stream: bool = False,
    api_url: str = "",
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    image_attachments: Optional[List[Tuple[str, str]]] = None,
    anthropic_image_attachments: Optional[List[Tuple[str, str]]] = None,
) -> Dict[str, Any]:
    """Non-streaming chat completion (aggregates full response).

    image_attachments: list of (mime_type, base64_raw) for the last user turn.
    Supported: anthropic (native), google (inlineData), openai-compatible (image_url data URLs).
    anthropic_image_attachments is deprecated; use image_attachments.
    """
    imgs = image_attachments if image_attachments is not None else anthropic_image_attachments
    try:
        api_url = _validate_api_url(api_url)
        if (
            not api_url
            and (getattr(settings, "llm_api_url", "") or "").strip()
            and (settings.llm_model or "").strip() == (model or "").strip()
        ):
            api_url = _validate_api_url(settings.llm_api_url)
    except ValueError as e:
        return {"error": str(e), "status": 400}

    provider = infer_provider(model, api_url)
    api_key = _get_api_key(provider)
    started = time.monotonic()

    if not api_key:
        return {"error": f"未配置 {provider} 的 API Key", "status": 503}

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            if provider == "anthropic":
                url = api_url or PROVIDER_ENDPOINTS["anthropic"]
                headers = {"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"}
                body = _build_anthropic_body(model, messages, temperature, max_tokens, user_images=imgs)
                if tools:
                    body["tools"] = _convert_tools_to_anthropic(tools)
                resp = await client.post(url, headers=headers, json=body)
                latency_ms = int((time.monotonic() - started) * 1000)
                if resp.status_code != 200 and imgs:
                    logger.warning(
                        "[llm] Anthropic multimodal failed (%s), retrying text-only",
                        resp.status_code,
                    )
                    body = _build_anthropic_body(
                        model, messages, temperature, max_tokens, user_images=None,
                    )
                    if tools:
                        body["tools"] = _convert_tools_to_anthropic(tools)
                    resp = await client.post(url, headers=headers, json=body)
                    latency_ms = int((time.monotonic() - started) * 1000)
                if resp.status_code != 200:
                    return {"error": resp.text[:2000], "status": resp.status_code, "latency_ms": latency_ms}
                data = resp.json()
                content, usage = _parse_anthropic_response(data)
                result: Dict[str, Any] = {
                    "content": content, "usage": usage,
                    "provider": provider, "model": model, "latency_ms": latency_ms,
                }
                tool_calls = _extract_anthropic_tool_calls(data)
                if tool_calls:
                    result["tool_calls"] = tool_calls
                return result

            if provider == "google":
                base = (api_url or PROVIDER_ENDPOINTS["google"]).rstrip("/")
                url = f"{base}/{model}:generateContent"
                headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
                body = _build_gemini_body(messages, temperature, max_tokens, user_images=imgs)
                resp = await client.post(url, headers=headers, json=body)
                latency_ms = int((time.monotonic() - started) * 1000)
                if resp.status_code != 200 and imgs:
                    logger.warning(
                        "[llm] Gemini multimodal failed (%s), retrying text-only",
                        resp.status_code,
                    )
                    body = _build_gemini_body(messages, temperature, max_tokens, user_images=None)
                    resp = await client.post(url, headers=headers, json=body)
                    latency_ms = int((time.monotonic() - started) * 1000)
                if resp.status_code != 200:
                    return {"error": resp.text[:2000], "status": resp.status_code, "latency_ms": latency_ms}
                data = resp.json()
                content, usage = _parse_gemini_response(data)
                return {
                    "content": content, "usage": usage,
                    "provider": provider, "model": model, "latency_ms": latency_ms,
                }

            # OpenAI-compatible (OpenAI, DeepSeek, Zhipu, Qwen, etc.)
            url = api_url or PROVIDER_ENDPOINTS.get(provider, PROVIDER_ENDPOINTS["openai"])
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            oa_messages = _messages_openai_multimodal(messages, imgs) if imgs else messages
            body: Dict[str, Any] = {
                "model": model,
                "messages": oa_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            }
            if tools:
                body["tools"] = [{"type": "function", "function": t} for t in tools]
                if tool_choice:
                    body["tool_choice"] = tool_choice
            resp = await client.post(url, headers=headers, json=body)
            latency_ms = int((time.monotonic() - started) * 1000)
            if resp.status_code != 200 and imgs:
                logger.warning(
                    "[llm] OpenAI-compatible vision failed (%s), retrying text-only",
                    resp.status_code,
                )
                body["messages"] = messages
                resp = await client.post(url, headers=headers, json=body)
                latency_ms = int((time.monotonic() - started) * 1000)
            if resp.status_code == 400 and _is_custom_openai_compat(provider, url):
                err_text = resp.text[:2000]
                if "messages" in err_text.lower():
                    logger.warning(
                        "[llm] Custom OpenAI-compatible endpoint rejected messages; "
                        "retrying with flattened tool history"
                    )
                    body["messages"] = _flatten_openai_tool_history(messages)
                    resp = await client.post(url, headers=headers, json=body)
                    latency_ms = int((time.monotonic() - started) * 1000)
            if resp.status_code != 200:
                return {"error": resp.text[:2000], "status": resp.status_code, "latency_ms": latency_ms}
            data = resp.json()
            choice = data.get("choices", [{}])[0]
            content = _extract_openai_message_text(choice.get("message", {}) or {})
            usage = data.get("usage")
            result = {
                "content": content, "usage": usage,
                "provider": provider, "model": model, "latency_ms": latency_ms,
            }
            openai_tool_calls = choice.get("message", {}).get("tool_calls")
            if openai_tool_calls:
                result["tool_calls"] = [
                    {
                        "id": tc.get("id", f"call_{i}"),
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"].get("arguments", "{}"),
                        },
                    }
                    for i, tc in enumerate(openai_tool_calls)
                ]
            return result

    except httpx.TimeoutException:
        latency_ms = int((time.monotonic() - started) * 1000)
        return {"error": "上游请求超时", "status": 504, "latency_ms": latency_ms}
    except Exception as e:
        latency_ms = int((time.monotonic() - started) * 1000)
        return {"error": f"上游请求失败: {e}", "status": 502, "latency_ms": latency_ms}


# ---------------------------------------------------------------------------
# Rate-limit aware wrapper: retry 429/1302 on the SAME provider with backoff
# ---------------------------------------------------------------------------
_RATE_LIMIT_BACKOFFS = [2.0, 4.0, 8.0]

_RATE_LIMIT_ERROR_PATTERNS = (
    "rate limit", "rate_limit", "ratelimit",
    "1302", "1303",
    "您的账户已达到速率限制",
    "too many requests",
)


def _is_rate_limited(result: Dict[str, Any]) -> bool:
    if result.get("status") == 429:
        return True
    err = str(result.get("error") or "").lower()
    return any(p in err for p in _RATE_LIMIT_ERROR_PATTERNS)


async def chat_completion_with_retry(
    **kwargs: Any,
) -> Dict[str, Any]:
    """Wrap ``chat_completion`` with same-provider retry on rate limits.

    Retries up to 3 times with exponential backoff (2s / 4s / 8s) before
    giving up. Non-rate-limit errors return immediately.
    """
    result = await chat_completion(**kwargs)
    if not _is_rate_limited(result):
        return result

    for backoff in _RATE_LIMIT_BACKOFFS:
        logger.info(
            "[llm-retry] rate limited on %s, waiting %.0fs before retry",
            kwargs.get("model", "?"), backoff,
        )
        await asyncio.sleep(backoff)
        result = await chat_completion(**kwargs)
        if not _is_rate_limited(result):
            return result

    return result


# ---------------------------------------------------------------------------
# Provider health probe — called at startup to mark providers healthy/unhealthy
# ---------------------------------------------------------------------------
_provider_health: Dict[str, bool] = {}


async def probe_provider(provider: str, model: str) -> bool:
    """Send a minimal request to verify the provider is reachable."""
    try:
        result = await asyncio.wait_for(
            chat_completion(
                model=model,
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.0,
                max_tokens=30,
            ),
            timeout=60.0,
        )
        healthy = bool(result.get("content")) and not result.get("error")
        _provider_health[provider] = healthy
        return healthy
    except (asyncio.TimeoutError, Exception):
        _provider_health[provider] = False
        return False


async def probe_all_providers() -> Dict[str, bool]:
    """Probe all configured providers in parallel. Returns {provider: healthy}."""
    keys = settings.get_provider_keys()
    probe_models = {
        "zhipu": "glm-4-flash",
        "deepseek": "deepseek-chat",
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-5-haiku-20241022",
        "qwen": "qwen-turbo",
        "google": "gemini-2.5-flash",
        "local": settings.llm_model or "default",
    }
    tasks = []
    providers = []
    for provider, key in keys.items():
        if not key:
            continue
        model = probe_models.get(provider, "default")
        providers.append(provider)
        tasks.append(probe_provider(provider, model))

    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for p, r in zip(providers, results):
            if isinstance(r, Exception):
                _provider_health[p] = False
                logger.warning("[llm-probe] %s failed: %s", p, r)
            else:
                status = "healthy" if r else "unhealthy"
                logger.info("[llm-probe] %s: %s %s", p, "✅" if r else "❌", status)

    # Also probe the strong local model if configured
    strong_model = settings.local_llm_model_strong
    if strong_model and "local" in keys:
        try:
            result = await asyncio.wait_for(
                chat_completion(
                    model=strong_model,
                    messages=[{"role": "user", "content": "hi"}],
                    temperature=0.0,
                    max_tokens=30,
                    api_url=settings.llm_api_url or "",
                ),
                timeout=60.0,
            )
            ok = bool(result.get("content")) and not result.get("error")
            logger.info("[llm-probe] local-strong (%s): %s", strong_model[:40], "✅ healthy" if ok else "❌ unhealthy")
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning("[llm-probe] local-strong probe failed: %s", e)

    if not tasks:
        logger.warning("[llm-probe] No providers with API keys configured!")

    return dict(_provider_health)


def get_provider_health() -> Dict[str, bool]:
    return dict(_provider_health)


async def chat_completion_stream(
    *,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: int = 4096,
    api_url: str = "",
    image_attachments: Optional[List[Tuple[str, str]]] = None,
    anthropic_image_attachments: Optional[List[Tuple[str, str]]] = None,
) -> AsyncIterator[str]:
    """Streaming chat completion — yields SSE-compatible data chunks."""
    imgs = image_attachments if image_attachments is not None else anthropic_image_attachments
    try:
        api_url = _validate_api_url(api_url)
        if (
            not api_url
            and (getattr(settings, "llm_api_url", "") or "").strip()
            and (settings.llm_model or "").strip() == (model or "").strip()
        ):
            api_url = _validate_api_url(settings.llm_api_url)
    except ValueError as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        return

    provider = infer_provider(model, api_url)
    api_key = _get_api_key(provider)

    if not api_key:
        yield f"data: {json.dumps({'error': f'未配置 {provider} 的 API Key'})}\n\n"
        return

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            if provider == "anthropic":
                url = api_url or PROVIDER_ENDPOINTS["anthropic"]
                headers = {"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"}
                body = _build_anthropic_body(model, messages, temperature, max_tokens, user_images=imgs)
                body["stream"] = True
                async with client.stream("POST", url, headers=headers, json=body) as resp:
                    if resp.status_code != 200 and imgs:
                        logger.warning(
                            "[llm] Anthropic stream multimodal failed (%s), retry text-only",
                            resp.status_code,
                        )
                        body = _build_anthropic_body(
                            model, messages, temperature, max_tokens, user_images=None,
                        )
                        body["stream"] = True
                        async with client.stream("POST", url, headers=headers, json=body) as resp2:
                            if resp2.status_code != 200:
                                text = await resp2.aread()
                                yield f"data: {json.dumps({'error': text.decode()[:1000]})}\n\n"
                                return
                            async for line in resp2.aiter_lines():
                                if not line.startswith("data: "):
                                    continue
                                payload = line[6:]
                                if payload.strip() == "[DONE]":
                                    break
                                try:
                                    event = json.loads(payload)
                                    delta = event.get("delta", {})
                                    if delta.get("type") == "text_delta":
                                        yield f"data: {json.dumps({'content': delta.get('text', ''), 'provider': provider})}\n\n"
                                except json.JSONDecodeError:
                                    pass
                            yield "data: [DONE]\n\n"
                            return
                    if resp.status_code != 200:
                        text = await resp.aread()
                        yield f"data: {json.dumps({'error': text.decode()[:1000]})}\n\n"
                        return
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:]
                        if payload.strip() == "[DONE]":
                            break
                        try:
                            event = json.loads(payload)
                            delta = event.get("delta", {})
                            if delta.get("type") == "text_delta":
                                yield f"data: {json.dumps({'content': delta.get('text', ''), 'provider': provider})}\n\n"
                        except json.JSONDecodeError:
                            pass
                yield "data: [DONE]\n\n"
                return

            if provider == "google":
                base = (api_url or PROVIDER_ENDPOINTS["google"]).rstrip("/")
                url = f"{base}/{model}:streamGenerateContent?alt=sse"
                headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
                body = _build_gemini_body(messages, temperature, max_tokens, user_images=imgs)
                async with client.stream("POST", url, headers=headers, json=body) as resp:
                    if resp.status_code != 200 and imgs:
                        logger.warning(
                            "[llm] Gemini stream multimodal failed (%s), retry text-only",
                            resp.status_code,
                        )
                        body = _build_gemini_body(messages, temperature, max_tokens, user_images=None)
                        async with client.stream("POST", url, headers=headers, json=body) as resp2:
                            if resp2.status_code != 200:
                                text = await resp2.aread()
                                yield f"data: {json.dumps({'error': text.decode()[:1000]})}\n\n"
                                return
                            async for line in resp2.aiter_lines():
                                if not line.startswith("data: "):
                                    continue
                                payload = line[6:]
                                try:
                                    event = json.loads(payload)
                                    parts = event.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                                    text = "".join(p.get("text", "") for p in parts)
                                    if text:
                                        yield f"data: {json.dumps({'content': text, 'provider': provider})}\n\n"
                                except json.JSONDecodeError:
                                    pass
                            yield "data: [DONE]\n\n"
                            return
                    if resp.status_code != 200:
                        text = await resp.aread()
                        yield f"data: {json.dumps({'error': text.decode()[:1000]})}\n\n"
                        return
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:]
                        try:
                            event = json.loads(payload)
                            parts = event.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                            text = "".join(p.get("text", "") for p in parts)
                            if text:
                                yield f"data: {json.dumps({'content': text, 'provider': provider})}\n\n"
                        except json.JSONDecodeError:
                            pass
                yield "data: [DONE]\n\n"
                return

            # OpenAI-compatible streaming
            url = api_url or PROVIDER_ENDPOINTS.get(provider, PROVIDER_ENDPOINTS["openai"])
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            oa_msgs = _messages_openai_multimodal(messages, imgs) if imgs else messages
            body = {
                "model": model,
                "messages": oa_msgs,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            }
            async with client.stream("POST", url, headers=headers, json=body) as resp:
                if resp.status_code != 200 and imgs:
                    logger.warning(
                        "[llm] OpenAI-compatible stream vision failed (%s), retry text-only",
                        resp.status_code,
                    )
                    body["messages"] = messages
                    async with client.stream("POST", url, headers=headers, json=body) as resp2:
                        if resp2.status_code != 200:
                            text = await resp2.aread()
                            yield f"data: {json.dumps({'error': text.decode()[:1000]})}\n\n"
                            return
                        async for line in resp2.aiter_lines():
                            if line.startswith("data: "):
                                payload = line[6:]
                                if payload.strip() == "[DONE]":
                                    break
                                try:
                                    chunk = json.loads(payload)
                                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                                    c = delta.get("content", "")
                                    if c:
                                        yield f"data: {json.dumps({'content': c, 'provider': provider})}\n\n"
                                except json.JSONDecodeError:
                                    pass
                        yield "data: [DONE]\n\n"
                        return
                if resp.status_code != 200:
                    text = await resp.aread()
                    yield f"data: {json.dumps({'error': text.decode()[:1000]})}\n\n"
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload.strip() == "[DONE]":
                        break
                    try:
                        event = json.loads(payload)
                        delta = event.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield f"data: {json.dumps({'content': content, 'provider': provider})}\n\n"
                    except json.JSONDecodeError:
                        pass
            yield "data: [DONE]\n\n"

    except httpx.TimeoutException:
        yield f"data: {json.dumps({'error': '上游请求超时'})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': f'上游请求失败: {e}'})}\n\n"


def _convert_tools_to_anthropic(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert OpenAI-style tool schemas to Anthropic format."""
    return [
        {"name": t["name"], "description": t.get("description", ""), "input_schema": t.get("parameters", {})}
        for t in tools
    ]


def _extract_anthropic_tool_calls(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract tool_use blocks from Anthropic response, normalized to OpenAI format."""
    result = []
    for i, block in enumerate(data.get("content", [])):
        if block.get("type") == "tool_use":
            result.append({
                "id": block.get("id", f"call_{i}"),
                "function": {
                    "name": block["name"],
                    "arguments": json.dumps(block.get("input", {})),
                },
            })
    return result


# ─────────────────────────────────────────────────────────────────
# Embeddings (OpenAI-compatible /v1/embeddings).
#
# Provider routing reuses the same key-discovery as chat_completion. We map
# `provider → embeddings_endpoint` so a misconfigured chat-completions URL
# doesn't accidentally get reused for embeddings (different schemas).
# ─────────────────────────────────────────────────────────────────

async def chat_completion_with_fallback(
    *,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: int = 4096,
    api_url: str = "",
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    image_attachments: Optional[List[Tuple[str, str]]] = None,
    on_fallback: Optional[
        Callable[[Dict[str, Any]], Awaitable[None]]
    ] = None,
    max_attempts: int = 3,
) -> Dict[str, Any]:
    """Call ``chat_completion`` with primary model, then walk the fallback
    chain on retriable failures (rate-limit, insufficient balance, 5xx).

    Returns the same shape as ``chat_completion`` plus:
        - ``tried_providers``: ``[{provider, model, status, error_excerpt, ok}]``
        - ``fell_back``: bool — True when the *successful* response came from a
          provider other than the one originally requested.

    The caller can supply an ``on_fallback`` async callback that fires *before*
    each retry, with payload ``{from_provider, from_model, to_provider, to_model,
    reason, status, error_excerpt}``. We use this in the pipeline engine to
    emit ``stage:provider-fallback`` SSE events so the UI surfaces what's
    happening rather than freezing.

    Non-retriable errors (401/403/400) short-circuit immediately — those mean
    "your config is wrong", not "this provider is having a bad day".
    """
    primary_provider = infer_provider(model, api_url)
    primary_attempt = {"provider": primary_provider, "model": model}
    available_keys = settings.get_provider_keys()

    tried: List[Dict[str, Any]] = []
    attempts = [primary_attempt]

    # Build fallback list: skip the primary provider, skip providers without keys.
    seen_providers = {primary_provider}
    for cand in PROVIDER_FALLBACK_CHAIN:
        if cand["provider"] in seen_providers:
            continue
        if not available_keys.get(cand["provider"]):
            continue
        attempts.append(dict(cand))
        seen_providers.add(cand["provider"])
        if len(attempts) >= max_attempts:
            break

    logger.info("[llm-fallback] attempts=%s health=%s", attempts, _provider_health)
    last_result: Dict[str, Any] = {}
    for idx, attempt in enumerate(attempts):
        # Skip providers known to be unhealthy (unless it's the primary — always try once)
        if idx > 0 and not _provider_health.get(attempt["provider"], True):
            logger.info("[llm-fallback] skipping %s (marked unhealthy)", attempt["provider"])
            continue
        logger.info("[llm-fallback] trying idx=%d provider=%s model=%s", idx, attempt["provider"], attempt["model"])

        # Primary uses caller's api_url (could be a custom OpenAI-compatible
        # endpoint). Fallbacks always use the canonical provider endpoint.
        attempt_api_url = api_url if idx == 0 else ""
        last_result = await chat_completion_with_retry(
            model=attempt["model"],
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            api_url=attempt_api_url,
            tools=tools,
            tool_choice=tool_choice,
            image_attachments=image_attachments,
        )
        ok = bool(last_result.get("content")) and not last_result.get("error")
        excerpt = (last_result.get("error") or "")[:200] if not ok else ""
        tried.append({
            "provider": attempt["provider"],
            "model": attempt["model"],
            "status": last_result.get("status", 200 if ok else None),
            "error_excerpt": excerpt,
            "ok": ok,
        })
        if ok:
            last_result["tried_providers"] = tried
            last_result["fell_back"] = idx > 0
            return last_result

        # Decide whether to advance or bail.
        if not _is_retriable_failure(last_result) or idx == len(attempts) - 1:
            last_result.setdefault("error", "all providers failed")
            last_result["tried_providers"] = tried
            last_result["fell_back"] = False
            return last_result

        # Notify observers (SSE / metrics) before the next attempt.
        next_attempt = attempts[idx + 1]
        reason = (
            f"primary {attempt['provider']}/{attempt['model']} returned "
            f"status={last_result.get('status')} — {excerpt[:120]}"
        )
        logger.warning("[llm-fallback] %s → %s/%s (reason: %s)",
                       attempt["provider"], next_attempt["provider"],
                       next_attempt["model"], reason)
        if on_fallback is not None:
            try:
                await on_fallback({
                    "from_provider": attempt["provider"],
                    "from_model":    attempt["model"],
                    "to_provider":   next_attempt["provider"],
                    "to_model":      next_attempt["model"],
                    "reason":        reason,
                    "status":        last_result.get("status"),
                    "error_excerpt": excerpt,
                })
            except Exception as cb_err:
                logger.debug("[llm-fallback] on_fallback callback raised: %s", cb_err)

    # Should be unreachable (loop returns inside), but for type-safety:
    last_result.setdefault("error", "no providers attempted")
    last_result["tried_providers"] = tried
    last_result["fell_back"] = False
    return last_result


EMBEDDING_ENDPOINTS: Dict[str, str] = {
    "openai":   "https://api.openai.com/v1/embeddings",
    "deepseek": "https://api.deepseek.com/v1/embeddings",
    "zhipu":    "https://open.bigmodel.cn/api/paas/v4/embeddings",
    "qwen":     "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
}

DEFAULT_EMBEDDING_MODELS: Dict[str, str] = {
    "openai":   "text-embedding-3-small",
    "deepseek": "deepseek-embedding",
    "zhipu":    "embedding-2",
    "qwen":     "text-embedding-v2",
}


async def create_embeddings(
    inputs: List[str],
    *,
    model: str = "",
    provider: str = "",
    batch_size: int = 64,
    timeout: float = 60.0,
) -> Dict[str, Any]:
    """Embed a list of texts; returns {ok, vectors[][], dim, provider, model, usage}.

    On any failure, returns {ok: False, error: "..."} — callers should treat
    embeddings as best-effort and fall back to literal search.
    """
    if not inputs:
        return {"ok": True, "vectors": [], "dim": 0, "provider": "", "model": ""}

    chosen_provider = (provider or "").lower()
    if not chosen_provider:
        keys = settings.get_provider_keys()
        for cand in ("openai", "deepseek", "zhipu", "qwen"):
            if keys.get(cand):
                chosen_provider = cand
                break
    if not chosen_provider:
        return {"ok": False, "error": "no embeddings-capable provider configured"}

    api_key = _get_api_key(chosen_provider)
    if not api_key:
        return {"ok": False, "error": f"no api key for provider {chosen_provider}"}

    chosen_model = model or DEFAULT_EMBEDDING_MODELS.get(chosen_provider, "text-embedding-3-small")
    url = EMBEDDING_ENDPOINTS.get(chosen_provider)
    if not url:
        return {"ok": False, "error": f"provider {chosen_provider} has no embeddings endpoint mapped"}

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    all_vectors: List[List[float]] = []
    total_tokens = 0
    started = time.monotonic()

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            for offset in range(0, len(inputs), batch_size):
                batch = inputs[offset:offset + batch_size]
                resp = await client.post(
                    url, headers=headers,
                    json={"model": chosen_model, "input": batch},
                )
                if resp.status_code != 200:
                    return {
                        "ok": False,
                        "error": f"http {resp.status_code}: {resp.text[:300]}",
                        "provider": chosen_provider, "model": chosen_model,
                    }
                data = resp.json()
                items = data.get("data") or []
                items.sort(key=lambda x: x.get("index", 0))
                for item in items:
                    vec = item.get("embedding") or []
                    if not isinstance(vec, list):
                        continue
                    all_vectors.append([float(x) for x in vec])
                usage = data.get("usage") or {}
                total_tokens += int(usage.get("total_tokens") or 0)
    except Exception as e:
        return {"ok": False, "error": f"embeddings call failed: {e}"}

    dim = len(all_vectors[0]) if all_vectors else 0
    return {
        "ok": True,
        "provider": chosen_provider,
        "model": chosen_model,
        "vectors": all_vectors,
        "dim": dim,
        "usage": {"total_tokens": total_tokens},
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }
