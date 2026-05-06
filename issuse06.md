两件下游事都做完了。

✅ #1 Alembic 迁移：5f8a9b0c1d2e_backfill_design_and_specialist_stages
文件：backend/alembic/versions/5f8a9b0c1d2e_backfill_design_and_specialist_stages.py

策略：

内嵌 15 个模板的 stage 快照（不依赖 app code，迁移历史不可变）
对 status NOT IN (done, cancelled) 且有 template 的老 task：
缺失的 stage → INSERT 为 pending
重新编号 sort_order，让 design 排到 planning 与 architecture 之间，security-review/legal-review 排到 testing 与 reviewing 之间，等等
reviewing 行的 owner_role 若仍是 orchestrator 且未运行 → 改成 acceptance
不动 done/active 行的 status/output/timestamp
Postgres + SQLite 双方言
幂等，可重跑
downgrade() 只删新增的 pending 行
执行结果：

INFO  [alembic.runtime.migration] Running upgrade 4e7f8a9b0c1d -> 5f8a9b0c1d2e
[5f8a9b0c1d2e] backfill done: 0 tasks synced, 0 stages inserted, ...
当前库里 13 个 task：1 个 simple/done 跳过、12 个 template=NULL（legacy 自定义流程，按设计也跳过）。新 task 一律走新 12 阶段链路，老 task 不被破坏。

alembic current 确认 head = 5f8a9b0c1d2e ✅

✅ #2 前端模板卡片：无需改代码
src/views/PipelineDashboard.vue:225-243 是完全数据驱动的：


PipelineDashboard.vue
Lines 225-243
          <div class="template-grid">
            <div
              v-for="(tmpl, key) in sdlcTemplates"
              :key="key"
              class="template-card"
              :class="{ active: newTask.template === key }"
              @click="selectTemplate(String(key))"
            >
              <span class="template-icon">{{ tmpl.icon }}</span>
              <div class="template-info">
                <span class="template-label">{{ tmpl.label }}</span>
                <span class="template-desc">{{ tmpl.description }}</span>
              </div>
icon / label / description 全部从 /api/pipeline/sdlc-templates 拉，没有硬编码 mapping。

实测 live API 返回：

🏛️ enterprise:     企业级 / 严格合规 (9 stages)
📈 growth_product: 增长型产品 (9 stages)
💳 fintech:        金融 / 支付 (10 stages)
这 3 张卡片刷新页面就会自动出现，stage 预览（selectedTemplateStages）也会一并显示新阶段（design / security-review / legal-review / data-modeling / marketing-launch / finance-review）和它们的 quality gate 阈值。

结论
新 task 默认 12 阶段、15 模板 100% 可用；老 task 安全无副作用。如果哪天想给某个老 in-flight task 强制升级到新链路，调一次 POST /pipeline/tasks/{id}/stages 就行（迁移已经把 schema 准备好了）。

AI-agent 军团完成了？

短答：0→1 主链路已经"能跑通"，但说"军团完成"还差一截。下面是我自己的诚实盘点。

✅ 已完成（这一轮 + 之前累计）
维度	现状
Agent 角色
13 个画像（CEO / Product / Designer / Architect / Developer / QA / Acceptance / DevOps / Security / Legal / Data / Marketing / Finance）
SDLC 阶段
12 个（planning → design → architecture → data-modeling → development → testing → security-review → legal-review → reviewing → deployment → marketing-launch）
DAG 模板
15 个（含新加的 enterprise / growth_product / fintech）
评审机制
每阶段 peer review + 部分 human gate
验收闭环
acceptance-agent 在部署后真访问 URL + 截图 + 跑 test_execute
成本治理
per-task 预算 + 60% 软限降级 + 100% 硬阻断 + REST API
安全护栏
Prompt Injection sanitizer 接 web_search / browser_*（中英 16 条规则）
质量门禁
12 个阶段都有 deliverable requirements + pass/fail 阈值
数据迁移
老 task / 新 task 都不冲突
主流程 demo 一句话：用户提需求 → 自动跑完 12 阶段 → 部署 → 验收 → 通知，端到端不需要人手介入。

⚠️ 还没真正闭环的 7 件事（按重要性排）
无学习回路 — Agent 不会从历史 task 的失败/通过里自我改进。没有 prompt DPO、没有 fine-tune、没有 evaluator-driven 提示迭代。每次都是"出厂设置"。
真并行度低 — DAG 编排理论上支持并行（design ∥ data-modeling），但运行时 Worker 池/调度 还是单 task 串行执行多 stage。需要做 stage-level 并发执行器。
观测看板缺失 — cost_governor 和 trace 已经在写数据了，但前端没有"成本曲线 / token 趋势 / 阶段耗时热力图"。后端就绪，UI 没接。
Self-healing 弱 — stage 失败后只会按 max_retries 重跑，没有"根因分析→改 prompt→再跑"的元循环。Acceptance REJECT 时虽然支持 REJECT_TO: <stage_id> 回退，但回退后还是用同一份 prompt。
Skill 沙箱不严 — tools/registry.py 里所有工具对所有 agent 开放，没有 per-role 白名单强约束（只有软声明）。security-agent 理论上能调 deploy 工具。
外部集成停在 demo 级 — Slack 通知有，Jira / Figma / GitHub Issue 双向同步没有。openclaw 是 IM 网关但没接进 pipeline 事件流。
Agent- 三个 agent 仍冗余* — Agent-product 和 CEO 角色重叠、Agent-marketing/Agent-finance 只在 2 个模板里激活。要么并入主角色，要么给它们差异化的能力（比如 Agent-product = 中文电商场景特调）。
我的判断
"0→1 自动开发"算 MVP 完成，可以拉真用户跑了。
"AI-agent 军团"还差一个 Wave-5：自我学习 + 真并行 + 可观测看板。

如果按军事比喻：

编制（角色 / 装备）✅ 完整
作战流程（SOP）✅ 完整
后勤（成本 / 安全）✅ 完整
实战经验积累（训练回路）❌ 缺
战场态势感知（dashboard）❌ 缺
兵种协同（真并行）⚠️ 半成品
要继续推到"军团"水平，建议下一阶段优先做 #3 观测看板 + #1 学习回路——这俩做完，系统就从"能跑"升级到"越跑越聪明"。

要我直接接着做哪一个？

