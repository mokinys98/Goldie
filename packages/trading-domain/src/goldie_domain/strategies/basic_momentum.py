from collections import deque
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..models import CandleInput, MarketContext, SignalDecision, SignalType
from ..strategy import BacktestGuards
from .base import PreparedStrategy


class BasicMomentumParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lookback_candles: int = Field(
        default=5,
        ge=2,
        le=100,
        description="Užbaigtų žvakių skaičius kainos pokyčiui apskaičiuoti.",
        json_schema_extra={
            "unit": "candles",
            "impact": "Didinant signalas vertina ilgesnį ir lėtesnį judėjimą.",
        },
    )
    min_momentum_points: Decimal = Field(
        default=Decimal("50"),
        gt=0,
        le=10000,
        description="Mažiausias kainos pokytis, reikalingas BUY arba SELL signalui.",
        json_schema_extra={
            "unit": "points",
            "impact": "Didinant signalų bus mažiau, bet reikės stipresnio judėjimo.",
        },
    )


class BasicMomentumStrategy(PreparedStrategy):
    name = "basic_momentum"
    description = "Signals when close-to-close momentum exceeds a points threshold."
    parameters_model = BasicMomentumParameters

    def required_candles(self, parameters: BaseModel) -> int:
        values = BasicMomentumParameters.model_validate(parameters)
        return values.lookback_candles + 1

    def create_backtest_evaluator(
        self,
        config: Any,
        *,
        point: Decimal,
        spread_points: Decimal,
    ) -> "_BasicMomentumBacktestEvaluator":
        parameters = BasicMomentumParameters.model_validate(config.strategy.parameters)
        return _BasicMomentumBacktestEvaluator(
            lookback_candles=parameters.lookback_candles,
            min_momentum_points=parameters.min_momentum_points,
            point=point,
            guards=BacktestGuards.from_config(config, spread_points=spread_points),
        )

    def evaluate(self, context: MarketContext, config: Any) -> SignalDecision:
        candles, raw, inputs, guard = self._start(context, config)
        parameters = BasicMomentumParameters.model_validate(raw)
        inputs.update(
            lookback_candles=parameters.lookback_candles,
            symbol=config.market.symbol,
        )
        if isinstance(guard, SignalDecision):
            return guard
        if len(candles) < self.required_candles(parameters):
            return self._finish(
                SignalType.NO_TRADE,
                "INSUFFICIENT_COMPLETED_CANDLES",
                context,
                config,
                guard,
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
            decision = self._finish(
                SignalType.NO_TRADE,
                "MOMENTUM_BELOW_THRESHOLD",
                context,
                config,
                guard,
            )
            decision.momentum_points = momentum_points
            return decision
        decision = self._finish(signal, reason, context, config, guard)
        decision.momentum_points = momentum_points
        return decision


class _BasicMomentumBacktestEvaluator:
    def __init__(
        self,
        *,
        lookback_candles: int,
        min_momentum_points: Decimal,
        point: Decimal,
        guards: BacktestGuards,
    ) -> None:
        self.required_candles = lookback_candles + 1
        self.min_momentum_points = min_momentum_points
        self.point = point
        self.guards = guards
        self.closes: deque[Decimal] = deque(maxlen=self.required_candles)

    def evaluate(
        self,
        candle: CandleInput,
        observed_at: datetime,
    ) -> tuple[SignalType, str]:
        self.closes.append(candle.close)
        rejection = self.guards.rejection_reason(observed_at)
        if rejection:
            return SignalType.NO_TRADE, rejection
        if len(self.closes) < self.required_candles:
            return (
                SignalType.NO_TRADE,
                "INSUFFICIENT_COMPLETED_CANDLES",
            )
        momentum_points = (self.closes[-1] - self.closes[0]) / self.point
        if momentum_points >= self.min_momentum_points:
            return SignalType.BUY, "MOMENTUM_UP"
        if momentum_points <= -self.min_momentum_points:
            return SignalType.SELL, "MOMENTUM_DOWN"
        return SignalType.NO_TRADE, "MOMENTUM_BELOW_THRESHOLD"
