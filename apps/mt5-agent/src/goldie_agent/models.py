from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class AccountData(BaseModel):
    observed_at: datetime
    broker: str
    server: str
    login: str
    currency: str
    balance: Decimal
    equity: Decimal
    margin_free: Decimal
    leverage: int
    is_demo: bool


class SymbolData(BaseModel):
    symbol: str
    digits: int
    point: Decimal
    tick_size: Decimal
    tick_value: Decimal
    contract_size: Decimal
    volume_min: Decimal
    volume_max: Decimal
    volume_step: Decimal


class TickData(BaseModel):
    symbol: str
    observed_at: datetime
    bid: Decimal
    ask: Decimal


class CandleData(BaseModel):
    symbol: str
    timeframe: str = "M1"
    opened_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    tick_volume: int
    is_complete: bool = True
