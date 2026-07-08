# 07 权限、版本与审计治理设计

## 1. 治理目标
知识库中台统一管理企业AI资产，必须解决三个核心问题：

1. 谁可以看见什么能力。
2. 谁可以调用什么能力。
3. 调用了什么、用了哪个版本、产生了什么结果。

## 2. 权限模型

### 2.1 RBAC角色权限
基础角色：
- platform_admin
- knowledge_admin
- capability_admin
- security_admin
- agent_owner
- agent_runtime
- auditor

Agent角色：
- hr_agent
- finance_agent
- product_submission_agent
- supply_chain_agent
- merchant_agent
- operation_agent
- business_school_agent
- master_agent

### 2.2 ABAC属性权限
属性包括：
- agent_role
- department
- business_domain
- region
- store_id
- data_security_level
- task_type
- operation_type
- environment

示例策略：
```json
{
  "policy_id": "policy_finance_budget_read",
  "effect": "allow",
  "subject": {
    "agent_role": ["finance_agent", "master_agent"]
  },
  "resource": {
    "capability_type": "tool",
    "business_domain": "finance",
    "security_level": ["internal", "confidential"]
  },
  "action": ["search", "invoke"],
  "condition": {
    "task_type": ["budget_analysis", "roi_estimation"]
  }
}
```

## 3. 数据密级

| 密级 | 说明 | 示例 |
|---|---|---|
| public | 企业内公开 | 通用FAQ |
| internal | 内部可见 | 运营SOP |
| confidential | 部门敏感 | 财务预算、供应商价格 |
| restricted | 严格受限 | 员工薪资、合同底价、个人身份信息 |

## 4. 操作权限

| 操作 | 说明 |
|---|---|
| search | 能力或知识可被检索到 |
| invoke | 能力可被调用 |
| read | 查看详情 |
| create | 创建资产 |
| update | 编辑资产 |
| publish | 发布资产 |
| approve | 审批资产 |
| delete | 删除资产 |
| export | 导出资产 |

## 5. 版本管理

### 5.1 版本对象
需要版本化的对象：
- 知识库
- 文档
- 知识切片
- Prompt
- Skill
- Tool Schema
- Agent注册元数据
- 权限策略

### 5.2 发布模式
- 草稿版本：仅Owner可见。
- 测试版本：测试Agent可调用。
- 灰度版本：部分Agent或部分流量可用。
- 生产版本：默认可用。
- 历史版本：可回滚，不可默认调用。

### 5.3 版本选择
Agent调用能力时可指定：
- latest：最新生产版本。
- stable：稳定版本。
- exact：指定版本。
- canary：灰度版本。

## 6. 审批流

### 6.1 需要审批的操作
- 发布高风险Skill。
- 发布财务、人事、合同、合规知识。
- 变更敏感工具权限。
- 授权跨部门Agent访问。
- 删除生产知识库。
- 上线写操作工具。

### 6.2 审批节点
```text
提交人 -> Owner审核 -> 安全/合规审核 -> 平台管理员发布
```

## 7. 审计日志

### 7.1 记录范围
- 登录
- 能力检索
- 能力调用
- 知识检索
- 文档上传
- 文档发布
- Skill发布
- Prompt变更
- 权限变更
- 审批操作
- 数据导出
- 异常调用

### 7.2 审计字段
```json
{
  "audit_id": "audit_001",
  "trace_id": "trace_001",
  "actor_type": "agent",
  "actor_id": "operation_agent_001",
  "action": "invoke_capability",
  "resource_type": "skill",
  "resource_id": "skill_live_script",
  "resource_version": "1.2.0",
  "decision": "allow",
  "input_digest": "hash_xxx",
  "output_digest": "hash_yyy",
  "latency_ms": 1200,
  "created_at": "2026-01-01T00:00:00Z"
}
```

## 8. 脱敏策略

敏感字段：
- 手机号
- 身份证
- 银行卡
- 员工薪资
- 合同金额
- 供应商底价
- 客户个人信息

脱敏模式：
- mask：部分隐藏。
- remove：完全移除。
- aggregate：只返回统计结果。
- deny：拒绝访问。

## 9. 越权防护

- 能力检索阶段不返回无权能力。
- 能力调用阶段再次校验权限。
- Tool内部执行前校验数据范围。
- 返回结果进行脱敏过滤。
- 异常高频调用触发告警。

## 10. 成品化要求

- 审计日志不可由普通管理员删除。
- 权限策略变更必须可追溯。
- 敏感能力调用必须保留输入输出摘要。
- 版本回滚不能丢失历史调用记录。
- 所有生产发布必须可回滚。
