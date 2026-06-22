from typing import Any

from pydantic import BaseModel

from .strategies import (
    BasicMomentumStrategy,
    BollingerEmaRsiMeanReversionStrategy,
    BollingerMomentumBreakoutStrategy,
    BollingerRsiMeanReversionStrategy,
    EmaAtrTrendStrategy,
    EmaMomentumBreakoutStrategy,
    EmaRsiStrategy,
    PineBollingerRsiStochStrategy,
    RangeBreakScalperStrategy,
)
from .strategy import Strategy

_STRATEGIES: dict[str, Strategy] = {}


def register_strategy(strategy: Strategy) -> None:
    if strategy.name in _STRATEGIES:
        raise ValueError(f"Strategy already registered: {strategy.name}")
    _STRATEGIES[strategy.name] = strategy


def get_strategy(name: str) -> Strategy:
    try:
        return _STRATEGIES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown strategy: {name}") from exc


def validate_strategy_parameters(name: str, parameters: dict[str, Any]) -> BaseModel:
    return get_strategy(name).parameters_model.model_validate(parameters)


def _parameter_metadata(property_schema: dict[str, Any]) -> dict[str, Any]:
    metadata = {
        key: value
        for key, value in property_schema.items()
        if key
        in {
            "title",
            "description",
            "type",
            "minimum",
            "maximum",
            "exclusiveMinimum",
            "default",
            "unit",
            "impact",
            "enum",
            "optimization_minimum",
            "optimization_maximum",
        }
    }
    if "type" not in metadata:
        numeric_schema = next(
            (
                option
                for option in property_schema.get("anyOf", [])
                if option.get("type") in {"integer", "number"}
            ),
            None,
        )
        if numeric_schema:
            metadata.update(
                {
                    key: value
                    for key, value in numeric_schema.items()
                    if key in {"type", "minimum", "maximum", "exclusiveMinimum"}
                }
            )
    return metadata


def strategy_catalog() -> list[dict[str, Any]]:
    result = []
    for strategy in _STRATEGIES.values():
        schema = strategy.parameters_model.model_json_schema()
        defaults = strategy.parameters_model().model_dump(mode="json")
        result.append(
            {
                "name": strategy.name,
                "description": strategy.description,
                "required_candles": strategy.required_candles(strategy.parameters_model()),
                "parameters": {
                    name: _parameter_metadata(property_schema)
                    for name, property_schema in schema.get("properties", {}).items()
                },
                "defaults": defaults,
            }
        )
    return result


register_strategy(BasicMomentumStrategy())
register_strategy(EmaRsiStrategy())
register_strategy(BollingerRsiMeanReversionStrategy())
register_strategy(EmaMomentumBreakoutStrategy())
register_strategy(EmaAtrTrendStrategy())
register_strategy(BollingerMomentumBreakoutStrategy())
register_strategy(BollingerEmaRsiMeanReversionStrategy())
register_strategy(RangeBreakScalperStrategy())
register_strategy(PineBollingerRsiStochStrategy())
