# 02 总体技术架构设计

## 1. 架构目标
知识库中台必须服务于两个方向：

1. 单Agent：让人事、财务、团品、供应链、招扶商、运营、商学院等Agent通过统一入口调用知识、工具、Skill和Prompt。
2. 多Agent协作：让主控Agent能够动态发现能力、拆解任务、调度子Agent，并在执行中统一使用中台能力。

系统必须满足成品化要求：权限、版本、审计、可观测、灰度、容灾、可扩展。

## 2. 总体分层

```text
用户/业务系统/OA/多Agent入口
        |
        v
API Gateway / Auth Gateway
        |
        v
AI知识库中台服务层
  - 能力注册中心 Capability Registry
  - 知识资产服务 Knowledge Service
  - RAG检索服务 Retrieval Service
  - Skill运行服务 Skill Runtime
  - Prompt模板服务 Prompt Service
  - Agent注册与发现 Agent Registry
  - 权限策略服务 Policy Service
  - 审计日志服务 Audit Service
  - 评估与监控服务 Eval & Observability
        |
        v
基础设施层
  - PostgreSQL 元数据
  - Vector DB 向量索引
  - Elasticsearch/OpenSearch 关键词索引
  - Redis 缓存
  - Object Storage 原始文件
  - MQ 异步任务
  - LLM/Embedding Provider
        |
        v
外部系统
  - HR系统
  - 财务系统
  - 商品/团品系统
  - 供应链系统
  - 招商系统
  - 运营系统
  - 学习平台
  - 存量Agent服务
```

## 3. 服务拆分

### 3.1 API Gateway
职责：
- 统一入口
- API Key/JWT/OAuth2鉴权
- 限流
- 访问日志
- 路由到后端服务

### 3.2 Capability Registry Service
职责：
- 统一注册知识库、工具、Skill、Prompt、Agent。
- 提供语义检索、标签检索、权限过滤。
- 维护能力元数据、版本、状态、Owner。

### 3.3 Knowledge Service
职责：
- 知识库、文档、切片、版本、权限管理。
- 文档生命周期：上传、解析、切片、索引、发布、下线。

### 3.4 Retrieval Service
职责：
- 关键词检索、向量检索、混合检索。
- Query Rewrite、Rerank、权限过滤。
- 返回可追溯引用。

### 3.5 Skill Runtime Service
职责：
- 执行标准化Skill。
- 支持Prompt Skill、Tool Skill、Workflow Skill、Agent Skill。
- 控制输入输出Schema、超时、重试、沙箱、日志。

### 3.6 Prompt Service
职责：
- 模板变量管理。
- Prompt版本、灰度、回滚。
- Prompt测试集与效果评分。

### 3.7 Agent Registry Service
职责：
- Agent注册、发现、健康检查、角色标签。
- 支持主控Agent查询可协作的子Agent。

### 3.8 Policy Service
职责：
- RBAC、ABAC权限判定。
- 数据密级与操作权限控制。
- 敏感字段脱敏策略。

### 3.9 Audit & Trace Service
职责：
- 记录检索、调用、生成、发布、审批、异常。
- 支持trace_id串联多Agent任务链路。

### 3.10 Evaluation Service
职责：
- RAG召回评估。
- Skill输出质量评估。
- Prompt版本对比。
- Agent调用成功率、幻觉率、合规率监控。

## 4. 关键调用链路

### 4.1 Agent检索能力
```text
Agent -> SDK -> /capabilities/search -> Gateway鉴权 -> Policy过滤 -> Registry检索 -> 返回授权能力列表
```

### 4.2 Agent调用能力
```text
Agent -> SDK -> /capabilities/{id}/invoke -> 鉴权 -> 权限判断 -> 参数校验 -> 执行器 -> 审计日志 -> 返回结果
```

### 4.3 知识入库
```text
管理员上传文档 -> 对象存储 -> 解析任务入队 -> 文档解析 -> 切片 -> Embedding -> 索引 -> 审核 -> 发布
```

### 4.4 多Agent协作
```text
用户任务 -> 主控Agent -> 中台检索能力 -> 任务拆解 -> 子Agent执行 -> 子Agent调用中台能力 -> 返回子结果 -> 主控整合 -> 中台终检 -> 输出结果 -> 资产沉淀
```

## 5. 推荐技术选型

### 5.1 后端语言
优先推荐Python FastAPI：
- 与LLM、RAG、LangGraph生态适配好。
- 便于快速接入DeepSeek、Embedding、向量库、评估框架。

若公司主技术栈为Java，也可采用：
- Java Spring Boot做平台后台和权限治理。
- Python微服务做RAG、Skill Runtime、多Agent编排。

### 5.2 数据库
- PostgreSQL：元数据、权限、版本、审计索引。
- Vector DB：Milvus/Qdrant/pgvector。
- Elasticsearch/OpenSearch：全文检索。
- Redis：缓存能力检索结果、权限策略、任务状态。
- Object Storage：原始文档、解析结果、附件、导出文件。

### 5.3 模型
- LLM：DeepSeek Chat/Reasoner，预留OpenAI兼容接口。
- Embedding：bge-m3、text-embedding-v3、企业私有Embedding。
- Reranker：bge-reranker、大模型rerank或轻量交叉编码器。

### 5.4 编排
- LangGraph：多Agent流程编排、状态持久化、人审节点。
- Temporal/Celery：异步任务、长任务、重试。

## 6. 部署拓扑

### 开发环境
```text
Docker Compose
- api-server
- worker
- postgres
- redis
- qdrant/pgvector
- minio
- opensearch optional
```

### 生产环境
```text
Kubernetes
- gateway deployment
- registry deployment
- knowledge service deployment
- retrieval service deployment
- skill runtime deployment
- policy service deployment
- worker deployment
- postgres managed service
- vector db cluster
- redis cluster
- object storage
- monitoring stack
```

## 7. 高可用设计

- API服务多副本部署。
- Worker异步任务可水平扩容。
- PostgreSQL主从与定期备份。
- Vector DB按collection分片。
- Redis集群或哨兵。
- MQ保证文档解析、Embedding任务可重试。
- 核心能力调用支持重试、熔断、降级。

## 8. 生产边界
不允许出现以下Demo式设计：

- Agent直接调用数据库或工具，绕过中台权限与审计。
- Prompt写死在代码里，无版本和Owner。
- 知识文档上传后直接可用，无审核和版本。
- RAG结果无来源引用。
- 没有调用日志和trace_id。
- 所有Agent共用超级权限。
- 所有工具一次性塞进Agent上下文。
