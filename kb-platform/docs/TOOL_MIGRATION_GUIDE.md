# 工具外置化迁移指南

## 概述

本次迁移将原本硬编码在服务代码中的工具实现，完全重构为可注册、可查询、可版本化、可管理的 Tool 资产。

## 迁移内容

### 1. 工具注册框架 (`app/services/tools/__init__.py`)

新增核心组件：

- **`ToolDefinition`**: 完整描述工具的元数据（schema、配置、示例等）
- **`ToolImplementation`**: 工具实现基类，所有工具继承此类
- **`ToolRegistry`**: 工具注册表，支持自动发现和动态加载
- **`create_tool_executor`**: 工厂函数，为 capability 创建执行器

### 2. 重构违禁词检测工具 (`app/services/tools/forbidden_word_check.py`)

**主要改进：**
- ✅ 词表配置外置到 Capability.metadata
- ✅ 支持自定义词表传入
- ✅ 多级别检测（strict/normal/loose）
- ✅ 上下文显示
- ✅ 版本化管理
- ✅ 向后兼容保留 `check_forbidden_words()` 函数

### 3. 能力服务改造 (`app/services/capability_service.py`)

**改进点：**
- 移除硬编码的 `if capability_key == "tool_forbidden_word_check"` 判断
- 通过 `ToolRegistry` 动态查找工具实现
- 支持远程工具端点调用（预留扩展）
- 友好的 STUB 提示

### 4. 技能运行时改造 (`app/services/skill_runtime.py`)

**改进点：**
- 从数据库加载 Capability 来实例化工具
- 支持工作流中的工具动态执行
- 保留向后兼容的回退机制

### 5. 新增工具管理 API (`app/api/v1/tools.py`)

**新增接口：**
- `GET /api/v1/tools/discover` - 发现已注册的工具
- `POST /api/v1/tools/register/{tool_key}` - 注册单个工具
- `POST /api/v1/tools/batch-register` - 批量注册所有工具
- `GET /api/v1/tools/config/{capability_id}` - 获取工具配置
- `PUT /api/v1/tools/config/{capability_id}` - 更新工具配置

### 6. 种子数据更新 (`app/seeds/seed_data.py`)

**改进：**
- 从 `ToolRegistry` 自动获取工具定义
- 合并到 `CAPABILITIES_EXTRA` 列表
- 保留原有示例工具

## 使用指南

### 注册一个新工具

1. 创建工具实现类：

```python
from app.services.tools import ToolDefinition, ToolImplementation

class MyCustomTool(ToolImplementation):
    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            capability_key="tool_my_custom",
            name="我的自定义工具",
            description="工具描述",
            business_domain="my_domain",
            tags=["标签1", "标签2"],
            scenarios=["使用场景1"],
            input_schema={...},
            output_schema={...},
            metadata={"config_key": "config_value"},
        )

    async def execute(self, input_data: dict) -> dict:
        # 工具执行逻辑
        return {"result": "..."}
```

2. 在 `ToolRegistry._load_tools()` 中注册

3. 通过 API 或种子数据注册到 Capability 表

### 更新工具配置（如违禁词表）

通过 API 更新：

```bash
PUT /api/v1/tools/config/{capability_id}
{
    "metadata": {
        "forbidden_words": ["新词1", "新词2"],
        "version": "1.1.0"
    },
    "version": "1.1.0",
    "release_notes": "更新违禁词表"
}
```

### 向后兼容

原有的调用方式继续工作：

```python
# 继续可用
from app.services.tools.forbidden_word_check import check_forbidden_words
result = check_forbidden_words("文本内容")
```

## 架构优势

### 可注册
- 工具实现与元数据定义在一起
- 自动发现机制
- 统一注册流程

### 可查询
- 通过 Capability API 查询所有工具
- 支持标签、业务域筛选
- 完整的元数据描述

### 可版本化
- `CapabilityVersion` 记录每次变更
- 配置更新自动创建版本
- 支持版本回滚

### 可管理
- 工具配置外置到 metadata
- 支持动态更新无需重启
- 权限控制与审计

## 示例调用

### 通过 Capability 调用

```python
# 通过 Capability ID 调用
POST /api/v1/capabilities/{capability_id}/invoke
{
    "input": {
        "text": "待检测文本",
        "check_level": "normal"
    }
}
```

### 在 Skill 中使用

```python
# Skill 可以依赖工具
skill = Skill(
    skill_key="skill_content_moderation",
    dependencies=["tool_forbidden_word_check"],
    ...
)
```

## 未来扩展

- [ ] 工具包自动扫描发现
- [ ] 工具沙箱执行环境
- [ ] 工具性能监控
- [ ] 工具市场/分享机制
- [ ] 可视化工具编排
