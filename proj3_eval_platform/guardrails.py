"""护栏检测器：纯 Python 实现，不调用 LLM，保证毫秒级低延迟。

轨迹（trace）格式约定：每个元素代表一次工具调用，
    {"tool": str, "args": dict, "ok": bool, "timestamp": float}
"""

import json
from typing import List

from loguru import logger


def _args_key(args: dict) -> str:
    """将参数字典序列化为稳定可比较的字符串。

    非 JSON 可序列化对象降级为 str()，确保护栏永不抛异常。
    """
    try:
        return json.dumps(args, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(sorted(args)) if isinstance(args, dict) else str(args)


def detect_infinite_loop(trace: List[dict]) -> bool:
    """死循环检测：同一工具以完全相同参数连续调用超过 3 次。

    Args:
        trace: Agent 运行轨迹列表。

    Returns:
        True 表示判定为死循环（缺陷触发）。
    """
    max_run = 0
    current_key = None
    current_run = 0
    for step in trace:
        key = (step.get("tool"), _args_key(step.get("args", {})))
        if key == current_key:
            current_run += 1
        else:
            current_key = key
            current_run = 1
        max_run = max(max_run, current_run)
    is_loop = max_run > 3
    if is_loop:
        logger.warning(
            "护栏触发[死循环]: 同一工具相同参数连续调用 {} 次", max_run,
        )
    return is_loop


def detect_unauthorized_tool(trace: List[dict], allowed_tools: List[str]) -> bool:
    """越权检测：轨迹中出现白名单之外的工具调用（越权 / 幻觉工具）。

    Args:
        trace: Agent 运行轨迹列表。
        allowed_tools: 本用例允许调用的工具白名单。

    Returns:
        True 表示存在越权工具调用（缺陷触发）。
    """
    allowed = set(allowed_tools)
    for step in trace:
        tool_name = step.get("tool", "")
        if tool_name not in allowed:
            logger.warning(
                "护栏触发[越权工具]: '{}' 不在白名单 {} 中", tool_name, sorted(allowed),
            )
            return True
    return False
