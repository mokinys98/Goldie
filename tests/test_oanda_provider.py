from datetime import UTC, datetime
from decimal import Decimal

from goldie_collector.provider import OandaProvider


def test_oanda_price_message_is_normalized() -> None:
    quote = OandaProvider.parse_price_message(
        {
            "type": "PRICE",
            "status": "tradeable",
            "time": "2026-06-12T10:15:30.123456789Z",
            "bids": [{"price": "4321.100"}],
            "asks": [{"price": "4321.250"}],
        }
    )
    assert quote is not None
    assert quote.bid == Decimal("4321.100")
    assert quote.ask == Decimal("4321.250")
    assert quote.observed_at.tzinfo is not None


def test_non_tradeable_oanda_price_is_ignored() -> None:
    assert (
        OandaProvider.parse_price_message(
            {
                "type": "PRICE",
                "status": "non-tradeable",
                "time": "2026-06-12T10:15:30Z",
                "bids": [{"price": "4321.100"}],
                "asks": [{"price": "4321.250"}],
            }
        )
        is None
    )


def test_only_complete_midpoint_candles_are_normalized() -> None:
    candle = OandaProvider.parse_candle(
        {
            "complete": True,
            "time": "2026-06-12T10:15:00Z",
            "volume": 42,
            "mid": {
                "o": "4321.10",
                "h": "4321.50",
                "l": "4320.90",
                "c": "4321.40",
            },
        }
    )
    assert candle is not None
    assert candle.close == Decimal("4321.40")
    assert OandaProvider.parse_candle({"complete": False}) is None


def test_weekend_is_reported_as_market_closed() -> None:
    provider = object.__new__(OandaProvider)
    assert provider.market_is_closed(datetime(2026, 6, 13, 12, tzinfo=UTC))
    assert not provider.market_is_closed(datetime(2026, 6, 12, 12, tzinfo=UTC))
