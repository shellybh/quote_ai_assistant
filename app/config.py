"""Settings from environment variables (and a local, git-ignored .env)."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Required: the server refuses to start without them.
    app_token: SecretStr
    gemini_model: str

    # Optional at startup so tests and /health run without a key;
    # an AI request without it fails.
    gemini_api_key: SecretStr | None = None
    gemini_embedding_model: str = "gemini-embedding-2"
    gemini_thinking_level: str = "MINIMAL"
    # Not sent by default: Gemini 3.x recommends the default (1.0), and
    # 3.5-flash-lite ignores custom values. Set only for models that honour it.
    gemini_temperature: float | None = None

    max_request_mb: float = 1.0
    request_timeout_s: float = 60.0
    rate_limit: str = "20/minute"

    @property
    def max_request_bytes(self) -> int:
        return int(self.max_request_mb * 1024 * 1024)


@lru_cache
def get_settings() -> Settings:
    return Settings()
