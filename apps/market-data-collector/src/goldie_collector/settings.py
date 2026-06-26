from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_INSTRUMENTS = (
    "EUR_USD,GBP_USD,USD_JPY,USD_CHF,USD_CAD,"
    "AUD_USD,NZD_USD,EUR_GBP,EUR_JPY,GBP_JPY"
)
DEFAULT_BINANCE_SPOT_INSTRUMENTS = "BTCUSDT,ETHUSDT"


class CollectorSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GOLDIE_",
        extra="ignore",
        populate_by_name=True,
    )

    api_url: str
    agent_token: str
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias=AliasChoices("INGESTION_REDIS_URL", "REDIS_URL", "GOLDIE_REDIS_URL"),
    )
    ingestion_transport: str = Field(
        default="http",
        pattern="^(http|redis)$",
        validation_alias=AliasChoices("INGESTION_TRANSPORT", "GOLDIE_INGESTION_TRANSPORT"),
    )
    agent_name: str = "railway-oanda-collector"
    provider: str = Field(default="oanda", pattern="^(oanda|binance_spot)$")
    provider_environment: str = Field(default="practice", pattern="^(practice|live|spot)$")
    instruments: str = DEFAULT_INSTRUMENTS
    binance_spot_instruments: str = DEFAULT_BINANCE_SPOT_INSTRUMENTS
    canonical_symbol: str = Field(default="EURUSD", pattern="^[A-Z0-9]{3,32}$")
    provider_symbol: str = Field(default="EUR_USD", pattern="^[A-Z0-9_]{3,64}$")
    quote_interval_seconds: float = Field(default=5.0, ge=1, le=60)
    candle_poll_seconds: float = Field(default=15.0, ge=5, le=300)
    heartbeat_seconds: float = Field(default=10.0, ge=5, le=300)
    backfill_days: int = Field(default=30, ge=1, le=365)
    backfill_batch_size: int = Field(default=50, ge=50, le=1000)
    request_timeout_seconds: float = Field(default=60.0, ge=5, le=120)
    quote_batch_seconds: float = Field(default=1.0, ge=0.1, le=10)
    quote_batch_size: int = Field(default=250, ge=1, le=1000)
    candle_batch_size: int = Field(default=50, ge=1, le=5000)
    configuration_retry_seconds: float = Field(default=900.0, ge=60, le=86400)

    oanda_api_token: str
    oanda_account_id: str
    oanda_rest_url: str = "https://api-fxpractice.oanda.com"
    oanda_stream_url: str = "https://stream-fxpractice.oanda.com"

    @field_validator("instruments")
    @classmethod
    def validate_instruments(cls, value: str) -> str:
        symbols = cls.parse_instruments(value)
        if not symbols:
            raise ValueError("At least one OANDA instrument is required")
        if len(symbols) > 20:
            raise ValueError("At most 20 OANDA instruments are supported per collector")
        return ",".join(symbols)

    @field_validator("binance_spot_instruments")
    @classmethod
    def validate_binance_spot_instruments(cls, value: str) -> str:
        symbols = cls.parse_instruments(value, require_separator=False)
        if not symbols:
            return ""
        if len(symbols) > 20:
            raise ValueError("At most 20 Binance spot instruments are supported per collector")
        return ",".join(symbols)

    @staticmethod
    def parse_instruments(value: str, *, require_separator: bool = True) -> list[str]:
        symbols: list[str] = []
        for item in value.split(","):
            symbol = item.strip().upper()
            if not symbol:
                continue
            parts = symbol.split("_")
            if (
                require_separator
                and (len(parts) != 2 or not all(part.isalnum() for part in parts))
            ) or (not require_separator and not symbol.replace("_", "").isalnum()):
                raise ValueError(f"Invalid OANDA instrument: {symbol}")
            if symbol not in symbols:
                symbols.append(symbol)
        return symbols

    @property
    def instrument_symbols(self) -> list[str]:
        return self.parse_instruments(self.instruments)

    @property
    def instrument_specs(self) -> list[dict[str, str]]:
        specs = [
            {
                "provider": "oanda",
                "environment": self.provider_environment
                if self.provider == "oanda"
                else "practice",
                "provider_symbol": symbol,
            }
            for symbol in self.instrument_symbols
        ]
        specs.extend(
            {
                "provider": "binance_spot",
                "environment": "spot",
                "provider_symbol": symbol,
            }
            for symbol in self.parse_instruments(
                self.binance_spot_instruments,
                require_separator=False,
            )
        )
        return specs

    def for_instrument(
        self,
        provider_symbol: str,
        *,
        provider: str | None = None,
        environment: str | None = None,
    ) -> "CollectorSettings":
        selected_provider = provider or self.provider
        selected_environment = environment or (
            "spot" if selected_provider == "binance_spot" else self.provider_environment
        )
        return self.model_copy(
            update={
                "provider": selected_provider,
                "provider_environment": selected_environment,
                "provider_symbol": provider_symbol,
                "canonical_symbol": provider_symbol.replace("_", ""),
                "agent_name": (
                    f"{self.agent_name}-{selected_provider}-{provider_symbol.lower()}"
                ),
            }
        )
