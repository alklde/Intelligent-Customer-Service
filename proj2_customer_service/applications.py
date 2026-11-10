"""客户申请（工单）查询：只返回当前登录客户自己的申请记录。"""

from core.redis_client import get_async_redis

_TICKET_FIELDS = (
    "ticket_id",
    "issue_desc",
    "package_no",
    "priority",
    "status",
    "user_id",
    "agent_id",
    "category",
    "resolution",
    "created_at",
    "updated_at",
)


async def list_my_tickets(user_id: str, limit: int = 50) -> list[dict]:
    """按创建时间倒序返回客户的申请单（包裹单号 / 状态 / 接单客服）。"""
    r = get_async_redis()
    ticket_ids = await r.zrevrange(f"index:user_tickets:{user_id}", 0, limit - 1)
    tickets = []
    for tid in ticket_ids:
        data = await r.hgetall(f"ticket:{tid}")
        if not data or data.get("user_id") != user_id:
            continue
        tickets.append({field: data.get(field, "") for field in _TICKET_FIELDS})
    return tickets