# 知识库系统 · Knowledge Base System

多格式文档入库、解析、语义抽取、混合检索平台。支持 PDF / Word / PPT / Excel / HTML / Markdown 等常见办公文档格式的智能解析与语义检索。

---

## 目录

- [架构概览](#架构概览)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [API 接口](#api-接口)
- [核心模块](#核心模块)
- [前端页面](#前端页面)
- [评测系统](#评测系统)
- [CHANGELOG](#changelog)

---

## 架构概览

```
                              ┌──────────────┐
                              │   Nginx 反向代理 │
                              │  HTTP/2 · SSE │
                              └──────┬───────┘
                                     │
┌────────────────────────────────────┼──────────────────────────┐
│                                   │   前端 SPA                 │
│  Vanilla JS · Router · 仪表盘/文档/搜索/入库/知识块              │
└────────────────────────────────────┼──────────────────────────┘
                                     │ HTTP REST + SSE (JSON)
┌────────────────────────────────────▼──────────────────────────┐
│                         FastAPI 后端                           │
│                                                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐ │
│  │ 文档管理  │  │ 知识块管理 │  │ 混合检索  │  │ 入库任务管理  │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬───────┘ │
│       │             │             │               │          │
│  ┌────▼─────────────▼─────────────▼───────────────▼────────┐ │
│  │                      核心服务层                          │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐  │ │
│  │  │ 解析器    │  │ 入库管道  │  │ 检索管道              │  │ │
│  │  │ (6种格式) │  │ (语义抽取) │  │ (向量+BM25+RRF+Rerank)│  │ │
│  │  └──────────┘  └──────────┘  └──────────────────────┘  │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌──────────────────────────────────────────────────────────┐│
│  │  异步任务层                              ┌──────────────┐ ││
│  │  Dramatiq Worker ←→ Redis Broker         │ SSE 进度推送  │ ││
│  │  (异步入库 · 自动重试 · 分段进度)          └──────────────┘ ││
│  └──────────────────────────────────────────────────────────┘│
└────────────────────────────┬────────────────────────────────┘
                             │
     ┌───────────────┼───────────────┬───────────────┬───────────────┐
     │               │               │               │               │
 ┌───▼───┐  ┌────────▼────────┐  ┌───▼───┐  ┌───────▼──────┐  ┌──────▼───┐
 │ 火山引擎│  │    Milvus      │  │  PG   │  │    MinIO     │  │  Redis   │
 │LLM/Emb │  │ 向量+BM25 双索引 │  │数据存储│  │  对象存储     │  │ 任务队列  │
 └───────┘  └────────┬────────┘  └───────┘  └──────┬───────┘  └─────┬────┘
                     │                             │               │
                     └────────── 内部依赖 ──────────┴───────────────┘
                     (Milvus 内部使用 MinIO + etcd)
```

**核心流程：**

```
文档上传 → 格式解析 → 语义抽取(LLM) → 知识块划分
                                         │
                                    ┌────▼────┐
                                    │ 双路索引 │
                                    └─┬───┬──┘
                           HNSW 向量索引  BM25 稀疏索引
                           (COSINE)      (Milvus 原生 Tantivy)
                                    │    │
                                    └┬──┬┘
                                   RRF 融合
                                      │
                                  LLM Rerank
                                      │
                                   最终结果
```

**检索链路已完全去 PG 化**：Milvus 存储全量标量字段（chunk_id / doc_id / title / content / category / knowledge_type / status / source_refs / asset_refs），筛选、召回、排序全链路闭环在 Milvus 内完成，无需回查 PostgreSQL。

---

## 技术栈

| 层级            | 技术                           | 说明                                                        |
| ------------- | ---------------------------- | --------------------------------------------------------- |
| **Web 框架**    | FastAPI 0.115+               | 异步 REST API + SSE 流式推送，自动 OpenAPI 文档                      |
| **反向代理**      | Nginx                        | HTTP/2 前端，SSE 长连接兼容配置                                     |
| **语言**        | Python 3.10+                 | 类型注解 `X \| None`、`list[X]` 语法                             |
| **数据模型**      | Pydantic v2                  | 请求/响应校验，Settings 配置管理                                     |
| **LLM（高质量）**  | 火山引擎 doubao-seed-2-0-pro     | 语义抽取等高质量任务                                                |
| **LLM（快速）**   | 火山引擎 doubao-seed-2-0-mini    | 查询重写、Rerank 等高频低延迟任务                                      |
| **Embedding** | 火山引擎 doubao-embedding-vision | 文本+视觉联合向量化（1024 维）                                        |
| **向量检索**      | Milvus 2.5 HNSW + COSINE     | 持久化稠密向量索引                                                 |
| **全文检索**      | Milvus 2.5 原生 BM25           | Tantivy 引擎 + chinese 分析器，自动稀疏向量化                          |
| **融合排序**      | RRF + LLM Rerank             | 倒数排序融合 + 深度语义重排                                           |
| **数据库**       | PostgreSQL                   | 文档/知识块/资产/任务/解析元素 元数据持久化                                  |
| **对象存储**      | MinIO + 内容寻址                 | 资产去重存储，SHA-256 哈希为 Key                                    |
| **任务队列**      | Dramatiq + Redis             | 异步入库、自动重试、分段进度                                            |
| **PDF 精准解析**  | MinerU API + PyMuPDF         | 布局分析、阅读顺序、公式识别，自动降级                                       |
| **微信微盘**      | 企业 API + Playwright          | 双路径下载策略，支持管理员/非管理员                                        |
| **前端**        | Vanilla JS SPA               | 自制路由、组件化，无框架依赖                                            |
| **样式**        | 自定义 CSS                      | 思源黑体 + JetBrains Mono                                     |
| **容器化**       | Docker Compose               | PostgreSQL + Milvus + MinIO + Redis + Nginx + etcd + Attu |

---

## 项目结构

```
knowledge-base-system/
├── frontend/                          # 前端单页应用
│   ├── index.html                     # SPA 入口
│   ├── css/style.css                  # 全局样式
│   └── js/
│       ├── api.js                     # API 客户端（封装所有后端接口，含 SSE）
│       ├── router.js                  # Hash 路由
│       ├── app.js                     # 应用入口，路由注册与初始化
│       └── components/
│           ├── common.js              # 公共 UI 组件（Toast/Modal/Badge/状态）
│           ├── dashboard.js           # 仪表盘页面
│           ├── documents.js           # 文档列表页面（含批量操作 + SSE 进度条）
│           ├── document-detail.js     # 文档详情页面
│           ├── search.js              # 搜索页面（含调试模式）
│           └── chunks.js              # 知识块管理页面
│
├── backend/                           # Python 后端
│   ├── app/                           # FastAPI 应用
│   │   ├── main.py                    # 应用入口，路由挂载，静态文件
│   │   ├── api/                       # API 路由
│   │   │   ├── upload_utils.py        # 上传工具（去重检测、文件保存）
│   │   │   └── v1/                    # v1 API（当前主力）
│   │   │       ├── __init__.py        # 路由挂载与异常处理器注册
│   │   │       ├── schemas.py         # 统一响应模型 (APIResponse/Error/Pagination)
│   │   │       ├── errors.py          # 错误码与异常处理器
│   │   │       ├── services.py        # 依赖注入服务工厂 + 索引同步服务
│   │   │       ├── health.py          # 健康检查（存活探测 + 四路依赖并行探测）
│   │   │       ├── documents.py       # 文档 CRUD + 上传 + 入库触发 + 批量操作
│   │   │       ├── chunks.py          # 知识块 CRUD + 批量操作 + 索引重建
│   │   │       ├── search.py          # 混合检索 + 调试检索 + 过滤器
│   │   │       └── jobs.py            # 入库任务 SSE 进度推送
│   │   ├── core/                      # 核心基础设施
│   │   │   ├── config.py              # 配置管理 (pydantic-settings)
│   │   │   ├── deps.py                # 全局依赖：LLM/Embedding/索引/仓库
│   │   │   ├── models.py              # 核心数据模型
│   │   │   ├── errors.py              # 业务异常类
│   │   │   └── paths.py               # 路径工具
│   │   ├── db/                        # 数据库层
│   │   │   ├── engine.py              # 数据库引擎（自动创建表+扩展）
│   │   │   ├── models.py              # SQLAlchemy ORM 模型（含入库任务、搜索日志）
│   │   │   └── repositories/          # 仓库模式
│   │   │       ├── base.py            # 基础仓库类
│   │   │       ├── documents.py       # 文档仓库
│   │   │       ├── elements.py        # 解析元素仓库
│   │   │       ├── chunks.py          # 知识块仓库
│   │   │       ├── assets.py          # 资产仓库
│   │   │       ├── jobs.py            # 入库任务仓库
│   │   │       └── search_logs.py     # 搜索日志仓库
│   │   ├── tasks/                     # 异步任务（Dramatiq）
│   │   │   ├── __init__.py            # 注册 broker + 导入 actor
│   │   │   ├── broker.py              # Redis Broker 配置
│   │   │   └── ingest.py              # 异步入库 actor（分段进度 + 自动重试）
│   │   └── utils/                     # 工具模块
│   │       └── thread_pool.py         # 多业务线隔离的线程池体系
│   │
│   ├── parsers/                       # 文档解析器
│   │   ├── base.py                    # 解析器基类 + ParseResult 模型
│   │   ├── registry.py                # 解析器注册表（按 source_type 匹配）
│   │   ├── utils.py                   # 解析通用工具（链接分类等）
│   │   ├── pdf_parser.py              # PDF 解析 (PyMuPDF)
│   │   ├── docx_parser.py             # Word (.docx) 解析
│   │   ├── pptx_parser.py             # PowerPoint (.pptx) 解析
│   │   ├── xlsx_parser.py             # Excel (.xlsx) 解析
│   │   ├── html_parser.py             # HTML 解析 (BeautifulSoup)
│   │   └── markdown_parser.py         # Markdown 解析
│   │
│   ├── ingestion/                     # 入库管道
│   │   └── pipeline.py                # 主入库流程（清理→解析→资产处理→语义抽取→双路索引）
│   │
│   ├── indexing/                      # 索引层
│   │   ├── base.py                    # 索引抽象基类 (VectorIndex / BM25Index)
│   │   ├── milvus_vector.py           # Milvus 稠密向量索引 (HNSW + COSINE)
│   │   ├── milvus_bm25.py             # Milvus 原生 BM25 索引 (Tantivy 引擎)
│   │   └── fusion.py                  # RRF 融合算法
│   │
│   ├── retrieval/                     # 检索管道
│   │   └── pipeline.py                # 完整检索流程（重写→双路召回→融合→Rerank）
│   │
│   ├── llm/                           # LLM 客户端
│   │   ├── volcengine_client.py       # 火山引擎 SDK 封装（chat/embed/vision）
│   │   ├── prompts.py                 # 提示词模板（语义抽取/筛选/摘要）
│   │   ├── semantic_extractor.py      # 语义知识块抽取器
│   │   ├── query_rewriter.py          # 查询重写器
│   │   └── reranker.py                # 结果重排序器
│   │
│   ├── assets/                        # 资产处理
│   │   ├── base.py                    # 资产存储抽象
│   │   ├── minio_store.py             # MinIO 对象存储（内容寻址）
│   │   ├── downloader.py              # HTTP 资源下载工具
│   │   └── asset_processor.py         # 资产处理器（图片/视频视觉理解）
│   │
│   ├── scripts/                       # 运维脚本
│   │   ├── setup_services.py          # 外部服务初始化（PG 建表 + Milvus 建 Collection + MinIO 建 Bucket）
│   │   ├── clear_services.py          # 外部服务数据清空（不可逆）
│   │   ├── import_folder.py           # 批量文件夹导入（支持嵌套目录、Dramatiq 异步入库）
│   │   ├── _analyze_eval.py           # 评测结果分析工具
│   │   └── _check_similarity.py       # 跨文档语义相似度检查
│   │
│   ├── requirements.txt               # Python 依赖
│   └── Dockerfile.worker              # Dramatiq Worker 镜像
│
├── evaluation/                        # 评测系统
│   ├── README.md                      # 评测系统详细文档
│   ├── dataset.py                     # 数据集模型与加载
│   ├── gen_dataset.py                 # 入库时 LLM 自动生成评测数据
│   ├── manual_gen_dataset.py          # 手动生成评测数据
│   ├── merge_to_global.py             # 手动合并到全局数据集
│   ├── run_eval.py                    # 评测执行入口
│   ├── metrics.py                     # 评测指标 (Hit@K、Recall@K、Precision@K、MRR)
│   ├── storage.py                     # 分文档存储 + JSONL 历史追加
│   └── eval_dataset.json              # 全局评测数据集
│
├── docker-compose.yml                 # Docker 服务编排（含 Redis/Dramatiq/Nginx）
├── nginx.conf                         # Nginx 反向代理配置（HTTP/2 + SSE + /assets/ MinIO 代理）
└── API接口汇总.md                      # 全部 API 接口详细说明
```

---

## 快速开始

### 环境要求

- Python 3.10+
- Docker & Docker Compose（用于 PostgreSQL / Milvus / MinIO / Redis）
- 火山引擎 API Key（LLM 和 Embedding 服务）
- MinerU API Token（可选，用于 PDF 精准解析）
- 微信企业 API 凭证（可选，用于微信微盘下载）

### 1. 克隆项目

```bash
git clone <repo-url>
cd knowledge-base-system
```

### 2. 创建虚拟环境并安装依赖

```bash
python -m venv venv
source venv/bin/activate   # Linux/macOS
# 或 venv\Scripts\activate  (Windows)

pip install -r backend/requirements.txt
```

### 3. 配置环境变量

编辑 `backend/.env`，填入火山引擎 API Key：

```env
VOLCENGINE_API_KEY=your-api-key-here
# 可选：MinerU PDF 精准解析
# MINERU_API_TOKEN=your-mineru-token
```

### 4. 启动基础服务

```bash
# 启动全部服务（PostgreSQL + Milvus + MinIO + Redis + Nginx + Dramatiq Worker）
docker compose up -d

# 仅启动基础服务（不含 Nginx 和 Worker，适合本地开发）
docker compose up -d postgres etcd minio milvus-standalone redis
```

> **Docker 服务端口映射：**
>
> | 服务 | 端口 | 说明 |
> |------|------|------|
> | Nginx | `80` | HTTP/2 反向代理（生产入口） |
> | PostgreSQL | `5432` | 关系数据库 |
> | Redis | `6379` | 任务队列 Broker |
> | MinIO API | `9000` | 对象存储 |
> | MinIO Console | `9001` | MinIO Web 管理 |
> | Milvus | `19530` | 向量数据库 |
> | Attu | `8001` | Milvus Web 管理界面 |

### 5. 初始化外部服务（首次运行）

```bash
cd backend
python scripts/setup_services.py
```

该脚本幂等地完成：PostgreSQL 建表、Milvus 建 Collection（HNSW + BM25 双索引）、MinIO 建 Bucket。

### 6. 启动应用

```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 7. 访问系统

- **生产入口 (Nginx)**：http://localhost
- **前端界面（直连）**：http://localhost:8000
- **API 文档 (Swagger)**：http://localhost:8000/docs
- **API 文档 (ReDoc)**：http://localhost:8000/redoc
- **Milvus 管理 (Attu)**：http://localhost:8001（如果启动了 Attu）

---

## 配置说明

所有配置项通过环境变量或 `.env` 文件设置，支持运行时热刷新。

### 核心配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VOLCENGINE_API_KEY` | — | 火山引擎 API Key（**必填**） |
| `VOLCENGINE_LLM_MODEL` | `doubao-seed-2-0-pro-260215` | LLM 模型（高质量任务：语义抽取） |
| `LLM_FAST_MODEL` | `doubao-seed-2-0-mini-260428` | LLM 快速模型（低延迟任务：查询重写、Rerank） |
| `VOLCENGINE_EMBEDDING_MODEL` | `doubao-embedding-vision-251215` | Embedding 模型（1024 维） |
| `VOLCENGINE_TIMEOUT_SECONDS` | `3600` | API 请求超时（秒） |

### 数据库

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `BACKEND` | `postgres` | 后端存储模式（仅支持 postgres） |
| `DATABASE_URL` | `postgresql://kbuser:kbpass@localhost:5432/knowledge_base` | PostgreSQL 连接串 |

### Milvus 向量检索

| 变量                            | 默认值                | 说明                             |
| ----------------------------- | ------------------ | ------------------------------ |
| `MILVUS_ENABLED`              | `true`             | 启用 Milvus                      |
| `MILVUS_HOST`                 | `localhost`        | Milvus 主机                      |
| `MILVUS_PORT`                 | `19530`            | Milvus 端口                      |
| `MILVUS_COLLECTION`           | `knowledge_chunks` | Collection 名称                  |
| `MILVUS_HNSW_M`               | `16`               | HNSW 图连接数                      |
| `MILVUS_HNSW_EF_CONSTRUCTION` | `200`              | HNSW 构建时搜索宽度                   |
| `MILVUS_HNSW_EF`              | `120`              | HNSW 搜索时候选集大小（建议 ≥ top_k×4）    |
| `MILVUS_SPARSE_EF`            | `60`               | BM25 稀疏向量搜索候选集大小（建议 ≥ top_k×2） |

### MinIO 对象存储

| 变量                       | 默认值              | 说明                                               |
| ------------------------ | ---------------- | ------------------------------------------------ |
| `MINIO_ENABLED`          | `true`           | 启用 MinIO                                         |
| `MINIO_ENDPOINT`         | `localhost:9000` | MinIO 地址                                         |
| `MINIO_ACCESS_KEY`       | `minioadmin`     | 访问密钥                                             |
| `MINIO_SECRET_KEY`       | `minioadmin`     | 秘密密钥                                             |
| `MINIO_BUCKET_INPUT`     | `kb-input`       | 原始文件 Bucket                                      |
| `MINIO_BUCKET_ASSETS`    | `kb-assets`      | 资产 Bucket（图片/视频）                                 |
| `MINIO_PRESIGNED_EXPIRY` | `3600`           | 预签名 URL 有效期（秒）                                   |
| `MINIO_PUBLIC_ENDPOINT`  | —                | 预签名 URL 对外地址，如 `https://kb.example.com`；留空使用内部地址 |

### MinerU PDF 精准解析

| 变量                 | 默认值                  | 说明                                  |
| ------------------ | -------------------- | ----------------------------------- |
| `MINERU_API_TOKEN` | —                    | MinerU API Token（不配置则自动降级到 PyMuPDF） |
| `MINERU_API_BASE`  | `https://mineru.net` | MinerU API 基础地址                     |
| `MINERU_USE_VLM`   | `false`              | 是否启用 VLM 辅助识别                       |

### 异步任务队列（Dramatiq + Redis）

| 变量                            | 默认值                        | 说明                         |
| ----------------------------- | -------------------------- | -------------------------- |
| `REDIS_URL`                   | `redis://localhost:6379/0` | Redis 连接串（Dramatiq Broker） |
| `DRAMATIQ_TASK_MAX_RETRIES`   | `3`                        | 入库任务最大重试次数                 |
| `DRAMATIQ_TASK_TIME_LIMIT_MS` | `1800000`                  | 单任务硬超时（毫秒），默认 30 分钟        |

### 微信微盘下载

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WECHAT_DRIVE_COOKIES` | — | 浏览器 Cookie（短期，需手动刷新，非管理员路径） |
| `WECHAT_CORPID` | — | 企业微信 CorpID（管理员路径，持久化） |
| `WECHAT_CORPSECRET` | — | 企业微信 CorpSecret（管理员路径，持久化） |

### 检索参数

| 变量             | 默认值  | 说明         |
| -------------- | ---- | ---------- |
| `VECTOR_TOP_K` | `30` | 向量召回候选数    |
| `BM25_TOP_K`   | `30` | BM25 召回候选数 |
| `FUSION_TOP_K` | `15` | RRF 融合后保留数 |
| `FINAL_TOP_K`  | `5`  | 最终返回数      |
| `RRF_K`        | `60` | RRF 平滑因子   |

### 入库与抽取

| 变量                        | 默认值      | 说明                                        |
| ------------------------- | -------- | ----------------------------------------- |
| `MAX_UPLOAD_SIZE_MB`      | `100`    | 上传文件大小上限（MB）                              |
| `CONTEXT_WINDOW_TOKENS`   | `256000` | LLM 上下文窗口大小（用于计算默认输入上限）                   |
| `MAX_WINDOW_TOKENS`       | `102400` | 单次 LLM 语义抽取的输入 Token 上限（默认 context 的 40%） |
| `EMBEDDING_BATCH_SIZE`    | `100`    | Embedding 批处理大小（与 INDEX_UPSERT_BATCH_SIZE 对齐） |
| `INDEX_UPSERT_BATCH_SIZE` | `100`    | 索引批量写入大小                                  |

### 视觉理解与评测

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `IMAGE_VISION_ENABLED` | `true` | 启用图片视觉理解 |
| `VIDEO_VISION_ENABLED` | `true` | 启用视频视觉理解 |
| `AUTO_EVAL_ENABLED` | `true` | 入库后自动生成评测数据 |
| `AUTO_EVAL_QUERIES_PER_DOC` | `3` | 每文档自动生成评测查询数 |

---

## API 接口

系统当前提供 **27 个活跃 v1 API**，所有 `/api/v1` 接口返回统一的 `{ data, meta, error }` 结构。

### 接口速览

| 分组       | 方法       | 路径                                | 功能                                       |
| -------- | -------- | --------------------------------- | ---------------------------------------- |
| **健康检查** | `GET`    | `/api/v1/health/live`             | 进程存活检查（K8s liveness probe）               |
|          | `GET`    | `/api/v1/health`                  | 整体状态 + 依赖详情（PG/Milvus/MinIO/LLM 四路并行探测）  |
| **文档管理** | `GET`    | `/api/v1/documents`               | 文档分页列表                                   |
|          | `POST`   | `/api/v1/documents`               | 创建文档                                     |
|          | `POST`   | `/api/v1/documents/upload`        | 上传文件并创建文档                                |
|          | `GET`    | `/api/v1/documents/ids`           | 批量获取文档 ID                                |
|          | `GET`    | `/api/v1/documents/{id}`          | 文档详情                                     |
|          | `PATCH`  | `/api/v1/documents/{id}`          | 更新文档元数据                                |
|          | `GET`    | `/api/v1/documents/{id}/elements` | 文档解析元素                                   |
|          | `DELETE` | `/api/v1/documents/{id}`          | 软删除文档                                    |
|          | `POST`   | `/api/v1/documents/{id}/restore`  | 恢复文档                                     |
|          | `POST`   | `/api/v1/documents/{id}/retry`    | 重新入队入库任务                                 |
|          | `GET`    | `/api/v1/documents/{id}/history`  | 文档版本历史                                   |
|          | `POST`   | `/api/v1/documents/batch-delete`  | 批量软删除文档                                  |
|          | `POST`   | `/api/v1/documents/batch-retry`   | 批量重试入库                                   |
|          | `POST`   | `/api/v1/documents/batch-restore` | 批量恢复文档                                   |
| **知识块**  | `GET`    | `/api/v1/chunks`                  | 知识块分页列表                                  |
|          | `POST`   | `/api/v1/chunks`                  | 创建知识块                                    |
|          | `GET`    | `/api/v1/chunks/ids`              | 批量获取知识块 ID                               |
|          | `GET`    | `/api/v1/chunks/{id}`             | 知识块详情                                    |
|          | `PATCH`  | `/api/v1/chunks/{id}`             | 更新知识块                                    |
|          | `DELETE` | `/api/v1/chunks/{id}`             | 软删除知识块                                   |
|          | `POST`   | `/api/v1/chunks/{id}/restore`     | 恢复知识块                                    |
|          | `POST`   | `/api/v1/chunks/batch`            | 批量状态操作                                   |
| **检索**   | `POST`   | `/api/v1/search`                  | 混合检索（Milvus 全链路闭环，过滤/召回/重排均在 Milvus 内完成） |
|          | `GET`    | `/api/v1/search/filters`          | 可用筛选项（分类/知识类型/知识块状态）                     |
| **任务**   | `GET`    | `/api/v1/jobs/{job_id}/stream`    | SSE 实时进度推送（progress/completed/failed 事件） |

详细接口文档见 [API接口汇总.md](API接口汇总.md)。

### 统一错误响应

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

错误码：`DOCUMENT_NOT_FOUND` | `DOCUMENT_DUPLICATE` | `DOCUMENT_VERSION_CONFLICT` | `CHUNK_NOT_FOUND` | `INGEST_JOB_NOT_FOUND` | `INGEST_JOB_CONFLICT` | `VALIDATION_ERROR` | `INTERNAL_ERROR` | `SERVICE_UNAVAILABLE`

---

## 核心模块

### 文档解析器 (parsers/)

支持 6 种文档格式的结构化解析，统一输出 `ParseResult` 模型：

| 解析器                    | 支持格式       | 核心能力                                                          |
| ---------------------- | ---------- | ------------------------------------------------------------- |
| `pdf_parser.py`        | PDF        | PyMuPDF 文本提取、表格检测、图片抽取、层级标题                                   |
| `docx_parser.py`       | Word       | 段落/表格/图片提取、超链接处理、嵌入媒体提取                                       |
| `pptx_parser.py`       | PowerPoint | 幻灯片文本、图片、表格、图表、超链接处理                                      |
| `xlsx_parser.py`       | Excel      | 工作表遍历、合并单元格、表格结构化、超链接处理                                       |
| `html_parser.py`       | HTML       | DOM 解析、标签过滤、语义区块划分                                            |
| `markdown_parser.py`   | Markdown   | 标题层级、代码块、表格、图片引用                                              |

所有解析器通过 `registry.py` 按 `source_type` 手动注册和匹配。`utils.py` 提供链接分类等通用工具。

### 入库管道 (ingestion/pipeline.py)

```
                    文档
                     │
              ┌──────▼──────┐
              │  清理旧产物  │  → 删除旧知识块、元素、资产（幂等）
              └──────┬──────┘
                     │
              ┌──────▼──────┐
              │  格式解析    │  → ParseResult（含元素 + 资产列表）
              └──────┬──────┘
                     │
              ┌──────▼──────┐
              │  资产处理    │  → 图片/视频视觉理解（6 线程并行）+ MinIO 上传
              └──────┬──────┘
                     │
              ┌──────▼──────┐
              │  语义抽取    │  → LLM 知识块划分 + 摘要（分批重叠滑窗）
              └──────┬──────┘
                     │
         ┌───────────┴───────────┐
         │                       │
   ┌─────▼─────┐           ┌─────▼─────┐
   │ HNSW 向量  │           │ BM25 索引  │
   │ (Embedding)│           │ (Tantivy) │
   └───────────┘           └───────────┘
```

	入库时先清理旧知识块、解析元素和资产，再走完整流水线（解析 → 资产处理 → 语义抽取 → 双路索引），保证幂等性。入库任务通过 **Dramatiq + Redis** 异步执行，自动重试、分段进度上报，前端通过 SSE 实时展示进度条。

### 异步任务系统 (app/tasks/)

```
用户上传文件 → 创建文档 + 入库任务 (job)
                         │
                  ┌──────▼──────┐
                  │  FastAPI    │  入队到 Redis
                  │  主进程      │ ──────────────▶  Redis Broker
                  └─────────────┘
                         │
                  ┌──────▼──────┐
                  │  GET /jobs/ │  EventSource 长连接
                  │  {id}/stream│ ◀──────────────  前端 SSE 进度条
                  └─────────────┘
                         │ 每秒轮询 PG
                  ┌──────▼──────────┐
                  │ Dramatiq Worker │  消费队列 → 执行入库
                  │ (Docker 容器)    │  解析→抽取→索引→资产处理
                  └─────────────────┘
```

| 组件 | 文件 | 说明 |
|------|------|------|
| Broker 配置 | `broker.py` | Redis Broker 连接，模块导入时自动初始化 |
| 入库 Actor | `ingest.py` | `ingest_document` 异步任务，分段进度回调，最大重试 3 次，30 分钟硬超时 |
| 任务仓储 | `db/repositories/jobs.py` | `ingest_jobs` 表 CRUD，SSE 端点每秒轮询 |
| SSE 端点 | `api/v1/jobs.py` | `GET /api/v1/jobs/{id}/stream`，推送 progress/completed/failed 事件 |
| Worker 镜像 | `Dockerfile.worker` | Python 3.12-slim，`dramatiq app.tasks --processes 2 --threads 4`，最多 8 并发 |

### 索引层 (indexing/)

双路索引统一存储在 Milvus Collection `knowledge_chunks` 中，单 Collection 同时支持稠密向量和稀疏向量检索：

| 组件 | 实现 | 说明 |
|------|------|------|
| 向量索引 | `milvus_vector.py` | HNSW + COSINE，1024 维稠密向量 |
| BM25 索引 | `milvus_bm25.py` | Milvus 2.5 原生 BM25 Function，Tantivy 引擎 + chinese 分析器 |
| 融合算法 | `fusion.py` | RRF 倒数排序融合 |

Milvus Collection 存储全量标量字段（chunk_id / doc_id / doc_title / title / content / category / knowledge_type / status / source_refs / asset_refs / metadata），检索时直接返回，无需回查 PostgreSQL。

### 检索管道 (retrieval/pipeline.py)

```
用户查询
   │
┌──▼──────────┐
│  查询重写    │  → LLM 优化查询表达（陈述句 + 关键词列表）
└──┬──────────┘
   │
┌──▼──────────┐
│  Embedding  │  → 查询向量化
└──┬──────────┘
   │
┌──▼──────────┐
│  双路并行召回 │  → 向量 (HNSW) + BM25（Milvus 原生），支持可开关
└──┬──────────┘
   │
┌──▼──────────┐
│  RRF 融合   │  → 取 Top 15
└──┬──────────┘
   │
┌──▼──────────┐
│  LLM Rerank │  → 最终排序 Top 5
└──┬──────────┘
   │
   最终结果（含评分明细、高亮片段）
```

- **全链路可开关**：`rewrite` / `hybrid` / `rerank` 三个策略参数独立控制各阶段
- **双路并行召回**：向量 + BM25 在同一请求内通过线程池并行执行，而非串行等待
- **筛选纯 Milvus**：全部过滤（`doc_ids` / `categories` / `knowledge_types` / `chunk_status`）走 Milvus 标量字段表达式，API 层无后置过滤
- **结果始终全量**：`asset_refs`（含预签名 URL）、`source_refs`、`score_components` 始终返回，无需前端传参控制
- **搜索日志**：每次搜索自动写入 `search_logs` 表（查询、策略、召回量、各阶段耗时、状态），异步落库不阻塞响应
- **分阶段计时**：`rewrite_ms` / `embedding_ms` / `search_ms` / `rerank_ms` / `total_ms` 五段耗时记录

### LLM 客户端 (llm/)

- **volcengine_client.py** — 火山引擎 SDK 封装，支持 `chat_json()` 自动重试与 JSON 提取、Embedding 批量向量化、视觉理解
- **semantic_extractor.py** — 将解析元素智能划分为语义知识块，生成标题和内容（分批重叠滑窗策略）
- **prompts.py** — 集中管理所有 LLM 提示词模板
- **query_rewriter.py** — 将用户查询重写为陈述句 + 关键词列表（使用快速模型 mini）
- **reranker.py** — 对融合结果进行深度语义重排序（使用快速模型 mini）

> **双模型策略**：高质量任务（语义抽取）使用 `doubao-seed-2-0-pro`，高频低延迟任务（查询重写、Rerank）使用 `doubao-seed-2-0-mini`，兼顾效果与成本。

### 资产处理 (assets/)

- **minio_store.py** — MinIO 对象存储，基于 SHA-256 内容寻址实现资产去重
- **downloader.py** — HTTP/HTTPS 资源统一下载 + **微信微盘双路径下载**
- **asset_processor.py** — 图片/视频视觉理解（LLM Vision），生成语义描述

#### 资源对外访问

知识块 API 和搜索 API 返回的 `asset_refs` 中直接携带 MinIO 预签名 URL（有效期 1 小时），前端可直接 `<img src="...">` 加载，无需再调下载接口。

```
内部链路                          公网链路（配 MINIO_PUBLIC_ENDPOINT）
minio://kb-assets/xxx.png    →    https://kb.example.com/assets/xxx.png?X-Amz-Signature=...
        ↑                                    ↑
  MinIO 预签名 URL                    Nginx /assets/ → MinIO 验签后返回
```

- **不配公网端点**时 URL 为内部地址（`localhost:9000`），仅本地开发可用
- **配置 `MINIO_PUBLIC_ENDPOINT`**后自动替换 host，外部用户可直接访问，Nginx 反向代理透传到 MinIO

#### 微信微盘下载器

`downloader.py` 内置微信微盘文件下载能力，支持三种路径：

| 路径 | 适用场景 | 鉴权方式 |
|------|----------|----------|
| **企业 API 路径** | 管理员，配置了 `WECHAT_CORPID` + `WECHAT_CORPSECRET` | 企业微信开放 API，access_token 自动刷新 |
| **浏览器自动化路径** | 非管理员 | Playwright 持久化浏览器会话（`~/.kb_wechat_profile/`），首次扫码 |
| **公开分享路径** | 授权类型为 0 的公开分享 | 直接提取分享页面的 `download_url` |

系统自动按优先级尝试：企业 API → 浏览器 Playwright → 公开直链。

### 运维脚本 (scripts/)

- **setup_services.py** — 首次运行初始化：PostgreSQL 建表 + Milvus 建 Collection（HNSW + BM25 索引）+ MinIO 建 Bucket，全部幂等
- **clear_services.py** — 清空所有外部服务数据（不可逆），用于测试环境重置
- **import_folder.py** — 批量文件夹导入，递归扫描嵌套目录，通过 Dramatiq 异步入库
- **_analyze_eval.py** — 评测结果分析工具（来源分布、分桶、抽样）
- **_check_similarity.py** — 跨文档语义相似度检查（采样、Embedding、余弦相似度）

### 并发架构

后端采用**线程池 + 任务队列**双层并发体系：

- **入库任务**：由 Dramatiq Worker（独立 Docker 容器）从 Redis 消费，与 API 主进程完全解耦。子文档链接（document_link）触发的新文档下载也通过 Dramatiq 异步入队，不再占用 API 线程池
- **在线任务**：由 5 个专用线程池处理，多业务线隔离，避免相互争抢

所有线程池由 FastAPI lifespan 统一管理生命周期。

| 池名                  | 线程数 | 用途                         |
| ------------------- | --- | -------------------------- |
| `health_executor`   | 4   | 健康检查（4 路依赖并行探测）            |
| `upload_executor`   | 8   | 文件上传 + MinIO 写入（I/O 密集）    |
| `search_executor`   | 8   | 检索任务隔离（每次搜索内部向量+BM25 双路并行） |
| `asset_worker_pool` | 6   | 资产处理六路并发（图片/视频/链接）         |
| `eval_gen_pool`     | 8   | 评测数据异步生成（入库完成后 LLM 调用）     |

---

## 前端页面

前端为纯 Vanilla JS 单页应用，无框架依赖。采用 Hash 路由、组件化架构。

| 页面 | 路由 | 组件 | 功能 |
|------|------|------|------|
| 仪表盘 | `/` | `dashboard.js` | 系统概览、服务状态、快捷入口 |
| 文档列表 | `/documents` | `documents.js` | 文档分页浏览、上传、筛选、批量操作 |
| 文档详情 | `/documents/:id` | `document-detail.js` | 文档信息、解析元素、知识块列表 |
| 搜索 | `/search` | `search.js` | 混合检索、筛选、结果高亮、调试模式 |
| 知识块 | `/chunks` | `chunks.js` | 知识块浏览、创建、编辑、索引管理 |

**设计系统**：自定义 CSS 设计语言（~68KB），包括色彩体系、间距系统、组件样式（卡片/表格/按钮/Badge/Toast/Modal/Spinner）、响应式布局。

**前端并行策略**：

| 场景 | 策略 | 实现 |
|------|------|------|
| 仪表盘首屏 | 5 路并行 | `Promise.all`（health + 4 个统计查询） |
| 文档详情页 | 3 路并行 | `Promise.all`（文档 + 知识块 + 元素） |
| 搜索 | 单次调用 | 后端内部向量+BM25 双路并行 |

---

## 评测系统

内置于 `evaluation/` 的检索质量评测框架。

### 核心能力

- **自动生成** — 入库完成后后台异步调用 LLM 自动生成评测数据，查询风格多样化（疑问句/关键词/口语片段/陈述句），已累积 **3,109 条标注查询**（覆盖 1,213 个文档）
- **手动合并** — 分文档评测数据手动审核后合并到全局数据集，人工标注受保护
- **多指标评估** — Hit@K（K 可配置）、Recall@K（K 可配置）、MRR
- **参数可控** — 命令行指定 rewrite/rerank/hybrid/top_k，同一数据集不同参数对比
- **结果持久化** — 评测结果 JSONL 追加写入，含检索参数、指标和成功/失败计数

### 快速使用

```bash
cd backend

# 入库完成后，手动合并评测数据到全局集
python ../evaluation/merge_to_global.py <doc_id>

# 运行评测（默认 rewrite=true, rerank=true, top_k=5）
python ../evaluation/run_eval.py

# 自定义参数
python ../evaluation/run_eval.py --no-rewrite --no-rerank --top-k 10
```

详细说明见 [evaluation/README.md](evaluation/README.md)。

---

## CHANGELOG

### v0.5.0 (当前)

- ✅ Dramatiq + Redis 异步任务系统（入库与 API 主进程解耦，自动重试）
- ✅ SSE 实时进度推送（前端 EventSource 长连接，分段进度条）
- ✅ Nginx 反向代理（HTTP/2 前端，SSE 长连接兼容配置，128MB 上传限制）
- ✅ Dramatiq Worker Docker 化（独立容器，2 进程 × 4 线程，最多 8 并发）
- ✅ 微信微盘下载器（企业 API + Playwright 双路径策略，持久化浏览器会话）
- ✅ LLM 双模型策略（pro 高质量任务 + mini 低延迟任务，兼顾效果与成本）
- ✅ 文档批量操作端点（batch-delete / batch-retry / batch-restore，前端 8 并发上限）
- ✅ 快速模型拆分（查询重写和 Rerank 从 pro 切换到 mini）
- ✅ 批量文件夹导入脚本（import_folder.py，Dramatiq 异步入库）
- ✅ 数据库索引优化 + 启动时 stale 文档/任务自动恢复
- ✅ 前端 SSE 进度条 + 多文件上传 + 骨架屏优化

### v0.4.0

- ✅ MinerU PDF 精准解析器（布局分析、阅读顺序、公式识别，自动降级到 PyMuPDF）
- ✅ PPTX/DOCX/XLSX 解析器重构（链接分类、嵌入媒体提取、超链接处理）
- ✅ Milvus 2.5 原生 BM25（Tantivy 引擎 + chinese 分析器，替代 jieba + rank-bm25）
- ✅ 检索链路完全去 PG 化（Milvus 存储全量标量字段，零数据库回查）
- ✅ MinIO 内容寻址存储（SHA-256 哈希去重）
- ✅ Asset 模型重构 + KnowledgeChunk 增加 doc_id 冗余字段
- ✅ 解析器输出格式统一为 ParseResult（含 ParseElement + Asset 列表）
- ✅ 运维脚本（setup_services.py / clear_services.py）
- ✅ 语义抽取分批重叠滑窗策略
- ✅ 检索全链路可独立开关（rewrite / hybrid / rerank）
- ✅ 评测系统增强（指标扩展、参数可控）

### v0.3.0

- ✅ 完成 API v1 完整迁移（28 个活跃接口）
- ✅ 评测数据集自动生成与多维度筛选系统
- ✅ 检索 Debug 模式（各阶段候选可视化）
- ✅ 多模态视觉理解（PDF/PPTX 图片 LLM Vision 描述）
- ✅ 增量入库与乐观锁并发控制
- ✅ 文档去重检测与软删除/恢复
- ✅ 知识块批量操作与索引管理
- ✅ 前端全页面 v1 接口切换

### v0.2.0

- ✅ 混合检索（向量 + BM25 + RRF + LLM Rerank）
- ✅ 多格式文档解析（PDF/DOCX/PPTX/XLSX/HTML/Markdown）
- ✅ Milvus 向量检索 + MinIO 对象存储
- ✅ PostgreSQL 持久化支持

### v0.1.0

- ✅ FastAPI 基础框架
- ✅ 火山引擎 LLM/Embedding 集成
- ✅ 内存向量索引 + BM25 全文检索
- ✅ 文档上传与解析入库基础流程

---

## 许可证

内部项目，未开源。

---

## 相关文档

- [API 接口汇总](API接口汇总.md) — 全部 API 详细说明
- [评测系统 README](evaluation/README.md) — 评测框架详细文档
