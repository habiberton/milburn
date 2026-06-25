import operator
from typing import Annotated, TypedDict, Any

class AgentState(TypedDict):
    run_id: str = ""
    prompt: str
    symbol: str
    frequency: str
    start: str
    end: str
    data_provider: str | None
    data_cache_key: str | None
    candle_summary: dict[str, Any] = {}
    validation_issues: list[dict[str, Any]] = []
    indicator_categories: list[str] = []
    selected_tools: list[str] = []
    tool_outputs: dict[str, Any] = {}
    chart_path: str | None
    model_profile: str
    report: dict[str, Any] | None
    consistency_check: dict[str, Any] | None
    warnings: Annotated[list[str], operator.add] = []
    traces: Annotated[list[dict[str, Any]], operator.add] = []

