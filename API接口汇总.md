# Knowledge Base System — API 接口汇总

> 生成日期：2026-07-02
> 版本：0.3.0
> 所有 `/api/v1` 接口返回统一的 `{ data, meta, error }` 结构。

---

## 一、系统健康检查 — `/api/v1/health`

| 方法 | 路径 | 功能 | 说明 |
|------|------|------|------|
| `GET` | `/api/v1/health/live` | 进程存活探针 | 始终返回 200 `{ status: "ok" }`，不触碰外部依赖，供 K8s liveness probe |
| `GET` | `/api/v1/health` | 整体健康检查 | 并行探测 PG/Milvus/MinIO/LLM 四路依赖，任一异常返回 `degraded`，HTTP 始终 200 |

**响应结构：**
- `/live`: `{ data: { status: "ok" }, meta: { service, version } }`
- `/`: `{ data: { status: "ok" | "degraded", dependencies: { postgresql, milvus, minio, llm } }, meta: { service, version } }`

> **已移除**：`/health/ready` 和 `/health/dependencies` 端点。健康检查统一收敛到 `/health`（仪表盘 + banner 状态灯）和 `/health/live`（K8s）。

---

## 二、文档管理 — `/api/v1/documents`

| 方法 | 路径 | 功能 | 参数 |
|------|------|------|------|
| `GET` | `/api/v1/documents` | 文档分页列表，支持多条件筛选和排序 | Query: `page`, `page_size`, `sort_by`(默认 updated_at), `sort_order`, `keyword`, `source_type`, `status`, `category`, `parent_doc_id`, `root_doc_id` |
| `GET` | `/api/v1/documents/ids` | 全量文档 ID 列表（分页遍历，供前端全选批量操作） | Query: `status`, `category`, `keyword` |
| `POST` | `/api/v1/documents` | 创建文档并提交异步入库任务（必定触发） | Body(JSON): `title`(必), `source_type`(必), `source_uri`(必), `source_hash`, `category`(默认"通用"), `metadata`(JSON 字符串) |
| `POST` | `/api/v1/documents/upload` | 上传文件（支持多文件）并创建文档+异步入库 | Form: `files`(必, 多文件), `category`, `replace_doc_id`, `confirm_replace` |
| `GET` | `/api/v1/documents/{doc_id}` | 文档详情（含统计信息） | Path: `doc_id` |
| `GET` | `/api/v1/documents/{doc_id}/elements` | 文档解析元素分页列表 | Path: `doc_id`; Query: `page`, `page_size` |
| `PATCH` | `/api/v1/documents/{doc_id}` | 更新文档标题/分类，批量同步关联知识块 | Path: `doc_id`; Query: `title`, `category` |
| `DELETE` | `/api/v1/documents/{doc_id}` | 软删除文档（级联知识块+索引） | Path: `doc_id` |
| `POST` | `/api/v1/documents/{doc_id}/restore` | 恢复软删除文档（按删前状态分流处理） | Path: `doc_id` |
| `POST` | `/api/v1/documents/{doc_id}/retry` | 重试失败文档的入库 | Path: `doc_id` |
| `GET` | `/api/v1/documents/{doc_id}/history` | 文档版本历史（含 previous_doc_id 链路） | Path: `doc_id` |
| `POST` | `/api/v1/documents/batch-delete` | 批量软删除文档 | Body: `{ doc_ids: [...] }` |
| `POST` | `/api/v1/documents/batch-retry` | 批量重试失败文档 | Body: `{ doc_ids: [...] }` |
| `POST` | `/api/v1/documents/batch-restore` | 批量恢复已删除文档（按删前状态分流） | Body: `{ doc_ids: [...] }` |

**响应结构：**
- 列表：`PaginatedResponse { data: [...], meta: { page, page_size, total, total_pages } }`
- 单条：`APIResponse { data: { doc_id, title, source_type, source_uri, source_hash, category, version, status, parent_doc_id, root_doc_id, previous_doc_id, error_message, created_at, updated_at, metadata, chunk_count, element_count, asset_count, index_summary } }`
- 上传响应（多文件模式）：`{ data: { files: [...], total, success, duplicate, failed } }`
- 单文件上传详细响应：`{ file_name, size, job_id, duplicate, suggested_replace, replaced, replaced_doc_id, ... }`
- 创建文档：`{ data: { ...doc字段, job_id, ingest_error? } }`

**错误码：** `DOCUMENT_NOT_FOUND`(404), `DOCUMENT_DUPLICATE`(409), `VALIDATION_ERROR`(400), `INTERNAL_ERROR`(500), `SERVICE_UNAVAILABLE`(503)

> **重大变更**：
> - `POST /documents` 和 `POST /documents/upload` 不再执行同步入库，改为创建 IngestJob + Dramatiq 异步入队，立即返回 `job_id`。前端通过 `GET /api/v1/jobs/{job_id}/stream` SSE 订阅进度。
> - 移除了 `ingest_after_create`、`mode`、`expected_version`、`status`、`source_uri`、`source_hash` 等旧参数。
> - `PATCH /documents/{id}` 简化为仅支持 `title` 和 `category` 更新。
> - 新增批量操作端点：`batch-delete`、`batch-retry`、`batch-restore`。
> - `POST /documents/{doc_id}/ingest` 已移除，改为通过 `retry` 触发。

---

## 三、知识块管理 — `/api/v1/chunks`

| 方法 | 路径 | 功能 | 参数 |
|------|------|------|------|
| `GET` | `/api/v1/chunks` | 知识块分页列表，多条件筛选 | Query: `page`, `page_size`, `sort_by`(默认 created_at), `sort_order`, `keyword`, `search_mode`(chunk_title/doc_title), `doc_id`, `source_type`, `category`, `knowledge_type`, `status`, `has_assets`, `has_sources` |
| `GET` | `/api/v1/chunks/ids` | 全量知识块 ID 列表（分页遍历，供前端全选批量操作） | Query: `keyword`, `search_mode`, `doc_id`, `source_type`, `category`, `knowledge_type`, `status` |
| `POST` | `/api/v1/chunks` | 创建人工知识块（自动索引写入 Milvus） | Query: `doc_id`(必), `content`(必), `title`, `knowledge_type`(默认 declarative), `category`(默认"通用"), `metadata`(JSON 字符串) |
| `GET` | `/api/v1/chunks/{chunk_id}` | 知识块详情（含完整内容+来源+资源详情+预签名 URL） | Path: `chunk_id` |
| `PATCH` | `/api/v1/chunks/{chunk_id}` | 更新知识块，内容变化时可选重建索引 | Path: `chunk_id`; Query: `title`, `content`, `category`, `knowledge_type`, `reindex`(默认 true) |
| `DELETE` | `/api/v1/chunks/{chunk_id}` | 软删除知识块，同步 Milvus 索引 | Path: `chunk_id` |
| `POST` | `/api/v1/chunks/{chunk_id}/restore` | 恢复软删除的知识块 | Path: `chunk_id` |
| `POST` | `/api/v1/chunks/batch` | 批量状态操作（delete/restore） | Body: `{ action: "delete"|"restore", chunk_ids: [...] }` |

**响应结构：**
- 列表条目：`{ chunk_id, doc_id, doc_title, doc_source_type, title, content_preview, knowledge_type, category, status, asset_count, source_count, created_at, updated_at, metadata }`
- 详情：`{ ...完整 content, content_hash, asset_refs: [{ asset_id, caption, asset_type, storage_uri }], source_refs }`

**错误码：** `CHUNK_NOT_FOUND`(404), `CHUNK_DUPLICATE`(409), `DOCUMENT_NOT_FOUND`(404), `VALIDATION_ERROR`(422)

> **已移除**：`POST /chunks/batch/reindex`、`POST /chunks/{chunk_id}/reindex` 端点。索引操作统一由 `PATCH`（reindex 参数）和 `sync_index_metadata` 内部处理。不再有 `doc_version`、`index_status`、`ingest_job_id`、`status`(Query 参数) 等字段。

---

## 四、检索 — `/api/v1/search`

| 方法 | 路径 | 功能 | 请求体/参数 |
|------|------|------|------|
| `POST` | `/api/v1/search` | 标准混合检索，支持完整过滤和 LLM Rerank | Body: `{ query(必), top_k(1-100, 默认10), filters: { doc_ids, categories, knowledge_types, chunk_status }, options: { rewrite, hybrid, rerank, include_assets, include_sources, include_score_components } }` |
| `GET` | `/api/v1/search/filters` | 返回可用筛选项（分类/知识类型/状态统计） | — |

**请求体 SearchRequest：**
```json
{
  "query": "如何配置火山引擎 API",
  "top_k": 10,
  "filters": {
    "doc_ids": ["doc_xxx"],
    "categories": ["技术文档"],
    "knowledge_types": ["declarative"],
    "chunk_status": ["active"]
  },
  "options": {
    "rewrite": true,
    "hybrid": true,
    "rerank": true,
    "include_assets": true,
    "include_sources": true,
    "include_score_components": true
  }
}
```

**响应结构：**
```json
{
  "data": {
    "results": [{
      "chunk_id": "...",
      "doc_id": "...",
      "doc_title": "...",
      "status": "active",
      "title": "...",
      "content": "...",
      "score": 0.85,
      "category": "技术文档",
      "knowledge_type": "declarative",
      "score_components": { "vector": 0.82, "bm25": 0.73, "rrf": 0.032, "rerank": 0.85 },
      "asset_refs": [{ "asset_id", "caption", "asset_type", "storage_uri" }],
      "source_refs": [{ "doc_id", "doc_version", "element_id", "source_location" }]
    }]
  },
  "meta": { "search_id", "query", "rewritten_query", "total_count", "filters", "options" }
}
```

> **已移除**：`POST /search/debug` 端点。调试功能改为 `retrieval_pipeline.search(debug=True)` 内部参数（仅代码调用）。筛选项 `source_types`、`doc_status`、`created_after`、`created_before`、`index_status` 不再支持（检索全程在 Milvus 内闭环，不查 PG）。`highlight` 选项不再支持。

---

## 五、入库任务状态 — `/api/v1/jobs`

| 方法 | 路径 | 功能 | 说明 |
|------|------|------|------|
| `GET` | `/api/v1/jobs/{job_id}/stream` | SSE 实时推送入库进度 | 前端使用 EventSource 连接，接收 progress/completed/failed 事件，每秒轮询 PG |

**SSE 事件类型：**
- `progress`: 进度更新 — `{ status, stage, progress(0-100) }`
- `completed`: 入库成功 — `{ doc_id, status: "completed" }`
- `failed`: 入库失败 — `{ doc_id, status: "failed", error_message }`

**入库阶段（stage）：** `queued` → `processing`(parsing/extracting/indexing) → `completed` | `failed`

> **重大变更**：旧版 `/api/v1/ingest/jobs` 路由前缀改为 `/api/v1/jobs`。不再有列表/详情/retry/cancel 端点——任务管理由 Dramatiq 中间件自动处理（失败自动重试 3 次，30 分钟硬超时），前端仅需 SSE 订阅进度。

---

## 六、统一响应结构

### 成功响应
```json
{
  "data": { ... },
  "meta": { ... },
  "error": null
}
```

### 错误响应
```json
{
  "data": null,
  "meta": {},
  "error": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "文档 xxx 不存在",
    "details": null
  }
}
```

### 错误码汇总

| 错误码 | HTTP 状态 | 说明 |
|------|------|------|
| `DOCUMENT_NOT_FOUND` | 404 | 文档不存在 |
| `DOCUMENT_DUPLICATE` | 409 | 相同 source_hash 的活跃文档已存在 |
| `CHUNK_NOT_FOUND` | 404 | 知识块不存在 |
| `CHUNK_DUPLICATE` | 409 | 知识块内容与已有知识块重复 |
| `VALIDATION_ERROR` | 400/422 | 请求参数校验失败 |
| `INTERNAL_ERROR` | 500 | 内部错误 |
| `SERVICE_UNAVAILABLE` | 503 | 服务/依赖不可用 |

---

## 七、接口统计

| 分组 | 接口数 | 前缀 |
|------|------|------|
| 健康检查 | 2 | `/api/v1/health` |
| 文档管理 | 14 | `/api/v1/documents` |
| 知识块管理 | 8 | `/api/v1/chunks` |
| 检索 | 2 | `/api/v1/search` |
| 入库任务 SSE | 1 | `/api/v1/jobs` |
| **合计** | **27** | — |

> **旧版接口（`/documents`、`/upload`、`/ingest`、`/search`）已全部移除**，不再提供兼容期。
