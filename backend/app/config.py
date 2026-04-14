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

    # Rate limiting
    rate_limit_per_minute: int = 60

    # Model cache TTL
    model_cache_ttl_seconds: int = 600  # 10 minutes

    # Gateway IM channels
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_verification_token: str = ""
    qq_bot_endpoint: str = ""

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
