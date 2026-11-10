"""会话状态机与 Redis 存储层。

本模块是会话 / 转人工队列 / 消息流的唯一合法写入口，
所有上层（proj2 用户 API、proj4 客服 API）都必须经由它操作数据，
键结构细节不外泄。

Redis 键约定：
    session:{id}              Hash    会话元数据（status / user_id / agent_id / 摘要 / 时间戳）
    session:{id}:messages     Stream  消息流（role / content / source / ts）
    queue:pending             ZSet    待接入队列，score = 优先级权重 + 入队时间戳
"""

import json
import time
import uuid
from enum import Enum

from loguru import logger

from config import settings
from core.redis_client import get_async_redis

PRIORITY_WEIGHTS = {"high": 1e12, "low": 0.0}


class SessionStatus(str, Enum):
    """会话状态机：ai_handling → pending_human → human_handling → closed。

    closed 会话可由客服选择"转回 AI"重新进入 ai_handling（保留上下文）。
    """

    AI_HANDLING = "ai_handling"
    PENDING_HUMAN = "pending_human"
    HUMAN_HANDLING = "human_handling"
    CLOSED = "closed"


def session_key(session_id: str) -> str:
    return f"session:{session_id}"


def messages_key(session_id: str) -> str:
    return f"session:{session_id}:messages"


class SessionStore:
    """会话存储封装：状态流转、消息流、待接入队列的原子操作。"""

    def __init__(self):
        self.redis = get_async_redis()

    # ==================== 会话元数据 ====================

    async def create_session(self, user_id: str) -> str:
        """创建 AI 接管中的新会话，返回会话 ID。"""
        session_id = uuid.uuid4().hex
        now = time.time()
        await self.redis.hset(
            session_key(session_id),
            mapping={
                "user_id": user_id,
                "status": SessionStatus.AI_HANDLING.value,
                "agent_id": "",
                "intent_summary": "",
                "title": "",
                "created_at": now,
                "updated_at": now,
            },
        )
        await self.redis.zadd(f"index:user_sessions:{user_id}", {session_id: now})
        logger.info("会话已创建: session={} user={}", session_id, user_id)
        return session_id

    async def get_session(self, session_id: str) -> dict | None:
        """读取会话元数据，不存在返回 None。"""
        data = await self.redis.hgetall(session_key(session_id))
        return data or None

    async def get_status(self, session_id: str) -> str:
        """读取会话状态，不存在视为 closed。"""
        status = await self.redis.hget(session_key(session_id), "status")
        return status or SessionStatus.CLOSED.value

    async def set_status(self, session_id: str, status: SessionStatus, agent_id: str = "") -> None:
        """更新会话状态（附带 updated_at 时间戳）。"""
        mapping = {"status": status.value, "updated_at": time.time()}
        if agent_id:
            mapping["agent_id"] = agent_id
        await self.redis.hset(session_key(session_id), mapping=mapping)
        logger.info("会话状态变更: session={} -> {}", session_id, status.value)

    async def update_context_summary(self, session_id: str, intent: str, tool_call_count: int) -> None:
        """刷新供客服接入时查看的上下文摘要。"""
        await self.redis.hset(
            session_key(session_id),
            mapping={
                "intent_summary": intent,
                "tool_call_count": tool_call_count,
                "updated_at": time.time(),
            },
        )

    # ==================== 消息流 ====================

    async def append_message(self, session_id: str, role: str, content: str, source: str) -> str:
        """追加消息到会话流，source 标记产生方（user / ai / human）。"""
        entry_id = await self.redis.xadd(
            messages_key(session_id),
            {"role": role, "content": content, "source": source, "ts": time.time()},
        )
        now = time.time()
        await self.redis.hset(session_key(session_id), "updated_at", now)
        meta = await self.redis.hmget(session_key(session_id), "title", "user_id", "agent_id")
        title, user_id, agent_id = meta
        if role == "user" and not title:
            await self.redis.hset(session_key(session_id), "title", content[:40])
        if user_id:
            await self.redis.zadd(f"index:user_sessions:{user_id}", {session_id: now})
        if agent_id:
            await self.redis.zadd(f"index:agent_sessions:{agent_id}", {session_id: now})
        return entry_id

    async def get_messages(self, session_id: str, count: int | None = None) -> list[dict]:
        """读取消息流；count 给定时返回最新 N 条（按时间正序）。"""
        if count:
            entries = await self.redis.xrevrange(messages_key(session_id), count=count)
            entries = list(reversed(entries))
        else:
            entries = await self.redis.xrange(messages_key(session_id))
        return [{"id": entry_id, **fields} for entry_id, fields in entries]

    async def get_context_messages(self, session_id: str) -> list[dict]:
        """转人工入队时携带的上下文快照（最近 N 条）。"""
        return await self.get_messages(session_id, count=settings.human_queue_context_messages)

    # ==================== 转人工队列 ====================

    async def enqueue_human(self, session_id: str, priority: str, context: list[dict]) -> None:
        """会话转入待接入队列（高优先级自动插队），并持久化上下文快照。"""
        weight = PRIORITY_WEIGHTS.get(priority, 0.0)
        await self.redis.zadd("queue:pending", {session_id: weight + time.time()})
        await self.redis.hset(
            session_key(session_id),
            mapping={
                "queue_priority": priority,
                "context_snapshot": json.dumps(context, ensure_ascii=False),
                "queued_at": time.time(),
            },
        )
        logger.info("会话转入人工队列: session={} priority={} 携带 {} 条上下文", session_id, priority, len(context))

    async def list_pending(self) -> list[dict]:
        """待接入队列（按优先级与排队时间排序），附带会话元数据。"""
        session_ids = await self.redis.zrange("queue:pending", 0, -1)
        pending = []
        for sid in session_ids:
            meta = await self.get_session(sid)
            if not meta:
                await self.redis.zrem("queue:pending", sid)
                continue
            pending.append(
                {
                    "session_id": sid,
                    "priority": meta.get("queue_priority", "low"),
                    "queued_at": float(meta.get("queued_at", 0)),
                    "waiting_seconds": round(time.time() - float(meta.get("queued_at", time.time()))),
                    "user_id": meta.get("user_id", ""),
                    "intent_summary": meta.get("intent_summary", ""),
                    "context_snapshot": json.loads(meta.get("context_snapshot", "[]")),
                }
            )
        return pending

    async def claim(self, session_id: str, agent_id: str) -> bool:
        """客服接入会话。

        以 ZREM 的返回值保证原子性：仅当调用方确实从队列移除了该会话
        才置为 human_handling，防止两名客服同时抢占同一会话。
        """
        removed = await self.redis.zrem("queue:pending", session_id)
        if not removed:
            return False
        await self.set_status(session_id, SessionStatus.HUMAN_HANDLING, agent_id=agent_id)
        await self.redis.zadd(f"index:agent_sessions:{agent_id}", {session_id: time.time()})
        return True

    # ==================== 历史会话 ====================

    async def _session_cards(self, session_ids: list[str]) -> list[dict]:
        """把会话 ID 列表转换为历史卡片（标题 / 状态 / 最近消息）。"""
        cards = []
        for sid in session_ids:
            meta = await self.get_session(sid)
            if not meta:
                continue
            recent = await self.get_messages(sid, count=1)
            last = recent[0] if recent else {}
            cards.append(
                {
                    "session_id": sid,
                    "title": meta.get("title") or "新会话",
                    "status": meta.get("status", "unknown"),
                    "user_id": meta.get("user_id", ""),
                    "agent_id": meta.get("agent_id", ""),
                    "updated_at": float(meta.get("updated_at", 0)),
                    "last_message": last.get("content", ""),
                    "last_source": last.get("source", ""),
                }
            )
        return cards

    async def list_user_sessions(self, user_id: str, limit: int = 30) -> list[dict]:
        """客户历史会话（按最近活动倒序）。"""
        session_ids = await self.redis.zrevrange(f"index:user_sessions:{user_id}", 0, limit - 1)
        return await self._session_cards(session_ids)

    async def list_agent_sessions(self, agent_id: str, limit: int = 30) -> list[dict]:
        """客服处理过的历史会话（按接入/活动时间倒序）。"""
        session_ids = await self.redis.zrevrange(f"index:agent_sessions:{agent_id}", 0, limit - 1)
        return await self._session_cards(session_ids)

    # ==================== 统计 ====================

    async def incr_stat(self, field: str, amount: int = 1) -> None:
        """按天累加运营统计计数（键 stats:{YYYYMMDD}）。"""
        day = time.strftime("%Y%m%d")
        await self.redis.hincrby(f"stats:{day}", field, amount)

    async def get_stats(self, day: str | None = None) -> dict:
        """读取当日（或指定日）统计计数。"""
        key = f"stats:{day or time.strftime('%Y%m%d')}"
        data = await self.redis.hgetall(key)
        return {k: int(v) for k, v in data.items()}
