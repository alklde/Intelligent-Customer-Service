"""Agentic RAG 图节点实现。

节点职责划分：
- retrieve:            Qdrant 向量检索 Top-K（不可用时降级为空列表）
- grade_documents:     LLM 批量相关性打分，过滤低分文档
- generate:            基于过滤后文档生成结构化答案（answer + references）
- check_hallucination: 幻觉校验，超阈值累计重试
- web_search:          Mock 网络检索兜底
"""

import time
from typing import List

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage
from loguru import logger
from pydantic import BaseModel, Field

from config import settings
from core.llm_factory import get_chat_model
from proj1_rag.kb import NO_INFO_ANSWER, kb_store
from proj1_rag.state import RAGState


# ==================== LLM 结构化输出模型 ====================


class DocumentGrade(BaseModel):
    """单篇文档与查询的相关性打分结果。"""

    score: float = Field(..., ge=0.0, le=1.0, description="相关性分数，1 表示完全相关")
    reason: str = Field(default="", description="一句话打分理由")


class RAGAnswer(BaseModel):
    """generate 节点的强约束输出：答案 + 引用来源。"""

    answer: str = Field(..., description="基于参考文档生成的最终答案")
    references: List[str] = Field(default_factory=list, description="答案引用的文档编号列表")


class HallucinationCheck(BaseModel):
    """check_hallucination 节点的强约束输出。"""

    grounded: bool = Field(..., description="答案是否完全基于参考文档")
    score: float = Field(..., ge=0.0, le=1.0, description="幻觉程度，0 表示完全无幻觉")


# ==================== 图节点 ====================


def retrieve(state: RAGState) -> dict:
    """从知识库执行混合检索（向量 + IDF 关键词），失败时降级为空列表。"""
    query = state["query"]
    try:
        start = time.perf_counter()
        documents = kb_store.retrieve(query)
        logger.info(
            "retrieve 完成: query='{}' 命中 {} 篇文档, 耗时 {:.2f}s",
            query, len(documents), time.perf_counter() - start,
        )
        return {"documents": documents}
    except Exception as exc:
        logger.error("知识库检索失败，降级返回空列表: {}", exc)
        return {"documents": []}


def grade_documents(state: RAGState) -> dict:
    """对候选文档做相关性过滤。

    混合检索得分足够高的分块直接保留（避免小模型打分波动误杀），
    其余分块交 LLM 逐篇打分；单篇打分失败时保守保留，避免误杀。
    """
    query = state["query"]
    documents = state["documents"]
    if not documents:
        logger.warning("grade_documents: 无候选文档，标记需要 web_search")
        return {"documents": [], "web_search_needed": True}

    grader = get_chat_model().with_structured_output(DocumentGrade)
    relevant = []
    for i, doc in enumerate(documents):
        retrieval_score = float(doc.metadata.get("retrieval_score", 0.0))
        if retrieval_score >= 0.5:
            logger.info("grade_documents: 文档 {} 检索得分 {:.2f}，直接保留", i, retrieval_score)
            relevant.append(doc)
            continue
        prompt = (
            "评估以下文档对回答用户查询的相关性，输出 0 到 1 之间的小数分数"
            "（1 表示完全相关，0 表示完全无关）。\n\n"
            f"[用户查询]\n{query}\n\n[文档 {i}]\n{doc.page_content}"
        )
        try:
            grade: DocumentGrade = grader.invoke([HumanMessage(content=prompt)])
            score = grade.score
            logger.info("grade_documents: 文档 {} 得分 {:.2f} ({})", i, score, grade.reason)
        except Exception as exc:
            logger.error("文档 {} 打分失败，保守保留: {}", i, exc)
            score = 1.0
        if score >= settings.grade_threshold:
            relevant.append(doc)

    logger.info(
        "grade_documents 完成: {} 篇候选, 保留 {} 篇 (阈值={})",
        len(documents), len(relevant), settings.grade_threshold,
    )
    return {"documents": relevant, "web_search_needed": len(relevant) == 0}


def generate(state: RAGState) -> dict:
    """基于过滤后的文档生成结构化答案（answer + references，Pydantic 强约束）。

    提示词采用严格接地策略：只允许引用参考文档中的事实，资料不足时
    必须输出固定无信息话术，禁止使用模型自身知识补全，杜绝幻觉。
    """
    query = state["query"]
    documents = state["documents"]
    docs_text = "\n\n".join(f"[文档 {i}] {doc.page_content}" for i, doc in enumerate(documents))
    fallback_docs = docs_text if documents else "(无可用文档)"
    prompt = (
        "你是企业客服知识库问答助手，必须严格遵守以下规则：\n"
        "1. 只能使用「参考文档」中明确出现的事实作答，禁止使用文档之外的知识，禁止猜测或编造。\n"
        "2. 如果参考文档不足以回答问题，answer 必须原样输出："
        f"{NO_INFO_ANSWER}\n"
        "3. 答案必须逐条对应参考文档中的事实，不得扩展、不得添加文档未提及的承诺、时效或规则。\n"
        "4. 用简体中文简洁作答；references 中列出实际引用文档的下标（从 0 开始）。\n\n"
        f"[参考文档]\n{fallback_docs}\n\n[用户查询]\n{query}"
    )

    try:
        generator = get_chat_model().with_structured_output(RAGAnswer)
        result: RAGAnswer = generator.invoke([HumanMessage(content=prompt)])
        logger.info("generate 完成: references={}", result.references)
        return {"generation": result.answer}
    except Exception as exc:
        logger.error("答案生成 LLM 调用失败: {}", exc)
        return {"generation": NO_INFO_ANSWER}


def check_hallucination(state: RAGState) -> dict:
    """校验答案是否完全基于参考文档。

    幻觉分数超过阈值时由路由函数送回 generate 重试；校验自身失败时
    视为通过（分数 0），避免因检测器故障导致图死循环。
    """
    generation = state["generation"]
    documents = state["documents"]
    retry_count = state.get("retry_count", 0)
    if not generation:
        logger.error("check_hallucination: 答案为空，直接判定失败")
        return {"hallucination_score": 1.0, "retry_count": retry_count + 1}

    docs_text = "\n\n".join(doc.page_content for doc in documents)
    prompt = (
        "你是幻觉检测器。请判断候选答案中的信息是否完全被参考文档支持。"
        "score 表示幻觉程度：0.0 表示答案完全基于文档，1.0 表示答案与文档矛盾或完全无中生有。\n\n"
        f"[参考文档]\n{docs_text if documents else '(无参考文档)'}\n\n[候选答案]\n{generation}"
    )

    try:
        checker = get_chat_model().with_structured_output(HallucinationCheck)
        result: HallucinationCheck = checker.invoke([HumanMessage(content=prompt)])
        score = result.score
        # 小参数量模型易把分数方向打反（有依据却给高分），
        # 以 grounded 二分类结论为准做一致性校正，保证分数语义正确
        score = min(score, 0.1) if result.grounded else max(score, 0.9)
    except Exception as exc:
        logger.error("幻觉检测 LLM 调用失败，视为通过: {}", exc)
        score = 0.0

    over_threshold = score > settings.hallucination_threshold
    if over_threshold and retry_count < settings.max_generation_retries:
        logger.warning("幻觉分数 {:.2f} 超阈值，准备第 {} 次重试", score, retry_count + 1)
    elif over_threshold:
        logger.warning("幻觉分数 {:.2f} 超阈值且已达重试上限 {}，放行当前答案", score, settings.max_generation_retries)
    else:
        logger.info("check_hallucination 通过: 幻觉分数={:.2f}", score)

    return {
        "hallucination_score": score,
        "retry_count": retry_count + 1 if over_threshold else retry_count,
    }


def web_search(state: RAGState) -> dict:
    """Mock 网络搜索节点。

    本地环境未接入真实搜索引擎，返回占位文档使下游 generate 节点可继续运行。
    """
    query = state["query"]
    logger.warning("触发 web_search (Mock): query='{}'", query)
    mock_doc = Document(
        page_content=f"[网络检索占位] 关于「{query}」未在本地知识库中找到高相关性资料，此内容来自 Mock 网络搜索。",
        metadata={"source": "web_search_mock"},
    )
    return {"documents": [mock_doc], "web_search_needed": False}
