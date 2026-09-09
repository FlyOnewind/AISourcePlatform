"""Dramatiq 任务模块 — broker 配置 + actor 注册。

导入顺序：broker 先于 actor，确保 set_broker() 在 @dramatiq.actor 装饰器之前执行。
"""

from app.tasks.broker import redis_broker  # noqa: F401  # 必须最先导入
from app.tasks.ingest import ingest_document  # noqa: F401
