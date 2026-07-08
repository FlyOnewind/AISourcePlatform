# Agent 中台化方案 V1

## 1. 目标与结论

基于当前项目现状，这套系统已经具备做 Agent 中台的良好基础，但更准确地说，它现在还是一套“知识库检索与内容生产系统”，而不是“面向多 Agent 的统一中台”。

现阶段最适合的方向，不是一次性把 Agent、Prompt、Skills、工具、MCP 全部做成重平台，而是先围绕中台的核心职责，把它们抽象成可注册、可复用、可统一接入、可观测、可治理的能力资产，再逐步补齐评测、版本管理和权限治理能力。

Agent 中台的核心职责应收敛为五类：

- 资产注册：有哪些 Agent、Prompt、Tool、Skill、知识库
- 能力复用：不同业务可以复用同一套 Prompt、Tool、知识空间
- 统一接入：业务系统按统一方式调用这些能力
- 运行观测：谁调用了什么、成功还是失败、耗时多少
- 治理能力：版本、权限、评测、下线、回滚

这件事的核心难点不在于 MCP、工具、Skills、Prompt 的封装，而在于知识库本身的维护管理。原因很直接：

- Prompt、Skill、Tool 也会持续更新，也需要版本、发布、灰度、评测和回滚；但相对知识资产，它们通常结构更清晰、边界更稳定，更适合先纳入平台治理。
- 知识库是“持续变化的数据资产”，涉及来源、版本、权限、时效性、质量、评测、回溯、失效处理等一整套治理问题。
- 如果知识库治理没有打稳，Agent 注册得再漂亮，最终也只是把不稳定的数据接给更多 Agent。

因此，这版方案建议采用一个核心原则：

- 统一入口
- 分域治理

也就是：

- 用统一的平台入口管理 Agent、Prompt、Skills、工具、MCP、知识接入关系；
- 但不要把它们当成同一种资产，用一套完全相同的表结构和治理方式硬管。

因此，这版方案建议把中台建设拆成两层：

- 第一层：能力中台
  - 统一注册 Agent、Prompt、Skills、工具、MCP
  - 统一查看运行情况
  - 统一接入知识库
- 第二层：知识治理中台
  - 把知识库从“检索系统”升级为“可维护、可版本化、可评测”的平台资产

## 2. 先讲清两个概念

### 2.1 什么叫“统一管理”

这里的统一管理，不是把 Prompt、Tool、Skill、Knowledge、Run Log 全塞进一张大表，也不是让它们共用完全一样的生命周期。

这里说的统一，指的是：

- 统一注册入口
- 统一查询入口
- 统一绑定关系
- 统一运行观测入口

举例：

- `门店运营助手` 这个 Agent，在平台里可以绑定：
  - 一个默认 Prompt
  - 两个 Tool
  - 一个 Skill
  - 一个知识空间

平台应该能统一看见这套关系，但这些对象本身仍然要分开治理：

- Prompt 关心版本、内容、输入输出 schema
- Tool 关心接口协议、超时、鉴权
- Skill 关心来源、安装方式、入口定义
- Knowledge 关心来源、版本、发布时间、权限、时效性
- Run Log 关心执行过程、耗时、错误、命中内容

所以，合理的统一是“统一入口”，不合理的统一是“统一成一种数据”。

### 2.2 什么叫“Agent 注册”

Agent 注册的本质是：把一个 Agent 从“散落在代码里的实现”变成“平台里可管理的正式对象”。

也就是给 Agent 建档，让平台知道：

- 它是谁
- 它负责什么场景
- 它默认用什么 Prompt
- 它能调用哪些 Tool / Skill / MCP
- 它能访问哪些知识空间
- 它当前是否可用

例如：

- `agent_id`: `store_ops_assistant`
- `name`: `门店运营助手`
- `description`: 回答门店拉新、活动执行、会员运营问题
- `default_prompt`: `store_ops_system_prompt v2`
- `tools`: `kb_search_tool`, `excel_reader_tool`
- `skills`: `campaign_analysis_skill`
- `knowledge_space`: `store_ops_kb`
- `status`: `active`

注册之后，平台才可以：

- 列出当前有哪些 Agent
- 让业务系统按 `agent_id` 调用它
- 控制它的知识和工具访问范围
- 追踪它的运行情况和成功率
- 做版本切换、灰度、下线

## 3. 基于项目现状的判断

当前项目里，已经有几块非常适合复用为中台底座的能力。

### 3.1 已有的知识生产与检索底座

- `backend/ingestion/pipeline.py`
  - 已经打通“文档解析 -> 语义抽取 -> chunk 化 -> 索引 -> 自动生成评测数据”的完整入库链路。
- `backend/app/db/models.py`
  - 已经有 `documents`、`parsed_elements`、`assets`、`knowledge_chunks` 等核心数据模型。
- `backend/app/db/repositories/chunks.py`
  - 已有知识块持久化和按文档/状态/分页查询能力。
- `backend/app/api/v1/search.py`
  - 已经有统一检索入口，并带有搜索日志记录。

这意味着“知识库中心”不需要从零搭建，当前系统本身就可以演进为中台的 Knowledge Plane。

### 3.2 已有的 Prompt 集中管理基础

- `backend/llm/prompts.py`
  - 已经集中管理语义抽取、查询改写、Rerank、视觉理解等提示词。

问题不在“有没有 Prompt”，而在于：

- 目前 Prompt 仍然是代码内常量；
- 缺少版本、发布、灰度、评测、回滚能力；
- 还没有抽象成 Agent 可引用的独立平台资产。

### 3.3 已有的注册模式雏形

- `backend/parsers/registry.py`
  - 已经体现出“能力注册表”的设计模式。
- `backend/app/core/deps.py`
  - 已经在启动期集中装配 parser、index、repo、pipeline 等共享能力。

这说明项目的工程风格已经适合继续往“注册中心 + 运行时装配”方向推进。

### 3.4 已有的运行状态追踪能力

- `backend/app/db/models.py`
  - `DbIngestJob` 已支持异步任务状态跟踪；
  - `DbSearchLog` 已支持搜索日志与阶段耗时记录。
- `backend/app/api/v1/jobs.py`
  - 已支持 SSE 推送任务进度。
- `frontend/js/components/dashboard.js`
  - 已有系统概览页，但目前主要展示文档、知识块、依赖健康状态。

也就是说，“运行情况展示”并不是空白，只是目前追踪对象还是“入库任务”和“检索请求”，尚未扩展到“Agent 运行”。

### 3.5 已有的评测基础设施

- `evaluation/`
  - 已经形成数据生成、人工合并、运行评测、历史记录追加的完整闭环。
- `backend/ingestion/pipeline.py`
  - 入库后会自动触发评测数据生成。

这是一笔很重要的资产。后续不只可以评测知识库检索，还可以扩展到：

- Prompt 评测
- Skill 评测
- Agent 任务完成质量评测

## 4. 中台化总体设计

建议把当前系统演进为“三层结构”。

### 4.1 Knowledge Plane：知识资产层

负责统一管理所有可被 Agent 消费的知识内容。

范围包括：

- 原始文档
- 解析元素
- 资产文件
- 知识块
- 检索索引
- 评测数据集
- 知识版本与状态

这一层继续复用当前项目作为主底座。

### 4.2 Capability Plane：能力注册层

负责统一注册和管理 Agent 可调用的能力对象。

能力对象包括：

- Prompt
- Skill
- Tool
- MCP Server / MCP Tool

核心职责：

- 注册
- 查询
- 版本管理
- 依赖关系管理
- 发布状态管理

### 4.3 Runtime Plane：运行与观测层

负责记录每个 Agent 的实际运行情况。

运行对象包括：

- Agent 定义
- Agent Run
- Run Step
- 调用的 Prompt / Skill / Tool / MCP
- 输入输出摘要
- Token / 时长 / 成功率 / 错误信息
- 产出物与关联知识引用

## 5. 中台的核心对象模型

建议优先抽象以下平台对象。

### 5.1 AgentDefinition

表示一个注册到中台的 Agent。

建议字段：

- `agent_id`
- `name`
- `description`
- `owner`
- `entry_type`
  - 例如 `codex_agent`、`service_agent`
- `status`
  - `draft` / `active` / `deprecated`
- `default_prompt_version_id`
- `default_skill_binding_ids`
- `default_tool_binding_ids`
- `default_kb_scope`
- `metadata`

### 5.2 PromptTemplate / PromptVersion

把当前代码里的 prompt 抽成平台资产。

建议拆成两层：

- `prompt_template`
  - 表示一个逻辑 Prompt，例如“query_rewrite”
- `prompt_version`
  - 表示该 Prompt 的具体版本内容

建议字段：

- `prompt_key`
- `scene`
- `content`
- `input_schema`
- `output_schema`
- `eval_status`
- `version`
- `published_at`

### 5.3 SkillDefinition

统一描述可复用 Skill。

建议字段：

- `skill_id`
- `name`
- `source_type`
  - `local_skill` / `repo_skill` / `builtin_skill`
- `entry_uri`
- `manifest`
- `owner`
- `version`
- `status`

### 5.4 ToolDefinition / MCPDefinition

统一管理工具与 MCP 接入。

建议字段：

- `tool_id`
- `name`
- `tool_type`
  - `http_api` / `python_adapter` / `mcp_tool`
- `server_id`
- `capability_schema`
- `auth_config`
- `timeout_policy`
- `status`
- `version`

### 5.5 AgentRun / AgentRunStep

用于展示 Agent 运行情况。

建议字段：

- `run_id`
- `agent_id`
- `trigger_type`
  - `manual` / `api` / `schedule`
- `status`
  - `queued` / `running` / `completed` / `failed`
- `started_at`
- `ended_at`
- `input_summary`
- `output_summary`
- `error_message`
- `token_usage`
- `cost`
- `latency_ms`

`run_step` 建议记录：

- 使用了哪个 Prompt 版本
- 使用了哪个 Skill / Tool / MCP
- 命中了哪些知识块
- 每一步耗时与结果

### 5.6 KnowledgeAssetVersion

这是后续最关键、也最难的对象。

建议为知识资产补一层平台级版本抽象：

- `knowledge_asset`
  - 文档、FAQ、规则库、操作手册等逻辑资产
- `knowledge_asset_version`
  - 每次入库、修改、审核后的具体版本

这样后面 Agent 才能引用：

- 某个知识空间
- 某个分类
- 某个发布版本
- 某个时间点有效的知识快照

## 6. 为什么知识库治理是核心难点

这一点建议在中台建设里明确作为主线，不要和 Skills / Prompt / Tool 的封装放在同一复杂度上处理。

### 6.1 知识不是静态配置，而是动态资产

Prompt、Skill、Tool 也不是静态配置，它们同样会更新、升级和下线，也需要版本、发布和回滚能力。

但知识库不一样，它除了“会变”之外，还额外叠加了数据资产治理问题：

- 文档不断新增和替换
- 同一知识多版本并存
- 来源不一致
- 内容冲突
- 过期但未失效
- Chunk 切分策略调整后评测集失真
- 不同 Agent 对知识时效性和权限范围要求不同

所以这里真正想强调的不是“Prompt / Skill / Tool 不变”，而是“知识资产的治理维度更多、链路更长、失败成本更高”。

### 6.2 当前项目已经有“知识治理问题”的前兆

从现有实现可以直接看到几个信号：

- 入库后自动生成评测数据，但仍需要人工合并
- 评测时需要过滤失效 chunk
- 文档重入库后需要清理旧数据
- 搜索链路虽然成熟，但平台层还没有“知识发布版本”概念

这说明系统已经不只是“能检索”，而是开始面对“知识如何持续保持可用”的问题了。

### 6.3 真正要解决的是四类治理问题

第一类：来源治理

- 这条知识来自哪份原文
- 谁上传的
- 什么时候生效
- 是否经过审核

第二类：版本治理

- 文档换版后，老 chunk 如何处理
- Prompt/Agent 是否绑定某个知识快照
- 评测数据对应哪个知识版本

第三类：质量治理

- 是否存在重复或冲突知识
- 检索命中率是否下降
- 哪些知识块高频命中但反馈差

第四类：权限治理

- 不同 Agent 是否能访问不同知识空间
- 是否需要按团队、业务线、敏感级别隔离

## 7. 建议的落地路径

建议按“基于已有基础、先收敛底座、再补平台骨架、最后做完善治理”的思路推进，而不是按概念一次铺满。

这套系统现在已经有：

- 知识生产与检索底座
- Prompt 集中管理雏形
- 注册表模式雏形
- 运行日志和任务状态追踪
- 检索评测基础设施

所以分阶段设计的原则应该是：

1. 先把已有知识、Prompt、注册、日志能力收敛成可复用底座
2. 再把平台对象和资产注册体系补齐
3. 再把 Agent 统一调用、运行留痕、知识空间接入打通
4. 最后补评测、版本、发布、权限等治理能力

## 8. 为什么这样划分阶段

这个阶段划分不是按功能类别随手拆，而是按“依赖关系 + 实施风险 + 交付价值”拆。

### 8.1 先收敛底座，再注册

如果不先把当前项目里已经存在的知识检索、Prompt 管理、注册表、日志追踪等能力收敛成稳定底座，后面注册出来的平台对象就会直接耦合到底层实现细节，后续很难演进。

但如果不再进一步把 `Agent / Prompt / Skill / Tool / Knowledge Space` 定义成平台对象，后面运行时也会说不清：

- 这次运行到底用了哪个 Prompt
- 这个 Tool 是不是平台认可的能力
- 这个 Agent 当前绑定了哪个知识范围

所以合理顺序应该是：

- 先收敛底层能力边界
- 再定义平台对象
- 再让平台对象运行

### 8.2 先统一接入与调用留痕，再逐步平台化知识与能力

如果只做注册中心，中台会停留在“资产目录”，还不是“可运行平台”。

因此第二步必须尽快形成统一接入和调用留痕能力，让平台能记录：

- 谁调用了哪个 Agent
- Agent 使用了哪些 Prompt / Tool / Skill / Knowledge Space
- 调用成功还是失败
- 总耗时和错误原因

只有这样，后续无论是知识空间接入，还是 Prompt / Skill / Tool 的版本切换和评测，才有真实调用语义，而不是孤立配置。

### 8.3 知识治理必须做，但要晚于平台骨架稳定

知识库是最难的部分，但如果一开始就做：

- 知识版本
- 发布流
- 权限体系
- 评测基线

项目会迅速变重，而且前面没有平台骨架可以挂这些能力。

而且如果在运行链路、绑定关系、平台对象都还没有稳定时就上重治理，知识治理能力也会缺少明确挂载点。

因此，合理顺序是：

- 先做知识空间接入
- 再做知识质量与版本治理

### 8.4 评测和版本治理必须建立在真实运行数据上

如果没有前面的注册、绑定、运行和知识空间抽象，后面的：

- Prompt 评测
- Agent 质量看板
- 版本回滚

都会变成没有上下文的孤立功能。

所以它们应该放在平台基础稳定之后。

## 9. 对当前项目的具体改造建议

如果就在这个仓库里开始演进，建议优先增加以下模块。

### 9.1 后端模块

建议新增：

- `backend/app/api/v1/platform/agents.py`
- `backend/app/api/v1/platform/prompts.py`
- `backend/app/api/v1/platform/skills.py`
- `backend/app/api/v1/platform/tools.py`
- `backend/app/api/v1/platform/knowledge_spaces.py`
- `backend/app/api/v1/platform/runs.py`

建议新增仓储：

- `backend/app/db/repositories/agent_definitions.py`
- `backend/app/db/repositories/agent_runs.py`
- `backend/app/db/repositories/prompt_assets.py`
- `backend/app/db/repositories/capability_assets.py`
- `backend/app/db/repositories/knowledge_spaces.py`

### 9.2 数据库表

建议新增最小集合：

- `agent_definitions`
- `prompt_templates`
- `prompt_versions`
- `skill_definitions`
- `tool_definitions`
- `knowledge_spaces`
- `agent_runs`
- `agent_run_steps`

后续增量表：

- `agent_prompt_bindings`
- `agent_skill_bindings`
- `agent_tool_bindings`
- `agent_knowledge_bindings`
- `knowledge_space_sources`
- `prompt_evaluations`
- `agent_evaluations`
- `skill_versions`
- `tool_versions`
- `agent_releases`

### 9.3 前端页面

在当前 SPA 上新增：

- Agent 管理
- Prompt 资产管理
- Skills / Tools 资产管理
- Knowledge Space 管理
- Agent 运行监控

现有 `dashboard.js` 可保留为系统总览，但后续可新增平台维度指标：

- 注册 Agent 数
- 最近 24h 运行次数
- 成功率
- 平均耗时
- 高频失败 Prompt / Tool

## 10. 第一阶段最小可落地方案

如果只做第一期，建议不要一上来做全量治理，先做一版最小闭环。

### 10.1 先落的对象

- `agent_definitions`
- `prompt_templates`
- `prompt_versions`
- `skill_definitions`
- `tool_definitions`
- `knowledge_spaces`
- `agent_runs`
- `agent_run_steps`

### 10.2 先支持的能力

- 注册一个 Agent
- 给 Agent 绑定默认 Prompt
- 给 Agent 绑定 Tool / Skill / Knowledge Space
- 触发一次 Agent 运行
- 记录运行过程与结果
- 在前端查看 Agent 列表和运行列表

### 10.3 暂时不要急着做满的部分

第一期先不做：

- Prompt 自动灰度
- Skill 自动安装与依赖处理
- Tool 健康探测矩阵
- Knowledge Release 发布流
- 复杂权限模型

这些都可以后补。第一期只要能证明三件事就够了：

- Agent 能被平台识别
- Agent 能绑定平台资产
- Agent 能被统一调用且过程可追踪

## 11. 分阶段开发方案

下面给出一版基于现有基础、从搭基础开始逐步演进到功能完善中台的六阶段开发方案。每一阶段结束后，都应得到一个可验收、可演示、可继续叠加的结果。

### Phase 0：底座收敛与平台边界

目标：

- 先复用并收敛当前仓库已经存在的底层能力
- 为后续平台对象、API 和运行链路建立稳定依赖边界

开发内容：

- 收敛现有底座能力为内部公共服务
  - 知识入库与检索底座
  - Prompt 提供与加载逻辑
  - 注册表与运行时装配逻辑
  - 搜索日志、任务日志、阶段耗时记录
- 统一底层接口边界
  - 明确“平台层调用什么，不直接感知什么”
  - 避免后续平台 API 直接耦合 parser / index / repo 细节
- 梳理现有数据与对象映射关系
  - 哪些对象直接复用现有表
  - 哪些对象需要新增平台表
  - 哪些日志和状态需要扩展为 Agent Runtime 语义

建议复用：

- `backend/ingestion/pipeline.py` 的入库流水线
- `backend/app/api/v1/search.py` 的统一检索入口
- `backend/llm/prompts.py` 的集中 Prompt 管理雏形
- `backend/parsers/registry.py` 与 `backend/app/core/deps.py` 的注册和装配模式
- `DbIngestJob`、`DbSearchLog`、SSE 任务跟踪能力

阶段完成后会得到：

- 后续平台层不再直接散落依赖底层实现
- 能明确区分“现有底座复用部分”和“平台新增部分”
- 第一阶段到第三阶段有稳定的底层承载面

唯一验收场景：

- 团队能明确说出：当前仓库中哪些能力直接作为中台底座复用，哪些能力需要在平台层重新抽象

### Phase 1：平台对象与资产注册中心

目标：

- 把平台里的核心对象正式纳管
- 让 Agent、Prompt、Skill、Tool、Knowledge Space 从“代码内能力”变成“平台资产”
- 建立统一注册与查询入口

开发内容：

- 定义第一期平台对象与最小字段
  - `Agent`
  - `Prompt`
  - `Skill`
  - `Tool`
  - `Knowledge Space`
  - `Run`
- 数据表
  - `agent_definitions`
  - `prompt_templates`
  - `prompt_versions`
  - `skill_definitions`
  - `tool_definitions`
  - `knowledge_spaces`
- 后端 API
  - Agent 注册、查询、编辑、启停
  - Prompt 注册、版本查询、状态切换
  - Skill / Tool 注册、查询、启停
  - Knowledge Space 创建、查询、编辑
- 前端页面
  - Agent 列表页
  - Prompt 资产页
  - Skill / Tool 资产页
  - Knowledge Space 列表页

基于已有基础的合理性：

- 当前项目已经有大量可复用能力，但缺少平台资产层
- 这一阶段的重点不是重新实现能力，而是补“可管理对象”这一层

阶段完成后会得到：

- 平台可以明确回答“现在有哪些 Agent、Prompt、Skill、Tool、Knowledge Space”
- Agent 和能力资产从代码实现变成平台对象
- 后续运行、评测、发布、权限都有明确挂载点

唯一验收场景：

- 可以在平台里注册一个 `门店运营助手`，并查询到它的基础定义

### Phase 2：统一接入与调用观测

目标：

- 让注册后的 Agent 可以被统一调用
- 让平台能记录一次调用使用了哪些平台资产
- 提前打下最基础的运行观测能力

开发内容：

- 数据表
  - `agent_prompt_bindings`
  - `agent_skill_bindings`
  - `agent_tool_bindings`
  - `agent_knowledge_bindings`
  - `agent_runs`
  - `agent_run_steps`
- 后端 API
  - Agent 统一调用接口
  - Agent 调用记录列表接口
  - Agent 调用记录详情接口
  - Agent 调用步骤接口
- 接入能力
  - 根据 `agent_definition` 装配默认 Prompt / Tool / Skill / Knowledge Space
  - 支持一条最小中台调用链路
    - 接收问题
    - 记录使用的 Prompt
    - 通过 Knowledge Space 调用现有检索能力
    - 返回结果摘要
  - 在每一步写入 `agent_run_steps`
- 基础观测
  - 成功 / 失败
  - 总耗时
  - 使用了哪些 Prompt / Tool
  - 错误原因
- 前端页面
  - Agent 运行列表页
  - Agent 运行详情页

建议复用：

- 复用当前 `DbIngestJob` / `jobs.py` 的运行状态追踪思路
- 复用当前 `DbSearchLog` 的日志落库模式
- 复用当前 `deps.py` 的集中装配思路，演进为平台运行时装配

阶段完成后会得到：

- 一个平台注册后的 Agent 可以被统一调用
- 平台可以追踪“用了什么 Prompt、调了什么 Tool、耗时多久、哪里失败了”
- 中台从“资产目录”升级成“统一接入和观测底座”

唯一验收场景：

- `门店运营助手` 能回答一个问题，并在平台里留下完整 run 记录

### Phase 3：知识空间与能力绑定平台化

目标：

- 把当前知识库从“内部检索实现”升级成“平台知识资产入口”
- 让 Agent 通过知识空间消费知识，而不是直接耦合底层索引
- 让 Prompt / Skill / Tool / Knowledge Space 的绑定关系真正进入平台运行时

开发内容：

- 数据表
  - `knowledge_space_sources`
  - `knowledge_space_agents`
- 后端能力
  - Agent 按 `knowledge_space` 发起检索
  - 支持按分类、来源、状态限制知识范围
  - Agent 不直接感知 Milvus / PG 细节
  - 运行时按绑定关系装配 Prompt / Skill / Tool / Knowledge Space
  - 支持按 Agent 场景隔离默认能力集合
- 前端页面
  - Knowledge Space 详情页
  - 知识空间绑定页
  - Agent 与 Knowledge Space 关系页

建议复用：

- 复用当前 `documents`、`knowledge_chunks`、`search` 体系作为底层知识能力
- 在其上新增空间抽象，而不是重写检索系统

为什么此阶段不做重版本治理：

- 这一阶段先解决“知识怎么接入平台”
- 不急着解决“知识怎么发布和回滚”
- 否则会过早把知识治理做重

阶段完成后会得到：

- 不同 Agent 可以绑定不同知识范围
- 知识库开始具备平台级复用能力
- 后续做权限、版本、发布时有清晰边界

唯一验收场景：

- 两个 Agent 绑定不同知识空间，对同一问题给出不同知识范围结果

### Phase 4：评测与质量治理

目标：

- 回答“平台里的 Agent 跑得好不好”
- 开始把 Prompt、Skill、Tool、知识、Agent 质量纳入可观测范围

开发内容：

- 数据表
  - `prompt_evaluations`
  - `agent_evaluations`
  - `skill_evaluations`
  - `tool_health_snapshots`
  - `knowledge_quality_snapshots`
- 后端能力
  - 复用 `evaluation/` 体系扩展 Prompt / Agent / Skill 评测
  - 对 Agent Run 聚合质量指标
  - 记录成功率、平均耗时、知识命中率、常见失败原因
  - 建立 Tool 健康状态与失败分类统计
- 前端页面
  - Agent 质量看板
  - Prompt 版本效果页
  - Skill / Tool 健康概览页
  - 知识空间质量概览页

建议复用：

- 复用当前 `evaluation/run_eval.py`、`history.jsonl` 的评测闭环思想
- 将“检索评测”扩展为“平台能力评测”

阶段完成后会得到：

- 平台不只知道 Agent 有没有运行，还知道运行质量如何
- Prompt 切换、知识更新开始有量化依据
- 后续版本切换不再只靠人工主观判断

唯一验收场景：

- 能比较两个 Prompt 版本在同一 Agent 下的效果差异

### Phase 5：版本、发布与权限治理

目标：

- 让平台从“能用”升级成“可持续演进、可回滚”
- 把 Prompt / Skill / Tool / Knowledge 的变更和权限纳入治理

开发内容：

- 数据表
  - `knowledge_releases`
  - `skill_versions`
  - `tool_versions`
  - `agent_releases`
  - `change_logs`
  - `permission_policies`
- 后端能力
  - 版本发布状态管理
    - `draft`
    - `active`
    - `deprecated`
  - Agent 绑定指定版本
  - 简单回滚能力
  - 变更记录与审计
  - Agent / 团队 / 业务线维度的知识与工具访问控制
- 前端页面
  - 发布管理页
  - 版本对比页
  - 变更历史页
  - 权限策略页

阶段完成后会得到：

- Prompt 改版、知识更新、Skill 升级都可控
- Agent 的运行结果可以和版本关联
- 中台进入可治理状态，而不是持续堆配置
- 关键能力的访问边界也开始可控

唯一验收场景：

- 能切换 Agent 绑定的 Prompt / Knowledge Release 版本，并在异常时回滚；同时限制不同 Agent 访问不同知识与工具

## 12. 这版方案的优先级判断

建议按下面的优先级做，不建议反过来。

1. 先收敛已有底座，补稳定边界
2. 再建立平台对象与资产注册
3. 再打通统一调用、运行留痕和能力绑定
4. 再抽象知识空间与知识范围接入
5. 然后做评测与质量治理
6. 最后做版本、发布与权限治理

原因是：

- 如果不先收敛已有底座，平台层会直接耦合底层实现，后续很难维护；
- 如果只做能力注册，不做统一调用和留痕，中台会停留在资产目录；
- 如果没有运行数据，评测和版本治理会失去上下文；
- 如果一开始就把知识治理、权限治理、发布治理全部做重，周期会拉得过长；
- 最稳妥的路径是先搭基础，再长骨架，最后把治理能力补全。

## 13. 最终建议

这套项目非常适合作为 Agent 中台的起点，但定位要稍微调整：

- 不是“在知识库系统旁边再搭一个中台”
- 而是“让当前知识库系统演进为 Agent 中台的知识与运行底座”

短期内，建议先把以下目标做成第一版里程碑：

- 现有知识、Prompt、注册、日志能力完成底座收敛
- Agent 可注册
- Prompt / Skill / Tool / MCP 可注册
- Agent Run 可追踪、可展示
- Agent 可绑定知识空间运行

中期再重点攻坚：

- 能力绑定运行时装配
- 知识空间治理
- 知识版本与发布
- Prompt / Skill 评测
- 平台级版本管理

一句话概括这版方案：

先把现有底座收敛成平台基础，再把 Agent 周边能力逐步“纳管”，最后把知识库和能力资产一起升级成“可治理”的平台资产，中台才会真正稳。
