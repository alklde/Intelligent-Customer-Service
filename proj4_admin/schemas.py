"""客服工作台后台服务的 Pydantic 模型。"""

from typing import Literal

from pydantic import BaseModel, Field


class ClaimRequest(BaseModel):
    """客服接入请求。"""

    agent_id: str = Field(..., min_length=1, description="客服工号")


class ReplyRequest(BaseModel):
    """人工回复请求。"""

    agent_id: str = Field(..., min_length=1, description="客服工号")
    content: str = Field(..., min_length=1, description="回复内容")


class CloseRequest(BaseModel):
    """会话关闭请求：close=结束会话，reopen=处理完毕转回 AI 接管。"""

    agent_id: str = Field(..., min_length=1, description="客服工号")
    resolve: bool = Field(default=True, description="是否标记为已解决")
    mark_badcase: bool = Field(default=False, description="是否标记为 badcase（沉淀进评测集）")
    action: Literal["close", "reopen"] = Field(default="close", description="close 关闭 / reopen 转回 AI")


class TicketPatch(BaseModel):
    """工单状态流转请求。"""

    status: Literal["open", "processing", "resolved", "closed"] = Field(..., description="目标状态")
