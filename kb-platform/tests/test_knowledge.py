"""知识库上传/解析/检索链路测试，对应文档04验收标准。"""
import io

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import generate_api_key
from app.models.agent import AdminUser, Agent


async def _create_admin(db_session: AsyncSession) -> str:
    api_key = generate_api_key("admin")
    admin = AdminUser(username="kb_admin", display_name="KB Admin", role="knowledge_admin", api_key=api_key, status="active")
    db_session.add(admin)
    await db_session.commit()
    return api_key


async def _create_agent(db_session: AsyncSession, role: str = "operation_agent") -> str:
    api_key = generate_api_key("agent")
    agent = Agent(agent_key=f"agent_{role}_kbtest", name="test agent", role=role, status="active", api_key=api_key)
    db_session.add(agent)
    await db_session.commit()
    return api_key


@pytest.mark.asyncio
async def test_create_kb_and_upload_document(client: AsyncClient, db_session: AsyncSession):
    admin_key = await _create_admin(db_session)

    kb_resp = await client.post(
        "/api/v1/knowledge-bases",
        json={"kb_key": "kb_test_operation", "name": "测试运营知识库", "business_domain": "operation", "security_level": "internal"},
        headers={"X-API-Key": admin_key},
    )
    assert kb_resp.status_code == 200
    kb_id = kb_resp.json()["data"]["id"]

    content = "# 测试SOP\n\n## 开播前准备\n货品检查、设备检查、脚本合规审核。\n\n## 引流策略\n直播预告和优惠券发放。"
    files = {"file": ("test_sop.md", io.BytesIO(content.encode("utf-8")), "text/markdown")}
    upload_resp = await client.post(
        f"/api/v1/knowledge-bases/{kb_id}/documents", files=files, headers={"X-API-Key": admin_key}
    )
    assert upload_resp.status_code == 200
    doc = upload_resp.json()["data"]
    assert doc["parse_status"] == "indexed"
    assert doc["chunk_count"] > 0

    publish_resp = await client.post(f"/api/v1/documents/{doc['id']}/publish", headers={"X-API-Key": admin_key})
    assert publish_resp.status_code == 200


@pytest.mark.asyncio
async def test_search_knowledge_after_publish(client: AsyncClient, db_session: AsyncSession):
    admin_key = await _create_admin(db_session)
    agent_key = await _create_agent(db_session)

    kb_resp = await client.post(
        "/api/v1/knowledge-bases",
        json={"kb_key": "kb_test_search", "name": "测试检索知识库", "business_domain": "operation"},
        headers={"X-API-Key": admin_key},
    )
    kb_id = kb_resp.json()["data"]["id"]

    content = "# 直播运营SOP\n\n## 货品检查\n开播前需完成货品盘点和价格核对。"
    files = {"file": ("live_sop.md", io.BytesIO(content.encode("utf-8")), "text/markdown")}
    upload_resp = await client.post(f"/api/v1/knowledge-bases/{kb_id}/documents", files=files, headers={"X-API-Key": admin_key})
    doc_id = upload_resp.json()["data"]["id"]
    await client.post(f"/api/v1/documents/{doc_id}/publish", headers={"X-API-Key": admin_key})

    search_resp = await client.post(
        "/api/v1/knowledge/search",
        json={"query": "开播前货品检查", "knowledge_base_ids": [kb_id], "top_k": 5},
        headers={"X-API-Key": agent_key},
    )
    assert search_resp.status_code == 200
    chunks = search_resp.json()["data"]["chunks"]
    assert len(chunks) > 0
    assert chunks[0]["source"]["doc_name"] == "live_sop.md"


@pytest.mark.asyncio
async def test_unsupported_file_type_rejected(client: AsyncClient, db_session: AsyncSession):
    admin_key = await _create_admin(db_session)
    kb_resp = await client.post(
        "/api/v1/knowledge-bases", json={"kb_key": "kb_test_bad_file", "name": "测试"}, headers={"X-API-Key": admin_key}
    )
    kb_id = kb_resp.json()["data"]["id"]
    files = {"file": ("bad.xyz", io.BytesIO(b"random content"), "application/octet-stream")}
    resp = await client.post(f"/api/v1/knowledge-bases/{kb_id}/documents", files=files, headers={"X-API-Key": admin_key})
    assert resp.status_code == 200
    assert resp.json()["data"]["parse_status"] == "parse_failed"
