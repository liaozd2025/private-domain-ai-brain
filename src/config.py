"""配置中心 - 所有环境变量和系统配置的单一入口"""

from enum import Enum
from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    CLAUDE = "claude"
    QWEN = "qwen"
    OPENAI = "openai"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ===== LLM 配置 =====
    anthropic_api_key: str = Field(default="", description="Anthropic API Key")
    dashscope_api_key: str = Field(default="", description="阿里云通义千问 API Key")
    openai_api_key: str = Field(default="", description="OpenAI API Key")
    openai_base_url: str = Field(default="https://api.openai.com/v1")

    primary_llm: LLMProvider = Field(default=LLMProvider.OPENAI, description="主力 LLM 提供商")
    primary_model: str = Field(default="Pro/MiniMaxAI/MiniMax-M2.5", description="主力模型 ID")

    router_llm: LLMProvider = Field(default=LLMProvider.QWEN, description="路由分类 LLM")
    router_model: str = Field(default="qwen-plus", description="路由分类模型 ID")
    vision_llm: LLMProvider = Field(default=LLMProvider.OPENAI, description="视觉模型提供商")
    vision_model: str = Field(default="Qwen/Qwen2.5-VL-72B-Instruct", description="视觉模型 ID")

    # ===== 数据库配置 =====
    postgres_host: str = Field(default="localhost")
    postgres_port: int = Field(default=5432)
    postgres_db: str = Field(default="ai_brain")
    postgres_user: str = Field(default="ai_brain")
    postgres_password: str = Field(default="changeme")

    @computed_field
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field
    @property
    def database_url_sync(self) -> str:
        """同步连接 URL，用于 LangGraph checkpointer"""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ===== Milvus 配置 =====
    milvus_host: str = Field(default="localhost")
    milvus_port: int = Field(default=19530)
    milvus_token: str = Field(default="")
    milvus_uri: str = Field(default="")
    milvus_collection_name: str = Field(default="private_domain_knowledge")
    milvus_top_k: int = Field(default=10, description="检索 Top-K")
    milvus_rerank_top_k: int = Field(default=5, description="重排后保留数量")

    @computed_field
    @property
    def milvus_connection_args(self) -> dict:
        if self.milvus_uri:
            return {"uri": self.milvus_uri, "token": self.milvus_token}
        return {"host": self.milvus_host, "port": self.milvus_port}

    # ===== Embedding / Reranker =====
    embedding_model: str = Field(default="BAAI/bge-large-zh-v1.5")
    reranker_model: str = Field(default="BAAI/bge-reranker-v2-m3")
    embedding_device: str = Field(default="cpu")
    embedding_dim: int = Field(default=1024, description="bge-large-zh 维度")

    # ===== 文件存储 =====
    upload_dir: str = Field(default="./uploads")
    max_upload_size_mb: int = Field(default=50)

    @computed_field
    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    # ===== API 配置 =====
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    api_cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:8080"]
    )

    # ===== 企微配置 =====
    wecom_token: str = Field(default="")
    wecom_encoding_aes_key: str = Field(default="")
    wecom_corp_id: str = Field(default="")
    wecom_agent_id: str = Field(default="")
    wecom_secret: str = Field(default="")

    # ===== OpenClaw 配置 =====
    openclaw_base_url: str = Field(default="https://api.openclaw.io")
    openclaw_api_key: str = Field(default="")

    # ===== 监控 =====
    langfuse_host: str = Field(default="https://cloud.langfuse.com")
    langfuse_public_key: str = Field(default="")
    langfuse_secret_key: str = Field(default="")
    enable_tracing: bool = Field(default=False)

    # ===== 应用配置 =====
    app_env: Literal["development", "staging", "production"] = Field(default="development")
    log_level: str = Field(default="INFO")
    secret_key: str = Field(default="change-this-in-production")

    @computed_field
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


# 全局 settings 实例
settings = get_settings()
