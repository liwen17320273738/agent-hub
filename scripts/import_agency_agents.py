#!/usr/bin/env python3
"""Import selected agency-agents as SKILL.md files into skills/custom/."""
import re
import sys
from pathlib import Path

AGENCY_ROOT = Path("/Users/wayne/Documents/agency-agents")
SKILLS_CUSTOM = Path("/Users/wayne/Documents/agent-hub/skills/custom")

STAGE_CATEGORY_MAP = {
    "engineering": "development",
    "testing": "testing",
    "design": "design",
    "product": "product",
    "strategy": "operations",
    "specialized": "specialized",
    "finance": "analysis",
    "project-management": "operations",
    "spatial-computing": "development",
}

SELECTED_AGENTS = [
    "engineering/engineering-frontend-developer.md",
    "engineering/engineering-backend-architect.md",
    "engineering/engineering-devops-automator.md",
    "engineering/engineering-senior-developer.md",
    "engineering/engineering-rapid-prototyper.md",
    "engineering/engineering-sre.md",
    "engineering/engineering-ai-engineer.md",
    "engineering/engineering-database-optimizer.md",
    "engineering/engineering-codebase-onboarding-engineer.md",
    "testing/testing-api-tester.md",
    "testing/testing-reality-checker.md",
    "testing/testing-performance-benchmarker.md",
    "testing/testing-accessibility-auditor.md",
    "testing/testing-evidence-collector.md",
    "design/design-ui-designer.md",
    "design/design-ux-researcher.md",
    "product/product-manager.md",
    "product/product-sprint-prioritizer.md",
    "specialized/specialized-workflow-architect.md",
    "specialized/specialized-mcp-builder.md",
    "specialized/compliance-auditor.md",
    "project-management/project-management-project-shepherd.md",
    "strategy/playbooks/phase-3-build.md",
    "strategy/playbooks/phase-4-hardening.md",
    "strategy/playbooks/phase-5-launch.md",
]


def parse_frontmatter(content: str):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
    if not m:
        return {}, content
    meta = {}
    for line in m.group(1).strip().splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        meta[key.strip()] = val.strip().strip("'\"")
    return meta, m.group(2).strip()


def agent_to_skill_id(path_str: str) -> str:
    name = Path(path_str).stem
    name = re.sub(r"^(engineering|testing|design|product|specialized|strategy|project-management)-", "", name)
    name = re.sub(r"^playbooks-", "", name)
    return name


def convert(agent_path: str) -> bool:
    src = AGENCY_ROOT / agent_path
    if not src.exists():
        print(f"  SKIP (not found): {agent_path}")
        return False

    content = src.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(content)

    skill_id = agent_to_skill_id(agent_path)
    category_key = agent_path.split("/")[0]
    category = STAGE_CATEGORY_MAP.get(category_key, "general")
    name = meta.get("name", skill_id.replace("-", " ").title())
    description = meta.get("description", "")
    emoji = meta.get("emoji", "")

    skill_md = f"""---
name: {skill_id}
description: "{emoji} {description}"
category: {category}
author: agency-agents
version: 1.0.0
tags: {skill_id}, {category}, agency-agents
enabled: true
---

# {name}

{body}
"""

    dest_dir = SKILLS_CUSTOM / skill_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
    print(f"  OK: {agent_path} -> skills/custom/{skill_id}/SKILL.md")
    return True


def main():
    print(f"Importing {len(SELECTED_AGENTS)} agents from {AGENCY_ROOT}")
    ok = 0
    for agent in SELECTED_AGENTS:
        if convert(agent):
            ok += 1
    print(f"\nDone: {ok}/{len(SELECTED_AGENTS)} imported to {SKILLS_CUSTOM}")


if __name__ == "__main__":
    main()
