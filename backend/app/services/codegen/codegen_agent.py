"""
CodeGen Agent — uses LLM + tools to generate, modify, and build project code.

Workflow:
1. Analyze task requirements (from pipeline outputs)
2. Select or scaffold project template
3. Generate code using LLM with file_write tool calls
4. Build the project in sandbox
5. Run tests if available
6. Return build artifacts
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

CODEGEN_SYSTEM_PROMPT = """你是一位全栈高级开发工程师，能够独立完成从需求到可运行代码的全部工作。

## 能力
- 根据 PRD 和架构方案生成完整的、可运行的项目代码
- 使用工具创建文件、执行命令、安装依赖
- 自动修复构建错误

## 工作流程
1. 分析需求和架构方案
2. 确定项目结构
3. 逐个创建代码文件（使用 file_write 工具）
4. 安装依赖并构建（使用 bash 工具）
5. 修复任何构建错误

## 输出规范
- 代码文件使用 file_write 工具创建
- 构建命令使用 bash 工具执行
- 最终输出包含所有文件路径和构建状态

当你完成所有代码文件的创建后，输出 JSON 标记：
```result
{"status": "complete", "files": ["path1", "path2", ...]}
```"""


class CodeGenAgent:
    """Orchestrates code generation from pipeline outputs to built artifacts."""

    def __init__(self, workspace: Optional[str] = None):
        self.workspace = workspace or os.path.join(get_sandbox_root(), "projects")
        os.makedirs(self.workspace, exist_ok=True)

    async def generate_from_pipeline(
        self,
        task_id: str,
        task_title: str,
        pipeline_outputs: Dict[str, str],
        template_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate project code from pipeline stage outputs.

        Args:
            task_id: Pipeline task identifier
            task_title: Human-readable title
            pipeline_outputs: dict of stage_id -> output content
            template_id: Optional template to scaffold from
        """
        project_dir = os.path.join(self.workspace, _slugify(task_title))
        os.makedirs(project_dir, exist_ok=True)

        if template_id:
            scaffold_result = scaffold_project(template_id, task_title, project_dir)
            if not scaffold_result.get("ok"):
                return scaffold_result

        code_blocks = await self._extract_code_from_outputs(pipeline_outputs)

        written_files = []
        for filepath, content in code_blocks.items():
            full_path = os.path.join(project_dir, filepath)
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
            "task_id": task_id,
            "project_dir": project_dir,
            "template": template_id,
            "files_written": written_files,
            "total_files": len(written_files),
            "build_result": build_result,
            "build_success": build_result is None or "[exit code: 0]" in (build_result or ""),
        }

    async def _extract_code_from_outputs(self, outputs: Dict[str, str]) -> Dict[str, str]:
        """用 LLM 二次解析从 pipeline 输出中提取代码文件，正则兜底。"""
        code_blocks: Dict[str, str] = {}

        # 先用正则快速提取明确标注了路径的代码块
        for stage_id, output in outputs.items():
            if not output:
                continue
            # 格式1: ```lang\n// filepath\ncode```
            for m in re.finditer(r'```\w*\s*\n//\s*(.+?)\n([\s\S]*?)```', output):
                fp, code = m.group(1).strip(), m.group(2).strip()
                if fp and code:
                    code_blocks[fp] = code
            # 格式2: 文件/File: `path`\n```code```
            for m in re.finditer(r'(?:文件|File)[：:]\s*`?([^\s`\n]+)`?\s*\n```\w*\s*\n([\s\S]*?)```', output):
                fp, code = m.group(1).strip(), m.group(2).strip()
                if fp and code:
                    code_blocks[fp] = code

        # 如果正则没提取到任何文件，用 LLM 解析
        if not code_blocks:
            combined = "\n\n".join(
                f"=== {sid} ===\n{out}" for sid, out in outputs.items() if out
            )
            if combined:
                code_blocks = await self._llm_extract_files(combined)

        return code_blocks

    async def _llm_extract_files(self, content: str) -> Dict[str, str]:
        """让 LLM 从非结构化输出中提取文件路径和代码内容。"""
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
            model="",  # 使用默认模型
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )

        if "error" in result:
            logger.warning(f"LLM 代码提取失败: {result['error']}")
            return {}

        try:
            raw = result.get("content", "")
            # 去掉可能的 markdown 包裹
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
