from collections import Counter, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from .config import BotConfiguration
from .models import CandleInput, MarketContext, SignalType
from .registry import get_strategy
from .shadow import calculate_position_size
from .strategy import Strategy


@dataclass(frozen=True)
class BacktestCosts:
    spread_points: Decimal = Decimal("2")
    fill_mode: str = "simulated"
    fee_maker: Decimal = Decimal("0")
    fee_taker: Decimal = Decimal("0")
    taker_slippage: Decimal = Decimal("0")
    slippage_small: Decimal = Decimal("0")
    slippage_medium: Decimal = Decimal("0")
    medium_impact: Decimal | None = None
    impact_model: str = "sqrt"
    model_sqrt_limit: Decimal = Decimal("1")
    limit_fill_timeout_s: int = 30
    min_qty_threshold: Decimal = Decimal("0")
    min_qty_check: bool = True
    slippage_points: Decimal | None = None
    commission_per_trade: Decimal = Decimal("0")


@dataclass(frozen=True)
class BacktestInstrument:
    point: Decimal
    tick_size: Decimal
    tick_value: Decimal
    volume_min: Decimal
    volume_max: Decimal
    volume_step: Decimal


@dataclass(frozen=True, slots=True)
class BacktestCandle:
    opened_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    tick_volume: int = 0
    is_complete: bool = True


@dataclass(frozen=True)
class BacktestTrade:
    direction: str
    signal_at: datetime
    opened_at: datetime
    closed_at: datetime
    entry_price: Decimal
    exit_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    volume: Decimal
    risk_amount: Decimal
    close_reason: str
    gross_pnl: Decimal
    commission: Decimal
    net_pnl: Decimal
    pnl_points: Decimal
    r_multiple: Decimal
    mfe_points: Decimal
    mae_points: Decimal
    duration_seconds: int


@dataclass(frozen=True)
class BacktestResult:
    trades: list[BacktestTrade]
    summary: dict
    reason_counts: dict[str, int]


class BacktestCancelled(Exception):
    pass


def _as_candle_input(candle: CandleInput | BacktestCandle) -> CandleInput:
    if isinstance(candle, CandleInput):
        return candle
    return CandleInput(
        opened_at=candle.opened_at,
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=candle.close,
        tick_volume=candle.tick_volume,
        is_complete=candle.is_complete,
    )


@dataclass
class _OpenPosition:
    direction: str
    signal_at: datetime
    opened_at: datetime
    entry_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    volume: Decimal
    risk_amount: Decimal
    mfe_points: Decimal = Decimal("0")
    mae_points: Decimal = Decimal("0")


@dataclass
class BacktestEngine:
    strategy: Strategy | None = field(default=None)

    def run(
        self,
        *,
        candles: list[CandleInput],
        config: BotConfiguration,
        instrument: BacktestInstrument,
        costs: BacktestCosts,
        initial_capital: Decimal,
        progress_callback: Callable[[int, int], bool] | None = None,
        use_prepared_strategy: bool = True,
        use_fast_strategy: bool = False,
        collect_reason_counts: bool = True,
    ) -> BacktestResult:
        ordered = sorted(
            (item for item in candles if item.is_complete),
            key=lambda item: item.opened_at,
        )
        return self.run_stream(
            candles=ordered,
            total_candles=len(ordered),
            config=config,
            instrument=instrument,
            costs=costs,
            initial_capital=initial_capital,
            progress_callback=progress_callback,
            use_prepared_strategy=use_prepared_strategy,
            use_fast_strategy=use_fast_strategy,
            collect_reason_counts=collect_reason_counts,
        )

    def run_stream(
        self,
        *,
        candles: Iterable[CandleInput | BacktestCandle],
        total_candles: int,
        config: BotConfiguration,
        instrument: BacktestInstrument,
        costs: BacktestCosts,
        initial_capital: Decimal,
        progress_callback: Callable[[int, int], bool] | None = None,
        use_prepared_strategy: bool = True,
        use_fast_strategy: bool = False,
        collect_reason_counts: bool = True,
    ) -> BacktestResult:
        reasons: Counter[str] = Counter()
        trades: list[BacktestTrade] = []
        position: _OpenPosition | None = None
        pending: tuple[str, object] | None = None
        balance = initial_capital
        expected_step = timedelta(minutes=1)
        strategy = self.strategy or get_strategy(config.strategy.name)
        evaluator_factory = None
        if use_fast_strategy:
            evaluator_factory = getattr(strategy, "create_fast_backtest_evaluator", None)
        if evaluator_factory is None:
            evaluator_factory = getattr(strategy, "create_backtest_evaluator", None)
        prepared = (
            evaluator_factory(
                config,
                point=instrument.point,
                spread_points=costs.spread_points,
            )
            if use_prepared_strategy and evaluator_factory is not None
            else None
        )
        history: deque[CandleInput | BacktestCandle] | None = None
        if prepared is None:
            parameters = strategy.parameters_model.model_validate(
                config.strategy.parameters
            )
            history = deque(maxlen=strategy.required_candles(parameters))
        previous: CandleInput | BacktestCandle | None = None
        last: CandleInput | BacktestCandle | None = None
        processed = 0

        for candle in candles:
            if not candle.is_complete:
                continue
            if progress_callback and not progress_callback(processed, total_candles):
                raise BacktestCancelled
            if previous and candle.opened_at - previous.opened_at > expected_step:
                if position is not None:
                    trade = self._close(
                        position,
                        closed_at=previous.opened_at + expected_step,
                        raw_exit=position.stop_loss,
                        close_reason="DATA_GAP",
                        instrument=instrument,
                        costs=costs,
                    )
                    trades.append(trade)
                    balance += trade.net_pnl
                    position = None
                pending = None
                if collect_reason_counts:
                    reasons["DATA_GAP"] += 1

            if position is None and pending is not None:
                direction, signal_at = pending
                fill_age = candle.opened_at - signal_at
                if fill_age.total_seconds() > costs.limit_fill_timeout_s:
                    if collect_reason_counts:
                        reasons["LIMIT_FILL_TIMEOUT"] += 1
                else:
                    position = self._open(
                        direction=direction,
                        signal_at=signal_at,
                        candle=candle,
                        config=config,
                        instrument=instrument,
                        costs=costs,
                        balance=balance,
                    )
                    if position is None:
                        if collect_reason_counts:
                            reasons["INVALID_POSITION_SIZE"] += 1
                pending = None

            if position is not None:
                closed = self._evaluate_position(
                    position,
                    candle=candle,
                    config=config,
                    instrument=instrument,
                    costs=costs,
                )
                if closed is not None:
                    trades.append(closed)
                    balance += closed.net_pnl
                    position = None

            observed_at = candle.opened_at + expected_step
            if prepared is not None:
                decision_signal, reason_code = prepared.evaluate(candle, observed_at)
            else:
                half_spread = costs.spread_points * instrument.point / Decimal("2")
                assert history is not None
                history.append(_as_candle_input(candle))
                decision = strategy.evaluate(
                    MarketContext(
                        observed_at=observed_at,
                        evaluated_at=observed_at,
                        bid=candle.close - half_spread,
                        ask=candle.close + half_spread,
                        point=instrument.point,
                        candles=list(history),
                    ),
                    config,
                )
                decision_signal = decision.signal
                reason_code = decision.reason_code
            if collect_reason_counts:
                reasons[reason_code] += 1
            if position is None and pending is None and decision_signal != SignalType.NO_TRADE:
                pending = (decision_signal.value, observed_at)
            elif decision_signal != SignalType.NO_TRADE:
                if collect_reason_counts:
                    reasons["OPEN_POSITION_EXISTS"] += 1
            previous = candle
            last = candle
            processed += 1

        if position is not None and last is not None:
            raw_exit = self._executable_close(position.direction, last.close, instrument, costs)
            trade = self._close(
                position,
                closed_at=last.opened_at + expected_step,
                raw_exit=raw_exit,
                close_reason="END_OF_DATA",
                instrument=instrument,
                costs=costs,
            )
            trades.append(trade)
        if progress_callback and not progress_callback(processed, total_candles):
            raise BacktestCancelled

        return BacktestResult(
            trades=trades,
            summary=self._summary(trades, initial_capital),
            reason_counts=dict(sorted(reasons.items())),
        )

    def _open(
        self,
        *,
        direction: str,
        signal_at: datetime,
        candle: CandleInput,
        config: BotConfiguration,
        instrument: BacktestInstrument,
        costs: BacktestCosts,
        balance: Decimal,
    ) -> _OpenPosition | None:
        half_spread = costs.spread_points * instrument.point / Decimal("2")
        slippage = self._slippage_amount(costs, instrument)
        entry = (
            candle.open + half_spread + slippage
            if direction == "BUY"
            else candle.open - half_spread - slippage
        )
        stop_distance = config.theoretical_trade.stop_loss_points * instrument.point
        take_distance = config.theoretical_trade.take_profit_points * instrument.point
        stop_loss = entry - stop_distance if direction == "BUY" else entry + stop_distance
        take_profit = entry + take_distance if direction == "BUY" else entry - take_distance
        size = calculate_position_size(
            balance=balance,
            equity=balance,
            risk_per_trade_pct=config.theoretical_trade.risk_per_trade_pct,
            entry_price=entry,
            stop_loss=stop_loss,
            tick_size=instrument.tick_size,
            tick_value=instrument.tick_value,
            volume_min=instrument.volume_min,
            volume_max=instrument.volume_max,
            volume_step=instrument.volume_step,
        )
        if size is None:
            return None
        if costs.min_qty_check and size.volume < costs.min_qty_threshold:
            return None
        return _OpenPosition(
            direction=direction,
            signal_at=signal_at,
            opened_at=candle.opened_at,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            volume=size.volume,
            risk_amount=size.risk_amount,
        )

    def _evaluate_position(
        self,
        position: _OpenPosition,
        *,
        candle: CandleInput,
        config: BotConfiguration,
        instrument: BacktestInstrument,
        costs: BacktestCosts,
    ) -> BacktestTrade | None:
        half_spread = costs.spread_points * instrument.point / Decimal("2")
        if position.direction == "BUY":
            favorable = candle.high - half_spread
            adverse = candle.low - half_spread
            stop_hit = adverse <= position.stop_loss
            take_hit = favorable >= position.take_profit
            move_high = (favorable - position.entry_price) / instrument.point
            move_low = (adverse - position.entry_price) / instrument.point
        else:
            favorable = candle.low + half_spread
            adverse = candle.high + half_spread
            stop_hit = adverse >= position.stop_loss
            take_hit = favorable <= position.take_profit
            move_high = (position.entry_price - favorable) / instrument.point
            move_low = (position.entry_price - adverse) / instrument.point
        position.mfe_points = max(position.mfe_points, move_high, Decimal("0"))
        position.mae_points = max(position.mae_points, -move_low, Decimal("0"))

        close_reason = None
        raw_exit = None
        if stop_hit:
            close_reason, raw_exit = "STOP_LOSS", position.stop_loss
        elif take_hit:
            close_reason, raw_exit = "TAKE_PROFIT", position.take_profit
        elif candle.opened_at >= position.opened_at + timedelta(
            minutes=config.theoretical_trade.max_trade_duration_minutes
        ):
            close_reason = "TIMEOUT"
            raw_exit = self._executable_close(
                position.direction, candle.close, instrument, costs
            )
        if close_reason is None or raw_exit is None:
            return None
        return self._close(
            position,
            closed_at=candle.opened_at + timedelta(minutes=1),
            raw_exit=raw_exit,
            close_reason=close_reason,
            instrument=instrument,
            costs=costs,
        )

    @staticmethod
    def _executable_close(
        direction: str,
        midpoint: Decimal,
        instrument: BacktestInstrument,
        costs: BacktestCosts,
    ) -> Decimal:
        half_spread = costs.spread_points * instrument.point / Decimal("2")
        return midpoint - half_spread if direction == "BUY" else midpoint + half_spread

    @staticmethod
    def _close(
        position: _OpenPosition,
        *,
        closed_at: datetime,
        raw_exit: Decimal,
        close_reason: str,
        instrument: BacktestInstrument,
        costs: BacktestCosts,
    ) -> BacktestTrade:
        slippage = BacktestEngine._slippage_amount(costs, instrument, position.volume)
        exit_price = (
            raw_exit - slippage if position.direction == "BUY" else raw_exit + slippage
        )
        pnl_points = (
            (exit_price - position.entry_price) / instrument.point
            if position.direction == "BUY"
            else (position.entry_price - exit_price) / instrument.point
        )
        gross = (
            pnl_points
            * instrument.point
            / instrument.tick_size
            * instrument.tick_value
            * position.volume
        )
        commission = BacktestEngine._commission_amount(
            costs=costs,
            entry_price=position.entry_price,
            exit_price=exit_price,
            volume=position.volume,
        )
        net = gross - commission
        return BacktestTrade(
            direction=position.direction,
            signal_at=position.signal_at,
            opened_at=position.opened_at,
            closed_at=closed_at,
            entry_price=position.entry_price,
            exit_price=exit_price,
            stop_loss=position.stop_loss,
            take_profit=position.take_profit,
            volume=position.volume,
            risk_amount=position.risk_amount,
            close_reason=close_reason,
            gross_pnl=gross,
            commission=commission,
            net_pnl=net,
            pnl_points=pnl_points,
            r_multiple=net / position.risk_amount,
            mfe_points=position.mfe_points,
            mae_points=position.mae_points,
            duration_seconds=int((closed_at - position.opened_at).total_seconds()),
        )

    @staticmethod
    def _summary(trades: list[BacktestTrade], initial_capital: Decimal) -> dict:
        wins = [trade for trade in trades if trade.net_pnl > 0]
        losses = [trade for trade in trades if trade.net_pnl < 0]
        gross_profit = sum((trade.net_pnl for trade in wins), Decimal("0"))
        gross_loss = abs(sum((trade.net_pnl for trade in losses), Decimal("0")))
        total_r = sum((trade.r_multiple for trade in trades), Decimal("0"))
        average_r = total_r / len(trades) if trades else None
        r_deviation = (
            (
                sum(
                    ((trade.r_multiple - average_r) ** 2 for trade in trades),
                    Decimal("0"),
                )
                / len(trades)
            ).sqrt()
            if trades and average_r is not None
            else None
        )
        downside_deviation = (
            (
                sum(
                    (min(trade.r_multiple, Decimal("0")) ** 2 for trade in trades),
                    Decimal("0"),
                )
                / len(trades)
            ).sqrt()
            if trades
            else None
        )
        cumulative = Decimal("0")
        peak = Decimal("0")
        max_drawdown = Decimal("0")
        max_losses = current_losses = 0
        max_wins = current_wins = 0
        equity_curve = []
        for trade in trades:
            cumulative += trade.net_pnl
            peak = max(peak, cumulative)
            max_drawdown = max(max_drawdown, peak - cumulative)
            equity_curve.append(
                {"time": trade.closed_at, "value": initial_capital + cumulative}
            )
            current_losses = current_losses + 1 if trade.net_pnl < 0 else 0
            current_wins = current_wins + 1 if trade.net_pnl > 0 else 0
            max_losses = max(max_losses, current_losses)
            max_wins = max(max_wins, current_wins)

        def average(values: list[Decimal]) -> Decimal | None:
            return sum(values, Decimal("0")) / len(values) if values else None

        return {
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": Decimal(len(wins) * 100) / len(trades) if trades else None,
            "average_win": average([trade.net_pnl for trade in wins]),
            "average_loss": average([trade.net_pnl for trade in losses]),
            "profit_factor": gross_profit / gross_loss if gross_loss else None,
            "expectancy": average([trade.net_pnl for trade in trades]),
            "expectancy_r": average([trade.r_multiple for trade in trades]),
            "total_r": total_r,
            "trade_sharpe": average_r / r_deviation if r_deviation else None,
            "trade_sortino": average_r / downside_deviation if downside_deviation else None,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss,
            "gross_pnl": sum((trade.gross_pnl for trade in trades), Decimal("0")),
            "commission": sum((trade.commission for trade in trades), Decimal("0")),
            "net_pnl": cumulative,
            "return_pct": cumulative * Decimal("100") / initial_capital,
            "final_equity": initial_capital + cumulative,
            "max_drawdown": max_drawdown,
            "max_drawdown_pct": max_drawdown * Decimal("100") / initial_capital,
            "max_consecutive_wins": max_wins,
            "max_consecutive_losses": max_losses,
            "average_duration_seconds": average(
                [Decimal(trade.duration_seconds) for trade in trades]
            ),
            "direction_breakdown": {
                direction: {
                    "trades": len(direction_trades),
                    "net_pnl": sum(
                        (trade.net_pnl for trade in direction_trades), Decimal("0")
                    ),
                    "win_rate": (
                        Decimal(
                            sum(1 for trade in direction_trades if trade.net_pnl > 0) * 100
                        )
                        / len(direction_trades)
                        if direction_trades
                        else None
                    ),
                }
                for direction in ("BUY", "SELL")
                if (direction_trades := [
                    trade for trade in trades if trade.direction == direction
                ])
            },
            "close_reason_counts": {
                reason: sum(1 for trade in trades if trade.close_reason == reason)
                for reason in sorted({trade.close_reason for trade in trades})
            },
            "year_breakdown": {
                year: {
                    "trades": len(period_trades),
                    "net_pnl": sum(
                        (trade.net_pnl for trade in period_trades), Decimal("0")
                    ),
                }
                for year in sorted({trade.closed_at.strftime("%Y") for trade in trades})
                if (period_trades := [
                    trade for trade in trades if trade.closed_at.strftime("%Y") == year
                ])
            },
            "month_breakdown": {
                month: {
                    "trades": len(period_trades),
                    "net_pnl": sum(
                        (trade.net_pnl for trade in period_trades), Decimal("0")
                    ),
                }
                for month in sorted({trade.closed_at.strftime("%Y-%m") for trade in trades})
                if (period_trades := [
                    trade for trade in trades if trade.closed_at.strftime("%Y-%m") == month
                ])
            },
            "equity_curve": equity_curve,
        }

    @staticmethod
    def _slippage_amount(
        costs: BacktestCosts,
        instrument: BacktestInstrument,
        volume: Decimal | None = None,
    ) -> Decimal:
        if costs.fill_mode == "perfect":
            return Decimal("0")
        if costs.slippage_points is not None:
            return costs.slippage_points * instrument.point
        base = max(costs.taker_slippage, costs.slippage_small)
        medium_impact = (
            costs.medium_impact
            if costs.medium_impact is not None
            else costs.slippage_medium
        )
        if costs.impact_model != "sqrt" or volume is None or instrument.volume_min <= 0:
            return base + medium_impact
        ratio = max(volume / instrument.volume_min, Decimal("1"))
        multiplier = ratio.sqrt() - Decimal("1")
        multiplier = min(multiplier, costs.model_sqrt_limit)
        return base + (medium_impact * multiplier)

    @staticmethod
    def _commission_amount(
        *,
        costs: BacktestCosts,
        entry_price: Decimal,
        exit_price: Decimal,
        volume: Decimal,
    ) -> Decimal:
        if costs.fill_mode == "perfect":
            return Decimal("0")
        if costs.commission_per_trade:
            return costs.commission_per_trade
        if not costs.fee_taker:
            return Decimal("0")
        return (entry_price + exit_price) * volume * costs.fee_taker
