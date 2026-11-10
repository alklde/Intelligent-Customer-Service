"""LLM 工厂模块。

统一创建 OpenAI 兼容的 ChatOpenAI / OpenAIEmbeddings 实例，
屏蔽 Ollama、vLLM 等本地推理后端的接入差异。
"""

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from loguru import logger

from config import settings


def get_chat_model(temperature: float | None = None) -> ChatOpenAI:
    """创建指向本地 OpenAI 兼容服务的 Chat 模型。

    Args:
        temperature: 采样温度；None 时使用全局配置默认值。

    Returns:
        ChatOpenAI 实例（内部重试关闭，重试策略由各节点自行控制）。
    """
    model = ChatOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        temperature=settings.llm_temperature if temperature is None else temperature,
        timeout=settings.llm_request_timeout,
        max_retries=0,
    )
    logger.debug("ChatModel 就绪: model={} base_url={}", settings.llm_model, settings.llm_base_url)
    return model


def get_embeddings() -> OpenAIEmbeddings:
    """创建 OpenAI 兼容的 Embeddings 实例，用于 Qdrant 文本向量化。

    Returns:
        OpenAIEmbeddings 实例（关闭本地 token 截断检查以兼容 Ollama 端点）。
    """
    return OpenAIEmbeddings(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.embedding_model,
        timeout=settings.llm_request_timeout,
        check_embedding_ctx_length=False,
    )
