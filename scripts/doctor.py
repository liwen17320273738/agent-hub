#!/usr/bin/env python3
"""Pre-flight health check for the golden-path E2E flow.

Reports which dependencies are present/missing, what env vars are configured,
and whether the user can run the full "one-sentence → live preview" flow.

Exit codes:
  0 — all critical golden-path deps met
  1 — one or more critical deps missing
  2 — runtime error during check
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Helpers ──────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[1]


def _which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def _run(cmd: List[str], timeout: int = 10) -> Optional[str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or r.stderr).strip()
    except Exception:
        return None


def _ver(raw: Optional[str]) -> str:
    if not raw:
        return ""
    s = raw.strip().lstrip("v")
    return s.split()[0] if s else ""


def _load_dotenv(path: Path, into: Dict[str, str]) -> None:
    if not path.is_file():
        return
    for line in path.read_text("utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        if s.startswith("export "):
            s = s[7:].strip()
        k, v = s.split("=", 1)
        k = k.strip()
        v = v.strip().strip("\"'").split("#", 1)[0].strip()
        if k:
            into[k] = v


def _merged_env() -> Dict[str, str]:
    """Match scripts/serve.sh merge order: backend/.env first, root .env wins."""
    out = dict(os.environ)
    _load_dotenv(REPO_ROOT / "backend" / ".env", out)
    _load_dotenv(REPO_ROOT / ".env", out)
    return out


# ── Check categories ─────────────────────────────────────────────────────────

def _check_category(label: str, checks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Run a list of checks under a category heading.

    Each check dict:
      - name: str
      - command: list[str] | None    — PATH tool name or full command list
      - env_var: str | None          — env var name to inspect
      - file: str | None             — file path to check
      - version_args: list[str]      — how to get version (only for command)
      - critical: bool               — blocks golden path if missing
      - detail: str                  — human-readable description
    """
    env = _merged_env()
    results: List[Dict[str, Any]] = []

    for c in checks:
        row: Dict[str, Any] = {
            "name": c["name"],
            "critical": c.get("critical", False),
            "ok": False,
            "version": "",
            "value": "",
            "detail": c.get("detail", ""),
        }

        # CLI tool check
        if c.get("command"):
            cmd = c["command"]
            tool_path = _which(cmd[0] if isinstance(cmd, list) else cmd)
            if tool_path:
                ver_args = c.get("version_args")
                ver_out = _run([tool_path] + (ver_args or ["--version"])) if ver_args else None
                row["ok"] = True
                row["version"] = _ver(ver_out) if ver_out else ""
            else:
                row["ok"] = False
                row["detail"] = c.get("detail", f"`{cmd[0] if isinstance(cmd, list) else cmd}` not found on PATH")

        # Env var check
        if c.get("env_var"):
            val = env.get(c["env_var"], "")
            if val:
                row["ok"] = True
                row["value"] = val[:8] + "..." if len(val) > 10 else "(set)"
            else:
                row["ok"] = False
                row["detail"] = c.get("detail", f"`{c['env_var']}` not set")

        # File check
        if c.get("file"):
            fp = Path(c["file"]).expanduser()
            if fp.exists():
                row["ok"] = True
            else:
                row["ok"] = False
                row["detail"] = c.get("detail", f"File not found: {c['file']}")

        results.append(row)

    ok = all(r["ok"] for r in results)
    return {"label": label, "ok": ok, "items": results}


# ── Doctor ───────────────────────────────────────────────────────────────────

def main() -> int:
    env = _merged_env()
    categories: List[Dict[str, Any]] = []

    # 1. Runtime (basic — from check.py but version minimums)
    categories.append(_check_category("Runtime", [
        {
            "name": "Node.js",
            "command": ["node"],
            "version_args": ["-v"],
            "critical": True,
            "detail": "Required: pnpm, QA executor, Playwright, local preview build & serve.\n  ｜  Install: https://nodejs.org/ (>= 18)",
        },
        {
            "name": "pnpm",
            "command": ["pnpm"],
            "version_args": ["-v"],
            "critical": True,
            "detail": "Package manager for build, test, and preview.\n  ｜  Install: `npm install -g pnpm`",
        },
        {
            "name": "Python 3",
            "command": ["python3"],
            "version_args": ["--version"],
            "critical": True,
            "detail": "Backend runtime (FastAPI). Not found on PATH after dotenv merge.",
        },
    ]))

    # 2. Golden-path config keys
    #    List which LLM providers are configured; at least one is critical.
    llm_key_names = [
        ("OPENAI_API_KEY", True, "LLM: OpenAI (also used for Phase 5 image gen)"),
        ("ANTHROPIC_API_KEY", False, "LLM: Anthropic fallback"),
        ("DEEPSEEK_API_KEY", False, "LLM: DeepSeek (default)"),
        ("GOOGLE_API_KEY", False, "LLM: Gemini fallback"),
        ("ZHIPU_API_KEY", False, "LLM: Zhipu fallback"),
        ("QWEN_API_KEY", False, "LLM: Qwen fallback"),
        ("LLM_API_KEY", False, "Custom LLM endpoint key"),
    ]
    any_llm = False
    llm_items: List[Dict[str, Any]] = []
    for var_name, critical, detail in llm_key_names:
        val = env.get(var_name, "")
        ok = bool(val)
        if var_name == "OPENAI_API_KEY" and ok:
            any_llm = True  # openai is enough
        elif ok:
            any_llm = True
        llm_items.append({
            "name": var_name,
            "critical": False,
            "ok": ok,
            "version": "",
            "value": val[:8] + "..." if len(val) > 10 else f"({ 'set' if ok else 'unset' })",
            "detail": detail,
        })
    # Override: at least one LLM key required for golden path.
    llm_cat_ok = any_llm
    categories.append({
        "label": "LLM Provider Keys",
        "ok": llm_cat_ok,
        "items": llm_items,
        "_custom_summary": True,
        "_summary_ok": f"✓ {sum(1 for i in llm_items if i['ok'])} provider(s) configured",
        "_summary_fail": "✗ No LLM provider key set — pipeline stages will fail.\n  ｜  Set at least one: OPENAI_API_KEY, DEEPSEEK_API_KEY, etc.",
    })

    # 3. Golden-path deploy
    categories.append(_check_category("Deploy", [
        {
            "name": "VERCEL_TOKEN",
            "env_var": "VERCEL_TOKEN",
            "critical": False,
            "detail": "Vercel deployment. Without it, falls back to local preview (pnpm preview).",
        },
        {
            "name": "CLOUDFLARE_API_TOKEN",
            "env_var": "CLOUDFLARE_API_TOKEN",
            "critical": False,
            "detail": "Cloudflare Pages deployment (alternative to Vercel).",
        },
    ]))

    # 4. Code generation engine
    codegen_items: List[Dict[str, Any]] = []
    for exe_name, env_override in [("claude", "CLAUDE_PATH"), ("codex", "CODEX_PATH")]:
        path = env.get(env_override) if env_override in env else None
        found = _which(path or exe_name) is not None
        codegen_items.append({
            "name": f"{exe_name} CLI {'(' + env_override + ')' if env_override in env else ''}",
            "critical": False,
            "ok": found,
            "version": "",
            "value": f"({ path or 'PATH' })" if found else "(not found)",
            "detail": f"Code generation engine. Without it, codegen falls back to subprocess/bridge mode.",
        })
    codegen_ok = any(i["ok"] for i in codegen_items)
    categories.append({
        "label": "Code Generation Engine",
        "ok": codegen_ok,
        "items": codegen_items,
        "_custom_summary": True,
        "_summary_ok": "✓ Codegen engine available",
        "_summary_fail": "⚠ No codegen CLI found — falls back to bridge/extraction mode (slower/less reliable).\n  ｜  Install: Claude Code Desktop or `pip install codex`",
    })

    # 5. Browser automation
    pw_found = _which("playwright") is not None
    pw_ver = _ver(_run(["playwright", "--version"])) if pw_found else ""
    pw_chromium_found = False
    for base in [
        Path.home() / "Library" / "Caches" / "ms-playwright",
        Path.home() / ".cache" / "ms-playwright",
        Path("/root/.cache/ms-playwright"),
    ]:
        if base.is_dir() and any(
            d.is_dir() and d.name.startswith("chromium") for d in base.iterdir()
        ):
            pw_chromium_found = True
            break
    categories.append({
        "label": "Browser Automation",
        "ok": pw_found and pw_chromium_found,
        "items": [
            {
                "name": "playwright (CLI)",
                "ok": pw_found,
                "critical": True,
                "version": pw_ver,
                "detail": (""
                    if pw_found else
                    "Used by QA executor (Phase 6) for browser smoke and deploy (Phase 7) for preview screenshots.\n"
                    "  ｜  Install: `pip install playwright && playwright install chromium`"
                ),
            },
            {
                "name": "Chromium (playwright)",
                "ok": pw_chromium_found,
                "critical": True,
                "detail": ("Chromium browser binary found."
                    if pw_chromium_found else
                    "Playwright Chromium browser not installed.\n"
                    "  ｜  Run: `playwright install chromium`"
                ),
            },
        ],
    })

    # 6. Database infrastructure
    categories.append(_check_category("Database & Cache", [
        {
            "name": "PostgreSQL",
            "command": ["psql"],
            "version_args": ["--version"],
            "critical": True,
            "detail": "Primary database. Required for task persistence, artifact storage, user auth.\n  ｜  Install: `brew install postgresql` (macOS) / `apt install postgresql` (Linux)",
        },
        {
            "name": "Redis",
            "command": ["redis-cli"],
            "version_args": ["--version"],
            "critical": True,
            "detail": "Required for SSE event streaming, working memory, rate limiting.\n  ｜  Install: `brew install redis` (macOS) / `apt install redis` (Linux)",
        },
    ]))

    # 7. Design & visual (optional)
    design_env = _merged_env()
    design_items: List[Dict[str, Any]] = [
        {
            "name": "OPENAI_API_KEY",
            "ok": bool(design_env.get("OPENAI_API_KEY")),
            "critical": False,
            "detail": "For Phase 5 Dall-E 3 UI mockup generation.",
        },
        {
            "name": "GEMINI_API_KEY",
            "ok": bool(design_env.get("GEMINI_API_KEY")),
            "critical": False,
            "detail": "For Gemini-based image generation (nano-banana-pro).",
        },
    ]
    # Check mermaid CLI
    mmdc = _which("mmdc") or _which("mermaid")
    design_items.append({
        "name": "mermaid CLI (mmdc)",
        "command": ["mmdc", "--version"] if _which("mmdc") else (["mermaid", "--version"] if _which("mermaid") else []),
        "critical": False,
        "ok": mmdc is not None,
        "version": "",
        "value": "(not found, CDN fallback)" if not mmdc else "",
        "detail": "For offline Mermaid diagram rendering. Falls back to CDN if missing.",
    })
    categories.append({
        "label": "Design & Visual (optional)",
        "ok": True,
        "items": design_items,
    })

    # ── Render output ────────────────────────────────────────────────────

    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║         Agent Hub — Golden Path Health Check                ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    print(f"  Repo root: {REPO_ROOT}")
    print()

    all_critical_ok = True
    for cat in categories:
        label = cat["label"]
        cat_ok = cat["ok"]
        items = cat["items"]

        icon = "✓" if cat_ok else "✗"
        if label == "LLM Provider Keys":
            print(f"  [{icon}] {label}")
            if cat_ok:
                print(f"         {cat.get('_summary_ok', '')}")
            else:
                print(f"         {cat.get('_summary_fail', '')}")
        elif label == "Code Generation Engine":
            print(f"  [{icon}] {label}")
            if cat_ok:
                print(f"         {cat.get('_summary_ok', '')}")
            else:
                print(f"         {cat.get('_summary_fail', '')}")
        else:
            print(f"  [{icon}] {label}")

        for item in items:
            i_icon = "✓" if item["ok"] else "·"
            name = item["name"]
            critical_mark = " [CRITICAL]" if item.get("critical") else ""
            ver = f" v{item['version']}" if item.get("version") else ""
            val = f" = {item['value']}" if item.get("value") else ""

            if not item["ok"]:
                print(f"    {i_icon} {name}{ver}{val}{critical_mark}")
                detail = item.get("detail", "")
                if detail:
                    for line in detail.split("\n"):
                        print(f"      {line.strip()}")
                    print()

        if not cat_ok:
            for item in items:
                if not item["ok"] and item.get("critical"):
                    all_critical_ok = False

        print()

    # ── Summary ──────────────────────────────────────────────────────────
    print("────────────────────────────────────────────────────────────")
    if all_critical_ok:
        print("  ✓ All critical golden-path dependencies satisfied.")
        print()
        print("  You can run the full E2E flow:")
        print("    make config  →  make migrate  →  make dev")
        print()
        return 0

    print("  ✗ Some critical dependencies are missing.")
    print()
    print("  Details:")
    for cat in categories:
        for item in cat["items"]:
            if not item["ok"] and item.get("critical"):
                detail = item.get("detail", "")
                first_line = detail.split("\n")[0] if detail else ""
                print(f"    - {item['name']}: {first_line}")
    print()
    print("  Fix the above, then re-run:  make doctor")
    print()
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"[doctor] Runtime error: {e}")
        sys.exit(2)
