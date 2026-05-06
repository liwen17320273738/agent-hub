"""Integration tests for the share token system."""
from app.services.share_token import create_share_token, verify_share_token


class TestShareToken:
    def test_create_and_verify(self):
        task_id = "abc-123-def"
        token = create_share_token(task_id, ttl_days=7)
        assert isinstance(token, str)
        assert len(token) > 10

        result = verify_share_token(token)
        assert result == task_id

    def test_different_task_ids(self):
        t1 = create_share_token("task-a", ttl_days=30)
        t2 = create_share_token("task-b", ttl_days=30)
        assert t1 != t2
        assert verify_share_token(t1) == "task-a"
        assert verify_share_token(t2) == "task-b"

    def test_invalid_token_returns_none(self):
        assert verify_share_token("garbage-token-123") is None
        assert verify_share_token("") is None

    def test_tampered_token_returns_none(self):
        token = create_share_token("real-task", ttl_days=7)
        tampered = token[:-3] + "xxx"
        assert verify_share_token(tampered) is None

    def test_ttl_365_days(self):
        token = create_share_token("long-live", ttl_days=365)
        assert verify_share_token(token) == "long-live"

    def test_expired_token_returns_none(self):
        task_id = "expired-task"
        token = create_share_token(task_id, ttl_days=-1)
        assert verify_share_token(token) is None
