"""客服工作台后台服务 (proj4_admin, :8004)。

面向人工客服 / 管理员的 API：
- 认证：工号 + 密钥登录、图形验证码、登出
- 会话队列：待接入列表、抢占接入、人工回复、关闭（身份取自令牌）
- 工单管理：列表、详情、状态流转
- 运营统计：当日指标汇总
- 管理员：客户 / 客服账号的数据库管理（仅 admin）

权限：除认证与初始化接口外，全部要求客服令牌（agent / admin）；
`/admin/*` 要求 admin 角色。
"""

from fastapi import Depends, FastAPI, HTTPException
from loguru import logger

from core.auth_deps import AuthContext, require_staff
from proj4_admin import sessions, tickets
from proj4_admin.admin_db import router as admin_router
from proj4_admin.auth_router import router as auth_router
from proj4_admin.schemas import ClaimRequest, CloseRequest, ReplyRequest, TicketPatch

app = FastAPI(title="客服工作台后台", version="2.0.0")
app.include_router(auth_router)
app.include_router(admin_router)


@app.get("/")
def root() -> dict:
    """服务欢迎页。"""
    return {
        "service": "客服工作台后台",
        "docs": "/docs",
        "endpoints": {
            "POST /auth/login": "客服登录（工号 + 密钥 + 图形验证码）",
            "GET /sessions/pending": "待接入队列",
            "POST /sessions/{id}/claim": "接入会话",
            "POST /sessions/{id}/reply": "人工回复",
            "POST /sessions/{id}/close": "关闭会话",
            "GET /tickets": "工单列表",
            "GET /stats/today": "运营统计",
            "GET /admin/users": "管理员：客户账号管理",
        },
    }


@app.get("/health")
async def health() -> dict:
    """健康探针。"""
    try:
        await sessions.store.redis.ping()
        redis_ok = True
    except Exception as exc:
        logger.error("健康探针 Redis 检查失败: {}", exc)
        redis_ok = False
    return {"status": "ok", "service": "proj4_admin", "redis": redis_ok}


# ==================== 会话队列 ====================


@app.get("/sessions/pending")
async def pending_sessions(_auth: AuthContext = Depends(require_staff)) -> list[dict]:
    """待接入会话队列。"""
    return await sessions.list_pending_sessions()


@app.get("/sessions/history")
async def session_history(auth: AuthContext = Depends(require_staff)) -> list[dict]:
    """当前客服处理过的历史会话（用于工作台恢复上下文）。"""
    return await sessions.list_agent_history(auth.subject)


@app.get("/sessions/{session_id}")
async def session_detail(
    session_id: str, _auth: AuthContext = Depends(require_staff)
) -> dict:
    """会话详情（元数据 + 全量消息）。"""
    detail = await sessions.get_session_detail(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"会话不存在: {session_id}")
    return detail


@app.post("/sessions/{session_id}/claim")
async def claim_session(
    session_id: str, req: ClaimRequest, auth: AuthContext = Depends(require_staff)
) -> dict:
    """接入会话（原子抢占，身份取令牌工号）。"""
    if req.agent_id and req.agent_id != auth.subject:
        raise HTTPException(status_code=403, detail="工号与登录身份不一致")
    result = await sessions.claim_session(session_id, auth.subject)
    if not result["ok"]:
        raise HTTPException(status_code=409, detail=result["detail"])
    return result


@app.post("/sessions/{session_id}/reply")
async def reply_session(
    session_id: str, req: ReplyRequest, auth: AuthContext = Depends(require_staff)
) -> dict:
    """人工回复（写入消息流，用户端 SSE 实时接收）。"""
    if req.agent_id and req.agent_id != auth.subject:
        raise HTTPException(status_code=403, detail="工号与登录身份不一致")
    result = await sessions.human_reply(session_id, auth.subject, req.content)
    if not result["ok"]:
        raise HTTPException(status_code=409, detail=result["detail"])
    return result


@app.post("/sessions/{session_id}/close")
async def close_session(
    session_id: str, req: CloseRequest, auth: AuthContext = Depends(require_staff)
) -> dict:
    """关闭会话（可标记已解决 / badcase）或转回 AI 接管。"""
    if req.agent_id and req.agent_id != auth.subject:
        raise HTTPException(status_code=403, detail="工号与登录身份不一致")
    result = await sessions.close_session(
        session_id, auth.subject, req.resolve, req.mark_badcase, req.action
    )
    if not result["ok"]:
        raise HTTPException(status_code=409, detail=result["detail"])
    return result


# ==================== 工单管理 ====================


@app.get("/tickets")
async def list_tickets(
    status: str | None = None,
    agent_id: str | None = None,
    _auth: AuthContext = Depends(require_staff),
) -> list[dict]:
    """工单列表（可按状态 / 接单客服过滤）。"""
    return await tickets.list_tickets(status=status, agent_id=agent_id)


@app.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: str, _auth: AuthContext = Depends(require_staff)) -> dict:
    """工单详情。"""
    ticket = await tickets.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"工单不存在: {ticket_id}")
    return ticket


@app.patch("/tickets/{ticket_id}")
async def patch_ticket(
    ticket_id: str, req: TicketPatch, _auth: AuthContext = Depends(require_staff)
) -> dict:
    """工单状态流转。"""
    ticket = await tickets.patch_ticket(ticket_id, req.status)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"工单不存在: {ticket_id}")
    return ticket


# ==================== 运营统计 ====================


@app.get("/stats/today")
async def today_stats(_auth: AuthContext = Depends(require_staff)) -> dict:
    """当日运营统计汇总。"""
    return await sessions.today_stats()