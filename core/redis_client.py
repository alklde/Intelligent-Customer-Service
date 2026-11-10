"""Redis 连接工厂。

提供同步 / 异步两种客户端：异步用于 FastAPI 路由与会话存储，
同步用于在线程池中执行的 Mock 工具（如 create_ticket 落库）。
"""

from functools import lru_cache

import redis as sync_redis
import redis.asyncio as aioredis
from loguru import logger

from config import settings


@lru_cache
def get_async_redis() -> aioredis.Redis:
    """进程级单例异步客户端（decode_responses=True，统一返回 str）。"""
    client = aioredis.from_url(settings.redis_url, decode_responses=True)
    logger.debug("异步 Redis 客户端就绪: {}", settings.redis_url)
    return client


@lru_cache
def get_sync_redis() -> sync_redis.Redis:
    """同步客户端，供线程池中的工具函数使用。"""
    return sync_redis.Redis.from_url(settings.redis_url, decode_responses=True)
