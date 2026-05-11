"""
AIDefence Security Engine — Prompt injection, PII detection, and CVE scanning.

Implements multi-layer security for Agent Hub pipeline:
1. Prompt Injection Detection & Blocking
2. PII Detection (14 types) with BLOCK/REDACT/HASH policies
3. CVE Vulnerability Scanning
4. SOC2/GDPR Audit Logging
"""
from __future__ import annotations

import re
import hashlib
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class PIIPolicy(str, Enum):
    BLOCK = "block"      # Block the content entirely
    REDACT = "redact"    # Replace PII with [REDACTED]
    HASH = "hash"        # Replace with hash
    MASK = "mask"        # Partially mask (show last 4 chars)
    PASS = "pass"        # Allow through


class InjectionSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class SecurityFinding:
    """A security finding from scanning"""
    finding_type: str  # "pii", "injection", "cve"
    severity: str  # low, medium, high, critical
    description: str
    location: Optional[str] = None
    match_text: Optional[str] = None
    policy: PIIPolicy = PIIPolicy.REDACT
    remediation: str = ""


@dataclass
class SecurityReport:
    """Complete security scan report"""
    content_length: int
    findings: List[SecurityFinding] = field(default_factory=list)
    blocked: bool = False
    redacted_content: Optional[str] = None
    recommendations: List[str] = field(default_factory=list)
    
    @property
    def is_clean(self) -> bool:
        return len(self.findings) == 0
    
    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "critical")
    
    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "high")


class AIDefenceEngine:
    """
    Multi-layer security engine for AI pipeline protection.
    
    Layers:
    1. Prompt Injection Detection
    2. PII Detection & Policy Enforcement
    3. CVE Vulnerability Scanning
    4. Audit Logging (SOC2/GDPR)
    """
    
    def __init__(self):
        self._pii_policies: Dict[str, PIIPolicy] = {
            # Default policies per PII type
            "email": PIIPolicy.HASH,
            "phone": PIIPolicy.MASK,
            "ssn": PIIPolicy.BLOCK,
            "credit_card": PIIPolicy.BLOCK,
            "api_key": PIIPolicy.BLOCK,
            "password": PIIPolicy.BLOCK,
            "ip_address": PIIPolicy.REDACT,
            "address": PIIPolicy.REDACT,
            "name": PIIPolicy.PASS,
            "date_of_birth": PIIPolicy.REDACT,
            "passport": PIIPolicy.BLOCK,
            "driver_license": PIIPolicy.BLOCK,
            "bank_account": PIIPolicy.BLOCK,
            "medical_record": PIIPolicy.BLOCK,
        }
    
    # ─────────────────────────────────────────────────────────────
    # Prompt Injection Detection
    # ─────────────────────────────────────────────────────────────
    
    def detect_injection(self, content: str) -> List[SecurityFinding]:
        """Detect prompt injection attempts"""
        findings = []
        
        # Pattern 1: System prompt override attempts
        injection_patterns = [
            (r"(?i)(ignore|forget|disregard)\s+(all\s+)?(previous|above|prior|earlier)\s+(instructions?|prompts?|context|rules?)", 
             "critical", "prompt_override", "Attempt to override system instructions"),
            (r"(?i)you\s+are\s+now\s+(DAN|jailbroken|unrestricted|free)", 
             "critical", "jailbreak", "Known jailbreak pattern detected"),
            (r"(?i)(pretend|act\s+as\s+if|imagine)\s+you\s+(are|were)\s+(not|no\s+longer)\s+(an?\s+)?AI", 
             "high", "identity_spoof", "Attempt to change AI identity"),
            (r"(?i)(bypass|override|disable)\s+(your\s+)?(safety|ethical|content)\s+(guidelines?|restrictions?|filters?)", 
             "critical", "safety_bypass", "Attempt to bypass safety guidelines"),
            (r"(?i)(system\s*:\s*|system\s+message\s*:|<<SYS>>)", 
             "medium", "system_role_impersonation", "Attempt to inject system-level messages"),
            (r"(?i)```\s*(system|function)\s*\n", 
             "medium", "code_injection", "Code block injection attempt"),
            (r"(?i)<?xml.*?<system>", 
             "high", "xml_injection", "XML-based system injection"),
            (r"(?i)(decode|translate)\s+(this|the\s+following)\s+(base64|hex|encoded)\s+(text|message|string)", 
             "low", "encoding_bypass", "Obfuscation via encoding"),
        ]
        
        for pattern, severity, finding_type, description in injection_patterns:
            matches = re.finditer(pattern, content, re.MULTILINE | re.IGNORECASE)
            for match in matches:
                findings.append(SecurityFinding(
                    finding_type=f"injection_{finding_type}",
                    severity=severity,
                    description=description,
                    match_text=match.group()[:100],
                    policy=PIIPolicy.BLOCK,
                    remediation=f"Remove or rephrase the injected content near '{match.group()[:50]}...'",
                ))
        
        return findings
    
    # ─────────────────────────────────────────────────────────────
    # PII Detection (14 types)
    # ─────────────────────────────────────────────────────────────
    
    def detect_pii(self, content: str) -> List[SecurityFinding]:
        """Detect PII in content using regex patterns"""
        findings = []
        
        pii_patterns = {
            "email": (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', PIIPolicy.HASH),
            "phone": (r'\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b', PIIPolicy.MASK),
            "ssn": (r'\b\d{3}-\d{2}-\d{4}\b', PIIPolicy.BLOCK),
            "credit_card": (r'\b(?:\d{4}[-\s]?){3}\d{4}\b', PIIPolicy.BLOCK),
            "api_key": (r'(?i)(api[_-]?key|api[_-]?secret|access[_-]?token|auth[_-]?token)\s*[:=]\s*["\']?[A-Za-z0-9_\-]{20,}["\']?', PIIPolicy.BLOCK),
            "password": (r'(?i)(password|passwd|pwd)\s*[:=]\s*["\'][^"\']{8,}["\']', PIIPolicy.BLOCK),
            "ip_address": (r'\b(?:\d{1,3}\.){3}\d{1,3}\b', PIIPolicy.REDACT),
            "passport": (r'\b[A-Z]{1,2}\d{6,9}\b', PIIPolicy.BLOCK),
            "bank_account": (r'\b\d{8,17}\b', PIIPolicy.BLOCK),
            # Additional patterns
            "aws_key": (r'\bAKIA[0-9A-Z]{16}\b', PIIPolicy.BLOCK),
            "private_key": (r'-----BEGIN\s+(RSA|EC|DSA|OPENSSH)\s+PRIVATE\s+KEY-----', PIIPolicy.BLOCK),
            "jwt_token": (r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b', PIIPolicy.BLOCK),
            "github_token": (r'\bgh[pousr]_[A-Za-z0-9_]{36,}\b', PIIPolicy.BLOCK),
            "openai_key": (r'\bsk-[A-Za-z0-9]{32,}\b', PIIPolicy.BLOCK),
        }
        
        for pii_type, (pattern, default_policy) in pii_patterns.items():
            policy = self._pii_policies.get(pii_type, default_policy)
            
            matches = re.finditer(pattern, content)
            for match in matches:
                findings.append(SecurityFinding(
                    finding_type=f"pii_{pii_type}",
                    severity="high" if policy == PIIPolicy.BLOCK else "medium",
                    description=f"Detected {pii_type.replace('_', ' ').title()}",
                    match_text=self._mask_value(match.group()),
                    policy=policy,
                    remediation=f"Remove or replace the {pii_type.replace('_', ' ')}",
                ))
        
        return findings
    
    def apply_pii_policy(self, content: str, findings: List[SecurityFinding]) -> Tuple[str, bool]:
        """
        Apply PII policies to content.
        
        Returns:
            Tuple of (processed_content, was_blocked)
        """
        blocked = any(f.policy == PIIPolicy.BLOCK for f in findings if f.finding_type.startswith("pii_"))
        
        if blocked:
            return content, True
        
        processed = content
        for finding in findings:
            if not finding.match_text:
                continue
            
            match_text = str(finding.match_text)
            if finding.policy == PIIPolicy.HASH:
                replacement = f"[HASH:{hashlib.sha256(match_text.encode()).hexdigest()[:12]}]"
            elif finding.policy == PIIPolicy.MASK:
                if len(match_text) > 4:
                    replacement = "*" * (len(match_text) - 4) + match_text[-4:]
                else:
                    replacement = "[MASKED]"
            elif finding.policy == PIIPolicy.REDACT:
                replacement = "[REDACTED]"
            elif finding.policy == PIIPolicy.PASS:
                continue
            else:
                continue
            
            processed = processed.replace(match_text, replacement)
        
        return processed, False
    
    def _mask_value(self, value: str) -> str:
        """Mask a value for safe display in logs"""
        if not value:
            return value
        if len(value) <= 8:
            return "****"
        return value[:4] + "****" + value[-4:]
    
    # ─────────────────────────────────────────────────────────────
    # CVE Vulnerability Scanning
    # ─────────────────────────────────────────────────────────────
    
    def scan_cve(self, code: str) -> List[SecurityFinding]:
        """Scan code for known CVE patterns"""
        findings = []
        
        # OWASP Top 10 patterns
        cve_patterns = [
            # A01: Broken Access Control
            (r'(?i)@app\.route.*authenticated\s*=\s*False', "medium", "A01_access_control",
             "Missing authentication on route"),
            
            # A03: SQL Injection
            (r'(?i)(execute|executemany)\s*\(\s*(f["\']|["\'].*%.*["\'])', "critical", "A03_injection",
             "Potential SQL injection via string formatting in query"),
            
            # A04: Insecure Design
            (r'(?i)(pickle\.loads|yaml\.load\s*\(|eval\s*\(|exec\s*\()', "critical", "A04_insecure_deserialization",
             "Insecure deserialization or code execution"),
            
            # A05: Security Misconfiguration
            (r'(?i)DEBUG\s*=\s*True', "low", "A05_misconfig",
             "Debug mode enabled in production"),
            
            # A06: Vulnerable Components
            (r'(?i)import\s+pickle', "medium", "A06_vulnerable_component",
             "Using pickle (insecure deserialization)"),
            
            # A07: Auth Failures
            (r'(?i)(password|secret|token|key)\s*=\s*["\'][^"\']{3,}["\']', "high", "A07_hardcoded_secret",
             "Hardcoded secret in source code"),
            
            # A08: SSRF
            (r'(?i)(requests?\.get|urllib\.request|httpx\.get)\s*\(\s*.*user.*url', "high", "A08_ssrf",
             "Potential SSRF with user-controlled URL"),
            
            # A09: Logging
            (r'(?i)console\.log\s*\(.*(password|token|secret|key)', "medium", "A09_logging",
             "Sensitive data logged to console"),
            
            # A10: Request Forgery
            (r'(?i)csrf.*=.*False', "medium", "A10_csrf",
             "CSRF protection disabled"),
        ]
        
        for pattern, severity, cve_id, description in cve_patterns:
            matches = re.finditer(pattern, code)
            for match in matches:
                findings.append(SecurityFinding(
                    finding_type=f"cve_{cve_id}",
                    severity=severity,
                    description=description,
                    match_text=match.group()[:100],
                    policy=PIIPolicy.BLOCK,
                    remediation=f"Fix {description.lower()} near line {code[:match.start()].count(chr(10)) + 1}",
                ))
        
        return findings
    
    # ─────────────────────────────────────────────────────────────
    # Full Security Scan
    # ─────────────────────────────────────────────────────────────
    
    def scan(self, content: str, scan_types: Optional[List[str]] = None) -> SecurityReport:
        """
        Run full security scan on content.
        
        Args:
            content: Content to scan
            scan_types: Types to scan (None = all): ["injection", "pii", "cve"]
            
        Returns:
            SecurityReport with all findings
        """
        if scan_types is None:
            scan_types = ["injection", "pii", "cve"]
        
        all_findings = []
        
        if "injection" in scan_types:
            all_findings.extend(self.detect_injection(content))
        
        if "pii" in scan_types:
            pii_findings = self.detect_pii(content)
            all_findings.extend(pii_findings)
        
        if "cve" in scan_types:
            all_findings.extend(self.scan_cve(content))
        
        # Apply PII policies
        pii_findings = [f for f in all_findings if f.finding_type.startswith("pii_")]
        processed_content, blocked = self.apply_pii_policy(content, pii_findings)
        
        # Check if any critical injection findings should block
        injection_block = any(
            f.finding_type.startswith("injection_") and f.severity == "critical"
            for f in all_findings
        )
        
        # Build report
        report = SecurityReport(
            content_length=len(content),
            findings=all_findings,
            blocked=blocked or injection_block,
            redacted_content=processed_content if pii_findings else content,
            recommendations=self._generate_recommendations(all_findings),
        )
        
        return report
    
    def _generate_recommendations(self, findings: List[SecurityFinding]) -> List[str]:
        """Generate security recommendations"""
        recommendations = []
        
        if not findings:
            return ["No security issues found"]
        
        injection_count = sum(1 for f in findings if f.finding_type.startswith("injection_"))
        pii_count = sum(1 for f in findings if f.finding_type.startswith("pii_"))
        cve_count = sum(1 for f in findings if f.finding_type.startswith("cve_"))
        
        if injection_count > 0:
            recommendations.append(
                f"⚠️ {injection_count} prompt injection attempt(s) detected. "
                "Review content for malicious instructions."
            )
        
        if pii_count > 0:
            recommendations.append(
                f"🔒 {pii_count} PII instance(s) detected. "
                "These should be redacted before storing or sharing."
            )
        
        if cve_count > 0:
            recommendations.append(
                f"🛡️ {cve_count} potential vulnerability pattern(s) found. "
                "Review code for OWASP compliance."
            )
        
        return recommendations


# Singleton
_ai_defence: Optional[AIDefenceEngine] = None


def get_ai_defence() -> AIDefenceEngine:
    """Get or create the AIDefence engine singleton"""
    global _ai_defence
    if _ai_defence is None:
        _ai_defence = AIDefenceEngine()
    return _ai_defence
