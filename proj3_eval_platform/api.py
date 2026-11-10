"""Agent 评测与护栏平台的 FastAPI 路由。

- POST /evaluate: 触发全量评测流水线，返回 JSON 评测报告（需客服令牌）。
- POST /guardrails/check: 护栏即服务——对任意轨迹实时做死循环 / 越权检测（需客服令牌）。
"""

from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from core.auth_deps import require_staff
from proj3_eval_platform.evaluator import run_evaluation
from proj3_eval_platform.guardrails import detect_infinite_loop, detect_unauthorized_tool

app = FastAPI(title="Agent 评测与护栏平台", version="2.0.0")


class GuardrailCheckRequest(BaseModel):
    """护栏检测请求：轨迹 + 工具白名单。"""

    trace: List[dict] = Field(..., description="Agent 运行轨迹，元素含 tool / args 字段")
    allowed_tools: List[str] = Field(default_factory=list, description="工具白名单")


class GuardrailCheckResponse(BaseModel):
    """护栏检测结果。"""

    infinite_loop: bool = Field(..., description="是否触发死循环缺陷")
    unauthorized_tool: bool = Field(..., description="是否触发越权工具缺陷")


class EvaluateRequest(BaseModel):
    """评测触发请求，可指定自定义数据集路径。"""

    dataset_path: Optional[str] = Field(default=None, description="可选的自定义 JSONL 数据集路径")
    save_report: bool = Field(default=True, description="是否将报告落盘")


@app.get("/")
def root() -> dict:
    """服务欢迎页，提供可用端点导航。"""
    return {
        "service": "Agent 评测与护栏平台",
        "docs": "/docs",
        "endpoints": {
            "POST /evaluate": "触发全量评测流水线",
            "POST /guardrails/check": "轨迹护栏检测（死循环 / 越权）",
            "GET /health": "健康探针",
        },
    }


@app.get("/health")
def health() -> dict:
    """健康探针。"""
    return {"status": "ok", "service": "proj3_eval_platform"}


@app.post("/guardrails/check", response_model=GuardrailCheckResponse)
def guardrails_check(
    req: GuardrailCheckRequest, _auth=Depends(require_staff)
) -> GuardrailCheckResponse:
    """护栏即服务：毫秒级轨迹缺陷检测，不调用 LLM（需客服令牌）。"""
    try:
        return GuardrailCheckResponse(
            infinite_loop=detect_infinite_loop(req.trace),
            unauthorized_tool=detect_unauthorized_tool(req.trace, req.allowed_tools),
        )
    except Exception as exc:
        logger.error("护栏检测异常: {}", exc)
        raise HTTPException(status_code=500, detail="护栏检测服务内部错误")


@app.post("/evaluate")
def evaluate(req: EvaluateRequest, _auth=Depends(require_staff)) -> dict:
    """触发全量评测流水线并返回报告（需客服令牌）。"""
    dataset_path = Path(req.dataset_path) if req.dataset_path else None
    if dataset_path is not None and not dataset_path.exists():
        raise HTTPException(status_code=404, detail=f"数据集不存在: {dataset_path}")
    try:
        return run_evaluation(dataset_path=dataset_path, save_report=req.save_report)
    except Exception as exc:
        logger.error("评测流水线执行失败: {}", exc)
        raise HTTPException(status_code=500, detail="评测流水线内部错误")
