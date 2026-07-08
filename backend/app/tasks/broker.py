"""Dramatiq Redis broker 配置。

必须在 import actor 之前设置 broker，因此 app.tasks.__init__ 先导入本模块。
"""

import logging

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.core.config import settings

logger = logging.getLogger(__name__)

redis_broker = RedisBroker(url=settings.redis_url)
"""Redis broker 实例，用于 Dramatiq 任务入队和消费。"""

dramatiq.set_broker(redis_broker)

logger.info("Dramatiq Redis broker 已配置: %s", settings.redis_url)
