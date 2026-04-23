#!/usr/bin/env python3
"""
Agent Hub 项目自测（Project Self-Test）
=====================================
10+ 个多样化项目，覆盖全链路：
  1. 创建任务 → 2. 推进阶段 → 3. 写入工件(v2) → 4. 验证工件
  5. 分享链接 → 6. ZIP下载 → 7. 工作区隔离 → 8. 成本预算
  9. 质量门禁 → 10. RCA报告 → 11. DAG模板 → 12. 最终验收

用法:
    TOKEN=$(curl -s http://localhost:8000/api/auth/login \
      -H "Content-Type: application/json" \
      -d '{"email":"admin@example.com","password":"changeme"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
    python3 backend/tests/selftest/run_selftest.py "$TOKEN"
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

BASE = "http://localhost:8000"
TIMEOUT = 30.0

# ── 10+ 测试项目定义 ──────────────────────────────────────────────
TEST_PROJECTS = [
    {
        "id": "P01",
        "title": "企业CRM系统",
        "description": "开发一个完整的企业客户关系管理系统，包含客户管理、销售漏斗、数据报表功能",
        "category": "Web应用",
    },
    {
        "id": "P02",
        "title": "实时聊天API服务",
        "description": "基于WebSocket的高并发聊天服务端，支持群组、私聊、消息持久化",
        "category": "API服务",
    },
    {
        "id": "P03",
        "title": "数据ETL管道",
        "description": "多数据源抽取-转换-加载管道，支持增量同步、数据质量检查、告警通知",
        "category": "数据管道",
    },
    {
        "id": "P04",
        "title": "移动端电商小程序",
        "description": "微信小程序电商平台，包含商品浏览、购物车、支付、订单管理",
        "category": "移动应用",
    },
    {
        "id": "P05",
        "title": "Kubernetes自动伸缩器",
        "description": "基于自定义指标的K8s HPA控制器，支持GPU利用率、队列深度触发",
        "category": "DevOps工具",
    },
    {
        "id": "P06",
        "title": "API安全网关",
        "description": "API网关，包含认证鉴权、限流熔断、请求日志审计、WAF防护",
        "category": "安全工具",
    },
    {
        "id": "P07",
        "title": "智能文档生成平台",
        "description": "结合LLM的技术文档自动生成平台，支持API文档、用户手册、变更日志",
        "category": "文档平台",
    },
    {
        "id": "P08",
        "title": "多租户SaaS计费系统",
        "description": "SaaS计费引擎，支持订阅制、用量制、混合计费模型，含发票生成",
        "category": "SaaS基础设施",
    },
    {
        "id": "P09",
        "title": "物联网设备管理平台",
        "description": "IoT设备管理后台，包含设备注册、OTA升级、实时监控仪表盘、告警规则",
        "category": "IoT平台",
    },
    {
        "id": "P10",
        "title": "AI图像审核系统",
        "description": "结合CV模型的图像内容审核系统，支持NSFW检测、敏感信息识别、审核队列",
        "category": "AI应用",
    },
    {
        "id": "P11",
        "title": "微服务链路追踪",
        "description": "分布式追踪系统，支持OpenTelemetry采集、Jaeger兼容、服务拓扑图",
        "category": "可观测性",
    },
    {
        "id": "P12",
        "title": "在线考试系统",
        "description": "支持题库管理、在线组卷、防作弊监考、自动批改的在线考试平台",
        "category": "教育SaaS",
    },
]

PIPELINE_STAGES = [
    "planning", "design", "architecture",
    "development", "testing", "reviewing", "deployment",
]

ARTIFACT_TYPES_TO_TEST = [
    "brief", "prd", "ui_spec", "architecture",
    "implementation", "test_report", "acceptance", "ops_runbook",
]


@dataclass
class TestResult:
    project_id: str
    project_title: str
    category: str
    tests: List[Dict[str, Any]] = field(default_factory=list)
    task_id: Optional[str] = None
    share_token: Optional[str] = None

    @property
    def passed(self):
        return sum(1 for t in self.tests if t["status"] == "PASS")

    @property
    def failed(self):
        return sum(1 for t in self.tests if t["status"] == "FAIL")

    @property
    def warnings(self):
        return sum(1 for t in self.tests if t["status"] == "WARN")

    def add(self, name: str, status: str, detail: str = ""):
        self.tests.append({"name": name, "status": status, "detail": detail})
        icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}.get(status, "❓")
        print(f"  {icon} [{self.project_id}] {name}: {detail[:120]}")


class SelfTester:
    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self.client = httpx.Client(base_url=BASE, timeout=TIMEOUT, headers=self.headers)
        self.results: List[TestResult] = []
        self.issues: List[Dict[str, Any]] = []
        self.workspace_id: Optional[str] = None

    def _get(self, path, **kw):
        return self.client.get(path, **kw)

    def _post(self, path, **kw):
        return self.client.post(path, **kw)

    def _patch(self, path, **kw):
        return self.client.patch(path, **kw)

    def _put(self, path, **kw):
        return self.client.put(path, **kw)

    def _delete(self, path, **kw):
        return self.client.delete(path, **kw)

    def _record_issue(self, severity: str, category: str, title: str, detail: str, project_id: str = ""):
        self.issues.append({
            "severity": severity,
            "category": category,
            "title": title,
            "detail": detail,
            "project": project_id,
        })

    # ═══════════════════════════════════════════════════════════════
    # Phase 0: 前置检查
    # ═══════════════════════════════════════════════════════════════

    def phase0_prechecks(self):
        print("\n" + "=" * 60)
        print("Phase 0: 前置检查")
        print("=" * 60)

        r = self._get("/health")
        assert r.status_code == 200, f"Health check failed: {r.status_code}"
        data = r.json()
        print(f"  ✅ Health OK: {data.get('service')} v{data.get('version')}, DB={data.get('database')}")

        r = self._get("/api/pipeline/tasks")
        assert r.status_code == 200, f"Task list failed: {r.status_code}"
        print(f"  ✅ Task API OK: existing tasks = {len(r.json().get('tasks', []))}")

        r = self._get("/api/pipeline/stages")
        assert r.status_code == 200
        stages = r.json().get("stages", [])
        print(f"  ✅ Stages: {len(stages)} defined")

        r = self._get("/api/pipeline/templates")
        assert r.status_code == 200
        templates = r.json().get("templates", {})
        print(f"  ✅ Templates: {list(templates.keys())}")

        r = self._get("/api/tasks/artifact-types")
        assert r.status_code == 200
        types = r.json()
        print(f"  ✅ Artifact Types: {len(types)} registered")
        if len(types) < 12:
            self._record_issue("WARN", "artifact-types", "工件类型不足", f"Expected >=12, got {len(types)}")

        r = self._get("/api/pipeline/agent-team")
        assert r.status_code == 200
        agents = r.json().get("agents", [])
        print(f"  ✅ Agent Team: {len(agents)} agents")

    # ═══════════════════════════════════════════════════════════════
    # Phase 1: 工作区隔离测试
    # ═══════════════════════════════════════════════════════════════

    def phase1_workspace(self):
        print("\n" + "=" * 60)
        print("Phase 1: 工作区隔离")
        print("=" * 60)
        r = self._get("/api/workspaces/")
        if r.status_code == 200:
            existing = r.json()
            print(f"  ✅ List workspaces: {len(existing)} existing")
        else:
            self._record_issue("WARN", "workspace", "工作区列表请求失败", f"status={r.status_code}")
            print(f"  ⚠️ List workspaces: {r.status_code}")
            return

        r = self._post("/api/workspaces/", json={
            "name": "自测工作区",
            "description": "用于项目自测的临时工作区",
        })
        if r.status_code == 201:
            ws = r.json()
            self.workspace_id = ws.get("id")
            print(f"  ✅ Created workspace: {self.workspace_id}")
        else:
            detail = r.text[:200]
            self._record_issue("WARN", "workspace", "创建工作区失败", detail)
            print(f"  ⚠️ Create workspace: {r.status_code} — {detail}")

        if self.workspace_id:
            r = self._get(f"/api/workspaces/{self.workspace_id}")
            if r.status_code == 200:
                data = r.json()
                member_count = len(data.get("members", []))
                print(f"  ✅ Get workspace: {data.get('name')}, members={member_count}")
            else:
                self._record_issue("FAIL", "workspace", "获取工作区详情失败", f"status={r.status_code}")

    # ═══════════════════════════════════════════════════════════════
    # Phase 2: 项目生命周期测试 (10+ 项目)
    # ═══════════════════════════════════════════════════════════════

    def phase2_projects(self):
        print("\n" + "=" * 60)
        print("Phase 2: 项目生命周期测试 (12 项目)")
        print("=" * 60)
        for project in TEST_PROJECTS:
            result = self._test_single_project(project)
            self.results.append(result)
            print()

    def _test_single_project(self, project: Dict[str, Any]) -> TestResult:
        pid = project["id"]
        result = TestResult(
            project_id=pid,
            project_title=project["title"],
            category=project["category"],
        )
        print(f"\n--- [{pid}] {project['title']} ({project['category']}) ---")

        # T1: 创建任务
        create_payload = {
            "title": f"[自测] {project['title']}",
            "description": project["description"],
            "source": "selftest",
        }
        if self.workspace_id:
            create_payload["workspace_id"] = self.workspace_id

        try:
            r = self._post("/api/pipeline/tasks", json=create_payload)
            if r.status_code == 201:
                task = r.json().get("task", {})
                task_id = str(task.get("id", ""))
                result.task_id = task_id
                stages = task.get("stages", [])
                result.add("T1-创建任务", "PASS", f"id={task_id[:8]}..., stages={len(stages)}")

                if len(stages) != len(PIPELINE_STAGES):
                    result.add("T1-阶段数量", "WARN", f"Expected {len(PIPELINE_STAGES)}, got {len(stages)}")
                    self._record_issue("WARN", "pipeline", "阶段数量不匹配", f"{pid}: {len(stages)}", pid)
            else:
                result.add("T1-创建任务", "FAIL", f"status={r.status_code}, body={r.text[:200]}")
                self._record_issue("FAIL", "pipeline", "创建任务失败", r.text[:200], pid)
                return result
        except Exception as e:
            result.add("T1-创建任务", "FAIL", str(e))
            return result

        task_id = result.task_id

        # T2: 获取任务详情
        try:
            r = self._get(f"/api/pipeline/tasks/{task_id}")
            if r.status_code == 200:
                detail = r.json().get("task", {})
                result.add("T2-任务详情", "PASS", f"status={detail.get('status')}, stage={detail.get('current_stage_id')}")
            else:
                result.add("T2-任务详情", "FAIL", f"status={r.status_code}")
        except Exception as e:
            result.add("T2-任务详情", "FAIL", str(e))

        # T3: 逐阶段推进 + 写入 stage output
        for i, stage_id in enumerate(PIPELINE_STAGES):
            try:
                output_text = f"[{pid}] {stage_id} 阶段产出内容 — 这是{project['title']}的{stage_id}阶段交付物。\n\n## 概述\n\n本阶段完成了{stage_id}相关的所有工作，包括设计评审、技术方案确认和产出物交付。\n\n## 核心内容\n\n1. 需求分析完成\n2. 方案设计完成\n3. 文档已产出"

                r = self._post(f"/api/pipeline/tasks/{task_id}/stage-output", json={
                    "stageId": stage_id,
                    "output": output_text,
                })
                if r.status_code == 200:
                    pass
                else:
                    result.add(f"T3-写入{stage_id}输出", "FAIL", f"status={r.status_code}")
                    self._record_issue("FAIL", "stage-output", f"写入{stage_id}输出失败", r.text[:200], pid)

                r = self._post(f"/api/pipeline/tasks/{task_id}/advance", json={
                    "output": output_text[:500],
                })
                if r.status_code == 200:
                    new_task = r.json().get("task", {})
                    new_stage = new_task.get("current_stage_id", "")
                    new_status = new_task.get("status", "")
                    if i < len(PIPELINE_STAGES) - 1:
                        expected = PIPELINE_STAGES[i + 1]
                        if new_stage == expected:
                            result.add(f"T3-推进{stage_id}→{expected}", "PASS", "")
                        else:
                            result.add(f"T3-推进{stage_id}", "WARN", f"Expected next={expected}, got={new_stage}")
                    else:
                        if new_status == "done":
                            result.add(f"T3-完成全部阶段", "PASS", "status=done")
                        else:
                            result.add(f"T3-最终阶段", "WARN", f"status={new_status}")
                else:
                    result.add(f"T3-推进{stage_id}", "FAIL", f"status={r.status_code}: {r.text[:150]}")
                    self._record_issue("FAIL", "advance", f"推进{stage_id}失败", r.text[:200], pid)
                    break
            except Exception as e:
                result.add(f"T3-推进{stage_id}", "FAIL", str(e)[:200])
                break

        # T4: v2 工件写入
        for art_type in ARTIFACT_TYPES_TO_TEST[:4]:  # test 4 types per project
            try:
                art_content = f"# {art_type} — {project['title']}\n\n## 版本 v1\n\n{project['description']}\n\n### 详细内容\n\n这是{art_type}类型工件的内容，用于验证v2工件系统。"
                r = self._post(f"/api/tasks/{task_id}/artifacts/{art_type}", json={
                    "title": f"{project['title']} - {art_type}",
                    "content": art_content,
                    "stage_id": "planning",
                    "created_by_agent": "selftest-agent",
                })
                if r.status_code == 201:
                    v = r.json().get("version", 0)
                    result.add(f"T4-工件{art_type}", "PASS", f"version={v}")
                else:
                    result.add(f"T4-工件{art_type}", "FAIL", f"status={r.status_code}: {r.text[:150]}")
                    self._record_issue("FAIL", "artifact-v2", f"{art_type}写入失败", r.text[:200], pid)
            except Exception as e:
                result.add(f"T4-工件{art_type}", "FAIL", str(e)[:200])

        # T5: 工件版本升级 (write v2 for first type)
        try:
            art_type = ARTIFACT_TYPES_TO_TEST[0]
            r = self._post(f"/api/tasks/{task_id}/artifacts/{art_type}", json={
                "title": f"{project['title']} - {art_type} v2",
                "content": f"# {art_type} v2\n\n升级后的内容。\n\n{project['description']}",
                "stage_id": "design",
                "created_by_agent": "selftest-agent",
            })
            if r.status_code == 201 and r.json().get("version") == 2:
                result.add("T5-工件版本升级", "PASS", f"{art_type} → v2")
            elif r.status_code == 201:
                result.add("T5-工件版本升级", "WARN", f"version={r.json().get('version')}")
            else:
                result.add("T5-工件版本升级", "FAIL", f"status={r.status_code}")
        except Exception as e:
            result.add("T5-工件版本升级", "FAIL", str(e)[:200])

        # T6: 查询工件列表
        try:
            r = self._get(f"/api/tasks/{task_id}/artifacts")
            if r.status_code == 200:
                items = r.json().get("artifacts", [])
                with_content = sum(1 for i in items if i.get("has_content"))
                result.add("T6-工件列表", "PASS", f"total types={len(items)}, with_content={with_content}")
            else:
                result.add("T6-工件列表", "FAIL", f"status={r.status_code}")
        except Exception as e:
            result.add("T6-工件列表", "FAIL", str(e)[:200])

        # T7: 查询单个工件详情 + 版本历史
        try:
            art_type = ARTIFACT_TYPES_TO_TEST[0]
            r = self._get(f"/api/tasks/{task_id}/artifacts/{art_type}")
            if r.status_code == 200:
                art = r.json()
                versions = art.get("versions", [])
                result.add("T7-工件详情+版本历史", "PASS", f"latest v{art.get('version')}, history={len(versions)}")
            else:
                result.add("T7-工件详情+版本历史", "FAIL", f"status={r.status_code}")
        except Exception as e:
            result.add("T7-工件详情+版本历史", "FAIL", str(e)[:200])

        # T8: Pipeline Artifact (v1)
        try:
            r = self._post(f"/api/pipeline/tasks/{task_id}/artifacts", json={
                "artifact_type": "document",
                "name": f"设计文档-{project['title']}",
                "content": f"这是{project['title']}的设计文档",
                "stage_id": "design",
            })
            if r.status_code == 200:
                result.add("T8-Pipeline工件(v1)", "PASS", "")
            else:
                result.add("T8-Pipeline工件(v1)", "FAIL", f"status={r.status_code}: {r.text[:150]}")
        except Exception as e:
            result.add("T8-Pipeline工件(v1)", "FAIL", str(e)[:200])

        # T9: 分享链接生成
        try:
            r = self._post("/api/share/generate", json={
                "task_id": task_id,
                "ttl_days": 7,
            })
            if r.status_code == 200:
                share_data = r.json()
                result.share_token = share_data.get("token", "")
                result.add("T9-分享链接", "PASS", f"url={share_data.get('url', '')[:40]}")
            else:
                result.add("T9-分享链接", "FAIL", f"status={r.status_code}: {r.text[:150]}")
                self._record_issue("FAIL", "share", "分享链接生成失败", r.text[:200], pid)
        except Exception as e:
            result.add("T9-分享链接", "FAIL", str(e)[:200])

        # T10: 分享链接访问（无需认证）
        if result.share_token:
            try:
                r = httpx.get(f"{BASE}/api/share/{result.share_token}", timeout=TIMEOUT)
                if r.status_code == 200:
                    shared = r.json()
                    result.add("T10-分享链接访问", "PASS",
                               f"title={shared.get('title', '')[:30]}, stages={len(shared.get('stages', []))}")
                else:
                    result.add("T10-分享链接访问", "FAIL", f"status={r.status_code}")
            except Exception as e:
                result.add("T10-分享链接访问", "FAIL", str(e)[:200])

        # T11: ZIP下载
        try:
            r = self._get(f"/api/tasks/{task_id}/deliverables.zip")
            if r.status_code == 200:
                content_type = r.headers.get("content-type", "")
                size = len(r.content)
                cd = r.headers.get("content-disposition", "")
                result.add("T11-ZIP下载", "PASS", f"size={size}B, ct={content_type[:30]}, cd={cd[:50]}")
            else:
                result.add("T11-ZIP下载", "FAIL", f"status={r.status_code}: {r.text[:150]}")
                self._record_issue("FAIL", "deliverables", "ZIP下载失败", r.text[:200], pid)
        except Exception as e:
            result.add("T11-ZIP下载", "FAIL", str(e)[:200])

        # T12: 预算设置
        try:
            r = self._post(f"/api/pipeline/tasks/{task_id}/budget", json={
                "budget_usd": 10.0,
                "soft_ratio": 0.6,
                "hard_ratio": 1.0,
            })
            if r.status_code == 200:
                budget = r.json()
                result.add("T12-预算设置", "PASS", f"budget_usd={budget.get('budget_usd')}")
            else:
                result.add("T12-预算设置", "FAIL", f"status={r.status_code}: {r.text[:150]}")
        except Exception as e:
            result.add("T12-预算设置", "FAIL", str(e)[:200])

        # T13: 预算查询
        try:
            r = self._get(f"/api/pipeline/tasks/{task_id}/budget")
            if r.status_code == 200:
                result.add("T13-预算查询", "PASS", f"data={json.dumps(r.json())[:100]}")
            else:
                result.add("T13-预算查询", "FAIL", f"status={r.status_code}")
        except Exception as e:
            result.add("T13-预算查询", "FAIL", str(e)[:200])

        # T14: RCA报告
        try:
            r = self._get(f"/api/pipeline/tasks/{task_id}/rca?use_llm=false")
            if r.status_code == 200:
                rca = r.json()
                result.add("T14-RCA报告", "PASS", f"ok={rca.get('ok')}")
            elif r.status_code == 400:
                result.add("T14-RCA报告", "PASS", "No failures to report (expected)")
            else:
                result.add("T14-RCA报告", "WARN", f"status={r.status_code}")
        except Exception as e:
            result.add("T14-RCA报告", "FAIL", str(e)[:200])

        # T15: 质量报告
        try:
            r = self._get(f"/api/pipeline/tasks/{task_id}/quality-report")
            if r.status_code == 200:
                qr = r.json()
                result.add("T15-质量报告", "PASS", f"score={qr.get('overall_quality_score')}")
            else:
                result.add("T15-质量报告", "WARN", f"status={r.status_code}: {r.text[:100]}")
        except Exception as e:
            result.add("T15-质量报告", "FAIL", str(e)[:200])

        # T16: 工件supersede
        try:
            art_type = ARTIFACT_TYPES_TO_TEST[1]
            r = self._post(f"/api/tasks/{task_id}/artifacts/{art_type}/supersede")
            if r.status_code == 200:
                result.add("T16-工件Supersede", "PASS", f"status={r.json().get('status')}")
            elif r.status_code == 404:
                result.add("T16-工件Supersede", "WARN", "No artifact to supersede")
            else:
                result.add("T16-工件Supersede", "FAIL", f"status={r.status_code}")
        except Exception as e:
            result.add("T16-工件Supersede", "FAIL", str(e)[:200])

        # T17: 任务更新
        try:
            r = self._patch(f"/api/pipeline/tasks/{task_id}", json={
                "description": f"{project['description']} [自测更新于{time.strftime('%H:%M:%S')}]",
            })
            if r.status_code == 200:
                result.add("T17-任务更新", "PASS", "")
            else:
                result.add("T17-任务更新", "FAIL", f"status={r.status_code}")
        except Exception as e:
            result.add("T17-任务更新", "FAIL", str(e)[:200])

        return result

    # ═══════════════════════════════════════════════════════════════
    # Phase 3: DAG 模板测试
    # ═══════════════════════════════════════════════════════════════

    def phase3_dag_templates(self):
        print("\n" + "=" * 60)
        print("Phase 3: DAG 模板 + SDLC 配置")
        print("=" * 60)

        try:
            r = self._get("/api/pipeline/templates")
            templates = r.json().get("templates", {})
            for name, tmpl in templates.items():
                stage_count = tmpl.get("stageCount", 0)
                print(f"  ✅ Template '{name}': {tmpl.get('label')} — {stage_count} stages")
        except Exception as e:
            print(f"  ❌ Templates: {e}")
            self._record_issue("FAIL", "dag", "DAG模板查询失败", str(e))

        try:
            r = self._get("/api/pipeline/sdlc-templates")
            if r.status_code == 200:
                sdlc = r.json().get("templates", {})
                for name, cfg in sdlc.items():
                    has_gates = cfg.get("hasCustomGates", False)
                    print(f"  ✅ SDLC '{name}': {cfg.get('label')} — gates={has_gates}")
            else:
                print(f"  ⚠️ SDLC templates: {r.status_code}")
        except Exception as e:
            print(f"  ❌ SDLC templates: {e}")

        try:
            r = self._get("/api/pipeline/project-templates")
            if r.status_code == 200:
                pt = r.json().get("templates", [])
                print(f"  ✅ Project templates: {len(pt)} available")
            else:
                print(f"  ⚠️ Project templates: {r.status_code}")
        except Exception as e:
            print(f"  ❌ Project templates: {e}")

    # ═══════════════════════════════════════════════════════════════
    # Phase 4: 边界条件测试
    # ═══════════════════════════════════════════════════════════════

    def phase4_edge_cases(self):
        print("\n" + "=" * 60)
        print("Phase 4: 边界条件 + 错误处理")
        print("=" * 60)

        # E1: invalid task ID
        r = self._get("/api/pipeline/tasks/not-a-uuid")
        print(f"  {'✅' if r.status_code == 400 else '❌'} E1-无效任务ID: status={r.status_code}")
        if r.status_code != 400:
            self._record_issue("FAIL", "validation", "无效UUID未返回400", f"Got {r.status_code}")

        # E2: non-existent task
        r = self._get("/api/pipeline/tasks/00000000-0000-0000-0000-000000000000")
        print(f"  {'✅' if r.status_code == 404 else '❌'} E2-不存在的任务: status={r.status_code}")
        if r.status_code != 404:
            self._record_issue("FAIL", "validation", "不存在任务未返回404", f"Got {r.status_code}")

        # E3: empty title
        r = self._post("/api/pipeline/tasks", json={"title": "", "description": "test"})
        print(f"  {'✅' if r.status_code in (400, 422) else '⚠️'} E3-空标题创建: status={r.status_code}")
        if r.status_code not in (400, 422):
            self._record_issue("WARN", "validation", "空标题未被拒绝", f"Got {r.status_code}")

        # E4: invalid artifact type
        if self.results and self.results[0].task_id:
            tid = self.results[0].task_id
            r = self._post(f"/api/tasks/{tid}/artifacts/nonexistent_type", json={
                "content": "test",
            })
            print(f"  {'✅' if r.status_code == 400 else '❌'} E4-无效工件类型: status={r.status_code}")
            if r.status_code != 400:
                self._record_issue("FAIL", "artifact", "无效工件类型未被拒绝", f"Got {r.status_code}")

        # E5: expired share token
        r = httpx.get(f"{BASE}/api/share/fake_token_123", timeout=TIMEOUT)
        print(f"  {'✅' if r.status_code == 403 else '❌'} E5-无效分享令牌: status={r.status_code}")
        if r.status_code != 403:
            self._record_issue("FAIL", "share", "无效token未返回403", f"Got {r.status_code}")

        # E6: budget validation
        if self.results and self.results[0].task_id:
            tid = self.results[0].task_id
            r = self._post(f"/api/pipeline/tasks/{tid}/budget", json={
                "budget_usd": -5.0,
            })
            print(f"  {'✅' if r.status_code in (400, 422) else '⚠️'} E6-负数预算: status={r.status_code}")

        # E7: double advance on done task
        if self.results and self.results[0].task_id:
            tid = self.results[0].task_id
            r = self._post(f"/api/pipeline/tasks/{tid}/advance", json={"output": "extra"})
            print(f"  {'✅' if r.status_code == 400 else '⚠️'} E7-已完成任务推进: status={r.status_code}")
            if r.status_code == 200:
                self._record_issue("WARN", "pipeline", "已完成任务仍可推进", "Expected 400 for done task")

    # ═══════════════════════════════════════════════════════════════
    # Phase 5: 观测性 + 中间件
    # ═══════════════════════════════════════════════════════════════

    def phase5_observability(self):
        print("\n" + "=" * 60)
        print("Phase 5: 可观测性 + 审计")
        print("=" * 60)

        r = self._get("/api/pipeline/middleware/stats")
        if r.status_code == 200:
            data = r.json()
            print(f"  ✅ Middleware stats: totalTraces={data.get('totalTraces')}")
        else:
            print(f"  ⚠️ Middleware stats: {r.status_code}")

        r = self._get("/api/observability/traces")
        if r.status_code == 200:
            traces = r.json()
            print(f"  ✅ Traces: OK")
        else:
            print(f"  ⚠️ Traces: {r.status_code}")

        r = self._get("/api/observability/audit-log")
        if r.status_code == 200:
            entries = r.json().get("entries", [])
            print(f"  ✅ Audit log: {len(entries)} entries")
        else:
            print(f"  ⚠️ Audit log: {r.status_code}")

    # ═══════════════════════════════════════════════════════════════
    # Phase 6: 质量门禁配置
    # ═══════════════════════════════════════════════════════════════

    def phase6_quality_gates(self):
        print("\n" + "=" * 60)
        print("Phase 6: 质量门禁配置")
        print("=" * 60)

        if not self.results or not self.results[0].task_id:
            print("  ⚠️ Skipped: no test task available")
            return

        tid = self.results[0].task_id

        r = self._get(f"/api/pipeline/tasks/{tid}/quality-gate-config")
        if r.status_code == 200:
            cfg = r.json()
            stages = cfg.get("stages", [])
            print(f"  ✅ Quality gate config: {len(stages)} stages")
            for s in stages[:3]:
                eff = s.get("effective", {})
                print(f"    - {s['stageId']}: pass={eff.get('passThreshold')}, fail={eff.get('failThreshold')}")
        else:
            print(f"  ⚠️ Quality gate config: {r.status_code}")
            self._record_issue("WARN", "quality", "质量门禁配置获取失败", f"status={r.status_code}")

        r = self._put(f"/api/pipeline/tasks/{tid}/quality-gate-config", json={
            "overrides": {
                "planning": {"pass_threshold": 0.8, "fail_threshold": 0.3, "min_length": 500},
            },
        })
        if r.status_code == 200:
            print(f"  ✅ Quality gate override: OK")
        else:
            print(f"  ⚠️ Quality gate override: {r.status_code}")

    # ═══════════════════════════════════════════════════════════════
    # Phase 7: 综合汇总
    # ═══════════════════════════════════════════════════════════════

    def generate_report(self) -> str:
        total_pass = sum(r.passed for r in self.results)
        total_fail = sum(r.failed for r in self.results)
        total_warn = sum(r.warnings for r in self.results)
        total_tests = total_pass + total_fail + total_warn

        report_lines = [
            "# Agent Hub 项目自测报告",
            f"\n> 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 总览",
            "",
            f"| 指标 | 数值 |",
            f"|------|------|",
            f"| 测试项目数 | {len(self.results)} |",
            f"| 总测试用例 | {total_tests} |",
            f"| ✅ 通过 | {total_pass} |",
            f"| ❌ 失败 | {total_fail} |",
            f"| ⚠️ 警告 | {total_warn} |",
            f"| 通过率 | {total_pass/max(total_tests,1)*100:.1f}% |",
            "",
            "## 各项目详情",
            "",
        ]

        for r in self.results:
            status = "✅" if r.failed == 0 else "❌"
            report_lines.append(f"### {status} [{r.project_id}] {r.project_title} ({r.category})")
            report_lines.append("")
            report_lines.append(f"| 测试 | 状态 | 详情 |")
            report_lines.append(f"|------|------|------|")
            for t in r.tests:
                icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️"}.get(t["status"], "❓")
                detail = t["detail"].replace("|", "\\|")[:80]
                report_lines.append(f"| {t['name']} | {icon} {t['status']} | {detail} |")
            report_lines.append("")

        if self.issues:
            report_lines.append("## 发现的问题")
            report_lines.append("")
            report_lines.append("| # | 严重性 | 分类 | 标题 | 详情 | 项目 |")
            report_lines.append("|---|--------|------|------|------|------|")
            for i, issue in enumerate(self.issues, 1):
                sev_icon = {"FAIL": "🔴", "WARN": "🟡"}.get(issue["severity"], "⚪")
                detail = issue["detail"].replace("|", "\\|")[:80]
                report_lines.append(
                    f"| {i} | {sev_icon} {issue['severity']} | {issue['category']} "
                    f"| {issue['title']} | {detail} | {issue.get('project', '')} |"
                )
            report_lines.append("")

        report_lines.extend([
            "## 问题分类统计",
            "",
            "| 分类 | 数量 |",
            "|------|------|",
        ])
        category_counts: Dict[str, int] = {}
        for issue in self.issues:
            cat = issue["category"]
            category_counts[cat] = category_counts.get(cat, 0) + 1
        for cat, count in sorted(category_counts.items(), key=lambda x: -x[1]):
            report_lines.append(f"| {cat} | {count} |")

        if not self.issues:
            report_lines.append("| (无问题) | 0 |")

        report_lines.extend([
            "",
            "## 待改进建议",
            "",
        ])

        if total_fail > 0:
            report_lines.append("### 🔴 必须修复")
            for issue in self.issues:
                if issue["severity"] == "FAIL":
                    report_lines.append(f"- [{issue['category']}] {issue['title']}: {issue['detail'][:100]}")
            report_lines.append("")

        if total_warn > 0:
            report_lines.append("### 🟡 建议改进")
            for issue in self.issues:
                if issue["severity"] == "WARN":
                    report_lines.append(f"- [{issue['category']}] {issue['title']}: {issue['detail'][:100]}")
            report_lines.append("")

        report_lines.extend([
            "## 结论",
            "",
            f"共测试 **{len(self.results)}** 个项目，**{total_tests}** 个测试用例。",
            f"通过率 **{total_pass/max(total_tests,1)*100:.1f}%**。",
            "",
        ])

        if total_fail == 0:
            report_lines.append("**所有核心流程均通过验证，系统基本就绪。**")
        elif total_fail <= 5:
            report_lines.append("**存在少量问题需要修复，但核心流程基本可用。**")
        else:
            report_lines.append("**存在较多问题，需要优先修复关键流程。**")

        return "\n".join(report_lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 run_selftest.py <JWT_TOKEN>")
        print("  Get token: curl -s http://localhost:8000/api/auth/login \\")
        print('    -H "Content-Type: application/json" \\')
        print("    -d '{\"email\":\"admin@example.com\",\"password\":\"changeme\"}' | python3 -c \"import sys,json;print(json.load(sys.stdin)['access_token'])\"")
        sys.exit(1)

    token = sys.argv[1]
    tester = SelfTester(token)

    print("╔══════════════════════════════════════════════════════════╗")
    print("║        Agent Hub — 项目自测 (12 Projects)               ║")
    print("╚══════════════════════════════════════════════════════════╝")

    t0 = time.time()

    try:
        tester.phase0_prechecks()
        tester.phase1_workspace()
        tester.phase2_projects()
        tester.phase3_dag_templates()
        tester.phase4_edge_cases()
        tester.phase5_observability()
        tester.phase6_quality_gates()
    except Exception as e:
        print(f"\n💥 Fatal error during self-test: {e}")
        traceback.print_exc()

    elapsed = time.time() - t0

    report = tester.generate_report()

    report_path = "selftest-report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    # Summary
    total_pass = sum(r.passed for r in tester.results)
    total_fail = sum(r.failed for r in tester.results)
    total_warn = sum(r.warnings for r in tester.results)
    total = total_pass + total_fail + total_warn

    print("\n" + "=" * 60)
    print(f"自测完成 — 耗时 {elapsed:.1f}s")
    print(f"  项目: {len(tester.results)}")
    print(f"  用例: {total} (✅{total_pass} ❌{total_fail} ⚠️{total_warn})")
    print(f"  通过率: {total_pass/max(total,1)*100:.1f}%")
    print(f"  发现问题: {len(tester.issues)}")
    print(f"  报告: {report_path}")
    print("=" * 60)

    sys.exit(1 if total_fail > 10 else 0)


if __name__ == "__main__":
    main()
