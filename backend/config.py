from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    gemini_api_key: SecretStr | None = None
    rag_trace_enabled: bool = False
    rag_query_model: Literal["gemini-3.6-flash", "gemini-3.8-flash"] = "gemini-3.6-flash"
    rag_generation_model: Literal["gemini-3.6-flash", "gemini-3.8-flash"] = "gemini-3.6-flash"
    supabase_url: str | None = None
    supabase_publishable_key: SecretStr | None = None
    admin_user_id: UUID | None = None
    rag_source_file_dir: Path = Path(__file__).resolve().parent.parent / "data" / "source_files"
    rag_tesseract_cmd: str = "tesseract"
    rag_ocr_timeout_seconds: float = Field(default=60, gt=0)

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
