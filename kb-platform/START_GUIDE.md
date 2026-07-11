# 项目启动与数据导入指南

## 前置条件

1. **Python 版本**: 3.11+ (重要!)
2. **Docker 与 Docker Compose** (用于数据库)
3. **Git** (可选，用于版本控制)

---

## 快速开始

### 方式一: 自动启动脚本（推荐）

```bash
# 1. 复制环境配置
cp .env.example .env

# 2. 查看并编辑 .env (可选)
# 根据需要修改配置

# 3. 使用启动脚本
python scripts/start.py  # (需先创建此脚本)
```

### 方式二: 手动启动步骤

#### 步骤 1: 设置 Python 环境

```bash
# 检查 Python 版本
python --version  # 应该是 3.11+

# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# 升级 pip
python -m pip install --upgrade pip
```

#### 步骤 2: 安装依赖

```bash
# 安装项目依赖
pip install -e .

# 或使用 uv (更快)
pip install uv
uv pip install -e .
```

#### 步骤 3: 配置环境变量

```bash
# 复制配置文件
cp .env.example .env

# 编辑 .env 文件，根据需要调整配置
# 主要配置项:
# - DATABASE_URL: 数据库连接
# - REDIS_URL: Redis 连接
# - OPENAI_API_KEY: OpenAI API Key (可选)
```

#### 步骤 4: 启动数据库

```bash
# 使用 Docker Compose 启动数据库
docker-compose up -d

# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f
```

#### 步骤 5: 初始化数据

```bash
# 运行种子数据脚本
python -m app.seeds.seed_data

# 这将创建:
# - 数据库表结构
# - 7个业务 Agent + 1个主控 Agent
# - 6个知识库（含文档）
# - 8个 Skills
# - 6个 Prompts
# - 多个 Tools (包括新迁移的工具)
# - 完整的权限配置
# - 策略配置
```

#### 步骤 6: 启动服务

```bash
# 开发模式（自动重启）
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 或生产模式
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

#### 步骤 7: 验证服务

```bash
# 检查健康检查端点
curl http://localhost:8000/api/v1/health

# 应该返回:
# {"status": "ok"}
```

---

## 访问应用

### 管理后台
打开浏览器访问: `http://localhost:8000/admin`

### API 文档
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

---

## 验证数据导入

### 检查数据库表

可以使用数据库管理工具（如 pgAdmin, DBeaver）连接数据库查看。

默认连接信息:
- Host: `localhost`
- Port: `5432` (PostgreSQL)
- Database: `kb_platform`
- User: `kb_user`
- Password: `kb_password`

### 验证数据

```python
# 在 Python 中验证
import asyncio
from sqlalchemy import select
from app.core.db import AsyncSessionLocal
from app.models.capability import Capability
from app.models.agent import Agent
from app.models.knowledge import KnowledgeBase

async def verify_data():
    async with AsyncSessionLocal() as db:
        # 检查 Agents
        agents = await db.execute(select(Agent))
        print(f"Agents: {len(agents.scalars().all())}")

        # 检查 Capabilities
        caps = await db.execute(select(Capability))
        print(f"Capabilities: {len(caps.scalars().all())}")

        # 检查 Tools
        tools = await db.execute(select(Capability).where(Capability.type == "tool"))
        print(f"Tools: {len(tools.scalars().all())}")

        # 检查 Knowledge Bases
        kbs = await db.execute(select(KnowledgeBase))
        print(f"Knowledge Bases: {len(kbs.scalars().all())}")

asyncio.run(verify_data())
```

---

## 测试新工具功能

### 1. 发现可用工具

```bash
curl http://localhost:8000/api/v1/tools/discover
```

应该返回包含以下工具的列表：
- `tool_forbidden_word_check` - 违禁词检测
- `tool_text_analysis` - 文本分析
- `tool_data_format` - 数据格式化
- `tool_sentiment_analysis` - 情感分析

### 2. 批量注册工具

```bash
curl -X POST http://localhost:8000/api/v1/tools/batch-register \
  -H "Content-Type: application/json"
```

### 3. 调用工具

```bash
# 首先获取工具的 capability_id
# 然后调用:

curl -X POST http://localhost:8000/api/v1/capabilities/{capability_id}/invoke \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "text": "这是一段测试文本，包含绝对和最高级违禁词",
      "check_level": "normal"
    }
  }'
```

---

## 常见问题

### Q: Python 版本不够怎么办？

A: 安装 Python 3.11 或更高版本
- Windows: 从 python.org 下载
- Mac: `brew install python@3.11`
- Linux: 使用 pyenv 或系统包管理器

### Q: Docker 没有安装？

A:
- Windows/Mac: 安装 Docker Desktop
- Linux: 安装 Docker Engine + Docker Compose

或者使用本地 SQLite（需修改配置）

### Q: 端口被占用？

A: 修改端口:
```bash
uvicorn app.main:app --reload --port 8080
```

### Q: 种子数据运行失败？

A:
1. 确认数据库已启动
2. 检查数据库连接配置
3. 删除旧的数据库容器重新开始:
```bash
docker-compose down -v
docker-compose up -d
```

### Q: 工具功能不可用？

A:
1. 确认工具已注册到数据库
2. 检查工具状态是否为 "published"
3. 查看后端日志:
```bash
docker-compose logs -f
```

---

## 开发模式

### 运行测试

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest
```

### 代码格式检查

```bash
# 使用 black 格式化
black app/

# 使用 ruff 检查
ruff check app/
```

---

## 生产部署

### 使用 Gunicorn

```bash
pip install gunicorn
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

### 使用 Docker 部署

```bash
# 构建镜像
docker build -t kb-platform .

# 运行容器
docker run -p 8000:8000 --env-file .env kb-platform
```

---

## 下一步

1. ✅ 服务已启动
2. ✅ 数据已导入
3. 👉 访问管理后台: `http://localhost:8000/admin`
4. 👉 尝试注册新工具
5. 👉 测试工具调用
6. 👉 探索其他功能

---

**需要帮助?** 查看项目文档或联系技术支持！
