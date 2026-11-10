"""统一异常定义模块。

所有子项目的节点 / 工具 / API 层统一抛出并捕获这里定义的异常，
便于在最外层做一致的降级与兜底处理。
"""


class AgentSuiteError(Exception):
    """项目内所有自定义异常的基类。"""


class LLMInvocationError(AgentSuiteError):
    """LLM 调用失败：网络异常、超时或返回结构不合法。"""


class VectorStoreError(AgentSuiteError):
    """Qdrant 向量库操作失败（连接中断、集合不存在等）。"""


class ToolExecutionError(AgentSuiteError):
    """外部工具执行失败或超时（熔断计数依据）。"""


class GuardrailViolationError(AgentSuiteError):
    """命中护栏规则：死循环、越权工具调用等。"""
