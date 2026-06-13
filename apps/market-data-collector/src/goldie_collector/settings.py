from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CollectorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GOLDIE_", extra="ignore")

    api_url: str
    agent_token: str
    agent_name: str = "railway-oanda-collector"
    provider: str = Field(default="oanda", pattern="^oanda$")
    provider_environment: str = Field(default="practice", pattern="^(practice|live)$")
    canonical_symbol: str = Field(default="XAUUSD", pattern="^XAUUSD$")
    provider_symbol: str = Field(default="XAU_USD", pattern="^XAU_USD$")
    quote_interval_seconds: float = Field(default=5.0, ge=1, le=60)
    candle_poll_seconds: float = Field(default=15.0, ge=5, le=300)
    heartbeat_seconds: float = Field(default=10.0, ge=5, le=300)
    backfill_days: int = Field(default=30, ge=1, le=365)
    request_timeout_seconds: float = Field(default=20.0, ge=5, le=120)

    oanda_api_token: str
    oanda_account_id: str
    oanda_rest_url: str = "https://api-fxpractice.oanda.com"
    oanda_stream_url: str = "https://stream-fxpractice.oanda.com"
