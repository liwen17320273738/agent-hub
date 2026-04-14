#!/usr/bin/env python3
"""Agent Hub — Setup Checker

Validates all external service connections and API key configurations.
Run: python3 scripts/setup-check.py
"""
import json
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"
CHECK = f"{GREEN}✓{RESET}"
CROSS = f"{RED}✗{RESET}"
WARN = f"{YELLOW}⚠{RESET}"


def load_env():
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def check_port(host, port, label):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()
        if result == 0:
            print(f"  {CHECK} {label} — {host}:{port}")
            return True
        else:
            print(f"  {CROSS} {label} — {host}:{port} 不可达")
            return False
    except Exception as e:
        print(f"  {CROSS} {label} — {e}")
        return False


def check_api_key(env, key_name, label, url=""):
    val = env.get(key_name, "")
    if val and val != "ollama-local":
        masked = val[:8] + "..." + val[-4:] if len(val) > 16 else val[:4] + "..."
        print(f"  {CHECK} {label} — {masked}")
        return True
    else:
        print(f"  {WARN} {label} — 未配置 ({key_name})")
        return False


def main():
    print(f"\n{BLUE}═══ Agent Hub Setup Check ═══{RESET}\n")

    env = load_env()

    print(f"{BLUE}[1] 基础设施{RESET}")
    pg_ok = check_port("localhost", 5432, "PostgreSQL")
    redis_ok = check_port("localhost", 6379, "Redis")
    ollama_ok = check_port("localhost", 11434, "Ollama (local LLM)")

    print(f"\n{BLUE}[2] LLM API Keys{RESET}")
    llm_keys = []
    for key, label in [
        ("ZHIPU_API_KEY", "智谱 GLM"),
        ("DEEPSEEK_API_KEY", "DeepSeek"),
        ("OPENAI_API_KEY", "OpenAI"),
        ("ANTHROPIC_API_KEY", "Anthropic"),
        ("GOOGLE_API_KEY", "Google Gemini"),
        ("QWEN_API_KEY", "通义千问"),
    ]:
        if check_api_key(env, key, label):
            llm_keys.append(key)

    if not llm_keys and ollama_ok:
        model = env.get("LLM_MODEL", "?")
        print(f"  {CHECK} Ollama 本地 — {model}")
        llm_keys.append("OLLAMA")

    print(f"\n{BLUE}[3] 部署平台{RESET}")
    vercel_ok = check_api_key(env, "VERCEL_TOKEN", "Vercel")
    cf_ok = check_api_key(env, "CLOUDFLARE_API_TOKEN", "Cloudflare Pages")
    mp_ok = check_api_key(env, "WECHAT_MP_APPID", "微信小程序")

    print(f"\n{BLUE}[4] IM 网关{RESET}")
    feishu_ok = check_api_key(env, "FEISHU_APP_ID", "飞书")
    qq_ok = check_api_key(env, "QQ_BOT_ENDPOINT", "QQ Bot")

    print(f"\n{BLUE}═══ 总结 ═══{RESET}")

    score = 0
    total = 4

    if pg_ok and redis_ok:
        print(f"  {CHECK} 数据库 + 缓存: OK")
        score += 1
    elif pg_ok or redis_ok:
        print(f"  {WARN} 数据库/缓存: 部分可用")
        score += 0.5
    else:
        print(f"  {CROSS} 数据库 + 缓存: 不可用 → docker compose up -d db redis")

    if llm_keys:
        print(f"  {CHECK} LLM: {len(llm_keys)} 个提供商已配置")
        score += 1
    else:
        print(f"  {CROSS} LLM: 未配置任何 API Key → 在 .env 中设置")

    if vercel_ok or cf_ok or mp_ok:
        print(f"  {CHECK} 部署平台: 已配置")
        score += 1
    else:
        print(f"  {WARN} 部署平台: 未配置 (可选)")
        score += 0.5

    if feishu_ok or qq_ok:
        print(f"  {CHECK} IM 网关: 已配置")
        score += 1
    else:
        print(f"  {WARN} IM 网关: 未配置 → 可直接调 /api/pipeline/e2e")
        score += 0.5

    pct = int(score / total * 100)
    color = GREEN if pct >= 75 else YELLOW if pct >= 50 else RED
    print(f"\n  {color}准备度: {pct}%{RESET}")

    if pct < 50:
        print(f"\n  {YELLOW}提示: 运行 'docker compose up -d db redis' 并设置至少一个 LLM API Key{RESET}")

    print()
    return 0 if pct >= 50 else 1


if __name__ == "__main__":
    sys.exit(main())
