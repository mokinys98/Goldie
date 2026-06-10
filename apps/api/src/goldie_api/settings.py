from functools import lru_cache

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

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
