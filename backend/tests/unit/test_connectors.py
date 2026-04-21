"""Unit tests for the issue-tracker connectors.

We mock ``httpx.AsyncClient`` so these tests are hermetic — no
network access needed. Each test verifies the request shape (URL,
auth header, body) and that the connector returns a well-formed
``ConnectorResult`` for the success / API-error / transport-error
cases.

This is the regression net for the connector contract: if a Jira
field name flips or GitHub renames ``html_url``, these tests catch
it before production.
"""
from __future__ import annotations

import pytest

from app.services.connectors import ExternalIssueRef
from app.services.connectors.github import GitHubConnector
from app.services.connectors.jira import JiraConnector
from app.services.connectors.registry import (
    available_connectors,
    get_connector,
    register_connector,
    reset_cache,
)


# ─────────────────────────────────────────────────────────────────────
# Httpx mocking
# ─────────────────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, status_code: int, json_body=None, text: str = ""):
        self.status_code = status_code
        self._json = json_body or {}
        self.text = text or (str(json_body) if json_body else "")

    def json(self):
        return self._json


class _FakeAsyncClient:
    """Minimal replacement for ``httpx.AsyncClient``.

    Records every request issued so the test can assert on URL/headers/
    body, then plays back a fixed response. Use ``calls`` to inspect."""

    def __init__(self, *, responses):
        # Allow either a single response (used for every call) or an
        # iterable of responses keyed by call order.
        if isinstance(responses, _FakeResponse):
            responses = [responses]
        self._responses = list(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def _next_response(self):
        if not self._responses:
            raise AssertionError("FakeAsyncClient: more requests than scripted responses")
        return self._responses.pop(0)

    async def get(self, url, headers=None, **kw):
        self.calls.append({"method": "GET", "url": url, "headers": dict(headers or {})})
        return self._next_response()

    async def post(self, url, headers=None, json=None, **kw):
        self.calls.append({
            "method": "POST", "url": url,
            "headers": dict(headers or {}), "json": json,
        })
        return self._next_response()


@pytest.fixture
def patch_httpx(monkeypatch):
    """Yield a function that installs a fake AsyncClient and returns
    the recorder. Tests call ``client = patch_httpx([...])`` then
    inspect ``client.calls`` after the connector method runs."""
    captured: dict = {}

    def _install(responses):
        client = _FakeAsyncClient(responses=responses)
        captured["client"] = client

        # Patch BOTH the jira and github modules' httpx reference; each
        # imports it independently via ``import httpx`` then uses
        # ``httpx.AsyncClient(...)``.
        import app.services.connectors.jira as _jira
        import app.services.connectors.github as _gh

        class _FakeHttpxModule:
            AsyncClient = lambda *a, **kw: client  # noqa: E731

        monkeypatch.setattr(_jira, "httpx", _FakeHttpxModule)
        monkeypatch.setattr(_gh, "httpx", _FakeHttpxModule)
        return client

    return _install


# ─────────────────────────────────────────────────────────────────────
# JiraConnector
# ─────────────────────────────────────────────────────────────────────


def _jira_conn():
    return JiraConnector(
        base_url="https://acme.atlassian.net",
        email="bot@acme.com",
        token="tok-xyz",
        default_project="AI",
    )


@pytest.mark.asyncio
async def test_jira_healthcheck_success(patch_httpx):
    client = patch_httpx(_FakeResponse(200, {"accountId": "abc"}))
    res = await _jira_conn().healthcheck()
    assert res.ok
    assert res.kind == "jira"
    call = client.calls[0]
    assert call["url"].endswith("/rest/api/3/myself")
    assert call["headers"]["Authorization"].startswith("Basic ")


@pytest.mark.asyncio
async def test_jira_healthcheck_failure_returns_error_not_raise(patch_httpx):
    patch_httpx(_FakeResponse(401, text="bad token"))
    res = await _jira_conn().healthcheck()
    assert not res.ok
    assert "401" in res.error


@pytest.mark.asyncio
async def test_jira_create_issue_success(patch_httpx):
    client = patch_httpx(_FakeResponse(201, {
        "id": "10042", "key": "AI-7",
        "self": "https://acme.atlassian.net/rest/api/3/issue/10042",
    }))
    res = await _jira_conn().create_issue(
        title="Add login feature",
        body="As a user I want to log in.\n\n## Acceptance\n- email/password",
        labels=["ai-generated", "needs-design"],
    )
    assert res.ok
    assert res.issue is not None
    assert res.issue.key == "AI-7"
    assert res.issue.url == "https://acme.atlassian.net/browse/AI-7"
    assert res.issue.project == "AI"

    # Body must be wrapped in ADF, not raw markdown.
    body = client.calls[0]["json"]
    assert body["fields"]["project"]["key"] == "AI"
    assert body["fields"]["summary"] == "Add login feature"
    assert body["fields"]["issuetype"]["name"] == "Story"
    assert body["fields"]["labels"] == ["ai-generated", "needs-design"]
    desc = body["fields"]["description"]
    assert desc["type"] == "doc"
    assert desc["version"] == 1
    # paragraph split on \n\n
    assert len(desc["content"]) >= 2


@pytest.mark.asyncio
async def test_jira_create_issue_skips_when_no_project(patch_httpx):
    """No JIRA_DEFAULT_PROJECT and no project= param → soft-skip,
    don't fire the request and don't raise."""
    client = patch_httpx(_FakeResponse(201, {}))  # should never be hit
    conn = JiraConnector(
        base_url="https://acme.atlassian.net",
        email="x", token="y",
        default_project=None,
    )
    res = await conn.create_issue(title="x", body="x")
    assert not res.ok
    assert res.skipped
    assert "JIRA_DEFAULT_PROJECT" in res.error
    assert client.calls == [], "skipped path must not issue HTTP"


@pytest.mark.asyncio
async def test_jira_add_comment_success(patch_httpx):
    client = patch_httpx(_FakeResponse(201, {"id": "555"}))
    ref = ExternalIssueRef(kind="jira", key="AI-7", url="...", project="AI")
    res = await _jira_conn().add_comment(ref, "REJECTED by AI reviewer: missing auth.")
    assert res.ok
    assert res.comment is not None
    assert res.comment.comment_id == "555"
    assert res.comment.url.endswith("focusedCommentId=555")
    assert "/issue/AI-7/comment" in client.calls[0]["url"]


@pytest.mark.asyncio
async def test_jira_add_comment_handles_missing_ref(patch_httpx):
    res = await _jira_conn().add_comment(
        ExternalIssueRef(kind="jira", key="", url=""), "hi",
    )
    assert not res.ok
    assert res.skipped


@pytest.mark.asyncio
async def test_jira_create_transport_error_caught(monkeypatch):
    """An exception raised by httpx (DNS error, timeout, etc.) must
    not propagate — it becomes a non-ok ConnectorResult so the
    pipeline doesn't crash."""
    import app.services.connectors.jira as _jira

    class _BoomClient:
        async def __aenter__(self):
            raise RuntimeError("dns lookup failed: acme.atlassian.net")

        async def __aexit__(self, *exc):
            return False

    class _BoomHttpx:
        AsyncClient = lambda *a, **kw: _BoomClient()  # noqa: E731

    monkeypatch.setattr(_jira, "httpx", _BoomHttpx)

    res = await _jira_conn().create_issue(title="x", body="x")
    assert not res.ok
    assert "dns lookup failed" in res.error


# ─────────────────────────────────────────────────────────────────────
# GitHubConnector
# ─────────────────────────────────────────────────────────────────────


def _gh_conn():
    return GitHubConnector(token="ghp_xxx", default_repo="acme/web")


@pytest.mark.asyncio
async def test_github_create_issue_success(patch_httpx):
    client = patch_httpx(_FakeResponse(201, {
        "number": 42, "id": 99001,
        "html_url": "https://github.com/acme/web/issues/42",
        "node_id": "I_node_x",
    }))
    res = await _gh_conn().create_issue(
        title="Bug: login retries forever",
        body="Steps:\n1. open /login\n2. submit invalid creds",
        labels=["bug", "p1"],
    )
    assert res.ok
    assert res.issue is not None
    assert res.issue.key == "acme/web#42"
    assert res.issue.url == "https://github.com/acme/web/issues/42"
    assert res.issue.project == "acme/web"

    body = client.calls[0]["json"]
    assert body["title"] == "Bug: login retries forever"
    assert body["labels"] == ["bug", "p1"]
    assert "/repos/acme/web/issues" in client.calls[0]["url"]
    headers = client.calls[0]["headers"]
    assert headers["Authorization"] == "Bearer ghp_xxx"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"


@pytest.mark.asyncio
async def test_github_create_skips_when_no_repo(patch_httpx):
    client = patch_httpx(_FakeResponse(201, {}))
    conn = GitHubConnector(token="x", default_repo=None)
    res = await conn.create_issue(title="x", body="x")
    assert not res.ok and res.skipped
    assert "GITHUB_DEFAULT_REPO" in res.error
    assert client.calls == []


@pytest.mark.asyncio
async def test_github_create_uses_per_call_repo_over_default(patch_httpx):
    client = patch_httpx(_FakeResponse(201, {
        "number": 1, "id": 1,
        "html_url": "https://github.com/other/repo/issues/1",
    }))
    res = await _gh_conn().create_issue(
        title="x", body="x", project="other/repo",
    )
    assert res.ok and res.issue is not None
    assert res.issue.project == "other/repo"
    assert "/repos/other/repo/issues" in client.calls[0]["url"]


@pytest.mark.asyncio
async def test_github_add_comment_success(patch_httpx):
    client = patch_httpx(_FakeResponse(201, {
        "id": 7, "html_url": "https://github.com/acme/web/issues/42#issuecomment-7",
    }))
    ref = ExternalIssueRef(
        kind="github", key="acme/web#42",
        project="acme/web", url="https://github.com/acme/web/issues/42",
    )
    res = await _gh_conn().add_comment(ref, "AI reviewer: missing test for null email.")
    assert res.ok
    assert res.comment is not None
    assert res.comment.comment_id == "7"
    assert "/repos/acme/web/issues/42/comments" in client.calls[0]["url"]


@pytest.mark.asyncio
async def test_github_add_comment_rejects_bad_ref(patch_httpx):
    """Malformed ref (missing project or # in key) should soft-skip."""
    res = await _gh_conn().add_comment(
        ExternalIssueRef(kind="github", key="just-a-string", project="", url=""),
        "x",
    )
    assert not res.ok and res.skipped


@pytest.mark.asyncio
async def test_github_api_error_returns_non_ok_with_message(patch_httpx):
    """4xx/5xx responses become ``ok=false`` with the body in error;
    we don't raise so the pipeline can continue and flag it."""
    patch_httpx(_FakeResponse(422, text='{"message":"Validation Failed"}'))
    res = await _gh_conn().create_issue(title="x", body="x")
    assert not res.ok
    assert "422" in res.error
    assert "Validation Failed" in res.error


# ─────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────


def test_registry_returns_none_when_env_missing(monkeypatch):
    """Without env vars, ``get_connector`` returns None and the
    available list excludes that kind."""
    for var in (
        "JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN",
        "JIRA_DEFAULT_PROJECT", "JIRA_DEFAULT_ISSUE_TYPE",
        "GITHUB_TOKEN", "GITHUB_DEFAULT_REPO", "GITHUB_API_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    reset_cache()
    assert get_connector("jira") is None
    assert get_connector("github") is None
    assert available_connectors() == []


def test_registry_picks_up_env(monkeypatch):
    monkeypatch.setenv("JIRA_BASE_URL", "https://acme.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "bot@acme.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "tok-xyz")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_xxx")
    reset_cache()
    j = get_connector("jira")
    g = get_connector("github")
    assert isinstance(j, JiraConnector)
    assert isinstance(g, GitHubConnector)
    assert sorted(available_connectors()) == ["github", "jira"]


def test_registry_unknown_kind_returns_none():
    reset_cache()
    assert get_connector("trello") is None
    assert get_connector("") is None


def test_register_connector_overrides_cache():
    """Tests use this to inject fakes without setting real env vars."""

    class _Fake:
        kind = "jira"

        async def healthcheck(self):  # pragma: no cover — stub
            return None

        async def create_issue(self, **kw):  # pragma: no cover
            return None

        async def add_comment(self, ref, body):  # pragma: no cover
            return None

    fake = _Fake()
    register_connector("jira", fake)
    try:
        assert get_connector("jira") is fake
        assert "jira" in available_connectors()
    finally:
        reset_cache()
