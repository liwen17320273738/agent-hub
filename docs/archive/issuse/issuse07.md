还差的 3 件（按重要性）
⚠️ ④ Self-healing 还是浅层
现在 REJECT 之后只触发学习回路（蒸馏成下一版 prompt 给未来任务用），当前 task 重跑还是同一份 prompt。
缺：root-cause→改本次 prompt→retry 的元循环。比如 acceptance REJECT_TO development 时应该把"被拒理由"作为额外 system patch 注入下一次 development 调用，目前没做。
影响：单 task 内"越跑越笨"，靠重试穷举。
⚠️ ⑥ 外部集成停在 demo 级
只有 notify/slack.py + 微信平台部署。
缺：Jira issue 双向同步（创建 PRD → Jira story；REJECT → Jira comment）、GitHub Issue/PR 反向闭环（PR comment → 触发 review stage）、Figma 设计稿读写。
影响：人在公司里习惯用的协作面，AI 军团是"瞎子"。
⚠️ ⑦ Agent-product / Agent-marketing / Agent-finance 冗余未拆
seed.py:250+ Agent-product 还是和 pipeline_role: product-manager 100% 重叠；Agent-marketing/finance 仍只在 2 个模板（growth_product/fintech）激活。
缺：要么并入主角色（删 3 个画像），要么差异化（如 Agent-product 改成"中文电商场景特调"独有 quick-prompt + capabilities）。
影响：不致命，但 UI agent 列表里有"重复 NPC"。
这一波建出来的潜在风险（CR-blocker 级）
读 git status + 跑测的过程发现几个还没暴露但会咬人的点：

没有自动化回归 — 这 4 轮 phase 全靠手工 python3 -c "..." 跑 assert。learning_loop / task_scheduler / sandbox_overrides / mcp_classify 没进 pytest，下一次 refactor 容易回退。
Alembic 链被反复改过 — git status 里 7 个旧 migration 文件被 modified（不是 untracked）。Alembic 哲学上 migration 不可变；现在线上 DB head 是 8c9d0e1f2a3b，如果别人 pull 下来跑 alembic upgrade head，他的 4e7f8a/5f8a9b 这种已 applied 的会因为内容变了而潜在有歧义。需要 squash 或者明确"已上线那批不要再动"。
前端只过了 ReadLints，没过 vue-tsc/build — package.json 没装 vue-tsc，新加的 cellEditor 弹窗、overrides 类型扩展没真正 type-check 过。上线前建议跑一次 npm run build 看 vite 能不能编。
没跑端到端"杀进程→重启→续跑" — TaskScheduler 持久化的 smoke 只验了 register_kind 注册可见，没真的 submit → kill -9 → restart → 看 redis 队列被消费。
scheduler:queue Redis key 没设 TTL/上限 — 长跑后异常崩溃可能会留下不可消费的 stale entry（kind 已删/参数 schema 已变），目前没 garbage-collect 策略。
SandboxRule 内存缓存只在启动时 preload + 写时更新本进程——多 worker（gunicorn -w N）部署时其他 worker 不会感知到 admin 在 UI 上做的改动，需要加 Redis pub/sub 或换成"每次查 DB + 短 TTL 缓存"。这是单进程 dev 模式下藏着的伪命题。
学习回路 targeting 没 UI — 后端 set_override_targeting API 已加，前端还没做"勾选这条 shadow 只对 template=qa 生效"的开关，操作员现在只能 curl。
我的判断
按军事比喻刷新一下：

项	状态
编制（角色/装备）
✅ 完整
作战流程（SOP）
✅ 完整
后勤（成本/安全）
✅ 完整
战场态势感知
✅ 完整（看板 5 tab）
兵种协同（真并行）
✅ 完整（stage + task 双层）
实战经验积累（学习回路）
✅ 已建 + ⚠️ 单 task 内自愈未闭环
跨建制协同（外部 IM/Issue 系统）
❌ 仍 demo
质量回归（CI/E2E）
❌ 全手工
多进程/多机部署就绪
❌ 单进程假设
短答："AI 军团"主链路 ✅ 能打仗了，但还不能交给副官独立带兵——三大短板：单 task 自愈、外部系统对接、生产部署稳态。

要继续推的话，我建议下一轮按这个顺序：

(P0) 把 4 轮 phase 的 smoke 升成 pytest — 防止 regression，单条 0.5 天
(P0) SandboxRule 跨进程一致性 — 加 Redis pub/sub 失效广播，半天
(P1) 单 task 自愈 — REJECT_TO 时把 reviewer 的拒绝理由注入到目标 stage 的下一次 prompt
(P2) Jira / GitHub Issue 双向连接器 — 一个独立 connector 包
要我接哪一条？