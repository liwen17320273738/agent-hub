"""Tests for self-verification module."""
from app.services.self_verify import verify_stage_output, VerifyStatus


def test_verify_planning_output_pass():
    output = """# PRD — 用户登录功能

## 需求概述
为平台用户提供安全便捷的账号登录功能，支持邮箱密码登录、记住登录状态、密码找回等核心流程。

## 目标用户
平台注册用户、管理员

## 功能范围
### IN-SCOPE
- 邮箱密码登录
- JWT Token 认证
- 登录状态持久化

### OUT-OF-SCOPE
- 第三方 OAuth 登录（后续迭代）

## 用户故事
1. As a user, I want to login with email and password so that I can access my dashboard.
2. As a user, I want to stay logged in so that I don't have to re-enter credentials.
3. As an admin, I want to manage user accounts so that I can control access.

## 验收标准
1. 用户可以通过邮箱和密码登录系统
2. 登录后获得 JWT Token，有效期 7 天
3. 错误密码时展示明确的错误提示信息
4. 连续 5 次登录失败后锁定账户 15 分钟

## 非功能需求
- 密码使用 bcrypt 加密存储
- API 响应时间 < 500ms

## 里程碑
- Phase 1: Basic email/password login
- Phase 2: Password reset flow
"""
    result = verify_stage_output("planning", "product-manager", output)
    assert result.overall_status in (VerifyStatus.PASS, VerifyStatus.WARN)


def test_verify_empty_output_fails():
    result = verify_stage_output("planning", "product-manager", "")
    assert result.overall_status == VerifyStatus.FAIL


def test_verify_short_output_warns():
    result = verify_stage_output("planning", "product-manager", "Very short PRD.")
    assert result.overall_status in (VerifyStatus.WARN, VerifyStatus.FAIL)


def test_verify_architecture_output():
    output = """# 技术架构方案 — 用户登录系统

## 技术选型和理由
- 后端框架: FastAPI — 异步高性能，类型安全
- 数据库: PostgreSQL — 成熟可靠，支持 JSONB 和扩展
- ORM: SQLAlchemy 2.0 — 异步支持，声明式映射
- 认证: JWT (python-jose) + bcrypt (passlib)
- 缓存: Redis — 登录失败计数、Token 黑名单

## 系统架构
### 组件划分
- `api/auth.py` — 登录/注册路由
- `security.py` — JWT 生成/验证、密码哈希
- `models/user.py` — User/Org ORM 模型
- `middleware/rate_limit.py` — 频率限制

## 数据模型设计
### users 表
| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| email | VARCHAR(320) | 邮箱，唯一索引 |
| password_hash | VARCHAR(255) | bcrypt 哈希 |
| role | VARCHAR(20) | admin/member/viewer |
| is_active | BOOLEAN | 账户启用状态 |
| created_at | TIMESTAMP | 创建时间 |

## API 接口设计
| Method | Path | Description |
|--------|------|-------------|
| POST | /api/auth/login | 邮箱密码登录 |
| GET | /api/auth/me | 获取当前用户信息 |
| POST | /api/auth/register | 管理员创建用户 |

## 实现步骤
1. 创建 User 和 Org 数据模型 (2h)
2. 实现密码哈希和 JWT 工具函数 (1h)
3. 编写登录/注册 API 路由 (3h)
4. 添加频率限制中间件 (1h)
5. 编写集成测试 (2h)

## 风险点和降级方案
1. 密码哈希性能: bcrypt rounds=12，单次 ~300ms，可接受
2. JWT 密钥泄露: 使用环境变量注入，定期轮换
3. 并发登录: Redis 分布式锁防止竞态
"""
    result = verify_stage_output("architecture", "developer", output)
    assert result.overall_status in (VerifyStatus.PASS, VerifyStatus.WARN)
