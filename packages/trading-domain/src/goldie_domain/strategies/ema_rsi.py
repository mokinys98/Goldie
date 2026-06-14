from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..indicators import ema_series, rsi
from ..models import MarketContext, SignalDecision, SignalType
from ..strategy import common_guard, completed, trade_prices


class EmaRsiParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fast_ema_period: int = Field(default=9, ge=2, le=200)
    slow_ema_period: int = Field(default=21, ge=3, le=500)
    rsi_period: int = Field(default=14, ge=2, le=200)
    buy_rsi_max: Decimal = Field(default=Decimal("70"), ge=0, le=100)
    sell_rsi_min: Decimal = Field(default=Decimal("30"), ge=0, le=100)
    min_trend_points: Decimal = Field(default=Decimal("0"), ge=0, le=10000)
    require_crossover: bool = False

    @model_validator(mode="after")
    def validate_periods(self) -> "EmaRsiParameters":
        if self.fast_ema_period >= self.slow_ema_period:
            raise ValueError("fast_ema_period must be lower than slow_ema_period")
        return self


class EmaRsiStrategy:
    name = "ema_rsi"
    description = "Combines fast/slow EMA trend with an RSI threshold."
    parameters_model = EmaRsiParameters

    def required_candles(self, parameters: BaseModel) -> int:
        values = EmaRsiParameters.model_validate(parameters)
        crossover_extra = 1 if values.require_crossover else 0
        return max(values.slow_ema_period + crossover_extra, values.rsi_period + 1)

    def evaluate(self, context: MarketContext, config: Any) -> SignalDecision:
        candles = completed(context)
        parameters = EmaRsiParameters.model_validate(config.strategy.parameters)
        inputs: dict[str, str | int | bool | None] = {
            "strategy": self.name,
            "complete_candles": len(candles),
            "fast_ema_period": parameters.fast_ema_period,
            "slow_ema_period": parameters.slow_ema_period,
            "rsi_period": parameters.rsi_period,
            "require_crossover": parameters.require_crossover,
        }
        guard = common_guard(context, config, inputs)
        if isinstance(guard, SignalDecision):
            return guard
        if len(candles) < self.required_candles(parameters):
            return SignalDecision(
                signal=SignalType.NO_TRADE,
                reason_code="INSUFFICIENT_COMPLETED_CANDLES",
                **guard,
            )
        closes = [candle.close for candle in candles]
        fast_values = ema_series(closes, parameters.fast_ema_period)
        slow_values = ema_series(closes, parameters.slow_ema_period)
        fast = fast_values[-1]
        slow = slow_values[-1]
        rsi_value = rsi(closes, parameters.rsi_period)
        assert rsi_value is not None
        trend_points = (fast - slow) / context.point
        inputs.update(
            {
                "fast_ema": str(fast),
                "slow_ema": str(slow),
                "rsi": str(rsi_value),
                "trend_points": str(trend_points),
            }
        )
        crossed_up = crossed_down = True
        if parameters.require_crossover:
            previous_fast = fast_values[-2]
            previous_slow = slow_values[-2]
            crossed_up = previous_fast <= previous_slow and fast > slow
            crossed_down = previous_fast >= previous_slow and fast < slow
            inputs["crossed_up"] = crossed_up
            inputs["crossed_down"] = crossed_down
        if (
            trend_points >= parameters.min_trend_points
            and rsi_value <= parameters.buy_rsi_max
            and crossed_up
        ):
            signal, reason = SignalType.BUY, "EMA_RSI_BUY"
        elif (
            trend_points <= -parameters.min_trend_points
            and rsi_value >= parameters.sell_rsi_min
            and crossed_down
        ):
            signal, reason = SignalType.SELL, "EMA_RSI_SELL"
        else:
            return SignalDecision(
                signal=SignalType.NO_TRADE,
                reason_code="EMA_RSI_CONDITIONS_NOT_MET",
                **guard,
            )
        entry, stop_loss, take_profit = trade_prices(signal, context, config)
        return SignalDecision(
            signal=signal,
            reason_code=reason,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            **guard,
        )
