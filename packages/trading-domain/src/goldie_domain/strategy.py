from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from .models import CandleInput, MarketContext, SignalDecision, SignalType


class BacktestStrategyEvaluator(Protocol):
    def evaluate(
        self,
        candle: CandleInput,
        observed_at: datetime,
    ) -> tuple[SignalType, str]: ...


class Strategy(Protocol):
    name: str
    description: str
    parameters_model: type[BaseModel]

    def required_candles(self, parameters: BaseModel) -> int: ...

    def evaluate(
        self,
        context: MarketContext,
        config: Any,
    ) -> SignalDecision: ...

    def create_backtest_evaluator(
        self,
        config: Any,
        *,
        point: Decimal,
        spread_points: Decimal,
    ) -> BacktestStrategyEvaluator: ...


@dataclass(frozen=True)
class BacktestGuards:
    max_spread_points: Decimal
    spread_points: Decimal
    timezone: ZoneInfo
    start_time: time
    end_time: time

    @classmethod
    def from_config(
        cls,
        config: Any,
        *,
        spread_points: Decimal,
    ) -> "BacktestGuards":
        return cls(
            max_spread_points=config.filters.max_spread_points,
            spread_points=spread_points,
            timezone=ZoneInfo(config.session.timezone),
            start_time=config.session.start_time,
            end_time=config.session.end_time,
        )

    def rejection_reason(self, observed_at: datetime) -> str | None:
        if self.spread_points > self.max_spread_points:
            return "SPREAD_TOO_HIGH"
        now = observed_at if observed_at.tzinfo else observed_at.replace(tzinfo=UTC)
        session_time = (
            now.time().replace(tzinfo=None)
            if self.timezone.key == "UTC"
            else now.astimezone(self.timezone).time().replace(tzinfo=None)
        )
        in_session = (
            self.start_time <= session_time < self.end_time
            if self.start_time < self.end_time
            else (session_time >= self.start_time or session_time < self.end_time)
        )
        return None if in_session else "OUTSIDE_TRADING_SESSION"


def completed(context: MarketContext) -> list:
    return sorted(
        (candle for candle in context.candles if candle.is_complete),
        key=lambda candle: candle.opened_at,
    )


def common_guard(
    context: MarketContext,
    config: Any,
    inputs: dict[str, str | int | bool | None],
) -> SignalDecision | dict:
    spread_points = (context.ask - context.bid) / context.point
    common = {
        "observed_at": context.observed_at,
        "spread_points": spread_points,
        "inputs": inputs,
    }
    now = context.observed_at
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    evaluated_at = context.evaluated_at or datetime_now_utc()
    if evaluated_at.tzinfo is None:
        evaluated_at = evaluated_at.replace(tzinfo=UTC)
    age = (evaluated_at.astimezone(UTC) - now.astimezone(UTC)).total_seconds()
    if age > config.filters.stale_after_seconds:
        return SignalDecision(
            signal=SignalType.NO_TRADE,
            reason_code="STALE_MARKET_DATA",
            **common,
        )
    if spread_points > config.filters.max_spread_points:
        return SignalDecision(
            signal=SignalType.NO_TRADE,
            reason_code="SPREAD_TOO_HIGH",
            **common,
        )
    session_time = now.astimezone(ZoneInfo(config.session.timezone)).time().replace(tzinfo=None)
    start = config.session.start_time
    end = config.session.end_time
    in_session = (
        start <= session_time < end
        if start < end
        else (session_time >= start or session_time < end)
    )
    if not in_session:
        return SignalDecision(
            signal=SignalType.NO_TRADE,
            reason_code="OUTSIDE_TRADING_SESSION",
            **common,
        )
    return common


def trade_prices(
    signal: SignalType,
    context: MarketContext,
    config: Any,
) -> tuple[Decimal, Decimal, Decimal]:
    if signal == SignalType.BUY:
        entry = context.ask
        stop_loss = entry - config.theoretical_trade.stop_loss_points * context.point
        take_profit = entry + config.theoretical_trade.take_profit_points * context.point
    else:
        entry = context.bid
        stop_loss = entry + config.theoretical_trade.stop_loss_points * context.point
        take_profit = entry - config.theoretical_trade.take_profit_points * context.point
    return entry, stop_loss, take_profit


def datetime_now_utc():
    from datetime import datetime

    return datetime.now(UTC)
