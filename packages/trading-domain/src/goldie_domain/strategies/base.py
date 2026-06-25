from collections import deque
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from ..models import CandleInput, MarketContext, SignalDecision, SignalType
from ..strategy import BacktestGuards, common_guard, completed, trade_prices


class ReplayBacktestEvaluator:
    def __init__(
        self,
        *,
        strategy: Any,
        config: Any,
        required_candles: int,
        point: Decimal,
        spread_points: Decimal,
    ) -> None:
        self.strategy = strategy
        self.config = config
        self.point = point
        self.half_spread = spread_points * point / Decimal("2")
        self.guards = BacktestGuards.from_config(config, spread_points=spread_points)
        self.candles: deque[CandleInput] = deque(maxlen=required_candles)

    def evaluate(self, candle: CandleInput, observed_at: datetime) -> tuple[SignalType, str]:
        if not isinstance(candle, CandleInput):
            candle = CandleInput(
                opened_at=candle.opened_at,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                tick_volume=candle.tick_volume,
                is_complete=candle.is_complete,
            )
        self.candles.append(candle)
        rejection = self.guards.rejection_reason(observed_at)
        if rejection:
            return SignalType.NO_TRADE, rejection
        decision = self.strategy.evaluate(
            MarketContext(
                observed_at=observed_at,
                evaluated_at=observed_at,
                bid=candle.close - self.half_spread,
                ask=candle.close + self.half_spread,
                point=self.point,
                candles=list(self.candles),
            ),
            self.config,
        )
        return decision.signal, decision.reason_code


class FastGuardedEvaluator:
    def __init__(self, *, guards: BacktestGuards, required: int) -> None:
        self.guards = guards
        self.required = required
        self.count = 0
        self.condition_counts: dict[str, dict[str, int]] = {}
        self.skip_guards = (
            guards.spread_points <= guards.max_spread_points
            and guards.timezone.key == "UTC"
            and guards.start_time == datetime.min.time()
            and guards.end_time >= datetime.max.time().replace(microsecond=0)
        )

    def rejection(self, observed_at: datetime) -> str | None:
        return None if self.skip_guards else self.guards.rejection_reason(observed_at)

    def count_condition(self, name: str, passed: bool) -> bool:
        counts = self.condition_counts.setdefault(name, {"evaluated": 0, "passed": 0})
        counts["evaluated"] += 1
        if passed:
            counts["passed"] += 1
        return passed

    def diagnostics(self) -> dict[str, dict[str, dict[str, int]]]:
        return {"condition_counts": self.condition_counts}


class PreparedStrategy:
    parameters_model: type[BaseModel]
    name: str

    def create_backtest_evaluator(
        self, config: Any, *, point: Decimal, spread_points: Decimal
    ) -> ReplayBacktestEvaluator:
        parameters = self.parameters_model.model_validate(config.strategy.parameters)
        return ReplayBacktestEvaluator(
            strategy=self,
            config=config,
            required_candles=self.required_candles(parameters),
            point=point,
            spread_points=spread_points,
        )

    def _start(
        self, context: MarketContext, config: Any
    ) -> tuple[list[CandleInput], BaseModel, dict[str, Any], dict[str, Any] | SignalDecision]:
        candles = completed(context)
        parameters = self.parameters_model.model_validate(config.strategy.parameters)
        inputs: dict[str, Any] = {"strategy": self.name, "complete_candles": len(candles)}
        return candles, parameters, inputs, common_guard(context, config, inputs)

    def _finish(
        self,
        signal: SignalType,
        reason: str,
        context: MarketContext,
        config: Any,
        guard: dict[str, Any],
    ) -> SignalDecision:
        if signal == SignalType.NO_TRADE:
            return SignalDecision(signal=signal, reason_code=reason, **guard)
        entry, stop_loss, take_profit = trade_prices(signal, context, config)
        return SignalDecision(
            signal=signal,
            reason_code=reason,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            **guard,
        )
