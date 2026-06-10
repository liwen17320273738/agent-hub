# 架构设计方案 — 智能客服问答系统

**文档状态**: Draft v1.0 | **版本**: 1.0 | **作者**: CTO / 架构师 | **日期**: 2026-06-09

---

## 一、技术选型

| 领域 | 选型 | 理由 | 替代方案 |
|------|------|------|---------|
| **前端框架** | React 18 + TypeScript | 组件生态成熟（Chat UI 组件库丰富），SSR/SSG 灵活，团队 React 经验充足 | Vue 3 + Nuxt（生态稍弱但学习成本低）；Svelte（性能好但生态不成熟） |
| **样式方案** | Tailwind CSS 3 + CSS Variables | 与 UI 设计 Token 天然匹配，零运行时开销，构建时 Tree-shaking | CSS Modules（Token 管理复杂）；Styled-components（运行时性能开销） |
| **后端框架** | FastAPI (Python) | 异步原生支持高并发文档解析和 LLM 流式响应，Pydantic 模型与 API Schema 自动生成，RAG 生态最成熟（LangChain/LlamaIndex 原生 Python） | Node.js Express（LLM SDK 生态弱）；Go Gin（RAG 库几乎为零） |
| **文档解析** | Unstructured.io + PyMuPDF + Markdown-it | Unstructured 支持 20+ 格式（PDF/Word/HTML/MD），PyMuPDF 做 PDF 文本提取，Markdown-it 做 MD/HTML 结构化解析 | LlamaParse（商业但解析质量高）；Tika（Java 依赖重） |
| **向量数据库** | Chroma (开发) → Milvus (生产) | Chroma 零配置本地运行适合开发；Milvus 支持分布式、10亿级向量、租户隔离（Partition）、混合检索（向量+标量过滤） | Pinecone（SaaS 托管，成本高，数据无法本地化）；Qdrant（Rust 实现性能好但生态略弱） |
| **Embedding 模型** | BAAI/bge-large-zh-v1.5 (本地) + OpenAI text-embedding-3-small (云端) | 中文场景 bge 效果最优（MTEB 中文榜前3），本地部署零 API 成本；OpenAI 作为高质量降级方案 | text2vec-large-chinese（效果略差）；m3e（已停止维护） |
| **LLM** | GPT-4o-mini (主) + Qwen2-7B (本地降级) | GPT-4o-mini 性价比最高（$0.15/M input tokens），流式响应快；Qwen2 本地部署作为成本控制和离线降级 | Claude 3 Haiku（价格相当但中文略弱）；DeepSeek-V2（中文强但需自部署） |
| **RAG 框架** | LangChain + 自定义检索流水线 | LangChain 生态最全（文档加载器/文本分割器/检索器/输出解析器），但抽象层较重，核心检索逻辑自定义 | LlamaIndex（索引管理更强但灵活性差）；Haystack（企业级但社区小） |
| **消息队列** | Redis Streams | 异步处理文档解析和向量化任务，支持消费者组和消息持久化 | RabbitMQ（重量级）；Celery（依赖 Redis/RabbitMQ 双组件） |
| **缓存** | Redis 7 | 缓存频繁提问的答案（TTL=1h），缓存 Embedding 结果，存储会话状态 | Memcached（仅缓存，无数据结构能力） |
| **认证** | JWT + OAuth2 Proxy | 无状态认证，适合 API 服务；OAuth2 Proxy 作为反向代理网关提供 SSO 集成 | Session-based（有状态，不适合水平扩展）；Auth0（SaaS 依赖） |
| **部署** | Docker Compose (开发) → Kubernetes (生产) | Docker Compose 快速启动；K8s 支持自动扩缩容、滚动更新、资源隔离 | AWS ECS（厂商锁定）；Nomad（社区小） |

### 选型决策逻辑

```
核心约束: 中文文档理解 + RAG 检索质量 + 成本可控
    │
    ├─ 文档解析: 必须支持 PDF/MD/HTML/Word → Unstructured.io (唯一成熟方案)
    ├─ 向量化: 中文 Embedding 质量 > 速度 → bge-large-zh-v1.5
    ├─ 向量检索: 开发期零配置 → Chroma; 生产期可扩展 → Milvus
    ├─ LLM: 成本优先 → GPT-4o-mini; 离线降级 → Qwen2-7B
    └─ 后端: RAG 生态优先 → FastAPI (Python)
```

---

## 二、系统架构

### 2.1 模块划分

```
┌──────────────────────────────────────────────────────────────────────┐
│                           Client Layer                               │
│  ┌──────────────────────┐  ┌──────────────────────────────────────┐  │
│  │  Web App (React SPA)  │  │  (未来) Mobile / API Client         │  │
│  └──────────┬───────────┘  └──────────────────┬───────────────────┘  │
└─────────────┼──────────────────────────────────┼──────────────────────┘
              │ HTTPS + SSE (流式)               │ HTTPS + JWT
              ▼                                  ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        Gateway Layer                                 │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Nginx / OAuth2 Proxy                                        │   │
│  │  - TLS 终止 / 静态资源缓存 / 速率限制 / JWT 验证              │   │
│  └──────────────────────────┬───────────────────────────────────┘   │
└─────────────────────────────┼────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        Service Layer                                 │
│                                                                      │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │
│  │  Chat Service    │  │  Document       │  │  Knowledge Base     │  │
│  │  (FastAPI)       │  │  Service        │  │  Service            │  │
│  │                  │  │  (FastAPI)      │  │  (FastAPI)          │  │
│  │  - 对话管理       │  │                 │  │                     │  │
│  │  - 流式响应       │  │  - 文件上传      │  │  - 文档管理 CRUD    │  │
│  │  - 引用标注       │  │  - 格式解析      │  │  - 知识库配置       │  │
│  │  - 会话历史       │  │  - 文本分块      │  │  - 索引状态追踪     │  │
│  └────────┬─────────┘  └────────┬─────────┘  └──────────┬──────────┘  │
│           │                     │                       │             │
│           │            ┌────────▼────────┐              │             │
│           │            │  RAG Pipeline    │              │             │
│           │            │  (异步 Worker)   │              │             │
│           │            │                  │              │             │
│           │            │  1. Embedding    │              │             │
│           │            │  2. 向量存储      │              │             │
│           │            │  3. 检索+重排序   │              │             │
│           │            │  4. LLM 生成     │              │             │
│           │            └────────┬─────────┘              │             │
└───────────┼─────────────────────┼────────────────────────┼─────────────┘
            │                     │                        │
            ▼                     ▼                        ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        Data Layer                                    │
│                                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐ │
│  │ PostgreSQL│  │  Redis    │  │  Milvus   │  │  Object Storage     │ │
│  │           │  │          │  │  (向量库)  │  │  (MinIO/S3)         │ │
│  │ - 用户     │  │ - 缓存   │  │           │  │                     │ │
│  │ - 会话     │  │ - 会话   │  │ - 文档向量 │  │ - 原始文档文件      │ │
│  │ - 文档元数据│  │ - 消息队列│  │ - 租户隔离 │  │ - 解析后文本        │ │
│  └──────────┘  └──────────┘  └──────────┘  └──────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.2 核心数据流

**文档上传 → 索引流程**:
```
用户上传文档 → Document Service → 格式校验 → 存入对象存储(原始文件)
    → Redis Streams (async task) → RAG Pipeline Worker:
        1. Unstructured.io 解析 → 提取纯文本
        2. 文本分割器 (RecursiveCharacterTextSplitter, chunk_size=512, overlap=50)
        3. bge-large-zh-v1.5 生成 Embedding
        4. 存入 Milvus (含 tenant_id, document_id, chunk_index 标量字段)
        5. 更新 PostgreSQL 文档状态为 "已索引"
```

**用户提问 → 回答流程**:
```
用户提问 → Chat Service → 安全检查(Prompt注入检测)
    → 生成 Query Embedding (bge)
    → Milvus 检索 (Top-K=5, filter: tenant_id)
    → 重排序 (Cross-encoder, 取 Top-3)
    → 构建 Prompt (System + 检索片段 + 用户问题)
    → LLM 流式生成 (GPT-4o-mini)
    → 输出后处理 (引用标注 [1][2], PII 过滤)
    → SSE 流式返回给前端
    → 异步保存对话历史到 PostgreSQL
```

### 2.3 核心接口

| 接口 | 方法 | 路径 | 描述 |
|------|------|------|------|
| 上传文档 | POST | `/api/v1/documents/upload` | 上传文档文件 |
| 文档列表 | GET | `/api/v1/documents` | 获取文档列表（分页+状态过滤） |
| 文档详情 | GET | `/api/v1/documents/{id}` | 获取文档详情及索引状态 |
| 删除文档 | DELETE | `/api/v1/documents/{id}` | 删除文档及向量数据 |
| 重建索引 | POST | `/api/v1/documents/{id}/reindex` | 重新解析和索引文档 |
| 发送消息 | POST | `/api/v1/chat/messages` | 发送用户消息，SSE 流式返回 |
| 会话历史 | GET | `/api/v1/chat/sessions/{id}/messages` | 获取会话消息历史 |
| 新建会话 | POST | `/api/v1/chat/sessions` | 创建新会话 |
| 获取引用 | GET | `/api/v1/documents/{id}/chunks/{chunk_id}` | 获取引用片段原文 |
| 知识库统计 | GET | `/api/v1/knowledge-base/stats` | 文档数/片段数/索引状态 |
| 系统设置 | GET/PUT | `/api/v1/settings` | LLM 配置/检索参数 |

---

## 三、数据模型

### 3.1 PostgreSQL Schema

```sql
-- 租户/组织
CREATE TABLE tenants (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL,
    plan            VARCHAR(50) NOT NULL DEFAULT 'free',  -- free, pro, enterprise
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 用户
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id),
    email           VARCHAR(255) UNIQUE NOT NULL,
    display_name    VARCHAR(100) NOT NULL,
    role            VARCHAR(50) NOT NULL DEFAULT 'member',  -- admin, member
    password_hash   VARCHAR(255) NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_users_tenant ON users(tenant_id);

-- 文档
CREATE TABLE documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id),
    filename        VARCHAR(500) NOT NULL,
    original_name   VARCHAR(500) NOT NULL,
    file_size       BIGINT NOT NULL,  -- bytes
    mime_type       VARCHAR(100) NOT NULL,
    storage_path    VARCHAR(1000) NOT NULL,  -- 对象存储路径
    page_count      INTEGER,  -- PDF 页数
    chunk_count     INTEGER DEFAULT 0,
    status          VARCHAR(50) NOT NULL DEFAULT 'pending',
        -- pending → parsing → indexing → indexed
        -- pending → parsing → failed
    error_message   TEXT,
    parsed_text_path VARCHAR(1000),  -- 解析后文本的存储路径
    uploaded_by     UUID NOT NULL REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_documents_tenant ON documents(tenant_id);
CREATE INDEX idx_documents_status ON documents(status);

-- 文档块（元数据，向量数据在 Milvus 中）
CREATE TABLE document_chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tenant_id       UUID NOT NULL REFERENCES tenants(id),
    chunk_index     INTEGER NOT NULL,
    chunk_text      TEXT NOT NULL,
    token_count     INTEGER NOT NULL,
    milvus_id       VARCHAR(100),  -- Milvus 中的向量 ID
    metadata        JSONB DEFAULT '{}',  -- 页码、标题等
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_chunks_document ON document_chunks(document_id);
CREATE INDEX idx_chunks_tenant ON document_chunks(tenant_id);

-- 会话
CREATE TABLE chat_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id),
    user_id         UUID NOT NULL REFERENCES users(id),
    title           VARCHAR(255) DEFAULT '新对话',
    is_active       BOOLEAN NOT NULL DEFAULT true,
    message_count   INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_sessions_tenant_user ON chat_sessions(tenant_id, user_id);

-- 消息
CREATE TABLE chat_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role            VARCHAR(50) NOT NULL,  -- user, assistant, system
    content         TEXT NOT NULL,
    tokens_used     INTEGER,
    sources         JSONB DEFAULT '[]',  -- [{document_id, chunk_id, chunk_index, score}]
    latency_ms      INTEGER,  -- LLM 响应时间
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_messages_session ON chat_messages(session_id);
CREATE INDEX idx_messages_created ON chat_messages(created_at);

-- 系统设置
CREATE TABLE system_settings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) UNIQUE,
    llm_provider    VARCHAR(50) NOT NULL DEFAULT 'openai',
    llm_model       VARCHAR(100) NOT NULL DEFAULT 'gpt-4o-mini',
    llm_temperature REAL NOT NULL DEFAULT 0.7,
    llm_max_tokens  INTEGER NOT NULL DEFAULT 2048,
    embedding_model VARCHAR(100) NOT NULL DEFAULT 'bge-large-zh-v1.5',
    chunk_size      INTEGER NOT NULL DEFAULT 512,
    chunk_overlap   INTEGER NOT NULL DEFAULT 50,
    top_k           INTEGER NOT NULL DEFAULT 5,
    enable_rerank   BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 审计日志
CREATE TABLE audit_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id),
    user_id         UUID NOT NULL REFERENCES users(id),
    action          VARCHAR(100) NOT NULL,  -- document.upload, document.delete, chat.send, settings.update
    resource_type   VARCHAR(50),
    resource_id     UUID,
    details         JSONB DEFAULT '{}',
    ip_address      INET,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_tenant_created ON audit_logs(tenant_id, created_at DESC);
```

### 3.2 存储选型策略

| 数据类型 | 存储 | 理由 |
|---------|------|------|
| 结构化业务数据（用户/文档元数据/会话/设置） | PostgreSQL | ACID 事务，外键约束，JSONB 灵活字段 |
| 文档原始文件和解析后文本 | MinIO (S3 兼容) | 大文件存储成本低，CDN 加速 |
| 向量数据（文档块 Embedding） | Milvus | 支持十亿级向量检索，Partition 实现租户隔离，混合检索（向量+标量过滤） |
| 会话缓存 / 热点问答缓存 / 消息队列 | Redis 7 | 低延迟缓存，Redis Streams 异步任务 |
| 对话历史 | PostgreSQL

---

## 并行评审反馈

### 并行评审意见 — security
[delegate→security | steps=2]

# 架构方案安全审计报告

**审计对象**: 智能客服问答系统架构设计方案 (Draft v1.0)  
**审计依据**: OWASP Top 10 (2021) / 最小权限原则 / 数据安全最佳实践  
**审计范围**: JWT 配置、数据加密、网络隔离、最小权限

---

## 发现的安全问题

### 1. JWT 配置 — 关键设计缺失

**严重性**: 高危  
**问题描述**: 架构文档中仅提及使用 JWT + OAuth2 Proxy 进行认证，但完全缺失以下关键安全配置：
- 未指定 JWT 签名算法（若默认使用 `HS256` 而非 `RS256`，存在密钥泄露后伪造 token 的风险）
- 未提及 JWT 过期时间（`exp`）和刷新机制（`refresh token`）
- 未说明 JWT 密钥的存储方式（硬编码？环境变量？密钥管理服务？）
- 未提及 JWT 的 `jti` (JWT ID) 声明用于防重放攻击
- 未说明 OAuth2 Proxy 与 JWT 的关系——是二选一还是叠加使用？若叠加，认证流程不清晰

**OWASP 映射**: A02:2021 – Cryptographic Failures

---

### 2. 数据加密 — 传输层与存储层均不完整

**严重性**: 高危  
**问题描述**:

**2.1 传输层加密**
- 架构图中标注了 `HTTPS + SSE`，但未说明内部服务间通信（Chat Service → Document Service → Knowledge Base Service → Vector DB / LLM）是否启用 mTLS 或至少 TLS
- 若服务间通信为明文 HTTP，攻击者通过内网横向移动即可截获：
  - 用户上传的原始文档内容
  - Embedding 向量（可反向推断文档语义）
  - LLM 请求/响应中的敏感信息
  - JWT token（若在内部 API 间透传）

**2.2 存储层加密**
- 未提及向量数据库（Chroma / Milvus）中向量数据的加密存储
- 未提及 Redis 中缓存的问答数据（TTL=1h）是否加密
- 未提及文档原始文件在存储层的加密（文件系统加密 / 对象存储加密）
- 未提及 Embedding 模型本地部署时模型文件的完整性校验

**OWASP 映射**: A02:2021 – Cryptographic Failures | A04:2021 – Insecure Design

---

### 3. 网络隔离 — 架构图显示为扁平网络

**严重性**: 中危  
**问题描述**: 架构图中所有服务（Chat Service、Document Service、Knowledge Base Service、Redis、Vector DB、LLM）均处于同一网络平面，缺乏以下隔离机制：
- 未划分 DMZ、应用层、数据层网络区域
- 未说明 Gateway Layer（Nginx/OAuth2 Proxy）是否与 Service Layer 物理/逻辑隔离
- 未说明向量数据库和 Redis 是否部署在独立私有子网，仅允许 Service Layer 特定端口访问
- 未提及 LLM API 调用是否通过专用出口 IP / 代理，避免直接暴露公网
- 未说明 Kubernetes 环境下的 NetworkPolicy 配置策略

**风险场景**: 若 Document Service 被攻破（如恶意文件上传漏洞），攻击者可直接横向访问向量数据库和 Redis，窃取所有知识库文档和缓存数据。

**OWASP 映射**: A01:2021 – Broken Access Control | A04:2021 – Insecure Design

---

### 4. 最小权限 — 服务间权限未定义

**严重性**: 中危  
**问题描述**: 架构文档未定义任何服务间的最小权限策略：
- 未说明 Chat Service 对 Document Service 的 API 访问范围（是否允许删除文档？是否允许列出所有文档？）
- 未说明 Document Service 对向量数据库的写入权限是否应限制为仅写入自身租户的 partition
- 未说明 Knowledge Base Service 对 Redis 的访问是否应限制为特定 key 前缀
- 未说明 OAuth2 Proxy 与后端服务之间的 JWT 是否携带角色/权限声明（`roles` / `permissions` c

### 并行评审意见 — developer
[delegate→developer | steps=4]

## 架构方案审阅报告

**审阅对象**: 智能客服问答系统 — 架构设计方案 v1.0
**审阅范围**: 技术选型、系统架构、API 设计、数据模型、存储方案
**审阅视角**: 全栈工程可实现性（API 设计完整性、数据模型可实现性、技术栈熟悉度）
**审阅结论**: **APPROVED**（附带 3 项中优先级修复项）

---

### 总体评价

该架构方案整体质量较高，技术选型逻辑清晰，决策链条完整（核心约束→选型→替代方案），模块划分合理。FastAPI + React + LangChain 的选型组合在当前 RAG 场景下是最成熟的技术栈之一，团队经验充足。以下列出 3 个最重要的可实现性顾虑：

---

### 顾虑 1：API 设计缺失 — 流式响应接口未定义

**严重程度**: 高
**问题描述**: 架构方案中提到了"流式响应"（SSE），但未给出任何 API 端点定义。智能客服的核心交互是流式对话，缺少 `/api/chat/stream` 端点的请求/响应 Schema 定义，会导致前后端联调时出现接口不一致。

**具体缺失**:
- 请求体结构（session_id, message, context, model_params 等）
- 响应格式（SSE event 类型：`token`, `done`, `error`, `source` 等）
- 错误处理（流中断、超时、重试策略）

**修复建议**:
```
POST /api/v1/chat/stream
Request: { session_id: string, message: string, context?: { document_ids?: string[] } }
Response: SSE stream
  event: token    data: { text: string }
  event: source   data: { document_id: string, chunk: string, score: float }
  event: done     data: { session_id: string, token_usage: {...} }
  event: error    data: { code: string, message: string }
```

---

### 顾虑 2：数据模型未定义 — 核心实体缺失

**严重程度**: 高
**问题描述**: 架构方案中完全没有定义数据模型（ERD 或至少核心表结构）。智能客服系统至少需要以下实体，缺失会导致后端开发时数据层设计不一致：

**必须定义的模型**:
1. **Conversation（会话）**: id, user_id, title, status, created_at, updated_at
2. **Message（消息）**: id, conversation_id, role(user/assistant/system), content, sources(json), token_usage, created_at
3. **Document（文档）**: id, user_id, filename, file_type, status(processing/ready/failed), chunk_count, created_at
4. **DocumentChunk（文档块）**: id, document_id, chunk_index, content, embedding(vector), metadata(json)
5. **KnowledgeBase（知识库）**: id, user_id, name, description, document_ids, created_at

**修复建议**: 在架构文档中补充核心 ERD 或至少列出以上 5 个核心实体的字段定义，并标注向量字段类型（pgvector 或 Milvus 的 vector 类型）。

---

### 顾虑 3：文档解析异步任务链路不完整

**严重程度**: 中
**问题描述**: 架构方案中提到了 Redis Streams 用于异步处理文档解析和向量化，但未说明以下关键细节：

**缺失环节**:
1. **任务队列结构**: Redis Stream 的 consumer group 设计、消息格式、重试次数、死信队列
2. **解析流程状态机**: 文档上传 → 解析中 → 向量化中 → 就绪 / 失败，状态变更如何通知前端（轮询