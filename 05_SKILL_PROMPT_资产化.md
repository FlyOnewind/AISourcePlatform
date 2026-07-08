# 05 Skill与Prompt资产化设计

## 1. 设计目标
把分散在各Agent内部的Prompt、业务经验、工具组合逻辑沉淀为可复用、可版本、可评估、可授权、可灰度发布的Skill和Prompt资产。

## 2. Skill定义
Skill是面向业务目标的可复用能力单元，它可以包含：

- Prompt模板
- 知识检索
- 工具调用
- 模型生成
- 规则校验
- 后处理逻辑
- 审批或人工确认

Skill不是单个函数，也不是单个Prompt，而是可被Agent调用的标准业务能力。

## 3. Skill类型

| 类型 | 说明 | 示例 |
|---|---|---|
| Prompt Skill | 纯Prompt模板生成 | 直播标题生成 |
| RAG Skill | 检索知识后生成 | 产品卖点总结 |
| Tool Skill | 封装工具调用 | 预算测算 |
| Workflow Skill | 多步骤组合 | 团品提报材料生成 |
| Agent Skill | 调用存量Agent | 违禁词审核智能体 |

## 4. Skill元数据

```json
{
  "skill_id": "skill_live_script",
  "name": "直播话术生成Skill",
  "description": "根据产品、目标客群、活动目标生成直播脚本",
  "type": "workflow_skill",
  "business_domain": "operation",
  "input_schema": {
    "product_info": "object",
    "customer_profile": "object",
    "duration_minutes": "integer",
    "compliance_level": "string"
  },
  "output_schema": {
    "script": "string",
    "risk_notes": "array",
    "recommended_actions": "array"
  },
  "dependencies": ["kb_product", "kb_compliance", "tool_forbidden_word_check"],
  "allowed_agent_roles": ["operation_agent", "business_school_agent", "master_agent"],
  "version": "1.0.0",
  "status": "published"
}
```

## 5. Skill执行流程

```text
Agent调用Skill -> 参数校验 -> 权限校验 -> 加载Skill版本 -> 执行依赖能力 -> 调用模型 -> 后处理 -> 质量检查 -> 返回结构化结果 -> 记录日志
```

## 6. Prompt资产化

### 6.1 Prompt模板字段
```json
{
  "prompt_id": "prompt_live_script_v1",
  "name": "直播脚本生成Prompt",
  "template": "你是资深门店直播运营专家... 产品信息：{{product_info}} 客群：{{customer_profile}}",
  "variables": [
    {
      "name": "product_info",
      "type": "object",
      "required": true
    },
    {
      "name": "customer_profile",
      "type": "object",
      "required": true
    }
  ],
  "model_config": {
    "model": "deepseek-chat",
    "temperature": 0.4
  },
  "version": "1.2.0",
  "owner": "运营部"
}
```

### 6.2 Prompt生命周期
```text
草稿 -> 测试 -> 评估 -> 待审批 -> 灰度 -> 全量发布 -> 回滚/下线
```

### 6.3 Prompt版本策略
- 大改：主版本号增加，如1.0.0到2.0.0。
- 兼容性增强：次版本号增加，如1.0.0到1.1.0。
- 文案微调：补丁版本号增加，如1.1.0到1.1.1。

## 7. Skill发布审批
高风险Skill必须审批：
- 财务预算类
- 合同条款类
- 对外营销合规类
- 写入业务系统类
- 涉及员工信息类

审批信息：
- 变更说明
- 影响Agent
- 回滚方案
- 测试报告
- 风险等级

## 8. Skill灰度
支持按以下维度灰度：
- Agent ID
- Agent角色
- 部门
- 门店区域
- 流量比例
- 任务类型

灰度指标：
- 成功率
- 平均耗时
- 成本
- 用户采纳率
- 合规通过率
- 人工修改率

## 9. Skill评估
每个核心Skill都应配置评估集。

示例：直播话术Skill评估维度：
- 产品信息完整性
- 客群匹配度
- 转化话术质量
- 合规风险
- 可执行性
- 结构完整性

## 10. Skill复用案例

### 10.1 直播话术生成Skill
可调用方：
- 运营智能体：生成门店直播脚本。
- 商学院智能体：生成直播培训案例。
- 多Agent主控Agent：作为复杂运营方案中的子能力。

### 10.2 ROI测算Skill
可调用方：
- 财务智能体：预算评估。
- 团品提报Agent：提报材料中的收益测算。
- 运营智能体：活动复盘。

### 10.3 供应链风险评估Skill
可调用方：
- 供应链智能体。
- 团品提报Agent。
- 主控Agent跨部门方案生成流程。

## 11. 成品化约束

- Skill不得直接散落在Agent代码中。
- Prompt不得无版本发布。
- Skill必须有输入输出Schema。
- 高风险Skill必须有评估集和审批。
- Skill调用必须记录版本号。
- Skill依赖能力发生变化时必须触发影响分析。
