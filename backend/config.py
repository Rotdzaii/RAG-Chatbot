from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    gemini_api_key: SecretStr | None = None
    rag_trace_enabled: bool = False

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
