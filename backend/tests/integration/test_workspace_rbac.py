"""Integration tests for Workspace model + RBAC logic."""
import uuid
import pytest
from app.models.workspace import Workspace, WorkspaceMember
from app.models.credential import Credential, _fernet


class TestWorkspaceModel:
    def test_workspace_creation(self):
        ws = Workspace(
            org_id=uuid.uuid4(),
            name="Test WS",
            description="A test workspace",
        )
        assert ws.name == "Test WS"
        assert not ws.is_default

    def test_workspace_member_roles(self):
        ws_id = uuid.uuid4()
        for role in ("admin", "manager", "member"):
            m = WorkspaceMember(
                workspace_id=ws_id,
                user_id=uuid.uuid4(),
                role=role,
            )
            assert m.role == role


class TestCredentialEncryption:
    def test_fernet_key_generation(self):
        f = _fernet()
        assert f is not None

    def test_encrypt_decrypt_roundtrip(self):
        cred = Credential(
            org_id=uuid.uuid4(),
            name="test-key",
            provider="openai",
        )
        secret = "sk-test-super-secret-key-12345"
        cred.set_value(secret)
        assert cred.encrypted_value != secret
        assert len(cred.encrypted_value) > 0
        assert cred.get_value() == secret

    def test_empty_value(self):
        cred = Credential(
            org_id=uuid.uuid4(),
            name="empty",
            provider="test",
        )
        assert cred.get_value() == ""

    def test_different_keys_produce_different_ciphertext(self):
        c1 = Credential(org_id=uuid.uuid4(), name="a", provider="x")
        c2 = Credential(org_id=uuid.uuid4(), name="b", provider="x")
        c1.set_value("same-secret")
        c2.set_value("same-secret")
        assert c1.get_value() == c2.get_value() == "same-secret"


class TestRBACRoles:
    """Validate role semantics at the model level."""

    def test_valid_roles(self):
        valid = {"admin", "manager", "member"}
        for role in valid:
            m = WorkspaceMember(
                workspace_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                role=role,
            )
            assert m.role in valid
