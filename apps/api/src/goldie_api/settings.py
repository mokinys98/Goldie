from decimal import Decimal
from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Goldie API"
    database_url: str = "sqlite:///./goldie.db"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "local-development-secret-change-me"
    jwt_expiry_minutes: int = 720
    local_admin_email: str = "admin@goldie.local"
    local_admin_password: str = "change-me-now"
    agent_service_token: str = "local-agent-token"
    cors_origins: str = "http://localhost:3000"
    agent_offline_after_seconds: int = 20
    quote_retention_days: int = 30
    shadow_notional_balance: Decimal = Decimal("10000")
    db_pool_size: int = 5
    db_max_overflow: int = 5
    ingestion_concurrency: int = 4
    provider_request_timeout_seconds: float = 30
    oanda_api_token: str = Field(
        default="",
        validation_alias=AliasChoices("OANDA_API_TOKEN", "GOLDIE_OANDA_API_TOKEN"),
    )
    oanda_account_id: str = Field(
        default="",
        validation_alias=AliasChoices("OANDA_ACCOUNT_ID", "GOLDIE_OANDA_ACCOUNT_ID"),
    )
    oanda_rest_url: str = Field(
        default="https://api-fxpractice.oanda.com",
        validation_alias=AliasChoices("OANDA_REST_URL", "GOLDIE_OANDA_REST_URL"),
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: object) -> object:
        if isinstance(value, str) and value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        if isinstance(value, str) and value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
