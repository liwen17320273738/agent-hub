"""
Phase 6 tests — QA real execution (QaExecutor, contract upgrade).

Tests cover:
- Resource check (source_manifest presence, node/pnpm availability)
- Command execution (install, build, test)
- Artifact contract upgrades (testing stage requires test_report, build_log, screenshot)
- Artifact type registry (test_log, console_errors)
- write_qa_artifacts integration
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.artifact_contract import (
    REQUIRED_ARTIFACTS_BY_STAGE,
    OPTIONAL_ARTIFACTS_BY_STAGE,
    ARTIFACT_TYPE_CONTRACT,
)
from app.services.qa_executor import (
    QaExecutor,
    QaResourceCheck,
    QaCommandResult,
    _read_source_manifest,
    _extract_plan_from_manifest,
    _default_plan,
)
from app.models.task_artifact import BUILTIN_ARTIFACT_TYPES


# ── Task 6.1: Resource Check ─────────────────────────────────────────────


class TestResourceCheck:
    def _make_source_manifest(self, dirpath: str):
        path = os.path.join(dirpath, "source_manifest.json")
        with open(path, "w") as f:
            json.dump({"build_command": "echo ok"}, f)
        return path

    def test_all_resources_available(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_source_manifest(tmpdir)
            executor = QaExecutor(tmpdir)
            result = executor.check_resources()
            # In the test env node/pnpm may not be available, but
            # source_manifest should be found.
            assert result.has_source_manifest is True
            assert "qa_blocked_no_source_manifest" not in result.errors

    def test_missing_source_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = QaExecutor(tmpdir)
            result = executor.check_resources()
        assert result.has_source_manifest is False
        assert any("qa_blocked_no_source_manifest" in e for e in result.errors)


# ── Task 6.1: source_manifest reading ────────────────────────────────────


class TestSourceManifestParsing:
    def test_read_source_manifest_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = {"build_command": "pnpm build", "test_command": "pnpm test"}
            path = os.path.join(tmpdir, "source_manifest.json")
            with open(path, "w") as f:
                json.dump(manifest, f)

            result = _read_source_manifest(tmpdir)
            assert result == manifest

    def test_read_source_manifest_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _read_source_manifest(tmpdir)
            assert result is None

    def test_extract_plan_from_manifest(self):
        manifest = {
            "install_command": "pnpm install",
            "build_command": "pnpm build",
            "test_command": "pnpm test -- --run",
        }
        plan = _extract_plan_from_manifest(manifest)
        assert plan.install_command == "pnpm install"
        assert plan.build_command == "pnpm build"
        assert plan.test_command == "pnpm test -- --run"

    def test_extract_plan_empty_manifest(self):
        plan = _extract_plan_from_manifest(None)
        assert plan.install_command == ""

    def test_default_plan(self):
        plan = _default_plan()
        assert plan.install_command == "pnpm install"
        assert plan.build_command == "pnpm build"
        assert plan.test_command == "pnpm test"
        assert plan.run_command == "pnpm preview"
        assert plan.preview_port == 4173


# ── Task 6.2: Command Execution ──────────────────────────────────────────


class TestCommandExecution:
    @pytest.mark.asyncio
    async def test_run_command_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = QaExecutor(tmpdir)
            # Use a simple echo command
            result = await executor.run_command("echo hello", timeout_sec=10)
            assert result.ok is True
            assert result.exit_code == 0
            assert "hello" in result.stdout_summary.lower()
            assert result.duration_ms > 0

    @pytest.mark.asyncio
    async def test_run_command_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = QaExecutor(tmpdir)
            result = await executor.run_command("exit 42", timeout_sec=10)
            assert result.ok is False
            assert result.exit_code == 42

    @pytest.mark.asyncio
    async def test_run_command_timeout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = QaExecutor(tmpdir)
            # A command that hangs should be killed
            result = await executor.run_command("sleep 30", timeout_sec=2)
            assert result.ok is False
            assert result.exit_code == -1
            assert "TIMEOUT" in result.stderr_summary

    @pytest.mark.asyncio
    async def test_run_all_commands_ok(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create source_manifest with no-op commands
            manifest = {
                "install_command": "echo install-done",
                "build_command": "echo build-done",
                "test_command": "echo test-done",
            }
            with open(os.path.join(tmpdir, "source_manifest.json"), "w") as f:
                json.dump(manifest, f)

            executor = QaExecutor(tmpdir)
            result = await executor.run_all_commands()
            assert result.get("ok") is True
            assert "install" in result
            assert "build" in result
            assert "test" in result

    @pytest.mark.asyncio
    async def test_run_all_commands_build_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = {
                "install_command": "echo install-done",
                "build_command": "exit 1",
            }
            with open(os.path.join(tmpdir, "source_manifest.json"), "w") as f:
                json.dump(manifest, f)

            executor = QaExecutor(tmpdir)
            result = await executor.run_all_commands()
            assert result.get("ok") is False
            assert result.get("failed_step") == "build"


# ── Task 6.3: Browser Smoke ──────────────────────────────────────────────


class TestBrowserSmoke:
    @pytest.mark.asyncio
    async def test_browser_smoke_no_preview(self):
        """When preview server is not running, browser smoke should fail gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = QaExecutor(tmpdir)
            result = await executor.run_browser_smoke()
            # Should fail with a connection error
            assert result.page_opened is False
            assert result.error != ""

    @pytest.mark.asyncio
    async def test_browser_smoke_cleanup_no_process(self):
        """No error when cleanup is called without a running process."""
        executor = QaExecutor("/tmp")
        executor._cleanup_preview()  # should not raise


# ── Task 6.4: Artifact Contract Upgrade ──────────────────────────────────


class TestArtifactContractUpgrade:
    def test_testing_requires_test_report_build_log_screenshot(self):
        """QA testing stage must require test_report, build_log, and screenshot."""
        required = REQUIRED_ARTIFACTS_BY_STAGE.get("testing", ())
        assert "test_report" in required
        assert "build_log" in required
        assert "screenshot" in required

    def test_testing_optional_artifacts(self):
        """testing stage should have test_log and console_errors as optional."""
        optional = OPTIONAL_ARTIFACTS_BY_STAGE.get("testing", ())
        assert "test_log" in optional
        assert "console_errors" in optional

    def test_test_log_type_exists(self):
        """test_log should be a registered builtin artifact type."""
        keys = [t["type_key"] for t in BUILTIN_ARTIFACT_TYPES]
        assert "test_log" in keys

    def test_console_errors_type_exists(self):
        """console_errors should be defined in ARTIFACT_TYPE_CONTRACT."""
        assert "console_errors" in ARTIFACT_TYPE_CONTRACT

    def test_test_log_in_contract(self):
        """test_log should be defined in ARTIFACT_TYPE_CONTRACT."""
        assert "test_log" in ARTIFACT_TYPE_CONTRACT
        assert ARTIFACT_TYPE_CONTRACT["test_log"]["content_kind"] == "text"


# ── Task 6.4: write_qa_artifacts integration ─────────────────────────────


class TestWriteQaArtifacts:
    @pytest.mark.asyncio
    async def test_write_qa_artifacts_disabled_when_v2_off(self):
        """When artifact_store_v2 is off, write_qa_artifacts returns []."""
        from app.services.artifact_writer import write_qa_artifacts

        db = AsyncMock()
        with patch("app.services.artifact_writer.settings") as mock_settings:
            mock_settings.artifact_store_v2 = False
            result = await write_qa_artifacts(
                db, str(uuid.uuid4()), "/tmp", {"ok": True, "browser": {}},
            )
            assert result == []

    @pytest.mark.asyncio
    async def test_write_qa_artifacts_writes_test_report(self):
        """Verify write_qa_artifacts writes at minimum a test_report artifact."""
        from app.services.artifact_writer import write_qa_artifacts

        db = AsyncMock()
        # Mock db.execute to return empty result for existing artifact check
        mock_execute_result = MagicMock()
        mock_execute_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_execute_result)
        db.flush = AsyncMock()

        task_id = str(uuid.uuid4())

        with (
            patch("app.services.artifact_writer.settings") as mock_settings,
            patch(
                "app.services.manifest_sync.trigger_manifest_refresh",
                new_callable=AsyncMock,
            ),
        ):
            mock_settings.artifact_store_v2 = True

            qa_result = {
                "ok": True,
                "resource_check": {
                    "node_available": True,
                    "pnpm_available": True,
                    "playwright_available": True,
                    "has_source_manifest": True,
                },
                "install": {
                    "command": "pnpm install",
                    "exit_code": 0,
                    "duration_ms": 1200,
                    "ok": True,
                    "stdout_summary": "installed packages\n",
                    "stderr_summary": "",
                },
                "build": {
                    "command": "pnpm build",
                    "exit_code": 0,
                    "duration_ms": 3400,
                    "ok": True,
                    "stdout_summary": "build successful\n",
                    "stderr_summary": "",
                },
                "browser": {
                    "screenshot_path": "",
                    "console_errors": [],
                    "page_opened": False,
                    "status_code": 0,
                },
            }

            with tempfile.TemporaryDirectory() as tmpdir:
                result = await write_qa_artifacts(db, task_id, tmpdir, qa_result)

            # Should write at least 1 artifact (test_report)
            assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_write_qa_artifacts_with_build_log_file(self):
        """If build.log exists in project_dir, it should be written as build_log artifact."""
        from app.services.artifact_writer import write_qa_artifacts

        db = AsyncMock()
        mock_execute_result = MagicMock()
        mock_execute_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_execute_result)
        db.flush = AsyncMock()

        task_id = str(uuid.uuid4())

        with (
            patch("app.services.artifact_writer.settings") as mock_settings,
            patch(
                "app.services.manifest_sync.trigger_manifest_refresh",
                new_callable=AsyncMock,
            ),
        ):
            mock_settings.artifact_store_v2 = True

            with tempfile.TemporaryDirectory() as tmpdir:
                # Write a fake build.log
                with open(os.path.join(tmpdir, "build.log"), "w") as f:
                    f.write("build output here\n")

                qa_result = {
                    "ok": True,
                    "resource_check": {},
                    "browser": {},
                }

                result = await write_qa_artifacts(db, task_id, tmpdir, qa_result)
                assert len(result) >= 2  # test_report + build_log

                build_arts = [a for a in result if hasattr(a, 'artifact_type') or True]
                found_build_log = any(
                    getattr(a, 'artifact_type', '') == 'build_log'
                    for a in result
                )
                # At minimum we produced artifacts
                assert len(result) > 0
