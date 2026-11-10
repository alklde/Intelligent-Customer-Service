"""一键启动脚本：并行拉起四个 FastAPI 服务并支持优雅退出。

用法：
    python run_all.py               # 环境预检 + 前台启动，Ctrl+C / kill 触发优雅退出
    python run_all.py --skip-check  # 跳过环境预检直接启动
    python run_all.py --check       # 仅执行环境预检，不启动服务
"""

import argparse
import signal
import subprocess
import sys
import urllib.request
from pathlib import Path

from loguru import logger

ROOT = Path(__file__).parent

SERVICES = [
    {"name": "proj1_rag 知识库", "module": "proj1_rag.api:app", "port": 8001},
    {"name": "proj2 智能客服", "module": "proj2_customer_service.api:app", "port": 8002},
    {"name": "proj3 评测护栏", "module": "proj3_eval_platform.api:app", "port": 8003},
    {"name": "proj4 客服工作台后台", "module": "proj4_admin.api:app", "port": 8004},
]


def _ping(url: str, timeout: float = 3.0) -> bool:
    """探测 HTTP 服务是否可达。"""
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except Exception:
        return False


def precheck() -> None:
    """环境预检：检查 Ollama 与 Qdrant 可达性，仅告警不阻断（各节点具备降级能力）。"""
    if _ping("http://localhost:11434/api/tags"):
        logger.info("预检通过: Ollama (localhost:11434) 可达")
    else:
        logger.warning("预检告警: Ollama 不可达，LLM 节点将走 try-except 降级逻辑")
    if _ping("http://localhost:6333/readyz"):
        logger.info("预检通过: Qdrant (localhost:6333) 可达")
    else:
        logger.warning("预检告警: Qdrant 不可达，RAG 检索将降级为空列表")


def start_services() -> list:
    """以当前 Python 解释器启动四个 uvicorn 子进程。"""
    procs = []
    for svc in SERVICES:
        cmd = [
            sys.executable, "-m", "uvicorn", svc["module"],
            "--host", "0.0.0.0", "--port", str(svc["port"]),
        ]
        procs.append(subprocess.Popen(cmd, cwd=ROOT))
        logger.info("已启动 {}: http://localhost:{}", svc["name"], svc["port"])
    return procs


def main() -> None:
    """入口：解析参数 → 预检 → 启动 → 注册信号处理，阻塞至退出。"""
    parser = argparse.ArgumentParser(description="AI Agent Suite 一键启动器")
    parser.add_argument("--check", action="store_true", help="仅执行环境预检")
    parser.add_argument("--skip-check", action="store_true", help="跳过环境预检")
    args = parser.parse_args()

    if not args.skip_check:
        precheck()
    if args.check:
        return

    procs = start_services()

    def _shutdown(signum, frame):
        logger.warning("收到信号 {}，正在终止所有服务...", signum)
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        logger.info("所有服务已停止，退出完成")
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    for proc in procs:
        proc.wait()


if __name__ == "__main__":
    main()
