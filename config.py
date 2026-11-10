"""全局配置模块。

基于 pydantic-settings 统一管理环境变量与默认值，
为各子项目提供类型安全的配置入口。
优先级：环境变量 > .env 文件 > 代码默认值。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置项，字段名与环境变量名大小写不敏感。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- LLM（OpenAI 兼容接口：Ollama / vLLM）----
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "qwen2.5:7b"
    llm_temperature: float = 0.0
    llm_request_timeout: float = 60.0

    # ---- Embedding（同样走 OpenAI 兼容接口，供 Qdrant 向量化使用）----
    embedding_model: str = "nomic-embed-text"
    embedding_dim: int = 768

    # ---- Qdrant ----
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "rag_knowledge_base"
    qdrant_top_k: int = 4
    qdrant_timeout: float = 5.0

    # ---- Redis（会话 / 队列 / 工单存储）----
    redis_url: str = "redis://localhost:6379/1"

    # ---- 认证 / 账号体系 ----
    auth_token_ttl_customer: int = 86400   # 客户令牌有效期（秒）
    auth_token_ttl_staff: int = 43200      # 客服令牌有效期（秒）
    captcha_ttl: int = 120                 # 图形验证码有效期（秒）
    login_max_failures: int = 5            # 连续失败上限
    login_lock_seconds: int = 900          # 触发上限后的锁定窗口（秒）
    bcrypt_rounds: int = 12                # 密码 / 密钥哈希强度
    admin_bootstrap_key: str = "SUITE-BOOTSTRAP-2026"  # 首次初始化管理员的引导密钥

    # ---- 转人工 ----
    human_queue_context_messages: int = 6  # 入队时携带的最近消息条数

    # ---- 知识库文档处理 ----
    kb_chunk_size: int = 420          # 分块目标字符数
    kb_chunk_overlap: int = 60        # 分块重叠字符数
    kb_min_chars: int = 20            # 文档正文最小长度
    kb_max_chars: int = 50000         # 文档正文最大长度（超长拒绝）

    # ---- Agent 通用阈值 ----
    grade_threshold: float = 0.7        # 文档相关性打分下限
    hallucination_threshold: float = 0.3  # 幻觉分数上限，超过则重试
    max_generation_retries: int = 2     # 幻觉检测最大重试次数
    tool_timeout: float = 3.0           # 单次工具执行超时（秒）
    max_tool_failures: int = 3          # 工具连续失败次数上限，达到即转人工


@lru_cache
def get_settings() -> Settings:
    """返回全局单例配置，避免重复解析环境变量。"""
    return Settings()


settings = get_settings()
