"""初始化演示账号（幂等）：管理员、演示客户、演示客服。

用法：
    python scripts/seed_accounts.py

默认账号（生产环境请立即修改）：
    管理员  admin001 / Admin@123456   （登录页：客服登录）
    客服    agent001 / Agent@123456
    客服    agent002 / Agent@123456
    客户    zhangsan / 123456
    客户    lisi / 123456
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from core.auth import AuthError, AuthStore

ADMIN = ("admin001", "Admin@123456", "系统管理员")
AGENTS = [
    ("agent001", "Agent@123456", "客服小李"),
    ("agent002", "Agent@123456", "客服小王"),
]
USERS = [
    ("zhangsan", "123456", "张三", "13800000001"),
    ("lisi", "123456", "李四", "13800000002"),
]


async def main() -> None:
    """按需创建演示账号，已存在的账号跳过。"""
    store = AuthStore()
    if await store.admin_exists():
        print("管理员已存在，跳过初始化")
    else:
        await store.init_admin(*ADMIN, settings.admin_bootstrap_key)
        print(f"管理员已初始化: {ADMIN[0]} / {ADMIN[1]}")

    for employee_id, secret, name in AGENTS:
        try:
            await store.create_agent(employee_id, secret, name)
            print(f"客服已创建: {employee_id} / {secret}")
        except AuthError as exc:
            print(f"客服跳过: {employee_id} ({exc.message})")

    for username, password, nickname, phone in USERS:
        try:
            await store.create_user(username, password, nickname, phone)
            print(f"客户已创建: {username} / {password}")
        except AuthError as exc:
            print(f"客户跳过: {username} ({exc.message})")

    print("SEED_ACCOUNTS_DONE")


if __name__ == "__main__":
    asyncio.run(main())