"""智能客服 Agent 的 Mock 工具集。

所有工具通过 @tool 装饰器注册，并强制绑定 Pydantic args_schema
完成入参校验，非法参数在进入业务逻辑前即被拦截。
"""

import random
import time
from typing import Literal

from langchain_core.tools import BaseTool, tool
from loguru import logger
from pydantic import BaseModel, Field

from core.redis_client import get_sync_redis


class QueryOrderArgs(BaseModel):
    """query_order 工具的入参约束。"""

    order_id: str = Field(..., min_length=6, max_length=32, description="订单编号")


class CreateTicketArgs(BaseModel):
    """create_ticket 工具的入参约束。"""

    issue_desc: str = Field(..., min_length=5, description="问题具体描述")
    priority: Literal["high", "low"] = Field(..., description="工单优先级，仅允许 high / low")
    package_no: str = Field(
        default="",
        max_length=32,
        description="相关包裹 / 订单单号（可选，用户提供时填写）",
    )


@tool(args_schema=QueryOrderArgs)
def query_order(order_id: str) -> str:
    """查询订单状态与物流信息。约 30% 概率抛出 TimeoutError 模拟下游服务超时。"""
    if random.random() < 0.3:
        logger.warning("query_order 模拟超时: order_id={}", order_id)
        raise TimeoutError("订单服务响应超时")
    logger.info("query_order 成功: order_id={}", order_id)
    return f"订单 {order_id} 状态：已发货，预计 2 天内送达。"


@tool(args_schema=CreateTicketArgs)
def create_ticket(issue_desc: str, priority: str, package_no: str = "") -> str:
    """创建客服工单并持久化到 Redis，返回工单编号与跟进承诺。"""
    ticket_id = f"TK{int(time.time() * 1000)}"
    now = time.time()
    r = get_sync_redis()
    r.hset(
        f"ticket:{ticket_id}",
        mapping={
            "ticket_id": ticket_id,
            "issue_desc": issue_desc,
            "priority": priority,
            "package_no": package_no.upper(),
            "status": "open",
            "source": "ai",
            "created_at": now,
            "updated_at": now,
        },
    )
    r.zadd("index:tickets", {ticket_id: now})
    r.hincrby(f"stats:{time.strftime('%Y%m%d')}", "tickets_created", 1)
    logger.info("工单已落库: ticket_id={} priority={} package={}", ticket_id, priority, package_no or "-")
    return f"工单创建成功，编号 {ticket_id}（优先级：{priority}），客服将在 24 小时内跟进。"


TOOLS: dict[str, BaseTool] = {
    "query_order": query_order,
    "create_ticket": create_ticket,
}
