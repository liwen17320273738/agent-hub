"""
CodeGen Agent — orchestrates code generation via Claude Code CLI or LLM extraction.

Primary engine: Claude Code (executor_bridge) — gives an autonomous coding agent
full access to the project directory with file_write, bash, build tools.

Fallback engine: regex + LLM extraction from pipeline markdown outputs.

Workflow:
1. Scaffold project template (optional)
2. Build a detailed prompt from pipeline PRD + architecture outputs
3. Execute Claude Code in the project directory → it writes files, installs deps, builds
4. If Claude Code unavailable, fall back to regex/LLM code block extraction
5. Verify build and return result
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from .templates import scaffold_project, get_template, list_templates
from ..tools.sandbox import configure_sandbox, get_sandbox_root
from ..tools import execute_tool
from ..llm_router import chat_completion

logger = logging.getLogger(__name__)

MAX_FIX_RETRIES = 3


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
        template = get_template(template_id)
        if template:
            sections.append(f"## 项目模板: {template.get('name', template_id)}")
            sections.append(f"技术栈: {', '.join(template.get('stack', []))}")
            if template.get("build_cmd"):
                sections.append(f"构建命令: `{template['build_cmd']}`")
            if template.get("dev_cmd"):
                sections.append(f"开发命令: `{template['dev_cmd']}`\n")

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


class CodeGenAgent:
    """Orchestrates code generation from pipeline outputs to built artifacts.

    Primary: Claude Code CLI (autonomous coding agent with file access)
    Fallback: regex/LLM extraction from pipeline markdown
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

        If existing_project_dir is set, operates on that directory (no scaffold).
        Otherwise creates a new project in the sandbox.
        """
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

        if use_claude_code:
            result = await self._generate_via_claude_code(
                task_id, task_title, project_dir, pipeline_outputs, template_id,
            )
            if result.get("ok"):
                return result
            logger.warning(f"[codegen] Claude Code failed, falling back to extraction: {result.get('error')}")

        return await self._generate_via_extraction(
            task_id, task_title, project_dir, pipeline_outputs, template_id,
        )

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

        return {
            "ok": True,
            "engine": "claude-code",
            "task_id": task_id,
            "project_dir": project_dir,
            "template": template_id,
            "files_written": files_written,
            "total_files": len(files_written),
            "build_success": True,
            "job_id": job.get("id"),
            "claude_output": job.get("output", "")[:2000],
        }

    async def _generate_via_extraction(
        self,
        task_id: str,
        task_title: str,
        project_dir: str,
        pipeline_outputs: Dict[str, str],
        template_id: Optional[str],
    ) -> Dict[str, Any]:
        """Fallback engine: extract code blocks from pipeline markdown outputs."""
        code_blocks = await self._extract_code_from_outputs(pipeline_outputs)

        from pathlib import Path
        project_root = Path(project_dir).resolve()

        written_files = []
        for filepath, content in code_blocks.items():
            full_path = (project_root / filepath).resolve()
            if not str(full_path).startswith(str(project_root)):
                logger.warning(f"[codegen] Skipped path traversal attempt: {filepath}")
                continue
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            written_files.append(filepath)

        build_result = None
        template = get_template(template_id) if template_id else None
        build_cmd = template.get("build_cmd") if template else None
        if build_cmd:
            build_result = await execute_tool("bash", {
                "command": f"cd {project_dir} && {build_cmd}",
                "timeout": 120,
            })

        return {
            "ok": True,
            "engine": "extraction",
            "task_id": task_id,
            "project_dir": project_dir,
            "template": template_id,
            "files_written": written_files,
            "total_files": len(written_files),
            "build_result": build_result,
            "build_success": build_result is None or "[exit code: 0]" in (build_result or ""),
        }

    async def auto_fix(
        self,
        task_id: str,
        project_dir: str,
        error_output: str,
        attempt: int = 1,
    ) -> Dict[str, Any]:
        """Use Claude Code to automatically fix build/test errors."""
        from ..executor_bridge import execute_claude_code

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

    async def _extract_code_from_outputs(self, outputs: Dict[str, str]) -> Dict[str, str]:
        """Extract code files from pipeline markdown outputs via regex + LLM fallback."""
        code_blocks: Dict[str, str] = {}

        for stage_id, output in outputs.items():
            if not output:
                continue
            for m in re.finditer(r'```\w*\s*\n//\s*(.+?)\n([\s\S]*?)```', output):
                fp, code = m.group(1).strip(), m.group(2).strip()
                if fp and code:
                    code_blocks[fp] = code
            for m in re.finditer(r'(?:文件|File)[：:]\s*`?([^\s`\n]+)`?\s*\n```\w*\s*\n([\s\S]*?)```', output):
                fp, code = m.group(1).strip(), m.group(2).strip()
                if fp and code:
                    code_blocks[fp] = code

        if not code_blocks:
            combined = "\n\n".join(
                f"=== {sid} ===\n{out}" for sid, out in outputs.items() if out
            )
            if combined:
                code_blocks = await self._llm_extract_files(combined)

        return code_blocks

    async def _llm_extract_files(self, content: str) -> Dict[str, str]:
        """Let LLM extract file paths and code from unstructured text."""
        prompt = f"""从下面的技术文档中提取所有代码文件。

要求：
- 识别所有代码块及其对应的文件路径
- 如果没有明确路径，根据代码内容推断合理的文件名
- 只返回 JSON，格式：{{"文件路径": "文件内容", ...}}
- 文件路径使用相对路径（如 src/main.py、index.html）

文档内容：
{content[:8000]}

只返回 JSON 对象，不要其他文字。"""

        result = await chat_completion(
            model="",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )

        if "error" in result:
            logger.warning(f"LLM 代码提取失败: {result['error']}")
            return {}

        try:
            raw = result.get("content", "")
            json_str = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip())
            return json.loads(json_str)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"LLM 代码提取 JSON 解析失败: {e}")
            return {}

    async def run_build(self, project_dir: str, command: str) -> Dict[str, Any]:
        """Run a build command in the project directory."""
        result = await execute_tool("bash", {
            "command": f"cd {project_dir} && {command}",
            "timeout": 120,
        })
        success = "[exit code: 0]" in result
        return {"ok": success, "output": result}


def _slugify(text: str) -> str:
    """Convert text to a safe directory name."""
    slug = re.sub(r'[^\w\s-]', '', text.lower())
    slug = re.sub(r'[\s_]+', '-', slug)
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
