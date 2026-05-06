# P1：Agent Hub Pipeline 核心 → pip 包

**工作量（估）**：约 2h  

**本仓库交付物**

- 包目录：`packages/agent-hub-pipeline/`
- 安装入口：`packages/agent-hub-pipeline/pyproject.toml`、`setup.py`
- 说明：`packages/agent-hub-pipeline/README.md`

**待办摘要**

- ✅ 本地可执行：`pip install -e ./packages/agent-hub-pipeline`
- 🔲 如需公开发布：配置 PyPI 项目名、License、CI `twine upload`（当前 `Proprietary`）
- ✅ 根目录 `AGENTS.md` 已指向本包 README；完整编排不在包内（避免过度承诺）
