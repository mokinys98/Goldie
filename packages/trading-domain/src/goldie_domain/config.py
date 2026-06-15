from datetime import time
from decimal import Decimal
from zoneinfo import ZoneInfo

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MarketConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(
        default="EURUSD",
        min_length=1,
        max_length=32,
        description="Instrumentas, kurio rinkos duomenis naudoja botas.",
        json_schema_extra={"unit": "symbol", "impact": "Keičia analizuojamą rinką."},
    )
    timeframe: str = Field(
        default="M1",
        pattern="^M1$",
        description="Užbaigtų žvakių periodas, naudojamas strategijos sprendimams.",
        json_schema_extra={"unit": "timeframe", "impact": "Didesnis periodas signalus retintų."},
    )


class StrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        default="basic_momentum",
        description="Vykdomo strategijos algoritmo techninis identifikatorius.",
        json_schema_extra={"unit": "strategy", "impact": "Pakeičia signalo generavimo logiką."},
    )
    parameters: dict[str, Any] = Field(
        default_factory=lambda: {
            "lookback_candles": 5,
            "min_momentum_points": "50",
        }
    )

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_parameters(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        parameters = dict(data.get("parameters") or {})
        for key in ("lookback_candles", "min_momentum_points"):
            if key in data:
                parameters[key] = data.pop(key)
        data["parameters"] = parameters
        return data

    @model_validator(mode="after")
    def validate_parameters(self) -> "StrategyConfig":
        from .registry import validate_strategy_parameters

        validated = validate_strategy_parameters(self.name, self.parameters)
        self.parameters = validated.model_dump(mode="json")
        return self


class FilterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_spread_points: Decimal = Field(
        default=Decimal("30"),
        gt=0,
        le=10000,
        description="Didžiausias leidžiamas bid ir ask kainų skirtumas.",
        json_schema_extra={
            "unit": "points",
            "impact": "Mažinant ribą sandorių mažėja, bet vykdymo kaina paprastai gerėja.",
        },
    )
    stale_after_seconds: int = Field(
        default=15,
        ge=2,
        le=300,
        description="Po kiek sekundžių rinkos duomenys laikomi pasenusiais.",
        json_schema_extra={
            "unit": "seconds",
            "impact": "Mažesnė reikšmė greičiau blokuoja prekybą sutrikus duomenims.",
        },
    )


class SessionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str = Field(
        default="Europe/Vilnius",
        description="IANA laiko zona, pagal kurią interpretuojama prekybos sesija.",
        json_schema_extra={"unit": "timezone", "impact": "Keičia sesijos laikų perskaičiavimą į UTC."},
    )
    start_time: time = Field(
        default=time(10, 0),
        description="Vietinis laikas, nuo kurio strategijai leidžiama generuoti sandorius.",
        json_schema_extra={"unit": "local time", "impact": "Vėlesnis laikas sutrumpina sesiją."},
    )
    end_time: time = Field(
        default=time(18, 0),
        description="Vietinis laikas, nuo kurio nauji strategijos sandoriai blokuojami.",
        json_schema_extra={"unit": "local time", "impact": "Ankstesnis laikas sutrumpina sesiją."},
    )

    @model_validator(mode="after")
    def validate_session(self) -> "SessionConfig":
        ZoneInfo(self.timezone)
        if self.start_time == self.end_time:
            raise ValueError("Session start and end must differ")
        return self


class TheoreticalTradeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stop_loss_points: Decimal = Field(
        default=Decimal("70"),
        gt=0,
        le=100000,
        description="Atstumas nuo įėjimo kainos iki apsauginio stop-loss.",
        json_schema_extra={"unit": "points", "impact": "Didinant stopas tolsta ir tam pačiam risk mažėja pozicija."},
    )
    take_profit_points: Decimal = Field(
        default=Decimal("100"),
        gt=0,
        le=100000,
        description="Atstumas nuo įėjimo kainos iki pelno fiksavimo lygio.",
        json_schema_extra={"unit": "points", "impact": "Didinant tikslas tolsta ir gali mažėti laimėjimų dažnis."},
    )
    risk_per_trade_pct: Decimal = Field(
        default=Decimal("0.25"),
        gt=0,
        le=100,
        description="Sąskaitos kapitalo dalis, kurią leidžiama rizikuoti vienu sandoriu.",
        json_schema_extra={"unit": "percent", "impact": "Didinant tiesiogiai didėja pozicijos dydis ir nuostolio rizika."},
    )
    max_trade_duration_minutes: int = Field(
        default=5,
        ge=1,
        le=1440,
        description="Ilgiausia teorinės pozicijos laikymo trukmė.",
        json_schema_extra={"unit": "minutes", "impact": "Didinant pozicijai suteikiama daugiau laiko pasiekti SL arba TP."},
    )
    max_open_shadow_positions: int = Field(
        default=1,
        ge=1,
        le=1,
        description="Didžiausias vienu metu leidžiamų atvirų shadow pozicijų skaičius.",
        json_schema_extra={"unit": "positions", "impact": "Riboja vienu metu modeliuojamą ekspoziciją."},
    )


class BotConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: MarketConfig = Field(default_factory=MarketConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    filters: FilterConfig = Field(default_factory=FilterConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    theoretical_trade: TheoreticalTradeConfig = Field(default_factory=TheoreticalTradeConfig)


DEFAULT_BOT_CONFIGURATION = BotConfiguration().model_dump(mode="json")
