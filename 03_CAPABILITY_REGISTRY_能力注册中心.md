# 03 能力注册中心设计

## 1. 核心定位
能力注册中心是AI知识库中台的核心模块。它负责把企业内部所有可被Agent调用的AI能力统一抽象、注册、发现、授权、调用和审计。

注册对象包括：

1. 知识库 Knowledge Base
2. 工具 Tool
3. Skill
4. Prompt Template
5. 存量Agent Existing Agent
6. Workflow组合能力

## 2. 核心原则

### 2.1 能力与Agent解耦
Agent不再预装全部工具。Agent只保留：

- 角色定位
- 任务执行Prompt
- 中台SDK
- 基础推理能力

所有工具、知识、Skill、Prompt都注册到中台。Agent运行时通过中台检索和调用。

### 2.2 先授权再返回
能力检索不是简单搜索。返回结果必须经过：

1. Agent身份认证
2. 角色权限过滤
3. 数据密级过滤
4. 场景策略过滤
5. 能力状态过滤

### 2.3 能力元数据必须结构化
LLM选择能力依赖能力描述，但生产系统不能只靠自然语言描述。必须提供结构化元数据、输入输出Schema、调用约束和示例。

## 3. 能力类型定义

### 3.1 Knowledge Base
示例：
- 产品知识库
- 门店运营知识库
- 人事制度知识库
- 财务报销规则库
- 供应链SOP库
- 招商话术库
- 商学院课程知识库

能力元数据：
```json
{
  "type": "knowledge_base",
  "name": "门店运营知识库",
  "description": "包含门店直播、到店引流、会员运营、活动复盘等运营知识",
  "tags": ["运营", "门店", "直播", "SOP"],
  "input_schema": {
    "query": "string",
    "top_k": "integer",
    "filters": "object"
  },
  "output_schema": {
    "chunks": "array",
    "citations": "array",
    "confidence": "number"
  },
  "owner": "运营部",
  "security_level": "internal",
  "status": "published"
}
```

### 3.2 Tool
示例：
- 财务预算测算工具
- 供应链库存查询工具
- 客户分层分析工具
- 合规校验工具
- HR排班测算工具

Tool必须定义：
- endpoint
- method
- auth_type
- input_schema
- output_schema
- timeout_ms
- retry_policy
- rate_limit
- side_effect：read_only / write / approval_required

### 3.3 Skill
Skill是可复用业务技能，不只是工具调用。它可以包含Prompt、知识检索、工具调用、模型生成和后处理。

示例：
- 直播话术生成Skill
- 客户异议处理Skill
- 团品提报材料生成Skill
- 供应链风险评估Skill
- 财务ROI测算Skill
- 培训课件大纲生成Skill

Skill类型：
- prompt_skill：纯Prompt模板执行
- rag_skill：检索增强生成
- tool_skill：封装一个或多个工具
- workflow_skill：多步骤流程
- agent_skill：调用存量Agent

### 3.4 Prompt Template
Prompt作为一等资产管理：
- system_prompt
- task_prompt
- critique_prompt
- rewrite_prompt
- guardrail_prompt

每个Prompt必须有：
- 变量定义
- 适用场景
- 适用模型
- 版本
- 评估集
- Owner
- 发布时间

### 3.5 Existing Agent
存量Agent作为能力注册。示例：
- 财务智能体
- 人事智能体
- 供应链智能体
- 运营智能体

注册内容：
- agent_id
- role_description
- supported_tasks
- endpoint
- auth
- input_schema
- output_schema
- sla
- health_check_url

## 4. 能力元数据模型

```json
{
  "capability_id": "cap_live_script_v1",
  "type": "skill",
  "name": "直播话术生成Skill",
  "description": "根据产品卖点、目标客群、直播时长生成合规直播脚本",
  "business_domain": "operation",
  "tags": ["直播", "话术", "门店", "运营"],
  "scenarios": ["门店直播", "团品直播", "商学院培训"],
  "input_schema": {},
  "output_schema": {},
  "examples": [],
  "owner_department": "运营部",
  "owner_user": "张三",
  "security_level": "internal",
  "allowed_agent_roles": ["operation_agent", "business_school_agent", "master_agent"],
  "version": "1.3.0",
  "status": "published",
  "endpoint": "/skills/live-script/invoke",
  "timeout_ms": 30000,
  "retry_policy": {
    "max_retries": 2,
    "backoff_ms": 500
  },
  "created_at": "2026-01-01T00:00:00Z",
  "updated_at": "2026-01-10T00:00:00Z"
}
```

## 5. 能力检索机制

### 5.1 检索输入
```json
{
  "agent_id": "operation_agent_001",
  "agent_role": "operation_agent",
  "task": "针对白佛华宸店输出直播运营优化方案，包含引流策略、产品脚本和合规审核",
  "keywords": ["门店直播", "引流", "脚本", "合规"],
  "business_context": {
    "store": "白佛华宸店",
    "department": "运营部"
  },
  "top_k": 10
}
```

### 5.2 检索流程
```text
任务文本 -> Query Rewrite -> 标签匹配 -> 语义召回 -> 权限过滤 -> 状态过滤 -> Rerank -> 返回推荐能力
```

### 5.3 返回结果
```json
{
  "trace_id": "trace_001",
  "recommended_plan": [
    {
      "step": 1,
      "capability_id": "kb_store_operation",
      "reason": "先检索门店运营知识和历史案例"
    },
    {
      "step": 2,
      "capability_id": "skill_live_script",
      "reason": "基于产品和客群生成直播脚本"
    },
    {
      "step": 3,
      "capability_id": "agent_compliance_review",
      "reason": "最终做合规审核"
    }
  ],
  "capabilities": []
}
```

## 6. 能力调用机制

### 6.1 统一调用接口
```http
POST /api/v1/capabilities/{capability_id}/invoke
```

请求：
```json
{
  "agent_id": "operation_agent_001",
  "task_id": "task_123",
  "input": {
    "query": "白佛华宸店直播引流策略"
  },
  "context": {
    "trace_id": "trace_001",
    "parent_span_id": "span_001"
  }
}
```

返回：
```json
{
  "success": true,
  "capability_id": "kb_store_operation",
  "version": "1.0.2",
  "output": {},
  "citations": [],
  "usage": {
    "latency_ms": 820,
    "tokens": 0
  },
  "trace_id": "trace_001"
}
```

## 7. 能力生命周期

```text
草稿 -> 测试中 -> 待审批 -> 已发布 -> 灰度中 -> 已发布 -> 停用 -> 废弃
```

每次状态变化必须记录：
- 操作人
- 操作时间
- 变更内容
- 变更原因
- 审批单号

## 8. 与各Agent的关系

| Agent | 典型可调用能力 |
|---|---|
| 人事智能体 | 人事制度库、排班工具、绩效规则Skill、培训通知Prompt |
| 财务智能体 | 报销规则库、预算测算工具、ROI Skill、费用合规校验 |
| 团品提报 | 产品知识库、提报模板Skill、毛利测算工具、供应链库存查询 |
| 供应链智能体 | 供应商库、库存查询工具、履约风险评估Skill |
| 招扶商智能体 | 商家画像库、招商话术Skill、合同条款知识库 |
| 运营智能体 | 门店运营库、直播话术Skill、活动复盘模板 |
| 商学院智能体 | 课程知识库、课件生成Skill、测验题生成Skill |
| 主控Agent | 可发现各领域Agent和跨部门组合能力 |

## 9. 成品化要求

- 能力必须有Owner，无Owner不得发布。
- 能力必须有输入输出Schema，无Schema不得被Agent自动调用。
- 涉及写操作的工具必须标记side_effect，并默认需要审批。
- 能力下线前必须分析近30天调用影响。
- 能力变更必须产生版本，不允许直接覆盖生产版本。
