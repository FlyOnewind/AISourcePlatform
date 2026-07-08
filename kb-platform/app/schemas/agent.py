"""Agent 相关请求/响应 schema，对应文档11 3.1 与文档06。"""
from pydantic import BaseModel, Field


class AgentCreate(BaseModel):
    agent_key: str
    name: str
    role: str
    business_domain: str | None = None
    owner_department: str | None = None
    owner_user: str | None = None
    is_master: bool = False
    endpoint: str | None = None
    supported_tasks: list[str] = Field(default_factory=list)


class AgentUpdate(BaseModel):
    name: str | None = None
    business_domain: str | None = None
    owner_department: str | None = None
    owner_user: str | None = None
    status: str | None = None
    supported_tasks: list[str] | None = None


class AgentOut(BaseModel):
    id: str
    agent_key: str
    name: str
    role: str
    business_domain: str | None
    owner_department: str | None
    status: str
    is_master: bool
    api_key: str | None = None
    """仅在创建/轮换时返回一次，列表接口中会置空。"""
    supported_tasks: list[str]

    model_config = {"from_attributes": True}
