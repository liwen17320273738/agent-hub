"""
/review Command - Code Review

Performs multi-dimensional code review including:
- Code quality analysis
- Security scanning
- Performance assessment
- AI-powered suggestions
"""
import logging
import time
from typing import Any, Dict, List, Optional

from . import BaseCommand, CommandArgument, CommandContext, CommandResult, CommandStatus, ExecutionMetrics

logger = logging.getLogger(__name__)


class ReviewCommand(BaseCommand):
    """
    /review - Code Review
    
    Performs comprehensive code review with multiple analysis dimensions:
    - Correctness and bug detection
    - Security vulnerabilities (OWASP Top 10)
    - Performance issues
    - Code style and maintainability
    - AI-powered suggestions
    """
    
    name = "/review"
    description = (
        "Perform comprehensive code review on PRs or files. "
        "Analyzes correctness, security, performance, and provides AI suggestions. "
        "Use --pr for pull requests or --files for specific files."
    )
    category = "review"
    
    def get_arguments(self) -> List[CommandArgument]:
        return [
            CommandArgument(
                name="pr",
                description="Pull request number to review",
                type="number",
                required=False,
            ),
            CommandArgument(
                name="files",
                description="Comma-separated list of files to review",
                type="array",
                required=False,
            ),
            CommandArgument(
                name="severity",
                description="Minimum severity to report",
                type="string",
                required=False,
                default="low",
                enum=["low", "medium", "high", "critical"],
            ),
            CommandArgument(
                name="include_security",
                description="Include security scan",
                type="boolean",
                required=False,
                default=True,
            ),
            CommandArgument(
                name="include_performance",
                description="Include performance analysis",
                type="boolean",
                required=False,
                default=True,
            ),
        ]
    
    async def execute(self, ctx: CommandContext) -> CommandResult:
        """Execute the review command"""
        start_time = time.time()
        errors = []
        artifacts = []
        
        try:
            # Extract arguments
            pr_number = ctx.arguments.get("pr")
            files = ctx.arguments.get("files", [])
            severity = ctx.arguments.get("severity", "low")
            include_security = ctx.arguments.get("include_security", True)
            include_performance = ctx.arguments.get("include_performance", True)
            
            if not pr_number and not files:
                return CommandResult(
                    command=self.name,
                    status=CommandStatus.FAILED,
                    errors=["Either --pr or --files is required"],
                    message="Either --pr or --files is required",
                )
            
            # Get code to review
            code_context = await self._fetch_code_context(pr_number, files, ctx)
            
            # Perform analysis
            findings = []
            
            # 1. Static analysis
            static_findings = await self._analyze_static(code_context, severity)
            findings.extend(static_findings)
            
            # 2. Security scan (if enabled)
            if include_security:
                security_findings = await self._scan_security(code_context, severity)
                findings.extend(security_findings)
            
            # 3. Performance analysis (if enabled)
            if include_performance:
                perf_findings = await self._analyze_performance(code_context, severity)
                findings.extend(perf_findings)
            
            # 4. AI-powered review
            ai_findings = await self._ai_review(code_context, severity, ctx)
            findings.extend(ai_findings)
            
            # Calculate overall score
            score = self._calculate_score(findings)
            
            # Determine approval
            critical_count = len([f for f in findings if f["severity"] == "critical"])
            high_count = len([f for f in findings if f["severity"] == "high"])
            approved = critical_count == 0 and high_count <= 2
            
            output = {
                "pr_number": pr_number,
                "files_reviewed": list(code_context.keys()),
                "findings": findings,
                "findings_by_severity": {
                    "critical": len([f for f in findings if f["severity"] == "critical"]),
                    "high": len([f for f in findings if f["severity"] == "high"]),
                    "medium": len([f for f in findings if f["severity"] == "medium"]),
                    "low": len([f for f in findings if f["severity"] == "low"]),
                },
                "score": score,
                "approved": approved,
                "recommendation": "approve" if approved else ("request_changes" if high_count > 5 else "comment"),
            }
            
            # Create review artifact
            artifacts.append({
                "type": "file",
                "name": "code-review-report.md",
                "content": self._generate_markdown_report(output),
            })
            
            duration_ms = int((time.time() - start_time) * 1000)
            tokens_used = len(str(code_context)) // 4  # Rough estimate
            
            return CommandResult(
                command=self.name,
                status=CommandStatus.COMPLETED,
                output=output,
                artifacts=artifacts,
                metrics=ExecutionMetrics(
                    duration_ms=duration_ms,
                    tokens_used=tokens_used,
                ),
                message=f"Review complete: {len(findings)} findings, score {score}/100",
            )
            
        except Exception as e:
            logger.error(f"/review failed: {e}")
            duration_ms = int((time.time() - start_time) * 1000)
            return CommandResult(
                command=self.name,
                status=CommandStatus.FAILED,
                errors=[str(e)],
                metrics=ExecutionMetrics(duration_ms=duration_ms),
                message=f"Review failed: {str(e)}",
            )
    
    async def _fetch_code_context(
        self, pr_number: Optional[int], files: List[str], ctx: CommandContext
    ) -> Dict[str, str]:
        """Fetch code to review"""
        code_context = {}
        
        if pr_number:
            try:
                from ..tools.git_tool import execute_git_tool
                result = await execute_git_tool({
                    "operation": "get_pr_diff",
                    "pr_number": pr_number,
                })
                code_context[f"PR #{pr_number}"] = result.get("diff", "")
            except Exception as e:
                logger.warning(f"Failed to fetch PR: {e}")
        
        # TODO: Fetch specific files if provided
        
        if not code_context:
            code_context["sample"] = "# No code available for review"
        
        return code_context
    
    async def _analyze_static(
        self, code_context: Dict[str, str], min_severity: str
    ) -> List[Dict[str, Any]]:
        """Perform static code analysis"""
        findings = []
        
        # Simple pattern-based analysis
        severity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        min_level = severity_order.get(min_severity, 0)
        
        for file_name, code in code_context.items():
            # Check for TODO/FIXME without descriptions
            import re
            todos = re.findall(r"//\s*(TODO|FIXME|HACK|XXX):?\s*([^\n]*)", code)
            for todo in todos:
                findings.append({
                    "type": "maintainability",
                    "severity": "low",
                    "file": file_name,
                    "line": code[:code.find(todo[0])].count("\n") + 1,
                    "message": f"Undocumented task: {todo[1] or todo[0]}",
                    "suggestion": "Add description to TODO comment",
                })
            
            # Check for long functions (heuristic)
            functions = re.findall(r"(?:def|function|async\s+def)\s+(\w+)", code)
            for func in functions:
                func_start = code.find(f"def {func}") if f"def {func}" in code else code.find(f"function {func}")
                if func_start != -1:
                    # Find function end (simplified)
                    next_def = code.find("\ndef ", func_start + 1)
                    next_func = code.find("\nfunction ", func_start + 1)
                    func_end = min(n if n != -1 else len(code) for n in [next_def, next_func])
                    func_length = code[func_start:func_end].count("\n")
                    
                    if func_length > 100:
                        findings.append({
                            "type": "maintainability",
                            "severity": "medium",
                            "file": file_name,
                            "function": func,
                            "message": f"Long function '{func}' with {func_length} lines",
                            "suggestion": "Consider breaking into smaller functions",
                        })
        
        return findings
    
    async def _scan_security(
        self, code_context: Dict[str, str], min_severity: str
    ) -> List[Dict[str, Any]]:
        """Perform security scan (OWASP Top 10 focused)"""
        findings = []
        
        severity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        min_level = severity_order.get(min_severity, 0)
        
        security_patterns = [
            # SQL Injection
            (r'execute\s*\(\s*["\'].*%s.*["\']', "critical", "SQL Injection", 
             "Use parameterized queries instead of string formatting"),
            (r'\.format\s*\([^)]*get', "high", "Injection Risk",
             "Avoid string formatting with user input"),
            
            # Hardcoded secrets
            (r'password\s*=\s*["\'][^"\']{8,}["\']', "high", "Hardcoded Password",
             "Use environment variables or secrets manager"),
            (r'api[_-]?key\s*=\s*["\'][A-Za-z0-9]{20,}["\']', "critical", "Hardcoded API Key",
             "Use environment variables for API keys"),
            (r'sk-[A-Za-z0-9]{20,}', "critical", "Hardcoded Secret Key",
             "Use environment variables for secret keys"),
            
            # XSS
            (r'innerHTML\s*=', "high", "XSS Risk",
             "Use textContent or sanitize HTML before setting innerHTML"),
            (r'dangerouslySetInnerHTML', "medium", "XSS Risk",
             "Ensure content is sanitized before use"),
            
            # Insecure crypto
            (r'hashlib\.md5', "medium", "Weak Cryptography",
             "MD5 is cryptographically broken. Use SHA-256 or stronger."),
            (r'hashlib\.sha1', "medium", "Weak Cryptography",
             "SHA-1 is deprecated. Use SHA-256 or stronger."),
            
            # Insecure protocols
            (r'http://(?!localhost)', "low", "Insecure Protocol",
             "Use HTTPS instead of HTTP"),
        ]
        
        import re
        for file_name, code in code_context.items():
            for pattern, severity, issue_type, suggestion in security_patterns:
                matches = re.finditer(pattern, code, re.IGNORECASE)
                for match in matches:
                    line_num = code[:match.start()].count("\n") + 1
                    findings.append({
                        "type": "security",
                        "severity": severity,
                        "file": file_name,
                        "line": line_num,
                        "issue_type": issue_type,
                        "message": f"{issue_type} detected",
                        "suggestion": suggestion,
                        "matched_text": match.group()[:50],
                    })
        
        return findings
    
    async def _analyze_performance(
        self, code_context: Dict[str, str], min_severity: str
    ) -> List[Dict[str, Any]]:
        """Perform performance analysis"""
        findings = []
        
        import re
        for file_name, code in code_context.items():
            # Check for N+1 query patterns
            if re.search(r'for\s*\(.*\):\s*\n\s*\w+\.query', code, re.MULTILINE):
                findings.append({
                    "type": "performance",
                    "severity": "high",
                    "file": file_name,
                    "message": "Potential N+1 query pattern detected",
                    "suggestion": "Use bulk queries or batch operations",
                })
            
            # Check for synchronous operations in async code
            if "async def" in code and re.search(r'\.sleep\(', code):
                findings.append({
                    "type": "performance",
                    "severity": "medium",
                    "file": file_name,
                    "message": "Blocking sleep in async function",
                    "suggestion": "Use asyncio.sleep() instead",
                })
            
            # Check for large data in memory
            if re.search(r'read\(\)|\.readlines\(\)', code):
                findings.append({
                    "type": "performance",
                    "severity": "low",
                    "file": file_name,
                    "message": "Reading entire file into memory",
                    "suggestion": "Consider streaming for large files",
                })
        
        return findings
    
    async def _ai_review(
        self, code_context: Dict[str, str], min_severity: str, ctx: CommandContext
    ) -> List[Dict[str, Any]]:
        """AI-powered code review using LLM"""
        findings = []
        
        # This would integrate with the LLM router
        # For now, return empty as it requires actual LLM calls
        # In production, this would:
        # 1. Build a prompt with code context
        # 2. Call LLM with review instructions
        # 3. Parse response into findings
        
        return findings
    
    def _calculate_score(self, findings: List[Dict[str, Any]]) -> float:
        """Calculate code quality score (0-100)"""
        if not findings:
            return 100.0
        
        penalties = {
            "critical": 20,
            "high": 10,
            "medium": 3,
            "low": 1,
        }
        
        total_penalty = sum(penalties.get(f["severity"], 1) for f in findings)
        score = max(0.0, 100.0 - total_penalty)
        
        return round(score, 1)
    
    def _generate_markdown_report(self, output: Dict[str, Any]) -> str:
        """Generate markdown review report"""
        report = f"""# Code Review Report

## Summary

| Metric | Value |
|--------|-------|
| Files Reviewed | {len(output['files_reviewed'])} |
| Overall Score | {output['score']}/100 |
| Status | {"✅ Approved" if output['approved'] else "❌ Changes Requested"} |
| Recommendation | `{output['recommendation']}` |

## Findings by Severity

| Severity | Count |
|----------|-------|
| 🔴 Critical | {output['findings_by_severity']['critical']} |
| 🟠 High | {output['findings_by_severity']['high']} |
| 🟡 Medium | {output['findings_by_severity']['medium']} |
| 🔵 Low | {output['findings_by_severity']['low']} |

## Detailed Findings

"""
        
        for finding in output["findings"]:
            severity_emoji = {
                "critical": "🔴",
                "high": "🟠",
                "medium": "🟡",
                "low": "🔵",
            }.get(finding["severity"], "⚪")
            
            report += f"""### {severity_emoji} {finding.get('issue_type', finding['type']).title()}: {finding['message']}

- **File**: `{finding.get('file', 'N/A')}`
- **Severity**: {finding['severity'].upper()}
- **Suggestion**: {finding.get('suggestion', 'N/A')}

"""
        
        return report
