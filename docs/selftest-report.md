# Agent Hub 项目自测报告

> 生成时间: 2026-04-27 13:15:13

## Hero Path 程序化 E2E（pytest，无真实 LLM）

**更新：2026-05-20**

Hero 验收拆成三层，避免「测试全绿但 PRD/UI/代码缺失」的假信号：

| 层级 | 测试 | 命令 | 说明 |
|------|------|------|------|
| **Smoke（状态机）** | `test_hero_delivery_path.py` | `pytest tests/test_hero_delivery_path.py -v` | `/advance` 走阶段 + 手动 POST stub 工件；断言 `all_required_satisfied is False` |
| **Acceptance（管线）** | `test_hero_pipeline_acceptance.py` | `pytest tests/test_hero_pipeline_acceptance.py -v` | 真实 `execute_stage` ×7（mock LLM / Phase 5–7）；断言质量契约 **满足** |
| **质量门** | `test_artifact_contract_quality.py` | `pytest tests/test_artifact_contract_quality.py -v` | 占位/mock PNG/假 deploy URL 进入 `invalid[]`，UI 显示「未达标」 |

Playwright：`tests/e2e/hero-smoke.spec.ts` — 仅 UI/API 接线（登录→建单→详情→分享），**不**断言交付物内容。

**2026-05-13（历史）** — 首版 `test_hero_delivery_path.py` 曾用 stub 占位且契约显示「满足」；现已加质量门，stub 任务应显示缺口。

| 项目 | 内容 |
|---|---|
| Smoke 测试文件 | `backend/tests/test_hero_delivery_path.py` |
| Acceptance 测试文件 | `backend/tests/test_hero_pipeline_acceptance.py` |
| 本地命令（推荐一起跑） | `cd backend && AGENTHUB_TEST_MINIMAL_LIFESPAN=1 python3 -m pytest tests/test_hero_delivery_path.py tests/test_hero_pipeline_acceptance.py tests/test_artifact_contract_quality.py -q` |
| 失败定位 | smoke：advance/分享/ZIP；acceptance：某阶段 `execute_stage` 失败或契约 `invalid`/`missing`；质量门：占位内容未拦截 |

本节与下方手工自测明细独立；下文表格仍为历史一次跑通快照。

## 总览

| 指标 | 数值 |
|------|------|
| 测试项目数 | 12 |
| 总测试用例 | 312 |
| ✅ 通过 | 312 |
| ❌ 失败 | 0 |
| ⚠️ 警告 | 0 |
| 通过率 | 100.0% |

## 各项目详情

### ✅ [P01] 企业CRM系统 (Web应用)

| 测试 | 状态 | 详情 |
|------|------|------|
| T1-创建任务 | ✅ PASS | id=8c40f98d..., stages=7 |
| T2-任务详情 | ✅ PASS | status=active, stage=planning |
| T3-推进planning→design | ✅ PASS |  |
| T3-推进design→architecture | ✅ PASS |  |
| T3-推进architecture→development | ✅ PASS |  |
| T3-推进development→testing | ✅ PASS |  |
| T3-推进testing→reviewing | ✅ PASS |  |
| T3-推进reviewing→deployment | ✅ PASS |  |
| T3-完成全部阶段 | ✅ PASS | status=done |
| T4-工件brief | ✅ PASS | version=1 |
| T4-工件prd | ✅ PASS | version=1 |
| T4-工件ui_spec | ✅ PASS | version=1 |
| T4-工件architecture | ✅ PASS | version=1 |
| T5-工件版本升级 | ✅ PASS | brief → v2 |
| T6-工件列表 | ✅ PASS | total types=12, with_content=4 |
| T7-工件详情+版本历史 | ✅ PASS | latest v2, history=2 |
| T8-Pipeline工件(v1) | ✅ PASS |  |
| T9-分享链接 | ✅ PASS | url=/share/OGM0MGY5OGQtZmYwOC00MmEyLTljZWEtN |
| T10-分享链接访问 | ✅ PASS | title=[自测] 企业CRM系统, stages=7 |
| T11-ZIP下载 | ✅ PASS | size=1438B, ct=application/zip, cd=attachment; filename="deliverables-8c40f98d.z |
| T12-预算设置 | ✅ PASS | budget_usd=10.0 |
| T13-预算查询 | ✅ PASS | data={"task_id": "8c40f98d-ff08-42a2-9cea-69573b75c545", "spent_usd": 0.0, "budg |
| T14-RCA报告 | ✅ PASS | ok=True |
| T15-质量报告 | ✅ PASS | score=None |
| T16-工件Supersede | ✅ PASS | status=superseded |
| T17-任务更新 | ✅ PASS |  |

### ✅ [P02] 实时聊天API服务 (API服务)

| 测试 | 状态 | 详情 |
|------|------|------|
| T1-创建任务 | ✅ PASS | id=c5bceba0..., stages=7 |
| T2-任务详情 | ✅ PASS | status=active, stage=planning |
| T3-推进planning→design | ✅ PASS |  |
| T3-推进design→architecture | ✅ PASS |  |
| T3-推进architecture→development | ✅ PASS |  |
| T3-推进development→testing | ✅ PASS |  |
| T3-推进testing→reviewing | ✅ PASS |  |
| T3-推进reviewing→deployment | ✅ PASS |  |
| T3-完成全部阶段 | ✅ PASS | status=done |
| T4-工件brief | ✅ PASS | version=1 |
| T4-工件prd | ✅ PASS | version=1 |
| T4-工件ui_spec | ✅ PASS | version=1 |
| T4-工件architecture | ✅ PASS | version=1 |
| T5-工件版本升级 | ✅ PASS | brief → v2 |
| T6-工件列表 | ✅ PASS | total types=12, with_content=4 |
| T7-工件详情+版本历史 | ✅ PASS | latest v2, history=2 |
| T8-Pipeline工件(v1) | ✅ PASS |  |
| T9-分享链接 | ✅ PASS | url=/share/YzViY2ViYTAtZTU1Zi00MTVlLWFkNWMtO |
| T10-分享链接访问 | ✅ PASS | title=[自测] 实时聊天API服务, stages=7 |
| T11-ZIP下载 | ✅ PASS | size=1443B, ct=application/zip, cd=attachment; filename="deliverables-c5bceba0.z |
| T12-预算设置 | ✅ PASS | budget_usd=10.0 |
| T13-预算查询 | ✅ PASS | data={"task_id": "c5bceba0-e55f-415e-ad5c-9f994ebaf434", "spent_usd": 0.0, "budg |
| T14-RCA报告 | ✅ PASS | ok=True |
| T15-质量报告 | ✅ PASS | score=None |
| T16-工件Supersede | ✅ PASS | status=superseded |
| T17-任务更新 | ✅ PASS |  |

### ✅ [P03] 数据ETL管道 (数据管道)

| 测试 | 状态 | 详情 |
|------|------|------|
| T1-创建任务 | ✅ PASS | id=c63a2ced..., stages=7 |
| T2-任务详情 | ✅ PASS | status=active, stage=planning |
| T3-推进planning→design | ✅ PASS |  |
| T3-推进design→architecture | ✅ PASS |  |
| T3-推进architecture→development | ✅ PASS |  |
| T3-推进development→testing | ✅ PASS |  |
| T3-推进testing→reviewing | ✅ PASS |  |
| T3-推进reviewing→deployment | ✅ PASS |  |
| T3-完成全部阶段 | ✅ PASS | status=done |
| T4-工件brief | ✅ PASS | version=1 |
| T4-工件prd | ✅ PASS | version=1 |
| T4-工件ui_spec | ✅ PASS | version=1 |
| T4-工件architecture | ✅ PASS | version=1 |
| T5-工件版本升级 | ✅ PASS | brief → v2 |
| T6-工件列表 | ✅ PASS | total types=12, with_content=4 |
| T7-工件详情+版本历史 | ✅ PASS | latest v2, history=2 |
| T8-Pipeline工件(v1) | ✅ PASS |  |
| T9-分享链接 | ✅ PASS | url=/share/YzYzYTJjZWQtNmY0Yi00MzE3LWE1NTMtZ |
| T10-分享链接访问 | ✅ PASS | title=[自测] 数据ETL管道, stages=7 |
| T11-ZIP下载 | ✅ PASS | size=1438B, ct=application/zip, cd=attachment; filename="deliverables-c63a2ced.z |
| T12-预算设置 | ✅ PASS | budget_usd=10.0 |
| T13-预算查询 | ✅ PASS | data={"task_id": "c63a2ced-6f4b-4317-a553-d0b118bd1447", "spent_usd": 0.0, "budg |
| T14-RCA报告 | ✅ PASS | ok=True |
| T15-质量报告 | ✅ PASS | score=None |
| T16-工件Supersede | ✅ PASS | status=superseded |
| T17-任务更新 | ✅ PASS |  |

### ✅ [P04] 移动端电商小程序 (移动应用)

| 测试 | 状态 | 详情 |
|------|------|------|
| T1-创建任务 | ✅ PASS | id=51e0e110..., stages=7 |
| T2-任务详情 | ✅ PASS | status=active, stage=planning |
| T3-推进planning→design | ✅ PASS |  |
| T3-推进design→architecture | ✅ PASS |  |
| T3-推进architecture→development | ✅ PASS |  |
| T3-推进development→testing | ✅ PASS |  |
| T3-推进testing→reviewing | ✅ PASS |  |
| T3-推进reviewing→deployment | ✅ PASS |  |
| T3-完成全部阶段 | ✅ PASS | status=done |
| T4-工件brief | ✅ PASS | version=1 |
| T4-工件prd | ✅ PASS | version=1 |
| T4-工件ui_spec | ✅ PASS | version=1 |
| T4-工件architecture | ✅ PASS | version=1 |
| T5-工件版本升级 | ✅ PASS | brief → v2 |
| T6-工件列表 | ✅ PASS | total types=12, with_content=4 |
| T7-工件详情+版本历史 | ✅ PASS | latest v2, history=2 |
| T8-Pipeline工件(v1) | ✅ PASS |  |
| T9-分享链接 | ✅ PASS | url=/share/NTFlMGUxMTAtMTY3Ny00MTIzLThkZmUtY |
| T10-分享链接访问 | ✅ PASS | title=[自测] 移动端电商小程序, stages=7 |
| T11-ZIP下载 | ✅ PASS | size=1448B, ct=application/zip, cd=attachment; filename="deliverables-51e0e110.z |
| T12-预算设置 | ✅ PASS | budget_usd=10.0 |
| T13-预算查询 | ✅ PASS | data={"task_id": "51e0e110-1677-4123-8dfe-afa731945a4d", "spent_usd": 0.0, "budg |
| T14-RCA报告 | ✅ PASS | ok=True |
| T15-质量报告 | ✅ PASS | score=None |
| T16-工件Supersede | ✅ PASS | status=superseded |
| T17-任务更新 | ✅ PASS |  |

### ✅ [P05] Kubernetes自动伸缩器 (DevOps工具)

| 测试 | 状态 | 详情 |
|------|------|------|
| T1-创建任务 | ✅ PASS | id=6daede9b..., stages=7 |
| T2-任务详情 | ✅ PASS | status=active, stage=planning |
| T3-推进planning→design | ✅ PASS |  |
| T3-推进design→architecture | ✅ PASS |  |
| T3-推进architecture→development | ✅ PASS |  |
| T3-推进development→testing | ✅ PASS |  |
| T3-推进testing→reviewing | ✅ PASS |  |
| T3-推进reviewing→deployment | ✅ PASS |  |
| T3-完成全部阶段 | ✅ PASS | status=done |
| T4-工件brief | ✅ PASS | version=1 |
| T4-工件prd | ✅ PASS | version=1 |
| T4-工件ui_spec | ✅ PASS | version=1 |
| T4-工件architecture | ✅ PASS | version=1 |
| T5-工件版本升级 | ✅ PASS | brief → v2 |
| T6-工件列表 | ✅ PASS | total types=12, with_content=4 |
| T7-工件详情+版本历史 | ✅ PASS | latest v2, history=2 |
| T8-Pipeline工件(v1) | ✅ PASS |  |
| T9-分享链接 | ✅ PASS | url=/share/NmRhZWRlOWItNjUxOS00MDRiLWI0NTEtY |
| T10-分享链接访问 | ✅ PASS | title=[自测] Kubernetes自动伸缩器, stages=7 |
| T11-ZIP下载 | ✅ PASS | size=1447B, ct=application/zip, cd=attachment; filename="deliverables-6daede9b.z |
| T12-预算设置 | ✅ PASS | budget_usd=10.0 |
| T13-预算查询 | ✅ PASS | data={"task_id": "6daede9b-6519-404b-b451-cf500d5d13cf", "spent_usd": 0.0, "budg |
| T14-RCA报告 | ✅ PASS | ok=True |
| T15-质量报告 | ✅ PASS | score=None |
| T16-工件Supersede | ✅ PASS | status=superseded |
| T17-任务更新 | ✅ PASS |  |

### ✅ [P06] API安全网关 (安全工具)

| 测试 | 状态 | 详情 |
|------|------|------|
| T1-创建任务 | ✅ PASS | id=3e8c54c1..., stages=7 |
| T2-任务详情 | ✅ PASS | status=active, stage=planning |
| T3-推进planning→design | ✅ PASS |  |
| T3-推进design→architecture | ✅ PASS |  |
| T3-推进architecture→development | ✅ PASS |  |
| T3-推进development→testing | ✅ PASS |  |
| T3-推进testing→reviewing | ✅ PASS |  |
| T3-推进reviewing→deployment | ✅ PASS |  |
| T3-完成全部阶段 | ✅ PASS | status=done |
| T4-工件brief | ✅ PASS | version=1 |
| T4-工件prd | ✅ PASS | version=1 |
| T4-工件ui_spec | ✅ PASS | version=1 |
| T4-工件architecture | ✅ PASS | version=1 |
| T5-工件版本升级 | ✅ PASS | brief → v2 |
| T6-工件列表 | ✅ PASS | total types=12, with_content=4 |
| T7-工件详情+版本历史 | ✅ PASS | latest v2, history=2 |
| T8-Pipeline工件(v1) | ✅ PASS |  |
| T9-分享链接 | ✅ PASS | url=/share/M2U4YzU0YzEtMzZjNC00YWQzLWJmZTYtZ |
| T10-分享链接访问 | ✅ PASS | title=[自测] API安全网关, stages=7 |
| T11-ZIP下载 | ✅ PASS | size=1438B, ct=application/zip, cd=attachment; filename="deliverables-3e8c54c1.z |
| T12-预算设置 | ✅ PASS | budget_usd=10.0 |
| T13-预算查询 | ✅ PASS | data={"task_id": "3e8c54c1-36c4-4ad3-bfe6-ffb65a56cf9b", "spent_usd": 0.0, "budg |
| T14-RCA报告 | ✅ PASS | ok=True |
| T15-质量报告 | ✅ PASS | score=None |
| T16-工件Supersede | ✅ PASS | status=superseded |
| T17-任务更新 | ✅ PASS |  |

### ✅ [P07] 智能文档生成平台 (文档平台)

| 测试 | 状态 | 详情 |
|------|------|------|
| T1-创建任务 | ✅ PASS | id=b1ebd799..., stages=7 |
| T2-任务详情 | ✅ PASS | status=active, stage=planning |
| T3-推进planning→design | ✅ PASS |  |
| T3-推进design→architecture | ✅ PASS |  |
| T3-推进architecture→development | ✅ PASS |  |
| T3-推进development→testing | ✅ PASS |  |
| T3-推进testing→reviewing | ✅ PASS |  |
| T3-推进reviewing→deployment | ✅ PASS |  |
| T3-完成全部阶段 | ✅ PASS | status=done |
| T4-工件brief | ✅ PASS | version=1 |
| T4-工件prd | ✅ PASS | version=1 |
| T4-工件ui_spec | ✅ PASS | version=1 |
| T4-工件architecture | ✅ PASS | version=1 |
| T5-工件版本升级 | ✅ PASS | brief → v2 |
| T6-工件列表 | ✅ PASS | total types=12, with_content=4 |
| T7-工件详情+版本历史 | ✅ PASS | latest v2, history=2 |
| T8-Pipeline工件(v1) | ✅ PASS |  |
| T9-分享链接 | ✅ PASS | url=/share/YjFlYmQ3OTktMGE5OS00YTQ1LTk4ZWUtZ |
| T10-分享链接访问 | ✅ PASS | title=[自测] 智能文档生成平台, stages=7 |
| T11-ZIP下载 | ✅ PASS | size=1447B, ct=application/zip, cd=attachment; filename="deliverables-b1ebd799.z |
| T12-预算设置 | ✅ PASS | budget_usd=10.0 |
| T13-预算查询 | ✅ PASS | data={"task_id": "b1ebd799-0a99-4a45-98ee-f485f2bfbb63", "spent_usd": 0.0, "budg |
| T14-RCA报告 | ✅ PASS | ok=True |
| T15-质量报告 | ✅ PASS | score=None |
| T16-工件Supersede | ✅ PASS | status=superseded |
| T17-任务更新 | ✅ PASS |  |

### ✅ [P08] 多租户SaaS计费系统 (SaaS基础设施)

| 测试 | 状态 | 详情 |
|------|------|------|
| T1-创建任务 | ✅ PASS | id=25074b9f..., stages=7 |
| T2-任务详情 | ✅ PASS | status=active, stage=planning |
| T3-推进planning→design | ✅ PASS |  |
| T3-推进design→architecture | ✅ PASS |  |
| T3-推进architecture→development | ✅ PASS |  |
| T3-推进development→testing | ✅ PASS |  |
| T3-推进testing→reviewing | ✅ PASS |  |
| T3-推进reviewing→deployment | ✅ PASS |  |
| T3-完成全部阶段 | ✅ PASS | status=done |
| T4-工件brief | ✅ PASS | version=1 |
| T4-工件prd | ✅ PASS | version=1 |
| T4-工件ui_spec | ✅ PASS | version=1 |
| T4-工件architecture | ✅ PASS | version=1 |
| T5-工件版本升级 | ✅ PASS | brief → v2 |
| T6-工件列表 | ✅ PASS | total types=12, with_content=4 |
| T7-工件详情+版本历史 | ✅ PASS | latest v2, history=2 |
| T8-Pipeline工件(v1) | ✅ PASS |  |
| T9-分享链接 | ✅ PASS | url=/share/MjUwNzRiOWYtY2VmYi00MDVkLThhYjAtN |
| T10-分享链接访问 | ✅ PASS | title=[自测] 多租户SaaS计费系统, stages=7 |
| T11-ZIP下载 | ✅ PASS | size=1447B, ct=application/zip, cd=attachment; filename="deliverables-25074b9f.z |
| T12-预算设置 | ✅ PASS | budget_usd=10.0 |
| T13-预算查询 | ✅ PASS | data={"task_id": "25074b9f-cefb-405d-8ab0-6bd950df9521", "spent_usd": 0.0, "budg |
| T14-RCA报告 | ✅ PASS | ok=True |
| T15-质量报告 | ✅ PASS | score=None |
| T16-工件Supersede | ✅ PASS | status=superseded |
| T17-任务更新 | ✅ PASS |  |

### ✅ [P09] 物联网设备管理平台 (IoT平台)

| 测试 | 状态 | 详情 |
|------|------|------|
| T1-创建任务 | ✅ PASS | id=caa4c78f..., stages=7 |
| T2-任务详情 | ✅ PASS | status=active, stage=planning |
| T3-推进planning→design | ✅ PASS |  |
| T3-推进design→architecture | ✅ PASS |  |
| T3-推进architecture→development | ✅ PASS |  |
| T3-推进development→testing | ✅ PASS |  |
| T3-推进testing→reviewing | ✅ PASS |  |
| T3-推进reviewing→deployment | ✅ PASS |  |
| T3-完成全部阶段 | ✅ PASS | status=done |
| T4-工件brief | ✅ PASS | version=1 |
| T4-工件prd | ✅ PASS | version=1 |
| T4-工件ui_spec | ✅ PASS | version=1 |
| T4-工件architecture | ✅ PASS | version=1 |
| T5-工件版本升级 | ✅ PASS | brief → v2 |
| T6-工件列表 | ✅ PASS | total types=12, with_content=4 |
| T7-工件详情+版本历史 | ✅ PASS | latest v2, history=2 |
| T8-Pipeline工件(v1) | ✅ PASS |  |
| T9-分享链接 | ✅ PASS | url=/share/Y2FhNGM3OGYtMzZkMi00YzZjLWEyMzktM |
| T10-分享链接访问 | ✅ PASS | title=[自测] 物联网设备管理平台, stages=7 |
| T11-ZIP下载 | ✅ PASS | size=1451B, ct=application/zip, cd=attachment; filename="deliverables-caa4c78f.z |
| T12-预算设置 | ✅ PASS | budget_usd=10.0 |
| T13-预算查询 | ✅ PASS | data={"task_id": "caa4c78f-36d2-4c6c-a239-3ef4459165af", "spent_usd": 0.0, "budg |
| T14-RCA报告 | ✅ PASS | ok=True |
| T15-质量报告 | ✅ PASS | score=None |
| T16-工件Supersede | ✅ PASS | status=superseded |
| T17-任务更新 | ✅ PASS |  |

### ✅ [P10] AI图像审核系统 (AI应用)

| 测试 | 状态 | 详情 |
|------|------|------|
| T1-创建任务 | ✅ PASS | id=e38954c9..., stages=7 |
| T2-任务详情 | ✅ PASS | status=active, stage=planning |
| T3-推进planning→design | ✅ PASS |  |
| T3-推进design→architecture | ✅ PASS |  |
| T3-推进architecture→development | ✅ PASS |  |
| T3-推进development→testing | ✅ PASS |  |
| T3-推进testing→reviewing | ✅ PASS |  |
| T3-推进reviewing→deployment | ✅ PASS |  |
| T3-完成全部阶段 | ✅ PASS | status=done |
| T4-工件brief | ✅ PASS | version=1 |
| T4-工件prd | ✅ PASS | version=1 |
| T4-工件ui_spec | ✅ PASS | version=1 |
| T4-工件architecture | ✅ PASS | version=1 |
| T5-工件版本升级 | ✅ PASS | brief → v2 |
| T6-工件列表 | ✅ PASS | total types=12, with_content=4 |
| T7-工件详情+版本历史 | ✅ PASS | latest v2, history=2 |
| T8-Pipeline工件(v1) | ✅ PASS |  |
| T9-分享链接 | ✅ PASS | url=/share/ZTM4OTU0YzktZGZiZi00MWY0LWI4ODQtZ |
| T10-分享链接访问 | ✅ PASS | title=[自测] AI图像审核系统, stages=7 |
| T11-ZIP下载 | ✅ PASS | size=1444B, ct=application/zip, cd=attachment; filename="deliverables-e38954c9.z |
| T12-预算设置 | ✅ PASS | budget_usd=10.0 |
| T13-预算查询 | ✅ PASS | data={"task_id": "e38954c9-dfbf-41f4-b884-f71bda33f63c", "spent_usd": 0.0, "budg |
| T14-RCA报告 | ✅ PASS | ok=True |
| T15-质量报告 | ✅ PASS | score=None |
| T16-工件Supersede | ✅ PASS | status=superseded |
| T17-任务更新 | ✅ PASS |  |

### ✅ [P11] 微服务链路追踪 (可观测性)

| 测试 | 状态 | 详情 |
|------|------|------|
| T1-创建任务 | ✅ PASS | id=be053c62..., stages=7 |
| T2-任务详情 | ✅ PASS | status=active, stage=planning |
| T3-推进planning→design | ✅ PASS |  |
| T3-推进design→architecture | ✅ PASS |  |
| T3-推进architecture→development | ✅ PASS |  |
| T3-推进development→testing | ✅ PASS |  |
| T3-推进testing→reviewing | ✅ PASS |  |
| T3-推进reviewing→deployment | ✅ PASS |  |
| T3-完成全部阶段 | ✅ PASS | status=done |
| T4-工件brief | ✅ PASS | version=1 |
| T4-工件prd | ✅ PASS | version=1 |
| T4-工件ui_spec | ✅ PASS | version=1 |
| T4-工件architecture | ✅ PASS | version=1 |
| T5-工件版本升级 | ✅ PASS | brief → v2 |
| T6-工件列表 | ✅ PASS | total types=12, with_content=4 |
| T7-工件详情+版本历史 | ✅ PASS | latest v2, history=2 |
| T8-Pipeline工件(v1) | ✅ PASS |  |
| T9-分享链接 | ✅ PASS | url=/share/YmUwNTNjNjItNmI2NC00ZWU3LTg4M2MtO |
| T10-分享链接访问 | ✅ PASS | title=[自测] 微服务链路追踪, stages=7 |
| T11-ZIP下载 | ✅ PASS | size=1445B, ct=application/zip, cd=attachment; filename="deliverables-be053c62.z |
| T12-预算设置 | ✅ PASS | budget_usd=10.0 |
| T13-预算查询 | ✅ PASS | data={"task_id": "be053c62-6b64-4ee7-883c-852c9037ad22", "spent_usd": 0.0, "budg |
| T14-RCA报告 | ✅ PASS | ok=True |
| T15-质量报告 | ✅ PASS | score=None |
| T16-工件Supersede | ✅ PASS | status=superseded |
| T17-任务更新 | ✅ PASS |  |

### ✅ [P12] 在线考试系统 (教育SaaS)

| 测试 | 状态 | 详情 |
|------|------|------|
| T1-创建任务 | ✅ PASS | id=bb29440c..., stages=7 |
| T2-任务详情 | ✅ PASS | status=active, stage=planning |
| T3-推进planning→design | ✅ PASS |  |
| T3-推进design→architecture | ✅ PASS |  |
| T3-推进architecture→development | ✅ PASS |  |
| T3-推进development→testing | ✅ PASS |  |
| T3-推进testing→reviewing | ✅ PASS |  |
| T3-推进reviewing→deployment | ✅ PASS |  |
| T3-完成全部阶段 | ✅ PASS | status=done |
| T4-工件brief | ✅ PASS | version=1 |
| T4-工件prd | ✅ PASS | version=1 |
| T4-工件ui_spec | ✅ PASS | version=1 |
| T4-工件architecture | ✅ PASS | version=1 |
| T5-工件版本升级 | ✅ PASS | brief → v2 |
| T6-工件列表 | ✅ PASS | total types=12, with_content=4 |
| T7-工件详情+版本历史 | ✅ PASS | latest v2, history=2 |
| T8-Pipeline工件(v1) | ✅ PASS |  |
| T9-分享链接 | ✅ PASS | url=/share/YmIyOTQ0MGMtYWEzZC00NmMyLTllYjgtZ |
| T10-分享链接访问 | ✅ PASS | title=[自测] 在线考试系统, stages=7 |
| T11-ZIP下载 | ✅ PASS | size=1442B, ct=application/zip, cd=attachment; filename="deliverables-bb29440c.z |
| T12-预算设置 | ✅ PASS | budget_usd=10.0 |
| T13-预算查询 | ✅ PASS | data={"task_id": "bb29440c-aa3d-46c2-9eb8-d51727b58199", "spent_usd": 0.0, "budg |
| T14-RCA报告 | ✅ PASS | ok=True |
| T15-质量报告 | ✅ PASS | score=None |
| T16-工件Supersede | ✅ PASS | status=superseded |
| T17-任务更新 | ✅ PASS |  |

## 问题分类统计

| 分类 | 数量 |
|------|------|
| (无问题) | 0 |

## 待改进建议

## 结论

共测试 **12** 个项目，**312** 个测试用例。
通过率 **100.0%**。

**所有核心流程均通过验证，系统基本就绪。**