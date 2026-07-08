# AI知识库管理中台：成品化开发文档总览

## 1. 项目一句话定位
AI知识库管理中台是企业级AI资产统一治理、注册、检索、调用、评估、审计与复用平台。它不是单纯的文档知识库，也不是Demo式RAG，而是多Agent体系中的公共弹药库、能力注册中心、权限管控中心、版本治理中心和资产沉淀中心。

## 2. 当前业务背景
公司现有以下独立Agent：

- 人事智能体
- 财务智能体
- 团品提报智能体
- 供应链智能体
- 招扶商智能体
- 运营智能体
- 商学院智能体

现状问题：

1. 每个Agent独立维护自己的知识库、工具、Skill、Prompt，出现重复建设。
2. 多个Agent可能对接同一类数据源或工具，但版本、口径、权限、日志不统一。
3. Agent加载工具过多，导致上下文臃肿、成本升高、调用决策不稳定。
4. 多Agent协作时，主控Agent难以动态发现公司已有能力，只能依赖人工硬编码。
5. 企业知识、Prompt、业务经验、SOP、工具能力没有统一资产化沉淀。

## 3. 建设目标
建设一个高度成品化的知识库中台，实现：

- 统一管理知识库、工具、Skill、Prompt、存量Agent等AI资产。
- Agent与能力解耦，Agent只接入一个统一SDK，不预装所有工具。
- 主控Agent可在运行时按任务动态检索、选择、调用授权能力。
- 支持知识版本、权限隔离、调用审计、质量评估、安全管控。
- 支持多Agent协作系统、门店智能体、办公智能体等业务方统一接入。
- 支持从任务产出中沉淀优质知识、话术、案例与Prompt，形成正循环。

## 4. 文档清单

| 文档 | 内容 |
|---|---|
| 00_README_总览.md | 项目总览、模块说明、实施路径 |
| 01_PRD_产品需求文档.md | 产品目标、用户角色、功能需求、验收标准 |
| 02_ARCH_总体技术架构.md | 总体架构、服务划分、技术选型、部署拓扑 |
| 03_CAPABILITY_REGISTRY_能力注册中心.md | 工具、Skill、Prompt、知识库、Agent注册与发现 |
| 04_KNOWLEDGE_RAG_知识资产与RAG治理.md | 文档接入、解析、切分、向量化、检索、召回评估 |
| 05_SKILL_PROMPT_资产化.md | Skill与Prompt模板的设计、版本、发布和复用 |
| 06_AGENT_ACCESS_SDK_接入协议.md | Agent统一SDK、权限、调用、降级和返回规范 |
| 07_PERMISSION_VERSION_AUDIT_权限版本审计.md | RBAC/ABAC、租户隔离、版本管理、审计日志 |
| 08_ADMIN_CONSOLE_管理后台设计.md | 管理端页面、交互、审批流、运营看板 |
| 09_MULTI_AGENT_INTEGRATION_多Agent集成.md | 与主控Agent、多Agent协作系统的集成方式 |
| 10_EVAL_OBSERVABILITY_GUARDRAILS.md | 评估、监控、Tracing、安全护栏和质量闭环 |
| 11_DATA_MODEL_API_SPEC.md | 数据模型、核心表结构、API接口草案 |
| 12_DEPLOYMENT_DEVOPS_SECURITY.md | 部署、环境、CI/CD、安全、备份和容灾 |
| 13_DEVPLAN_CODEX_开发计划.md | Codex任务拆解、里程碑、测试和验收 |
| 14_INFO_CHECKLIST_需补充信息.md | 需要业务方/技术方补充的信息与配置清单 |

## 5. 推荐MVP边界，但按成品化架构设计
第一阶段不要做一次性Demo，而是做可演进的最小生产闭环：

1. 能力注册中心：支持知识库、工具、Skill、Prompt、Agent五类能力注册。
2. 知识资产管理：支持文档上传、解析、切分、Embedding、检索、权限过滤。
3. Agent SDK：提供能力检索、能力调用、结果回传、日志上报。
4. 权限与审计：按Agent、部门、业务线、数据密级控制可见与可调用能力。
5. 多Agent集成：主控Agent通过中台检索能力，动态拆解任务并分派给子Agent。
6. 管理后台：能力目录、知识库管理、Prompt/Skill管理、版本发布、调用日志。

## 6. 推荐技术栈

| 层级 | 推荐 |
|---|---|
| 后端 | Python FastAPI / Java Spring Boot 均可；若与LLM生态深度结合，优先FastAPI |
| 编排 | LangGraph，用于多Agent流程和有状态任务编排 |
| LLM | DeepSeek API、OpenAI兼容Client封装，可预留多模型路由 |
| Embedding | bge-m3 / text-embedding-v3 / 企业私有Embedding模型 |
| 向量库 | Milvus / Qdrant / pgvector；生产推荐Milvus或Qdrant，轻量推荐pgvector |
| 关系库 | PostgreSQL |
| 缓存 | Redis |
| 对象存储 | MinIO / 阿里云OSS / 腾讯云COS |
| 消息队列 | Kafka / RabbitMQ / Redis Stream |
| 搜索 | Elasticsearch / OpenSearch，可与向量检索混合召回 |
| 可观测 | OpenTelemetry + Prometheus + Grafana + Loki/ELK |
| 鉴权 | OAuth2/OIDC + JWT + API Key + 服务间mTLS可选 |
| 部署 | Docker Compose开发，Kubernetes生产 |

## 7. 核心原则

1. 能力与Agent解耦：Agent不绑定全部工具，只绑定统一中台SDK。
2. 所有能力先注册再调用：无注册、无权限、无审计的能力不能被Agent直接调用。
3. 知识库不是文件夹：必须具备来源、版本、权限、切片、召回质量和生命周期管理。
4. Prompt和Skill是资产：要有Owner、版本、适用场景、输入输出、评估集、灰度发布。
5. 多Agent只调用授权能力：主控Agent和子Agent看到的能力列表必须经过权限过滤。
6. 生产系统必须可观测：每次检索、调用、生成、失败、降级都要可追踪。
7. 结果可沉淀：高质量任务产出要经过审核后回流为知识、案例、Skill或Prompt。
