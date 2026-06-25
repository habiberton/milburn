from collections.abc import Callable
from typing import Any
from milburn.tools.results import ToolResult
from milburn.tools.indicators import calculate_rsi

from pydantic import BaseModel
from pandas import DataFrame

CATEGORY_TO_TOOLS: dict[str, list[str]] = {
    "trend": [
        "sma", "sma_cross", "ema"
    ],
    "momentum": [
        "rsi", "macd"
    ],
    "volatility": [
        "atr", "bollinger_bands"
    ],
    "volume": [
        "volume_stats"
    ],
    "levels": [
        "swing_points", "support_resistance"
    ]
}

class ToolSpec(BaseModel):
    name: str
    description: str 
    function: Callable[..., ToolResult]
    default_params: dict[str, Any] = {}
    required_columns: list[str] = ["close"]

class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
    
    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Tool already registered: {spec.name}")
        self._tools[spec.name] = spec
    
    def get(self, name: str) -> ToolSpec:
        return self._tools[name]
    
    def all(self) -> list[ToolSpec]:
        return list(self._tools.values())

def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ToolSpec(
        name="rsi",
        description="Relative Strength Index - momentum oscillator (0-100).",
        function=calculate_rsi,
        default_params={"period": 14},
        required_columns=["close"],
    ))
    return registry

def tool_selection(indicator_categories: list[str], validation_issues: list[dict[str, Any]]) -> list[str]:
    toolset = {}
    for cat in indicator_categories:
        for tool in CATEGORY_TO_TOOLS.get(cat, []):
            toolset[tool] = None
    return list(toolset)

# def tool_runner(toolset: list[str], frame: DataFrame) -> dict[str, ToolResult]:
#     registry = build_registry()
#     tools
#     for tool in toolset:
#         tools.update(registry.get(tool, []))
    
#     cols = frame.columns.tolist()
#     result: list[ToolResult] = []
#     for t in tools:
#         if not t.required_columns.subset(cols):
#             continue
        
        

    

