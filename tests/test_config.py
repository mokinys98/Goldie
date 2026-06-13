from decimal import Decimal

import pytest
from goldie_domain import BotConfiguration
from pydantic import ValidationError


def test_unknown_config_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        BotConfiguration.model_validate({"unknown": True})


def test_only_m1_is_supported_in_local_mvp() -> None:
    with pytest.raises(ValidationError):
        BotConfiguration.model_validate({"market": {"symbol": "XAUUSD", "timeframe": "M5"}})


def test_shadow_defaults_are_added_to_legacy_configuration() -> None:
    config = BotConfiguration.model_validate(
        {
            "theoretical_trade": {
                "stop_loss_points": 70,
                "take_profit_points": 100,
            }
        }
    )

    assert config.theoretical_trade.risk_per_trade_pct == Decimal("0.25")
    assert config.theoretical_trade.max_trade_duration_minutes == 5
    assert config.theoretical_trade.max_open_shadow_positions == 1
