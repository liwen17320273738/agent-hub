from __future__ import annotations

from typing import Dict, List

from pydantic_settings import BaseSettings


def _default_db_url() -> str:
    """Use PostgreSQL if available (Docker), fall back to SQLite for zero-dependency dev."""
    import os
    import socket

    pg_url = "postgresql+asyncpg://agenthub:agenthub@localhost:5432/agenthub"
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("localhost", 5432))
        sock.close()
        if result == 0:
            return pg_url
    except Exception:
        pass

    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    db_path = os.path.join(base, "data", "agent-hub.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return f"sqlite+aiosqlite:///{db_path}"


class Settings(BaseSettings):
    app_name: str = "Agent Hub"
    debug: bool = False

    database_url: str = _default_db_url()
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days

    admin_email: str = "admin@example.com"
    admin_password: str = "changeme"

    cors_origins: List[str] = ["http://localhost:5200", "http://127.0.0.1:5200"]

    # Per-provider API keys (all optional)
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    google_api_key: str = ""
    zhipu_api_key: str = ""
    qwen_api_key: str = ""

    # Default LLM
    llm_api_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"

    # Pipeline
    pipeline_api_key: str = ""
    pipeline_upload_dir: str = ""
    pipeline_upload_max_mb: int = 15

    # Git clone allowlist (comma-separated hostnames). Empty = use defaults.
    git_allowed_hosts: str = "github.com,gitee.com,gitlab.com,bitbucket.org,codeup.aliyun.com"

    # Sandbox isolation
    sandbox_use_docker: bool = False         # set to True in prod to run bash/build inside container
    sandbox_docker_image: str = "agent-hub/sandbox:latest"   # overridable; falls back to python:3.11-slim if missing
    sandbox_docker_network: str = "none"     # "none" / "bridge" / a named network
    sandbox_docker_memory: str = "1g"        # docker --memory limit
    sandbox_docker_cpus: str = "1"           # docker --cpus limit
    sandbox_docker_timeout: int = 1800       # hard ceiling for any single container exec (seconds)
    sandbox_strict_bash: bool = True         # stricter command pattern blocking even outside docker

    # Long-task / phase budget
    phase_timeout_seconds: int = 1800        # default per-phase wall clock (was hard-coded 600)
    phase_max_timeout_seconds: int = 7200    # absolute upper bound a stage may request

    # Browser (Playwright) tool
    browser_enabled: bool = True             # registry will skip if Playwright not importable
    browser_max_pages: int = 5
    browser_default_timeout_ms: int = 30000

    # Codebase index
    codebase_index_max_files: int = 5000
    codebase_index_max_file_kb: int = 200    # skip files bigger than this when indexing

    # Plan/Act dual-mode for IM gateway
    # When True: clarifier-success → planner produces a short plan → wait for IM
    #            user to reply 通过/开干/approve before executing.
    # When False (default): clarifier-success creates and dispatches the task
    #            immediately (legacy behavior).
    gateway_plan_mode: bool = False

    # Rate limiting (per-IP, sliding 60s window).
    # 600/min ≈ 10 req/sec — enough headroom for the dashboard's polling fan-out
    # (~7 endpoints/refresh) while still capping abusive clients. Loopback hosts
    # (127.0.0.1, ::1, localhost) bypass the limiter entirely; see rate_limit.py.
    rate_limit_per_minute: int = 600

    # Model cache TTL
    model_cache_ttl_seconds: int = 600  # 10 minutes

    # Gateway IM channels
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_verification_token: str = ""
    feishu_encrypt_key: str = ""    # Feishu Event v2 AES key (set in 开放平台 → 事件订阅 → 加密策略)
    feishu_group_webhook: str = ""  # custom robot webhook (fallback when IM API unavailable)
    qq_bot_endpoint: str = ""        # OneBot v11 HTTP API base url, e.g. http://127.0.0.1:5700
    qq_bot_access_token: str = ""    # OneBot bridge access token (used both for inbound and outbound)

    # Slack — supports two outbound modes (auto-fallback in this order):
    #   1) Bot Token (preferred): chat.postMessage to a user/channel ID
    #   2) Incoming Webhook: posts to a fixed channel
    # And one inbound mode:
    #   - Events API + interactivity → /api/gateway/slack/webhook
    #     (signing_secret used to verify the X-Slack-Signature)
    slack_bot_token: str = ""           # xoxb-... (Bot User OAuth Token)
    slack_signing_secret: str = ""      # used to verify inbound events + interactivity
    slack_default_channel: str = ""     # fallback channel id when receive_id is empty
    slack_incoming_webhook: str = ""    # https://hooks.slack.com/services/...

    # Deploy platforms
    vercel_token: str = ""
    cloudflare_api_token: str = ""
    cloudflare_account_id: str = ""

    # WeChat Mini Program
    wechat_mp_appid: str = ""
    wechat_mp_secret: str = ""
    wechat_mp_private_key_path: str = ""

    # Apple App Store Connect
    appstore_issuer_id: str = ""
    appstore_key_id: str = ""
    appstore_private_key: str = ""

    # Google Play
    google_play_service_account: str = ""
    google_play_package_name: str = ""

    model_config = {
        "env_file": [".env", "../.env"],
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    def get_provider_keys(self) -> Dict[str, str]:
        keys: Dict[str, str] = {}
        mapping = {
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
            "deepseek": self.deepseek_api_key,
            "google": self.google_api_key,
            "zhipu": self.zhipu_api_key,
            "qwen": self.qwen_api_key,
        }
        for provider, key in mapping.items():
            if key:
                keys[provider] = key

        if self.llm_api_key and self.llm_api_url:
            url = self.llm_api_url.lower()
            inferred = None
            if "deepseek" in url:
                inferred = "deepseek"
            elif "openai.com" in url:
                inferred = "openai"
            elif "anthropic" in url:
                inferred = "anthropic"
            elif "bigmodel.cn" in url:
                inferred = "zhipu"
            elif "dashscope" in url:
                inferred = "qwen"
            elif "googleapis" in url or "gemini" in url:
                inferred = "google"
            if inferred and inferred not in keys:
                keys[inferred] = self.llm_api_key

        return keys


settings = Settings()
