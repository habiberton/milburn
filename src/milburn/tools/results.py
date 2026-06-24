from pydantic import BaseModel
from typing import Any

class ToolEvent(BaseModel):
    timestamp: str
    type: str
    value: float
    details: dict[str, Any] = {}

class ToolResult(BaseModel):
    name: str
    params: dict[str, Any]
    lookback: int
    latest: dict[str, Any]
    events: list[ToolEvent] = []
    warnings: list[str] = []