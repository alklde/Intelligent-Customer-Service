"""认证核心：账号存储、密码哈希、图形验证码与不透明令牌。

职责边界：
- 本模块是账号数据（客户 / 客服）的唯一合法读写入口；
- 路由层只通过 AuthStore 的方法操作账号，不直接拼接 Redis 键；
- 密码与密钥仅以 bcrypt 哈希形式落库，任何返回结构都不包含哈希字段。

Redis 键约定（详见 docs/design_auth.md）：
    auth:user:{user_id}        Hash    客户账号
    auth:user:name:{username}  String  用户名唯一索引 -> user_id
    index:users                ZSet    客户列表索引（score=created_at）
    auth:agent:{employee_id}   Hash    客服账号（工号即主键）
    index:agents               ZSet    客服列表索引（score=created_at）
    auth:captcha:{id}          String  验证码答案（TTL 120s，一次性）
    auth:token:{token}         Hash    令牌会话（TTL 按角色区分）
    auth:fail:{identity}       String  连续失败计数（TTL 锁定窗口）
    auth:bootstrapped          String  管理员已初始化标记
"""

import base64
import io
import random
import re
import secrets
import time
import uuid
from typing import Optional

import bcrypt
from loguru import logger
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from config import settings
from core.redis_client import get_async_redis

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,24}$")
EMPLOYEE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,24}$")
PACKAGE_NO_PATTERN = re.compile(r"^[A-Za-z0-9-]{6,32}$")

CAPTCHA_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 剔除 0/O/1/I 等易混淆字符
CAPTCHA_LENGTH = 4
ROLES = ("customer", "agent", "admin")


class AuthError(Exception):
    """认证业务异常：由路由层转换为对应的 HTTP 状态码。"""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def hash_secret(raw: str) -> str:
    """对密码 / 密钥做 bcrypt 哈希（cost 由配置控制）。"""
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt(rounds=settings.bcrypt_rounds)).decode("utf-8")


def verify_secret(raw: str, hashed: str) -> bool:
    """校验明文与 bcrypt 哈希是否匹配。"""
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _user_public(data: dict) -> dict:
    """客户账号响应脱敏：剔除密码哈希。"""
    return {
        "user_id": data.get("user_id", ""),
        "username": data.get("username", ""),
        "nickname": data.get("nickname", ""),
        "phone": data.get("phone", ""),
        "status": data.get("status", "active"),
        "created_at": data.get("created_at", ""),
        "updated_at": data.get("updated_at", ""),
    }


def _agent_public(data: dict) -> dict:
    """客服账号响应脱敏：剔除密钥哈希。"""
    return {
        "employee_id": data.get("employee_id", ""),
        "name": data.get("name", ""),
        "role": data.get("role", "agent"),
        "status": data.get("status", "active"),
        "created_at": data.get("created_at", ""),
        "updated_at": data.get("updated_at", ""),
    }


def _render_captcha(code: str) -> str:
    """用 Pillow 绘制图形验证码，返回 data URL（PNG base64）。"""
    width, height = 132, 44
    image = Image.new("RGB", (width, height), (18, 20, 28))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=26)

    # 背景噪点
    for _ in range(160):
        draw.point(
            (random.randint(0, width), random.randint(0, height)),
            fill=(random.randint(40, 90), random.randint(40, 90), random.randint(60, 110)),
        )
    # 干扰线
    for _ in range(5):
        draw.line(
            [(random.randint(0, width), random.randint(0, height)),
             (random.randint(0, width), random.randint(0, height))],
            fill=(random.randint(60, 120), random.randint(60, 120), random.randint(90, 150)),
            width=1,
        )
    # 逐字符绘制（随机颜色与纵向偏移）
    for index, char in enumerate(code):
        color = (random.randint(150, 255), random.randint(150, 255), random.randint(180, 255))
        draw.text((14 + index * 28, random.randint(2, 10)), char, font=font, fill=color)
    image = image.filter(ImageFilter.SMOOTH)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


class AuthStore:
    """账号 / 验证码 / 令牌的统一存储封装。"""

    def __init__(self):
        self.redis = get_async_redis()

    # ==================== 图形验证码 ====================

    async def create_captcha(self) -> dict:
        """生成一次性图形验证码：答案入 Redis（TTL），图片以 data URL 返回。"""
        captcha_id = uuid.uuid4().hex
        code = "".join(random.choice(CAPTCHA_CHARS) for _ in range(CAPTCHA_LENGTH))
        await self.redis.set(f"auth:captcha:{captcha_id}", code, ex=settings.captcha_ttl)
        return {
            "captcha_id": captcha_id,
            "image": _render_captcha(code),
            "expires_in": settings.captcha_ttl,
        }

    async def verify_captcha(self, captcha_id: str, code: str) -> None:
        """校验验证码；无论对错都删除（一次性），失败抛 AuthError(400)。"""
        key = f"auth:captcha:{captcha_id}"
        expected = await self.redis.get(key)
        await self.redis.delete(key)
        if not expected:
            raise AuthError("验证码已过期，请刷新重试", status_code=400)
        if (code or "").strip().upper() != expected:
            raise AuthError("验证码错误", status_code=400)

    # ==================== 登录失败锁定 ====================

    async def ensure_not_locked(self, identity: str) -> None:
        """连续失败达到上限时拒绝登录。"""
        count = await self.redis.get(f"auth:fail:{identity}")
        if count and int(count) >= settings.login_max_failures:
            raise AuthError("失败次数过多，账号已临时锁定，请稍后再试", status_code=423)

    async def record_failure(self, identity: str) -> None:
        """记录一次失败并刷新锁定窗口。"""
        key = f"auth:fail:{identity}"
        await self.redis.incr(key)
        await self.redis.expire(key, settings.login_lock_seconds)

    async def clear_failures(self, identity: str) -> None:
        """登录成功后清零失败计数。"""
        await self.redis.delete(f"auth:fail:{identity}")

    # ==================== 客户账号 ====================

    async def create_user(self, username: str, password: str, nickname: str = "", phone: str = "") -> dict:
        """创建客户账号：校验格式、唯一性，密码哈希后落库并维护索引。"""
        if not USERNAME_PATTERN.match(username or ""):
            raise AuthError("用户名需为 3-24 位字母、数字或下划线", status_code=400)
        if len(password or "") < 6:
            raise AuthError("密码至少 6 位", status_code=400)
        if await self.redis.exists(f"auth:user:name:{username}"):
            raise AuthError(f"用户名已存在: {username}", status_code=409)

        user_id = f"u_{uuid.uuid4().hex[:12]}"
        now = time.time()
        mapping = {
            "user_id": user_id,
            "username": username,
            "password_hash": hash_secret(password),
            "nickname": nickname or username,
            "phone": phone,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.hset(f"auth:user:{user_id}", mapping=mapping)
            pipe.set(f"auth:user:name:{username}", user_id)
            pipe.zadd("index:users", {user_id: now})
            await pipe.execute()
        logger.info("客户账号已创建: {} ({})", username, user_id)
        return _user_public(mapping)

    async def get_user(self, user_id: str) -> dict | None:
        """按 user_id 读取客户账号原始数据。"""
        data = await self.redis.hgetall(f"auth:user:{user_id}")
        return data or None

    async def get_user_by_username(self, username: str) -> dict | None:
        """按用户名读取客户账号原始数据（经唯一索引）。"""
        user_id = await self.redis.get(f"auth:user:name:{username}")
        if not user_id:
            return None
        return await self.get_user(user_id)

    async def verify_user_login(self, username: str, password: str) -> dict:
        """客户登录校验：返回脱敏后的账号信息，失败抛 AuthError(401)。"""
        await self.ensure_not_locked(f"user:{username}")
        user = await self.get_user_by_username(username)
        if not user or user.get("status") != "active" or not verify_secret(password, user.get("password_hash", "")):
            await self.record_failure(f"user:{username}")
            raise AuthError("用户名或密码错误", status_code=401)
        await self.clear_failures(f"user:{username}")
        return _user_public(user)

    async def list_users(self) -> list[dict]:
        """客户账号列表（脱敏），按创建时间倒序。"""
        user_ids = await self.redis.zrevrange("index:users", 0, -1)
        users = []
        for uid in user_ids:
            data = await self.get_user(uid)
            if data:
                users.append(_user_public(data))
        return users

    async def update_user(self, user_id: str, **changes) -> dict:
        """更新客户账号（密码 / 昵称 / 手机号 / 状态），密码自动重新哈希。"""
        user = await self.get_user(user_id)
        if not user:
            raise AuthError(f"客户不存在: {user_id}", status_code=404)
        mapping: dict = {"updated_at": time.time()}
        if changes.get("password"):
            if len(changes["password"]) < 6:
                raise AuthError("密码至少 6 位", status_code=400)
            mapping["password_hash"] = hash_secret(changes["password"])
        for field in ("nickname", "phone"):
            if changes.get(field) is not None:
                mapping[field] = changes[field]
        if changes.get("status") is not None:
            if changes["status"] not in ("active", "disabled"):
                raise AuthError("状态仅允许 active / disabled", status_code=400)
            mapping["status"] = changes["status"]
        await self.redis.hset(f"auth:user:{user_id}", mapping=mapping)
        logger.info("客户账号已更新: {}", user_id)
        return _user_public({**user, **mapping})

    # ==================== 客服账号 ====================

    async def create_agent(self, employee_id: str, secret: str, name: str, role: str = "agent") -> dict:
        """创建客服账号：工号为主键，密钥哈希后落库。"""
        if not EMPLOYEE_ID_PATTERN.match(employee_id or ""):
            raise AuthError("工号需为 3-24 位字母、数字、下划线或连字符", status_code=400)
        if len(secret or "") < 8:
            raise AuthError("密钥至少 8 位", status_code=400)
        if role not in ("agent", "admin"):
            raise AuthError("角色仅允许 agent / admin", status_code=400)
        if await self.redis.exists(f"auth:agent:{employee_id}"):
            raise AuthError(f"工号已存在: {employee_id}", status_code=409)

        now = time.time()
        mapping = {
            "employee_id": employee_id,
            "name": name or employee_id,
            "secret_hash": hash_secret(secret),
            "role": role,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.hset(f"auth:agent:{employee_id}", mapping=mapping)
            pipe.zadd("index:agents", {employee_id: now})
            await pipe.execute()
        logger.info("客服账号已创建: {} ({})", employee_id, role)
        return _agent_public(mapping)

    async def get_agent(self, employee_id: str) -> dict | None:
        """按工号读取客服账号原始数据。"""
        data = await self.redis.hgetall(f"auth:agent:{employee_id}")
        return data or None

    async def verify_agent_login(self, employee_id: str, secret: str) -> dict:
        """客服登录校验：返回脱敏信息，失败抛 AuthError(401)。"""
        await self.ensure_not_locked(f"agent:{employee_id}")
        agent = await self.get_agent(employee_id)
        if not agent or agent.get("status") != "active" or not verify_secret(secret, agent.get("secret_hash", "")):
            await self.record_failure(f"agent:{employee_id}")
            raise AuthError("工号或密钥错误", status_code=401)
        await self.clear_failures(f"agent:{employee_id}")
        return _agent_public(agent)

    async def list_agents(self) -> list[dict]:
        """客服账号列表（脱敏），按创建时间倒序。"""
        employee_ids = await self.redis.zrevrange("index:agents", 0, -1)
        agents = []
        for eid in employee_ids:
            data = await self.get_agent(eid)
            if data:
                agents.append(_agent_public(data))
        return agents

    async def update_agent(self, employee_id: str, **changes) -> dict:
        """更新客服账号（密钥 / 姓名 / 角色 / 状态），密钥自动重新哈希。"""
        agent = await self.get_agent(employee_id)
        if not agent:
            raise AuthError(f"客服不存在: {employee_id}", status_code=404)
        mapping: dict = {"updated_at": time.time()}
        if changes.get("secret"):
            if len(changes["secret"]) < 8:
                raise AuthError("密钥至少 8 位", status_code=400)
            mapping["secret_hash"] = hash_secret(changes["secret"])
        if changes.get("name") is not None:
            mapping["name"] = changes["name"]
        if changes.get("role") is not None:
            if changes["role"] not in ("agent", "admin"):
                raise AuthError("角色仅允许 agent / admin", status_code=400)
            mapping["role"] = changes["role"]
        if changes.get("status") is not None:
            if changes["status"] not in ("active", "disabled"):
                raise AuthError("状态仅允许 active / disabled", status_code=400)
            mapping["status"] = changes["status"]
        await self.redis.hset(f"auth:agent:{employee_id}", mapping=mapping)
        logger.info("客服账号已更新: {}", employee_id)
        return _agent_public({**agent, **mapping})

    # ==================== 管理员初始化 ====================

    async def admin_exists(self) -> bool:
        """是否已存在管理员账号。"""
        employee_ids = await self.redis.zrange("index:agents", 0, -1)
        for eid in employee_ids:
            role = await self.redis.hget(f"auth:agent:{eid}", "role")
            if role == "admin":
                return True
        return False

    async def init_admin(self, employee_id: str, secret: str, name: str, bootstrap_key: str) -> dict:
        """首次初始化管理员：仅在系统未初始化且引导密钥正确时允许。"""
        if await self.admin_exists() or await self.redis.exists("auth:bootstrapped"):
            raise AuthError("管理员已初始化，请直接登录", status_code=409)
        if bootstrap_key != settings.admin_bootstrap_key:
            raise AuthError("初始化密钥错误", status_code=403)
        agent = await self.create_agent(employee_id, secret, name or "系统管理员", role="admin")
        await self.redis.set("auth:bootstrapped", "1")
        logger.info("管理员初始化完成: {}", employee_id)
        return agent

    # ==================== 令牌 ====================

    async def issue_token(self, role: str, subject: str, name: str) -> dict:
        """签发不透明令牌，按角色选择有效期。"""
        if role not in ROLES:
            raise AuthError("非法角色", status_code=400)
        token = secrets.token_urlsafe(32)
        ttl = settings.auth_token_ttl_customer if role == "customer" else settings.auth_token_ttl_staff
        await self.redis.hset(
            f"auth:token:{token}",
            mapping={"role": role, "subject": subject, "name": name, "created_at": time.time()},
        )
        await self.redis.expire(f"auth:token:{token}", ttl)
        return {"token": token, "role": role, "subject": subject, "name": name, "expires_in": ttl}

    async def get_token(self, token: str) -> Optional[dict]:
        """校验并读取令牌对应的身份信息（含剩余有效期）。"""
        key = f"auth:token:{token}"
        data = await self.redis.hgetall(key)
        if not data:
            return None
        ttl = await self.redis.ttl(key)
        return {**data, "expires_in": max(ttl, 0)}

    async def revoke_token(self, token: str) -> None:
        """登出：删除令牌。"""
        await self.redis.delete(f"auth:token:{token}")