"""多Agent协作Demo：复现文档09"门店直播运营优化方案"完整链路。

用法（先跑 seed_data 并确保服务已启动）:
    uv run python scripts/demo_multi_agent.py

流程对应文档09 第5节：
  主控Agent检索能力 -> 拆解任务DAG -> 各领域子Agent通过SDK调用中台能力 -> 主控整合 -> 终检(违禁词工具) -> 输出
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sdk"))

from kb_platform_sdk import KBPlatformClient  # noqa: E402
from kb_platform_sdk.client import KBPlatformError  # noqa: E402

BASE_URL = os.environ.get("KB_PLATFORM_BASE_URL", "http://localhost:8000")
CREDS_PATH = Path(__file__).resolve().parent.parent / ".local" / "seed_credentials.json"

SUBTASKS = [
    {"subtask_id": "s1", "agent_key": "operation_agent_001", "role": "operation_agent",
     "goal": "分析门店直播现状并提出到店引流策略", "query": "白佛华宸店直播引流策略有哪些最佳实践"},
    {"subtask_id": "s2", "agent_key": "product_submission_agent_001", "role": "product_submission_agent",
     "goal": "确定适合直播的产品池和卖点", "query": "适合直播的产品卖点和禁用表达"},
    {"subtask_id": "s3", "agent_key": "finance_agent_001", "role": "finance_agent",
     "goal": "测算活动预算和ROI", "query": "活动ROI测算口径"},
    {"subtask_id": "s4", "agent_key": "hr_agent_001", "role": "hr_agent",
     "goal": "生成人员排班和职责分工", "query": "直播活动人员排班安排"},
    {"subtask_id": "s5", "agent_key": "business_school_agent_001", "role": "business_school_agent",
     "goal": "生成直播前培训课件大纲", "query": "直播培训课件大纲"},
]


def load_credentials() -> dict:
    if not CREDS_PATH.exists():
        print(f"未找到凭证文件 {CREDS_PATH}，请先运行: uv run python -m app.seeds.seed_data")
        sys.exit(1)
    return json.loads(CREDS_PATH.read_text(encoding="utf-8"))


def main() -> None:
    creds = load_credentials()
    trace_id = "trace_demo_live_optimize_001"
    task_id = "task_live_optimize_001"

    print("=" * 70)
    print("多Agent协作Demo：白佛华宸店直播运营优化方案")
    print(f"trace_id={trace_id}  task_id={task_id}")
    print("=" * 70)

    # --- 第一步：主控Agent检索能力 ---
    master_client = KBPlatformClient(BASE_URL, "master_agent_001", creds["master_agent_001"])
    print("\n[主控Agent] 检索可用能力...")
    search_result = master_client.search_capabilities(
        task="针对白佛华宸店，输出一份直播运营优化方案，要求包含到店引流策略、产品直播脚本、合规审核、人员安排、预算ROI和培训材料",
        keywords=["门店直播", "引流", "脚本", "合规", "预算", "培训"],
        top_k=10,
        trace_id=trace_id,
    )
    print(f"  返回 {len(search_result['capabilities'])} 个候选能力：")
    for cap in search_result["capabilities"]:
        print(f"    - [{cap['type']}] {cap['name']} (score={cap['score']})")
    print("  推荐调用顺序：")
    for step in search_result["recommended_plan"]:
        print(f"    {step['step']}. {step['capability_key']} — {step['reason']}")

    # --- 第二步：主控Agent发现可协作子Agent ---
    print("\n[主控Agent] 发现可协作子Agent...")
    agents = master_client.discover_agents(task="门店直播运营优化方案", trace_id=trace_id)
    print(f"  发现 {len(agents)} 个可协作Agent: {[a['name'] for a in agents]}")

    # --- 第三步：拆解任务DAG ---
    collab_task = master_client.create_collaboration_task(
        {"task_id": task_id, "subtasks": [{"subtask_id": s["subtask_id"], "agent_role": s["role"], "goal": s["goal"]} for s in SUBTASKS]}
    )
    print(f"\n[主控Agent] 已创建协作任务: {collab_task['task_id']}, 共 {len(SUBTASKS)} 个子任务")

    # --- 第四步：各子Agent执行 ---
    subtask_results = []
    for sub in SUBTASKS:
        print(f"\n[{sub['role']}] 执行子任务 {sub['subtask_id']}: {sub['goal']}")
        client = KBPlatformClient(BASE_URL, sub["agent_key"], creds[sub["agent_key"]])
        used_capabilities = []
        try:
            search = client.search_capabilities(task=sub["goal"], keywords=sub["query"].split(), top_k=5, trace_id=trace_id)
            used_capabilities = [c["capability_key"] for c in search["capabilities"][:2]]
            kb_result = client.search_knowledge(query=sub["query"], top_k=3, trace_id=trace_id)
            hits = kb_result["chunks"]
            print(f"    检索到 {len(hits)} 条知识片段，调用了能力: {used_capabilities}")
            for h in hits[:2]:
                print(f"      [{h['source']['doc_name']}] score={h['score']} {h['content'][:60]}...")
            result = {"subtask_id": sub["subtask_id"], "hits": len(hits), "used_capabilities": used_capabilities}
        except KBPlatformError as exc:
            print(f"    调用失败: {exc}")
            result = {"subtask_id": sub["subtask_id"], "error": str(exc)}
        client.report_subtask_result(task_id, sub["subtask_id"], result)
        subtask_results.append(result)
        client.close()

    # --- 第五步：调用直播话术生成Skill（运营Agent）---
    print("\n[operation_agent] 调用直播话术生成Skill...")
    op_client = KBPlatformClient(BASE_URL, "operation_agent_001", creds["operation_agent_001"])
    search = op_client.search_capabilities(task="生成直播脚本", keywords=["直播", "话术"], top_k=5, trace_id=trace_id)
    live_script_cap = next((c for c in search["capabilities"] if c["capability_key"] == "skill_live_script"), None)
    live_script_text = ""
    if live_script_cap:
        invoke_result = op_client.invoke_capability(
            capability_id=live_script_cap["capability_id"],
            input={
                "product_info": {"name": "天然温和护肤套装", "selling_points": ["天然成分", "温和配方"]},
                "customer_profile": {"segment": "敏感肌人群"},
                "duration_minutes": 60,
            },
            task_id=task_id,
            trace_id=trace_id,
        )
        live_script_text = invoke_result.get("output", {}).get("output_text", "")
        print(f"    脚本生成结果: {live_script_text[:120]}...")
    else:
        print("    未找到直播话术生成Skill")
    op_client.close()

    # --- 第六步：财务Agent调用ROI测算Skill ---
    print("\n[finance_agent] 调用ROI测算Skill...")
    fin_client = KBPlatformClient(BASE_URL, "finance_agent_001", creds["finance_agent_001"])
    search = fin_client.search_capabilities(task="测算活动ROI", keywords=["ROI", "预算"], top_k=5, trace_id=trace_id)
    roi_cap = next((c for c in search["capabilities"] if c["capability_key"] == "skill_roi_estimate"), None)
    if roi_cap:
        roi_result = fin_client.invoke_capability(
            capability_id=roi_cap["capability_id"],
            input={"budget": 50000, "expected_revenue": 180000},
            task_id=task_id,
            trace_id=trace_id,
        )
        print(f"    ROI测算结果: {roi_result.get('output', {}).get('output_text', '')[:120]}...")
    else:
        print("    未找到ROI测算Skill")
    fin_client.close()

    # --- 第七步：主控Agent终检（违禁词合规工具）---
    print("\n[主控Agent] 终检：调用违禁词合规校验工具...")
    search = master_client.search_capabilities(task="合规审核直播脚本", keywords=["合规", "违禁词"], top_k=5, trace_id=trace_id)
    tool_cap = next((c for c in search["capabilities"] if c["capability_key"] == "tool_forbidden_word_check"), None)
    if tool_cap:
        check_text = live_script_text or "本产品天然温和，适合敏感肌人群使用，欢迎到店体验"
        check_result = master_client.invoke_capability(
            capability_id=tool_cap["capability_id"], input={"text": check_text}, task_id=task_id, trace_id=trace_id,
        )
        tool_output = check_result.get("output", {})
        print(f"    合规检测结果: passed={tool_output.get('passed')}, risk_level={tool_output.get('risk_level')}")
    else:
        print("    未找到合规校验工具")

    # --- 第八步：整合结果 ---
    print("\n" + "=" * 70)
    print("[主控Agent] 整合最终结果：")
    print(f"  子任务完成: {len(subtask_results)}/{len(SUBTASKS)}")
    print(f"  已用能力清单: {[r.get('used_capabilities') for r in subtask_results]}")
    print(f"  trace_id={trace_id} 可通过 GET /api/v1/traces/{{trace_id}} 查看完整调用链")
    print("=" * 70)

    master_client.close()


if __name__ == "__main__":
    main()
