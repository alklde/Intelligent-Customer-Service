"""智能客服 Agent 节点实现。

节点职责划分：
- intent_router:    LLM 一次完成意图判定 + 工具参数抽取（失败降级转人工）
- chat_reply:       预设话术短路 + 知识库严格接地问答（禁止 LLM 自由发挥）
- tool_executor:    线程池隔离执行工具（3s 超时熔断 + 失败计数）
- fallback_handler: 人工兜底，输出固定话术并终止
"""

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
import re
import time

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool
from loguru import logger
from pydantic import BaseModel, Field
from typing import Literal

from config import settings
from core.exceptions import ToolExecutionError
from core.llm_factory import get_chat_model
from proj1_rag.graph import rag_graph
from proj1_rag.kb import NO_INFO_ANSWER
from proj2_customer_service.state import ServiceState
from proj2_customer_service.tools import TOOLS

FALLBACK_MESSAGE = "已处理，正在等待人工客服介入"

HUMAN_KEYWORDS = ("转人工", "人工客服", "人工坐席", "转接人工", "找人工", "要人工", "真人客服")

# 预设话术：仅覆盖常见寒暄 / 致谢 / 告别，命中后无需调用模型
PRESET_RULES = (
    (("你好", "您好", "hi", "hello", "在吗", "早上好", "晚上好"), "您好，我是智能客服小助手，很高兴为您服务。请问有什么可以帮您？"),
    (("谢谢", "感谢", "多谢"), "不客气，很高兴能帮到您。如有其他问题，欢迎随时咨询。"),
    (("再见", "拜拜", "bye"), "感谢您的咨询，祝您生活愉快，再见！"),
)
PRESET_MAX_LEN = 12


class IntentResult(BaseModel):
    """intent_router 的强约束输出：意图分类 + 可选参数抽取。"""

    intent: Literal["chitchat", "query_order", "create_ticket", "human"] = Field(
        ..., description="用户意图分类"
    )
    order_id: str | None = Field(default=None, description="查询订单时从对话中提取的订单编号")
    issue_desc: str | None = Field(default=None, description="提交工单时的问题描述")
    priority: Literal["high", "low"] | None = Field(default=None, description="工单优先级")


def intent_router(state: ServiceState) -> dict:
    """LLM 判定用户意图并抽取工具参数，一次调用完成分类与槽位填充。

    转人工意图先做关键词短路（小模型对「转人工」类短句易误判为建单），
    LLM 调用失败时同样降级为转人工，保证对话链路不中断。
    """
    latest_user = next(
        (m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), ""
    )
    if any(keyword in latest_user for keyword in HUMAN_KEYWORDS):
        logger.info("意图识别命中转人工关键词: {}", latest_user)
        return {"intent": "human", "needs_human": True}

    history = "\n".join(
        f"{'用户' if isinstance(m, HumanMessage) else '客服'}: {m.content}"
        for m in state["messages"][-6:]
    )
    prompt = (
        "你是客服意图分类器。根据对话历史判断用户最新意图，必须取以下值之一：\n"
        "- chitchat: 闲聊、问候或与业务无关\n"
        "- query_order: 查询订单（从对话中提取 order_id）\n"
        "- create_ticket: 提交工单或投诉（提取 issue_desc，紧急用 high 否则 low）\n"
        "- human: 用户明确要求转接人工\n"
        "无法提取的参数字段留空。\n\n"
        f"[对话历史]\n{history}"
    )

    try:
        classifier = get_chat_model().with_structured_output(IntentResult)
        result: IntentResult = classifier.invoke([HumanMessage(content=prompt)])
        logger.info(
            "意图识别完成: intent={} order_id={} priority={}",
            result.intent, result.order_id, result.priority,
        )
    except Exception as exc:
        logger.error("意图识别 LLM 调用失败，降级转人工: {}", exc)
        return {"intent": "human", "needs_human": True}

    tool_args: dict = {}
    if result.intent == "query_order" and result.order_id:
        tool_args = {"order_id": result.order_id}
    elif result.intent == "create_ticket":
        tool_args = {
            "issue_desc": result.issue_desc or "用户未填写具体问题",
            "priority": result.priority or "low",
        }

    return {"intent": result.intent, "tool_args": tool_args}


def _preset_reply(text: str) -> str | None:
    """命中常见寒暄 / 致谢 / 告别时返回标准话术，避免模型自由发挥。"""
    normalized = (text or "").strip().lower()
    if not normalized or len(normalized) > PRESET_MAX_LEN:
        return None
    for keywords, reply in PRESET_RULES:
        if any(keyword in normalized for keyword in keywords):
            return reply
    return None


def _bigrams(text: str) -> set[str]:
    """提取字符二元组，用于答案与知识库文档的确定性接地校验。"""
    clean = re.sub(r"[\s，。！？、；：,.!?;:~「」（）()\[\]【】]", "", text or "")
    if len(clean) < 2:
        return {clean} if clean else set()
    return {clean[i : i + 2] for i in range(len(clean) - 1)}


def _grounding_coverage(answer: str, docs_text: str) -> float:
    """答案二元组在参考文档中的覆盖比例，作为幻觉检测的确定性补充。"""
    answer_grams = _bigrams(answer)
    if not answer_grams:
        return 0.0
    return len(answer_grams & _bigrams(docs_text)) / len(answer_grams)


def chat_reply(state: ServiceState) -> dict:
    """问答回复：预设话术短路；其余问题必须基于知识库严格接地作答。

    接地判定（全部满足才返回生成答案）：
    1. 检索到知识库文档，且未走 Mock 网络搜索；
    2. 生成结果非固定无信息话术；
    3. 幻觉检测通过，或答案与参考文档的二元组覆盖率达标。
    任一不满足则返回固定无信息话术，绝不编造。
    """
    last_user_msg = next(
        (m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), ""
    )
    preset = _preset_reply(last_user_msg)
    if preset:
        logger.info("命中预设话术: {}", last_user_msg)
        return {"messages": [AIMessage(content=preset)]}

    try:
        result = rag_graph.invoke({"query": last_user_msg}, config={"recursion_limit": 25})
        documents = result.get("documents", [])
        used_web = any(doc.metadata.get("source") == "web_search_mock" for doc in documents)
        answer = (result.get("generation") or "").strip()
        score = float(result.get("hallucination_score", 1.0))
        docs_text = "\n".join(doc.page_content for doc in documents)
        coverage = _grounding_coverage(answer, docs_text)
        grounded = (
            bool(documents)
            and not used_web
            and bool(answer)
            and NO_INFO_ANSWER not in answer
            and (score <= settings.hallucination_threshold or coverage >= 0.6)
        )
        if not grounded:
            logger.warning(
                "知识库接地未通过，返回无信息话术: web={} docs={} score={} coverage={:.2f}",
                used_web, len(documents), score, coverage,
            )
            answer = NO_INFO_ANSWER
        return {"messages": [AIMessage(content=answer)]}
    except Exception as exc:
        logger.error("知识库问答失败: {}", exc)
        return {"messages": [AIMessage(content=NO_INFO_ANSWER)]}


def _run_with_timeout(tool: BaseTool, tool_args: dict, timeout: float) -> str:
    """在线程池中以固定超时执行工具，超时统一包装为 ToolExecutionError。

    独立线程隔离执行避免阻塞；tool.invoke 走 args_schema 校验，
    非法参数将以 ValidationError 形式抛出。
    """
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(tool.invoke, tool_args)
    try:
        return future.result(timeout=timeout)
    except FuturesTimeoutError as exc:
        raise ToolExecutionError(f"工具执行超时（>{timeout}s）") from exc
    finally:
        executor.shutdown(wait=False)


def _trace_step(tool_name: str, tool_args: dict, ok: bool) -> dict:
    """构造单条轨迹记录，格式由评测平台的护栏检测器约定。"""
    return {
        "tool": tool_name,
        "args": tool_args,
        "ok": ok,
        "timestamp": time.time(),
    }


def tool_executor(state: ServiceState) -> dict:
    """执行意图对应的工具。

    强约束：
    - 单次执行超时 settings.tool_timeout（3 秒）
    - 任何异常（超时 / 参数校验失败 / 工具内部错误）均累计 tool_call_count
    - 失败达 settings.max_tool_failures（3 次）强制 needs_human=True，
      话术输出交由 fallback_handler，避免重复
    - 每次调用（成功或失败）均写入 trace，供评测平台做护栏检测
    """
    intent = state["intent"]
    tool_args = state.get("tool_args", {})
    tool_call_count = state.get("tool_call_count", 0)
    trace = state.get("trace", [])

    tool = TOOLS.get(intent)
    if tool is None:
        logger.error("tool_executor 收到未知意图，直接转人工: {}", intent)
        return {"tool_call_count": tool_call_count, "needs_human": True}

    try:
        result = _run_with_timeout(tool, tool_args, settings.tool_timeout)
        logger.info("工具执行成功: intent={} args={}", intent, tool_args)
        return {
            "messages": [AIMessage(content=result)],
            "tool_call_count": tool_call_count,
            "needs_human": False,
            "trace": trace + [_trace_step(intent, tool_args, True)],
        }
    except Exception as exc:
        new_count = tool_call_count + 1
        needs_human = new_count >= settings.max_tool_failures
        logger.error(
            "工具执行失败({}/{}): intent={} args={} error={}",
            new_count, settings.max_tool_failures, intent, tool_args, exc,
        )
        new_trace = trace + [_trace_step(intent, tool_args, False)]
        if needs_human:
            return {
                "tool_call_count": new_count,
                "needs_human": True,
                "trace": new_trace,
            }
        return {
            "messages": [
                AIMessage(
                    content=f"操作失败（{new_count}/{settings.max_tool_failures}），请稍后再试一次。"
                )
            ],
            "tool_call_count": new_count,
            "needs_human": False,
            "trace": new_trace,
        }


def fallback_handler(state: ServiceState) -> dict:
    """人工兜底节点：输出固定转接话术，needs_human 保持 True 以终止图运行。"""
    logger.warning(
        "进入人工兜底: user_id={} tool_call_count={}",
        state.get("user_id", "unknown"), state.get("tool_call_count", 0),
    )
    return {
        "messages": [AIMessage(content=FALLBACK_MESSAGE)],
        "needs_human": True,
    }
