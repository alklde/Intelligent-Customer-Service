"""工单管理业务：列表 / 详情 / 状态流转。"""

import time

from loguru import logger

from core.redis_client import get_async_redis

TICKET_STATUSES = ("open", "processing", "resolved", "closed")

_TICKET_FIELDS = (
    "ticket_id",
    "issue_desc",
    "package_no",
    "priority",
    "status",
    "source",
    "user_id",
    "agent_id",
    "category",
    "session_id",
    "resolution",
    "created_at",
    "updated_at",
)


def _public(data: dict) -> dict:
    """工单哈希转白名单结构（避免内部字段外泄）。"""
    return {field: data.get(field, "") for field in _TICKET_FIELDS}


async def list_tickets(status: str | None = None, agent_id: str | None = None, limit: int = 100) -> list[dict]:
    """按创建时间倒序列出工单，可按状态 / 接单客服过滤。"""
    r = get_async_redis()
    if agent_id:
        ticket_ids = await r.zrevrange(f"index:agent_tickets:{agent_id}", 0, limit - 1)
    else:
        ticket_ids = await r.zrevrange("index:tickets", 0, limit - 1)
    tickets = []
    for tid in ticket_ids:
        data = await r.hgetall(f"ticket:{tid}")
        if not data:
            continue
        if status and data.get("status") != status:
            continue
        if agent_id and data.get("agent_id") != agent_id:
            continue
        tickets.append(_public(data))
    return tickets


async def get_ticket(ticket_id: str) -> dict | None:
    """工单详情。"""
    data = await get_async_redis().hgetall(f"ticket:{ticket_id}")
    return _public(data) if data else None


async def patch_ticket(ticket_id: str, status: str) -> dict | None:
    """工单状态流转（open → processing → resolved / closed）。"""
    r = get_async_redis()
    key = f"ticket:{ticket_id}"
    if not await r.exists(key):
        return None
    await r.hset(key, mapping={"status": status, "updated_at": time.time()})
    logger.info("工单状态流转: ticket={} -> {}", ticket_id, status)
    data = await r.hgetall(key)
    return _public(data)


async def assign_ticket_agent(ticket_id: str, agent_id: str, status: str | None = None) -> None:
    """回填工单的接单客服（会话接入时调用），维护客服接单索引。"""
    r = get_async_redis()
    mapping = {"agent_id": agent_id, "updated_at": time.time()}
    if status:
        mapping["status"] = status
    await r.hset(f"ticket:{ticket_id}", mapping=mapping)
    await r.zadd(f"index:agent_tickets:{agent_id}", {ticket_id: time.time()})
    logger.info("工单接单客服回填: ticket={} agent={}", ticket_id, agent_id)
