"""Unit tests for the v2 artifact system (issuse21 Phase 2-4)."""
from app.models.task_artifact import (
    TaskArtifact,
    ArtifactTypeRegistry,
    BUILTIN_ARTIFACT_TYPES,
)
from app.services.artifact_writer import STAGE_TO_ARTIFACT


class TestArtifactTypeRegistry:
    def test_builtin_types_count(self):
        assert len(BUILTIN_ARTIFACT_TYPES) == 12

    def test_builtin_types_all_have_required_keys(self):
        required = {"type_key", "category", "display_name", "icon", "tab_group", "sort_order"}
        for spec in BUILTIN_ARTIFACT_TYPES:
            missing = required - set(spec.keys())
            assert not missing, f"{spec['type_key']} missing: {missing}"

    def test_type_keys_unique(self):
        keys = [t["type_key"] for t in BUILTIN_ARTIFACT_TYPES]
        assert len(keys) == len(set(keys))

    def test_registry_model_fields(self):
        reg = ArtifactTypeRegistry(
            type_key="test_type",
            category="test",
            display_name="Test",
            icon="🧪",
            tab_group="test",
            sort_order=99,
        )
        assert reg.type_key == "test_type"
        assert reg.is_builtin is None or reg.is_builtin is True

    def test_sort_order_sequential(self):
        orders = [t["sort_order"] for t in BUILTIN_ARTIFACT_TYPES]
        assert orders == sorted(orders), "Builtin types should be in sort_order sequence"


class TestTaskArtifactModel:
    def test_model_creation(self):
        import uuid
        art = TaskArtifact(
            task_id=uuid.uuid4(),
            artifact_type="prd",
            title="PRD v1",
            content="# Product Requirements",
            version=1,
        )
        assert art.artifact_type == "prd"
        assert art.version == 1
        assert art.is_latest is None or art.is_latest is True
        assert art.status is None or art.status == "active"

    def test_default_mime_type(self):
        import uuid
        art = TaskArtifact(task_id=uuid.uuid4(), artifact_type="brief")
        assert art.mime_type is None or art.mime_type == "text/markdown"


class TestStageToArtifactMapping:
    def test_all_standard_stages_mapped(self):
        expected_stages = {"planning", "design", "architecture", "development", "testing", "reviewing", "deployment"}
        assert set(STAGE_TO_ARTIFACT.keys()) == expected_stages

    def test_mapping_values_are_valid_types(self):
        valid_types = {t["type_key"] for t in BUILTIN_ARTIFACT_TYPES}
        for stage, art_type in STAGE_TO_ARTIFACT.items():
            assert art_type in valid_types, f"Stage {stage} maps to invalid type: {art_type}"

    def test_deployment_maps_to_ops_runbook_tab(self):
        assert STAGE_TO_ARTIFACT["deployment"] == "ops_runbook"


class TestConfigFlag:
    def test_artifact_store_v2_default(self):
        from app.config import settings
        assert hasattr(settings, "artifact_store_v2")
        assert isinstance(settings.artifact_store_v2, bool)


class TestManifestSync:
    def test_imports_cleanly(self):
        from app.services.manifest_sync import rebuild_manifest, trigger_manifest_refresh
        assert callable(rebuild_manifest)
        assert callable(trigger_manifest_refresh)


class TestWorkspaceArchiver:
    def test_imports_cleanly(self):
        from app.services.workspace_archiver import archive_stale_tasks
        assert callable(archive_stale_tasks)

    def test_constants(self):
        from app.services.workspace_archiver import ACCEPTED_AGE_DAYS, CANCELLED_AGE_DAYS
        assert ACCEPTED_AGE_DAYS == 30
        assert CANCELLED_AGE_DAYS == 7
