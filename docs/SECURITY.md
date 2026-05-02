# Agent Hub 安全加固与密钥轮换指南

> ⚠️ **生产部署前必须执行**

## 第一步：生成新密钥

```bash
# JWT Secret（至少32字符）
python3 -c "import secrets; print(secrets.token_urlsafe(48))"

# Pipeline API Key
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Session Secret（Node.js server）
python3 -c "import secrets; print(secrets.token_urlsafe(48))"

# PostgreSQL Password
python3 -c "import secrets; print(secrets.token_urlsafe(16))"

# Redis Password
python3 -c "import secrets; print(secrets.token_urlsafe(16))"
```

## 第二步：需要轮换的密钥清单

| 密钥 | 状态 | 需要做的 |
|------|------|----------|
| ZHIPU_API_KEY | ⚠️ 旧密钥仍有效 | [智谱开放平台](https://bigmodel.cn/usercenter/apikeys) 重新生成 |
| ANTHROPIC_API_KEY | ⚠️ 旧密钥仍有效 | [Anthropic Console](https://console.anthropic.com/) 重新生成 |
| VERCEL_TOKEN | ⚠️ 旧密钥仍有效 | [Vercel](https://vercel.com/account/tokens) 重新生成 |
| FEISHU_APP_SECRET | ⚠️ 旧密钥仍有效 | [飞书开放平台](https://open.feishu.cn/) 重新生成 |
| FEISHU_VERIFICATION_TOKEN | ⚠️ 旧密钥仍有效 | [飞书开放平台](https://open.feishu.cn/) 重新生成 |
| DATABASE_URL | ✅ 已轮换 (2026-05-02) | 密码已更新 |
| JWT_SECRET | ✅ 已轮换 (2026-05-02) | 已生成新值 |
| ADMIN_PASSWORD | ✅ 已轮换 (2026-05-02) | 已更新为强密码 |
| PIPELINE_API_KEY | ✅ 已轮换 (2026-05-02) | 已更新 `.env` 和 `backend/.env` |
| REDIS_PASSWORD | ✅ 已轮换 (2026-05-02) | 已更新 `.env` 和 docker-compose |
| POSTGRES_PASSWORD | ✅ 已轮换 (2026-05-02) | 已更新 `.env` 和 docker-compose |

## 第三步：更新 `.env`

```bash
# 1. 备份当前 .env
cp .env .env.backup.$(date +%Y%m%d)

# 2. 编辑 .env，替换以上所有密钥
# 3. 确保 .gitignore 包含 .env（已包含，不要移除）

# 4. 删除 backend/.env 中的敏感信息
# backend/.env 应该只保留开发配置，生产用 docker-compose 的环境变量
```

## 第四步：更新 Docker 配置

```bash
# docker-compose.yml 和 docker/*.yml 中的密码已改为 ${VAR:?required} 模式
# 现在密码从 .env 读取，不再硬编码

# 生产部署前在 .env 中设置：
POSTGRES_PASSWORD=<生成的新密码>
REDIS_PASSWORD=<生成的新密码>
```

## 第五步：验证

```bash
# 启动服务
docker compose up -d

# 检查健康状态
curl http://localhost:80/health

# 确认 Redis AOF 已开启
docker exec agent-hub-redis redis-cli CONFIG GET appendonly
# 应返回: 1) "appendonly" 2) "yes"
```

## 定期维护

```bash
# 每日备份（添加到 crontab）
0 3 * * * /app/scripts/backup-db.sh /data/backups

# 密钥轮换周期
# - API Keys: 90天
# - Database Password: 180天
# - JWT Secret: 在部署新版本时更换
```
