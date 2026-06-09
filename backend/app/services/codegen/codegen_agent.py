"""
CodeGen Agent — 通过 Claude Code CLI 或 Codex CLI 编排代码生成。

引擎自动切换策略：
1. 检测 claude / codex CLI 是否可用
2. 默认优先 Claude Code（质量更高），不可用时自动切换 Codex
3. 可通过 use_claude_code=False 跳过 Claude Code 直接用 Codex
4. 两个引擎都不可用时返回明确错误

Workflow:
1. 可选的项目模板脚手架
2. 根据 PRD + 架构输出构建详细 prompt
3. 自动选择可用引擎执行代码生成
4. 验证构建并返回结果
5. 写入 source_manifest.json + build.log 到 project_dir
6. 文件路径白名单检查
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .templates import scaffold_project, get_template
from ..tools.sandbox import get_sandbox_root
from ..tools import execute_tool

logger = logging.getLogger(__name__)

# Phase 4: max 2 auto-fix retries
MAX_FIX_RETRIES = 2

# Allowlist: only these paths may be created/modified by codegen
ALLOWED_FILE_PREFIXES = frozenset({
    "src/",
    "public/",
    "package.json",
    "vite.config.ts",
    "vitest.config.ts",
    "tsconfig.json",
    ".gitignore",
})


def _detect_available_engines() -> Dict[str, bool]:
    """检测可用的代码生成引擎 CLI。

    Returns {"claude": bool, "codex": bool}
    结果会被缓存（TTL 5 分钟），避免重复检测。
    """
    _now = datetime.now().timestamp()
    _cache_ttl = 300  # 5 minutes
    if not hasattr(_detect_available_engines, "_cache") or (
        hasattr(_detect_available_engines, "_cache_at")
        and (_now - _detect_available_engines._cache_at) > _cache_ttl
    ):
        claude_bin = os.environ.get("CLAUDE_PATH") or shutil.which("claude") or "claude"
        codex_bin = os.environ.get("CODEX_PATH") or shutil.which("codex") or "codex"

        _detect_available_engines._cache = {
            "claude": shutil.which(claude_bin) is not None,
            "codex": shutil.which(codex_bin) is not None,
        }
        _detect_available_engines._cache_at = _now
        logger.info(
            "[codegen] Engine availability: claude=%s codex=%s",
            _detect_available_engines._cache["claude"],
            _detect_available_engines._cache["codex"],
        )

    return _detect_available_engines._cache


def _check_inputs(pipeline_outputs: Dict[str, str]) -> Optional[str]:
    """Return error message if required inputs are missing, else None."""
    if not pipeline_outputs.get("planning", "").strip():
        return "missing_required_input:planning"
    if not pipeline_outputs.get("architecture", "").strip():
        return "missing_required_input:architecture"
    return None


def _enforce_allowlist(project_dir: str, template_files_baseline: set) -> List[str]:
    """Check project_dir for files outside allowed prefixes.

    Returns a list of offending file paths (relative). Does NOT delete files.
    """
    allowed = set(ALLOWED_FILE_PREFIXES)
    # All files that existed in the baseline are grandfathered in
    baseline = template_files_baseline
    offenders: List[str] = []
    _skip_allowlist_dirs = {"node_modules", ".git", "__pycache__", ".next", "dist", "build", ".venv", "venv"}
    for root, dirs, filenames in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in _skip_allowlist_dirs]
        for fn in filenames:
            rel = os.path.relpath(os.path.join(root, fn), project_dir)
            if rel in baseline:
                continue
            if any(rel.startswith(p) for p in allowed):
                continue
            offenders.append(rel)
    return sorted(set(offenders))


def _load_template_baseline(project_dir: str) -> set:
    """Record all files present in project_dir at scaffold time (before codegen writes)."""
    baseline: set = set()
    for root, _dirs, filenames in os.walk(project_dir):
        for fn in filenames:
            rel = os.path.relpath(os.path.join(root, fn), project_dir)
            baseline.add(rel)
    return baseline


def _build_source_manifest(
    project_dir: str,
    template_baseline: set,
    build_cmd: str,
    dev_cmd: str,
    test_cmd: str,
    build_success: bool,
) -> dict:
    """Build source_manifest dict from project_dir state."""
    all_files = _scan_project_files(project_dir)
    created = sorted(set(all_files) - template_baseline)
    modified = sorted(set(all_files) & template_baseline)

    return {
        "created_files": created,
        "modified_files": modified,
        "total_files": len(all_files),
        "build_command": build_cmd or "",
        "run_command": dev_cmd or "",
        "test_command": test_cmd or "",
        "build_success": build_success,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _write_source_manifest(project_dir: str, manifest: dict) -> Optional[str]:
    """Write source_manifest.json to project_dir, return its path or None on failure."""
    path = os.path.join(project_dir, "source_manifest.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        return path
    except IOError as e:
        logger.error("[codegen] Failed to write source_manifest.json: %s", e)
        return None


def _write_build_log(project_dir: str, log_text: str) -> Optional[str]:
    """Append build.log to project_dir, return its path or None on failure."""
    path = os.path.join(project_dir, "build.log")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(log_text)
        return path
    except IOError as e:
        logger.error("[codegen] Failed to write build.log: %s", e)
        return None


def _build_claude_prompt(
    task_title: str,
    pipeline_outputs: Dict[str, str],
    template_id: Optional[str] = None,
) -> str:
    """Build a comprehensive prompt for Claude Code from pipeline stage outputs."""
    sections = [f"# 项目: {task_title}\n"]

    stage_labels = {
        "planning": "产品需求 (PRD)",
        "design": "UI/UX 设计",
        "architecture": "技术架构方案",
        "development": "开发要求",
        "testing": "测试要求",
    }
    for stage_id in ["planning", "design", "architecture", "development", "testing"]:
        content = pipeline_outputs.get(stage_id, "")
        if content:
            label = stage_labels.get(stage_id, stage_id)
            sections.append(f"## {label}\n\n{content[:6000]}\n")

    if template_id:
        tmpl = get_template(template_id)
        if tmpl:
            sections.append(f"## 项目模板: {tmpl.get('name', template_id)}")
            sections.append(f"技术栈: {', '.join(tmpl.get('stack', []))}")
            if tmpl.get("build_cmd"):
                sections.append(f"构建命令: `{tmpl['build_cmd']}`")
            if tmpl.get("dev_cmd"):
                sections.append(f"开发命令: `{tmpl['dev_cmd']}`\n")

    sections.append("""## 执行要求

请根据以上需求和架构方案，在当前目录下生成完整的、可运行的项目代码：

1. **创建项目结构** — 按照架构方案组织文件目录
2. **编写所有代码文件** — 包含完整的业务逻辑，不要写 TODO 或占位符
3. **安装依赖** — 运行 npm install / pip install 等
4. **构建项目** — 确保构建通过
5. **如果构建失败** — 分析错误并修复，直到构建成功

最终确认：列出所有创建的文件和构建状态。""")

    return "\n\n".join(sections)


def _build_fix_prompt(error_output: str, attempt: int) -> str:
    """Build a prompt for Claude Code to fix build/test errors."""
    return f"""构建或测试失败（第 {attempt} 次尝试）。请分析以下错误并修复：

```
{error_output[:4000]}
```

要求：
1. 分析根本原因
2. 修复相关文件
3. 重新安装依赖（如需要）
4. 重新构建并确认通过

只修复问题，不要重写不相关的文件。"""


def _build_home_view_prompt(
    task_title: str, prd: str, design: str, template_home: str
) -> str:
    """Prompt to customize a single self-contained Vue SFC from the PRD."""
    return f"""基于以下产品需求，为「{task_title}」生成一个**单文件 Vue3 组件**作为应用首页（替换脚手架的 Home.vue）。

## 产品需求（PRD 摘要）
{prd}

## 设计要点
{design}

## 硬性约束（必须遵守，否则构建失败）
1. 只能用 Vue 3 `<script setup lang="ts">` + `<template>` + `<style scoped>` 三段式。
2. **禁止** import 任何第三方库；只能从 'vue' 导入 ref/computed/onMounted/watch 等。不要 import 组件、不要用 element-plus/axios 等。
3. 所有逻辑、样式自包含在这一个文件里。需要持久化用 localStorage 即可。
4. 必须通过 TypeScript 严格编译（vue-tsc --noEmit）：所有变量/函数标注类型，无未使用变量、无 any 滥用。
5. 直接输出**一个** ```vue 代码块，不要任何解释文字。

## 当前脚手架 Home.vue（供参考结构）
```vue
{template_home[:1200]}
```"""


def _extract_single_vue_sfc(text: str) -> str:
    """Extract a *complete* single Vue SFC from an LLM response.

    Returns "" for truncated output (missing closing tags). A partial SFC would
    fail `vite build` ("Element is missing end tag") and force a revert to the
    bare template — discarding all generated features. Rejecting incomplete
    output lets the caller keep the (working) scaffold instead of writing
    guaranteed-broken code.
    """
    if not text:
        return ""
    m = re.search(r"```(?:vue|html)?\s*\n(.*?)\n```", text, re.DOTALL)
    if m:
        candidate = m.group(1).strip()
    elif "<template>" in text:
        candidate = text.strip()
    else:
        return ""
    # Require a balanced <template> block and, if present, balanced <script>/<style>.
    if "<template>" not in candidate or "</template>" not in candidate:
        return ""
    if "<script" in candidate and "</script>" not in candidate:
        return ""
    if "<style" in candidate and "</style>" not in candidate:
        return ""
    return candidate


class CodeGenAgent:
    """编排代码生成：自动检测可用引擎，Claude Code 优先，Codex 自动降级。

    引擎选择策略：
    - 检测 claude / codex CLI 是否安装
    - Claude Code 可用 → 优先使用；不可用 → 自动切换 Codex
    - use_claude_code=False → 跳过 Claude Code，直接用 Codex
    - 两个引擎都不可用 → 返回明确错误，不再浪费时间尝试
    """

    def __init__(self, workspace: Optional[str] = None):
        self.workspace = workspace or os.path.join(get_sandbox_root(), "projects")
        os.makedirs(self.workspace, exist_ok=True)

    async def generate_from_pipeline(
        self,
        task_id: str,
        task_title: str,
        pipeline_outputs: Dict[str, str],
        template_id: Optional[str] = None,
        use_claude_code: bool = True,
        existing_project_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate project code from pipeline stage outputs.

        Phase 4 additions:
        - Input guard: planning + architecture required
        - source_manifest.json + build.log written to project_dir
        - Allowlist enforcement after generation
        """
        # Phase 4: input guard
        missing = _check_inputs(pipeline_outputs)
        if missing:
            return {"ok": False, "error": missing}

        if existing_project_dir and os.path.isdir(existing_project_dir):
            project_dir = existing_project_dir
            logger.info(f"[codegen] Using existing project: {project_dir}")
        else:
            project_dir = os.path.join(self.workspace, _slugify(task_title))
            os.makedirs(project_dir, exist_ok=True)
            if template_id:
                scaffold_result = scaffold_project(template_id, task_title, project_dir)
                if not scaffold_result.get("ok"):
                    return scaffold_result

        # Record template baseline before codegen touches files
        template_baseline = _load_template_baseline(project_dir)

        # 自动检测可用引擎
        engines = _detect_available_engines()
        result: Dict[str, Any] = {"ok": False, "error": "no engine ran", "project_dir": project_dir}

        # --- 引擎选择与执行 ---
        claude_available = engines.get("claude", False)
        codex_available = engines.get("codex", False)
        try_claude = use_claude_code and claude_available

        if use_claude_code and not claude_available:
            logger.warning(
                "[codegen] Claude Code CLI 不可用 (which=%s)，自动切换 Codex",
                os.environ.get("CLAUDE_PATH") or shutil.which("claude") or "claude",
            )
            if codex_available:
                logger.info("[codegen] Codex CLI 可用，直接使用 Codex")
            else:
                logger.error("[codegen] Claude Code 和 Codex CLI 都不可用，无法生成代码")

        if try_claude:
            logger.info("[codegen] 使用 Claude Code (primary engine)")
            result = await self._generate_via_claude_code(
                task_id, task_title, project_dir, pipeline_outputs, template_id,
            )
            if not result.get("ok"):
                logger.warning(
                    "[codegen] Claude Code failed: %s, trying Codex fallback",
                    result.get("error"),
                )

        # Codex fallback：Claude Code 失败或未启用时自动切换
        if not result.get("ok"):
            if codex_available:
                logger.info("[codegen] 使用 Codex (fallback engine)")
                result = await self._generate_via_codex(
                    task_id, task_title, project_dir, pipeline_outputs, template_id,
                )
                if not result.get("ok"):
                    logger.warning("[codegen] Codex failed: %s, trying self-contained llm-local engine", result.get("error"))
            else:
                logger.warning("[codegen] Codex CLI 不可用，切换到 self-contained llm-local engine")

        # Self-contained fallback：CLI 引擎都失败/不可用时，用脚手架模板 + LLM 定制 +
        # 本地构建产出真实可运行代码（不依赖外部 CLI 网关）。
        if not result.get("ok"):
            logger.info("[codegen] 使用 llm-local (self-contained engine)")
            result = await self._generate_via_llm_local(
                task_id, task_title, project_dir, pipeline_outputs, template_id,
            )
            if not result.get("ok"):
                logger.error("[codegen] llm-local engine failed: %s", result.get("error"))

        if not result.get("ok"):
            return result

        # Engines may relocate the project (llm-local scaffolds into app/); write
        # manifest/build.log to the dir that actually holds the built code.
        effective_dir = result.get("project_dir") or project_dir
        manifest_baseline = template_baseline if effective_dir == project_dir else set()

        # Phase 4: allowlist check
        tmpl = get_template(template_id) if template_id else None
        offenders = _enforce_allowlist(effective_dir, manifest_baseline)
        if offenders:
            logger.warning(f"[codegen] allowlist violations: {offenders}")
            result["allowlist_violations"] = offenders

        # Phase 4: write source_manifest.json
        build_cmd = result.get("build_command") or (tmpl.get("build_cmd") if tmpl else "") or ""
        dev_cmd = result.get("dev_command") or (tmpl.get("dev_cmd") if tmpl else "") or ""
        test_cmd = (tmpl.get("test_cmd") if tmpl else "") or ""
        if not test_cmd and (
            "pnpm test" in build_cmd
            or (tmpl and "&& pnpm test" in (tmpl.get("build_cmd") or ""))
        ):
            test_cmd = "pnpm test"
        build_success = result.get("build_success", False)
        manifest = _build_source_manifest(
            effective_dir, manifest_baseline, build_cmd, dev_cmd, test_cmd, build_success,
        )
        _write_source_manifest(effective_dir, manifest)
        result["source_manifest"] = manifest

        # Phase 4: write build.log if build ran
        build_output = result.get("build_output") or result.get("engine_output") or ""
        if build_output:
            _write_build_log(effective_dir, build_output)

        return result

    async def _generate_via_claude_code(
        self,
        task_id: str,
        task_title: str,
        project_dir: str,
        pipeline_outputs: Dict[str, str],
        template_id: Optional[str],
    ) -> Dict[str, Any]:
        """Primary engine: Claude Code CLI writes files directly in project_dir."""
        from ..executor_bridge import execute_claude_code

        prompt = _build_claude_prompt(task_title, pipeline_outputs, template_id)

        logger.info(f"[codegen] Invoking Claude Code for {task_title} in {project_dir}")
        job = await execute_claude_code(
            task_id=task_id,
            prompt=prompt,
            work_dir=project_dir,
            timeout_seconds=600,
            created_by="codegen-agent",
        )

        if job.get("status") not in ("done",):
            return {
                "ok": False,
                "engine": "claude-code",
                "error": f"Claude Code {job.get('status', 'unknown')}: {job.get('output', '')[:500]}",
                "job_id": job.get("id"),
            }

        files_written = _scan_project_files(project_dir)
        claude_output = job.get("output", "")
        build_success = job.get("exitCode", 1) == 0

        if not files_written and build_success:
            logger.warning("[codegen] Claude Code reported success but no files were written in %s", project_dir)
            return {
                "ok": False,
                "engine": "claude-code",
                "error": "Engine reported success but no files were written",
                "job_id": job.get("id"),
            }

        return {
            "ok": True,
            "engine": "claude-code",
            "task_id": task_id,
            "project_dir": project_dir,
            "template": template_id,
            "files_written": files_written,
            "total_files": len(files_written),
            "build_success": build_success,
            "build_output": claude_output,
            "job_id": job.get("id"),
            "engine_output": claude_output[:2000],
        }

    async def _generate_via_codex(
        self,
        task_id: str,
        task_title: str,
        project_dir: str,
        pipeline_outputs: Dict[str, str],
        template_id: Optional[str],
    ) -> Dict[str, Any]:
        """备选引擎：Codex CLI 在 project_dir 中直接生成代码。"""
        from ..executor_bridge import execute_codex

        prompt = _build_claude_prompt(task_title, pipeline_outputs, template_id)

        logger.info("[codegen] Invoking Codex for %s in %s", task_title, project_dir)
        job = await execute_codex(
            task_id=task_id,
            prompt=prompt,
            work_dir=project_dir,
            timeout_seconds=600,
            created_by="codegen-agent",
        )

        if job.get("status") not in ("done",):
            return {
                "ok": False,
                "engine": "codex",
                "error": f"Codex {job.get('status', 'unknown')}: {job.get('output', '')[:500]}",
                "job_id": job.get("id"),
            }

        files_written = _scan_project_files(project_dir)
        codex_output = job.get("output", "")
        build_success = job.get("exitCode", 1) == 0

        if not files_written and build_success:
            logger.warning("[codegen] Codex reported success but no files were written in %s", project_dir)
            return {
                "ok": False,
                "engine": "codex",
                "error": "Engine reported success but no files were written",
                "job_id": job.get("id"),
            }

        return {
            "ok": True,
            "engine": "codex",
            "task_id": task_id,
            "project_dir": project_dir,
            "template": template_id,
            "files_written": files_written,
            "total_files": len(files_written),
            "build_success": build_success,
            "build_output": codex_output,
            "job_id": job.get("id"),
            "engine_output": codex_output[:2000],
        }

    async def _generate_via_llm_local(
        self,
        task_id: str,
        task_title: str,
        project_dir: str,
        pipeline_outputs: Dict[str, str],
        template_id: Optional[str],
    ) -> Dict[str, Any]:
        """Self-contained fallback engine — no external CLI gateway.

        When both Claude Code and Codex CLIs are unavailable or their gateways
        are down (e.g. expired token), the pipeline still needs to produce real,
        *building* code. This engine:
          1. Scaffolds the known-good vue-app template into a clean ``app/``
             subdir (guaranteed to build).
          2. LLM-customizes the home view from the PRD as one self-contained
             SFC (no new deps), build-verified with revert-on-failure so the
             build always ends green.
          3. Runs ``pnpm install && build`` locally (bash), not via the CLI
             gateway, and reports the real build status.
        Output is honest: source_manifest/build_log reflect the actual build.
        """
        from ..llm_router import chat_completion_with_fallback
        from ...config import settings

        code_dir = os.path.join(project_dir, "app")
        os.makedirs(code_dir, exist_ok=True)

        logger.info("[codegen] llm-local: scaffolding vue-app into %s", code_dir)
        scaffold = scaffold_project("vue-app", task_title, code_dir)
        if not scaffold.get("ok"):
            return {
                "ok": False,
                "engine": "llm-local",
                "error": f"scaffold failed: {scaffold.get('error')}",
            }

        # LLM-customize the home view (single SFC, no new deps) from the PRD.
        home_path = os.path.join(code_dir, "src", "views", "Home.vue")
        template_home = ""
        try:
            with open(home_path, "r", encoding="utf-8") as f:
                template_home = f.read()
        except IOError:
            pass

        customized = False
        prd = (pipeline_outputs.get("planning") or "")[:4000]
        design = (pipeline_outputs.get("design") or "")[:2000]
        if template_home:
            try:
                llm = await chat_completion_with_fallback(
                    model=settings.llm_model or "deepseek-chat",
                    messages=[
                        {
                            "role": "system",
                            "content": "你是资深 Vue3 前端工程师。只输出一个完整的 Vue 单文件组件代码块，不要解释。",
                        },
                        {
                            "role": "user",
                            "content": _build_home_view_prompt(
                                task_title, prd, design, template_home
                            ),
                        },
                    ],
                    temperature=0.3,
                    max_tokens=8000,
                )
                new_home = _extract_single_vue_sfc(llm.get("content", ""))
                if new_home:
                    with open(home_path, "w", encoding="utf-8") as f:
                        f.write(new_home)
                    customized = True
                    logger.info("[codegen] llm-local: customized Home.vue from PRD")
            except Exception as e:  # noqa: BLE001 — customization is best-effort
                logger.warning("[codegen] llm-local home customization failed: %s", e)

        # Local build — no external CLI dependency.
        build_res = await self.run_build(
            code_dir, "pnpm install && pnpm run build", timeout=420
        )
        build_ok = build_res.get("ok", False)

        # Keep the build green: if the customized view broke compilation,
        # revert to the scaffold's view and rebuild (deps already installed).
        if not build_ok and customized and template_home:
            logger.warning(
                "[codegen] llm-local: customized Home.vue broke build, reverting to template"
            )
            with open(home_path, "w", encoding="utf-8") as f:
                f.write(template_home)
            build_res = await self.run_build(code_dir, "pnpm run build", timeout=240)
            build_ok = build_res.get("ok", False)
            customized = False

        files_written = _scan_project_files(code_dir)
        return {
            "ok": True,
            "engine": "llm-local",
            "task_id": task_id,
            "project_dir": code_dir,
            "template": "vue-app",
            "files_written": files_written,
            "total_files": len(files_written),
            "build_success": build_ok,
            "build_command": "pnpm install && pnpm run build",
            "dev_command": "pnpm dev",
            "build_output": build_res.get("output", ""),
            "customized_home": customized,
            "engine_output": (build_res.get("output", "") or "")[:2000],
        }

    async def auto_fix(
        self,
        task_id: str,
        project_dir: str,
        build_log_path: str,
        attempt: int = 1,
    ) -> Dict[str, Any]:
        """Use Claude Code to automatically fix build/test errors.

        Phase 4: reads build.log from disk instead of inline error string,
        maximum 2 retries (MAX_FIX_RETRIES).
        """
        from ..executor_bridge import execute_claude_code

        error_output = ""
        if os.path.isfile(build_log_path):
            with open(build_log_path, "r", encoding="utf-8") as f:
                error_output = f.read()

        if not error_output.strip():
            logger.info("[codegen] Auto-fix attempt %d skipped: build log is empty for %s", attempt, project_dir)
            return {
                "ok": False,
                "attempt": attempt,
                "error": "build_log_empty",
                "status": "skipped",
            }

        prompt = _build_fix_prompt(error_output, attempt)

        logger.info(f"[codegen] Auto-fix attempt {attempt} for {project_dir}")
        job = await execute_claude_code(
            task_id=task_id,
            prompt=prompt,
            work_dir=project_dir,
            timeout_seconds=300,
            created_by="codegen-autofix",
        )

        success = job.get("status") == "done" and job.get("exitCode", 1) == 0
        return {
            "ok": success,
            "attempt": attempt,
            "job_id": job.get("id"),
            "output": job.get("output", "")[:2000],
            "status": job.get("status"),
        }

    async def run_build(
        self, project_dir: str, command: str, timeout: int = 120
    ) -> Dict[str, Any]:
        """Run a build command in the project directory and write build.log."""
        result = await execute_tool("bash", {
            "command": f"cd {project_dir} && {command}",
            "timeout": timeout,
        })
        # 结构化提取退出码，避免子字符串误匹配
        exit_match = re.search(r"\[exit code:\s*(-?\d+)\]", result)
        success = exit_match is not None and int(exit_match.group(1)) == 0
        _write_build_log(project_dir, result)
        return {"ok": success, "output": result}


def _slugify(text: str) -> str:
    """Convert text to a safe directory name."""
    slug = re.sub(r'[^\w\s-]', '', text.lower())
    slug = re.sub(r'[\s_]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)  # collapse multiple hyphens
    return slug[:64].strip("-") or "project"


def _scan_project_files(project_dir: str) -> List[str]:
    """Scan project directory and return list of relative file paths."""
    skip_dirs = {"node_modules", ".git", "__pycache__", ".next", "dist", "build", ".venv", "venv"}
    files = []
    for root, dirs, filenames in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in filenames:
            rel = os.path.relpath(os.path.join(root, f), project_dir)
            files.append(rel)
    return sorted(files)
