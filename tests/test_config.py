import pytest
from goldie_domain import BotConfiguration
from pydantic import ValidationError


def test_unknown_config_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        BotConfiguration.model_validate({"unknown": True})


def test_only_m1_is_supported_in_local_mvp() -> None:
    with pytest.raises(ValidationError):
        BotConfiguration.model_validate({"market": {"symbol": "XAUUSD", "timeframe": "M5"}})
