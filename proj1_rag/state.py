"""Agentic RAG 的 LangGraph 状态定义。

RAGState 是整个图共享的单一数据结构，
各节点通过返回"部分状态字典"实现增量更新。
"""

from typing import List, TypedDict

from langchain_core.documents import Document


class RAGState(TypedDict):
    """RAG 图的全局共享状态。

    Attributes:
        query: 用户原始查询。
        documents: 当前参与下游流程的候选文档（随打分过滤动态收缩）。
        generation: 最近一次生成的答案文本。
        web_search_needed: 打分后无相关文档时置 True，驱动路由进入 web_search。
        hallucination_score: 幻觉检测分数，0 表示完全基于文档，1 表示完全捏造。
        retry_count: 幻觉重试计数器（为实现"最多重试 2 次"补充的内部字段）。
    """

    query: str
    documents: List[Document]
    generation: str
    web_search_needed: bool
    hallucination_score: float
    retry_count: int
