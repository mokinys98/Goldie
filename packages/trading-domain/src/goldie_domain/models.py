from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SignalType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    NO_TRADE = "NO_TRADE"


class CandleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opened_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    is_complete: bool = True


class MarketContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_at: datetime
    bid: Decimal
    ask: Decimal
    point: Decimal = Field(gt=0)
    candles: list[CandleInput]


class SignalDecision(BaseModel):
    signal: SignalType
    reason_code: str
    observed_at: datetime
    entry_price: Decimal | None = None
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    momentum_points: Decimal | None = None
    spread_points: Decimal | None = None
    inputs: dict[str, str | int | bool | None] = Field(default_factory=dict)
