"""loguru 日志初始化模块。

在包导入时完成全局日志配置：控制台输出 INFO 级别，
文件按天轮转并保留 7 天，输出 DEBUG 级别用于排查。
"""

import sys

from loguru import logger

_CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)


def setup_logger() -> None:
    """移除默认 handler 并注册控制台 + 滚动文件两个 sink。"""
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        format=_CONSOLE_FORMAT,
        enqueue=True,
    )
    logger.add(
        "logs/ai_agent_suite_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        rotation="00:00",
        retention="7 days",
        encoding="utf-8",
        enqueue=True,
    )


setup_logger()
