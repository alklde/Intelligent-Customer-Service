"""管理员数据库管理接口（仅 admin 角色可访问，初始化接口除外）。

- GET  /admin/status       系统是否已初始化（登录页/初始化表单使用）
- POST /admin/init         首次初始化管理员（校验引导密钥，仅一次）
- CRUD /admin/users        客户账号
- CRUD /admin/agents       客服账号
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.auth import AuthError, AuthStore
from core.auth_deps import require_admin

router = APIRouter(prefix="/admin", tags=["数据库管理"])

store = AuthStore()


class InitAdminRequest(BaseModel):
    """首次初始化管理员：工号 + 密钥 + 引导密钥。"""

    employee_id: str = Field(..., min_length=3, max_length=24)
    secret: str = Field(..., min_length=8, max_length=64)
    name: str = Field(default="系统管理员", max_length=32)
    bootstrap_key: str = Field(..., min_length=1, description="配置中的初始化引导密钥")


class CreateUserRequest(BaseModel):
    """创建客户账号。"""

    username: str = Field(..., min_length=3, max_length=24)
    password: str = Field(..., min_length=6, max_length=64)
    nickname: str = Field(default="", max_length=32)
    phone: str = Field(default="", max_length=20)


class UpdateUserRequest(BaseModel):
    """更新客户账号（字段均可选）。"""

    password: str | None = Field(default=None, min_length=6, max_length=64)
    nickname: str | None = Field(default=None, max_length=32)
    phone: str | None = Field(default=None, max_length=20)
    status: Literal["active", "disabled"] | None = None


class CreateAgentRequest(BaseModel):
    """创建客服账号。"""

    employee_id: str = Field(..., min_length=3, max_length=24)
    secret: str = Field(..., min_length=8, max_length=64)
    name: str = Field(..., min_length=1, max_length=32)
    role: Literal["agent", "admin"] = "agent"


class UpdateAgentRequest(BaseModel):
    """更新客服账号（字段均可选）。"""

    secret: str | None = Field(default=None, min_length=8, max_length=64)
    name: str | None = Field(default=None, max_length=32)
    role: Literal["agent", "admin"] | None = None
    status: Literal["active", "disabled"] | None = None


def _to_http(exc: AuthError) -> HTTPException:
    """把认证业务异常转换为 HTTP 异常。"""
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/status")
async def status() -> dict:
    """系统初始化状态（公开：仅暴露布尔值）。"""
    initialized = await store.admin_exists() or bool(await store.redis.exists("auth:bootstrapped"))
    return {"initialized": initialized, "bootstrap_required": not initialized}


@router.post("/init")
async def init_admin(req: InitAdminRequest) -> dict:
    """首次初始化管理员（校验引导密钥；已初始化返回 409）。"""
    try:
        agent = await store.init_admin(req.employee_id, req.secret, req.name, req.bootstrap_key)
        return {"ok": True, "agent": agent}
    except AuthError as exc:
        raise _to_http(exc)


# ==================== 客户账号 ====================


@router.get("/users")
async def list_users(_auth=Depends(require_admin)) -> list[dict]:
    """客户账号列表（脱敏）。"""
    return await store.list_users()


@router.post("/users")
async def create_user(req: CreateUserRequest, _auth=Depends(require_admin)) -> dict:
    """创建客户账号。"""
    try:
        return await store.create_user(req.username, req.password, req.nickname, req.phone)
    except AuthError as exc:
        raise _to_http(exc)


@router.patch("/users/{user_id}")
async def update_user(user_id: str, req: UpdateUserRequest, _auth=Depends(require_admin)) -> dict:
    """更新客户账号（重置密码 / 启停用）。"""
    try:
        return await store.update_user(
            user_id, password=req.password, nickname=req.nickname, phone=req.phone, status=req.status
        )
    except AuthError as exc:
        raise _to_http(exc)


# ==================== 客服账号 ====================


@router.get("/agents")
async def list_agents(_auth=Depends(require_admin)) -> list[dict]:
    """客服账号列表（脱敏）。"""
    return await store.list_agents()


@router.post("/agents")
async def create_agent(req: CreateAgentRequest, _auth=Depends(require_admin)) -> dict:
    """创建客服 / 管理员账号。"""
    try:
        return await store.create_agent(req.employee_id, req.secret, req.name, req.role)
    except AuthError as exc:
        raise _to_http(exc)


@router.patch("/agents/{employee_id}")
async def update_agent(employee_id: str, req: UpdateAgentRequest, _auth=Depends(require_admin)) -> dict:
    """更新客服账号（重置密钥 / 角色 / 启停用）。"""
    try:
        return await store.update_agent(
            employee_id, secret=req.secret, name=req.name, role=req.role, status=req.status
        )
    except AuthError as exc:
        raise _to_http(exc)