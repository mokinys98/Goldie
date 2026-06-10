from datetime import UTC
from zoneinfo import ZoneInfo

from .config import BotConfiguration
from .models import MarketContext, SignalDecision, SignalType


class BasicMomentumStrategy:
    def evaluate(self, context: MarketContext, config: BotConfiguration) -> SignalDecision:
        complete = sorted(
            (candle for candle in context.candles if candle.is_complete),
            key=lambda candle: candle.opened_at,
        )
        spread_points = (context.ask - context.bid) / context.point
        common = {
            "observed_at": context.observed_at,
            "spread_points": spread_points,
            "inputs": {
                "lookback_candles": config.strategy.lookback_candles,
                "complete_candles": len(complete),
                "symbol": config.market.symbol,
            },
        }

        now = context.observed_at
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        age = (datetime_now_utc() - now.astimezone(UTC)).total_seconds()
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

        lookback = config.strategy.lookback_candles
        if len(complete) < lookback + 1:
            return SignalDecision(
                signal=SignalType.NO_TRADE,
                reason_code="INSUFFICIENT_COMPLETED_CANDLES",
                **common,
            )

        baseline = complete[-(lookback + 1)].close
        latest = complete[-1].close
        momentum_points = (latest - baseline) / context.point
        threshold = config.strategy.min_momentum_points

        if momentum_points >= threshold:
            signal = SignalType.BUY
            reason = "MOMENTUM_UP"
            entry = context.ask
            stop_loss = entry - config.theoretical_trade.stop_loss_points * context.point
            take_profit = entry + config.theoretical_trade.take_profit_points * context.point
        elif momentum_points <= -threshold:
            signal = SignalType.SELL
            reason = "MOMENTUM_DOWN"
            entry = context.bid
            stop_loss = entry + config.theoretical_trade.stop_loss_points * context.point
            take_profit = entry - config.theoretical_trade.take_profit_points * context.point
        else:
            signal = SignalType.NO_TRADE
            reason = "MOMENTUM_BELOW_THRESHOLD"
            entry = stop_loss = take_profit = None

        return SignalDecision(
            signal=signal,
            reason_code=reason,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            momentum_points=momentum_points,
            **common,
        )


def datetime_now_utc():
    from datetime import datetime

    return datetime.now(UTC)
