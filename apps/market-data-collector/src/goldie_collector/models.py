from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class Quote(BaseModel):
    observed_at: datetime
    bid: Decimal
    ask: Decimal


class Candle(BaseModel):
    opened_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    complete: bool


class Instrument(BaseModel):
    canonical_symbol: str
    provider_symbol: str
    display_precision: int
    pip_location: int
    minimum_trade_size: Decimal | None
    trade_units_precision: int | None
    margin_rate: Decimal | None
    provider_metadata: dict
