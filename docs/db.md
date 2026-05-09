连接方式：自动探测 + 环境变量覆盖
数据库地址由 backend/app/config.py 中的 _default_db_url() 函数自动探测：


config.py
Lines 13-27
    pg_url = "postgresql+asyncpg://agenthub:agenthub@localhost:5432/agenthub"
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("localhost", 5432))
        sock.close()
        if result == 0:
            return pg_url
    except Exception:
        pass
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    db_path = os.path.join(base, "data", "agent-hub.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return f"sqlite+aiosqlite:///{db_path}"
逻辑是：

先尝试连 PostgreSQL — TCP 探测 localhost:5432，通了就用 PG
连不上就降级 SQLite — 文件存在 data/agent-hub.db
当前实际默认值
项目	PostgreSQL（生产/Docker）	SQLite（本地开发）
地址
localhost:5432
data/agent-hub.db
用户名
agenthub
N/A
密码
agenthub
N/A
数据库名
agenthub
N/A
连接串
postgresql+asyncpg://agenthub:agenthub@localhost:5432/agenthub
sqlite+aiosqlite:///data/agent-hub.db
如何覆盖
有 3 种方式改变数据库地址，优先级从高到低：

环境变量 DATABASE_URL — 直接设置
.env 文件 — 在 backend/.env 或项目根目录 .env 中配置（当前项目中 不存在 .env 文件，只有 .env.example）
Docker Compose — docker-compose.yml 中写死为 postgresql+asyncpg://agenthub:agenthub@db:5432/agenthub（db 是 Docker 内部服务名）
当前运行状态
你现在通过 make dev 启动，没有跑 Docker 中的 PostgreSQL 容器，所以实际情况是：

localhost:5432 端口探测失败
自动降级到 SQLite → data/agent-hub.db
可以通过访问 http://localhost:8000/health 验证 — 返回的 "database" 字段会显示 "sqlite" 或 "postgresql"。

初始化流程
启动时 main.py 的 lifespan 函数自动处理建表：


main.py
Lines 69-71
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
即 ORM 模型定义了什么表，启动时自动创建（不依赖 Alembic）。Alembic 迁移是给已有数据库升级用的。

如果需要切到 PostgreSQL，最简单的方式：


docker compose up -d db redis    # 只启动 PG + Redis
make dev                         # 再启动后端，会自动检测到 5432 端口