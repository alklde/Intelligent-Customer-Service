"""智能客服 Agent 图编排模块。

拓扑结构：
    START → intent_router
        ├─ chitchat                  → chat_reply → END
        ├─ query_order/create_ticket → tool_executor
        │                                ├─ 失败达上限 → fallback_handler → END
        │                                └─ 否则 → END
        └─ human / 意图识别失败      → fallback_handler → END
"""

from langgraph.graph import END, START, StateGraph
from loguru import logger

from proj2_customer_service.nodes import (
    chat_reply,
    fallback_handler,
    intent_router,
    tool_executor,
)
from proj2_customer_service.state import ServiceState


def route_by_intent(state: ServiceState) -> str:
    """意图路由：闲聊走 chat_reply，业务意图走 tool_executor，其余转人工。"""
    mapping = {
        "chitchat": "chat_reply",
        "query_order": "tool_executor",
        "create_ticket": "tool_executor",
    }
    return mapping.get(state.get("intent", ""), "fallback_handler")


def route_after_tool(state: ServiceState) -> str:
    """工具执行后路由：needs_human=True 时进入人工兜底，否则结束本轮对话。"""
    return "fallback_handler" if state.get("needs_human") else END


def build_graph():
    """编译客服 Agent 图。

    Returns:
        编译后的 Runnable 图实例。
    """
    builder = StateGraph(ServiceState)
    builder.add_node("intent_router", intent_router)
    builder.add_node("chat_reply", chat_reply)
    builder.add_node("tool_executor", tool_executor)
    builder.add_node("fallback_handler", fallback_handler)

    builder.add_edge(START, "intent_router")
    builder.add_conditional_edges(
        "intent_router",
        route_by_intent,
        {
            "chat_reply": "chat_reply",
            "tool_executor": "tool_executor",
            "fallback_handler": "fallback_handler",
        },
    )
    builder.add_edge("chat_reply", END)
    builder.add_conditional_edges(
        "tool_executor",
        route_after_tool,
        {"fallback_handler": "fallback_handler", END: END},
    )
    builder.add_edge("fallback_handler", END)
    return builder.compile()


cs_graph = build_graph()
logger.debug("客服 Agent 图编译完成, 节点: {}", list(cs_graph.get_graph().nodes))
