"""Agentic RAG 图编排模块。

拓扑结构：
    START → retrieve → grade_documents
        ├─ (无相关文档) → web_search (Mock) ─┐
        └─ (有相关文档) ────────────────────→ generate → check_hallucination
                                                    ↑              │ (超阈值且未达重试上限)
                                                    └──────────────┘
                                                                   │ (通过 / 达上限)
                                                                  END
"""

from langgraph.graph import END, START, StateGraph
from loguru import logger

from config import settings
from proj1_rag.nodes import (
    check_hallucination,
    generate,
    grade_documents,
    retrieve,
    web_search,
)
from proj1_rag.state import RAGState


def route_after_grading(state: RAGState) -> str:
    """打分后路由：过滤后无相关文档则走 web_search，否则进入 generate。"""
    return "web_search" if state.get("web_search_needed") else "generate"


def route_after_check(state: RAGState) -> str:
    """幻觉校验后路由：超阈值且未达重试上限则回 generate，否则结束图运行。"""
    over_threshold = state.get("hallucination_score", 0.0) > settings.hallucination_threshold
    can_retry = state.get("retry_count", 0) < settings.max_generation_retries
    return "generate" if over_threshold and can_retry else END


def build_graph():
    """编译 Agentic RAG 图。

    Returns:
        编译后的 Runnable 图实例，可直接 invoke / stream。
    """
    builder = StateGraph(RAGState)
    builder.add_node("retrieve", retrieve)
    builder.add_node("grade_documents", grade_documents)
    builder.add_node("generate", generate)
    builder.add_node("check_hallucination", check_hallucination)
    builder.add_node("web_search", web_search)

    builder.add_edge(START, "retrieve")
    builder.add_edge("retrieve", "grade_documents")
    builder.add_conditional_edges(
        "grade_documents",
        route_after_grading,
        {"generate": "generate", "web_search": "web_search"},
    )
    builder.add_edge("web_search", "generate")
    builder.add_edge("generate", "check_hallucination")
    builder.add_conditional_edges(
        "check_hallucination",
        route_after_check,
        {"generate": "generate", END: END},
    )
    return builder.compile()


rag_graph = build_graph()
logger.debug("Agentic RAG 图编译完成, 节点: {}", list(rag_graph.get_graph().nodes))
