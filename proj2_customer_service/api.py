"""智能客服 Agent 的 FastAPI 路由。

会话化 + 账号体系：
- POST /auth/*: 客户登录、验证码、登出、当前身份
- POST /chat: 以 session_id 串联多轮；服务端按会话状态路由，
  并要求客户令牌（客户身份取令牌 subject，越权会话一律 403）
- GET /chat/stream: SSE 实时推送（EventSource 以 ?token= 携带令牌）
- GET /my/tickets: 当前客户的申请单（包裹单号 / 状态 / 接单客服）
"""

import json
import re
import time

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from loguru import logger
from pydantic import BaseModel, Field

from core.auth import PACKAGE_NO_PATTERN
from core.auth_deps import AuthContext, require_customer
from core.redis_client import get_async_redis
from proj2_customer_service.applications import list_my_tickets
from proj2_customer_service.auth_router import router as auth_router
from proj2_customer_service.graph import cs_graph
from proj2_customer_service.store import (
    SessionStatus,
    SessionStore,
    messages_key,
)

app = FastAPI(title="多轮对话智能客服 Agent", version="3.0.0")
app.include_router(auth_router)

store = SessionStore()

STATUS_WAITING_REPLY = "已处理，正在等待人工客服介入"


class ChatRequest(BaseModel):
    """用户对话请求：单条消息 + 会话标识（缺省自动建会话）。"""

    message: str = Field(..., min_length=1, description="本轮用户输入")
    session_id: str | None = Field(default=None, description="会话 ID，缺省新建")
    user_id: str = Field(default="anonymous", min_length=1, description="用户唯一标识")


class ChatResponse(BaseModel):
    """客服回复响应。reply 为空表示本轮由人工处理 / 等待接入。"""

    session_id: str
    status: str = Field(..., description="会话当前状态")
    reply: str = Field(..., description="AI 回复；空字符串表示等待人工")
    intent: str = Field(..., description="本轮识别的意图")
    needs_human: bool = Field(..., description="是否已触发人工兜底")
    tool_call_count: int = Field(..., description="工具失败累计次数")


def _to_graph_messages(rows: list[dict]) -> list:
    """把存储层消息流转换为 LangGraph 需要的消息列表。"""
    return [
        HumanMessage(content=r["content"]) if r["role"] == "user" else AIMessage(content=r["content"])
        for r in rows
    ]


def _extract_package_no(text: str) -> str:
    """从用户消息中提取包裹 / 订单单号（如 ORD2024110015、SF1234567890）。"""
    for token in re.findall(r"[A-Za-z]{2,4}\d{6,24}", text or ""):
        if PACKAGE_NO_PATTERN.match(token):
            return token.upper()
    return ""


async def _link_ticket_to_customer(session_id: str, ticket_id: str, req: ChatRequest, intent: str) -> None:
    """AI 建单后回填客户归属、包裹单号，并维护会话 / 客户索引。"""
    r = get_async_redis()
    mapping = {"user_id": req.user_id, "session_id": session_id, "category": intent}
    package_no = _extract_package_no(req.message)
    if package_no and not await r.hget(f"ticket:{ticket_id}", "package_no"):
        mapping["package_no"] = package_no
    await r.hset(f"ticket:{ticket_id}", mapping=mapping)
    await r.zadd(f"index:user_tickets:{req.user_id}", {ticket_id: time.time()})
    await r.hset(f"session:{session_id}", "ticket_id", ticket_id)
    logger.info("工单 {} 已关联客户 {} / 会话 {}", ticket_id, req.user_id, session_id)


async def _route_ai(session_id: str, req: ChatRequest) -> ChatResponse:
    """AI 处理分支：历史进图 → 回复落流 → 转人工时入队。"""
    history = await store.get_messages(session_id)
    try:
        result = cs_graph.invoke(
            {"messages": _to_graph_messages(history), "user_id": req.user_id},
            config={"recursion_limit": 15},
        )
    except Exception as exc:
        logger.error("客服图执行失败: session={} error={}", session_id, exc)
        raise HTTPException(status_code=500, detail="客服服务内部错误")

    reply = next((m.content for m in reversed(result["messages"]) if isinstance(m, AIMessage)), "")
    intent = result.get("intent", "unknown")
    needs_human = result.get("needs_human", False)
    tool_call_count = result.get("tool_call_count", 0)

    await store.append_message(session_id, "assistant", reply, "ai")
    await store.update_context_summary(session_id, intent, tool_call_count)
    await store.incr_stat("total_sessions_ai_replied")

    # AI 建单回填归属：从回复中提取工单号，关联当前客户 / 会话（供工作台与我的申请展示）
    if intent == "create_ticket":
        ticket_match = re.search(r"TK\d+", reply)
        if ticket_match:
            await _link_ticket_to_customer(session_id, ticket_match.group(), req, intent)

    if needs_human:
        priority = "high" if intent in ("create_ticket", "human") else "low"
        context = await store.get_context_messages(session_id)
        await store.enqueue_human(session_id, priority=priority, context=context)
        await store.set_status(session_id, SessionStatus.PENDING_HUMAN)
        await store.incr_stat("transferred_human")

    return ChatResponse(
        session_id=session_id,
        status=await store.get_status(session_id),
        reply=reply,
        intent=intent,
        needs_human=needs_human,
        tool_call_count=tool_call_count,
    )


@app.get("/")
def root() -> dict:
    """服务欢迎页，提供可用端点导航。"""
    return {
        "service": "多轮对话智能客服 Agent",
        "docs": "/docs",
        "endpoints": {
            "POST /auth/login": "客户登录（账号密码 + 图形验证码）",
            "GET /auth/captcha": "图形验证码",
            "POST /chat": "会话化对话（需客户令牌，AI 知识库接地 / 人工）",
            "GET /chat/stream": "SSE 消息流推送（?token= 携带令牌）",
            "GET /my/sessions": "我的历史会话",
            "GET /my/sessions/{id}": "历史会话详情",
            "GET /my/tickets": "我的申请列表",
            "GET /health": "健康探针",
        },
    }


@app.get("/health")
async def health() -> dict:
    """健康探针（含 Redis 连通性）。"""
    try:
        await store.redis.ping()
        redis_ok = True
    except Exception as exc:
        logger.error("健康探针 Redis 检查失败: {}", exc)
        redis_ok = False
    return {"status": "ok", "service": "proj2_customer_service", "redis": redis_ok}


@app.get("/my/tickets")
async def my_tickets(auth: AuthContext = Depends(require_customer)) -> list[dict]:
    """当前客户提交的申请单（包裹单号 / 状态 / 接单客服）。"""
    return await list_my_tickets(auth.subject)


@app.get("/my/sessions")
async def my_sessions(auth: AuthContext = Depends(require_customer)) -> list[dict]:
    """当前客户的历史会话（按最近活动倒序）。"""
    return await store.list_user_sessions(auth.subject)


@app.get("/my/sessions/{session_id}")
async def my_session_detail(
    session_id: str, auth: AuthContext = Depends(require_customer)
) -> dict:
    """历史会话详情（元数据 + 全量消息），仅限会话所属客户。"""
    meta = await store.get_session(session_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    if meta.get("user_id") != auth.subject:
        raise HTTPException(status_code=403, detail="无权查看其他客户的会话")
    messages = await store.get_messages(session_id)
    return {"meta": meta, "messages": messages}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, auth: AuthContext = Depends(require_customer)) -> ChatResponse:
    """会话化对话入口：按会话状态把消息路由到 AI 或人工通道。"""
    # 客户端传入的 user_id 一律以令牌身份覆盖，防止冒用他人身份
    req = req.model_copy(update={"user_id": auth.subject})

    session_id = req.session_id
    if session_id:
        session = await store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
        if session.get("user_id") != auth.subject:
            raise HTTPException(status_code=403, detail="无权访问其他客户的会话")
    else:
        session_id = await store.create_session(req.user_id)

    status = await store.get_status(session_id)
    await store.append_message(session_id, "user", req.message, "user")
    await store.incr_stat("total_user_messages")

    if status == SessionStatus.HUMAN_HANDLING.value:
        # 人工处理中：消息直通消息流，绝不经过 LLM
        logger.info("消息直通人工: session={}", session_id)
        return ChatResponse(
            session_id=session_id, status=status, reply="",
            intent="human", needs_human=True, tool_call_count=0,
        )

    if status == SessionStatus.PENDING_HUMAN.value:
        # 已在队列：提示等待，并把用户追问升级为高优先级
        await store.enqueue_human(
            session_id, priority="high", context=await store.get_context_messages(session_id)
        )
        await store.append_message(session_id, "assistant", STATUS_WAITING_REPLY, "ai")
        return ChatResponse(
            session_id=session_id, status=status, reply=STATUS_WAITING_REPLY,
            intent="human", needs_human=True, tool_call_count=0,
        )

    if status == SessionStatus.CLOSED.value:
        return ChatResponse(
            session_id=session_id, status=status,
            reply="本会话已结束，请刷新页面开启新会话。",
            intent="unknown", needs_human=False, tool_call_count=0,
        )

    return await _route_ai(session_id, req)


@app.get("/chat/stream")
async def chat_stream(
    request: Request,
    session_id: str,
    last_id: str = "0",
    auth: AuthContext = Depends(require_customer),
) -> StreamingResponse:
    """SSE 推流：阻塞读取消息 Stream，推送新消息及会话状态。

    客户端以 last_id 续传（EventSource 重连时带回最后收到的事件 ID）；
    鉴权令牌以 ?token= 携带，并校验会话归属。
    """
    session = await store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    if session.get("user_id") != auth.subject:
        raise HTTPException(status_code=403, detail="无权订阅其他客户的会话")

    async def event_generator():
        cursor = last_id or "0"
        while True:
            if await request.is_disconnected():
                logger.info("SSE 客户端断开: session={}", session_id)
                break
            results = await store.redis.xread(
                {messages_key(session_id): cursor}, block=10000, count=20
            )
            if not results:
                yield ": keep-alive\n\n"
                continue
            for _, entries in results:
                for entry_id, fields in entries:
                    cursor = entry_id
                    payload = json.dumps(
                        {"id": entry_id, "status": await store.get_status(session_id), **fields},
                        ensure_ascii=False,
                    )
                    yield f"id: {entry_id}\ndata: {payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
