"""
Compare actual HTML content of all 12 generated mockups to verify diversity.
Fetches HTML files via worktree API and compares content hashes.
"""
import asyncio
import hashlib
import json
import re
import httpx

API_BASE = "http://localhost:8000/api"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI0MWIwYTg0NC1hZjY4LTQ0MDMtODM2OS0xYzUyYWRhMmNiNmMiLCJvcmciOiJlNmE3YTliOS0yZTU4LTQ4ZDMtYmZkYy0wNjQ2ZmE2OTkwMDEiLCJleHAiOjE3ODE1ODk1OTB9.BoWS6pgIWac5pG4yZk-qDY14L-OmZjIspABv93XeyjY"

TASK_IDS = [
    "8e582352-a0e5-42bb-bce9-938c3cd5339f",  # CRM Dashboard
    "d28c2a24-c4f7-4e97-9430-f24cf0a2c912",  # E-Commerce Store
    "3fd63b98-93c6-4aff-ace8-555f1eee8a9e",  # Blog Platform
    "805e0881-2ed9-438a-8e45-6d63d75b0a40",  # Chat Application
    "6fb5d65b-b13c-4722-b844-c0addccc8ea0",  # Project Kanban
    "197e90f7-c099-4e43-8ecf-15bce85fac0c",  # Marketing Landing Page
    "0d4a3f76-910d-4ff6-b3bf-cb69e1d8c44e",  # Settings Panel
    "71f9e51d-413a-4566-90f8-29cf9d6a7bd2",  # Learning Platform
    "cc0952b2-30e1-419e-802c-ca2171322150",  # Healthcare Dashboard
    "87b0550d-62f7-4936-a630-87692f6f0f25",  # Admin Analytics
    "821adcde-7492-42c2-9d1a-c9a6a7345331",  # Portfolio Site
    "dc9156e3-fdf0-409a-88bb-2a4ef15a3f87",  # SaaS Onboarding
]

async def main():
    headers = {"Authorization": f"Bearer {TOKEN}"}
    results = []

    async with httpx.AsyncClient(base_url=API_BASE, timeout=30) as c:
        for tid in TASK_IDS:
            # 1. Get task title
            r = await c.get(f"/pipeline/tasks/{tid}", headers=headers)
            cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', r.text)
            task_data = json.loads(cleaned).get("task", {})
            title = task_data.get("title", "?").replace("[E2E] ", "")

            # 2. Get ui_spec (LLM-generated design spec — content)
            r = await c.get(f"/tasks/{tid}/artifacts/ui_spec", headers=headers)
            spec_data = {}
            if r.status_code == 200:
                cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', r.text)
                spec_data = json.loads(cleaned)
            spec_content = spec_data.get("content", "")
            spec_hash = hashlib.md5(spec_content.encode()).hexdigest()[:16]
            spec_len = len(spec_content)

            # 3. Get ui_mockup_html storage_path
            r = await c.get(f"/tasks/{tid}/artifacts/ui_mockup_html", headers=headers)
            html_data = {}
            if r.status_code == 200:
                cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', r.text)
                html_data = json.loads(cleaned)
            storage_path = html_data.get("storage_path", "")

            # 4. Fetch the actual HTML file from worktree
            html_content = ""
            if storage_path:
                r = await c.get(f"/tasks/{tid}/worktree/raw/{storage_path}", headers=headers)
                if r.status_code == 200:
                    html_content = r.text

            html_hash = hashlib.md5(html_content.encode()).hexdigest()[:16] if html_content else "N/A"
            html_len = len(html_content)

            results.append({
                "title": title,
                "spec_hash": spec_hash,
                "spec_len": spec_len,
                "storage_path": storage_path,
                "html_hash": html_hash,
                "html_len": html_len,
            })

            print(f"{title:25s} spec={spec_hash[:10]}..({spec_len}c)  html={html_hash[:10]}..({html_len}c)  path={storage_path[:50] if storage_path else 'N/A'}")

    # DIVERSITY CHECK
    print()
    print("=" * 80)
    print("DIVERSITY CHECK: Are the HTML contents actually different?")
    print("=" * 80)
    
    spec_hashes = {r["spec_hash"] for r in results if r["spec_hash"]}
    html_hashes = {r["html_hash"] for r in results if r["html_hash"] != "N/A"}
    
    print(f"\nUnique ui_spec (LLM) contents: {len(spec_hashes)}/{len(results)}")
    print(f"Unique HTML file contents:     {len(html_hashes)}/{len(results)}")
    
    if len(spec_hashes) == 1:
        print("\n⚠ PROBLEM: All ui_spec contents are IDENTICAL!")
        print("  This means the LLM generated the same design spec for all tasks.")
        print("  But wait — the spec content length varies, so let me check more closely...")
    
    # Group by HTML hash
    from collections import Counter
    html_counts = Counter(r["html_hash"] for r in results if r["html_hash"] != "N/A")
    dup_html = {h: c for h, c in html_counts.items() if c > 1}
    
    if dup_html:
        print(f"\n⚠ DUPLICATE HTML FILES FOUND: {len(dup_html)} hash(es) shared across tasks:")
        for h, c in dup_html.items():
            tasks = [r["title"] for r in results if r["html_hash"] == h]
            print(f"  {h} → {c}x: {', '.join(tasks)}")
    else:
        print(f"\n✓ All {len(results)} HTML files have unique content hashes. Diversity confirmed!")
    
    # Show spec vs html comparison
    print()
    print("-" * 80)
    print("DETAILED COMPARISON TABLE")
    print("-" * 80)
    print(f"{'Task':25s} {'Spec(MD5)':18s} {'HTML(MD5)':18s} {'SpecLen':8s} {'HTMLLen':8s}")
    print("-" * 80)
    for r in results:
        print(f"{r['title']:25s} {r['spec_hash'][:12]:18s} {r['html_hash'][:12]:18s} {r['spec_len']:8d} {r['html_len']:8d}")

if __name__ == "__main__":
    asyncio.run(main())
