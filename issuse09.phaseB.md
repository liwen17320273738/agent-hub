任务 1、2 完成总结
① Launch Post — docs/launch/LAUNCH-POST.md（~480 行）
完整 launch kit，包含：

章节	内容
§1
HN Show HN 主帖（~600 词，两个候选标题，按 SWE-Bench 数据可选）
§2
HN 自评首条评论（讲 self-healing / 防回环 / 没做的事）
§3
Reddit 4 个子版变体：r/programming / r/devops / r/selfhosted / r/LocalLLaMA
§4
Twitter / X 8 条 thread
§5
dev.to 长文骨架（launch +5 天发）
§6
Demo 资产 checklist（GIF/MP4/架构图，硬性要求）
§7
发布日 SOP（T-7 / T-1 / T-0 / T+1 / T+7 时间线 + 复制即用回复模板）
§8
风险登记册 6 项
§8a 红色警告：README.md:47-57 明文写着 Kimi / Qwen / DeepSeek API key 和默认 admin 密码。launch 前必须 git filter-repo 清掉 + 在 provider 端轮换。我没动 README，你自己确认范围后处理。

② SWE-Bench 跑分骨架 — backend/scripts/swebench/
模块	行数	职责
dataset.py
158
加载 hf:princeton-nlp/SWE-bench_Lite 或本地 jsonl，统一为 SweInstance dataclass
patch_utils.py
124
纯函数 — 从 LLM 输出抽取 unified diff、统计 hunks/files、按文件拆分
repo_workspace.py
145
bare-clone cache + 每实例 worktree + 应用 test_patch
agent.py
220
3 阶段 Agentless 循环（locate → read → patch），含文件 shortlist 启发式
evaluator.py
230
git apply --check → git apply → 在 docker_sandbox 跑 pytest → 按 FAIL_TO_PASS / PASS_TO_PASS 评分
__main__.py
178
CLI：--source / --only / --limit / --concurrency / --dry-run / --allow-local-exec
辅助：

backend/requirements-bench.txt — 可选依赖（datasets / pyarrow / swebench）
backend/tests/unit/fixtures/swebench_sample.jsonl — 2 条假数据，CI 不需要联网
backend/tests/unit/test_swebench_harness.py — 22 个新单测全过（patch_utils / dataset / agent / evaluator pure logic）
scripts/run-swebench.sh — 项目根的便捷 launcher
docs/BENCHMARK.md — 复现指南（前置依赖、单题/全集命令、cost 估算 $33-110、输出 schema、已知局限、roadmap）
③ 验证
检查	结果
python -m scripts.swebench --dry-run
✅ 加载 fixture，输出 summary.json
backend 全量 unit suite
✅ 182 passed（160 → 182，+22 SWE-Bench）
lint（新文件 + 新文档）
✅ 0 错误
④ 你接下来要做的事（按 launch SOP 优先级）
必做（阻塞 launch）
轮换 + 删除 README 里 4 个明文 secret（README.md:47-57）+ git filter-repo 重写历史
改写 README 主文案（用 LAUNCH-POST §1 那段做模板）
创建 agent-hub-demo 仓库 + 一个故意有 bug 的 issue 给 demo 用
强烈建议（决定 launch 影响力大小）
export ANTHROPIC_API_KEY=... → ./scripts/run-swebench.sh --source hf:princeton-nlp/SWE-bench_Lite --limit 5 跑 5 题打通
没问题就跑全 Lite（~6h / ~$50）→ 把 summary.json + 失败案例分析提交到 docs/benchmarks/
再考虑 Verified 全集（~10h / ~$100）
launch 前一周
录 90s demo MP4 + 转成 ≤8MB GIF
走 LAUNCH-POST §7 的 T-7 checklist
选周二/周三 PST 7:00 发
需要我接着做：

(a) 帮你写 README 重写版（用 launch post 主帖那段 expand 到 README.md hero 区）
(b) 帮你写 git history rewrite 脚本清掉那 4 个 secret
(c) 创建 demo 仓库的种子代码 + 故意的 bug + issue 模板
(d) 真跑 SWE-Bench Lite 5 题（你给我 API key 就开跑）
说哪个就动哪个。