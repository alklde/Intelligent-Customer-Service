"""智能客服 Agent 的 LangGraph 状态定义。"""

from typing import List, TypedDict

from langchain_core.messages import BaseMessage


class ServiceState(TypedDict):
    """客服图的全局共享状态。

    Attributes:
        messages: 多轮对话消息历史（Human / AIMessage 交错）。
        user_id: 用户唯一标识，用于日志追踪与工单归属。
        tool_call_count: 工具失败累计计数，达到上限强制转人工。
        needs_human: 置 True 时路由进入 fallback_handler 并终止图。
        intent: 意图识别结果（内部编排字段）。
        tool_args: 意图识别阶段抽取的工具参数（内部编排字段）。
        trace: 工具调用轨迹，供评测平台做护栏检测（内部编排字段）。
    """

    messages: List[BaseMessage]
    user_id: str
    tool_call_count: int
    needs_human: bool
    intent: str
    tool_args: dict
    trace: List[dict]
