"""种子数据脚本：建表 + 灌入 7 个业务Agent + master_agent、示例知识库/文档、
Skill、Prompt、Policy、Tool能力，覆盖文档09"门店直播运营优化方案"场景所需的全部数据。

用法: uv run python -m app.seeds.seed_data
幂等：重复运行会跳过已存在的 key，不会重复插入或报错。

每次运行都会把当前全部身份的 API Key 写入 .local/seed_credentials.json
（已加入 .gitignore，不会被提交），供 scripts/demo_multi_agent.py 与手动调试使用。
"""
import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.core.db import AsyncSessionLocal, create_all_tables
from app.core.security import generate_api_key
from app.models.agent import AdminUser, Agent
from app.models.capability import Capability
from app.models.capability_permission import CapabilityPermission
from app.models.knowledge import KnowledgeBase
from app.models.policy import Policy
from app.models.skill import PromptTemplate, Skill
from app.services.knowledge_service import KnowledgeService
from app.services.llm.factory import get_llm_provider

BUSINESS_AGENTS = [
    ("hr_agent_001", "人事智能体", "hr_agent", "hr", "人事部"),
    ("finance_agent_001", "财务智能体", "finance_agent", "finance", "财务部"),
    ("product_submission_agent_001", "团品提报智能体", "product_submission_agent", "product", "商品部"),
    ("supply_chain_agent_001", "供应链智能体", "supply_chain_agent", "supply_chain", "供应链部"),
    ("merchant_agent_001", "招扶商智能体", "merchant_agent", "merchant", "招商部"),
    ("operation_agent_001", "运营智能体", "operation_agent", "operation", "运营部"),
    ("business_school_agent_001", "商学院智能体", "business_school_agent", "business_school", "商学院"),
]

DOCS = {
    "kb_store_operation": (
        "门店直播运营SOP.md",
        """# 门店直播运营SOP

## 开播前准备
### 货品检查
开播前需完成货品盘点、价格核对、库存确认，确保直播间展示商品与库存一致。

### 设备检查
检查直播设备、网络、灯光、收音，确认信号稳定后再开播。

### 脚本与合规
直播脚本需提前经过合规审核，禁止出现夸大功效、医疗承诺类话术。

## 到店引流策略
### 线上引流
通过直播预告、优惠券发放、社群裂变提升到店转化率。

### 会员运营
针对会员分层推送专属优惠，提升复购率和到店频次。

## 直播复盘
每场直播结束后需产出复盘报告，包含观看人数、转化率、引流效果和问题清单。
""",
    ),
    "kb_product": (
        "产品知识库.md",
        """# 产品知识库

## 产品卖点
本季度主推产品具备天然成分、温和配方、适合敏感肌人群等卖点，可强调使用体验和用户口碑。

## 禁用表达
产品宣传中禁止使用"根治""包治百病""特效""祖传秘方"等违反广告法的表达。

## 价格政策
门店活动价格需在提报系统中登记备案，不得私自调整零售价。
""",
    ),
    "kb_compliance": (
        "合规规则库.md",
        """# 合规规则库

## 广告法禁用词
禁止使用"国家级""最高级""绝对安全""永久有效"等绝对化用语。

## 内部审批规则
涉及价格调整、促销活动、跨部门资源协调的方案需经过对应部门审批后方可执行。
""",
    ),
    "kb_finance": (
        "财务报销与预算规则.md",
        """# 财务报销与预算规则

## 报销规则
差旅、招待、活动类费用需附发票及审批单，超过额度需财务负责人二次审批。

## ROI测算口径
活动ROI = (活动带来的净增销售额 - 活动成本) / 活动成本，净增销售额需扣除自然增长部分。

## 费用归属
门店活动费用归属对应门店成本中心，跨门店活动按客流占比分摊。
""",
    ),
}

PROMPTS = [
    {
        "prompt_key": "prompt_live_script_v1",
        "name": "直播脚本生成Prompt",
        "template": (
            "你是资深门店直播运营专家。请根据以下信息生成一段直播脚本大纲：\n"
            "产品信息：{{product_info}}\n客群：{{customer_profile}}\n时长：{{duration_minutes}}分钟\n"
            "要求：突出产品卖点，符合广告合规要求，包含开场、产品讲解、互动、收官四个环节。"
        ),
        "variables": [
            {"name": "product_info", "type": "object", "required": True},
            {"name": "customer_profile", "type": "object", "required": True},
            {"name": "duration_minutes", "type": "integer", "required": False},
        ],
        "owner": "运营部",
    },
    {
        "prompt_key": "prompt_roi_estimate_v1",
        "name": "活动ROI测算Prompt",
        "template": (
            "你是财务分析专家。请根据活动预算 {{budget}} 元、预计带来净增销售额 {{expected_revenue}} 元，"
            "测算本次活动的ROI，并给出是否建议执行的结论。"
        ),
        "variables": [
            {"name": "budget", "type": "number", "required": True},
            {"name": "expected_revenue", "type": "number", "required": True},
        ],
        "owner": "财务部",
    },
]

SKILLS = [
    {
        "skill_key": "skill_live_script",
        "name": "直播话术生成Skill",
        "description": "根据产品卖点、目标客群、直播时长生成合规直播脚本",
        "type": "workflow_skill",
        "business_domain": "operation",
        "input_schema": {"product_info": "object", "customer_profile": "object", "duration_minutes": "integer"},
        "output_schema": {"output_text": "string", "steps": "array"},
        "dependencies": ["kb_product", "kb_compliance", "tool_forbidden_word_check"],
        "allowed_agent_roles": ["operation_agent", "business_school_agent", "master_agent"],
        "prompt_key": None,
    },
    {
        "skill_key": "skill_roi_estimate",
        "name": "ROI测算Skill",
        "description": "根据活动预算与预计收益测算ROI",
        "type": "prompt_skill",
        "business_domain": "finance",
        "input_schema": {"budget": "number", "expected_revenue": "number"},
        "output_schema": {"output_text": "string"},
        "dependencies": [],
        "allowed_agent_roles": ["finance_agent", "product_submission_agent", "operation_agent", "master_agent"],
        "prompt_key": "prompt_roi_estimate_v1",
    },
]

CAPABILITIES_EXTRA = [
    # tool
    {
        "capability_key": "tool_forbidden_word_check",
        "type": "tool",
        "name": "违禁词/合规话术检测工具",
        "description": "检测文本中是否包含违禁词或夸大表达，返回风险等级",
        "business_domain": "compliance",
        "tags": ["合规", "违禁词", "审核"],
        "scenarios": ["直播脚本审核", "文案合规审核"],
        "input_schema": {"text": "string"},
        "output_schema": {"passed": "boolean", "risk_level": "string", "hits": "array"},
        "security_level": "internal",
        "owner_department": "合规部",
        "allowed_agent_roles": [],
        "side_effect": "read_only",
        "ref_id": "tool_forbidden_word_check",
    },
]


async def get_or_create_agent(db, agent_key, name, role, domain, dept, is_master=False) -> tuple[Agent, bool]:
    result = await db.execute(select(Agent).where(Agent.agent_key == agent_key))
    existing = result.scalar_one_or_none()
    if existing:
        return existing, False
    agent = Agent(
        agent_key=agent_key, name=name, role=role, business_domain=domain, owner_department=dept,
        status="active", api_key=generate_api_key("agent"), is_master=is_master,
        supported_tasks=[],
    )
    db.add(agent)
    await db.flush()
    return agent, True


async def get_or_create_kb(db, kb_key, name, domain, security_level="internal") -> tuple[KnowledgeBase, bool]:
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.kb_key == kb_key))
    existing = result.scalar_one_or_none()
    if existing:
        return existing, False
    kb = KnowledgeBase(kb_key=kb_key, name=name, business_domain=domain, owner_department=name, security_level=security_level, status="draft")
    db.add(kb)
    await db.flush()
    return kb, True


async def get_or_create_capability(db, **kwargs) -> tuple[Capability, bool]:
    result = await db.execute(select(Capability).where(Capability.capability_key == kwargs["capability_key"]))
    existing = result.scalar_one_or_none()
    if existing:
        return existing, False
    metadata = kwargs.pop("metadata", {})
    cap = Capability(**kwargs, metadata_=metadata, status="published")
    db.add(cap)
    await db.flush()
    return cap, True


async def get_or_create_policy(db, policy_key, **kwargs) -> tuple[Policy, bool]:
    result = await db.execute(select(Policy).where(Policy.policy_key == policy_key))
    existing = result.scalar_one_or_none()
    if existing:
        return existing, False
    policy = Policy(policy_key=policy_key, status="active", **kwargs)
    db.add(policy)
    await db.flush()
    return policy, True


async def get_or_create_capability_permission(
    db,
    capability: Capability,
    subject_type: str,
    subject_code: str,
    permission: str,
    conditions: dict | None = None,
    status: str = "active",
) -> tuple[CapabilityPermission, bool]:
    result = await db.execute(
        select(CapabilityPermission).where(
            CapabilityPermission.capability_id == capability.id,
            CapabilityPermission.subject_type == subject_type,
            CapabilityPermission.subject_code == subject_code,
            CapabilityPermission.permission == permission,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return existing, False
    perm = CapabilityPermission(
        capability_id=capability.id,
        subject_type=subject_type,
        subject_code=subject_code,
        permission=permission,
        conditions=conditions or {},
        status=status,
    )
    db.add(perm)
    await db.flush()
    return perm, True


async def seed() -> None:
    await create_all_tables()
    llm = get_llm_provider()
    created_keys: list[tuple[str, str, str]] = []
    all_credentials: dict[str, str] = {}

    async with AsyncSessionLocal() as db:
        # --- Admin user ---
        result = await db.execute(select(AdminUser).where(AdminUser.username == "admin"))
        admin = result.scalar_one_or_none()
        if admin is None:
            admin = AdminUser(
                username="admin", display_name="平台管理员", role="platform_admin",
                api_key=generate_api_key("admin"), status="active",
            )
            db.add(admin)
            await db.flush()
            created_keys.append(("admin_user", "admin", admin.api_key))
        all_credentials["admin"] = admin.api_key

        # --- Agents ---
        agent_map: dict[str, Agent] = {}
        for agent_key, name, role, domain, dept in BUSINESS_AGENTS:
            agent, is_new = await get_or_create_agent(db, agent_key, name, role, domain, dept)
            agent_map[role] = agent
            if is_new:
                created_keys.append(("agent", agent_key, agent.api_key))
            all_credentials[agent_key] = agent.api_key

        master, is_new = await get_or_create_agent(
            db, "master_agent_001", "主控Agent", "master_agent", None, "多Agent协作系统", is_master=True
        )
        agent_map["master_agent"] = master
        if is_new:
            created_keys.append(("agent", "master_agent_001", master.api_key))
        all_credentials["master_agent_001"] = master.api_key

        await db.flush()

        # --- Knowledge bases + documents ---
        kb_domain_map = {
            "kb_store_operation": ("门店运营知识库", "operation", "internal"),
            "kb_product": ("产品知识库", "product", "internal"),
            "kb_compliance": ("合规规则库", "compliance", "internal"),
            "kb_finance": ("财务报销与预算规则库", "finance", "confidential"),
        }
        kb_service = KnowledgeService(db, llm)
        kb_map: dict[str, KnowledgeBase] = {}
        for kb_key, (name, domain, level) in kb_domain_map.items():
            kb, is_new = await get_or_create_kb(db, kb_key, name, domain, level)
            kb_map[kb_key] = kb
            if is_new:
                filename, content = DOCS[kb_key]
                doc = await kb_service.upload_document(kb, filename, content.encode("utf-8"), security_level=level)
                await kb_service.publish_document(doc)
                kb.status = "published"
                await db.flush()

        # --- Prompts ---
        for p in PROMPTS:
            result = await db.execute(select(PromptTemplate).where(PromptTemplate.prompt_key == p["prompt_key"]))
            if result.scalar_one_or_none() is None:
                prompt = PromptTemplate(
                    prompt_key=p["prompt_key"], name=p["name"], template=p["template"], variables=p["variables"],
                    owner=p["owner"], status="published",
                )
                db.add(prompt)
        await db.flush()

        # 补上 skill_live_script 的 prompt_key（依赖上面刚创建的 prompt）
        for s in SKILLS:
            if s["skill_key"] == "skill_live_script":
                s["prompt_key"] = "prompt_live_script_v1"

        # --- Skills ---
        for s in SKILLS:
            result = await db.execute(select(Skill).where(Skill.skill_key == s["skill_key"]))
            if result.scalar_one_or_none() is None:
                skill = Skill(**s, status="published")
                db.add(skill)
        await db.flush()

        # --- Capabilities: wrap KB / Skill / Prompt / Agent as searchable capabilities ---
        for kb_key, (name, domain, level) in kb_domain_map.items():
            kb = kb_map[kb_key]
            await get_or_create_capability(
                db, capability_key=kb_key, type="knowledge_base", name=name,
                description=f"{name}，业务域={domain}", business_domain=domain,
                tags=[domain, "知识库"], scenarios=[], input_schema={"query": "string", "top_k": "integer"},
                output_schema={"chunks": "array", "citations": "array"}, security_level=level,
                owner_department=name, allowed_agent_roles=[], ref_id=kb_key,
            )

        for s in SKILLS:
            await get_or_create_capability(
                db, capability_key=s["skill_key"], type="skill", name=s["name"], description=s["description"],
                business_domain=s["business_domain"], tags=[s["business_domain"], "skill"],
                scenarios=[], input_schema=s["input_schema"], output_schema=s["output_schema"],
                security_level="internal", owner_department=s["business_domain"],
                allowed_agent_roles=s["allowed_agent_roles"], ref_id=s["skill_key"],
            )

        await get_or_create_capability(
            db, capability_key="prompt_live_script", type="prompt", name="直播脚本生成Prompt",
            description="直接渲染并生成直播脚本文案", business_domain="operation", tags=["operation", "prompt"],
            scenarios=[], input_schema={"product_info": "object", "customer_profile": "object"},
            output_schema={"rendered": "string", "output_text": "string"}, security_level="internal",
            owner_department="运营部", allowed_agent_roles=["operation_agent", "business_school_agent", "master_agent"],
            ref_id="prompt_live_script_v1",
        )

        for cap_kwargs in CAPABILITIES_EXTRA:
            await get_or_create_capability(db, **cap_kwargs)

        # --- Capability permissions：显式授权，用于更细粒度的发现/调用控制 ---
        async def cap_by_key(capability_key: str) -> Capability:
            result = await db.execute(select(Capability).where(Capability.capability_key == capability_key))
            capability = result.scalar_one()
            return capability

        explicit_permissions = [
            ("kb_store_operation", "role", "operation_agent", ["discover", "invoke"]),
            ("kb_product", "role", "product_submission_agent", ["discover", "invoke"]),
            ("kb_compliance", "role", "operation_agent", ["discover", "invoke"]),
            ("kb_compliance", "role", "product_submission_agent", ["discover", "invoke"]),
            ("kb_compliance", "role", "finance_agent", ["discover", "invoke"]),
            ("skill_live_script", "role", "operation_agent", ["discover", "invoke"]),
            ("skill_live_script", "role", "business_school_agent", ["discover", "invoke"]),
            ("skill_live_script", "role", "master_agent", ["discover", "invoke"]),
            ("skill_roi_estimate", "role", "finance_agent", ["discover", "invoke"]),
            ("skill_roi_estimate", "role", "operation_agent", ["discover", "invoke"]),
            ("skill_roi_estimate", "role", "product_submission_agent", ["discover", "invoke"]),
            ("prompt_live_script", "role", "operation_agent", ["discover", "invoke"]),
            ("prompt_live_script", "role", "business_school_agent", ["discover", "invoke"]),
            ("prompt_live_script", "role", "master_agent", ["discover", "invoke"]),
            ("tool_forbidden_word_check", "role", "operation_agent", ["discover", "invoke"]),
            ("tool_forbidden_word_check", "role", "finance_agent", ["discover", "invoke"]),
            ("tool_forbidden_word_check", "role", "product_submission_agent", ["discover", "invoke"]),
            ("tool_forbidden_word_check", "role", "merchant_agent", ["discover", "invoke"]),
            ("tool_forbidden_word_check", "role", "supply_chain_agent", ["discover", "invoke"]),
            ("tool_forbidden_word_check", "role", "hr_agent", ["discover", "invoke"]),
            ("tool_forbidden_word_check", "role", "business_school_agent", ["discover", "invoke"]),
            ("tool_forbidden_word_check", "role", "master_agent", ["discover", "invoke"]),
        ]
        for capability_key, subject_type, subject_code, permissions in explicit_permissions:
            capability = await cap_by_key(capability_key)
            for permission in permissions:
                await get_or_create_capability_permission(db, capability, subject_type, subject_code, permission)

        # 存量Agent作为能力注册，供 master_agent 发现和调用（对应文档03 3.5）
        for agent_key, name, role, domain, dept in BUSINESS_AGENTS:
            await get_or_create_capability(
                db, capability_key=f"agent_{role}", type="agent", name=name,
                description=f"{name}，业务域={domain}，可处理该领域相关子任务",
                business_domain=domain, tags=[domain, "agent"], scenarios=[],
                input_schema={"task": "string"}, output_schema={"result": "object"},
                security_level="internal", owner_department=dept, allowed_agent_roles=["master_agent"],
                ref_id=agent_key,
            )

        # --- Policies：各Agent角色可见/可调用自己业务域的能力 ---
        domain_policies = [
            ("policy_hr_own_domain", ["hr_agent"], ["hr"]),
            ("policy_finance_own_domain", ["finance_agent"], ["finance"]),
            ("policy_product_own_domain", ["product_submission_agent"], ["product"]),
            ("policy_supply_chain_own_domain", ["supply_chain_agent"], ["supply_chain"]),
            ("policy_merchant_own_domain", ["merchant_agent"], ["merchant"]),
            ("policy_operation_own_domain", ["operation_agent"], ["operation"]),
            ("policy_business_school_own_domain", ["business_school_agent"], ["operation", "business_school"]),
        ]
        for policy_key, roles, domains in domain_policies:
            await get_or_create_policy(
                db, policy_key, name=policy_key, effect="allow",
                subject={"agent_role": roles}, resource={"business_domain": domains},
                actions=["search", "invoke"], conditions={},
            )

        # 合规能力对所有业务Agent开放（违禁词检测是终检共用工具）
        await get_or_create_policy(
            db, "policy_compliance_shared", name="合规能力共享", effect="allow",
            subject={"agent_role": [role for _, _, role, _, _ in BUSINESS_AGENTS]},
            resource={"business_domain": ["compliance"]}, actions=["search", "invoke"], conditions={},
        )
        # 财务ROI Skill 允许运营/团品提报Agent调用（跨域复用场景，文档05 10.2）
        await get_or_create_policy(
            db, "policy_roi_skill_cross_domain", name="ROI测算Skill跨域复用", effect="allow",
            subject={"agent_role": ["operation_agent", "product_submission_agent"]},
            resource={"business_domain": ["finance"], "security_level": ["internal"]},
            actions=["search", "invoke"], conditions={},
        )

        await db.commit()

    creds_dir = Path(".local")
    creds_dir.mkdir(exist_ok=True)
    creds_path = creds_dir / "seed_credentials.json"
    creds_path.write_text(json.dumps(all_credentials, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 60)
    print("种子数据灌入完成。")
    if created_keys:
        print("\n新创建的身份 API Key（仅显示一次，请妥善保存）：")
        for kind, key, api_key in created_keys:
            print(f"  [{kind}] {key} -> {api_key}")
    else:
        print("\n所有种子数据均已存在，未创建新身份。")
    print(f"\n全部身份的 API Key 已写入 {creds_path.resolve()}（demo脚本会自动读取）")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(seed())
