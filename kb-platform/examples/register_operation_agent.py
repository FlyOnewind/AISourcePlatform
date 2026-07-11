"""
示例：运营智能体能力注册
演示如何将运营智能体的知识库、工具、技能等注册到中台
"""
import requests
import json
from typing import Dict, List, Any

# 中台服务配置
PLATFORM_BASE_URL = "http://localhost:8000/api/v1"
API_KEY = "your-admin-api-key"  # 从环境变量或配置获取

# 请求头
headers = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json"
}


def register_knowledge_base(
    kb_key: str,
    name: str,
    description: str,
    business_domain: str = "retail",
    tags: List[str] = None,
    scenarios: List[str] = None,
    owner_department: str = "运营部",
    security_level: str = "internal"
) -> Dict[str, Any]:
    """
    注册知识库到中台
    """
    data = {
        "capability_key": kb_key,
        "type": "knowledge_base",
        "name": name,
        "description": description,
        "business_domain": business_domain,
        "tags": tags or [],
        "scenarios": scenarios or [],
        "owner_department": owner_department,
        "security_level": security_level,
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "查询内容"},
                "top_k": {"type": "integer", "default": 5, "description": "返回结果数量"}
            },
            "required": ["query"]
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "results": {"type": "array", "description": "检索结果列表"},
                "total": {"type": "integer", "description": "总结果数"}
            }
        }
    }

    response = requests.post(
        f"{PLATFORM_BASE_URL}/capabilities",
        headers=headers,
        json=data
    )
    response.raise_for_status()
    result = response.json()

    if result.get("success"):
        print(f"✅ 知识库 '{name}' 注册成功")
        return result["data"]
    else:
        print(f"❌ 知识库 '{name}' 注册失败: {result.get('error')}")
        return None


def register_tool(
    tool_key: str,
    name: str,
    description: str,
    endpoint: str,
    business_domain: str = "retail",
    tags: List[str] = None,
    scenarios: List[str] = None,
    owner_department: str = "运营部",
    input_schema: Dict[str, Any] = None,
    output_schema: Dict[str, Any] = None,
    security_level: str = "internal",
    side_effect: str = "read_only"
) -> Dict[str, Any]:
    """
    注册工具到中台
    """
    data = {
        "capability_key": tool_key,
        "type": "tool",
        "name": name,
        "description": description,
        "endpoint": endpoint,
        "business_domain": business_domain,
        "tags": tags or [],
        "scenarios": scenarios or [],
        "owner_department": owner_department,
        "security_level": security_level,
        "side_effect": side_effect,
        "input_schema": input_schema or {
            "type": "object",
            "properties": {}
        },
        "output_schema": output_schema or {
            "type": "object",
            "properties": {}
        }
    }

    response = requests.post(
        f"{PLATFORM_BASE_URL}/capabilities",
        headers=headers,
        json=data
    )
    response.raise_for_status()
    result = response.json()

    if result.get("success"):
        print(f"✅ 工具 '{name}' 注册成功")
        return result["data"]
    else:
        print(f"❌ 工具 '{name}' 注册失败: {result.get('error')}")
        return None


def register_skill(
    skill_key: str,
    name: str,
    description: str,
    prompt_key: str = None,
    business_domain: str = "retail",
    tags: List[str] = None,
    scenarios: List[str] = None,
    owner_department: str = "运营部",
    input_schema: Dict[str, Any] = None,
    output_schema: Dict[str, Any] = None,
    security_level: str = "internal"
) -> Dict[str, Any]:
    """
    注册技能到中台
    """
    data = {
        "capability_key": skill_key,
        "type": "skill",
        "name": name,
        "description": description,
        "business_domain": business_domain,
        "tags": tags or [],
        "scenarios": scenarios or [],
        "owner_department": owner_department,
        "security_level": security_level,
        "prompt_key": prompt_key,
        "input_schema": input_schema or {
            "type": "object",
            "properties": {}
        },
        "output_schema": output_schema or {
            "type": "object",
            "properties": {}
        }
    }

    response = requests.post(
        f"{PLATFORM_BASE_URL}/capabilities",
        headers=headers,
        json=data
    )
    response.raise_for_status()
    result = response.json()

    if result.get("success"):
        print(f"✅ 技能 '{name}' 注册成功")
        return result["data"]
    else:
        print(f"❌ 技能 '{name}' 注册失败: {result.get('error')}")
        return None


def register_prompt(
    prompt_key: str,
    name: str,
    description: str,
    template: str,
    variables: List[str] = None,
    business_domain: str = "retail",
    tags: List[str] = None,
    owner_department: str = "运营部",
    security_level: str = "internal"
) -> Dict[str, Any]:
    """
    注册提示词模板到中台
    """
    data = {
        "capability_key": prompt_key,
        "type": "prompt",
        "name": name,
        "description": description,
        "business_domain": business_domain,
        "tags": tags or [],
        "owner_department": owner_department,
        "security_level": security_level,
        "input_schema": {
            "type": "object",
            "properties": {
                var: {"type": "string"}
                for var in variables or []
            },
            "required": variables or []
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "完整的提示词内容"}
            }
        },
        "examples": [],
        "metadata": {
            "template": template
        }
    }

    response = requests.post(
        f"{PLATFORM_BASE_URL}/prompts",
        headers=headers,
        json={
            "prompt_key": prompt_key,
            "name": name,
            "template": template,
            "variables": variables or [],
            "status": "draft"
        }
    )
    response.raise_for_status()
    result = response.json()

    if result.get("success"):
        print(f"✅ 提示词 '{name}' 注册成功")
        return result["data"]
    else:
        print(f"❌ 提示词 '{name}' 注册失败: {result.get('error')}")
        return None


def register_agent_capability(
    agent_key: str,
    name: str,
    description: str,
    business_domain: str = "retail",
    tags: List[str] = None,
    scenarios: List[str] = None,
    owner_department: str = "运营部",
    security_level: str = "internal"
) -> Dict[str, Any]:
    """
    注册智能体综合能力到中台
    """
    data = {
        "capability_key": agent_key,
        "type": "agent",
        "name": name,
        "description": description,
        "business_domain": business_domain,
        "tags": tags or [],
        "scenarios": scenarios or [],
        "owner_department": owner_department,
        "security_level": security_level,
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "任务描述"},
                "context": {"type": "object", "description": "上下文信息"}
            },
            "required": ["task"]
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "response": {"type": "string", "description": "智能体响应"},
                "steps": {"type": "array", "description": "执行步骤"}
            }
        }
    }

    response = requests.post(
        f"{PLATFORM_BASE_URL}/capabilities",
        headers=headers,
        json=data
    )
    response.raise_for_status()
    result = response.json()

    if result.get("success"):
        print(f"✅ Agent能力 '{name}' 注册成功")
        return result["data"]
    else:
        print(f"❌ Agent能力 '{name}' 注册失败: {result.get('error')}")
        return None


def register_permission(
    capability_id: str,
    subject_type: str,
    subject_code: str,
    permission: str = "invoke",
    requires_audit: bool = False
) -> Dict[str, Any]:
    """
    注册能力权限
    """
    data = {
        "subject_type": subject_type,
        "subject_code": subject_code,
        "permission": permission,
        "conditions": {
            "requires_audit": requires_audit
        },
        "status": "active"
    }

    response = requests.post(
        f"{PLATFORM_BASE_URL}/capabilities/{capability_id}/permissions",
        headers=headers,
        json=data
    )
    response.raise_for_status()
    result = response.json()

    if result.get("success"):
        print(f"✅ 权限 '{subject_type}:{subject_code}' 配置成功")
        return result["data"]
    else:
        print(f"❌ 权限配置失败: {result.get('error')}")
        return None


def register_operation_agent_capabilities():
    """
    注册运营智能体的所有能力
    """
    print("=" * 60)
    print("🚀 开始注册运营智能体能力到中台")
    print("=" * 60)

    capabilities = []

    # 1. 注册知识库
    print("\n📚 注册知识库...")
    kb1 = register_knowledge_base(
        kb_key="kb_store_operation",
        name="门店运营知识库",
        description="包含门店运营指南、活动方案、销售技巧等知识",
        business_domain="retail",
        tags=["门店", "运营", "销售"],
        scenarios=["门店运营", "活动策划", "销售培训"]
    )
    if kb1:
        capabilities.append(kb1)

    kb2 = register_knowledge_base(
        kb_key="kb_live_operation",
        name="直播运营知识库",
        description="包含直播流程、话术、场控等直播运营知识",
        business_domain="live",
        tags=["直播", "话术", "场控"],
        scenarios=["直播策划", "话术生成"]
    )
    if kb2:
        capabilities.append(kb2)

    # 2. 注册工具
    print("\n🔧 注册工具...")
    tool1 = register_tool(
        tool_key="tool_customer_segment",
        name="客户分层分析工具",
        description="根据客户消费数据进行分层分析",
        endpoint="http://localhost:8030/tools/customer-segment",
        business_domain="retail",
        tags=["客户", "分层", "分析"],
        scenarios=["客户画像", "营销策略"],
        input_schema={
            "type": "object",
            "properties": {
                "customer_ids": {"type": "array", "items": {"type": "string"}, "description": "客户ID列表"},
                "start_date": {"type": "string", "description": "开始日期"},
                "end_date": {"type": "string", "description": "结束日期"}
            },
            "required": ["customer_ids"]
        },
        output_schema={
            "type": "object",
            "properties": {
                "segments": {"type": "array", "description": "客户分层结果"},
                "summary": {"type": "string", "description": "分析摘要"}
            }
        }
    )
    if tool1:
        capabilities.append(tool1)

    tool2 = register_tool(
        tool_key="tool_metric_calc",
        name="活动指标计算工具",
        description="计算直播活动的各项KPI指标",
        endpoint="http://localhost:8030/tools/metric-calc",
        business_domain="live",
        tags=["指标", "KPI", "分析"],
        scenarios=["活动分析", "效果评估"],
        input_schema={
            "type": "object",
            "properties": {
                "activity_id": {"type": "string", "description": "活动ID"},
                "metrics": {"type": "array", "items": {"type": "string"}, "description": "需要计算的指标"}
            },
            "required": ["activity_id"]
        },
        output_schema={
            "type": "object",
            "properties": {
                "results": {"type": "object", "description": "指标结果"},
                "summary": {"type": "string", "description": "总结"}
            }
        }
    )
    if tool2:
        capabilities.append(tool2)

    # 3. 注册技能
    print("\n⚡ 注册技能...")
    skill1 = register_skill(
        skill_key="skill_live_script_generator",
        name="直播话术生成技能",
        description="根据产品特点生成直播话术",
        business_domain="live",
        tags=["话术", "直播", "文案"],
        scenarios=["直播准备", "文案生成"],
        input_schema={
            "type": "object",
            "properties": {
                "product_name": {"type": "string", "description": "产品名称"},
                "product_features": {"type": "array", "items": {"type": "string"}, "description": "产品特点"},
                "target_audience": {"type": "string", "description": "目标受众"},
                "duration": {"type": "integer", "description": "预计时长（分钟）"}
            },
            "required": ["product_name", "product_features"]
        },
        output_schema={
            "type": "object",
            "properties": {
                "opening": {"type": "string", "description": "开场话术"},
                "introduction": {"type": "string", "description": "产品介绍"},
                "interaction": {"type": "string", "description": "互动环节"},
                "closing": {"type": "string", "description": "结束话术"}
            }
        }
    )
    if skill1:
        capabilities.append(skill1)

    # 4. 注册提示词
    print("\n💬 注册提示词模板...")
    prompt1 = register_prompt(
        prompt_key="prompt_store_diagnosis",
        name="门店运营诊断提示词",
        description="诊断门店运营问题的提示词模板",
        template="""你是一位资深的门店运营专家。请根据以下数据诊断门店运营问题：

门店数据：
{{store_data}}

分析周期：{{period}}

请从以下几个方面进行分析：
1. 销售表现
2. 客户服务
3. 商品管理
4. 人员管理
5. 营销活动

请提供详细的问题诊断和改进建议。""",
        variables=["store_data", "period"],
        business_domain="retail",
        tags=["诊断", "分析", "建议"],
        scenarios=["门店分析", "问题诊断", "优化建议"]
    )

    # 5. 注册Agent综合能力
    print("\n🤖 注册Agent综合能力...")
    agent_cap = register_agent_capability(
        agent_key="agent_operation",
        name="运营方案生成能力",
        description="运营智能体的综合能力入口",
        business_domain="retail",
        tags=["运营", "方案", "综合"],
        scenarios=["方案策划", "活动策划", "运营优化"]
    )
    if agent_cap:
        capabilities.append(agent_cap)

    # 6. 配置权限
    print("\n🔐 配置权限...")
    for cap in capabilities:
        if cap and "id" in cap:
            # 允许主控Agent调用
            register_permission(
                capability_id=cap["id"],
                subject_type="agent",
                subject_code="master_agent",
                permission="invoke",
                requires_audit=False
            )

            # 允许财务Agent读取（部分能力）
            if cap["type"] != "knowledge_base":
                register_permission(
                    capability_id=cap["id"],
                    subject_type="agent",
                    subject_code="finance_agent",
                    permission="read",
                    requires_audit=False
                )

    print("\n" + "=" * 60)
    print("✅ 运营智能体能力注册完成!")
    print(f"共计注册 {len(capabilities)} 个能力")
    print("=" * 60)


if __name__ == "__main__":
    register_operation_agent_capabilities()
