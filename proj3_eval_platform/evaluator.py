"""评测流水线：轻量级手写实现，不依赖重型评测框架。

流程：读取 dataset.jsonl → 逐条调用 Project 2 客服 Agent 收集
输出与 Trace → 护栏检测（死循环 / 越权）→ difflib 相似度评分
→ 生成 JSON 评测报告并落盘。
"""

import difflib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from langchain_core.messages import AIMessage, HumanMessage
from loguru import logger

from proj2_customer_service.graph import cs_graph
from proj3_eval_platform.guardrails import detect_infinite_loop, detect_unauthorized_tool

DATASET_PATH = Path(__file__).parent / "dataset.jsonl"
REPORT_DIR = Path(__file__).parent / "reports"
SIMILARITY_PASS_THRESHOLD = 0.5  # 相似度达标线，低于该值判定用例未通过


async def append_badcase_to_dataset(session_id: str) -> dict | None:
    """把客服标记为 badcase 的会话沉淀为评测样本，追加写入 dataset.jsonl。

    样本构造规则：
    - input: 会话首条用户消息（问题源头）
    - expected_output: 人工客服的最后回复（人工给出的正确答案），
      无人介入时降级为 AI 最后回复
    - allowed_tools: 保守给全量业务工具白名单
    写入后将会话标记 exported，防止重复导出。
    """
    from core.redis_client import get_async_redis
    from proj2_customer_service.store import SessionStore

    store = SessionStore()
    r = get_async_redis()
    meta = await store.get_session(session_id)
    if not meta or meta.get("exported"):
        return None
    messages = await store.get_messages(session_id)
    first_user = next((m["content"] for m in messages if m["source"] == "user"), None)
    last_human = next((m["content"] for m in reversed(messages) if m["source"] == "human"), None)
    last_ai = next((m["content"] for m in reversed(messages) if m["source"] == "ai"), None)
    expected = last_human or last_ai
    if not first_user or not expected:
        logger.warning("badcase 导出跳过: session={} 缺少有效问答对", session_id)
        return None

    sample = {
        "case_id": f"badcase_{session_id[:8]}_{time.strftime('%m%d%H%M%S')}",
        "input": first_user,
        "expected_output": expected,
        "allowed_tools": ["query_order", "create_ticket"],
    }
    DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DATASET_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(sample, ensure_ascii=False) + "\n")
    await r.hset(f"session:{session_id}", "exported", "1")
    logger.info("badcase 已沉淀进评测集: {} -> {}", session_id, sample["case_id"])
    return sample


def load_dataset(path: Path = DATASET_PATH) -> List[dict]:
    """读取 JSONL 测试集，跳过解析失败的行并记录日志。"""
    samples: List[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                samples.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.error("数据集第 {} 行解析失败，已跳过: {}", line_no, exc)
    logger.info("数据集加载完成: {} 条样本", len(samples))
    return samples


def run_agent_case(sample: dict) -> dict:
    """调用 Project 2 客服 Agent 执行单条用例，收集实际输出与运行轨迹。

    单条用例执行失败不中断评测，降级返回错误占位结果并计入统计。
    """
    try:
        result = cs_graph.invoke(
            {
                "messages": [HumanMessage(content=sample["input"])],
                "user_id": f"eval_{sample.get('case_id', 'unknown')}",
            },
            config={"recursion_limit": 30},
        )
        actual_output = next(
            (m.content for m in reversed(result["messages"]) if isinstance(m, AIMessage)), ""
        )
        return {
            "actual_output": actual_output,
            "trace": result.get("trace", []),
            "needs_human": result.get("needs_human", False),
            "error": None,
        }
    except Exception as exc:
        logger.error("用例 {} 执行异常: {}", sample.get("case_id"), exc)
        return {
            "actual_output": "",
            "trace": [],
            "needs_human": False,
            "error": str(exc),
        }


def score_relevance(expected: str, actual: str) -> float:
    """基于 difflib.SequenceMatcher 的答案相似度（0-1）。"""
    return difflib.SequenceMatcher(None, expected, actual).ratio()


def evaluate_case(sample: dict) -> dict:
    """执行单条用例的完整评测：Agent 调用 + 护栏检测 + 相似度评分。"""
    case_id = sample.get("case_id", "unknown")
    run = run_agent_case(sample)
    trace = run["trace"]
    allowed_tools = sample.get("allowed_tools", [])

    infinite_loop = detect_infinite_loop(trace)
    unauthorized_tool = detect_unauthorized_tool(trace, allowed_tools)
    similarity = score_relevance(sample.get("expected_output", ""), run["actual_output"])

    case_result = {
        "case_id": case_id,
        "input": sample.get("input", ""),
        "expected_output": sample.get("expected_output", ""),
        "actual_output": run["actual_output"],
        "similarity": round(similarity, 4),
        "passed": similarity >= SIMILARITY_PASS_THRESHOLD and run["error"] is None,
        "needs_human": run["needs_human"],
        "agent_error": run["error"],
        "guardrails": {
            "infinite_loop": infinite_loop,
            "unauthorized_tool": unauthorized_tool,
        },
        "trace": trace,
    }
    logger.info(
        "用例 {} 评测完成: 相似度={:.2f} passed={} 死循环={} 越权={}",
        case_id, similarity, case_result["passed"], infinite_loop, unauthorized_tool,
    )
    return case_result


def run_evaluation(
    dataset_path: Optional[Path] = None, save_report: bool = True
) -> dict:
    """运行全量评测流水线，返回报告字典并可选落盘 JSON。

    Returns:
        含 summary（平均相似度 / 通过率 / 护栏缺陷计数）与 cases 明细的报告。
    """
    samples = load_dataset(dataset_path or DATASET_PATH)
    cases = [evaluate_case(sample) for sample in samples]

    total = len(cases)
    passed_count = sum(1 for c in cases if c["passed"])
    loop_count = sum(1 for c in cases if c["guardrails"]["infinite_loop"])
    unauthorized_count = sum(1 for c in cases if c["guardrails"]["unauthorized_tool"])
    avg_similarity = sum(c["similarity"] for c in cases) / total if total else 0.0

    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_cases": total,
        "summary": {
            "avg_similarity": round(avg_similarity, 4),
            "pass_count": passed_count,
            "pass_rate": round(passed_count / total, 4) if total else 0.0,
            "guardrail_violations": {
                "infinite_loop_triggers": loop_count,
                "unauthorized_tool_triggers": unauthorized_count,
            },
        },
        "cases": cases,
    }
    logger.info(
        "评测完成: {} 条 | 通过率 {:.0%} | 平均相似度 {:.2f} | 死循环 {} | 越权 {}",
        total, report["summary"]["pass_rate"], avg_similarity, loop_count, unauthorized_count,
    )

    if save_report:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        report_file = REPORT_DIR / f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        report_file.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("评测报告已写入: {}", report_file)

    return report
