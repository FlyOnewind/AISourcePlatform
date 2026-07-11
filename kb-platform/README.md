# AI知识库管理中台 — V1 本地可运行版

企业级AI资产统一治理、注册、检索、调用、评估、审计与复用平台。本目录是根据 `../` 下的开发文档（00~11）落地的第一版可本地运行代码，目标是跑通文档描述的核心闭环，暂不追求生产部署。

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11+ / FastAPI / SQLAlchemy 2.0 async |
| 数据库 | PostgreSQL 16（Docker） |
| 缓存 | Redis（Docker，当前仅预留，尚未接入限流/缓存逻辑） |
| 向量库 | Qdrant（Docker） |
| 对象存储 | MinIO（Docker） |
| LLM/Embedding | 可插拔 Provider：默认 Mock（无需外网），可切换 OpenAI 兼容接口（如 DeepSeek） |
| 管理后台前端 | 纯静态 HTML/CSS/JS（无构建步骤），挂载于 `/admin` |
| 依赖管理 | uv |

## 目录结构

```
kb-platform/
  app/                    FastAPI 应用
    core/                 配置、数据库、Redis、对象存储、向量库封装
    models/                SQLAlchemy 模型
    schemas/               Pydantic 请求/响应
    api/v1/                 路由：agents / capabilities / knowledge / skills / prompts / audit / health
    services/               业务逻辑：能力检索调用、知识入库检索、Skill执行、Prompt渲染、RBAC/ABAC、审计
      llm/                   LLM Provider 抽象（Mock / OpenAI兼容）
      parsers/                文档解析（txt/md/pdf/docx）
      chunkers/               知识切片
      tools/                  内置示例工具（违禁词检测）
    seeds/                  种子数据脚本
  sdk/kb_platform_sdk/      Agent统一接入SDK
  admin_console/           管理后台静态前端
  scripts/demo_multi_agent.py  多Agent协作Demo（复现文档09门店直播场景）
  tests/                   pytest 测试套件
  docker-compose.yml       postgres/redis/qdrant/minio
  .env.example             环境变量模板
```

## 快速开始

### 1. 安装依赖
```bash
cd kb-platform
uv sync
```

### 2. 准备环境变量
```bash
cp .env.example .env
```
默认 `LLM_PROVIDER=mock`，全部功能（含向量检索、内容生成）使用内置 Mock Provider，**无需任何外部 API Key 即可跑通全部链路**。若要接入真实模型（如 DeepSeek），编辑 `.env`：
```
LLM_PROVIDER=openai_compatible
LLM_API_KEY=sk-xxxx
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

### 3. 启动基础设施
```bash
docker compose up -d
docker compose ps   # 确认 postgres/redis/qdrant/minio 均为 healthy
```

### 4. 灌入种子数据（建表 + 7个业务Agent + master_agent + 示例知识库/Skill/Prompt/Policy）
```bash
uv run python -m app.seeds.seed_data
```
运行后会在控制台打印所有身份的 API Key，并写入 `.local/seed_credentials.json`（已加入 `.gitignore`，不会被提交）。**请妥善保存这些 Key**，demo 脚本会自动从该文件读取。

### 5. 启动服务
```bash
uv run uvicorn app.main:app --reload --port 8010
```
- Swagger 文档：http://localhost:8010/docs
- 管理后台：http://localhost:8010/admin （用种子数据中 `admin` 的 API Key 登录）


### 6. 跑多Agent协作Demo
复现文档09"门店直播运营优化方案"完整链路：主控Agent检索能力 → 拆解任务 → 5个业务Agent并行调用中台能力 → 整合结果 → 合规终检。
```bash
uv run python scripts/demo_multi_agent.py
```
若服务不在默认的 `http://localhost:8000`，用环境变量指定：
```bash
KB_PLATFORM_BASE_URL=http://localhost:8010 uv run python scripts/demo_multi_agent.py
```

### 7. 跑测试
```bash
uv run pytest
```
测试会自动在同一 Postgres 实例上创建/清理独立的 `kbplatform_test` 库。**注意**：完整测试套件中知识库上传/解析类测试较慢（每个测试都会创建全部表+跑完整解析流程，单个约1-2分钟），可用 `-k` 只跑关心的部分，例如：
```bash
uv run pytest tests/test_agents.py tests/test_policy.py   # 无文档解析开销，较快
```

## 已验证的核心链路

- ✅ `POST /api/v1/capabilities/search`：不同 Agent 角色返回不同能力集合（PRD 4.1 验收标准）。
- ✅ `POST /api/v1/capabilities/{id}/invoke`：按能力类型分发（knowledge_base/tool/skill/prompt/agent），带审计日志与耗时统计。
- ✅ 知识库全流程：上传 → 解析（txt/md/pdf/docx）→ 切片 → Embedding → Qdrant索引 → 发布 → 检索（向量+关键词混合，带来源引用）。
- ✅ RBAC/ABAC：`policies` 表驱动，默认拒绝（无匹配策略即拒绝），`master_agent` 默认放行，deny 优先于 allow。
- ✅ 审计日志：`audit_logs` 记录检索/调用/发布，`trace_id` 贯穿整条多Agent协作链路。
- ✅ Agent SDK：`search_capabilities/invoke_capability/search_knowledge/invoke_skill/render_prompt/discover_agents/create_collaboration_task` 等方法，超时+重试+trace透传。
- ✅ 多Agent协作 Demo：完整跑通 `scripts/demo_multi_agent.py`。
- ✅ 管理后台：总览、能力目录、知识库（含上传）、Agent列表、审计日志四个页面。

## 已知限制 / 后续待办

本轮为"先跑通"的 V1，以下能力**明确未实现**，避免造成"看起来做了但没做"的误解：

| 领域 | 未实现内容 | 备注 |
|---|---|---|
| 数据库迁移 | 无 Alembic，仅 `create_all` 建表 | schema 变更需手动处理，生产化时需补齐 |
| 异步任务 | 无 Kafka/RabbitMQ/Celery，文档解析同步执行 | 大文件/高并发场景需要异步队列 |
| 全文检索 | 无 Elasticsearch，用 Qdrant+关键词打分模拟混合检索 | 检索质量弱于专业全文引擎 |
| 鉴权 | 仅 API Key，无 OAuth2/OIDC/JWT/mTLS | 生产环境需要更完整的身份体系 |
| 多Agent编排 | 无 LangGraph，`create_collaboration_task` 只在客户端本地生成任务结构 | demo脚本手工编排子任务，未做真正的DAG调度引擎 |
| 灰度发布 | Capability/Skill/Prompt 有 status 字段但无灰度流量分配逻辑 | 管理后台也未提供灰度配置UI |
| 评估中心 | `/skills/{id}/evaluate` 仅执行测试用例并返回原始输出 | 无自动打分模型、无召回率/幻觉率等指标计算 |
| 知识沉淀 | `submit_asset_candidate` SDK方法仅本地校验，后端无对应接口 | 文档04第11节的沉淀闭环未实现 |
| 审批流 | `ApprovalTicket` 模型存在但无审批节点路由/通知 | 仅单节点人工审批数据结构 |
| 敏感字段脱敏 | 未实现 mask/remove/aggregate 脱敏策略 | 仅通过 security_level 做整块内容的可见性过滤，非字段级脱敏 |
| 管理后台 | 仅总览/能力目录/知识库/Agent/审计5个页面 | Skill调试台、Prompt编辑器、审批中心UI、监控图表均未实现，对应后端API已就绪，可在Swagger中调用 |
| 已知安全模型简化 | 知识检索的 `max_security_level` 目前只区分 `master_agent`/管理员 vs 普通Agent两档 | 未按 Agent 自身业务域匹配对应知识库密级，例如 finance_agent 目前无法检索 confidential 级的财务知识库，需要后续按角色-密级矩阵细化 |

## 环境变量说明

见 `.env.example` 内注释，核心项：
- `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`：切换 Mock 与真实模型。
- `DATABASE_URL` / `REDIS_URL` / `QDRANT_URL` / `OBJECT_STORAGE_*`：对应 docker-compose 中的服务地址，默认值已可直接使用。

## 故障排查

- **502 Bad Gateway（仅在 SDK/demo脚本请求 localhost 时出现）**：Windows 系统代理设置可能劫持 localhost 流量。SDK 已在 `httpx.Client` 中设置 `trust_env=False` 规避，若自行编写 httpx 调用请同样加此参数。
- **`asyncpg.exceptions.InterfaceError: cannot perform operation`（仅测试环境）**：pytest-asyncio 每个测试函数使用独立事件循环，若自行扩展测试引擎配置，务必使用 `NullPool`（见 `tests/conftest.py` 注释）。
- **端口 8000 被占用**：换用 `--port` 参数启动，管理后台/demo脚本通过 `KB_PLATFORM_BASE_URL` 环境变量或浏览器地址栏相应调整。
