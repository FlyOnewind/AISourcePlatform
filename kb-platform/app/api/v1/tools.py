"""工具管理 API：支持工具发现、注册、配置更新。"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Identity, get_current_identity, require_admin_roles
from app.core.db import get_db
from app.models.capability import Capability, CapabilityVersion
from app.schemas.common import ok
from app.services.tools import ToolRegistry, ToolDefinition


router = APIRouter(prefix="/api/v1/tools", tags=["tools"])


@router.get("/discover")
async def discover_tools(
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
):
    """发现所有已注册的工具定义。"""
    tool_definitions = ToolRegistry.get_all_definitions()

    # 检查哪些工具已经注册到 capability 表中
    registered_keys = set()
    result = await db.execute(
        select(Capability.capability_key).where(Capability.type == "tool")
    )
    for row in result.scalars().all():
        registered_keys.add(row)

    return ok({
        "tools": [
            {
                "capability_key": td.capability_key,
                "name": td.name,
                "description": td.description,
                "business_domain": td.business_domain,
                "tags": td.tags,
                "registered": td.capability_key in registered_keys,
            }
            for td in tool_definitions
        ],
        "total": len(tool_definitions),
    })


@router.post("/register/{tool_key}")
async def register_tool(
    tool_key: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(require_admin_roles("platform_admin", "capability_admin")),
):
    """将发现的工具注册到 capability 注册表中。"""
    tool_definitions = ToolRegistry.get_all_definitions()
    tool_def = next((td for td in tool_definitions if td.capability_key == tool_key), None)

    if not tool_def:
        raise HTTPException(status_code=404, detail=f"工具定义未找到: {tool_key}")

    # 检查是否已经存在
    existing = await db.execute(
        select(Capability).where(Capability.capability_key == tool_key)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"工具已注册: {tool_key}")

    # 创建 capability
    capability = Capability(
        capability_key=tool_def.capability_key,
        type="tool",
        name=tool_def.name,
        description=tool_def.description,
        business_domain=tool_def.business_domain,
        tags=tool_def.tags,
        scenarios=tool_def.scenarios,
        input_schema=tool_def.input_schema,
        output_schema=tool_def.output_schema,
        security_level=tool_def.security_level,
        owner_department=tool_def.owner_department,
        allowed_agent_roles=[],
        side_effect=tool_def.side_effect,
        ref_id=tool_def.capability_key,
        metadata_=tool_def.metadata,
        timeout_ms=tool_def.timeout_ms,
        examples=tool_def.examples,
        status="draft",
        current_version="1.0.0",
    )
    db.add(capability)
    await db.flush()

    # 创建版本记录
    db.add(CapabilityVersion(
        capability_id=capability.id,
        version="1.0.0",
        config={
            "tool_definition": {
                "name": tool_def.name,
                "description": tool_def.description,
                "metadata": tool_def.metadata,
            }
        },
        status="draft",
        release_notes="初始版本，从工具注册表自动注册",
    ))

    await db.commit()
    await db.refresh(capability)

    return ok({
        "capability_id": str(capability.id),
        "capability_key": capability.capability_key,
        "name": capability.name,
        "status": capability.status,
        "message": "工具已注册",
    })


@router.get("/config/{capability_id}")
async def get_tool_config(
    capability_id: str,
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(get_current_identity),
):
    """获取工具的当前配置。"""
    result = await db.execute(
        select(Capability).where(Capability.id == capability_id)
    )
    capability = result.scalar_one_or_none()

    if not capability:
        raise HTTPException(status_code=404, detail="能力不存在")

    if capability.type != "tool":
        raise HTTPException(status_code=400, detail="不是工具类型的能力")

    return ok({
        "capability_key": capability.capability_key,
        "name": capability.name,
        "metadata": capability.metadata_ or {},
        "input_schema": capability.input_schema,
        "output_schema": capability.output_schema,
        "timeout_ms": capability.timeout_ms,
    })


@router.put("/config/{capability_id}")
async def update_tool_config(
    capability_id: str,
    config: dict[str, Any],
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(require_admin_roles("platform_admin", "capability_admin")),
):
    """更新工具配置（如违禁词表等）。"""
    result = await db.execute(
        select(Capability).where(Capability.id == capability_id)
    )
    capability = result.scalar_one_or_none()

    if not capability:
        raise HTTPException(status_code=404, detail="能力不存在")

    if capability.type != "tool":
        raise HTTPException(status_code=400, detail="不是工具类型的能力")

    # 更新 metadata
    current_metadata = capability.metadata_ or {}
    current_metadata.update(config.get("metadata", {}))
    capability.metadata_ = current_metadata

    # 如果指定了新版本号，则创建新版本
    new_version = config.get("version")
    if new_version and new_version != capability.current_version:
        capability.current_version = new_version
        db.add(CapabilityVersion(
            capability_id=capability.id,
            version=new_version,
            config={
                "metadata": current_metadata,
            },
            status="published" if capability.status == "published" else "draft",
            release_notes=config.get("release_notes", "配置更新"),
        ))

    await db.commit()
    await db.refresh(capability)

    return ok({
        "capability_key": capability.capability_key,
        "name": capability.name,
        "current_version": capability.current_version,
        "metadata": capability.metadata_,
        "message": "配置已更新",
    })


@router.post("/batch-register")
async def batch_register_tools(
    db: AsyncSession = Depends(get_db),
    identity: Identity = Depends(require_admin_roles("platform_admin", "capability_admin")),
):
    """批量注册所有发现的工具。"""
    tool_definitions = ToolRegistry.get_all_definitions()

    results = []
    for tool_def in tool_definitions:
        # 检查是否已经存在
        existing = await db.execute(
            select(Capability).where(Capability.capability_key == tool_def.capability_key)
        )
        if existing.scalar_one_or_none():
            results.append({
                "capability_key": tool_def.capability_key,
                "status": "skipped",
                "message": "已存在",
            })
            continue

        # 创建 capability
        capability = Capability(
            capability_key=tool_def.capability_key,
            type="tool",
            name=tool_def.name,
            description=tool_def.description,
            business_domain=tool_def.business_domain,
            tags=tool_def.tags,
            scenarios=tool_def.scenarios,
            input_schema=tool_def.input_schema,
            output_schema=tool_def.output_schema,
            security_level=tool_def.security_level,
            owner_department=tool_def.owner_department,
            allowed_agent_roles=[],
            side_effect=tool_def.side_effect,
            ref_id=tool_def.capability_key,
            metadata_=tool_def.metadata,
            timeout_ms=tool_def.timeout_ms,
            examples=tool_def.examples,
            status="draft",
            current_version="1.0.0",
        )
        db.add(capability)
        await db.flush()

        # 创建版本记录
        db.add(CapabilityVersion(
            capability_id=capability.id,
            version="1.0.0",
            config={"tool_definition": tool_def.metadata},
            status="draft",
            release_notes="初始版本，从工具注册表自动注册",
        ))

        results.append({
            "capability_key": tool_def.capability_key,
            "status": "registered",
            "message": "注册成功",
        })

    await db.commit()

    return ok({
        "results": results,
        "total": len(results),
        "registered": sum(1 for r in results if r["status"] == "registered"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
    })
