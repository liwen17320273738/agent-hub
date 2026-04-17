"""Feishu / Lark Event Subscription v2 helpers.

Two relevant operations:

1. **AES-256-CBC decryption** — when the developer enables 加密策略 in
   开放平台 → 事件订阅, every callback body becomes
   `{"encrypt": "<base64 ciphertext>"}`. The key is `SHA256(encrypt_key)`,
   IV is the first 16 bytes of the ciphertext, padding is PKCS#7. The
   plaintext is JSON: either a `url_verification` challenge or a
   real event with `header` + `event` fields.

2. **`url_verification` challenge** — Feishu posts
   `{"challenge": "...", "token": "...", "type": "url_verification"}`
   when you save the callback URL. We MUST verify `token ==
   verification_token` and echo `challenge` back.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets as _secrets
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from ..config import settings

logger = logging.getLogger(__name__)


class FeishuDecryptError(ValueError):
    """Raised when an `encrypt` payload can't be decrypted."""


def _aes_key() -> bytes:
    key = settings.feishu_encrypt_key or ""
    if not key:
        raise FeishuDecryptError("feishu_encrypt_key not configured")
    return hashlib.sha256(key.encode("utf-8")).digest()


def decrypt_payload(encrypt_b64: str) -> Dict[str, Any]:
    """Decrypt a Feishu v2 `encrypt` field. Returns the decoded JSON body."""
    if not encrypt_b64:
        raise FeishuDecryptError("empty encrypt payload")

    try:
        blob = base64.b64decode(encrypt_b64)
    except (ValueError, TypeError) as e:
        raise FeishuDecryptError(f"base64 decode failed: {e}") from e

    if len(blob) < 32 or (len(blob) - 16) % 16 != 0:
        raise FeishuDecryptError("ciphertext has invalid length")

    iv, ciphertext = blob[:16], blob[16:]
    try:
        cipher = Cipher(algorithms.AES(_aes_key()), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
    except Exception as e:
        raise FeishuDecryptError(f"AES decrypt failed: {e}") from e

    if not padded:
        raise FeishuDecryptError("decryption produced empty output")
    pad_len = padded[-1]
    if pad_len < 1 or pad_len > 16 or padded[-pad_len:] != bytes([pad_len]) * pad_len:
        raise FeishuDecryptError("invalid PKCS#7 padding")
    plaintext = padded[:-pad_len]

    try:
        return json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise FeishuDecryptError(f"plaintext is not valid JSON: {e}") from e


def normalize_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    """If body has `encrypt`, decrypt it; otherwise return as-is."""
    if isinstance(raw, dict) and "encrypt" in raw and isinstance(raw["encrypt"], str):
        return decrypt_payload(raw["encrypt"])
    return raw


def verify_token(payload: Dict[str, Any]) -> bool:
    """Constant-time check the body's verification token.

    Feishu places the token in different spots depending on event type:
      - url_verification: payload["token"]
      - v2 events:        payload["header"]["token"]
    """
    expected = settings.feishu_verification_token or ""
    if not expected:
        return False
    candidate = ""
    if isinstance(payload.get("token"), str):
        candidate = payload["token"]
    if not candidate and isinstance(payload.get("header"), dict):
        candidate = payload["header"].get("token", "")
    if not candidate:
        return False
    return _secrets.compare_digest(str(candidate), expected)


def is_url_verification(payload: Dict[str, Any]) -> bool:
    return (
        isinstance(payload, dict)
        and (payload.get("type") == "url_verification" or "challenge" in payload)
    )


def extract_card_action(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return normalized {action, source, user_id, open_id, raw_value} for an
    interactive-card button click. None if this isn't a card.action event.

    Feishu sends two roughly equivalent shapes depending on whether the card
    was sent via group webhook (legacy) or im.message API (v2):

      v2:   {"header":{"event_type":"card.action.trigger"},
              "event":{"action":{"value":{...our payload...}},
                       "operator":{"open_id":"ou_xxx", ...}}}

      legacy: {"action":{"value":{...}}, "open_id":"ou_xxx", "type":"interactive"}
    """
    header = payload.get("header") or {}
    event = payload.get("event") or {}
    event_type = header.get("event_type") or ""

    action_node: Dict[str, Any] = {}
    open_id = ""
    if event_type == "card.action.trigger" or event_type == "card.action":
        action_node = (event.get("action") or {}) if isinstance(event, dict) else {}
        operator = (event.get("operator") or {}) if isinstance(event, dict) else {}
        open_id = (
            operator.get("open_id")
            or operator.get("operator_id", {}).get("open_id", "")
            if isinstance(operator.get("operator_id"), dict) else operator.get("open_id", "")
        )
    elif isinstance(payload.get("action"), dict):
        action_node = payload.get("action") or {}
        open_id = payload.get("open_id") or payload.get("user_open_id") or ""

    if not action_node:
        return None

    value = action_node.get("value") or {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            value = {}
    if not isinstance(value, dict):
        return None

    action_name = str(value.get("action") or "")
    if not action_name:
        return None

    return {
        "action": action_name,
        "source": str(value.get("source") or "feishu"),
        "user_id": str(value.get("user_id") or open_id or ""),
        "open_id": open_id,
        "raw_value": value,
    }


def extract_message(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return a normalized dict {text, user_id, message_id} for a v2 message event.

    Returns None if the payload is not a message event (e.g. card action,
    member-add, etc).
    """
    header = payload.get("header") or {}
    event = payload.get("event") or {}
    event_type = header.get("event_type") or ""
    if event_type and event_type != "im.message.receive_v1":
        return None

    msg = event.get("message") or {}
    if not msg:
        return None

    raw_content = msg.get("content", "{}")
    try:
        text = json.loads(raw_content).get("text", "") if isinstance(raw_content, str) else ""
    except (json.JSONDecodeError, TypeError):
        text = str(raw_content)

    sender = event.get("sender") or {}
    sender_id = sender.get("sender_id") or {}
    user_id = (
        sender_id.get("open_id")
        or sender_id.get("user_id")
        or sender_id.get("union_id")
        or ""
    )

    return {
        "text": (text or "").strip(),
        "user_id": user_id,
        "message_id": msg.get("message_id", ""),
        "chat_type": msg.get("chat_type", ""),
    }
