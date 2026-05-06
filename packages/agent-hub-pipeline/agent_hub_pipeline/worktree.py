from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class WorktreeCheck:
    check_name: str
    status: str
    message: str


@dataclass
class WorktreeQualityReport:
    overall_status: str
    checks: List[WorktreeCheck]
    score: float
    auto_proceed: bool
    suggestions: List[str]


def detect_build_command(worktree: Path) -> Optional[str]:
    """Detect project type and return an appropriate build/test command."""
    try:
        root_files = {f.name for f in worktree.iterdir() if f.is_file()}
        if "package.json" in root_files:
            return "npm install && npm run build"
        if "requirements.txt" in root_files or "setup.py" in root_files or "pyproject.toml" in root_files:
            return "pip install -r requirements.txt && python -m pytest"
        if "Cargo.toml" in root_files:
            return "cargo build"
        if "go.mod" in root_files:
            return "go build ./..."
        if "pom.xml" in root_files:
            return "mvn compile"
        if "build.gradle" in root_files:
            return "./gradlew build"
        if "Makefile" in root_files:
            return "make"
        if "Dockerfile" in root_files:
            return "docker build -t test ."
        for sub in worktree.iterdir():
            if sub.is_dir():
                sub_files = {f.name for f in sub.iterdir() if f.is_file()}
                if "package.json" in sub_files:
                    return f"cd {sub.name} && npm install && npm run build"
        return None
    except Exception as e:
        logger.warning("[pipeline] Build command detection failed: %s", e)
        return None


def verify_worktree_code_quality(worktree: Path) -> Optional[WorktreeQualityReport]:
    """Heuristic code-quality scoring based on files in ``worktree`` (0.0–1.0)."""
    try:
        skip_dirs = {"node_modules", ".git", "__pycache__", ".next", "dist", "build", ".venv", "venv"}
        code_exts = {
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".vue",
            ".go",
            ".rs",
            ".java",
            ".kt",
            ".swift",
            ".cpp",
            ".c",
            ".h",
            ".cs",
            ".rb",
            ".php",
            ".sh",
            ".html",
            ".css",
            ".scss",
            ".sql",
            ".dart",
            ".scala",
        }
        config_names = {
            "requirements.txt",
            "package.json",
            "Dockerfile",
            "Makefile",
            "Cargo.toml",
            "go.mod",
            "pyproject.toml",
            "setup.py",
            "pom.xml",
            "build.gradle",
            "composer.json",
            "Gemfile",
            "CMakeLists.txt",
        }
        placeholder_re = re.compile(r"\b(TODO|FIXME|HACK|XXX|TBD|PLACEHOLDER)\b", re.IGNORECASE)

        code_files: List[Path] = []
        test_files: List[Path] = []
        config_found = False
        empty_files = 0
        placeholder_count = 0

        for root, dirs, filenames in os.walk(worktree):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for fname in filenames:
                fpath = Path(root) / fname
                rel = fpath.relative_to(worktree)
                if fpath.suffix.lower() in code_exts:
                    code_files.append(rel)
                if fname.lower() in config_names:
                    config_found = True
                lower_name = fname.lower()
                if "test" in lower_name or "spec" in lower_name:
                    test_files.append(rel)
                try:
                    size = fpath.stat().st_size
                    if size == 0:
                        empty_files += 1
                except OSError:
                    pass
                if fpath.suffix.lower() in code_exts:
                    try:
                        text = fpath.read_text(encoding="utf-8", errors="ignore")[:50000]
                        placeholder_count += len(placeholder_re.findall(text))
                    except Exception:
                        pass

        checks: List[WorktreeCheck] = []
        total_score = 0.0

        file_score = min(0.50, 0.30 + max(0, len(code_files) - 3) * 0.05)
        total_score += file_score
        checks.append(
            WorktreeCheck(
                "code_file_count",
                "pass" if len(code_files) >= 3 else "warn",
                f"{len(code_files)} code files",
            )
        )

        if config_found:
            total_score += 0.15
            checks.append(WorktreeCheck("config_file", "pass", "Config file found"))
        else:
            checks.append(WorktreeCheck("config_file", "warn", "No config file found"))

        if placeholder_count == 0:
            total_score += 0.15
            checks.append(WorktreeCheck("placeholders", "pass", "No placeholders"))
        else:
            checks.append(
                WorktreeCheck("placeholders", "warn", f"{placeholder_count} placeholders found")
            )

        if test_files:
            total_score += 0.10
            checks.append(WorktreeCheck("test_files", "pass", f"{len(test_files)} test files"))
        else:
            checks.append(WorktreeCheck("test_files", "warn", "No test files"))

        if empty_files == 0:
            total_score += 0.10
            checks.append(WorktreeCheck("non_empty", "pass", "All files non-empty"))
        else:
            checks.append(WorktreeCheck("non_empty", "warn", f"{empty_files} empty files"))

        if total_score >= 0.7:
            overall = "pass"
        elif total_score >= 0.4:
            overall = "warn"
        else:
            overall = "fail"

        return WorktreeQualityReport(
            overall_status=overall,
            checks=checks,
            score=round(total_score, 2),
            auto_proceed=overall != "fail",
            suggestions=[],
        )
    except Exception as e:
        logger.warning("[pipeline] Worktree code quality check failed: %s", e)
        return None
