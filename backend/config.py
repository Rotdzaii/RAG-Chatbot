from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    gemini_api_key: SecretStr | None = None

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
