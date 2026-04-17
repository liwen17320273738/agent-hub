本次交付清单
🔴 P0-1 沙箱真隔离
新增 services/tools/docker_sandbox.py：当 SANDBOX_USE_DOCKER=true 且 docker 可用时，用 --network none --read-only --cap-drop ALL --no-new-privileges --memory 1g --cpus 1，工作区只挂载到 /workspace。镜像缺失会自动降级到 python:3.11-slim。

重写 services/tools/bash_tool.py：

在 docker 模式下走容器
否则走加固的 subprocess
无论哪种模式，先做 28 条正则黑名单（rm -rf /、sudo、curl|bash、cd /、base64|sh、docker run、kubectl、shutdown、/dev/tcp/...）
拒绝时绝不静默回落到 host，明确返回错误
烟测验证：6/6 危险命令被拦，正常命令放行。

🔴 P0-2 长任务自治
配置化超时：PHASE_TIMEOUT_SECONDS=1800（默认 1800s，原硬编码 600s），PHASE_MAX_TIMEOUT_SECONDS=7200
新增 services/pipeline_checkpoint.py：DAG 每完成一个 batch 把状态/输出存进 PipelineArtifact(type=checkpoint)，无需迁移
DAG 支持 resume：execute_dag_pipeline(..., resume=True) 会从 checkpoint 复原 DONE 阶段、跳过它们、从首个未完成处续跑
新增两个 API：
POST /pipeline/tasks/{task_id}/resume — 一键续跑
GET /pipeline/tasks/{task_id}/checkpoint — 检视 checkpoint 状态
🔴 P0-3 浏览器能力
新增 services/tools/browser_tool.py（Playwright 异步、软导入）：

browser_open — 抓取 URL 渲染后的标题+正文
browser_screenshot — 全页 PNG（base64 data URL）
browser_extract — CSS 选择器批量取文本
browser_click_flow — goto → click → 等待 → 抽取（覆盖 SPA 路由）
未装 Playwright 时 registry 静默跳过，不影响系统启动。

🔴 P0-4 真·多 agent 团队
a. 新增 services/agent_delegate.py + delegate_to_agent 工具：任意 agent 可通过 role 召唤 14 个专业 agent 之一（security/designer/data/legal/...），独立 DB session、独立 max_steps，结果文本回灌到调用者上下文。

b. 启用全部 14 角色：

_AGENT_KEY_TO_SEED_ID 从 5 项扩到 13 项
在 5 个核心阶段 prompt 末尾注入 _DELEGATE_HINT，明确告诉它们"何时该 delegate、给哪个角色"
9 个先前闲置的 wayne-* agent 全部具备完整工具集，随时可被 delegate 召唤
c. 顺手修 memory bug：AgentRuntime 加 task_id 入参；pipeline_engine 调用时透传，store_memory(task_id=effective_task_id) 不再写错值。

🔴 P0-5 Codebase 索引
新增 services/tools/codebase_index.py（零额外依赖）：

codebase_map — 走目录树（自动跳过 node_modules/.git/dist/...），按目录分组列文件 + 顶层符号（py/ts/tsx/js/jsx/vue/go/rs/java 都有 regex），输出 markdown ≤10K 字符
codebase_search — 优先用系统 rg，否则 pure-Python 走 os.walk，行号化匹配
codebase_read_chunk — 切片读，配合 search 命中后下钻
烟测：在 services/tools 上 0.4s 抽出 14 文件 + 全部函数符号；ripgrep 路径 0.05s 找到 4 处 TOOL_REGISTRY。

绑定到 wayne-cto / wayne-developer / wayne-qa（含 read_chunk）和 wayne-security / wayne-acceptance（仅 search）。

验证矩阵
检查项	结果
ReadLints — 13 个文件
0 errors
py_compile — 13 个文件
OK
bash_tool 危险命令拦截
6/6 通过
repo_map 抽符号
14 文件正确解析
codebase_search ripgrep
4 处命中
工具注册数量
22 → 32
14 个 agent 工具绑定
全部 OK，无悬空引用
6 个核心模块 import
全部 OK
升级影响一览（数字版）
维度	升级前	升级后
沙箱隔离
host subprocess
docker container 或 28-pattern 黑名单严控 subprocess
Phase 超时
600s 硬编码
1800s 默认 / 7200s 上限 / 可断点续跑
浏览器能力
无
Playwright × 4 工具
Agent 工具
22
32
实战 agent
5
14（5 主 + 9 可被 delegate）
Memory 任务隔离
task_id 写错
修复
Codebase 友好度
必须 file_read 盲读
repo_map + codebase_search + read_chunk
失败可恢复
无
DAG checkpoint + /resume API
还差什么（下一波建议）
短板还在，但段位已显著提升。下一步推荐按这个顺序：

POST /agents/run API — 暴露 AgentRuntime，让你能从 Web/IM 单独调任意 agent（现在只能跑 pipeline）
MCP 客户端 — 让 32 个工具+社区数百个 MCP server 互通
Eval Suite v1 — 30 题 nightly 跑分，今天 P0 改完没有量化体感
Plan/Act 双模式 — IM 进来先发方案卡片，approve 才动手
要不要继续推进 #1（最小代码量 + 立即解锁"一句话调任意 agent"的体验）？

