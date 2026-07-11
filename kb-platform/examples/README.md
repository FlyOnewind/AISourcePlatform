# 能力注册示例

本目录包含了将智能体能力注册到中台的示例代码。

## 注册架构

```
外部智能体（运营/财务/商学院）
       ↓
   注册能力
       ↓
   中台Capability Registry
       ↓
   其他智能体调用
```

## 快速开始

### 1. 启动中台服务

```bash
cd /path/to/kb-platform
docker-compose up -d
uvicorn app.main:app --reload --port 8000
```

### 2. 注册运营智能体能力

```bash
cd examples
python register_operation_agent.py
```

这将注册：
- 📚 kb_store_operation - 门店运营知识库
- 📚 kb_live_operation - 直播运营知识库  
- 🔧 tool_customer_segment - 客户分层分析工具
- 🔧 tool_metric_calc - 活动指标计算工具
- ⚡ skill_live_script_generator - 直播话术生成技能
- 💬 prompt_store_diagnosis - 门店运营诊断提示词
- 🤖 agent_operation - 运营方案生成能力

### 3. 注册财务智能体能力

```bash
python register_finance_agent.py
```

这将注册：
- 🔧 tool_finance_roi_calc - 财务ROI计算工具（高风险，需要审计）

### 4. 使用前端管理

打开 `admin_console/index.html` 可以：
- 全局搜索能力
- 查看详情（格式化展示）
- 发布/禁用能力
- 配置权限

## 能力类型

| 类型 | 说明 |
|------|------|
| knowledge_base | 知识库 |
| tool | 工具 |
| skill | 技能 |
| prompt | 提示词 |
| agent | Agent综合能力 |
| workflow | 工作流 |

## 权限配置

### 权限类型

- `read` - 读取能力信息
- `invoke` - 调用能力
- `manage` - 管理能力

### 权限条件

```python
conditions = {
    "requires_audit": True,  # 需要审计
    "min_security_level": "internal"  # 最小密级
}
```

### 权限授予对象类型

- `agent` - 特定Agent
- `user` - 特定用户
- `role` - 角色
- `department` - 部门

## 使用示例

### 前端搜索

```javascript
// 全局搜索
performGlobalSearch("直播话术");

// 查看详情
showCapabilityDetailPage(capabilityId);

// 发布能力
publishCurrentCapability();
```

### SDK调用（示例）

```python
from kb_platform_sdk import PlatformClient

client = PlatformClient(api_key="your-key")

# 搜索能力
results = client.search("ROI计算")

# 调用能力
output = client.invoke(
    capability_key="tool_finance_roi_calc",
    input={
        "budget": 100000,
        "expected_sales": 150000,
        "gross_margin_rate": 0.4
    }
)
```

## 安全级别

| 级别 | 说明 |
|------|------|
| public | 公开，所有人可用 |
| internal | 内部，内部员工可用 |
| confidential | 机密，敏感数据需要权限 |
| restricted | 受限，严格控制访问 |

## 副作用类型

| 类型 | 说明 |
|------|------|
| read_only | 只读，无副作用 |
| write | 写操作，会修改数据 |
| approval_required | 需要审批 |

## 批量注册

你可以使用能力注册向导页面进行批量注册，或编写自定义脚本参考示例格式。

## 最佳实践

1. **能力粒度** - 保持能力单一职责
2. **输入输出Schema** - 提供清晰的Schema定义
3. **示例** - 添加使用示例便于理解
4. **标签** - 使用标签分类能力
5. **权限** - 根据业务需要设置合适的权限
6. **审计** - 高风险操作需要审计

## 常见问题

Q: 注册失败提示 capability_key 已存在？
A: 说明该Key已经被注册，使用不同的Key或删除已有的能力。

Q: 如何更新已注册的能力？
A: 使用 PUT /api/v1/capabilities/{id} API，或在前端管理页面更新。

Q: 如何删除能力？
A: 目前能力只能设置为禁用状态，这样可以保留历史调用记录。
