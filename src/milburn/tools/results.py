from pydantic import BaseModel, field_validator
from typing import Any

class ToolEvent(BaseModel):
    timestamp: str
    type: str
    value: float
    details: dict[str, Any] = {}

    @field_validator("value")
    @classmethod
    def round_value(cls, val: float) -> float:
        return round(val, 3)

class ToolResult(BaseModel):
    name: str
    params: dict[str, Any]
    lookback: int
    latest: dict[str, Any]
    events: list[ToolEvent] = []
    warnings: list[str] = []