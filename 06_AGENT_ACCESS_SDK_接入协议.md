# 06 Agent接入SDK与API设计

## 1. 设计目标
让所有Agent通过统一SDK接入知识库中台，而不是每个Agent分别对接知识库、工具、Skill、Prompt。

Agent侧只需要具备：

1. Agent身份凭证
2. 角色描述
3. 中台SDK
4. 自身专业任务Prompt

## 2. SDK能力

### 2.1 核心方法
```python
client.search_capabilities(task, top_k=10, filters=None)
client.invoke_capability(capability_id, input, context=None)
client.search_knowledge(query, kb_ids=None, top_k=5, filters=None)
client.invoke_skill(skill_id, input, context=None)
client.render_prompt(prompt_id, variables, version=None)
client.report_result(task_id, result, artifacts=None)
client.submit_asset_candidate(asset_type, content, metadata)
```

### 2.2 主控Agent扩展方法
```python
client.discover_agents(task, domain=None)
client.create_collaboration_task(task_spec)
client.report_subtask_result(task_id, subtask_id, result)
```

## 3. Agent认证

### 3.1 Agent注册信息
每个Agent在中台注册后获得：

- agent_id
- client_id
- client_secret 或 API Key
- role_tags
- business_domain
- permission_policy_id

### 3.2 请求头
```http
Authorization: Bearer <jwt>
X-Agent-ID: operation_agent_001
X-Trace-ID: trace_xxx
X-Task-ID: task_xxx
```

## 4. 能力检索API

```http
POST /api/v1/capabilities/search
```

请求：
```json
{
  "task": "生成白佛华宸店直播运营优化方案",
  "agent_id": "master_agent_001",
  "agent_role": "master_agent",
  "top_k": 10,
  "filters": {
    "business_domain": ["operation", "compliance"]
  }
}
```

返回：
```json
{
  "trace_id": "trace_001",
  "capabilities": [
    {
      "capability_id": "kb_store_operation",
      "type": "knowledge_base",
      "name": "门店运营知识库",
      "description": "门店直播、到店引流、会员运营相关知识",
      "score": 0.91,
      "why_recommended": "任务涉及门店直播和引流策略",
      "input_schema": {},
      "version": "1.2.0"
    }
  ],
  "recommended_plan": []
}
```

## 5. 能力调用API

```http
POST /api/v1/capabilities/{capability_id}/invoke
```

请求：
```json
{
  "agent_id": "operation_agent_001",
  "task_id": "task_001",
  "input": {
    "query": "白佛华宸店直播引流策略"
  },
  "context": {
    "trace_id": "trace_001",
    "span_id": "span_002"
  }
}
```

返回：
```json
{
  "success": true,
  "output": {},
  "citations": [],
  "error": null,
  "usage": {
    "latency_ms": 900,
    "tokens": 1200,
    "cost": 0.02
  }
}
```

## 6. 错误码

| 错误码 | 说明 | Agent处理建议 |
|---|---|---|
| 401001 | Agent未认证 | 停止任务，提示接入配置错误 |
| 403001 | 无权限访问能力 | 重新检索替代能力或请求授权 |
| 404001 | 能力不存在 | 重新检索能力 |
| 409001 | 版本冲突 | 使用返回的推荐版本 |
| 422001 | 入参不符合Schema | 修正参数后重试 |
| 429001 | 限流 | 延迟重试 |
| 500001 | 能力执行失败 | 调用备用能力或降级 |
| 504001 | 能力调用超时 | 重试或降级 |

## 7. Agent工具选择策略

### 7.1 不把所有工具塞给Agent
Agent启动时只加载一个通用工具：

```json
{
  "name": "knowledge_middle_platform",
  "description": "用于检索和调用企业中台中的知识库、工具、Skill、Prompt和其他Agent",
  "methods": ["search_capabilities", "invoke_capability"]
}
```

### 7.2 动态能力卡片
中台返回的能力列表以短卡片形式加入Agent上下文。

能力卡片示例：
```text
能力：直播话术生成Skill
用途：根据产品、客群和活动目标生成直播脚本
输入：product_info, customer_profile, duration_minutes
限制：不能生成夸大功效、医疗承诺类话术
```

## 8. 多Agent调用上下文
每次任务必须传递：

- trace_id：全链路追踪
- task_id：任务ID
- parent_task_id：父任务ID
- subtask_id：子任务ID
- caller_agent_id：调用方Agent
- business_context：门店、部门、项目、区域等上下文

## 9. Python SDK草案

```python
from kb_platform_sdk import KBPlatformClient

client = KBPlatformClient(
    base_url="https://kb-platform.company.com",
    agent_id="operation_agent_001",
    api_key="${KB_PLATFORM_API_KEY}"
)

caps = client.search_capabilities(
    task="生成门店直播运营方案，需要引流、脚本和合规审核",
    top_k=5
)

result = client.invoke_capability(
    capability_id="skill_live_script",
    input={
        "product_info": {...},
        "customer_profile": {...},
        "duration_minutes": 60
    }
)
```

## 10. 接入流程

1. Agent Owner提交接入申请。
2. 管理员在中台创建Agent身份。
3. 分配角色标签和权限策略。
4. 生成API Key或Client Credential。
5. Agent集成SDK。
6. 在测试环境验证能力检索和调用。
7. 配置调用限额和监控告警。
8. 发布到生产。

## 11. 成品化要求

- SDK必须支持超时、重试、熔断。
- SDK必须自动携带trace_id。
- SDK不得在日志中打印敏感输入。
- SDK必须支持多环境配置。
- SDK必须支持能力调用失败后的标准错误解析。
