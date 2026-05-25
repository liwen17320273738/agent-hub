# Agent Hub 深度诊断：为什么 AI 军团一直没达预期

> 时间：2026-05-22  视角：工作流 + 产品体验  依据：源码 + CLAUDE.md 实证对照

---

## 一句话结论

**Agent Hub 的代码不是骗子，骨架是真的；但它把"交付平台"当"管线引擎"在做——管线每一层都通了，可 Hero Path 的"用户感知"和"失败兜底"两条命脉都没接上，所以演示能跑、生产不敢用。**

主要病根有三：
1. **Hero Path 在 Phase 6 QA 这一关是硬断点**：失败就打回 development，没有"降级交付"。
2. **质量闸门容易走过场**：LLM 评分一旦不可用就退化成宽松的启发式，几乎永远 PASS。
3. **核心 E2E 测试用 stub 推进状态机**，从来没真正端到端跑过"一句话 → 分享链接"。

下面分五块拆。

---

## 一、Hero Path 哪里最容易塌

CLAUDE.md 里 Hero Path 写得很漂亮："一句话需求 → 收件箱(90s 方案) → 团队执行 → 验收闸门 → 部署上线 → 分享链接"。代码里这条链路实际是这样的：

`Dashboard.vue` 提交一句话 → `pipeline.py` 建 `PipelineTask` → `dag_orchestrator.py` 并行调度 14 个 stage → `pipeline_engine.py` 跑 8+ 层管线 → `artifact_writer.py` 写 `TaskArtifact` → `SharePage.vue` 拉 artifact 渲染。

**真正会塌的几个点**：

- **Phase 4.2b 自动修复有上限**（`codegen_agent.py:MAX_FIX_RETRIES=2`）。两次构建仍失败时，代码选择 `emit stage:degraded` 然后**继续走**——这就把一颗哑弹传给 Phase 6。
- **Phase 6 QA 是真跑 `pnpm install/build/test`**（这点是亮点），可一旦 `qa_result.ok=False`，`pipeline_engine.py` 直接 `return {ok:False, revert_to:"development"}`。**只有打回、没有降级**：没有"先交付 PRD + 设计稿、代码挂红"这种 partial delivery 路径。
- **Phase 7 部署只有"Vercel 优先 + 本地 preview 兜底"**，没有第三层。Vercel token 缺失 + 本地无 node/pnpm 时，`deploy_manifest` 写空，前端的 `DeployPreviewCard` 没 placeholder——用户看到一张空卡片。
- **SharePage 没有 graceful degradation**。`PipelineTaskDetail.vue` 取不到 artifact 时既不显示"为什么没有"，也不给"看上一版"的入口。用户最在意的"链接"，恰恰是这条链路最末端、最容易空的那一格。

**结论**：Hero Path 不是"一直有问题"，而是被设计成**全或无**——任何一个 stage 翻车，用户就什么都看不到，而 stage 翻车的概率（LLM 漂移 + pnpm 环境 + Vercel 配额）单次累乘下来一定不小。

---

## 二、14 角色军团是真协作还是换皮

好消息：**真不是换皮**。`pipeline_engine.py` 的 `STAGE_ROLE_PROMPTS` 给 planning/design/architecture/development/testing/acceptance/deployment 各写了 30 行专业化 system prompt；`dag_orchestrator.py` 用 `asyncio.gather` 真并行，依赖图靠 `depends_on` + `get_ready_stages()` 做拓扑排序，每个 stage 独立 `AsyncSession`。

坏消息有三层：

1. **军团其实只有 7 个常驻**。data/marketing/finance/legal/security 这 5 个角色只在 enterprise / growth_product / fintech 模板里被装配进 DAG。日常的 web_app 模板，"14 角色"实际是 7-8 个。市场宣传和代码不一致。
2. **依赖传递是字典而非契约**。`previous_outputs` 直接塞 dict 透给下游 prompt，没有 schema 校验。design 输出 1500 字、architecture 输出 800 字、development 看到的就是"前面这一坨"——下游 agent 实际上**只在做长文本拼接**，不是结构化交接。这就解释了为什么生成的代码经常跟前面的 PRD 对不上号。
3. **真并行也要让最慢的等**。`DAG_PARALLEL_LIMIT=4`，意味着任何一个 stage 卡住，剩下的就排队；又因为没有 stage 级超时，**任何 LLM 网络抖动都会拖垮整批 wall time**。CLAUDE.md 里宣传的"90 秒方案"几乎不可能稳定达到。

**结论**：协作的骨架是对的，**契约层和模板层在偷工**——这是 agent 输出对不齐、产品看起来"碎"的根因。

---

## 三、质量闸门是真闸还是花瓶

`self_verify.py` + `quality_gates.py` + `guardrails.py` 三层听起来很硬，实际硬度：

- **Self-Verify**：纯启发式（章节名、最小长度、代码块数）。development stage 要求 `min_length=1500` + `min_code_blocks=3`，门槛极低。失败时调用 `_top_up_stage_output()` 二次修复——而修复策略基本是"再让 LLM 写长一点"，几乎一定能过。
- **Quality Gate**：本来设计成"启发式 + LLM 评分"双轨。问题在 `dag_orchestrator.py` 那行 `skip_llm=True` 的退化路径——**只要 LLM provider 调用失败，闸门就只剩启发式**，那个 0.7 的 pass_threshold 在宽松 heuristic 下基本是 100% 通过。
- **Guardrails**：除 deploy 等不可逆操作要求审批外，其他 stage 全是 `AUTO_APPROVE / WARN`，且 WARN 也 `proceed=True`。**警告不阻塞**。

`dag_orchestrator.py:929` 那段 `if not gate_result.can_proceed: stage.status = BLOCKED` 是真能阻塞的，但**前提是评分真的低于阈值**——而上面三条退化路径加在一起，让"评分低于阈值"成了小概率事件。

**结论**：闸门有，钥匙交在了启发式手里，**LLM 失联时它会自动变成橡皮图章**。这是用户看到"流程都过了、东西却烂"的直接来源。

---

## 四、产品体验和用户感知的断层

工作流的"达不到预期"，一半是工程问题，一半是产品问题。从用户视角看：

- **Dashboard 的"一句话"按下去之后没有进度叙事**。Inbox 列出来的是状态（active / done / failed），没有"AI 正在做 PRD"、"架构师正在画图"这种过程感。用户花 5 分钟等 90 秒方案，盯着一个 spinner——这是体感最伤的地方。
- **Failure RCA Card 设计很好，但触发面太窄**。它只在 stage 抛硬错时出现；启发式过了、内容糟糕的"软失败"完全捕捉不到。所以用户经常拿到一份"看上去都成功了"的烂活儿，没人告诉他哪里不对。
- **8-Tab 详情页是工程师视角**：PRD、UI、code、QA、deploy……每个 tab 都需要点开才看到内容。商业用户要的是"我能不能上线、链接在哪、能不能用"，**Hero Path 的最后一公里应该是一个高亮的 Preview URL + 一句话验收摘要**，而不是 8 个并列 tab。
- **SharePage 没有验收叙事**。CLAUDE.md 说"4-field 失败卡 + accept/reject"，但 happy path 上没有对应的"4-field 成功卡"——一个普通客户打开分享链接，看到的是一堆 markdown 文档，没有"这交付了什么、试用入口在哪、谁负责后续"这种 SaaS 标配信息。
- **i18n 只覆盖了 5 个侧边栏入口 + Dashboard + Inbox**。8-Tab 详情、SharePage、错误提示、QA 报告里大量中文硬编码——出海/演示给英文客户都尴尬。

---

## 五、离上线还差什么——优先级清单

下面按"先解锁演示 → 再敢小范围生产 → 再谈规模化"的顺序排：

**P0（不做这些，每次演示都在赌运气）**

1. **Hero Path 加 partial delivery**。Phase 6 失败时不要 revert，先把已经产出的 PRD/UI/architecture 落到 share token，前端给"代码暂缓，文档先看"。
2. **质量闸门的 LLM 路径做硬依赖**：评分 LLM 不可用就 BLOCK，不要静默退化成启发式。这是诚实度问题。
3. **stage 级超时 + 进度事件流**。SSE 已经有 channel，把"agent 在写什么"以人话推到 Dashboard，把 90s 变成可观测的 90s。
4. **核心 E2E 测试用真 LLM 跑一次**。`test_hero_delivery_path.py` 用 stub 等于没测——加一个 `test_hero_real_llm.py`，每天 nightly 跑一次"一句话 → 分享链接"全链路，allow flake 但必须有趋势。

**P1（小范围生产前必须）**

5. **agent 之间换成结构化契约**。`previous_outputs` 改成 Pydantic schema：design 必须吐出 `{screens:[], tokens:{}, ...}`，architecture 必须吐出 `{apis:[], entities:[], files:[]}`。不再让下游 agent 啃长文本。
6. **14 角色补齐 or 改口径**。要么把 data/marketing/finance/legal/security 在常用模板里也接上，要么对外口径改成"7+5 按需扩展"。代码和市场话术对齐。
7. **Deploy 第三层兜底**：Vercel 失败 → Cloudflare Pages / Netlify / 自建静态托管。至少要保证"有一个能点的链接"是 P0 SLA。
8. **失败软识别**。在 Quality Gate 加"输出与上游一致性"检查（embedding 相似度 / LLM judge "PRD 和代码是否对得上"），把软失败转成显式 FailureCard。
9. **DAG_PARALLEL_LIMIT 自适应**。根据 stage 类型 + 历史 wall time 动态调度，避免一个慢 stage 拖死整批。

**P2（规模化和商业化）**

10. **SharePage 重做成验收页**：顶部 Preview URL + 验收摘要 + 一键试用，下面才是 8 个文档 tab。
11. **Cost Governor 暴露给用户**：当前 60% 软降级是黑盒，应该让用户在 Dashboard 看到"本次预算消耗 / 当前模型 / 是否降级"。
12. **i18n 全覆盖 + 错误码本地化**。
13. **Memory 的"learned patterns"接到 Planner**。现在三层记忆写得很认真，但 Planner 几乎没用 patterns 做模板选择——这是 Agent Hub 区别于"一次性脚本工具"的关键资产，必须用起来。
14. **可观测性的客户化**。Traces / spans 现在只有 admin 视图，企业客户买这个平台一定会要"我自己的任务的审计日志"。

---

## 六、把话说白

Agent Hub 现在的状态像一辆**发动机调校到 8000 转、但变速箱还是手动挡、安全气囊没装**的赛车。

- 发动机（pipeline_engine + dag_orchestrator + codegen + qa_executor）真的能跑，而且跑得不慢。
- 变速箱（agent 之间的契约、partial delivery、降级路径）还在用长字符串拼接换挡，颠簸全靠运气。
- 安全气囊（质量闸门的真硬度、失败兜底、用户感知）几乎没装——平时不出事，出事就直接撞穿挡风玻璃。

**最该立刻动手的两件事**：把 Phase 6 改成 partial delivery（解锁演示），把 Quality Gate 的 LLM 退化路径堵死（解锁信任）。这两件做完，再谈"上线使用"才有意义。
