# Phase 0：冻结范围，定义唯一 Hero Path

## 目标

停止继续扩散功能，先定义一条必须跑通、能反复验证、能面向用户解释的主路径。

目标主路径：

1. 用户输入一句话。
2. Product Agent 生成结构化 PRD。
3. Designer Agent 生成 UI 设计规格和至少 1 张可预览设计图。
4. Architect Agent 生成架构说明和至少 1 张架构图。
5. Developer Agent 基于 Vue/Vite 黄金模板生成真实代码。
6. QA Agent 执行安装、构建、测试、浏览器截图。
7. DevOps Agent 启动预览或部署链接。
8. Acceptance Agent 生成分享链接和验收页。

## 本阶段不做

- 任意复杂 Workflow。
- 多语言、多框架通用代码生成。
- 复杂 MCP 市场化。
- 多平台部署。
- 大型企业 RBAC 深化。
- 泛化 App Store / Google Play 发布。

## 输入

- 总分析文档：`docs/analysis/2026-5-13-03.md`
- 现有项目规则：`AGENTS.md`、`CLAUDE.md`
- 当前后端 Pipeline / Workflow / Artifact 代码结构。

## 任务拆分

### 1. 定义唯一黄金模板

确定 MVP 只支持：

- Vue 3
- Vite
- TypeScript
- Element Plus 或轻量自研组件
- Vitest
- Playwright smoke
- 本地 preview，后续接 Vercel / Cloudflare Pages

### 2. 定义 7 个核心 Agent

只保留主路径必需 Agent：

- Product
- Designer
- Architect
- Developer
- QA
- DevOps
- Acceptance

其他 Agent 暂时降级为专家顾问池。

### 3. 定义固定阶段

固定阶段顺序：

```text
intake -> product -> design -> architecture -> development -> qa -> deployment -> acceptance
```

### 4. 明确暂停范围

所有不能直接提升 Hero Path 成功率的功能暂缓。

## 可能涉及文件

- `docs/analysis/2026-5-13-03.md`
- `docs/analysis/ai-legion-execution/README.md`
- `backend/app/agents/seed.py`
- `backend/app/services/collaboration.py`
- `backend/app/services/pipeline_engine.py`
- `src/views/Workflow.vue`
- `src/views/Team.vue`

## 强制产物

- Hero Path 定义文档。
- 7 个核心 Agent 清单。
- 暂缓功能清单。
- 黄金模板说明。

## 验收标准

- 文档中明确唯一黄金模板。
- 所有阶段都围绕这条路径服务。
- 新功能如果不能提高这条路径成功率，就不进入当前阶段。
- 团队页面和产品文案不再暗示“任意复杂任务都能稳定完成”。

## 风险

- 需求收缩会看起来“不够强”。
- 现有很多模块会暂时不作为主线。
- 如果不冻结范围，后续阶段会继续被泛化需求拖散。

## 执行完成标志

当团队能共同回答下面问题，本阶段完成：

> 当前唯一必须跑通的用户路径是什么？哪些能力暂时不做？
