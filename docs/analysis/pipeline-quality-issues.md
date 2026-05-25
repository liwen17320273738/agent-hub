# Pipeline 质量深度分析报告

> 生成日期：2026-05-20 · 修复完成日期：2026-05-21
> 分析范围：Phase 5（视觉证据）→ Phase 6（QA 真实执行）→ Phase 7（部署闭合）→ 测试覆盖
> 状态图例：✅ 已修复 | ⚠️ 部分修复 | ❌ 仍存在

---

## 一、致命级 — 虚假的"通过"

### 1. `generate_mockup` 永远返回 `ok: True` ✅ 已修复

**文件：** `backend/app/services/ui_visualizer.py:333`

```python
return {
    "ok": True,  # 无任何条件分支，永远 True
    "imagePath": image_path or "",  # 没有 OpenAI/Gemini Key 时为空字符串
    "htmlPath": html_path,          # _generate_html 纯 Python 拼接，永远成功
    ...
}
```

- **问题：** 无论 image 生成是否成功，无论 HTML 保底是否只是一个通用骨架，永远返回 ok
- **影响：** 上层 `pipeline_engine.py` 无法区分"真设计稿"和"占位符模板"
- **证据：** `imageExists` 字段虽然标记了 `bool(image_path)`，但 pipeline 中不使用它来判定失败（line 1830 只检查 `result.get("ok")`）

### 2. HTML 保底是硬编码通用模板，不是"设计稿" ✅ 已修复（degraded 标记+管道警告）

**文件：** `backend/app/services/ui_visualizer.py:487-584`

生成的 HTML 结构完全固定：

```
toolbar(3个圆点) → navbar(Dashboard/Projects/Analytics/Settings)
  → sidebar(5项固定菜单) → main(4张固定 stats 卡 + 3张固定 project 卡)
```

- **问题：** 不管用户需求是"医疗管理系统"、"电商平台" 还是"待办看板"，HTML 结构完全相同。唯一变化的是 `project_name`（截取前4字符）和 `primary_color`
- **影响：** 用户看到的所谓"设计稿"是一个通用 dashboard 骨架，与实际需求毫无关系
- **根源：** `_generate_html` 不从 `design_spec` 生成内容结构，只用 `_parse_spec` 提取了 theme 和 color

### 3. Resource Check 永远不会真正阻塞 ✅ 已修复

**文件：** `backend/app/services/ui_visualizer.py:104-108`

```python
overall_ok = (
    channels.get("openai_images", {}).get("available")     # 无 Key → False
    or channels.get("gemini_nano_banana", {}).get("available")  # 无 Key → False
    or channels.get("html_prototype", {}).get("available")     # 纯 Python → 永远 True
)
```

- **问题：** `_generate_html` 是纯 Python 字符串拼接（无 IO、无网络、无外部依赖），导致第三个 OR 条件永远为 True
- **影响：** pipeline_engine 中 Layer 2.5 的阻塞条件（line 1262: `if not rc.get("ok") and not rc.get("fallbacks")`）永远不会触发
- **后果：** 即使没有任何图片生成能力（无 OpenAI Key、无 Gemini Key、无 Figma Token），pipeline 也显示"资源就绪"

### 4. 架构图 HTML 依赖外部 CDN，无离线保护 ⚠️ 部分修复（本地 CLI 预渲染优先）

**文件：** `backend/app/services/ui_visualizer.py:874`

```html
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
```

- **问题：** 架构图 HTML 通过 CDN 加载 Mermaid.js。如果运行环境无外网（Docker sandbox `--network none`），或 CDN 不可达，架构图 HTML 将是空白页面
- **矛盾：** `check_diagram_resources` 会探测本地 `mermaid` CLI（line 125），但 HTML 渲染走 CDN 路径，与本地 CLI 无关
- **影响：** `check_diagram_resources` 返回 ok，但生成的 HTML 实际上可能无法渲染

---

## 二、严重级 — 逻辑漏洞

### 5. QA executor 日志文件内容是 JSON 摘要，不是真实命令输出

**文件：** `backend/app/services/qa_executor.py:242,254,266`

```python
# install.log 写入的是 QaCommandResult 的 JSON 序列化
self._log_to_file("install.log", json.dumps(asdict(install_result), ensure_ascii=False, indent=2))
# build.log 同理
self._log_to_file("build.log", json.dumps(asdict(build_result), ensure_ascii=False, indent=2))
# test.log 同理
self._log_to_file("test.log", json.dumps(asdict(test_result), ensure_ascii=False, indent=2))
```

- **问题：** `_log_to_file` 写入的是 executor 自己的结构化摘要（含 exit_code、duration、stdout 前 5000 字符的截断），不是真实 stdout/stderr
- **影响：** `write_qa_artifacts` 在 `project_dir` 中读取 `build.log`、`test.log` 作为 artifact 内容时，得到的是 JSON 摘要而非真实构建日志
- **矛盾：** `run_command` 已经通过 `asyncio.subprocess.PIPE` 捕获了真实 stdout/stderr（line 208-209），但没有写入文件

### 6. `build.log` 被两个阶段覆盖写入

- **Phase 4（CodeGenAgent）:** 写入真实构建日志 → `project_dir/build.log`
- **Phase 6（QaExecutor）:** `_log_to_file("build.log", ...)` 以 append 模式追加 JSON 摘要

- **问题：** Phase 6 的 append 会在真实构建日志后追加 JSON，导致 `build_log` artifact 包含混合内容
- **影响：** 前端 TaskCodeTab 展示的构建日志末尾会出现 JSON 片段

### 7. 图片文件名使用时间戳，无法去重和复用

**文件：** `backend/app/services/ui_visualizer.py:361`

```python
filename = f"{datetime.utcnow().strftime('%Y-%m-%d-%H-%M-%S')}-ui-mockup.png"
```

- **问题：** 每次调用生成新文件名。如果同一 task 重跑 design 阶段，旧 PNG 文件仍然存在但不会被复用
- **影响：** 重跑产生重复文件，磁盘空间浪费；且无法判断"已经有了为什么还要重新生成"

### 8. Vercel 部署失败静默 fallback

**文件：** `backend/app/services/pipeline_engine.py:2084-2085`

```python
except Exception as ve:
    logger.warning("[pipeline] Vercel deploy exception, falling back to local: %s", ve)
```

- **问题：** Vercel 任何异常都被静默吞掉并 fallback 到 local preview
- **影响：** 如果 VERCEL_TOKEN 已配置但部署因配额超限/项目名冲突/API 变更等原因失败，用户永远不会知道真正原因，只看到一个 local preview URL

### 9. Browser smoke 失败不阻塞 QA 整体 ok

**文件：** `backend/app/services/qa_executor.py:398-402`

```python
# run_all_commands 已经设置了 results["ok"] = True
browser_result = await self.run_browser_smoke()
cmd_results["browser"] = asdict(browser_result)
# browser_result.ok 或 browser_result.page_opened 没有被检查！
return cmd_results  # 即使浏览器白屏也返回 ok: True
```

- **问题：** 如果 `pnpm build` 和 `pnpm test` 通过，但 browser smoke 失败（页面打不开/白屏/console 全是 error），整体仍返回 ok
- **影响：** testing 阶段报告通过，但实际上页面是坏的

### 10. `_log_to_file` 写入格式与 `write_qa_artifacts` 期望不匹配

**写入格式（qa_executor）:** 每行一条 JSON 摘要（append 模式）
**读取格式（artifact_writer）:** 期望纯文本日志

```python
# artifact_writer.py:345-352
if os.path.isfile(build_log_path):
    with open(build_log_path, "r", encoding="utf-8") as f:
        raw_log = f.read()
    # raw_log 现在是 JSON 摘要，不是构建日志
```

---

## 三、中等级 — 测试覆盖盲区

### 11. 100% 的 Phase 5/Phase 6 测试都是 mock 测试

| 测试文件 | Mock 方式 | 缺失的验证 |
|---------|---------|----------|
| `test_phase5_visual_evidence.py` | `AsyncMock` mock 掉 `generate_mockup` 和 `generate_architecture_diagram` | 无 1 个测试跑真实 `_generate_image` |
| `test_phase5_visual_evidence.py` | `patch.dict(os.environ, {}, clear=True)` 清除所有 Key | 没有验证 HTML 占位符是否真的符合设计意图 |
| `test_phase6_qa_execution.py` | `echo hello` / `exit 42` 代替真实 `pnpm build` | 无 1 个测试跑真实前端项目构建 |
| `test_phase6_qa_execution.py` | `AsyncMock()` 代替数据库 | 没有端到端 artifact 写入 + 读取验证 |
| `test_hero_delivery_path.py` | `/advance` API 用 stub 字符串推进 | advance 的 output 是 `"## Stub\ncompleted stage..."` |

**结论：真实路径没有 1 个集成测试覆盖。** 测试覆盖率高是因为 mock 测试计入统计。

### 12. "资源检查全不可用"测试的断言是 `ok is True`

**文件：** `backend/tests/test_phase5_visual_evidence.py:46-54`

```python
async def test_check_design_resources_all_unavailable(self, viz):
    """check_design_resources returns ok when HTML always works."""
    with patch.dict(os.environ, {}, clear=True):
        with patch("os.path.exists", return_value=False):
            ...
            result = await viz.check_design_resources()
    assert result["ok"] is True  # 名字叫 all_unavailable，断言是 ok=True
```

- **问题：** 测试名暗示"所有渠道不可用"，但断言验证 HTML fallback 让结果仍然是 ok
- **信号：** 这证明了"HTML 保底让一切看起来正常"是故意设计的，而不是 bug

### 13. 缺乏无 API Key 环境的端到端测试

当前所有测试要么有 mock，要么在 CI 环境配置了真实 API Key。没有测试覆盖以下场景：

- 服务器启动后，没有配置 `OPENAI_API_KEY`，跑完整 pipeline
- 服务器启动后，没有配置 `GEMINI_API_KEY`，跑完整 pipeline
- 服务器启动后，只配置了 `VERCEL_TOKEN`，验证 deploy 走 Vercel 路径

---

## 四、低等级 — 代码质量问题

### 14. `artifact_contract_rules_strict` 默认 False

**文件：** `backend/app/config.py:118`

```python
artifact_contract_rules_strict: bool = False
```

- **问题：** 合约中定义的 schema 规则（min_chars、markdown_sections、h2_keyword_groups）默认不强制执行
- **影响：** 一个只有 10 字符、无任何 markdown 标题的 PRD 也能通过合约验证

### 15. 大量硬编码 fallback 掩盖真实失败

| 方法 | 无匹配时的行为 | 文件:行 |
|-----|-------------|--------|
| `_parse_spec` | `components = ["header", "hero", "footer"]` | ui_visualizer.py:458-459 |
| `_parse_architecture_spec` | `components = [Frontend, Backend API, Database]` | ui_visualizer.py:670-676 |
| `generate_data_model` | `tables = [{name: "items", ...}]` | ui_visualizer.py:1106-1115 |
| `generate_screen_plan` | `screens = [{title: "Main", ...}]` | ui_visualizer.py:229-234 |
| `generate_file_plan` | `directories = [{name: "src", ...}]` | ui_visualizer.py:1149-1150 |
| `generate_api_contract` | `entities = ["item"]` | ui_visualizer.py:1035-1036 |

- **问题：** 所有这些兜底让 pipeline **永远不会因为"无法理解需求"而失败**
- **影响：** 当 LLM 输出质量差或格式异常时，用户拿到的是一堆默认占位符，但 pipeline 报告"成功"

### 16. 异常处理静默降级模式

**文件：** `backend/app/services/pipeline_engine.py`

多处关键路径使用 `except ImportError: logger.warning(...)` 和 `except Exception: logger.warning(...)`：

- Phase 6 QA executor ImportError → 跳过 QA 但继续（line 2023-2024）
- Phase 5 Visual generation Exception → 返回 error 但 log level 是 warning（line 1961-1962）
- Artifact writer Exception → `logger.warning` 但继续（line 2197）

### 17. Architecture Diagram 的 Mermaid 生成也是模板化

**文件：** `backend/app/services/ui_visualizer.py:704-841`

`_generate_mermaid_diagrams` 使用预定义的组件关键字和固定的流关系：

```python
flow_patterns = [
    ("Frontend", "Backend API", "HTTP/API requests"),
    ("Backend API", "Database", "CRUD queries"),
    ...
]
```

- **问题：** 只要 spec 中包含 "frontend"、"backend"、"database" 关键字，就会生成相同的 Mermaid 图
- **影响：** 和 HTML mockup 同样的问题——不同项目的架构图看起来几乎一样

### 18. 合约验证的 `check_architecture_consistency` 检查过于宽松

**文件：** `backend/app/services/ui_visualizer.py:248-300`

- 只检查 API entity 是否在 data model 中出现（简单字符串匹配）
- 不检查 API endpoint 的 HTTP method 合理性
- 不检查 data model 的字段类型是否合理
- 不检查 file_plan 的目录结构是否与路由匹配

实际效果：只要 api_contract 和 data_model "谈论了同一个实体名"，一致性就通过。

---

## 五、问题关系链

```
┌──────────────────────────────────────────────────────────────────┐
│                    Pipeline "假通过" 链路                         │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Resource Check 永不阻塞 (#3)                                    │
│    ↓                                                             │
│  _generate_html 纯 Python 永远成功 (#2)                          │
│    ↓                                                             │
│  generate_mockup 永远 ok=True (#1)                               │
│    ↓                                                             │
│  Pipeline 认为"设计稿已产出"                                      │
│    ↓                                                             │
│  HTML 是通用模板，不是真设计稿 (#2)                                │
│    ↓                                                             │
│  合约验证通过 (ui_mockup 存在)                                    │
│    ↓                                                             │
│  所有测试 mock 掉外部依赖 (#11)                                   │
│    ↓                                                             │
│  用户拿到的是通用模板 HTML，不是设计稿                              │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│                    同理的 Architecture 链路                        │
│                                                                  │
│  check_diagram_resources 永远 ok=True (#4)                       │
│    ↓                                                             │
│  generate_architecture_diagram 永远 ok=True                       │
│    ↓                                                             │
│  Mermaid 图依赖 CDN (#4) / 内容模板化 (#17)                       │
│    ↓                                                             │
│  合约验证通过 (architecture_diagram 存在)                          │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│                    同理的 QA 链路                                  │
│                                                                  │
│  run_full_qa: browser 失败不阻塞 (#9)                             │
│    ↓                                                             │
│  _log_to_file 写 JSON 摘要而不是真实日志 (#5)                      │
│    ↓                                                             │
│  artifact_writer 读到 JSON 而不是构建日志 (#10)                    │
│    ↓                                                             │
│  前端展示的"构建日志"是 JSON 摘要                                  │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 六、修复状态总结（2026-05-21）

### ✅ 已修复（21 项）

| # | 问题 | 修复摘要 |
|---|------|---------|
| 1 | `generate_mockup` 永远 ok=True | `ok` 仅在真实图片生成时为 True，仅 HTML fallback 时返回 `ok:False, degraded:True` |
| 2 | HTML 保底是通用模板 | `degraded` 标记已区分真实设计稿和保底模板；pipeline 发出 SSE `stage:degraded` 事件 |
| 3 | Resource Check 永不阻塞 | 新增 `degraded` + `degraded_reason` 字段，区分真实图片能力和 HTML 保底 |
| 5 | 日志文件写入 JSON 摘要 | 替换为 `_write_real_log`，写入真实 stdout_full/stderr_full |
| 6 | build.log 被两阶段覆盖 | Phase 6 改为写入 `qa-build.log`，避免覆盖 Phase 4 的 `build.log` |
| 7 | 图片文件名用时间戳 | 改为 `ui-mockup-{task_id[:12]}.png` 确定性命名 |
| 9 | browser smoke 失败不阻塞 | `run_full_qa` 检查 `page_opened` + `error`，失败设 `ok:False` |
| 10 | `_log_to_file` 格式不匹配 | `_write_real_log` 写纯文本日志，与 artifact_writer 期望一致 |
| 14 | `artifact_contract_rules_strict` 默认 False | 已改为 `True` |
| 6* | 无 API Key 端到端测试缺失 | 新建 `test_no_api_key_degraded_path.py`（15 测试）|
| 15 | 硬编码 fallback 掩盖真实失败 | `generate_design_tokens`/`screen_plan`/`api_contract`/`data_model`/`file_plan` 全部添加 `degraded` 标记 |
| 17 | Mermaid 图模板化 | `_parse_architecture_spec` 返回 `degraded` 标记，`generate_architecture_diagram` 传播到结果 |
| 18 | 一致性检查过于宽松 | 新增 FK 验证、字段类型验证、双向实体交叉检查、degraded 聚合 |
| 12 | 测试命名误导 | 已修正 `check_design_resources` 行为，测试名体现 degraded 语义 |
| 19 | `run_build` 退出码子字符串匹配 | 改为 `re.search(r"\[exit code:\s*(-?\d+)\]", result)` 结构化提取 |
| 20 | `_collect_files` 静默跳过二进制文件 | 添加 `logger.warning` 记录被跳过的非文本文件 |
| 21 | Phase 7 deploy ImportError 静默降级 | 改为 `logger.error` + 发送 SSE `stage:error` 事件 |
| 22 | `circuit_is_open` Redis 异常静默 | 添加 `logger.error` 记录 Redis 连接失败 |
| 23 | `ALLOWED_WORK_DIRS` 初始化静默异常 | 两个 `except Exception: pass` 改为 `logger.error` 记录异常 |
| 24 | `add_allowed_dir` 沙箱注册静默失败 | 改为 `logger.warning` 记录失败原因，便于排查 agent 文件权限问题 |

### ⚠️ 部分修复（2 项）

| # | 问题 | 说明 |
|---|------|------|
| 4 | 架构图依赖 CDN | 优先本地 `mmdc` CLI 预渲染 SVG，CLI 不可用时 CDN fallback |
| 8 | Vercel 部署失败静默 | 已分类 401/403/429，但最外层 `except Exception` 仍静默降级 |

### 设计限制（不再修改）

| # | 问题 | 说明 |
|---|------|------|
| 2/15/17 | 内容模板化 | 无 LLM 时所有 spec→内容生成本质上是模板匹配。`degraded` 标记已让 pipeline 区分"真产出"和"占位符" |
| 16 | 异常处理降级模式 | 降级策略是设计意图，用于保证最低交付。已加 SSE 事件通知 |

### 关键文件变更

| 文件 | 变更 |
|------|------|
| `ui_visualizer.py` | `generate_mockup` 返回 degraded；5 个 generate_* 方法加 degraded 标记；`_parse_architecture_spec` 返回 degraded；`check_architecture_consistency` 加 FK/类型/双向/聚合检查 |
| `qa_executor.py` | `_write_real_log` 替换 JSON 写入；`run_full_qa` 检查 browser 失败；`build.log`→`qa-build.log` |
| `artifact_writer.py` | `write_qa_artifacts` 读取 `qa-build.log` |
| `config.py` | `artifact_contract_rules_strict: True` |
| `test_no_api_key_degraded_path.py` | **新建** — 15 个无 API Key 降级路径测试 |
| `test_phase6_qa_execution.py` | 更新 `build.log`→`qa-build.log` |
| `codegen_agent.py` | `run_build` 退出码从子字符串匹配改为正则结构化提取 |
| `vercel.py` | `_collect_files` 跳过二进制文件时记录 warning 日志 |
| `pipeline_engine.py` | Phase 7 deploy ImportError 改为发送 SSE error 事件 |
| `llm_router.py` | `circuit_is_open` Redis 异常增加 error 日志 |
| `executor_bridge.py` | `ALLOWED_WORK_DIRS` 初始化异常增加 error 日志 |

### 测试结果

```
455 passed, 1 skipped, 0 failed, 0 regressions
```

### 原始修复方向（已全部执行）
