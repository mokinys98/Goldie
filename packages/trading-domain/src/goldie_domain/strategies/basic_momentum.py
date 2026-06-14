from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..models import MarketContext, SignalDecision, SignalType
from ..strategy import common_guard, completed, trade_prices


class BasicMomentumParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lookback_candles: int = Field(default=5, ge=2, le=100)
    min_momentum_points: Decimal = Field(default=Decimal("50"), gt=0, le=10000)


class BasicMomentumStrategy:
    name = "basic_momentum"
    description = "Signals when close-to-close momentum exceeds a points threshold."
    parameters_model = BasicMomentumParameters

    def required_candles(self, parameters: BaseModel) -> int:
        values = BasicMomentumParameters.model_validate(parameters)
        return values.lookback_candles + 1

    def evaluate(self, context: MarketContext, config: Any) -> SignalDecision:
        candles = completed(context)
        parameters = BasicMomentumParameters.model_validate(config.strategy.parameters)
        inputs: dict[str, str | int | bool | None] = {
            "strategy": self.name,
            "lookback_candles": parameters.lookback_candles,
            "complete_candles": len(candles),
            "symbol": config.market.symbol,
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
        baseline = candles[-(parameters.lookback_candles + 1)].close
        latest = candles[-1].close
        momentum_points = (latest - baseline) / context.point
        inputs["momentum_points"] = str(momentum_points)
        if momentum_points >= parameters.min_momentum_points:
            signal, reason = SignalType.BUY, "MOMENTUM_UP"
        elif momentum_points <= -parameters.min_momentum_points:
            signal, reason = SignalType.SELL, "MOMENTUM_DOWN"
        else:
            return SignalDecision(
                signal=SignalType.NO_TRADE,
                reason_code="MOMENTUM_BELOW_THRESHOLD",
                momentum_points=momentum_points,
                **guard,
            )
        entry, stop_loss, take_profit = trade_prices(signal, context, config)
        return SignalDecision(
            signal=signal,
            reason_code=reason,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            momentum_points=momentum_points,
            **guard,
        )
