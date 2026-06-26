from collections.abc import Callable
from typing import Any
from milburn.tools.results import ToolResult
from milburn.tools.indicators import calculate_rsi, calculate_macd
from milburn.helper import print_json

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
        return self._tools.get(name)
    
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
    registry.register(ToolSpec(
        name="macd",
        description="Moving Average Convergence Divergence - trend/momentum indicator; "
                  "fast EMA(12) minus slow EMA(26), with a signal EMA(9) and histogram.",
        function=calculate_macd,
        default_params={"fast": 12, "slow": 26, "signal":9},
        required_columns=["close"],
    ))
    return registry

def tool_selection(indicator_categories: list[str], validation_issues: list[dict[str, Any]]) -> list[str]:
    toolset = {}
    for cat in indicator_categories:
        for tool in CATEGORY_TO_TOOLS.get(cat, []):
            toolset[tool] = None
    return list(toolset)

def tool_runner(toolset: list[str], frame: DataFrame, registry: ToolRegistry) -> dict[str, ToolResult]:    
    cols = frame.columns.tolist()
    results: dict[str, ToolResult] = {}
    for tool in toolset:
        spec = registry.get(tool)
        if not spec:
            continue
        if not all(col in cols for col in spec.required_columns):
            continue
        results[spec.name] = spec.function(frame, **spec.default_params)
    return results
        

    

