"""会话队列业务：待接入列表 / 抢占接入 / 人工回复 / 关闭 / 详情 / 统计。

所有写操作经由 proj2 的 SessionStore 完成，保证与用户侧 API
操作同一份数据与状态机，无跨服务直连 Redis 的写路径。
"""

import time

from loguru import logger

from core.auth import AuthStore
from proj2_customer_service.store import SessionStatus, SessionStore

from proj4_admin.tickets import assign_ticket_agent

store = SessionStore()
auth_store = AuthStore()

AGENT_GREETING = "您好，我是人工客服{name}（工号 {agent_id}），很高兴为您服务，请问有什么可以帮您？"


async def _ticket_of_session(session_id: str) -> str:
    """读取会话关联的工单号（AI 建单时回填），无则返回空串。"""
    meta = await store.get_session(session_id)
    return (meta or {}).get("ticket_id", "")


async def list_pending_sessions() -> list[dict]:
    """待接入队列（优先级 + 排队时长排序）。"""
    return await store.list_pending()


async def list_agent_history(agent_id: str) -> list[dict]:
    """当前客服处理过的历史会话（接入/最近活动倒序）。"""
    return await store.list_agent_sessions(agent_id)


async def claim_session(session_id: str, agent_id: str) -> dict:
    """接入会话：原子抢占，失败说明已被他人接入或已离队。"""
    claimed = await store.claim(session_id, agent_id)
    if not claimed:
        return {"ok": False, "detail": "会话已被其他客服接入或已离队"}
    await store.incr_stat("sessions_claimed")
    # 关联工单回填接单客服，状态进入 processing
    ticket_id = await _ticket_of_session(session_id)
    if ticket_id:
        await assign_ticket_agent(ticket_id, agent_id, status="processing")
    # 接入即发送预设问候语，客户 SSE 实时可见
    agent = await auth_store.get_agent(agent_id)
    display_name = (agent or {}).get("name") or agent_id
    greeting = AGENT_GREETING.format(name=display_name, agent_id=agent_id)
    await store.append_message(session_id, "assistant", greeting, "human")
    await store.incr_stat("human_replies")
    logger.info("客服接入会话并发送问候: agent={} session={}", agent_id, session_id)
    return {"ok": True, "detail": "接入成功", "greeting": greeting}


async def human_reply(session_id: str, agent_id: str, content: str) -> dict:
    """人工回复：写入消息流（source=human），用户端 SSE 实时可见。"""
    status = await store.get_status(session_id)
    if status != SessionStatus.HUMAN_HANDLING.value:
        return {"ok": False, "detail": f"会话状态为 {status}，不允许人工回复"}
    await store.append_message(session_id, "assistant", content, "human")
    await store.incr_stat("human_replies")
    logger.info("人工回复: agent={} session={}", agent_id, session_id)
    return {"ok": True, "detail": "已发送"}


async def close_session(session_id: str, agent_id: str, resolve: bool, mark_badcase: bool, action: str = "close") -> dict:
    """关闭会话或转回 AI 接管（可标记已解决 / badcase）。"""
    status = await store.get_status(session_id)
    if status == SessionStatus.CLOSED.value:
        return {"ok": False, "detail": "会话已是关闭状态"}

    if status == SessionStatus.PENDING_HUMAN.value:
        # 离开队列（转回 AI 或关闭都不再排队）
        await store.redis.zrem("queue:pending", session_id)

    if action == "reopen":
        await store.set_status(session_id, SessionStatus.AI_HANDLING)
        logger.info("会话转回 AI 接管: agent={} session={}", agent_id, session_id)
        return {"ok": True, "detail": "会话已转回 AI 接管"}

    await store.set_status(session_id, SessionStatus.CLOSED)
    if resolve:
        await store.incr_stat("sessions_resolved")
    # 关联工单同步收敛状态
    ticket_id = await _ticket_of_session(session_id)
    if ticket_id:
        await assign_ticket_agent(ticket_id, agent_id, status="resolved" if resolve else "processing")
    if mark_badcase:
        await store.redis.hset(f"session:{session_id}", "badcase", "1")
        await store.incr_stat("badcases")
        # badcase 自动沉淀：人工给出的正确答案写入评测集，形成回归闭环
        from proj3_eval_platform.evaluator import append_badcase_to_dataset

        await append_badcase_to_dataset(session_id)
        logger.info("会话标记 badcase: session={}", session_id)
    logger.info("会话关闭: agent={} session={} resolve={}", agent_id, session_id, resolve)
    return {"ok": True, "detail": "会话已关闭"}


async def get_session_detail(session_id: str) -> dict | None:
    """会话详情（元数据 + 全量消息），供工作台打开会话时渲染。"""
    meta = await store.get_session(session_id)
    if not meta:
        return None
    messages = await store.get_messages(session_id)
    return {"meta": meta, "messages": messages}


async def today_stats() -> dict:
    """当日运营统计。"""
    stats = await store.get_stats()
    return {
        "total_user_messages": stats.get("total_user_messages", 0),
        "total_sessions_ai_replied": stats.get("total_sessions_ai_replied", 0),
        "transferred_human": stats.get("transferred_human", 0),
        "sessions_claimed": stats.get("sessions_claimed", 0),
        "sessions_resolved": stats.get("sessions_resolved", 0),
        "human_replies": stats.get("human_replies", 0),
        "tickets_created": stats.get("tickets_created", 0),
        "badcases": stats.get("badcases", 0),
        "pending_queue_size": len(await store.list_pending()),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
