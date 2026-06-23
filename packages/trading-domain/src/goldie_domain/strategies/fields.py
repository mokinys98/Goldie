from decimal import Decimal
from typing import Any

from pydantic import Field


def decimal_parameter(
    default: str,
    *,
    ge: int | None = None,
    gt: int | None = None,
    le: int,
    description: str,
    unit: str,
    impact: str,
    optimization_minimum: str | int | None = None,
    optimization_maximum: str | int | None = None,
) -> Any:
    extra: dict[str, Any] = {"unit": unit, "impact": impact}
    if optimization_minimum is not None:
        extra["optimization_minimum"] = optimization_minimum
    if optimization_maximum is not None:
        extra["optimization_maximum"] = optimization_maximum
    return Field(
        default=Decimal(default),
        ge=ge,
        gt=gt,
        le=le,
        description=description,
        json_schema_extra=extra,
    )
