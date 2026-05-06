"""Unit tests for the Jira / GitHub inbound webhook bridge.

Covers the four boundaries of the inbound path that the integration
relies on:

1. Signature / token verification (HMAC mismatch ⇒ reject; absent
   secret ⇒ open + warn).
2. Payload parsing — only the events we care about pass through;
   everything else returns ``None`` so callers can short-circuit.
3. Self-loop bounce — comments authored by Agent Hub itself
   (``[Agent Hub] ...``) or by the configured bot account never
   trigger feedback. Without this, the REJECT comment would
   webhook back ⇒ another REJECT ⇒ explosion.
4. Task lookup — only tasks whose ``external_links`` actually
   contain the incoming issue key are routed to feedback.
"""
from __future__ import annotations

import hashlib
import hmac


from app.services.connectors import webhook as wh


# ─────────────────────────────────────────────────────────────────────
# 1. Signature verification
# ─────────────────────────────────────────────────────────────────────


def test_github_signature_open_when_secret_unset(monkeypatch):
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    assert wh.verify_github_signature(b"payload", None) is True
    assert wh.verify_github_signature(b"payload", "sha256=anything") is True


def test_github_signature_passes_with_correct_hmac(monkeypatch):
    secret = "topsecret"
    body = b'{"hello": "world"}'
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert wh.verify_github_signature(body, f"sha256={expected}", secret=secret) is True


def test_github_signature_rejects_wrong_hmac():
    body = b'{"hello": "world"}'
    assert wh.verify_github_signature(body, "sha256=deadbeef", secret="topsecret") is False
    assert wh.verify_github_signature(body, None, secret="topsecret") is False
    assert wh.verify_github_signature(body, "sha1=foo", secret="topsecret") is False


def test_jira_token_open_when_secret_unset(monkeypatch):
    monkeypatch.delenv("JIRA_WEBHOOK_SECRET", raising=False)
    assert wh.verify_jira_token(None) is True
    assert wh.verify_jira_token("anything") is True


def test_jira_token_strict_when_secret_set():
    assert wh.verify_jira_token("good", secret="good") is True
    assert wh.verify_jira_token("bad", secret="good") is False
    assert wh.verify_jira_token(None, secret="good") is False


# ─────────────────────────────────────────────────────────────────────
# 2. Payload parsing — GitHub
# ─────────────────────────────────────────────────────────────────────


def _gh_payload(*, action="created", body="please retry with X",
                login="alice", user_type="User", number=42, full_name="acme/web",
                pr=False):
    issue = {"number": number}
    if pr:
        issue["pull_request"] = {"url": "..."}
    return {
        "action": action,
        "issue": issue,
        "comment": {"body": body, "user": {"login": login, "type": user_type}},
        "repository": {"full_name": full_name},
    }


def test_parse_github_happy_path():
    out = wh.parse_github_issue_comment(_gh_payload())
    assert out is not None
    assert out.kind == "github"
    assert out.issue_key == "acme/web#42"
    assert out.body == "please retry with X"
    assert out.author == "alice"
    assert out.is_self_authored is False


def test_parse_github_drops_non_created_actions():
    assert wh.parse_github_issue_comment(_gh_payload(action="edited")) is None
    assert wh.parse_github_issue_comment(_gh_payload(action="deleted")) is None


def test_parse_github_drops_pr_comments():
    """``issue_comment`` webhook also fires on PR comments — we only
    want plain issues."""
    assert wh.parse_github_issue_comment(_gh_payload(pr=True)) is None


def test_parse_github_drops_garbage():
    assert wh.parse_github_issue_comment({}) is None
    assert wh.parse_github_issue_comment({"action": "created"}) is None
    assert wh.parse_github_issue_comment("not-a-dict") is None


def test_parse_github_self_authored_via_prefix():
    p = _gh_payload(body="[Agent Hub] 评审驳回 → ...")
    out = wh.parse_github_issue_comment(p)
    assert out.is_self_authored is True


def test_parse_github_self_authored_via_bot_user():
    p = _gh_payload(user_type="Bot")
    out = wh.parse_github_issue_comment(p)
    assert out.is_self_authored is True


# ─────────────────────────────────────────────────────────────────────
# 3. Payload parsing — Jira (ADF + plain text)
# ─────────────────────────────────────────────────────────────────────


def _jira_payload(*, event="comment_created", issue_key="AI-7",
                  body="please update schema", author_email="reviewer@acme.com",
                  display_name="Reviewer", body_is_adf=False):
    if body_is_adf:
        body_payload = {
            "type": "doc", "version": 1,
            "content": [
                {"type": "paragraph",
                 "content": [{"type": "text", "text": body}]},
            ],
        }
    else:
        body_payload = body
    return {
        "webhookEvent": event,
        "issue": {"key": issue_key},
        "comment": {
            "body": body_payload,
            "author": {
                "emailAddress": author_email,
                "displayName": display_name,
                "accountId": "acc-123",
            },
        },
    }


def test_parse_jira_happy_path_plain_body():
    out = wh.parse_jira_comment(_jira_payload())
    assert out is not None
    assert out.kind == "jira"
    assert out.issue_key == "AI-7"
    assert out.body == "please update schema"
    assert out.author == "reviewer@acme.com"
    assert out.is_self_authored is False


def test_parse_jira_flattens_adf_body():
    out = wh.parse_jira_comment(_jira_payload(body="hello world", body_is_adf=True))
    assert out.body == "hello world"


def test_parse_jira_drops_other_events():
    assert wh.parse_jira_comment(_jira_payload(event="issue_created")) is None
    assert wh.parse_jira_comment({}) is None


def test_parse_jira_self_authored_via_prefix():
    p = _jira_payload(body="[Agent Hub] 自动评论")
    assert wh.parse_jira_comment(p).is_self_authored is True


def test_parse_jira_self_authored_via_email_match(monkeypatch):
    monkeypatch.setenv("JIRA_EMAIL", "bot@acme.com")
    p = _jira_payload(author_email="bot@acme.com")
    assert wh.parse_jira_comment(p).is_self_authored is True


# ─────────────────────────────────────────────────────────────────────
# 4. Task selection
# ─────────────────────────────────────────────────────────────────────


class _FakeTask:
    def __init__(self, links):
        self.external_links = links


def test_link_matches_normal_case():
    link = {"kind": "jira", "key": "AI-7"}
    assert wh.link_matches(link, "jira", "AI-7") is True
    assert wh.link_matches(link, "JIRA", "AI-7") is True
    assert wh.link_matches(link, "github", "AI-7") is False
    assert wh.link_matches(link, "jira", "AI-8") is False


def test_select_tasks_filters_by_link():
    t1 = _FakeTask([{"kind": "jira", "key": "AI-7"}])
    t2 = _FakeTask([{"kind": "jira", "key": "AI-8"}])
    t3 = _FakeTask([])
    t4 = _FakeTask(None)
    out = wh.select_tasks_for_inbound([t1, t2, t3, t4], "jira", "AI-7")
    assert out == [t1]


def test_select_tasks_handles_legacy_dict_links():
    t = _FakeTask({"kind": "github", "key": "acme/web#42"})
    out = wh.select_tasks_for_inbound([t], "github", "acme/web#42")
    assert out == [t]
