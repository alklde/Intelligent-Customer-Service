"""客服认证路由（proj4 客服侧，:8004）。

客服以「工号 + 密钥」登录，令牌与客户体系同构（不透明令牌 + Redis 会话）。
角色为 agent / admin，管理员在客服界面登录后可进入数据库管理页。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.auth import AuthError, AuthStore
from core.auth_deps import AuthContext, get_current_auth

router = APIRouter(prefix="/auth", tags=["认证"])

store = AuthStore()


class StaffLoginRequest(BaseModel):
    """客服登录请求：工号 + 密钥 + 图形验证码。"""

    employee_id: str = Field(..., min_length=3, max_length=24, description="客服工号")
    secret: str = Field(..., min_length=8, max_length=64, description="登录密钥")
    captcha_id: str = Field(..., min_length=8, description="验证码 ID")
    captcha_code: str = Field(..., min_length=1, max_length=8, description="验证码")


class TokenResponse(BaseModel):
    """登录成功后的令牌与身份信息。"""

    token: str
    role: str
    subject: str
    name: str
    expires_in: int


def _to_http(exc: AuthError) -> HTTPException:
    """把认证业务异常转换为 HTTP 异常。"""
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/captcha")
async def captcha() -> dict:
    """生成客服登录用图形验证码。"""
    return await store.create_captcha()


@router.post("/login", response_model=TokenResponse)
async def login(req: StaffLoginRequest) -> TokenResponse:
    """客服登录：先校验验证码，再校验工号密钥，最后签发令牌。"""
    try:
        await store.verify_captcha(req.captcha_id, req.captcha_code)
        agent = await store.verify_agent_login(req.employee_id, req.secret)
        token = await store.issue_token(agent["role"], agent["employee_id"], agent["name"])
        return TokenResponse(**token)
    except AuthError as exc:
        raise _to_http(exc)


@router.post("/logout")
async def logout(auth: AuthContext = Depends(get_current_auth)) -> dict:
    """登出：撤销当前令牌。"""
    await store.revoke_token(auth.token)
    return {"ok": True}


@router.get("/me")
async def me(auth: AuthContext = Depends(get_current_auth)) -> dict:
    """当前登录身份（含角色，前端据此渲染管理员入口）。"""
    data = await store.get_token(auth.token)
    return {
        "role": auth.role,
        "subject": auth.subject,
        "name": auth.name,
        "expires_in": data.get("expires_in", 0) if data else 0,
    }