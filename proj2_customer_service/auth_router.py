"""客户认证路由（proj2 用户侧，:8002）。

提供图形验证码、账号密码登录、登出与当前身份查询。
令牌为不透明字符串，随请求以 `Authorization: Bearer` 携带。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.auth import AuthError, AuthStore
from core.auth_deps import AuthContext, get_current_auth

router = APIRouter(prefix="/auth", tags=["认证"])

store = AuthStore()


class CustomerLoginRequest(BaseModel):
    """客户登录请求：账号 + 密码 + 图形验证码。"""

    username: str = Field(..., min_length=3, max_length=24, description="用户名")
    password: str = Field(..., min_length=6, max_length=64, description="密码")
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
    """生成客户登录用图形验证码。"""
    return await store.create_captcha()


@router.post("/login", response_model=TokenResponse)
async def login(req: CustomerLoginRequest) -> TokenResponse:
    """客户登录：先校验验证码，再校验账号密码，最后签发令牌。"""
    try:
        await store.verify_captcha(req.captcha_id, req.captcha_code)
        user = await store.verify_user_login(req.username, req.password)
        token = await store.issue_token("customer", user["user_id"], user["nickname"])
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
    """当前登录身份。"""
    data = await store.get_token(auth.token)
    return {
        "role": auth.role,
        "subject": auth.subject,
        "name": auth.name,
        "expires_in": data.get("expires_in", 0) if data else 0,
    }