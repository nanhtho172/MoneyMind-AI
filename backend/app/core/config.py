from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "MoneyMind AI"
    app_env: str = "development"
    database_url: str = "sqlite:///./data/moneymind.db"
    auth_secret_key: SecretStr
    access_token_expire_minutes: int = Field(default=120, gt=0)
    llm_provider: str = "groq"
    llm_base_url: AnyHttpUrl = "https://api.groq.com/openai/v1"
    llm_model: str = "openai/gpt-oss-120b"
    llm_reasoning_effort: Literal["low", "medium", "high"] = "low"
    llm_api_key: SecretStr | None = None
    groq_ip_family: Literal["auto", "ipv4", "ipv6"] = "auto"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    rag_top_k: int = Field(default=3, ge=1, le=8)
    rag_min_similarity: float = Field(default=0.46, ge=0, le=1)
    rag_chunk_size: int = Field(default=500, ge=150, le=2000)
    rag_chunk_overlap: int = Field(default=80, ge=0, le=500)
    rag_upload_max_bytes: int = Field(default=10 * 1024**2, ge=1024, le=50 * 1024**2)
    rag_upload_directory: Path = Path("data/knowledge/uploads")
    rag_directory: Path = Path("data/chroma")
    agent_checkpoint_path: Path = Path("data/agent-checkpoints.db")
    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "moneymind-local"

    @model_validator(mode="after")
    def validate_rag_chunking(self):
        if 2 * self.rag_chunk_overlap >= self.rag_chunk_size:
            raise ValueError("RAG_CHUNK_OVERLAP must be less than half of RAG_CHUNK_SIZE")
        return self

    @field_validator("rag_directory", "rag_upload_directory", "agent_checkpoint_path")
    @classmethod
    def resolve_local_path(cls, value: Path) -> Path:
        return (PROJECT_ROOT / value).resolve()

    @field_validator("auth_secret_key")
    @classmethod
    def validate_secret(cls, secret: SecretStr) -> SecretStr:
        if len(secret.get_secret_value().encode("utf-8")) < 32:
            raise ValueError("AUTH_SECRET_KEY must contain at least 32 bytes")
        return secret

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        url = make_url(value)
        if url.drivername not in {"sqlite", "sqlite+pysqlite"}:
            raise ValueError("DATABASE_URL must use SQLite")
        if url.database and url.database != ":memory:":
            path = PROJECT_ROOT / url.database
            url = url.set(database=str(path.resolve()))
        return url.render_as_string(hide_password=False)
