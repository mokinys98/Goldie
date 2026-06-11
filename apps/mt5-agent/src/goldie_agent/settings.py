import uuid

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GOLDIE_", extra="ignore")

    api_url: str = "http://localhost:8000"
    agent_token: str = "local-agent-token"
    bot_id: uuid.UUID
    agent_mode: str = "fake"
    agent_name: str = "local-market-agent"
    poll_seconds: float = 2.0
    heartbeat_seconds: float = 5.0
    metadata_seconds: float = 30.0

    mt5_terminal_path: str | None = None
    mt5_login: int | None = None
    mt5_password: str | None = None
    mt5_server: str | None = None
    mt5_symbol: str | None = None
    mt5_symbol_hint: str = "XAU"
