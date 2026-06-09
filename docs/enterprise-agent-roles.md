# 企业 AI Agent 全角色覆盖平台

> 一个公司里所有可以用 AI Agent 自动化赋能的人+场景全景图

---

## 一、研发线 (Engineering)

| 角色 | Agent 名称 | 核心能力 | 接入工具 | 联动禅道 |
|------|-----------|---------|---------|---------|
| **后端开发** | Developer-Backend | 查Bug→修复→测试→提交→禅道完成 | Claude Code / Codex / Cursor | ✅ Bug/任务闭环 |
| **前端开发** | Developer-Frontend | 查UI Bug→修复→类型检查→提交→禅道完成 | Claude Code / Cursor | ✅ Bug/任务闭环 |
| **移动端开发** | Developer-Mobile | Flutter/小程序/iOS/Android 开发 | Codex / Cursor | ✅ 任务闭环 |
| **测试工程师** | QA-Automation | 查待测Bug→执行测试→禅道更新状态 | Claude Code + Playwright | ✅ Bug验证闭环 |
| **测试开发** | QA-Scripting | 编写自动化测试用例、测试框架搭建 | Claude Code | ✅ 关联任务 |
| **代码审查** | Code-Reviewer | 自动Review PR、代码质量检查、安全扫描 | Cursor + GitHub MCP | ✅ 关联任务 |
| **技术架构师** | Architect | 技术方案设计、架构评审、ADR编写 | Claude Code | ✅ 需求关联 |

### 研发线工作流示例

```yaml
定时触发 (工作日9:00):
  1. Developer-Backend:
     - 查禅道 active Bug → 并行修复 → type-check → git commit #id → resolved
     - 查禅道 wait 任务 → 并行开发 → type-check → git commit #id → done
  2. QA-Automation:
     - 查禅道 resolved Bug → 并行验证 → passed → closed / failed → active+备注
  3. Code-Reviewer:
     - 查未Review的PR → 并行Review → 通过/打回
```

---

## 二、运维/DevOps 线

| 角色 | Agent 名称 | 核心能力 | 接入工具 |
|------|-----------|---------|---------|
| **运维工程师** | DevOps-Automation | 服务器巡检、日志分析、故障排查、自动修复 | Shell + Claude Code |
| **发布管理** | Release-Manager | 自动化发布流水线、回滚管理、发布检查清单 | Cursor Automation |
| **监控告警** | Monitoring-SRE | 告警响应、根因分析、自动扩缩容 | Sentry MCP + Shell |
| **数据库管理** | DBA-Automation | SQL优化、慢查询分析、备份检查、数据迁移 | Postgres MCP + Claude Code |
| **安全工程师** | Security-Auditor | 安全扫描、漏洞修复、合规检查、密钥轮换 | Security MCP |

### 运维线工作流示例

```yaml
每日巡检 (定时7:00):
  1. DBA-Automation:
     - 查慢查询日志 → 分析索引 → 生成优化SQL
     - 检查备份是否成功 → 报告异常
  
事件驱动 (告警触发):
  1. Monitoring-SRE:
     - 收到告警 → 分析日志 → 定位根因
     - 自动修复 → 恢复确认 → 生成事故报告
```

---

## 三、数据线

| 角色 | Agent 名称 | 核心能力 | 接入工具 |
|------|-----------|---------|---------|
| **数据分析师** | Data-Analyst | SQL查询、Python分析、可视化报表、洞察报告 | Claude Code / Codex |
| **数据工程师** | Data-Engineer | ETL管道、数据清洗、数仓建模、数据质量检查 | Codex |
| **BI分析师** | BI-Analyst | Dashboard设计、指标看板、周报/月报自动生成 | Claude Code + ECharts |
| **算法工程师** | ML-Engineer | 模型训练、特征工程、模型评估、A/B测试 | Codex |
| **数据产品** | Data-PM | 数据需求管理、指标定义、数据资产目录 | Claude Code |

### 数据线工作流示例

```yaml
周报自动生成 (每周五17:00):
  1. Data-Analyst:
     - 连接数据库 → 查询本周核心指标
     - 生成趋势分析 → 输出可视化图表
     - 生成指标看板快照 → 保存到文档

定时数据质量报告 (每日8:00):
  1. Data-Engineer:
     - 运行数据质量检查脚本
     - 报告异常数据、缺失值、延迟
     - 自动修复可自动处理的数据问题
```

---

## 四、AI/ML 线

| 角色 | Agent 名称 | 核心能力 | 接入工具 |
|------|-----------|---------|---------|
| **Prompt工程师** | Prompt-Engineer | Prompt优化、Few-shot设计、评估集管理 | Claude Code |
| **AI应用开发** | AI-Developer | RAG管道、Agent编排、Tool设计、LLM集成 | Claude Code + Codex |
| **模型评估** | Eval-Engineer | 自动化评估、红队测试、回归检测 | Python + LLM-as-Judge |
| **AI产品经理** | AI-PM | AI功能规划、数据飞轮设计、用户体验设计 | Claude Code |

---

## 五、产品线

| 角色 | Agent 名称 | 核心能力 | 接入工具 |
|------|-----------|---------|---------|
| **产品经理** | Product-Manager | PRD撰写、需求评审、验收确认、竞品分析 | Claude Code |
| **交互设计师** | UX-Designer | 用户流程设计、交互原型、可用性测试 | Figma MCP |
| **UI设计师** | UI-Designer | 界面设计、设计系统维护、组件库管理 | Figma MCP + Pencil |
| **用户研究员** | UX-Research | 用户访谈分析、问卷设计、行为分析 | Claude Code |

### 产品线工作流示例

```yaml
需求验收 (每日10:00):
  1. Product-Manager:
     - 查禅道 reviewing Story → 验收 → active (通过) / 打回+备注
     - 查禅道 draft Story → 完善 → 提交评审

设计同步:
  1. UI-Designer:
     - 查禅道 UI 任务 → 设计 → 上传Figma → done+附链接
```

---

## 六、营销线

| 角色 | Agent 名称 | 核心能力 | 接入工具 |
|------|-----------|---------|---------|
| **内容营销** | Content-Marketer | 公众号/小红书/抖音内容生成、SEO优化 | Claude Code |
| **社媒运营** | Social-Media-Ops | 发布排期、互动回复、热点追踪 | Slack MCP |
| **广告投放** | Ad-Operator | 广告文案、投放策略、ROI分析 | Claude Code |
| **品牌策略** | Brand-Strategist | 品牌定位、品牌故事、价值观传达 | Claude Code |

---

## 七、商务线

| 角色 | Agent 名称 | 核心能力 | 接入工具 |
|------|-----------|---------|---------|
| **销售** | Sales-Agent | 话术生成、报价方案、客户跟进策略 | Claude Code |
| **客户成功** | Customer-Success | Onboarding引导、使用分析、续费提醒 | Slack MCP |
| **售前支持** | PreSales-Engineer | 技术方案、POC搭建、产品演示 | Claude Code |
| **渠道管理** | Channel-Manager | 合作伙伴管理、渠道策略、联合营销 | Claude Code |

---

## 八、职能线

| 角色 | Agent 名称 | 核心能力 | 接入工具 |
|------|-----------|---------|---------|
| **财务** | Finance-Agent | 收支分析、发票管理、税务提醒、预算跟踪 | Claude Code |
| **法务** | Legal-Agent | 合同审查、隐私合规、知识产权 | Claude Code |
| **HR** | HR-Agent | 简历筛选、面试问题、入职流程、OKR管理 | Claude Code |
| **行政** | Admin-Agent | 制度文档、流程SOP、公告通知 | Claude Code |

---

## 九、管理线

| 角色 | Agent 名称 | 核心能力 | 接入工具 |
|------|-----------|---------|---------|
| **项目经理** | Project-Manager | 进度跟踪、风险预警、资源调配、周报生成 | Claude Code + 禅道 |
| **技术总监** | Tech-Lead | 技术决策、方案评审、团队任务分配 | Claude Code |
| **CEO助手** | Executive-Assistant | 决策支持、竞品洞察、战略分析、汇报材料 | Claude Code |

### 管理线工作流示例

```yaml
每日晨会 (定时8:30):
  1. Project-Manager:
     - 查禅道: 昨天完成的任务 / 今天到期任务 / 延期风险
     - 查Git: 昨天的代码提交统计
     - 生成晨会简报 → 发送Slack/飞书

周报自动生成 (每周五16:00):
  1. Executive-Assistant:
     - 收集本周所有Agent的执行报告
     - 汇总关键指标和里程碑
     - 生成管理层周报
```

---

## 十、技术架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                     Agent Hub 平台                            │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  入口层                                                │   │
│  │  Web页面 / Slack / 飞书 / QQ / iOS Shortcuts / API    │   │
│  └──────────────────────┬───────────────────────────────┘   │
│                         ▼                                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  调度层 (Orchestrator)                                 │   │
│  │  - 意图识别 → 任务拆解 → Agent分派 → 进度追踪          │   │
│  │  - 支持: 定时触发 / 事件驱动 / 手动触发 / Webhook      │   │
│  └──────────────────────┬───────────────────────────────┘   │
│                         ▼                                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Agent 执行层 (并行多进程)                              │   │
│  │                                                         │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │   │
│  │  │ Developer│ │ QA      │ │ DevOps   │ │ Data     │ │   │
│  │  │ Claude   │ │ Playwright│ │ Shell    │ │ Python   │ │   │
│  │  │ Codex    │ │ Claude   │ │ K8s MCP  │ │ SQL MCP  │ │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ │   │
│  │  │ PM      │ │ Designer │ │ Marketer │ │ Finance  │ │   │
│  │  │ Claude   │ │ Figma MCP│ │ Claude   │ │ Claude   │ │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘ │   │
│  └──────────────────────┬───────────────────────────────┘   │
│                         ▼                                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  工具/MCP 层                                           │   │
│  │  zentao │ git │ postgres │ slack │ sentry │ figma    │   │
│  │  shell │ docker │ k8s │ jira │ linear │ ...         │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  规则/治理层                                            │   │
│  │  - Role-based Rules (每个角色有强制执行纪律)             │   │
│  │  - Quality Gates (质量门禁: type-check / lint / test)   │   │
│  │  - Security Policies (安全策略: 禁止密钥、禁止force)     │   │
│  │  - Audit Logging (审计日志: 谁、什么时间、做了什么)       │   │
│  │  - Budget Control (预算控制: 每Agent/每任务/每日上限)    │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 十一、与市面上方案对比

| 维度 | 禅道官方ZAI | Cursor内置Agent | GitHub Copilot | **Agent Hub(你的方案)** |
|------|------------|----------------|----------------|----------------------|
| 覆盖角色 | 仅研发 | 仅开发 | 仅开发 | **全公司16+角色** |
| 禅道集成 | ✅ 查询+操作 | ❌ | ❌ | **✅ 端到端闭环** |
| 定时自动 | ✅ 计划中 | ✅ Automation | ❌ | **✅ 配置化定时** |
| 多进程并行 | ❌ | ✅ /multitask | ❌ | **✅ 原生支持** |
| 执行纪律 | ❌ | ✅ Rules | ❌ | **✅ 角色级Rules** |
| 配置页面 | ❌ | ❌ | ❌ | **✅ Web自助配置** |
| 跨角色协同 | ❌ | ❌ | ❌ | **✅ 13条线协同** |
| 自托管 | ❌ 需禅道企业版 | ❌ SaaS | ❌ | **✅ 内网私有部署** |

---

## 十二、一句话总结

> **Agent Hub = 全公司所有人的 AI 替身。每个人选自己的角色，配置好自己的项目路径和禅道账号，Agent 每天自动帮你把活干了。**
