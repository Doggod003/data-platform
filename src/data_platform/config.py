"""Central configuration. Reads from environment / .env — never hardcode secrets."""

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    log_level: str = Field(default="INFO")
    # api_key: str | None = None
    # database_url: str | None = None

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
