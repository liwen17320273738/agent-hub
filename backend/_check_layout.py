"""
Check that the LLM-generated ui_spec content has correct layout keywords
that _parse_spec will recognize as different layout types.
"""
import asyncio
import json
import re
import httpx

API_BASE = "http://localhost:8000/api"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI0MWIwYTg0NC1hZjY4LTQ0MDMtODM2OS0xYzUyYWRhMmNiNmMiLCJvcmciOiJlNmE3YTliOS0yZTU4LTQ4ZDMtYmZkYy0wNjQ2ZmE2OTkwMDEiLCJleHAiOjE3ODE1ODk1OTB9.BoWS6pgIWac5pG4yZk-qDY14L-OmZjIspABv93XeyjY"

TASKS = {
    "8e582352-a0e5-42bb-bce9-938c3cd5339f": "CRM Dashboard",
    "d28c2a24-c4f7-4e97-9430-f24cf0a2c912": "E-Commerce Store",
    "3fd63b98-93c6-4aff-ace8-555f1eee8a9e": "Blog Platform",
    "805e0881-2ed9-438a-8e45-6d63d75b0a40": "Chat Application",
    "6fb5d65b-b13c-4722-b844-c0addccc8ea0": "Project Kanban",
    "197e90f7-c099-4e43-8ecf-15bce85fac0c": "Marketing Landing Page",
    "0d4a3f76-910d-4ff6-b3bf-cb69e1d8c44e": "Settings Panel",
    "71f9e51d-413a-4566-90f8-29cf9d6a7bd2": "Learning Platform",
    "cc0952b2-30e1-419e-802c-ca2171322150": "Healthcare Dashboard",
    "87b0550d-62f7-4936-a630-87692f6f0f25": "Admin Analytics",
    "821adcde-7492-42c2-9d1a-c9a6a7345331": "Portfolio Site",
    "dc9156e3-fdf0-409a-88bb-2a4ef15a3f87": "SaaS Onboarding",
}

# Layout detection rules from _parse_spec
LAYOUT_RULES = [
    ("dashboard",        ["sidebar", "side nav", "drawer", "dashboard"]),
    ("single-page",      ["single page", "spa"]),
    ("landing-page",     ["landing", "marketing", "homepage", "portfolio"]),
    ("chat-app",         ["chat", "messenger", "im"]),
    ("blog-layout",      ["blog", "article", "post"]),
    ("ecommerce",        ["ecommerce", "shop", "store"]),
    ("settings-page",    ["setting", "config", "preference"]),
    ("kanban-board",     ["todo", "kanban"]),
]

async def main():
    headers = {"Authorization": f"Bearer {TOKEN}"}
    results = {}

    async with httpx.AsyncClient(base_url=API_BASE, timeout=30) as c:
        for tid, title in TASKS.items():
            # Get ui_spec
            r = await c.get(f"/tasks/{tid}/artifacts/ui_spec", headers=headers)
            cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', r.text)
            d = json.loads(cleaned)
            content = d.get("content", "")
            lower = content.lower()

            # Also get the original task description to compare
            r2 = await c.get(f"/pipeline/tasks/{tid}", headers=headers)
            cleaned2 = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', r2.text)
            task_data = json.loads(cleaned2).get("task", {})
            orig_desc = task_data.get("description", "").lower()

            # Determine layout from ui_spec
            detected_layout = "dashboard"  # default
            for layout_name, keywords in LAYOUT_RULES:
                if any(kw in lower for kw in keywords):
                    detected_layout = layout_name
                    # Special: kanban-board needs "board" but not "dashboard"
                    if layout_name == "kanban-board":
                        if "board" in lower and "dashboard" not in lower:
                            break
                        else:
                            detected_layout = "dashboard"
                    break

            # Determine expected layout from original description
            expected_layout = "dashboard"
            for layout_name, keywords in LAYOUT_RULES:
                if any(kw in orig_desc for kw in keywords):
                    expected_layout = layout_name
                    if layout_name == "kanban-board":
                        if "board" in orig_desc and "dashboard" not in orig_desc:
                            break
                        else:
                            expected_layout = "dashboard"
                    break

            # Check actual HTML file for layout structure
            mockup_r = await c.get(f"/tasks/{tid}/artifacts/ui_mockup", headers=headers)
            mockup_cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', mockup_r.text)
            mockup_d = json.loads(mockup_cleaned)
            meta = mockup_d.get("metadata") or mockup_d.get("metadata_json") or {}
            if isinstance(meta, str):
                meta = json.loads(meta) if meta else {}
            storage_path = meta.get("filePath", mockup_d.get("storage_path", ""))

            # Get actual HTML filename to see what layout was used
            html_filename = storage_path.split("/")[-1] if storage_path else "N/A"

            match = "✓" if detected_layout == expected_layout else f"✗ expected={expected_layout}"
            
            print(f"{title:25s} spec→{detected_layout:15s} desc→{expected_layout:15s} {match:30s} file={html_filename}")
            results[title] = {
                "detected": detected_layout,
                "expected": expected_layout,
                "match": detected_layout == expected_layout,
                "spec_len": len(content),
                "html_file": html_filename,
            }

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    mismatches = [t for t, r in results.items() if not r["match"]]
    if mismatches:
        print(f"\n⚠ MISMATCHES ({len(mismatches)}/{len(results)}):")
        for t in mismatches:
            r = results[t]
            print(f"  {t:25s} spec→{r['detected']:15s} expected→{r['expected']:15s}")
    else:
        print(f"\n✓ All {len(results)} tasks match expected layout!")

    print(f"\nUnique layouts generated: {len(set(r['detected'] for r in results.values()))}")
    layout_counts = {}
    for r in results.values():
        layout_counts[r["detected"]] = layout_counts.get(r["detected"], 0) + 1
    for layout, count in sorted(layout_counts.items()):
        print(f"  {layout:15s}: {count}x")

if __name__ == "__main__":
    asyncio.run(main())
