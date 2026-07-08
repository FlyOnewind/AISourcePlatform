# 09 与多Agent协作系统集成设计

## 1. 集成目标
多Agent协作系统负责“任务拆解、分派、协作、汇总”，知识库中台负责“能力供给、权限、调用、审计、沉淀”。两者关系如下：

```text
多Agent协作系统 = 项目经理和执行团队
知识库中台 = 公共弹药库 + 能力注册中心 + 质量与权限控制中心
```

## 2. 集成架构

```text
用户任务
  -> 主控Agent
     -> 调用中台能力检索
     -> 生成任务DAG
     -> 发现可协作子Agent
     -> 分派子任务
         -> 子Agent通过SDK调用中台能力
     -> 收集结果
     -> 调用中台终检Skill/合规工具
     -> 输出最终结果
     -> 将优质产出提交中台沉淀
```

## 3. 主控Agent职责

主控Agent不直接处理所有业务细节，主要负责：
- 理解任务目标。
- 调用中台检索可用能力。
- 判断需要哪些领域Agent参与。
- 拆解任务DAG。
- 分派子任务。
- 跟踪子任务状态。
- 整合子结果。
- 发起终检。
- 提交可沉淀资产。

## 4. 子Agent职责

子Agent专注领域任务：
- 人事Agent：排班、人力成本、培训安排、制度解释。
- 财务Agent：预算、ROI、费用规则、财务合规。
- 团品提报Agent：商品提报、价格、毛利、卖点材料。
- 供应链Agent：库存、履约、物流、供应商风险。
- 招扶商Agent：商家招募、扶持政策、招商话术。
- 运营Agent：活动策略、门店运营、直播运营、用户转化。
- 商学院Agent：课程、培训、考试、知识传达。

## 5. 示例任务流程

任务：
“针对白佛华宸店，输出一份直播运营优化方案，要求包含到店引流策略、产品直播脚本、合规审核、人员安排、预算ROI和培训材料。”

### 第一步：主控Agent检索能力
调用：
```http
POST /api/v1/capabilities/search
```

关键词：
- 白佛华宸店
- 直播运营
- 到店引流
- 产品脚本
- 合规审核
- 人员安排
- 预算ROI
- 培训材料

中台返回：
- 门店运营知识库
- 产品知识库
- 直播话术生成Skill
- 违禁词审核Agent
- 客户分层工具
- 财务ROI测算Skill
- 人事排班工具
- 商学院课件生成Skill

### 第二步：主控Agent拆解任务
```json
{
  "task_id": "task_live_optimize_001",
  "subtasks": [
    {
      "subtask_id": "s1",
      "agent_role": "operation_agent",
      "goal": "分析门店直播现状并提出到店引流策略"
    },
    {
      "subtask_id": "s2",
      "agent_role": "product_submission_agent",
      "goal": "确定适合直播的产品池和卖点"
    },
    {
      "subtask_id": "s3",
      "agent_role": "finance_agent",
      "goal": "测算活动预算和ROI"
    },
    {
      "subtask_id": "s4",
      "agent_role": "hr_agent",
      "goal": "生成人员排班和职责分工"
    },
    {
      "subtask_id": "s5",
      "agent_role": "business_school_agent",
      "goal": "生成直播前培训课件大纲"
    },
    {
      "subtask_id": "s6",
      "agent_role": "compliance_or_operation_agent",
      "goal": "进行话术和方案合规审核"
    }
  ]
}
```

### 第三步：子Agent执行
每个子Agent只通过中台SDK获取能力，不预装全部工具。

运营Agent调用：
- 门店运营知识库
- 客户分层分析Skill

团品提报Agent调用：
- 产品知识库
- 毛利测算工具
- 团品提报模板Skill

财务Agent调用：
- ROI测算Skill
- 费用规则知识库

人事Agent调用：
- 排班工具
- 人事制度知识库

商学院Agent调用：
- 课件生成Skill
- 培训知识库

合规Agent或运营Agent调用：
- 违禁词审核Agent
- 合规规则库
- 方案合规校验工具

### 第四步：主控Agent整合
主控Agent收齐结果后：
- 统一格式。
- 去重冲突。
- 补齐引用。
- 生成管理层摘要。
- 生成执行清单。

### 第五步：终检与沉淀
主控Agent再次调用中台：
- 方案合规校验工具
- 输出质量评估Skill
- 知识沉淀接口

## 6. 多Agent任务状态
```json
{
  "task_id": "task_001",
  "status": "running",
  "trace_id": "trace_001",
  "subtasks": [
    {
      "subtask_id": "s1",
      "agent_id": "operation_agent_001",
      "status": "completed",
      "used_capabilities": ["kb_store_operation", "skill_customer_segment"]
    }
  ]
}
```

## 7. 中台给主控Agent的能力推荐
中台可以返回推荐调用顺序，降低Agent选错能力概率：

```json
{
  "recommended_plan": [
    "先检索门店运营知识库",
    "再调用客户分层Skill",
    "再生成直播话术",
    "最后调用合规校验工具"
  ]
}
```

## 8. 失败处理

| 场景 | 策略 |
|---|---|
| 能力调用超时 | SDK自动重试，仍失败则返回备用能力 |
| 子Agent失败 | 主控Agent重新分派或降级 |
| 无权限调用 | 主控Agent重新规划任务或发起授权申请 |
| 检索无结果 | 扩展查询、请求人工补充知识 |
| 合规终检失败 | 回到相关子Agent修改 |

## 9. 成品化要求

- 多Agent任务必须有trace_id。
- 每个子任务必须记录调用了哪些中台能力。
- 主控Agent不得绕过中台直接调用敏感工具。
- 中台必须能展示一次多Agent任务的完整调用链。
- 最终结果中的关键事实必须可追溯到知识来源或工具结果。
