"""FastAPI 认证依赖：Bearer 令牌解析与角色校验。

路由层通过 Depends 注入身份上下文：
    auth = Depends(require_customer)   # 仅客户
    auth = Depends(require_staff)      # 客服 / 管理员
    auth = Depends(require_admin)      # 仅管理员
SSE（EventSource 无法自定义请求头）场景允许以 ?token= 查询参数携带令牌。
"""

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel

from core.auth import AuthStore


class AuthContext(BaseModel):
    """已认证的请求身份。"""

    token: str
    role: str
    subject: str
    name: str


_store = AuthStore()


def _extract_token(request: Request) -> str:
    """从 Authorization: Bearer 或 ?token= 中提取令牌。"""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        if token:
            return token
    return (request.query_params.get("token") or "").strip()


async def get_current_auth(request: Request) -> AuthContext:
    """解析并校验当前请求令牌，无效抛 401。"""
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="未登录，请先登录")
    data = await _store.get_token(token)
    if not data:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return AuthContext(
        token=token,
        role=data.get("role", ""),
        subject=data.get("subject", ""),
        name=data.get("name", ""),
    )


def require_roles(*roles: str):
    """生成角色校验依赖：令牌角色不在允许集合内时抛 403。"""

    async def dependency(auth: AuthContext = Depends(get_current_auth)) -> AuthContext:
        if auth.role not in roles:
            raise HTTPException(status_code=403, detail="无权访问该资源")
        return auth

    return dependency


require_customer = require_roles("customer")
require_staff = require_roles("agent", "admin")
require_admin = require_roles("admin")
require_any = require_roles("customer", "agent", "admin")