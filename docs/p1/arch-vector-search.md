# P1-4: 向量检索架构设计

## 1. 概述

### 1.1 设计目标

为 Agent Hub 实现高效的向量检索能力，支持：
- 语义搜索
- 代码理解
- 文档检索
- 知识库问答

### 1.2 技术选型对比

| 特性 | pgvector | Qdrant | Chroma |
|------|----------|--------|--------|
| **部署复杂度** | 低（PostgreSQL扩展） | 中（独立服务） | 低（嵌入式/Library） |
| **向量维度** | 最大 16,000 | 无限制 | 最大 4096 |
| **过滤能力** | 基础 SQL 过滤 | 高级元数据过滤 | 基础过滤 |
| **性能** | 中等 | 高 | 中等 |
| **可扩展性** | 垂直扩展 | 水平扩展 | 有限水平扩展 |
| **维护成本** | 低 | 中 | 低 |
| **云原生** | 一般 | 优秀 | 一般 |
| **License** | Apache 2.0 | Apache 2.0 | Apache 2.0 |

### 1.3 推荐方案

**推荐方案：pgvector + Qdrant 双模式**

- **pgvector**：作为主存储，用于需要事务支持和 SQL 查询的场景
- **Qdrant**：作为专用向量引擎，用于高性能向量搜索场景

---

## 2. 系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Vector Search Architecture                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐               │
│  │   Frontend   │    │   Chat API   │    │  Skills API  │               │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘               │
│         │                   │                   │                       │
│         └───────────────────┼───────────────────┘                       │
│                             │                                           │
│                             ▼                                           │
│              ┌──────────────────────────────┐                          │
│              │     Vector Search Gateway     │                          │
│              │  - Query routing  - Load bal. │                          │
│              │  - Cache layer   - Rate limit │                          │
│              └──────────────┬───────────────┘                          │
│                             │                                           │
│         ┌───────────────────┴───────────────────┐                      │
│         │                                       │                      │
│         ▼                                       ▼                      │
│  ┌─────────────┐                        ┌─────────────┐                │
│  │   pgvector  │                        │   Qdrant    │                │
│  │  (Primary)   │                        │ (Specialized)│               │
│  └──────┬──────┘                        └──────┬──────┘                │
│         │                                       │                       │
│         └───────────────────┬───────────────────┘                       │
│                             │                                           │
│                             ▼                                           │
│              ┌──────────────────────────────┐                          │
│              │    Embedding Generation      │                          │
│              │  - OpenAI  - local models    │                          │
│              │  - BGE     - E5              │                          │
│              └──────────────────────────────┘                          │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 模块划分

```
backend/app/services/vector/
├── __init__.py
├── gateway.py           # 向量搜索网关，统一入口
├── registry.py           # 向量引擎注册表
├── embedding.py          # Embedding 生成服务
├── routers/
│   ├── __init__.py
│   ├── pgvector.py      # pgvector 路由
│   └── qdrant.py        # Qdrant 路由
├── engines/
│   ├── __init__.py
│   ├── base.py          # BaseVectorEngine 抽象基类
│   ├── pgvector_engine.py
│   └── qdrant_engine.py
└── cache.py             # 向量缓存层
```

---

## 3. 数据模型

### 3.1 向量集合定义

```python
@dataclass
class VectorCollection:
    name: str                          # 集合名称
    dimension: int                     # 向量维度
    engine: str                        # 引擎类型: "pgvector" | "qdrant"
    metric: str                        # 距离度量: "cosine" | "euclidean" | "dotproduct"
    description: str                   # 集合描述
    metadata_fields: List[MetadataField]  # 元数据字段定义
    created_at: datetime
    updated_at: datetime

@dataclass
class MetadataField:
    name: str
    type: str  # "string" | "integer" | "float" | "boolean"
    indexed: bool = False

@dataclass
class VectorRecord:
    id: str                            # 唯一 ID
    vector: List[float]                # 向量数据
    text: str                         # 原始文本
    metadata: Dict[str, Any]          # 元数据
    collection: str                    # 所属集合
    created_at: datetime
```

### 3.2 预定义集合

| 集合名称 | 维度 | 引擎 | 用途 |
|----------|------|------|------|
| `code_chunks` | 1536 | pgvector | 代码片段语义搜索 |
| `documents` | 1536 | pgvector | 文档检索 |
| `skills` | 768 | qdrant | 技能匹配 |
| `conversations` | 1536 | pgvector | 对话历史 |
| `memory` | 1536 | pgvector | 长期记忆 |

---

## 4. API 设计

### 4.1 向量操作 API

#### 创建集合

```
POST /api/vector/collections
Content-Type: application/json

Request:
{
  "name": "code_chunks",
  "dimension": 1536,
  "engine": "pgvector",
  "metric": "cosine",
  "description": "代码片段向量存储",
  "metadata_fields": [
    {"name": "file_path", "type": "string", "indexed": true},
    {"name": "language", "type": "string", "indexed": true},
    {"name": "project_id", "type": "string", "indexed": true}
  ]
}

Response:
{
  "success": true,
  "collection": {
    "name": "code_chunks",
    "dimension": 1536,
    "total_vectors": 0,
    "created_at": "2024-05-09T10:00:00Z"
  }
}
```

#### 插入向量

```
POST /api/vector/collections/{collection}/vectors
Content-Type: application/json

Request:
{
  "vectors": [
    {
      "id": "vec_001",
      "vector": [0.1, 0.2, ...],
      "text": "def authenticate(user): ...",
      "metadata": {
        "file_path": "auth.py",
        "language": "python",
        "project_id": "proj_xxx"
      }
    }
  ],
  "batch_size": 100
}

Response:
{
  "success": true,
  "inserted_count": 1,
  "failed_count": 0
}
```

#### 搜索

```
POST /api/vector/collections/{collection}/search
Content-Type: application/json

Request:
{
  "query_vector": [0.1, 0.2, ...],  // 可选，提供向量
  "query_text": "用户认证函数",      // 可选，文本自动转向量
  "top_k": 10,
  "filters": {
    "language": {"$eq": "python"},
    "project_id": {"$eq": "proj_xxx"}
  },
  "include_metadata": true,
  "include_vectors": false
}

Response:
{
  "success": true,
  "results": [
    {
      "id": "vec_001",
      "score": 0.95,
      "text": "def authenticate(user): ...",
      "metadata": {
        "file_path": "auth.py",
        "language": "python"
      }
    }
  ],
  "query_time_ms": 12
}
```

#### 删除向量

```
DELETE /api/vector/collections/{collection}/vectors/{vector_id}

Response:
{
  "success": true,
  "deleted_id": "vec_001"
}
```

### 4.2 批量操作 API

```
POST /api/vector/batch

Request:
{
  "operations": [
    {
      "type": "upsert",
      "collection": "code_chunks",
      "vectors": [...]
    },
    {
      "type": "delete",
      "collection": "code_chunks",
      "filter": {"language": {"$eq": "test"}}
    }
  ]
}

Response:
{
  "success": true,
  "results": [
    {"type": "upsert", "success": true, "count": 10},
    {"type": "delete", "success": true, "count": 5}
  ]
}
```

---

## 5. Embedding 服务

### 5.1 Embedding 提供商

```python
class EmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, texts: List[str]) -> List[List[float]]:
        """生成文本的向量表示"""
        pass

    @abstractmethod
    def get_dimension(self) -> int:
        """返回向量维度"""
        pass

# 支持的提供商
class OpenAIEmbedding(EmbeddingProvider):
    MODEL = "text-embedding-3-small"
    DIMENSION = 1536

class BGEEmbedding(EmbeddingProvider):
    MODEL = "BAAI/bge-small-zh"
    DIMENSION = 512

class LocalEmbedding(EmbeddingProvider):
    """使用本地模型（如 sentence-transformers）"""
    DIMENSION = 768
```

### 5.2 Embedding 缓存

```python
class EmbeddingCache:
    """LRU 缓存，避免重复计算相同文本的 embedding"""

    def __init__(self, max_size: int = 10000):
        self._cache: Dict[str, List[float]] = {}
        self._access_order: List[str] = []

    async def get_or_compute(
        self,
        text: str,
        provider: EmbeddingProvider
    ) -> List[float]:
        """获取缓存或计算新的 embedding"""
        cache_key = hash_text(text)
        if cache_key in self._cache:
            return self._cache[cache_key]

        vector = await provider.embed([text])[0]
        self._put(cache_key, vector)
        return vector
```

---

## 6. pgvector 实现

### 6.1 数据库 Schema

```sql
-- 向量集合表
CREATE TABLE vector_collections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) UNIQUE NOT NULL,
    dimension INTEGER NOT NULL,
    engine VARCHAR(50) DEFAULT 'pgvector',
    metric VARCHAR(50) DEFAULT 'cosine',
    description TEXT,
    metadata_schema JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 向量数据表
CREATE TABLE vectors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    collection_id UUID REFERENCES vector_collections(id) ON DELETE CASCADE,
    external_id VARCHAR(255),  -- 外部引用 ID
    vector VECTOR(1536),        -- pgvector 类型
    text TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),

    -- 索引
    CONSTRAINT vector_dim_check CHECK (vector_size(vector) = (SELECT dimension FROM vector_collections WHERE id = collection_id))
);

-- 创建 HNSW 索引
CREATE INDEX idx_vectors_hnsw ON vectors
USING hnsw (vector vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- 创建元数据索引
CREATE INDEX idx_vectors_metadata ON vectors USING gin (metadata);
```

### 6.2 pgvector Engine 实现

```python
class PGVectorEngine(BaseVectorEngine):
    """pgvector 向量引擎实现"""

    async def upsert(
        self,
        collection: str,
        records: List[VectorRecord]
    ) -> UpsertResult:
        """批量插入或更新向量"""
        # SQL: INSERT ... ON CONFLICT DO UPDATE
        pass

    async def search(
        self,
        collection: str,
        query_vector: List[float],
        top_k: int,
        filters: Optional[Dict] = None
    ) -> SearchResult:
        """向量相似度搜索"""
        sql = """
            SELECT id, text, metadata, (vector <=> %s::vector) as distance
            FROM vectors v
            JOIN vector_collections vc ON v.collection_id = vc.id
            WHERE vc.name = %s
            AND (%s 条件过滤)
            ORDER BY vector <=> %s::vector
            LIMIT %s
        """
        pass

    async def delete(
        self,
        collection: str,
        vector_id: str
    ) -> bool:
        """删除向量"""
        pass

    async def get_collection_info(
        self,
        collection: str
    ) -> CollectionInfo:
        """获取集合信息"""
        pass
```

---

## 7. Qdrant 实现

### 7.1 Qdrant 配置

```python
# Qdrant 集合配置
QDANT_COLLECTION_CONFIG = {
    "code_chunks": {
        "vector_size": 1536,
        "distance": "Cosine",
        "hnsw_config": {
            "m": 16,
            "ef_construct": 64
        },
        "optimizers_config": {
            "vacuum_min_vector_size": 1000,
            "default_segment_number": 2
        }
    }
}
```

### 7.2 Qdrant Engine 实现

```python
class QdrantEngine(BaseVectorEngine):
    """Qdrant 向量引擎实现"""

    def __init__(self, url: str = "http://localhost:6333", api_key: str = None):
        self.client = QdrantClient(url=url, api_key=api_key)

    async def upsert(
        self,
        collection: str,
        records: List[VectorRecord]
    ) -> UpsertResult:
        """批量插入向量"""
        points = [
            PointStruct(
                id=record.id,
                vector=record.vector,
                payload={
                    "text": record.text,
                    **record.metadata
                }
            )
            for record in records
        ]
        await self.client.upsert(collection, points)
        pass

    async def search(
        self,
        collection: str,
        query_vector: List[float],
        top_k: int,
        filters: Optional[Filter] = None
    ) -> SearchResult:
        """向量搜索"""
        results = await self.client.search(
            collection_name=collection,
            query_vector=query_vector,
            query_filter=filters,
            limit=top_k
        )
        return [SearchHit(...) for r in results]

    async def delete(
        self,
        collection: str,
        vector_id: str
    ) -> bool:
        """删除向量"""
        await self.client.delete(collection, [vector_id])
        pass
```

---

## 8. 向量搜索网关

### 8.1 查询路由

```python
class VectorSearchGateway:
    """向量搜索统一入口"""

    def __init__(self):
        self._engines: Dict[str, BaseVectorEngine] = {}
        self._cache = VectorSearchCache()
        self._embedding = EmbeddingService()

    def register_engine(self, name: str, engine: BaseVectorEngine):
        """注册向量引擎"""
        self._engines[name] = engine

    async def search(
        self,
        collection: str,
        query: str,
        top_k: int = 10,
        engine_hint: str = None,
        filters: Dict = None
    ) -> SearchResult:
        """统一搜索接口"""

        # 1. 路由到合适引擎
        engine = self._select_engine(collection, engine_hint)

        # 2. 检查缓存
        cache_key = self._cache.make_key(collection, query, filters)
        if cached := await self._cache.get(cache_key):
            return cached

        # 3. 生成 embedding
        query_vector = await self._embedding.embed(query)

        # 4. 执行搜索
        results = await engine.search(
            collection=collection,
            query_vector=query_vector,
            top_k=top_k,
            filters=filters
        )

        # 5. 缓存结果
        await self._cache.set(cache_key, results)

        return results

    def _select_engine(
        self,
        collection: str,
        hint: str = None
    ) -> BaseVectorEngine:
        """选择最优引擎"""
        if hint and hint in self._engines:
            return self._engines[hint]

        # 根据集合选择默认引擎
        collection_config = COLLECTION_CONFIGS.get(collection)
        engine_name = collection_config.get("engine", "pgvector")
        return self._engines[engine_name]
```

### 8.2 搜索结果缓存

```python
class VectorSearchCache:
    """搜索结果缓存"""

    def __init__(self, redis_client, ttl: int = 3600):
        self._redis = redis_client
        self._ttl = ttl

    async def get(self, key: str) -> Optional[SearchResult]:
        """获取缓存结果"""
        cached = await self._redis.get(f"vec_search:{key}")
        if cached:
            return SearchResult.parse_raw(cached)
        return None

    async def set(self, key: str, result: SearchResult):
        """设置缓存"""
        await self._redis.setex(
            f"vec_search:{key}",
            self._ttl,
            result.json()
        )

    @staticmethod
    def make_key(collection: str, query: str, filters: Dict) -> str:
        """生成缓存键"""
        filter_str = json.dumps(filters, sort_keys=True) if filters else ""
        return hashlib.md5(f"{collection}:{query}:{filter_str}".encode()).hexdigest()
```

---

## 9. 集成到 Agent Hub

### 9.1 代码理解集成

```python
# backend/app/services/codebase_indexer.py 增强
class CodebaseIndexer:
    """代码库索引服务"""

    def __init__(self, vector_gateway: VectorSearchGateway):
        self._vector = vector_gateway
        self._embedding = EmbeddingService()

    async def index_file(self, file_path: str, content: str):
        """索引单个文件"""

        # 1. 代码分块
        chunks = self._chunk_code(content, file_path)

        # 2. 生成向量
        texts = [chunk["text"] for chunk in chunks]
        embeddings = await self._embedding.embed_batch(texts)

        # 3. 存储到向量数据库
        records = [
            VectorRecord(
                id=f"{file_path}:{i}",
                vector=emb,
                text=chunk["text"],
                metadata={
                    "file_path": file_path,
                    "language": detect_language(file_path),
                    "chunk_line_start": chunk["start"],
                    "chunk_line_end": chunk["end"]
                },
                collection="code_chunks"
            )
            for i, (emb, chunk) in enumerate(zip(embeddings, chunks))
        ]

        await self._vector.upsert("code_chunks", records)

    async def semantic_search(
        self,
        query: str,
        language: str = None,
        file_path: str = None
    ) -> List[SearchHit]:
        """语义搜索代码"""
        filters = {}
        if language:
            filters["language"] = {"$eq": language}
        if file_path:
            filters["file_path"] = {"$eq": file_path}

        return await self._vector.search(
            collection="code_chunks",
            query=query,
            top_k=10,
            filters=filters
        )
```

### 9.2 技能匹配集成

```python
# backend/app/services/skill_matcher.py
class SkillMatcher:
    """技能匹配服务"""

    def __init__(self, vector_gateway: VectorSearchGateway):
        self._vector = vector_gateway

    async def find_relevant_skills(
        self,
        task_description: str,
        required_capabilities: List[str] = None
    ) -> List[SkillMatch]:
        """根据任务描述找到最匹配的技能"""

        # 1. 搜索相似技能
        results = await self._vector.search(
            collection="skills",
            query=task_description,
            top_k=5
        )

        # 2. 过滤满足需求的技能
        matched_skills = []
        for r in results:
            skill = Skill.from_result(r)
            if required_capabilities:
                if all(cap in skill.capabilities for cap in required_capabilities):
                    matched_skills.append(skill)
            else:
                matched_skills.append(skill)

        return matched_skills
```

---

## 10. 依赖关系

### 10.1 外部依赖

| 依赖 | 用途 | 版本要求 |
|------|------|----------|
| psycopg2-binary | pgvector 连接 | >= 2.9 |
| pgvector | PostgreSQL 扩展 | >= 0.5 |
| qdrant-client | Qdrant 客户端 | >= 1.7 |
| sentence-transformers | 本地 embedding | >= 2.2 |
| redis | 结果缓存 | >= 7.0 |

### 10.2 内部依赖

```
VectorSearchGateway
    ├── PGVectorEngine
    │   └── PostgreSQL (vector_collections, vectors)
    ├── QdrantEngine
    │   └── Qdrant Service
    ├── EmbeddingService
    │   ├── OpenAI API
    │   └── Local Models (optional)
    └── VectorSearchCache
        └── Redis
```

---

## 11. 实施计划

### Phase 1: 基础设施
- [ ] 设计数据库 schema (pgvector)
- [ ] 实现 BaseVectorEngine 抽象类
- [ ] 实现 PGVectorEngine
- [ ] 搭建 Qdrant 测试环境

### Phase 2: 核心功能
- [ ] 实现 VectorSearchGateway
- [ ] 实现 EmbeddingService
- [ ] 实现向量搜索 API
- [ ] 实现结果缓存

### Phase 3: 应用集成
- [ ] 增强 CodebaseIndexer
- [ ] 实现 SkillMatcher
- [ ] 对话历史向量化
- [ ] 长期记忆向量化

### Phase 4: 优化
- [ ] HNSW 索引调优
- [ ] 批量操作优化
- [ ] 缓存策略优化
- [ ] 监控告警

---

## 12. 配置参考

```yaml
# config.yaml

vector:
  # 默认引擎
  default_engine: "pgvector"

  # pgvector 配置
  pgvector:
    host: "localhost"
    port: 5432
    database: "agenthub"
    user: "postgres"
    password: "${POSTGRES_PASSWORD}"
    pool_size: 10

  # Qdrant 配置
  qdrant:
    url: "http://localhost:6333"
    api_key: "${QDRANT_API_KEY}"
    collections:
      code_chunks:
        vector_size: 1536
        distance: "Cosine"

  # Embedding 配置
  embedding:
    provider: "openai"  # openai | bge | local
    openai:
      model: "text-embedding-3-small"
      dimension: 1536
    bge:
      model: "BAAI/bge-small-zh"
      dimension: 512

  # 缓存配置
  cache:
    enabled: true
    ttl: 3600
    max_size: 10000
```
