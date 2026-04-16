"""Multi-provider LLM router: routes requests to the correct provider API.

Supports both blocking and streaming modes for all providers.
"""
from __future__ import annotations

import json
import logging
import re
import time
from ipaddress import ip_address
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

PROVIDER_ENDPOINTS: Dict[str, str] = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "deepseek": "https://api.deepseek.com/v1/chat/completions",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    "google": "https://generativelanguage.googleapis.com/v1beta/models",
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

    try:
        addr = ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
            raise ValueError(f"Blocked private/internal address: {hostname}")
    except ValueError as e:
        if "does not appear to be" not in str(e):
            raise

    extra_hosts_env = settings.__dict__.get("llm_allowed_hosts", "")
    extra = {h.strip().lower() for h in extra_hosts_env.split(",") if h.strip()} if extra_hosts_env else set()
    allowed = _ALLOWED_API_HOSTS | extra

    if hostname.lower() not in allowed:
        raise ValueError(
            f"URL host '{hostname}' is not in the allowed list. "
            f"Allowed: {', '.join(sorted(allowed))}"
        )

    return url


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


def _build_anthropic_body(model: str, messages: List[Dict[str, Any]], temperature: float, max_tokens: int) -> Dict[str, Any]:
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
    body: Dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": anthropic_messages,
    }
    if system:
        body["system"] = system
    return body


def _build_gemini_body(messages: List[Dict[str, Any]], temperature: float, max_tokens: int) -> Dict[str, Any]:
    system, conversation = _extract_system_and_messages(messages)
    body: Dict[str, Any] = {
        "contents": [
            {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
            for m in conversation
        ],
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
) -> Dict[str, Any]:
    """Non-streaming chat completion (aggregates full response)."""
    try:
        api_url = _validate_api_url(api_url)
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
                body = _build_anthropic_body(model, messages, temperature, max_tokens)
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
                body = _build_gemini_body(messages, temperature, max_tokens)
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

            # OpenAI-compatible (OpenAI, DeepSeek, Zhipu, Qwen)
            url = api_url or PROVIDER_ENDPOINTS.get(provider, PROVIDER_ENDPOINTS["openai"])
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            body: Dict[str, Any] = {
                "model": model,
                "messages": messages,
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
            if resp.status_code != 200:
                return {"error": resp.text[:2000], "status": resp.status_code, "latency_ms": latency_ms}
            data = resp.json()
            choice = data.get("choices", [{}])[0]
            content = choice.get("message", {}).get("content", "")
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


async def chat_completion_stream(
    *,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float = 0.7,
    max_tokens: int = 4096,
    api_url: str = "",
) -> AsyncIterator[str]:
    """Streaming chat completion — yields SSE-compatible data chunks."""
    try:
        api_url = _validate_api_url(api_url)
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
                body = _build_anthropic_body(model, messages, temperature, max_tokens)
                body["stream"] = True
                async with client.stream("POST", url, headers=headers, json=body) as resp:
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
                body = _build_gemini_body(messages, temperature, max_tokens)
                async with client.stream("POST", url, headers=headers, json=body) as resp:
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
            body = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            }
            async with client.stream("POST", url, headers=headers, json=body) as resp:
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
