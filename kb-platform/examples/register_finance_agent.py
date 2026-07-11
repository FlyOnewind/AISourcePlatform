"""
示例：财务智能体能力注册
演示如何将财务智能体的工具等注册到中台（高风险能力）
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


def register_finance_roi_calc():
    """
    注册财务ROI计算工具（高风险，需要审计）
    """
    print("=" * 60)
    print("🚀 开始注册财务智能体能力到中台")
    print("=" * 60)

    data = {
        "capability_key": "tool_finance_roi_calc",
        "type": "tool",
        "name": "财务ROI计算工具",
        "description": "根据预算、预计销售额和毛利率计算活动ROI",
        "business_domain": "finance",
        "tags": ["ROI", "预算", "财务"],
        "scenarios": ["预算审批", "投资评估", "活动策划"],
        "owner_department": "财务部",
        "security_level": "confidential",
        "side_effect": "read_only",
        "endpoint": "http://localhost:8030/tools/roi-calc",
        "input_schema": {
            "type": "object",
            "properties": {
                "budget": {"type": "number", "description": "预算金额"},
                "expected_sales": {"type": "number", "description": "预计销售额"},
                "gross_margin_rate": {"type": "number", "description": "毛利率 (0-1)"}
            },
            "required": ["budget", "expected_sales", "gross_margin_rate"]
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "roi": {"type": "number", "description": "ROI比率"},
                "gross_profit": {"type": "number", "description": "毛利润"},
                "risk_level": {"type": "string", "description": "风险等级"},
                "suggestion": {"type": "string", "description": "建议"}
            }
        },
        "examples": [
            {
                "input": {
                    "budget": 100000,
                    "expected_sales": 150000,
                    "gross_margin_rate": 0.4
                },
                "output": {
                    "roi": 0.6,
                    "gross_profit": 60000,
                    "risk_level": "low",
                    "suggestion": "预算收益测算基本可行"
                }
            }
        ]
    }

    print("\n🔧 注册财务ROI计算工具...")
    response = requests.post(
        f"{PLATFORM_BASE_URL}/capabilities",
        headers=headers,
        json=data
    )

    if response.status_code == 200:
        result = response.json()
        if result.get("success"):
            print("✅ 财务ROI计算工具注册成功")
            capability = result["data"]

            # 配置权限（需要审计）
            print("\n🔐 配置权限...")

            # 允许主控Agent调用，但需要审计
            perm1 = {
                "subject_type": "agent",
                "subject_code": "master_agent",
                "permission": "invoke",
                "conditions": {
                    "requires_audit": True
                },
                "status": "active"
            }

            response = requests.post(
                f"{PLATFORM_BASE_URL}/capabilities/{capability['id']}/permissions",
                headers=headers,
                json=perm1
            )
            print("✅ 主控Agent权限配置完成")

            # 允许财务Agent调用
            perm2 = {
                "subject_type": "agent",
                "subject_code": "finance_agent",
                "permission": "invoke",
                "conditions": {
                    "requires_audit": True
                },
                "status": "active"
            }

            response = requests.post(
                f"{PLATFORM_BASE_URL}/capabilities/{capability['id']}/permissions",
                headers=headers,
                json=perm2
            )
            print("✅ 财务Agent权限配置完成")

            print("\n" + "=" * 60)
            print("✅ 财务智能体能力注册完成!")
            print("=" * 60)

            return capability
        else:
            print(f"❌ 注册失败: {result.get('error')}")
    else:
        print(f"❌ 请求失败: {response.status_code} - {response.text}")


if __name__ == "__main__":
    register_finance_roi_calc()
