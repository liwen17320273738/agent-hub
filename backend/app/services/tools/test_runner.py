"""
Test Runner Tool — execute tests and collect results for pipeline feedback.

Capabilities:
- Run pytest, jest, go test, cargo test
- Parse test results (pass/fail/skip counts)
- Capture stdout/stderr
- Generate structured test reports
- Feed results back to pipeline stages
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_OUTPUT_LENGTH = 100000
_DEFAULT_TIMEOUT = 300  # 5 minutes


RUNNERS = {
    "pytest": {
        "cmd": ["python3", "-m", "pytest", "-v", "--tb=short", "--no-header", "-q"],
        "detect": ["pytest.ini", "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt"],
        "detect_content": "pytest",
        "parse": "_parse_pytest_output",
    },
    "jest": {
        "cmd": ["npx", "jest", "--verbose", "--no-coverage"],
        "detect": ["jest.config.js", "jest.config.ts", "jest.config.mjs"],
        "detect_content": "jest",
        "parse": "_parse_jest_output",
    },
    "vitest": {
        "cmd": ["npx", "vitest", "run", "--reporter=verbose"],
        "detect": ["vitest.config.ts", "vitest.config.js"],
        "detect_content": "vitest",
        "parse": "_parse_vitest_output",
    },
    "go": {
        "cmd": ["go", "test", "-v", "./..."],
        "detect": ["go.mod"],
        "parse": "_parse_go_output",
    },
    "cargo": {
        "cmd": ["cargo", "test"],
        "detect": ["Cargo.toml"],
        "parse": "_parse_cargo_output",
    },
}


def detect_test_runner(project_dir: str) -> Optional[str]:
    """Auto-detect which test runner to use based on project files."""
    p = Path(project_dir)

    for runner_name, config in RUNNERS.items():
        for detect_file in config.get("detect", []):
            if (p / detect_file).exists():
                if "detect_content" in config:
                    try:
                        content = (p / detect_file).read_text(errors="ignore")
                        if config["detect_content"] in content:
                            return runner_name
                    except Exception:
                        pass
                else:
                    return runner_name

    if (p / "package.json").exists():
        try:
            pkg = json.loads((p / "package.json").read_text())
            scripts = pkg.get("scripts", {})
            if "test" in scripts:
                test_cmd = scripts["test"]
                if "vitest" in test_cmd:
                    return "vitest"
                if "jest" in test_cmd:
                    return "jest"
        except Exception:
            pass

    if (p / "requirements.txt").exists() or (p / "pyproject.toml").exists():
        return "pytest"

    return None


async def run_tests(
    project_dir: str,
    runner: Optional[str] = None,
    test_path: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
    timeout: int = _DEFAULT_TIMEOUT,
    env_vars: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Run tests in a project directory and return structured results."""
    p = Path(project_dir).resolve()
    if not p.exists():
        return {"ok": False, "error": f"Directory does not exist: {project_dir}"}

    if not runner:
        runner = detect_test_runner(str(p))
    if not runner or runner not in RUNNERS:
        return {"ok": False, "error": f"Could not detect test runner. Available: {list(RUNNERS.keys())}"}

    config = RUNNERS[runner]
    cmd = list(config["cmd"])

    if test_path:
        if test_path.startswith("-"):
            return {"ok": False, "error": "test_path cannot start with '-'", "runner": runner}
        cmd.append(test_path)
    if extra_args:
        blocked = {"--exec", "--command", "-e", "--shell", "&&", "||", ";", "|"}
        for arg in extra_args:
            if arg.lower() in blocked or any(c in arg for c in ";|&`$"):
                return {"ok": False, "error": f"Blocked argument: {arg}", "runner": runner}
        cmd.extend(extra_args)

    env = {**os.environ}
    if env_vars:
        env.update(env_vars)
    env["CI"] = "true"
    env["FORCE_COLOR"] = "0"
    env["NO_COLOR"] = "1"

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(p),
            env=env,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        return {
            "ok": False,
            "error": f"Tests timed out after {timeout}s",
            "runner": runner,
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "error": f"Test runner command not found: {cmd[0]}",
            "runner": runner,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "runner": runner}

    stdout = stdout_bytes.decode(errors="replace")
    stderr = stderr_bytes.decode(errors="replace")

    if len(stdout) > _MAX_OUTPUT_LENGTH:
        stdout = stdout[:_MAX_OUTPUT_LENGTH] + "\n... (output truncated)"
    if len(stderr) > _MAX_OUTPUT_LENGTH:
        stderr = stderr[:_MAX_OUTPUT_LENGTH] + "\n... (output truncated)"

    parsed = _parse_output(runner, stdout, stderr, proc.returncode)

    return {
        "ok": proc.returncode == 0,
        "runner": runner,
        "exit_code": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        **parsed,
    }


def _parse_output(runner: str, stdout: str, stderr: str, exit_code: int) -> Dict[str, Any]:
    """Parse test output into structured results."""
    parsers = {
        "pytest": _parse_pytest_output,
        "jest": _parse_jest_output,
        "vitest": _parse_vitest_output,
        "go": _parse_go_output,
        "cargo": _parse_cargo_output,
    }
    parser = parsers.get(runner, _parse_generic_output)
    try:
        return parser(stdout, stderr, exit_code)
    except Exception as e:
        logger.warning(f"[test_runner] Parse error for {runner}: {e}")
        return _parse_generic_output(stdout, stderr, exit_code)


def _parse_pytest_output(stdout: str, stderr: str, exit_code: int) -> Dict[str, Any]:
    """Parse pytest verbose output."""
    passed = failed = skipped = errors = 0

    summary_match = re.search(
        r'(\d+)\s+passed(?:.*?(\d+)\s+failed)?(?:.*?(\d+)\s+skipped)?(?:.*?(\d+)\s+error)?',
        stdout + stderr,
    )
    if summary_match:
        passed = int(summary_match.group(1) or 0)
        failed = int(summary_match.group(2) or 0)
        skipped = int(summary_match.group(3) or 0)
        errors = int(summary_match.group(4) or 0)
    else:
        passed = stdout.count(" PASSED")
        failed = stdout.count(" FAILED")
        skipped = stdout.count(" SKIPPED")

    failures = []
    for match in re.finditer(r'FAILED\s+([\w/.:]+)', stdout):
        failures.append(match.group(1))

    total = passed + failed + skipped + errors
    return {
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "errors": errors,
        },
        "failures": failures,
        "pass_rate": round(passed / total * 100, 1) if total > 0 else 0,
    }


def _parse_jest_output(stdout: str, stderr: str, exit_code: int) -> Dict[str, Any]:
    """Parse Jest output."""
    combined = stdout + stderr

    tests_match = re.search(r'Tests:\s+(.*)', combined)

    passed = failed = skipped = 0
    if tests_match:
        line = tests_match.group(1)
        p = re.search(r'(\d+)\s+passed', line)
        f = re.search(r'(\d+)\s+failed', line)
        s = re.search(r'(\d+)\s+skipped', line)
        passed = int(p.group(1)) if p else 0
        failed = int(f.group(1)) if f else 0
        skipped = int(s.group(1)) if s else 0

    failures = []
    for match in re.finditer(r'●\s+(.*?)$', combined, re.MULTILINE):
        failures.append(match.group(1).strip())

    total = passed + failed + skipped
    return {
        "summary": {"total": total, "passed": passed, "failed": failed, "skipped": skipped, "errors": 0},
        "failures": failures[:20],
        "pass_rate": round(passed / total * 100, 1) if total > 0 else 0,
    }


def _parse_vitest_output(stdout: str, stderr: str, exit_code: int) -> Dict[str, Any]:
    """Parse Vitest output."""
    combined = stdout + stderr

    passed = len(re.findall(r'✓|√', combined))
    failed = len(re.findall(r'✗|×|FAIL', combined))

    test_match = re.search(r'Tests\s+(\d+)\s+passed.*?(\d+)\s+failed', combined)
    if test_match:
        passed = int(test_match.group(1))
        failed = int(test_match.group(2))

    total = passed + failed
    return {
        "summary": {"total": total, "passed": passed, "failed": failed, "skipped": 0, "errors": 0},
        "failures": [],
        "pass_rate": round(passed / total * 100, 1) if total > 0 else 0,
    }


def _parse_go_output(stdout: str, stderr: str, exit_code: int) -> Dict[str, Any]:
    """Parse go test output."""
    combined = stdout + stderr
    passed = len(re.findall(r'--- PASS:', combined))
    failed = len(re.findall(r'--- FAIL:', combined))
    skipped = len(re.findall(r'--- SKIP:', combined))

    failures = []
    for match in re.finditer(r'--- FAIL:\s+(\S+)', combined):
        failures.append(match.group(1))

    total = passed + failed + skipped
    return {
        "summary": {"total": total, "passed": passed, "failed": failed, "skipped": skipped, "errors": 0},
        "failures": failures,
        "pass_rate": round(passed / total * 100, 1) if total > 0 else 0,
    }


def _parse_cargo_output(stdout: str, stderr: str, exit_code: int) -> Dict[str, Any]:
    """Parse cargo test output."""
    combined = stdout + stderr
    result_match = re.search(r'test result: \w+\.\s+(\d+)\s+passed;\s+(\d+)\s+failed;\s+(\d+)\s+ignored', combined)

    if result_match:
        passed = int(result_match.group(1))
        failed = int(result_match.group(2))
        skipped = int(result_match.group(3))
    else:
        passed = combined.count("... ok")
        failed = combined.count("... FAILED")
        skipped = combined.count("... ignored")

    total = passed + failed + skipped
    return {
        "summary": {"total": total, "passed": passed, "failed": failed, "skipped": skipped, "errors": 0},
        "failures": [],
        "pass_rate": round(passed / total * 100, 1) if total > 0 else 0,
    }


def _parse_generic_output(stdout: str, stderr: str, exit_code: int) -> Dict[str, Any]:
    """Generic parser when specific runner is unknown."""
    return {
        "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "errors": 0},
        "failures": [],
        "pass_rate": 0 if exit_code != 0 else 100,
    }


def format_test_report(result: Dict[str, Any]) -> str:
    """Format test results as a Markdown report for pipeline consumption."""
    s = result.get("summary", {})
    lines = [
        "## Test Execution Report",
        "",
        f"**Runner**: {result.get('runner', 'unknown')}",
        f"**Exit code**: {result.get('exit_code', -1)}",
        f"**Pass rate**: {result.get('pass_rate', 0)}%",
        "",
        "### Summary",
        "| Metric | Count |",
        "|--------|-------|",
        f"| Total | {s.get('total', 0)} |",
        f"| Passed | {s.get('passed', 0)} |",
        f"| Failed | {s.get('failed', 0)} |",
        f"| Skipped | {s.get('skipped', 0)} |",
        f"| Errors | {s.get('errors', 0)} |",
    ]

    failures = result.get("failures", [])
    if failures:
        lines.append("")
        lines.append("### Failed Tests")
        for f in failures[:20]:
            lines.append(f"- `{f}`")

    if not result.get("ok"):
        stderr = result.get("stderr", "")
        if stderr:
            lines.append("")
            lines.append("### Error Output")
            lines.append(f"```\n{stderr[:3000]}\n```")

    return "\n".join(lines)


TEST_TOOL_DEFINITIONS = [
    {
        "name": "run_tests",
        "description": "Run tests in a project directory and get structured results",
        "parameters": {
            "type": "object",
            "properties": {
                "project_dir": {"type": "string", "description": "Path to project root"},
                "runner": {"type": "string", "description": "Test runner (pytest/jest/vitest/go/cargo). Auto-detected if omitted."},
                "test_path": {"type": "string", "description": "Specific test file/directory to run"},
                "extra_args": {"type": "array", "items": {"type": "string"}},
                "timeout": {"type": "integer", "default": 300},
            },
            "required": ["project_dir"],
        },
    },
    {
        "name": "detect_test_runner",
        "description": "Auto-detect which test runner a project uses",
        "parameters": {
            "type": "object",
            "properties": {
                "project_dir": {"type": "string"},
            },
            "required": ["project_dir"],
        },
    },
]


async def execute_test_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a test tool by name."""
    if name == "run_tests":
        result = await run_tests(**{k: v for k, v in args.items() if v is not None})
        result["report"] = format_test_report(result)
        return result
    elif name == "detect_test_runner":
        runner = detect_test_runner(args["project_dir"])
        return {"ok": True, "runner": runner}
    return {"ok": False, "error": f"Unknown test tool: {name}"}
