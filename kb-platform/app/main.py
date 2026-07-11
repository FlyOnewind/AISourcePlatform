"""FastAPI 应用入口：中间件(trace_id)、路由挂载、静态管理后台、启动建表。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1 import agents, audit, capabilities, health, integration, knowledge, prompts, skills, tools
from app.core.config import get_settings
from app.core.db import create_all_tables
from app.core.security import generate_trace_id


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_all_tables()
    yield


settings = get_settings()

app = FastAPI(
    title="AI知识库管理中台",
    description="企业级AI资产统一治理、注册、检索、调用、评估、审计与复用平台（V1 本地可运行版）",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-ID") or generate_trace_id()
    task_id = request.headers.get("X-Task-ID")
    request.state.trace_id = trace_id
    request.state.task_id = task_id
    response = await call_next(request)
    response.headers["X-Trace-ID"] = trace_id
    return response


app.include_router(health.router)
app.include_router(agents.router)
app.include_router(capabilities.router)
app.include_router(integration.router)
app.include_router(knowledge.router)
app.include_router(skills.router)
app.include_router(prompts.router)
app.include_router(audit.router)
app.include_router(tools.router)

app.mount("/admin", StaticFiles(directory="admin_console", html=True), name="admin")
